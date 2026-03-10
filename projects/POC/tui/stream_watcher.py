"""Async JSONL file tailer for real-time activity streaming.

Watches multiple JSONL stream files simultaneously, yielding new events
as they are appended. Uses polling with asyncio.sleep to avoid platform-
specific file watchers.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Callable


class StreamWatcher:
    """Tails multiple JSONL files, calling a callback with new events."""

    def __init__(self, callback: Callable[[str, dict], None]):
        self.callback = callback
        self._positions: dict[str, int] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False

    def watch(self, file_path: str) -> None:
        """Start watching a JSONL file. Idempotent."""
        if file_path in self._tasks:
            return
        if not self._running:
            return
        task = asyncio.create_task(self._tail(file_path))
        self._tasks[file_path] = task

    def start(self) -> None:
        """Mark watcher as running so new watches can be started."""
        self._running = True

    def stop(self) -> None:
        """Stop all watching tasks."""
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()

    def stop_file(self, file_path: str) -> None:
        """Stop watching a specific file."""
        task = self._tasks.pop(file_path, None)
        if task:
            task.cancel()

    async def _tail(self, file_path: str) -> None:
        """Continuously tail a JSONL file, calling callback with new events."""
        pos = self._positions.get(file_path, 0)

        while self._running:
            try:
                pos = await self._read_new_lines(file_path, pos)
                self._positions[file_path] = pos
            except asyncio.CancelledError:
                break
            except Exception:
                pass
            await asyncio.sleep(0.2)

    async def _read_new_lines(self, path: str, pos: int) -> int:
        """Read new lines from file starting at pos. Returns new position."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_read, path, pos)

    def _sync_read(self, path: str, pos: int) -> int:
        """Synchronous file read for use in executor."""
        try:
            size = os.path.getsize(path)
            if size <= pos:
                return pos

            with open(path) as f:
                f.seek(pos)
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            event = json.loads(line)
                            self.callback(path, event)
                        except json.JSONDecodeError:
                            pass
                return f.tell()
        except FileNotFoundError:
            return pos
