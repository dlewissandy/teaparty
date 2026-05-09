"""Historical-telemetry backfill (Issue #431).

Walks each project's ``.teaparty/jobs/job-*/`` tree, parses the
per-phase orchestrator stream JSONL files, and emits the Issue #431
event types (``JOB_CREATED``, ``MESSAGE_RECORDED``, ``TOOL_CALL_COMPLETE``,
``DISPATCH_EDGE``) for runs that pre-date the in-process emission paths
landing on the bus.

The backfill is idempotent. It never relies on file-system markers —
the events table itself is the dedupe source. A row already exists in
``session_messages`` for ``(session_id, message_id)``? Skip. A
``JOB_CREATED`` event already exists for ``job_id``? Skip. Running
twice is a no-op.

Source file layout (matches the canonical spec):
    {project_root}/.teaparty/jobs/job-{short_id}--{slug}/
        job.json                 (created_at, status, branch, issue)
        PROMPT.txt               (full prompt text)
        .intent-stream.jsonl     (orchestrator stream — intent phase)
        .plan-stream.jsonl       (orchestrator stream — plan phase)
        .exec-stream.jsonl       (orchestrator stream — exec phase)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from teaparty.telemetry import events as E
from teaparty.telemetry import (
    record as _record,
    record_event,
    record_message,
    record_dispatch_edge,
)

_log = logging.getLogger('teaparty.telemetry.backfill')


# Stream files emitted by the CFA engine, one per phase.
PHASE_STREAM_FILES = (
    ('intent', '.intent-stream.jsonl'),
    ('plan',   '.plan-stream.jsonl'),
    ('exec',   '.exec-stream.jsonl'),
)


# Session-id matchers used for child-of-Delegate hex extraction (the
# parent's stream contains tool_use(Delegate) → tool_result whose body
# carries the child's dispatch hex either as ``conversation_id``:
# ``"dispatch:<hex>"`` or as a session branch ``session/<hex>``).
_DISPATCH_HEX_RE = re.compile(r'dispatch:([0-9a-f]{8,16})')
_SESSION_BRANCH_HEX_RE = re.compile(r'session/([0-9a-f]{8,16})')


def _is_delegate_tool(name: str | None) -> bool:
    return bool(name) and name.endswith('__Delegate')


def _parse_dispatch_hex(text: str | None) -> str | None:
    if not text:
        return None
    m = _DISPATCH_HEX_RE.search(text)
    if m:
        return m.group(1)
    m = _SESSION_BRANCH_HEX_RE.search(text)
    return m.group(1) if m else None


def _parse_job_dir_name(name: str) -> tuple[str, str]:
    """Split ``job-{short}--{slug}`` into ``(short, slug)``."""
    body = name[len('job-'):] if name.startswith('job-') else name
    short, _, slug = body.partition('--')
    return short, slug


def _content_blocks(rec: dict) -> list[dict]:
    msg = rec.get('message') or {}
    content = msg.get('content') or []
    return [c for c in content if isinstance(c, dict)]


def _iter_jsonl(path: Path) -> Iterator[dict]:
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _job_already_recorded(job_id: str) -> bool:
    conn = _record._ensure_conn()  # noqa: SLF001
    if conn is None:
        return False
    with _record._lock:  # noqa: SLF001
        row = conn.execute(
            "SELECT 1 FROM events WHERE event_type='job_created' "
            "AND json_extract(data, '$.job_id') = ? LIMIT 1",
            (job_id,),
        ).fetchone()
    return row is not None


def _dispatch_edge_already_recorded(
    parent_session_id: str, child_session_id: str,
) -> bool:
    conn = _record._ensure_conn()  # noqa: SLF001
    if conn is None:
        return False
    with _record._lock:  # noqa: SLF001
        row = conn.execute(
            'SELECT 1 FROM dispatch_edges '
            'WHERE parent_session_id = ? AND child_session_id = ? LIMIT 1',
            (parent_session_id, child_session_id),
        ).fetchone()
    return row is not None


def _session_already_backfilled(session_id: str) -> bool:
    """Skip a stream's TURN_COMPLETE / TOOL_CALL_COMPLETE emission when
    its session was already backfilled. Streams are static files, so
    once processed they don't need to be re-processed; the events
    table itself answers the dedupe question."""
    conn = _record._ensure_conn()  # noqa: SLF001
    if conn is None:
        return False
    with _record._lock:  # noqa: SLF001
        row = conn.execute(
            "SELECT 1 FROM events WHERE session_id = ? "
            "AND event_type IN ('turn_complete', 'tool_call_complete') "
            "LIMIT 1",
            (session_id,),
        ).fetchone()
    return row is not None


@dataclass
class BackfillCounts:
    """Per-run row counts. Aggregated across job dirs by ``backfill_all``."""
    jobs_inserted: int = 0
    jobs_skipped: int = 0
    turns_inserted: int = 0
    messages_inserted: int = 0
    messages_skipped: int = 0
    tool_calls_inserted: int = 0
    dispatch_edges_inserted: int = 0
    dispatch_edges_skipped: int = 0
    streams_parsed: int = 0
    job_dirs_visited: int = 0

    def merge(self, other: 'BackfillCounts') -> None:
        self.jobs_inserted += other.jobs_inserted
        self.jobs_skipped += other.jobs_skipped
        self.turns_inserted += other.turns_inserted
        self.messages_inserted += other.messages_inserted
        self.messages_skipped += other.messages_skipped
        self.tool_calls_inserted += other.tool_calls_inserted
        self.dispatch_edges_inserted += other.dispatch_edges_inserted
        self.dispatch_edges_skipped += other.dispatch_edges_skipped
        self.streams_parsed += other.streams_parsed
        self.job_dirs_visited += other.job_dirs_visited


def backfill_job_metadata(job_dir: Path, project: str) -> BackfillCounts:
    """Emit a ``JOB_CREATED`` event for one job dir if absent.

    Reads ``PROMPT.txt`` and ``job.json`` for metadata. Idempotent —
    a job whose ``job_id`` already has a JOB_CREATED row is skipped.
    """
    counts = BackfillCounts()
    short, slug = _parse_job_dir_name(job_dir.name)
    job_id = f'job-{short}'
    if _job_already_recorded(job_id):
        counts.jobs_skipped += 1
        return counts

    prompt_text = ''
    prompt_hash = ''
    prompt_bytes = 0
    prompt_path = job_dir / 'PROMPT.txt'
    if prompt_path.exists():
        try:
            prompt_text = prompt_path.read_text(errors='replace')
            prompt_hash = hashlib.sha1(
                prompt_text.encode('utf-8', errors='replace'),
            ).hexdigest()
            prompt_bytes = len(prompt_text)
        except OSError:
            pass

    meta: dict = {}
    job_json_path = job_dir / 'job.json'
    if job_json_path.exists():
        try:
            meta = json.loads(job_json_path.read_text())
        except (OSError, json.JSONDecodeError):
            meta = {}

    record_event(
        E.JOB_CREATED,
        scope=project,
        session_id=short,
        data={
            'job_id':         job_id,
            'project':        project,
            'slug':           slug,
            'classification': '',
            'prompt_text':    prompt_text,
            'prompt_hash':    prompt_hash,
            'prompt_bytes':   prompt_bytes,
            'branch':         meta.get('branch') or '',
            'status':         meta.get('status') or '',
            'created_at':     meta.get('created_at') or '',
            'issue':          meta.get('issue'),
            'backfilled':     True,
        },
        job_id=job_id,
    )
    counts.jobs_inserted += 1
    return counts


def backfill_stream_file(
    path: Path,
    *,
    job_id: str,
    project: str,
) -> BackfillCounts:
    """Parse one stream JSONL file and emit MESSAGE_RECORDED /
    TOOL_CALL_COMPLETE / DISPATCH_EDGE rows.

    The session_id used for emitted rows is the SDK uuid from the
    first ``system/init`` record in the stream — that's what the
    canonical spec uses to cross-link to claude-home jsonl files.
    """
    counts = BackfillCounts()
    counts.streams_parsed += 1
    init_uuid: str | None = None
    init_model: str | None = None
    pending_tools: dict[str, dict] = {}
    pending_delegates: dict[str, dict] = {}
    # Set after the first system/init: True iff this session already
    # has TURN_COMPLETE rows in the events table, in which case we
    # skip non-message emissions to keep the second pass a no-op.
    session_already_done: bool = False

    for rec in _iter_jsonl(path):
        rtype = rec.get('type')
        if rtype == 'system' and rec.get('subtype') == 'init':
            first_init = init_uuid is None
            if first_init:
                init_uuid = rec.get('session_id')
                if init_uuid:
                    session_already_done = _session_already_backfilled(
                        init_uuid,
                    )
            if rec.get('model'):
                init_model = rec.get('model')
            # Issue #431 — emit a TURN_START event for the launch the
            # init record represents. Without this, queries that count
            # turn_starts per session (the spec's resume-signal
            # query) produce zero for backfilled jobs even after
            # turn_complete is emitted from the matching result.
            if init_uuid and not session_already_done:
                record_event(
                    E.TURN_START,
                    scope=project,
                    session_id=init_uuid,
                    ts=rec.get('timestamp'),
                    data={
                        'trigger':              'new',
                        'claude_session':       init_uuid,
                        'model':                init_model or '',
                        'resume_from_phase':    None,
                        'backfilled':           True,
                    },
                    job_id=job_id,
                )
            continue

        # Without a session uuid we can't key MESSAGE_RECORDED — skip
        # any records that arrive before system/init.
        if init_uuid is None:
            continue

        if rtype == 'result':
            if session_already_done:
                continue
            # Each ``result`` record is the end-of-call SDK report and
            # is the authoritative cost source for historical runs.
            # Emit a TURN_COMPLETE event with the same field shape as
            # the live launcher emission so per-job cost rollups in
            # job_cost_summary / session_summary actually contain cost
            # for backfilled jobs.
            usage = rec.get('usage') or {}
            cc = usage.get('cache_creation') or {}
            c5 = cc.get('ephemeral_5m_input_tokens') or 0
            c1 = cc.get('ephemeral_1h_input_tokens') or 0
            data = {
                'cost_usd':           rec.get('total_cost_usd') or 0.0,
                'duration_ms':        rec.get('duration_ms'),
                'duration_api_ms':    rec.get('duration_api_ms'),
                'num_turns':          rec.get('num_turns') or 0,
                'input_tokens':       usage.get('input_tokens'),
                'output_tokens':      usage.get('output_tokens'),
                'cache_read_tokens':  usage.get('cache_read_input_tokens'),
                'cache_create_tokens': c5 + c1,
                'cache_5m_tokens':    c5,
                'cache_1h_tokens':    c1,
                'stop_reason':        usage.get('stop_reason')
                                      or rec.get('stop_reason'),
                'is_error':           bool(rec.get('is_error')),
                'api_error_status':   rec.get('api_error_status'),
                'model':              init_model or '',
                'claude_session_uuid': init_uuid,
                'tools_called':       {},
                'response_text_len':  0,
                'exit_code':          0,
                'backfilled':         True,
            }
            record_event(
                E.TURN_COMPLETE,
                scope=project,
                session_id=init_uuid,
                ts=rec.get('timestamp'),
                data=data,
                job_id=job_id,
                cost_source='stream_result',
            )
            counts.tool_calls_inserted += 0  # no-op; documented for symmetry
            counts.messages_inserted += 0
            counts.streams_parsed += 0
            # Track the new TURN_COMPLETE row count separately.
            counts.turns_inserted += 1
            continue

        if rtype == 'assistant':
            msg = rec.get('message') or {}
            mid = msg.get('id')
            if mid:
                usage = msg.get('usage') or {}
                cc = usage.get('cache_creation') or {}
                inserted = record_message(
                    session_id=init_uuid,
                    message_id=mid,
                    ts=rec.get('timestamp'),
                    model=msg.get('model'),
                    input_tokens=usage.get('input_tokens'),
                    output_tokens=usage.get('output_tokens'),
                    cache_read_tokens=usage.get('cache_read_input_tokens'),
                    cache_5m_tokens=cc.get('ephemeral_5m_input_tokens'),
                    cache_1h_tokens=cc.get('ephemeral_1h_input_tokens'),
                    stop_reason=msg.get('stop_reason'),
                )
                if inserted:
                    counts.messages_inserted += 1
                else:
                    counts.messages_skipped += 1

            for c in _content_blocks(rec):
                btype = c.get('type')
                if btype != 'tool_use':
                    continue
                use_id = c.get('id') or ''
                name = c.get('name') or ''
                if not use_id or not name:
                    continue
                mcp_server = None
                if name.startswith('mcp__'):
                    parts = name.split('__', 2)
                    if len(parts) >= 2:
                        mcp_server = parts[1]
                input_blob = c.get('input') or {}
                try:
                    input_size = len(json.dumps(input_blob))
                except (TypeError, ValueError):
                    input_size = 0
                pending_tools[use_id] = {
                    'tool_name': name,
                    'mcp_server': mcp_server,
                    'start_ts': rec.get('timestamp'),
                    'input_size': input_size,
                }
                if _is_delegate_tool(name):
                    pending_delegates[use_id] = {
                        'member': input_blob.get('member'),
                        'skill':  input_blob.get('skill'),
                        'task':   (input_blob.get('task') or '')[:300],
                        'ts':     rec.get('timestamp'),
                    }

        elif rtype == 'user':
            if session_already_done:
                continue
            msg = rec.get('message') or {}
            for c in (msg.get('content') or []):
                if not isinstance(c, dict):
                    continue
                if c.get('type') != 'tool_result':
                    continue
                use_id = c.get('tool_use_id') or ''
                pending = pending_tools.pop(use_id, None)
                if pending is None:
                    continue
                content = c.get('content')
                if isinstance(content, str):
                    output_size = len(content)
                    text_blob = content
                else:
                    try:
                        text_blob = json.dumps(content)
                        output_size = len(text_blob)
                    except (TypeError, ValueError):
                        text_blob = ''
                        output_size = 0
                child_sid = _parse_dispatch_hex(text_blob)
                start_ts = pending['start_ts']
                end_ts = rec.get('timestamp')
                duration_ms = None
                if (start_ts is not None and end_ts is not None
                        and isinstance(start_ts, (int, float))
                        and isinstance(end_ts, (int, float))):
                    duration_ms = int((end_ts - start_ts) * 1000)
                record_event(
                    E.TOOL_CALL_COMPLETE,
                    scope=project,
                    session_id=init_uuid,
                    ts=end_ts,
                    data={
                        'tool_use_id': use_id,
                        'tool_name': pending['tool_name'],
                        'mcp_server': pending['mcp_server'],
                        'start_ts': start_ts,
                        'end_ts': end_ts,
                        'duration_ms': duration_ms,
                        'is_error': bool(c.get('is_error')),
                        'input_size': pending['input_size'],
                        'output_size': output_size,
                        'parent_session_id': init_uuid,
                        'child_session_id': child_sid,
                        'backfilled': True,
                    },
                    parent_session_id=init_uuid,
                    job_id=job_id,
                )
                counts.tool_calls_inserted += 1

                # Delegate edge.
                delegate_info = pending_delegates.pop(use_id, None)
                if delegate_info is not None and child_sid:
                    if not _dispatch_edge_already_recorded(
                        init_uuid, child_sid,
                    ):
                        record_dispatch_edge(
                            parent_session_id=init_uuid,
                            child_session_id=child_sid,
                            member=delegate_info.get('member'),
                            skill=delegate_info.get('skill'),
                            task_summary=delegate_info.get('task'),
                            ts=delegate_info.get('ts'),
                            job_id=job_id,
                        )
                        counts.dispatch_edges_inserted += 1
                    else:
                        counts.dispatch_edges_skipped += 1

    return counts


def backfill_job_dir(job_dir: Path, project: str) -> BackfillCounts:
    """Backfill one ``job-X--slug`` directory."""
    counts = BackfillCounts()
    counts.job_dirs_visited += 1
    short, _ = _parse_job_dir_name(job_dir.name)
    job_id = f'job-{short}'

    counts.merge(backfill_job_metadata(job_dir, project))

    for _phase, fname in PHASE_STREAM_FILES:
        path = job_dir / fname
        if path.exists():
            counts.merge(
                backfill_stream_file(path, job_id=job_id, project=project),
            )
    return counts


def iter_project_job_dirs(
    project_root: Path,
) -> Iterator[Path]:
    """Yield every ``job-*`` directory under ``{project_root}/.teaparty/jobs/``."""
    jobs_dir = project_root / '.teaparty' / 'jobs'
    if not jobs_dir.is_dir():
        return
    for entry in sorted(jobs_dir.iterdir()):
        if entry.is_dir() and entry.name.startswith('job-'):
            yield entry


def backfill_project(
    project_root: Path, project_name: str | None = None,
) -> BackfillCounts:
    """Backfill every job directory under one project root.

    The default project_name is the project_root's basename — the same
    convention ``job_store.create_job`` uses when emitting the live
    JOB_CREATED scope.
    """
    project = project_name or os.path.basename(
        os.path.normpath(str(project_root))
    )
    counts = BackfillCounts()
    for job_dir in iter_project_job_dirs(project_root):
        counts.merge(backfill_job_dir(job_dir, project))
    return counts


def backfill_all(project_roots: list[tuple[str, Path]]) -> BackfillCounts:
    """Backfill across multiple projects.

    ``project_roots`` is a list of ``(project_name, project_root_path)``
    tuples. The CLI shim discovers these from ``~/.teaparty/teaparty.yaml``;
    callers can supply them directly for tests.
    """
    counts = BackfillCounts()
    for project, root in project_roots:
        counts.merge(backfill_project(Path(root), project))
    return counts
