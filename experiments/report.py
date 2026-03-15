"""Report generation — markdown tables and formatted output from analysis results.

Takes the dict output from analyze.analyze_experiment() and produces
human-readable markdown reports.
"""
from __future__ import annotations

from typing import Any


def markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    """Generate a markdown table from a list of row dicts.

    Args:
        rows: list of dicts, each containing values for the columns
        columns: ordered list of column keys to include
    """
    if not rows or not columns:
        return ''

    # Header
    header = '| ' + ' | '.join(columns) + ' |'
    separator = '| ' + ' | '.join('---' for _ in columns) + ' |'

    # Rows
    lines = [header, separator]
    for row in rows:
        cells = []
        for col in columns:
            val = row.get(col, '')
            if isinstance(val, float):
                cells.append(f'{val:.4f}')
            else:
                cells.append(str(val))
        lines.append('| ' + ' | '.join(cells) + ' |')

    return '\n'.join(lines)


def format_stats(stats: dict[str, float], label: str = '') -> str:
    """Format descriptive stats as a compact string."""
    if not stats or stats.get('n', 0) == 0:
        return f'{label}: no data' if label else 'no data'

    parts = [
        f'mean={stats["mean"]:.2f}',
        f'median={stats["median"]:.2f}',
        f'std={stats["std"]:.2f}',
        f'range=[{stats["min"]:.2f}, {stats["max"]:.2f}]',
        f'n={stats["n"]}',
    ]
    prefix = f'{label}: ' if label else ''
    return prefix + ', '.join(parts)


def format_analysis(report: dict[str, Any]) -> str:
    """Format an analysis report as markdown."""
    lines = []
    experiment = report.get('experiment', 'unknown')
    total = report.get('total_runs', 0)

    lines.append(f'# Analysis: {experiment}')
    lines.append(f'\nTotal runs: {total}\n')

    if report.get('error'):
        lines.append(f'**Error:** {report["error"]}\n')
        return '\n'.join(lines)

    # Per-condition summary
    conditions = report.get('conditions', {})
    if conditions:
        lines.append('## Condition Summaries\n')
        for cond, summary in sorted(conditions.items()):
            n = summary.get('n', 0)
            completed = summary.get('completed', 0)
            rate = summary.get('completion_rate', 0)
            lines.append(f'### {cond} (n={n}, completed={completed}, rate={rate:.0%})\n')

            # Terminal states
            ts = summary.get('terminal_states', {})
            if ts:
                lines.append('**Terminal states:**')
                for state, count in sorted(ts.items()):
                    lines.append(f'- {state}: {count}')
                lines.append('')

            # Key metrics
            for metric_name in ['backtracks', 'elapsed_seconds', 'state_transitions',
                                'proxy_auto_approvals', 'proxy_escalations',
                                'proxy_mean_confidence']:
                stats = summary.get(metric_name, {})
                if stats and stats.get('n', 0) > 0:
                    lines.append(f'- {format_stats(stats, metric_name)}')

            # Quality ratings (if any runs were rated)
            if summary.get('rated_runs'):
                lines.append(f'\n**Quality ratings** ({summary["rated_runs"]} rated):')
                for qm in ['quality_overall', 'quality_correctness',
                            'quality_completeness', 'quality_code']:
                    stats = summary.get(qm, {})
                    if stats and stats.get('n', 0) > 0:
                        lines.append(f'- {format_stats(stats, qm)}')
            lines.append('')

    # Comparisons
    comparisons = report.get('comparisons', {})
    if comparisons:
        lines.append('## Statistical Comparisons\n')
        for metric, comp in sorted(comparisons.items()):
            lines.append(f'### {metric}\n')
            comp_list = comp.get('comparisons', [])
            if comp_list:
                rows = []
                for c in comp_list:
                    rows.append({
                        'A': c['condition_a'],
                        'B': c['condition_b'],
                        'U': c['u_statistic'],
                        'p': c['p_value'],
                        'd': c['cohens_d'],
                        'sig': 'yes' if c['significant'] else 'no',
                    })
                lines.append(markdown_table(rows, ['A', 'B', 'U', 'p', 'd', 'sig']))
            else:
                lines.append('*Insufficient data for comparison.*')
            lines.append('')

    return '\n'.join(lines)


def full_report(report: dict[str, Any]) -> str:
    """Generate a complete markdown report suitable for docs.

    Includes analysis plus context about the experiment.
    """
    lines = []
    experiment = report.get('experiment', 'unknown')
    total = report.get('total_runs', 0)

    lines.append(f'# Experiment Report: {experiment}')
    lines.append(f'\n*Generated from {total} runs.*\n')

    if report.get('error'):
        lines.append(f'> {report["error"]}\n')
        return '\n'.join(lines)

    # Overview table: one row per condition
    conditions = report.get('conditions', {})
    if conditions:
        lines.append('## Overview\n')
        has_quality = any(s.get('quality_overall') for s in conditions.values())
        overview_rows = []
        for cond, summary in sorted(conditions.items()):
            bt = summary.get('backtracks', {})
            elapsed = summary.get('elapsed_seconds', {})
            proxy = summary.get('proxy_mean_confidence', {})
            quality = summary.get('quality_overall', {})
            row = {
                'Condition': cond,
                'N': summary.get('n', 0),
                'Completed': summary.get('completed', 0),
                'Rate': f'{summary.get("completion_rate", 0):.0%}',
                'Backtracks (mean)': f'{bt.get("mean", 0):.1f}',
                'Time (mean)': f'{elapsed.get("mean", 0):.0f}s',
                'Proxy Conf (mean)': f'{proxy.get("mean", 0):.3f}',
            }
            if has_quality:
                row['Quality (mean)'] = f'{quality.get("mean", 0):.1f}'
            overview_rows.append(row)

        columns = ['Condition', 'N', 'Completed', 'Rate',
                    'Backtracks (mean)', 'Time (mean)', 'Proxy Conf (mean)']
        if has_quality:
            columns.append('Quality (mean)')
        lines.append(markdown_table(overview_rows, columns))
        lines.append('')

    # Detailed analysis
    lines.append(format_analysis(report))

    return '\n'.join(lines)
