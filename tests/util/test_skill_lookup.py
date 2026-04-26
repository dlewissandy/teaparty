#!/usr/bin/env python3
"""Tests for the skill-frontmatter parser.

The CfA engine used to do its own embedding-based skill lookup before
the planning phase ran (System 1 fast path).  Skill selection moved
into the planning skill itself, so the lookup pipeline is gone.
What remains is the frontmatter parser.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from teaparty.util.skill_lookup import _parse_frontmatter


class TestParseFrontmatter(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, content: str) -> str:
        path = os.path.join(self.tmpdir, 'SKILL.md')
        with open(path, 'w') as f:
            f.write(content)
        return path

    def test_parses_metadata_and_body(self):
        path = self._write(
            '---\n'
            'name: foo\n'
            'description: does foo\n'
            '---\n\n'
            '# Body\n\nDo foo things.\n'
        )
        meta, body = _parse_frontmatter(path)
        self.assertEqual(meta['name'], 'foo')
        self.assertEqual(meta['description'], 'does foo')
        self.assertIn('# Body', body)

    def test_no_frontmatter_returns_empty_meta(self):
        path = self._write('# Just body\nNo frontmatter here.\n')
        meta, body = _parse_frontmatter(path)
        self.assertEqual(meta, {})
        self.assertIn('# Just body', body)

    def test_unterminated_frontmatter_returns_empty_meta(self):
        path = self._write('---\nname: foo\n# no closer\nbody\n')
        meta, body = _parse_frontmatter(path)
        self.assertEqual(meta, {})

    def test_lines_without_colons_are_skipped(self):
        path = self._write(
            '---\n'
            'name: foo\n'
            'just a comment line\n'
            'description: bar\n'
            '---\n\nbody\n'
        )
        meta, _ = _parse_frontmatter(path)
        self.assertEqual(meta['name'], 'foo')
        self.assertEqual(meta['description'], 'bar')


if __name__ == '__main__':
    unittest.main()
