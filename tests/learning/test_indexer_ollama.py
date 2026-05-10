"""Ollama embedding provider tests (issue #432).

The proxy memory system prefers local Ollama (free, fast) over paid
APIs. These tests pin the provider-detection order and the embedding
call path against a stubbed urllib so no real network access is needed.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.learning.episodic import indexer


def _reset_probe_cache() -> None:
    indexer._OLLAMA_PROBE_RESULT = None


class TestProviderOrder(unittest.TestCase):
    """detect_provider prefers Ollama over OpenAI/Gemini when available."""

    def setUp(self) -> None:
        _reset_probe_cache()

    def tearDown(self) -> None:
        _reset_probe_cache()

    def test_ollama_preferred_over_openai_when_available(self):
        """When Ollama is reachable, it wins even if OPENAI_API_KEY is set."""
        with mock.patch.object(indexer, '_ollama_available', return_value=True), \
             mock.patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test'}, clear=False):
            provider, model = indexer.detect_provider()
        self.assertEqual(
            provider, 'ollama',
            f"detect_provider must prefer ollama when reachable; got {provider}",
        )
        self.assertEqual(
            model, 'nomic-embed-text',
            f"Ollama model must be nomic-embed-text; got {model}",
        )

    def test_falls_back_to_openai_when_ollama_unavailable(self):
        """If Ollama is not reachable, OpenAI is the next choice."""
        with mock.patch.object(indexer, '_ollama_available', return_value=False), \
             mock.patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test'}, clear=False):
            provider, model = indexer.detect_provider()
        self.assertEqual(provider, 'openai')
        self.assertEqual(model, 'text-embedding-3-small')

    def test_falls_back_to_none_when_nothing_available(self):
        """No Ollama, no API keys → 'none'."""
        env_clean = {
            k: v for k, v in os.environ.items()
            if k not in ('OPENAI_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_API_KEY')
        }
        with mock.patch.object(indexer, '_ollama_available', return_value=False), \
             mock.patch.dict(os.environ, env_clean, clear=True):
            provider, model = indexer.detect_provider()
        self.assertEqual(provider, 'none')


class TestOllamaEmbedCall(unittest.TestCase):
    """try_embed POSTs to /api/embeddings and returns the vector."""

    def setUp(self) -> None:
        _reset_probe_cache()

    def tearDown(self) -> None:
        _reset_probe_cache()

    def test_try_embed_calls_ollama_api_and_returns_vector(self):
        """try_embed sends the right payload to /api/embeddings and parses the response."""
        captured: dict = {}
        fake_vec = [0.1, 0.2, 0.3]

        class _FakeResp:
            def __init__(self, payload: bytes) -> None:
                self._payload = payload
            def read(self) -> bytes:
                return self._payload
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            captured['url'] = req.full_url
            captured['method'] = req.get_method()
            captured['body'] = json.loads(req.data.decode('utf-8')) if req.data else None
            captured['headers'] = dict(req.headers)
            return _FakeResp(json.dumps({'embedding': fake_vec}).encode('utf-8'))

        with mock.patch.object(indexer, '_ollama_available', return_value=True), \
             mock.patch('urllib.request.urlopen', side_effect=fake_urlopen):
            result = indexer.try_embed('hello world')

        self.assertEqual(
            result, fake_vec,
            f'try_embed must return the embedding vector from the Ollama response; got {result}',
        )
        self.assertIn(
            '/api/embeddings', captured.get('url', ''),
            f"try_embed must POST to /api/embeddings; got {captured.get('url')}",
        )
        self.assertEqual(
            captured.get('method'), 'POST',
            f"Ollama embedding call must be POST; got {captured.get('method')}",
        )
        self.assertEqual(
            captured.get('body', {}).get('model'), 'nomic-embed-text',
            f"Body must select nomic-embed-text; got {captured.get('body')}",
        )
        self.assertEqual(
            captured.get('body', {}).get('prompt'), 'hello world',
            f'Body prompt must equal the input text; got {captured.get("body")}',
        )

    def test_try_embed_returns_none_when_ollama_unreachable_and_no_keys(self):
        """No Ollama, no API keys → None (the gracefulest possible failure)."""
        env_clean = {
            k: v for k, v in os.environ.items()
            if k not in ('OPENAI_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_API_KEY')
        }
        with mock.patch.object(indexer, '_ollama_available', return_value=False), \
             mock.patch.dict(os.environ, env_clean, clear=True):
            result = indexer.try_embed('anything')
        self.assertIsNone(
            result,
            'try_embed must return None when no provider is available',
        )


if __name__ == '__main__':
    unittest.main()
