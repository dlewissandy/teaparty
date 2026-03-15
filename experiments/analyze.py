"""Analysis utilities — load results, compute statistics, compare conditions.

All analysis reads from the JSONL event files and metrics.json summaries
written by EventCollector. No external dependencies beyond scipy for
statistical tests.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any


def _default_results_base() -> str:
    """Default results directory: experiments/results/"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')


def load_all_runs(
    experiment: str,
    results_base: str = '',
) -> list[dict[str, Any]]:
    """Load metrics.json from every run of an experiment.

    Returns a list of metrics dicts, each augmented with 'results_dir'.
    """
    base = results_base or _default_results_base()
    exp_dir = os.path.join(base, experiment)

    if not os.path.isdir(exp_dir):
        return []

    runs = []
    # Walk experiment/<condition>/<task_id>/metrics.json
    for condition in sorted(os.listdir(exp_dir)):
        cond_dir = os.path.join(exp_dir, condition)
        if not os.path.isdir(cond_dir):
            continue
        for task_id in sorted(os.listdir(cond_dir)):
            metrics_path = os.path.join(cond_dir, task_id, 'metrics.json')
            if os.path.isfile(metrics_path):
                try:
                    with open(metrics_path) as f:
                        metrics = json.load(f)
                    metrics['results_dir'] = os.path.join(cond_dir, task_id)
                    runs.append(metrics)
                except (json.JSONDecodeError, OSError):
                    continue

    return runs


