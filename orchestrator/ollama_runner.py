"""LLM runner backed by a local Ollama instance.

Writes stream-json-compatible JSONL to stream_file so that downstream
consumers (_iter_stream_events, artifact detection) work unchanged.
"""
from __future__ import annotations

import json
import time

from orchestrator.claude_runner import ClaudeResult


class OllamaRunner:
    """LLM runner that calls a local Ollama API."""

    def __init__(
        self,
        prompt: str,
        *,
        cwd: str,
        stream_file: str,
        model: str = 'llama3.1',
        ollama_host: str = 'http://localhost:11434',
        **kwargs,
    ):
        self.prompt = prompt
        self.cwd = cwd
        self.stream_file = stream_file
        self.model = model
        self.ollama_host = ollama_host

    async def run(self) -> ClaudeResult:
        import aiohttp

        start = time.time()
        url = f'{self.ollama_host}/api/generate'
        payload = {
            'model': self.model,
            'prompt': self.prompt,
            'stream': True,
        }

        full_response = ''
        input_tokens = 0
        output_tokens = 0

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    resp.raise_for_status()
                    with open(self.stream_file, 'w') as sf:
                        async for line in resp.content:
                            chunk = json.loads(line)
                            text = chunk.get('response', '')
                            full_response += text

                            # Write stream-json-compatible JSONL
                            event = {
                                'type': 'assistant',
                                'subtype': 'text',
                                'content_block': {
                                    'type': 'text',
                                    'text': text,
                                },
                            }
                            sf.write(json.dumps(event) + '\n')
                            sf.flush()

                            if chunk.get('done'):
                                input_tokens = chunk.get('prompt_eval_count', 0)
                                output_tokens = chunk.get('eval_count', 0)

        except Exception as exc:
            elapsed_ms = int((time.time() - start) * 1000)
            return ClaudeResult(
                exit_code=1,
                stream_file=self.stream_file,
                start_time=start,
                duration_ms=elapsed_ms,
                stderr_lines=[str(exc)],
            )

        elapsed_ms = int((time.time() - start) * 1000)
        return ClaudeResult(
            exit_code=0,
            stream_file=self.stream_file,
            start_time=start,
            duration_ms=elapsed_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
