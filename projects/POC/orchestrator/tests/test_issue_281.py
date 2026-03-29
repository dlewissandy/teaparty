"""Tests for issue #281: Stats page proxy accuracy spec — wrong source table,
missing time-series schema, conflated metrics, undisclosed prerequisites.

Acceptance criteria:
1. Data Sources table names proxy_accuracy as the source, not proxy_chunks
2. action_match_rate and prior_calibration are named as distinct metrics
3. No 7-day time-series claim for proxy accuracy without a schema path — the
   chart section must either not exist or be explicitly reframed
4. Dependencies on #231 and #221 are noted in the proxy accuracy section
"""
import os
import unittest

_STATS_DOC_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        '..', '..', '..', '..', 'docs', 'proposals', 'ui-redesign', 'references', 'stats.md',
    )
)


def _read_stats_doc() -> str:
    with open(_STATS_DOC_PATH) as f:
        return f.read()


class TestProxyAccuracySourceTable(unittest.TestCase):
    """Data Sources table must reference proxy_accuracy, not proxy_chunks."""

    def test_proxy_accuracy_table_is_named_as_source(self):
        """The Data Sources table must list proxy_accuracy as the source for accuracy metrics."""
        content = _read_stats_doc()
        self.assertIn(
            'proxy_accuracy',
            content,
            "stats.md must reference the proxy_accuracy table as the accuracy data source. "
            "proxy_accuracy holds aggregated prior_correct/posterior_correct counts "
            "per (state, task_type); it is not the same as proxy_chunks.",
        )

    def test_proxy_chunks_is_not_the_accuracy_source(self):
        """proxy_chunks must not be described as the source for proxy accuracy stats.

        The current Data Sources row says 'Proxy memory chunks (prediction vs. outcome)'
        which is wrong — chunks are raw interaction records, not aggregated accuracy.
        """
        content = _read_stats_doc()
        # Accept: proxy_chunks may be referenced elsewhere (e.g. for explanation),
        # but must not appear as the Data Sources entry for "Proxy accuracy".
        lines = content.splitlines()
        for line in lines:
            if 'proxy_chunks' in line.lower() or 'proxy memory chunks' in line.lower():
                # A line referencing proxy_chunks is only acceptable if it does NOT
                # describe it as the source for accuracy.
                self.assertNotIn(
                    'accuracy',
                    line.lower(),
                    f"stats.md describes proxy_chunks as the source for accuracy data: {line!r}. "
                    "Accuracy is aggregated in proxy_accuracy, not raw proxy_chunks.",
                )


class TestDistinctMetricNames(unittest.TestCase):
    """action_match_rate and prior_calibration must be named separately."""

    def test_action_match_rate_is_named(self):
        """stats.md must name action_match_rate as a distinct metric."""
        content = _read_stats_doc()
        self.assertIn(
            'action_match_rate',
            content,
            "stats.md must name action_match_rate explicitly. "
            "It measures posterior_prediction vs. outcome (escalated gates only) "
            "and is distinct from prior_calibration.",
        )

    def test_prior_calibration_is_named(self):
        """stats.md must name prior_calibration as a distinct metric."""
        content = _read_stats_doc()
        self.assertIn(
            'prior_calibration',
            content,
            "stats.md must name prior_calibration explicitly. "
            "It measures prior_prediction vs. posterior_prediction agreement "
            "and is distinct from action_match_rate.",
        )

    def test_two_metrics_are_distinguished_not_collapsed(self):
        """Both metrics must appear — not collapsed into a single 'proxy accuracy' value.

        A single blended 'accuracy' percentage hides whether the proxy is
        confidently wrong vs. self-correcting, which is scientifically meaningful.
        """
        content = _read_stats_doc()
        self.assertIn('action_match_rate', content)
        self.assertIn('prior_calibration', content)
        # They must appear as separate entries, not as aliases for the same thing.
        amr_idx = content.index('action_match_rate')
        pc_idx = content.index('prior_calibration')
        self.assertNotEqual(
            amr_idx, pc_idx,
            "action_match_rate and prior_calibration must appear as separate entries.",
        )


class TestNoUnsupportedTimeSeries(unittest.TestCase):
    """The proxy accuracy section must not claim a 7-day time-series without schema support.

    proxy_accuracy has one row per (state, task_type) with a last_updated TEXT field.
    proxy_chunks.traces stores interaction counters, not wall-clock timestamps.
    Neither table supports per-day bucketing without schema additions.
    """

    def test_proxy_accuracy_trend_chart_is_not_listed_as_time_series(self):
        """The Charts table must not list 'Proxy Accuracy Trend' with Date on the x-axis
        without an explanation of how per-day data is obtained.

        If the chart is reframed as an aggregate or per-context display, or if the doc
        explicitly notes that the time-series variant requires future schema work, the
        requirement is met.
        """
        content = _read_stats_doc()
        # The problem pattern: 'Proxy Accuracy Trend' with 'Date' in the same table row
        # (pipe-separated markdown table).
        lines = content.splitlines()
        for line in lines:
            if 'Proxy Accuracy Trend' in line and '| Date |' in line:
                self.fail(
                    f"stats.md claims a 7-day proxy accuracy trend chart sourced by date: {line!r}. "
                    "The proxy_accuracy table has no per-day time-series structure. "
                    "Either reframe the chart or document the schema path explicitly.",
                )


class TestPrerequisiteAnnotations(unittest.TestCase):
    """Proxy accuracy metrics must be marked as dependent on open prerequisites."""

    def test_issue_231_referenced_in_proxy_accuracy_section(self):
        """#231 (confidence threshold recalibration) must be mentioned near proxy accuracy.

        Consumers of this spec need to know the accuracy metrics require #231 before
        interpreting thresholds as meaningful.
        """
        content = _read_stats_doc()
        self.assertIn(
            '#231',
            content,
            "stats.md must reference #231 (proxy confidence threshold recalibration) "
            "as a prerequisite for the accuracy metrics.",
        )

    def test_issue_221_referenced_in_proxy_accuracy_section(self):
        """#221 (evaluation harness) must be mentioned near proxy accuracy.

        The accuracy metrics are not meaningful until the evaluation harness is built.
        """
        content = _read_stats_doc()
        self.assertIn(
            '#221',
            content,
            "stats.md must reference #221 (evaluation harness) as a prerequisite "
            "for the proxy accuracy metrics.",
        )
