#!/usr/bin/env python3
"""Tests for the surviving approval_gate surface — per-team model-path resolution."""
import unittest

from teaparty.proxy.approval_gate import resolve_team_model_path


class TestResolveTeamModelPath(unittest.TestCase):

    def test_with_team_inserts_team_name(self):
        self.assertEqual(
            resolve_team_model_path('/path/to/.proxy-confidence.json', 'coding'),
            '/path/to/.proxy-confidence-coding.json',
        )

    def test_empty_team_returns_base(self):
        base = '/path/to/.proxy-confidence.json'
        self.assertEqual(resolve_team_model_path(base, ''), base)

    def test_preserves_extension(self):
        self.assertEqual(
            resolve_team_model_path('/data/.proxy-confidence.json', 'art'),
            '/data/.proxy-confidence-art.json',
        )

    def test_different_teams_different_paths(self):
        base = '/tmp/.proxy-confidence.json'
        self.assertNotEqual(
            resolve_team_model_path(base, 'coding'),
            resolve_team_model_path(base, 'art'),
        )


if __name__ == '__main__':
    unittest.main()
