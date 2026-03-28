#!/usr/bin/env python3
"""Tests for Issue #215 — embedding-based skill lookup.

Covers:
 1. Synonym-heavy queries match via embeddings where Jaccard fails.
 2. Fallback to Jaccard when no embedding provider is available.
 3. Cosine threshold rejects unrelated skills.
 4. embed_fn parameter is threaded through lookup_skill.
 5. Skill text (name + description + category) is embedded for scoring.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.skill_lookup import SkillMatch, lookup_skill


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_skills_dir(skills: dict[str, str]) -> tempfile.TemporaryDirectory:
    """Create a temp directory with skill markdown files."""
    td = tempfile.TemporaryDirectory()
    for name, content in skills.items():
        with open(os.path.join(td.name, name), 'w') as f:
            f.write(content)
    return td


def _make_skill_content(
    name: str = 'test-skill',
    description: str = 'A test skill',
    category: str = 'testing',
    body: str = '## Steps\n\n1. Do the thing\n2. Verify the thing',
) -> str:
    return (
        f'---\n'
        f'name: {name}\n'
        f'description: {description}\n'
        f'category: {category}\n'
        f'---\n\n'
        f'{body}'
    )


def _fake_embed(text: str) -> list[float]:
    """Deterministic fake embedding that captures semantic similarity.

    Maps known synonym groups to similar vectors so that embedding-based
    scoring can distinguish related from unrelated text.
    """
    # Base vector — 8 dimensions for testability
    vec = [0.0] * 8

    text_lower = text.lower()

    # Auth/login concept group — dimension 0
    auth_words = ['login', 'authentication', 'sign-in', 'auth', 'sign in',
                  'repair', 'fix', 'defect', 'bug']
    for w in auth_words:
        if w in text_lower:
            vec[0] += 0.5

    # Database/migration concept group — dimension 1
    db_words = ['database', 'migration', 'schema', 'rollback', 'migrate']
    for w in db_words:
        if w in text_lower:
            vec[1] += 0.5

    # Research/paper concept group — dimension 2
    research_words = ['research', 'paper', 'survey', 'literature', 'writing']
    for w in research_words:
        if w in text_lower:
            vec[2] += 0.5

    # API concept group — dimension 3
    api_words = ['api', 'endpoint', 'rest', 'crud', 'route']
    for w in api_words:
        if w in text_lower:
            vec[3] += 0.5

    # Normalize
    mag = sum(x * x for x in vec) ** 0.5
    if mag > 0:
        vec = [x / mag for x in vec]

    return vec


# ── Tests ────────────────────────────────────────────────────────────────────


class TestEmbeddingSkillLookup(unittest.TestCase):
    """Embedding-based skill lookup resolves synonyms that Jaccard misses."""

    def test_synonym_query_matches_via_embeddings(self):
        """'repair sign-in auth defect' matches 'fix login authentication bug'
        skill via embeddings, even though they share zero Jaccard tokens."""
        td = _make_skills_dir({
            'fix-auth-bug.md': _make_skill_content(
                name='fix-auth-bug',
                description='Fix login authentication bug with systematic investigation',
                category='debugging',
            ),
        })
        with td:
            result = lookup_skill(
                task='Repair the sign-in auth defect',
                intent='Fix the authentication sign-in defect in the login flow',
                skills_dir=td.name,
                embed_fn=_fake_embed,
            )
            self.assertIsNotNone(result)
            self.assertEqual(result.name, 'fix-auth-bug')

    def test_unrelated_skill_rejected_with_embeddings(self):
        """An unrelated skill scores below the cosine threshold."""
        td = _make_skills_dir({
            'database-migration.md': _make_skill_content(
                name='database-migration',
                description='Migrate database schema with rollback plan',
                category='infrastructure',
            ),
        })
        with td:
            result = lookup_skill(
                task='Repair the sign-in auth defect',
                intent='Fix the authentication issue',
                skills_dir=td.name,
                embed_fn=_fake_embed,
            )
            self.assertIsNone(result)

    def test_best_embedding_match_wins(self):
        """When multiple skills exist, embedding similarity picks the best one."""
        td = _make_skills_dir({
            'fix-auth-bug.md': _make_skill_content(
                name='fix-auth-bug',
                description='Fix login authentication bug',
                category='debugging',
            ),
            'database-migration.md': _make_skill_content(
                name='database-migration',
                description='Migrate database schema with rollback',
                category='infrastructure',
            ),
        })
        with td:
            result = lookup_skill(
                task='Repair the sign-in auth defect',
                intent='Fix the authentication sign-in issue',
                skills_dir=td.name,
                embed_fn=_fake_embed,
            )
            self.assertIsNotNone(result)
            self.assertEqual(result.name, 'fix-auth-bug')


class TestFallbackToJaccard(unittest.TestCase):
    """When embed_fn is None, skill lookup falls back to Jaccard scoring."""

    def test_no_embed_fn_uses_jaccard(self):
        """Without an embed_fn, lookup_skill uses Jaccard as before."""
        td = _make_skills_dir({
            'research-paper.md': _make_skill_content(
                name='research-paper',
                description='Write a research paper with literature survey',
                category='writing',
            ),
        })
        with td:
            result = lookup_skill(
                task='Write a research paper on distributed systems',
                intent='Research and write a paper surveying distributed consensus',
                skills_dir=td.name,
                embed_fn=None,
            )
            self.assertIsNotNone(result)
            self.assertEqual(result.name, 'research-paper')

    def test_embed_fn_returning_none_falls_back(self):
        """If embed_fn returns None (provider error), falls back to Jaccard."""
        td = _make_skills_dir({
            'research-paper.md': _make_skill_content(
                name='research-paper',
                description='Write a research paper with literature survey',
                category='writing',
            ),
        })
        with td:
            result = lookup_skill(
                task='Write a research paper on distributed systems',
                intent='Research and write a paper surveying distributed consensus',
                skills_dir=td.name,
                embed_fn=lambda text: None,
            )
            self.assertIsNotNone(result)


class TestEmbedFnThreading(unittest.TestCase):
    """The embed_fn parameter is properly threaded through scoring."""

    def test_embed_fn_called_with_skill_and_query_text(self):
        """embed_fn is called for both query text and skill text."""
        calls = []

        def tracking_embed(text: str) -> list[float]:
            calls.append(text)
            return _fake_embed(text)

        td = _make_skills_dir({
            'test.md': _make_skill_content(
                name='test-skill',
                description='A test skill for debugging',
                category='debugging',
            ),
        })
        with td:
            lookup_skill(
                task='Fix the bug',
                intent='Debug the issue',
                skills_dir=td.name,
                embed_fn=tracking_embed,
            )
            # Should have been called at least twice: once for query, once for skill
            self.assertGreaterEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