def group_by_condition(runs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group runs by condition name."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        cond = run.get('condition', 'unknown')
        groups.setdefault(cond, []).append(run)
    return groups


def condition_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary statistics for a group of runs in one condition."""
    n = len(runs)
    if n == 0:
        return {'n': 0}

    backtracks = [r.get('backtrack_count', 0) for r in runs]
    elapsed = [r.get('elapsed_seconds', 0) for r in runs]
    proxy_autos = [r.get('proxy', {}).get('auto_approvals', 0) for r in runs]
    proxy_escalations = [r.get('proxy', {}).get('escalations', 0) for r in runs]
    proxy_confs = [r.get('proxy', {}).get('mean_confidence', 0) for r in runs]
    transitions = [r.get('state_transitions', 0) for r in runs]

    # Token accounting
    total_tokens = [r.get('tokens', {}).get('total_tokens', 0) for r in runs]
    input_tokens = [r.get('tokens', {}).get('input_tokens', 0) for r in runs]
    output_tokens = [r.get('tokens', {}).get('output_tokens', 0) for r in runs]
    cost_usd = [r.get('tokens', {}).get('cost_usd', 0) for r in runs]

    # Quality ratings (only include runs that have ratings)
    quality_overall = [r['quality_rating'] for r in runs if 'quality_rating' in r]
    quality_correctness = [r.get('ratings', {}).get('correctness', 0) for r in runs
                           if 'ratings' in r]
    quality_completeness = [r.get('ratings', {}).get('completeness', 0) for r in runs
                            if 'ratings' in r]
    quality_code = [r.get('ratings', {}).get('code_quality', 0) for r in runs
                    if 'ratings' in r]

    terminal_states = {}
    for r in runs:
        ts = r.get('terminal_state', 'unknown')
        terminal_states[ts] = terminal_states.get(ts, 0) + 1

    completed = terminal_states.get('COMPLETED_WORK', 0)

    summary = {
        'n': n,
        'completed': completed,
        'completion_rate': completed / n if n else 0,
        'terminal_states': terminal_states,
        'backtracks': _descriptive_stats(backtracks),
        'elapsed_seconds': _descriptive_stats(elapsed),
        'state_transitions': _descriptive_stats(transitions),
        'proxy_auto_approvals': _descriptive_stats(proxy_autos),
        'proxy_escalations': _descriptive_stats(proxy_escalations),
        'proxy_mean_confidence': _descriptive_stats(proxy_confs),
        'total_tokens': _descriptive_stats(total_tokens),
        'input_tokens': _descriptive_stats(input_tokens),
        'output_tokens': _descriptive_stats(output_tokens),
        'cost_usd': _descriptive_stats(cost_usd),
    }

    # Only include quality stats if any ratings exist
    if quality_overall:
        summary['quality_overall'] = _descriptive_stats(quality_overall)
        summary['quality_correctness'] = _descriptive_stats(quality_correctness)
        summary['quality_completeness'] = _descriptive_stats(quality_completeness)
        summary['quality_code'] = _descriptive_stats(quality_code)
        summary['rated_runs'] = len(quality_overall)

    return summary


def _descriptive_stats(values: list[float]) -> dict[str, float]:
    """Compute mean, median, std, min, max for a list of values."""
    n = len(values)
    if n == 0:
        return {'mean': 0, 'median': 0, 'std': 0, 'min': 0, 'max': 0, 'n': 0}

    sorted_v = sorted(values)
    mean = sum(values) / n
    median = sorted_v[n // 2] if n % 2 == 1 else (sorted_v[n // 2 - 1] + sorted_v[n // 2]) / 2
    variance = sum((x - mean) ** 2 for x in values) / (n - 1) if n > 1 else 0
    std = math.sqrt(variance)

    return {
        'mean': round(mean, 4),
        'median': round(median, 4),
        'std': round(std, 4),
        'min': round(min(values), 4),
        'max': round(max(values), 4),
        'n': n,
    }


def compare_conditions(
    runs: list[dict[str, Any]],
    metric_path: str = 'backtrack_count',
) -> dict[str, Any]:
    """Compare a metric across conditions using Wilcoxon rank-sum test.

    Args:
        runs: all runs for an experiment
        metric_path: dot-delimited path to the metric (e.g., 'backtrack_count',
                     'proxy.mean_confidence')

    Returns:
        dict with per-condition stats and pairwise comparisons
    """
    groups = group_by_condition(runs)
    condition_names = sorted(groups.keys())

    # Extract metric values per condition
    condition_values: dict[str, list[float]] = {}
    for cond, cond_runs in groups.items():
        values = []
        for r in cond_runs:
            val = _extract_metric(r, metric_path)
            if val is not None:
                values.append(float(val))
        condition_values[cond] = values

    # Pairwise comparisons
    comparisons = []
    try:
        from scipy.stats import mannwhitneyu
        has_scipy = True
    except ImportError:
        has_scipy = False

    if has_scipy and len(condition_names) >= 2:
        for i, c1 in enumerate(condition_names):
            for c2 in condition_names[i + 1:]:
                v1, v2 = condition_values[c1], condition_values[c2]
                if len(v1) >= 2 and len(v2) >= 2:
                    try:
                        stat, p = mannwhitneyu(v1, v2, alternative='two-sided')
                        effect = _cohens_d(v1, v2)
                        comparisons.append({
                            'condition_a': c1,
                            'condition_b': c2,
                            'u_statistic': round(stat, 4),
                            'p_value': round(p, 6),
                            'cohens_d': round(effect, 4),
                            'significant': p < 0.05,
                        })
                    except Exception:
                        pass

    return {
        'metric': metric_path,
        'conditions': {
            cond: _descriptive_stats(condition_values.get(cond, []))
            for cond in condition_names
        },
        'comparisons': comparisons,
    }


def _extract_metric(run: dict, path: str) -> Any:
    """Extract a nested metric by dot path (e.g., 'proxy.mean_confidence')."""
    parts = path.split('.')
    obj = run
    for part in parts:
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


def _cohens_d(group1: list[float], group2: list[float]) -> float:
    """Compute Cohen's d effect size."""
    n1, n2 = len(group1), len(group2)
    if n1 < 2 or n2 < 2:
        return 0.0

    mean1 = sum(group1) / n1
    mean2 = sum(group2) / n2

    var1 = sum((x - mean1) ** 2 for x in group1) / (n1 - 1)
    var2 = sum((x - mean2) ** 2 for x in group2) / (n2 - 1)

    pooled_std = math.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
    if pooled_std == 0:
        return 0.0

    return (mean1 - mean2) / pooled_std


def analyze_experiment(
    experiment: str,
    results_base: str = '',
) -> dict[str, Any]:
    """Full analysis of an experiment: per-condition summaries + comparisons.

    Returns a dict suitable for report generation.
    """
    runs = load_all_runs(experiment, results_base)

    if not runs:
        return {
            'experiment': experiment,
            'total_runs': 0,
            'conditions': {},
            'comparisons': {},
            'error': f'No results found for experiment {experiment!r}',
        }

    groups = group_by_condition(runs)

    summaries = {}
    for cond, cond_runs in sorted(groups.items()):
        summaries[cond] = condition_summary(cond_runs)

    # Compare key metrics across conditions
    metrics_to_compare = [
        'backtrack_count',
        'elapsed_seconds',
        'state_transitions',
        'proxy.mean_confidence',
        'proxy.auto_approvals',
        'tokens.total_tokens',
        'tokens.cost_usd',
        'quality_rating',
    ]

    comparisons = {}
    for metric in metrics_to_compare:
        comparisons[metric] = compare_conditions(runs, metric)

    return {
        'experiment': experiment,
        'total_runs': len(runs),
        'conditions': summaries,
        'comparisons': comparisons,
    }
