"""Tests for issue #285: align stats page with cost-based reality.

Acceptance criteria:
1. stats.md Data Sources table: row says "Cost per Day", not "Token usage"
2. stats.md user story no longer says "tokens" in the cost chart story
3. bridge/stats.py: limitations dict does NOT have a 'token_usage' key
4. stats.html: does NOT reference limits.token_usage
5. data.js: does NOT contain tokensUsed fields
6. test_issue_304.py: does NOT contain test_limitations_has_token_usage_note
"""
import os
import tempfile
import unittest


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATS_MD   = os.path.join(_REPO_ROOT, 'docs', 'proposals', 'ui-redesign', 'references', 'stats.md')
_STATS_HTML = os.path.join(_REPO_ROOT, 'docs', 'proposals', 'ui-redesign', 'mockup', 'stats.html')
_DATA_JS    = os.path.join(_REPO_ROOT, 'docs', 'proposals', 'ui-redesign', 'mockup', 'data.js')
_TEST_304   = os.path.join(_REPO_ROOT, 'tests', 'test_issue_304.py')


# ── stats.md ─────────────────────────────────────────────────────────────────

class TestStatsMdDataSources(unittest.TestCase):
    """stats.md must describe cost, not token usage, as the chart data source."""

    def setUp(self):
        with open(_STATS_MD) as f:
            self.content = f.read()

    def test_data_sources_row_says_cost_per_day_not_token_usage(self):
        self.assertNotIn('| Token usage |', self.content,
                         'Data Sources table must not have a "Token usage" row')
        self.assertIn('Cost per Day', self.content,
                      'Data Sources table must have a "Cost per Day" row')

    def test_data_sources_no_issue_285_caveat(self):
        self.assertNotIn('stores USD, not tokens', self.content,
                         'Data Sources table must not contain the stale token caveat')

    def test_user_story_cost_chart_does_not_say_tokens(self):
        # Find the cost chart user story and verify it's about cost, not tokens
        lines = self.content.splitlines()
        cost_story_idx = next(
            (i for i, ln in enumerate(lines) if 'spending' in ln.lower()),
            None,
        )
        self.assertIsNotNone(cost_story_idx,
                             'Could not find cost chart user story (line with "spending")')
        story_block = '\n'.join(lines[cost_story_idx:cost_story_idx + 5])
        self.assertNotIn('tokens', story_block.lower(),
                         'Cost chart user story must not reference tokens')


# ── bridge/stats.py ──────────────────────────────────────────────────────────

class TestBridgeStatsLimitations(unittest.TestCase):
    """compute_stats must not emit a token_usage limitation (issue resolved)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, 'POC', '.sessions'), exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _compute(self):
        from projects.POC.bridge.stats import compute_stats
        return compute_stats(self.tmpdir, self.tmpdir)

    def test_limitations_does_not_have_token_usage_key(self):
        result = self._compute()
        self.assertNotIn('token_usage', result['limitations'],
                         'token_usage limitation must be removed — cost chart is now by design')


# ── stats.html ────────────────────────────────────────────────────────────────

class TestStatsHtmlNoTokenUsageRef(unittest.TestCase):
    """stats.html must not reference limits.token_usage (no longer a limitation)."""

    def setUp(self):
        with open(_STATS_HTML) as f:
            self.content = f.read()

    def test_stats_html_does_not_reference_limits_token_usage(self):
        self.assertNotIn('limits.token_usage', self.content,
                         'stats.html must not reference limits.token_usage — limitation is resolved')

    def test_stats_html_does_not_reference_token_usage_variable(self):
        self.assertNotIn('token_usage', self.content,
                         'stats.html must not contain any token_usage reference')


# ── data.js ───────────────────────────────────────────────────────────────────

class TestDataJsNoTokensUsed(unittest.TestCase):
    """data.js must not contain tokensUsed fields (never rendered, not a real API field)."""

    def setUp(self):
        with open(_DATA_JS) as f:
            self.content = f.read()

    def test_data_js_does_not_contain_tokens_used(self):
        self.assertNotIn('tokensUsed', self.content,
                         'data.js must not contain tokensUsed fields — not persisted, not rendered')


# ── test_issue_304.py ─────────────────────────────────────────────────────────

class TestIssue304NoTokenUsageTest(unittest.TestCase):
    """test_issue_304.py must not contain the obsolete token_usage test."""

    def setUp(self):
        with open(_TEST_304) as f:
            self.content = f.read()

    def test_no_token_usage_test_in_304(self):
        self.assertNotIn('test_limitations_has_token_usage_note', self.content,
                         'test_issue_304.py must not contain the obsolete token_usage test')


if __name__ == '__main__':
    unittest.main()
