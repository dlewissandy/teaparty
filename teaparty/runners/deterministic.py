"""Deterministic LLM runner for testing.

Returns scripted ClaudeResult values without calling any external process.
Captures prompts for test assertions.
"""
from __future__ import annotations

from teaparty.runners.claude import ClaudeResult


class DeterministicRunner:
    """Test driver that returns scripted ClaudeResult values."""

    def __init__(
        self,
        prompt: str,
        *,
        cwd: str,
        stream_file: str,
        result: ClaudeResult | None = None,
        results: list[ClaudeResult] | None = None,
        **kwargs,
    ):
        self.prompt = prompt
        self.cwd = cwd
        self.stream_file = stream_file
        self._results = list(results or [])
        if result and not self._results:
            self._results = [result]
        self._call_count = 0
        self.captured_prompts: list[str] = []

    async def run(self) -> ClaudeResult:
        self.captured_prompts.append(self.prompt)
        if self._call_count < len(self._results):
            r = self._results[self._call_count]
        else:
            r = self._results[-1] if self._results else ClaudeResult(exit_code=0)
        self._call_count += 1
        # Touch stream file so downstream consumers don't crash
        with open(self.stream_file, 'a'):
            pass
        return r
