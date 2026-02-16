"""Persistent ``claude`` process with bidirectional ``stream-json`` I/O.

A :class:`TeamSession` manages a long-running ``claude`` process for a
multi-agent conversation.  Messages are sent via stdin and events are
read from stdout as newline-delimited JSON.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field

from teaparty_app.models import Agent, Workgroup
from teaparty_app.services.agent_definition import build_agent_json, slugify

logger = logging.getLogger(__name__)


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
    return env


class TeamSession:
    """Persistent claude process with stream-json I/O."""

    def __init__(self, conversation_id: str, worktree_path: str | None = None):
        self.conversation_id = conversation_id
        self.worktree_path = worktree_path
        self.process: asyncio.subprocess.Process | None = None
        self.session_id: str | None = None
        self.started_at: float = 0.0
        self.is_running: bool = False
        self._reader_task: asyncio.Task | None = None
        self.event_queue: asyncio.Queue[TeamEvent] = asyncio.Queue()
        self._agent_slugs: dict[str, str] = {}  # slug -> agent_id

    async def start(
        self,
        agents: list[Agent],
        workgroup: Workgroup | None = None,
        conversation_name: str = "",
        conversation_description: str = "",
    ) -> None:
        """Spawn ``claude`` with ``--input-format stream-json --output-format stream-json``."""
        from teaparty_app.models import Conversation

        # Build a minimal Conversation for agent_definition to use
        dummy_conv = Conversation(
            id=self.conversation_id,
            workgroup_id=workgroup.id if workgroup else "",
            created_by_user_id="",
            kind="topic",
            name=conversation_name,
            description=conversation_description,
        )

        agents_dict: dict[str, dict] = {}
        for agent in agents:
            slug = slugify(agent.name)
            agents_dict[slug] = build_agent_json(agent, dummy_conv, workgroup)
            self._agent_slugs[slug] = agent.id

        cmd: list[str] = [
            "claude",
            "--output-format", "stream-json",
            "--input-format", "stream-json",
            "--permission-mode", "bypassPermissions",
            "--agents", json.dumps(agents_dict),
            "--verbose",
        ]

        if self.worktree_path:
            cmd.extend(["--add-dir", self.worktree_path])

        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.worktree_path,
            env=_clean_env(),
        )
        self.started_at = time.time()
        self.is_running = True
        self._reader_task = asyncio.create_task(self._read_events())

    async def send_message(self, content: str) -> None:
        """Write a user message to stdin in stream-json format."""
        if not self.process or not self.process.stdin:
            raise RuntimeError("TeamSession not started")
        msg = json.dumps({"type": "user_message", "content": content})
        self.process.stdin.write((msg + "\n").encode())
        await self.process.stdin.drain()

    async def _read_events(self) -> None:
        """Read stream-json events from stdout, push to event queue."""
        if not self.process or not self.process.stdout:
            return
        try:
            async for line in self.process.stdout:
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
                    await self.event_queue.put(event)

                # Capture session_id from result events
                if raw.get("session_id"):
                    self.session_id = raw["session_id"]

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error reading team session events")
        finally:
            self.is_running = False

    def _parse_event(self, raw: dict) -> TeamEvent | None:
        """Convert a raw stream-json dict to a TeamEvent."""
        event_type = raw.get("type", "")

        if event_type == "assistant":
            # Agent text content
            message = raw.get("message", {})
            content_blocks = message.get("content", [])
            text_parts = []
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            if text_parts:
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

    def get_agent_id(self, slug: str) -> str | None:
        """Map an agent slug back to its Agent.id."""
        return self._agent_slugs.get(slug)

    async def stop(self) -> None:
        """Gracefully terminate the session."""
        self.is_running = False
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self.process.kill()
                except ProcessLookupError:
                    pass
            self.process = None
