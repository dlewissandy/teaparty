"""Deterministic LLM runner for testing.

Returns scripted ClaudeResult values without calling any external process.
Fires on_stream_event with scripted events so the full stream pipeline
(bus writes, message relay, etc.) exercises under test.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from teaparty.runners.claude import ClaudeResult


class DeterministicRunner:
    """Test driver that returns scripted ClaudeResult values.

    Accepts the same constructor parameters as ClaudeRunner so it can
    be used as a drop-in replacement via launch()'s runner construction.

    If stream_events are provided, they are fired through on_stream_event
    before returning — exercising the full stream→bus→relay pipeline.
    If no stream_events, a default assistant text event is generated from
    the response_text.
    """

    def __init__(
        self,
        prompt: str,
        *,
        cwd: str,
        stream_file: str,
        result: ClaudeResult | None = None,
        results: list[ClaudeResult] | None = None,
        stream_events: list[dict] | None = None,
        response_text: str = '',
        delay: float = 0.0,
        on_stream_event: Callable[[dict], None] | None = None,
        **kwargs,
    ):
        self.prompt = prompt
        self.cwd = cwd
        self.stream_file = stream_file
        self.on_stream_event = on_stream_event
        self._results = list(results or [])
        if result and not self._results:
            self._results = [result]
        self._stream_events = stream_events
        self._response_text = response_text
        self._delay = delay
        self._call_count = 0
        self.captured_prompts: list[str] = []

    async def run(self) -> ClaudeResult:
        self.captured_prompts.append(self.prompt)

        # Fire stream events through the callback
        if self.on_stream_event:
            events = self._stream_events
            if events is None and self._response_text:
                # Generate a default assistant text event
                events = [{
                    'type': 'assistant',
                    'message': {'content': [
                        {'type': 'text', 'text': self._response_text},
                    ]},
                }]
            for ev in (events or []):
                self.on_stream_event(ev)

        if self._delay > 0:
            await asyncio.sleep(self._delay)

        # Touch stream file so downstream consumers don't crash
        with open(self.stream_file, 'a'):
            pass

        if self._call_count < len(self._results):
            r = self._results[self._call_count]
        else:
            r = self._results[-1] if self._results else ClaudeResult(
                exit_code=0, session_id='deterministic-session')
        self._call_count += 1
        return r
