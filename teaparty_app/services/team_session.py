"""Streaming ``claude -p`` invocation for multi-agent team conversations.

A :class:`TeamSession` wraps a ``claude -p`` subprocess that produces
``stream-json`` events.  The user message is piped via stdin (prompt mode),
and stdout is read line-by-line in a background thread so events can be
consumed incrementally by the team bridge.

Uses ``subprocess.Popen`` and ``threading.Thread`` — no asyncio.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field

from teaparty_app.models import Agent, Workgroup
from teaparty_app.services.agent_definition import build_agent_json, slugify

logger = logging.getLogger(__name__)

_PROTOCOL_TYPES = frozenset({
    "idle_notification", "permission_request", "shutdown_request",
    "shutdown_approved", "shutdown_response",
    "plan_approval_request", "plan_approval_response",
})


@dataclass
class TeamEvent:
    """A single event parsed from the stream-json output."""

    kind: str  # "assistant", "tool_use", "tool_result", "error", "system", "result"
    agent_slug: str = ""
    content: str = ""
    tool_name: str = ""
    raw: dict = field(default_factory=dict)


def _clean_env() -> dict[str, str]:
    """Build a clean environment for the claude subprocess."""
    env = {**os.environ}
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    env.pop("CLAUDECODE", None)
    env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"
    return env


class TeamSession:
    """Streaming claude -p invocation for multi-agent teams.

    Each call to :meth:`run` spawns a new ``claude -p`` process.  Events
    are read from stdout in a background thread and pushed to
    :attr:`event_queue` for the bridge to consume.
    """

    def __init__(self, conversation_id: str, worktree_path: str | None = None):
        self.conversation_id = conversation_id
        self.worktree_path = worktree_path
        self.process: subprocess.Popen | None = None
        self.session_id: str | None = None
        self.started_at: float = 0.0
        self.is_running: bool = False
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_lines: list[str] = []
        self.event_queue: queue.Queue[TeamEvent] = queue.Queue()
        self._agent_slugs: dict[str, str] = {}  # slug -> agent_id
        self._materialized_dir: str | None = None  # temp dir for cleanup
        self.team_dir: str | None = None
        self._inbox_thread: threading.Thread | None = None

    def run(
        self,
        agents: list[Agent],
        user_message: str,
        workgroup: Workgroup | None = None,
        conversation_name: str = "",
        conversation_description: str = "",
        lead_slug: str | None = None,
        files_context: str = "",
        teammates: list[Agent] | None = None,
        settings_json: str | None = None,
    ) -> None:
        """Spawn ``claude -p``, pipe the message, and start reading events.

        The subprocess runs in prompt mode: the user message is written to
        stdin, stdin is closed, and stdout produces stream-json events until
        the process exits.  Events are read in a background thread.
        """
        from teaparty_app.models import Conversation

        # Build a minimal Conversation for agent_definition to use
        dummy_conv = Conversation(
            id=self.conversation_id,
            workgroup_id=workgroup.id if workgroup else "",
            created_by_user_id="",
            kind="job",
            name=conversation_name,
            description=conversation_description,
        )

        agents_dict: dict[str, dict] = {}
        for agent in agents:
            slug = slugify(agent.name)
            is_lead = lead_slug and slug == lead_slug
            agents_dict[slug] = build_agent_json(
                agent, dummy_conv, workgroup,
                files_context=files_context,
                teammates=teammates if is_lead else None,
            )
            self._agent_slugs[slug] = agent.id

        max_turns = max(6, 4 * len(agents))

        cmd: list[str] = [
            "claude",
            "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--max-turns", str(max_turns),
            "--permission-mode", "bypassPermissions",
            "--agents", json.dumps(agents_dict),
        ]

        if lead_slug:
            cmd.extend(["--agent", lead_slug])

        if settings_json:
            cmd.extend(["--settings", settings_json])

        logger.info(
            "Starting team session for conversation %s: lead=%s, agents=%s, cwd=%s",
            self.conversation_id, lead_slug, list(agents_dict.keys()),
            self.worktree_path,
        )

        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.worktree_path,
            env=_clean_env(),
        )
        self.started_at = time.time()
        self.is_running = True

        # Write user message to stdin and close (prompt mode).
        self.process.stdin.write(user_message.encode())
        self.process.stdin.close()

        # Read stderr in a separate thread to prevent pipe buffer deadlock.
        self._stderr_lines = []
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_thread.start()

        # Read events from stdout in a background thread.
        self._reader_thread = threading.Thread(target=self._read_events, daemon=True)
        self._reader_thread.start()

        # Poll inbox files for agent-to-agent messages.
        self._inbox_thread = threading.Thread(target=self._poll_inboxes, daemon=True)
        self._inbox_thread.start()

    def _read_stderr(self) -> None:
        """Read stderr in a background thread to prevent pipe buffer deadlock."""
        if not self.process or not self.process.stderr:
            return
        try:
            for line in self.process.stderr:
                text = line.decode(errors="replace").rstrip()
                if text:
                    self._stderr_lines.append(text)
        except Exception:
            pass

    def _read_events(self) -> None:
        """Read stream-json events from stdout in a background thread."""
        if not self.process or not self.process.stdout:
            self.is_running = False
            return
        event_count = 0
        try:
            for line in self.process.stdout:
                text = line.decode(errors="replace").strip()
                if not text:
                    continue
                try:
                    raw = json.loads(text)
                except json.JSONDecodeError:
                    logger.debug("Non-JSON line from team session: %s", text[:200])
                    continue

                event = self._parse_event(raw)
                if event:
                    self.event_queue.put(event)
                    event_count += 1

                # Capture session_id from result events
                if raw.get("session_id"):
                    self.session_id = raw["session_id"]

        except Exception:
            logger.exception("Error reading team session events")
        finally:
            # Wait for the process to finish and log exit info.
            if self.process:
                try:
                    rc = self.process.wait(timeout=10.0)
                except subprocess.TimeoutExpired:
                    rc = None
                if rc and rc != 0:
                    stderr_text = "\n".join(self._stderr_lines[-20:])
                    logger.error(
                        "Team session process exited %d for conversation %s. "
                        "Events received: %d. Stderr:\n%s",
                        rc, self.conversation_id, event_count, stderr_text,
                    )
                elif event_count == 0:
                    stderr_text = "\n".join(self._stderr_lines[-20:])
                    logger.warning(
                        "Team session produced 0 events for conversation %s "
                        "(exit code %s). Stderr:\n%s",
                        self.conversation_id, rc, stderr_text,
                    )
                else:
                    logger.info(
                        "Team session finished for conversation %s: "
                        "%d events, exit code %s",
                        self.conversation_id, event_count, rc,
                    )
            self.is_running = False
            # Signal end-of-stream so the bridge doesn't wait for _IDLE_TIMEOUT
            self.event_queue.put(TeamEvent(kind="eof"))

    def _parse_event(self, raw: dict) -> TeamEvent | None:
        """Convert a raw stream-json dict to a TeamEvent."""
        event_type = raw.get("type", "")

        if event_type == "assistant":
            # Agent message — may contain text, tool_use, or both.
            # Always emit so the bridge can track Task delegations even
            # when there's no surrounding text.
            message = raw.get("message", {})
            content_blocks = message.get("content", [])
            if content_blocks:
                text_parts = []
                for block in content_blocks:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                return TeamEvent(
                    kind="assistant",
                    content="\n".join(text_parts),
                    raw=raw,
                )

        elif event_type == "content_block_delta":
            delta = raw.get("delta", {})
            if delta.get("type") == "text_delta":
                return TeamEvent(
                    kind="text_delta",
                    content=delta.get("text", ""),
                    raw=raw,
                )

        elif event_type == "tool_use":
            return TeamEvent(
                kind="tool_use",
                tool_name=raw.get("name", ""),
                content=json.dumps(raw.get("input", {})),
                raw=raw,
            )

        elif event_type == "tool_result":
            return TeamEvent(
                kind="tool_result",
                tool_name=raw.get("tool_name", ""),
                content=raw.get("content", ""),
                raw=raw,
            )

        elif event_type == "result":
            return TeamEvent(
                kind="result",
                content=raw.get("result", ""),
                raw=raw,
            )

        elif event_type == "error":
            return TeamEvent(
                kind="error",
                content=raw.get("error", {}).get("message", str(raw)),
                raw=raw,
            )

        return None

    def _discover_team_dir(self) -> str | None:
        """Find the team directory created for this session.

        Scans ``~/.claude/teams/`` for directories whose ``config.json``
        has a ``createdAt`` timestamp within 5 seconds of ``self.started_at``.
        Returns the newest match, or ``None``.
        """
        teams_root = os.path.expanduser("~/.claude/teams")
        if not os.path.isdir(teams_root):
            return None

        threshold_ms = self.started_at * 1000 - 5000
        best: tuple[float, str] | None = None

        try:
            for name in os.listdir(teams_root):
                config_path = os.path.join(teams_root, name, "config.json")
                if not os.path.isfile(config_path):
                    continue
                try:
                    with open(config_path) as f:
                        config = json.load(f)
                    created_at = config.get("createdAt", 0)
                    if created_at >= threshold_ms:
                        if best is None or created_at > best[0]:
                            best = (created_at, os.path.join(teams_root, name))
                except (json.JSONDecodeError, OSError):
                    continue
        except OSError:
            return None

        return best[1] if best else None

    def _poll_inboxes(self) -> None:
        """Background thread: poll inbox files for agent-to-agent messages.

        Waits up to 30s for the team directory to appear, then polls
        ``{team_dir}/inboxes/*.json`` every 2s for new entries.
        """
        # Phase 1: discover team dir (up to 30s)
        for _ in range(15):
            if not self.is_running:
                return
            found = self._discover_team_dir()
            if found:
                self.team_dir = found
                logger.info("Discovered team dir: %s", found)
                break
            time.sleep(2)
        else:
            logger.debug("No team dir found within 30s for conversation %s", self.conversation_id)
            return

        # Phase 2: poll inbox files
        inboxes_dir = os.path.join(self.team_dir, "inboxes")
        seen_counts: dict[str, int] = {}  # file path → entries already processed

        while self.is_running:
            if os.path.isdir(inboxes_dir):
                try:
                    for fname in os.listdir(inboxes_dir):
                        if not fname.endswith(".json"):
                            continue
                        # Filename is the recipient (e.g. "Proponent.json")
                        recipient_name = fname[:-5]
                        fpath = os.path.join(inboxes_dir, fname)
                        try:
                            with open(fpath) as f:
                                entries = json.load(f)
                        except (json.JSONDecodeError, OSError):
                            continue
                        if not isinstance(entries, list):
                            continue

                        prev_count = seen_counts.get(fpath, 0)
                        if len(entries) <= prev_count:
                            continue

                        for entry in entries[prev_count:]:
                            if not isinstance(entry, dict):
                                continue
                            text = entry.get("text") or entry.get("content") or ""
                            if isinstance(text, str) and text.strip() and not self._is_protocol_message(text):
                                from_name = entry.get("from", "")
                                self.event_queue.put(TeamEvent(
                                    kind="inbox",
                                    agent_slug=from_name,
                                    content=text.strip(),
                                    raw={
                                        "recipient": recipient_name,
                                        "from": from_name,
                                        "timestamp": entry.get("timestamp", ""),
                                        "summary": entry.get("summary", ""),
                                    },
                                ))

                        seen_counts[fpath] = len(entries)
                except OSError:
                    pass

            time.sleep(2)

    @staticmethod
    def _is_protocol_message(text: str) -> bool:
        """Return True if *text* is a JSON protocol message (not conversational)."""
        text = text.strip()
        if not text.startswith("{"):
            return False
        try:
            obj = json.loads(text)
            return isinstance(obj, dict) and obj.get("type") in _PROTOCOL_TYPES
        except (json.JSONDecodeError, ValueError):
            return False

    def get_agent_id(self, slug: str) -> str | None:
        """Map an agent slug back to its Agent.id."""
        return self._agent_slugs.get(slug)

    def stop(self) -> None:
        """Terminate the subprocess if still running."""
        self.is_running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                try:
                    self.process.kill()
                    self.process.wait(timeout=2.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            except OSError:
                pass
            self.process = None
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=5.0)
            self._reader_thread = None
        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=2.0)
            self._stderr_thread = None
        if self._inbox_thread and self._inbox_thread.is_alive():
            self._inbox_thread.join(timeout=5.0)
            self._inbox_thread = None
        if self._materialized_dir:
            import shutil
            try:
                shutil.rmtree(self._materialized_dir)
            except OSError:
                logger.warning("Failed to clean up materialized dir: %s", self._materialized_dir)
            self._materialized_dir = None
