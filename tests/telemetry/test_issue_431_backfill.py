"""Backfill tests for Issue #431.

Construct a synthetic ``.teaparty/jobs/job-X--slug/`` tree with stream
JSONL files, run the backfill, and assert the resulting events table.
Idempotency is verified by running the backfill twice and asserting the
second pass inserts zero new rows.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from teaparty import telemetry
from teaparty.telemetry import events as E
from teaparty.telemetry.backfill import (
    BackfillCounts,
    backfill_job_dir,
    backfill_project,
    backfill_stream_file,
)


def _make_home() -> str:
    home = tempfile.mkdtemp(prefix='backfill-431-')
    telemetry.reset_for_tests()
    telemetry.set_teaparty_home(home)
    return home


def _make_project(root: Path, project: str = 'comics') -> Path:
    """Create ``{root}/{project}/.teaparty/jobs/`` and return the
    project's directory."""
    proj = root / project
    (proj / '.teaparty' / 'jobs').mkdir(parents=True)
    return proj


def _write_job(
    proj: Path,
    short: str,
    slug: str,
    *,
    prompt: str = 'fix a thing',
    branch: str = 'fix/x',
    status: str = 'active',
    issue: int | None = None,
    streams: dict[str, list[dict]] | None = None,
) -> Path:
    """Create a job dir with PROMPT.txt + job.json (+ optional streams).

    ``streams`` maps phase suffix (intent / plan / exec) → list of
    JSONL records to write.
    """
    job_dir = proj / '.teaparty' / 'jobs' / f'job-{short}--{slug}'
    job_dir.mkdir()
    (job_dir / 'PROMPT.txt').write_text(prompt)
    (job_dir / 'job.json').write_text(json.dumps({
        'job_id':  f'job-{short}',
        'slug':    slug,
        'branch':  branch,
        'status':  status,
        'issue':   issue,
        'created_at': '2026-05-09T00:00:00Z',
    }))
    streams = streams or {}
    for phase, records in streams.items():
        path = job_dir / f'.{phase}-stream.jsonl'
        with open(path, 'w') as f:
            for rec in records:
                f.write(json.dumps(rec) + '\n')
    return job_dir


def _system_init(uuid: str, model: str = 'claude-opus-4-7') -> dict:
    return {
        'type': 'system', 'subtype': 'init',
        'session_id': uuid, 'model': model,
        'cwd': '/tmp/x',
    }


def _assistant_msg(
    *, mid: str, model: str = 'claude-opus-4-7',
    input_tokens: int = 100, output_tokens: int = 200,
    cache_read: int = 0, cache_5m: int = 0, cache_1h: int = 0,
    stop_reason: str = 'end_turn',
    content: list | None = None,
    timestamp: float = 1000.0,
) -> dict:
    return {
        'type': 'assistant',
        'timestamp': timestamp,
        'message': {
            'id': mid,
            'model': model,
            'usage': {
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'cache_read_input_tokens': cache_read,
                'cache_creation': {
                    'ephemeral_5m_input_tokens': cache_5m,
                    'ephemeral_1h_input_tokens': cache_1h,
                },
            },
            'stop_reason': stop_reason,
            'content': content or [],
        },
    }


def _tool_use_block(
    tu_id: str, name: str, input_data: dict,
) -> dict:
    return {
        'type': 'tool_use',
        'id':   tu_id,
        'name': name,
        'input': input_data,
    }


def _tool_result(
    tu_id: str, content: str | dict, *,
    is_error: bool = False, timestamp: float = 1003.0,
) -> dict:
    return {
        'type': 'user',
        'timestamp': timestamp,
        'message': {
            'content': [{
                'type': 'tool_result',
                'tool_use_id': tu_id,
                'content': content,
                'is_error': is_error,
            }],
        },
    }


class BackfillStreamFileTests(unittest.TestCase):
    """Each emit type from a parsed stream file produces a row."""

    def setUp(self) -> None:
        self._home = _make_home()
        self._tmp = tempfile.mkdtemp(prefix='backfill-stream-')

    def tearDown(self) -> None:
        telemetry.reset_for_tests()
        shutil.rmtree(self._home, ignore_errors=True)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_assistant_event_yields_one_message_row(self) -> None:
        path = Path(self._tmp) / 'stream.jsonl'
        with open(path, 'w') as f:
            f.write(json.dumps(_system_init('uuid-A')) + '\n')
            f.write(json.dumps(_assistant_msg(mid='msg-1')) + '\n')

        counts = backfill_stream_file(
            path, job_id='job-J', project='comics',
        )
        self.assertEqual(counts.messages_inserted, 1)

        db = os.path.join(self._home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                "SELECT session_id, message_id, input_tokens, output_tokens "
                "FROM session_messages WHERE message_id='msg-1'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(
            row, ('uuid-A', 'msg-1', 100, 200),
            f'backfill must key the session_messages row by the SDK uuid '
            f'from system/init — got {row!r}',
        )

    def test_repeated_assistant_with_same_message_id_dedupes(self) -> None:
        """Two assistant events sharing one message_id must collapse to
        one row — the same dedupe contract live runs use."""
        path = Path(self._tmp) / 'stream.jsonl'
        with open(path, 'w') as f:
            f.write(json.dumps(_system_init('uuid-D')) + '\n')
            for _ in range(3):
                f.write(json.dumps(
                    _assistant_msg(mid='msg-dup', input_tokens=100,
                                   output_tokens=200),
                ) + '\n')

        counts = backfill_stream_file(
            path, job_id='job-D', project='comics',
        )
        self.assertEqual(
            counts.messages_inserted, 1,
            f'backfill must dedupe on (session_id, message_id) — got '
            f'{counts.messages_inserted} insertions',
        )
        self.assertEqual(
            counts.messages_skipped, 2,
            f'two duplicate writes must be tracked as skipped — got '
            f'{counts.messages_skipped}',
        )

    def test_tool_use_followed_by_tool_result_yields_tool_call_complete(
        self,
    ) -> None:
        path = Path(self._tmp) / 'stream.jsonl'
        with open(path, 'w') as f:
            f.write(json.dumps(_system_init('uuid-T')) + '\n')
            f.write(json.dumps(_assistant_msg(
                mid='msg-T', timestamp=1000.0,
                content=[_tool_use_block('toolu_1', 'Bash', {'command': 'ls'})],
            )) + '\n')
            f.write(json.dumps(_tool_result(
                'toolu_1', 'output text', timestamp=1003.0,
            )) + '\n')

        counts = backfill_stream_file(
            path, job_id='job-T', project='comics',
        )
        self.assertEqual(counts.tool_calls_inserted, 1)
        events = telemetry.query_events(event_type=E.TOOL_CALL_COMPLETE)
        self.assertEqual(len(events), 1)
        d = events[0].data
        self.assertEqual(d['tool_name'], 'Bash')
        self.assertEqual(d['mcp_server'], None)
        self.assertEqual(d['duration_ms'], 3000)
        self.assertEqual(d['parent_session_id'], 'uuid-T')

    def test_delegate_tool_use_yields_dispatch_edge(self) -> None:
        path = Path(self._tmp) / 'stream.jsonl'
        with open(path, 'w') as f:
            f.write(json.dumps(_system_init('uuid-Del')) + '\n')
            f.write(json.dumps(_assistant_msg(
                mid='msg-Del', timestamp=1000.0,
                content=[_tool_use_block(
                    'toolu_d',
                    'mcp__teaparty-config__Delegate',
                    {'member': 'developer', 'task': 'fix it',
                     'skill': 'attempt-task'},
                )],
            )) + '\n')
            f.write(json.dumps(_tool_result(
                'toolu_d',
                json.dumps({'conversation_id': 'dispatch:abcd1234'}),
                timestamp=1004.0,
            )) + '\n')

        counts = backfill_stream_file(
            path, job_id='job-D', project='comics',
        )
        self.assertEqual(counts.tool_calls_inserted, 1)
        self.assertEqual(counts.dispatch_edges_inserted, 1)

        db = os.path.join(self._home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                'SELECT parent_session_id, child_session_id, member, '
                'skill, job_id FROM dispatch_edges'
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(
            row,
            ('uuid-Del', 'abcd1234', 'developer', 'attempt-task', 'job-D'),
            f'dispatch_edges row must be parsed from Delegate '
            f'tool_result content — got {row!r}',
        )


class BackfillJobMetadataTests(unittest.TestCase):

    def setUp(self) -> None:
        self._home = _make_home()
        self._tmp = tempfile.mkdtemp(prefix='backfill-job-')

    def tearDown(self) -> None:
        telemetry.reset_for_tests()
        shutil.rmtree(self._home, ignore_errors=True)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_job_metadata_yields_one_job_created_event(self) -> None:
        proj = _make_project(Path(self._tmp))
        _write_job(proj, 'abcdef', 'fix-bug', prompt='fix it', issue=99)
        counts = backfill_project(proj)
        self.assertEqual(
            counts.jobs_inserted, 1,
            f'backfill must emit one JOB_CREATED per job dir — got '
            f'{counts.jobs_inserted}',
        )
        evs = telemetry.query_events(event_type=E.JOB_CREATED)
        self.assertEqual(len(evs), 1)
        d = evs[0].data
        self.assertEqual(d['job_id'], 'job-abcdef')
        self.assertEqual(d['slug'], 'fix-bug')
        self.assertEqual(d['prompt_text'], 'fix it')
        self.assertEqual(d['prompt_bytes'], len('fix it'))
        # The hash must be sha1 of the prompt text — same contract
        # the live emission uses.
        import hashlib
        self.assertEqual(
            d['prompt_hash'],
            hashlib.sha1(b'fix it').hexdigest(),
            'backfill must compute prompt_hash with sha1 to match the '
            'live emission contract',
        )
        self.assertEqual(d['issue'], 99)
        self.assertTrue(
            d.get('backfilled'),
            'backfilled JOB_CREATED rows must carry data.backfilled=True '
            'so analyses can distinguish historical from live data',
        )


class BackfillIdempotencyTests(unittest.TestCase):

    def setUp(self) -> None:
        self._home = _make_home()
        self._tmp = tempfile.mkdtemp(prefix='backfill-idem-')

    def tearDown(self) -> None:
        telemetry.reset_for_tests()
        shutil.rmtree(self._home, ignore_errors=True)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_running_backfill_twice_inserts_zero_new_rows(self) -> None:
        proj = _make_project(Path(self._tmp))
        _write_job(
            proj, 'idem01', 'fix-bug',
            streams={
                'intent': [
                    _system_init('uuid-IA'),
                    _assistant_msg(mid='m-1', timestamp=1000.0,
                                   content=[_tool_use_block(
                                       'tu-1', 'Bash', {'command': 'x'},
                                   )]),
                    _tool_result('tu-1', 'ok', timestamp=1001.0),
                ],
            },
        )
        counts1 = backfill_project(proj)
        counts2 = backfill_project(proj)

        self.assertEqual(
            counts1.jobs_inserted, 1,
            'first pass must record the JOB_CREATED row',
        )
        self.assertEqual(
            counts1.messages_inserted, 1,
            'first pass must record the assistant message',
        )

        self.assertEqual(
            counts2.jobs_inserted, 0,
            f'second pass must insert no new JOB_CREATED rows — '
            f'got {counts2.jobs_inserted}',
        )
        self.assertEqual(
            counts2.jobs_skipped, 1,
            f'second pass must mark the existing job as skipped — '
            f'got {counts2.jobs_skipped}',
        )
        # The session_messages PRIMARY KEY blocks the duplicate insert,
        # so messages_inserted on the second pass is 0 and
        # messages_skipped is 1.
        self.assertEqual(
            counts2.messages_inserted, 0,
            f'second pass must insert no new session_messages rows — '
            f'got {counts2.messages_inserted}',
        )
        self.assertEqual(
            counts2.messages_skipped, 1,
            'second pass must mark the duplicate as skipped',
        )


class BackfillProjectScanTests(unittest.TestCase):
    """Scanning a project root must visit every job-* dir under it."""

    def setUp(self) -> None:
        self._home = _make_home()
        self._tmp = tempfile.mkdtemp(prefix='backfill-scan-')

    def tearDown(self) -> None:
        telemetry.reset_for_tests()
        shutil.rmtree(self._home, ignore_errors=True)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_three_jobs_visited_and_one_skipped_when_already_recorded(
        self,
    ) -> None:
        proj = _make_project(Path(self._tmp))
        _write_job(proj, 'aaa', 's1')
        _write_job(proj, 'bbb', 's2')
        _write_job(proj, 'ccc', 's3')
        # Pre-record one job_id manually so it gets skipped.
        telemetry.record_event(
            E.JOB_CREATED, scope='comics',
            data={'job_id': 'job-bbb'}, job_id='job-bbb',
        )

        counts = backfill_project(proj)
        self.assertEqual(
            counts.job_dirs_visited, 3,
            f'all three job dirs must be visited — got '
            f'{counts.job_dirs_visited}',
        )
        self.assertEqual(
            counts.jobs_inserted, 2,
            f'two new JOB_CREATED rows expected — got '
            f'{counts.jobs_inserted}',
        )
        self.assertEqual(
            counts.jobs_skipped, 1,
            f'one job already recorded — got {counts.jobs_skipped} '
            f'skipped',
        )


if __name__ == '__main__':
    unittest.main()
