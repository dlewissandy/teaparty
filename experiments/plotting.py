"""Plotting utilities — convergence curves, box plots, cost-quality frontiers.

Produces matplotlib figures from experiment results. All plot functions
return a matplotlib Figure so callers can save to file or display inline.

matplotlib is an optional dependency. Functions raise ImportError with a
clear message if it's not installed.
"""
from __future__ import annotations

import os
from typing import Any

from experiments.analyze import (
    _extract_metric,
    group_by_condition,
    load_all_runs,
)


def _require_matplotlib():
    """Import and return matplotlib.pyplot, raising if unavailable."""
    try:
        import matplotlib
        matplotlib.use('Agg')  # non-interactive backend for CI/headless
        import matplotlib.pyplot as plt
        return plt
    except ImportError:
        raise ImportError(
            'matplotlib is required for plotting. '
            'Install it with: uv add --dev matplotlib'
        )


# ── Convergence Curves ────────────────────────────────────────────────────────


def plot_convergence(
    runs: list[dict[str, Any]],
    metric_path: str = 'proxy.mean_confidence',
    title: str = '',
    ylabel: str = '',
) -> Any:
    """Plot a metric over sequential tasks to show convergence behavior.

    Each condition is plotted as a separate line. Tasks are ordered by
    their position in the run list (assumed sequential within condition).

    Args:
        runs: list of metrics dicts from load_all_runs()
        metric_path: dot-delimited metric path (e.g., 'proxy.mean_confidence')
        title: plot title (auto-generated if empty)
        ylabel: y-axis label (auto-generated if empty)

    Returns:
        matplotlib Figure
    """
    plt = _require_matplotlib()
    groups = group_by_condition(runs)

    fig, ax = plt.subplots(figsize=(10, 6))

    for cond_name, cond_runs in sorted(groups.items()):
        values = []
        for r in cond_runs:
            val = _extract_metric(r, metric_path)
            values.append(float(val) if val is not None else 0.0)

        x = list(range(1, len(values) + 1))
        ax.plot(x, values, marker='o', markersize=4, label=cond_name, linewidth=1.5)

    ax.set_xlabel('Task sequence')
    ax.set_ylabel(ylabel or metric_path)
    ax.set_title(title or f'Convergence: {metric_path}')
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return fig


# ── Box Plots ─────────────────────────────────────────────────────────────────


def plot_box(
    runs: list[dict[str, Any]],
    metric_path: str = 'elapsed_seconds',
    title: str = '',
    ylabel: str = '',
) -> Any:
    """Box plot comparing a metric across conditions.

    Args:
        runs: list of metrics dicts
        metric_path: dot-delimited metric path
        title: plot title
        ylabel: y-axis label

    Returns:
        matplotlib Figure
    """
    plt = _require_matplotlib()
    groups = group_by_condition(runs)

    condition_names = sorted(groups.keys())
    data = []
    for cond in condition_names:
        values = []
        for r in groups[cond]:
            val = _extract_metric(r, metric_path)
            if val is not None:
                values.append(float(val))
        data.append(values)

    fig, ax = plt.subplots(figsize=(8, 6))

    bp = ax.boxplot(data, tick_labels=condition_names, patch_artist=True)

    # Color the boxes
    colors = plt.cm.Set2.colors  # type: ignore[attr-defined]
    for i, patch in enumerate(bp['boxes']):
        patch.set_facecolor(colors[i % len(colors)])
        patch.set_alpha(0.7)

    ax.set_ylabel(ylabel or metric_path)
    ax.set_title(title or f'Distribution: {metric_path}')
    ax.grid(True, axis='y', alpha=0.3)
    fig.tight_layout()

    return fig


# ── Cost-Quality Frontier ─────────────────────────────────────────────────────


def plot_cost_quality(
    runs: list[dict[str, Any]],
    cost_metric: str = 'tokens.total_tokens',
    quality_metric: str = 'quality_rating',
    title: str = '',
    xlabel: str = '',
    ylabel: str = '',
) -> Any:
    """Scatter plot of cost vs quality across conditions.

    Each point is a single run. Color distinguishes conditions.
    Identifies the Pareto frontier (runs where no other run is both
    cheaper and higher quality).

    Args:
        runs: list of metrics dicts
        cost_metric: dot-delimited path to cost metric
        quality_metric: dot-delimited path to quality metric
        title: plot title
        xlabel: x-axis label
        ylabel: y-axis label

    Returns:
        matplotlib Figure
    """
    plt = _require_matplotlib()
    groups = group_by_condition(runs)

    fig, ax = plt.subplots(figsize=(10, 7))

    all_costs = []
    all_qualities = []

    colors = plt.cm.Set1.colors  # type: ignore[attr-defined]
    for i, (cond_name, cond_runs) in enumerate(sorted(groups.items())):
        costs = []
        qualities = []
        for r in cond_runs:
            c = _extract_metric(r, cost_metric)
            q = _extract_metric(r, quality_metric)
            if c is not None and q is not None:
                costs.append(float(c))
                qualities.append(float(q))

        color = colors[i % len(colors)]
        ax.scatter(costs, qualities, label=cond_name, color=color, alpha=0.7, s=60)
        all_costs.extend(costs)
        all_qualities.extend(qualities)

    # Draw Pareto frontier
    if all_costs and all_qualities:
        frontier = _pareto_frontier(
            list(zip(all_costs, all_qualities)),
            minimize_x=True, maximize_y=True,
        )
        if len(frontier) >= 2:
            frontier_x, frontier_y = zip(*frontier)
            ax.plot(frontier_x, frontier_y, 'k--', alpha=0.5,
                    linewidth=1.5, label='Pareto frontier')

    ax.set_xlabel(xlabel or cost_metric)
    ax.set_ylabel(ylabel or quality_metric)
    ax.set_title(title or 'Cost-Quality Frontier')
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return fig


def _pareto_frontier(
    points: list[tuple[float, float]],
    minimize_x: bool = True,
    maximize_y: bool = True,
) -> list[tuple[float, float]]:
    """Compute the Pareto frontier from a set of (x, y) points.

    Args:
        points: list of (x, y) tuples
        minimize_x: whether lower x is better
        maximize_y: whether higher y is better

    Returns:
        list of (x, y) tuples on the frontier, sorted by x
    """
    if not points:
        return []

    # Sort by x (ascending if minimizing, descending if maximizing)
    sorted_pts = sorted(points, key=lambda p: p[0], reverse=not minimize_x)

    frontier = []
    best_y = float('-inf') if maximize_y else float('inf')

    for x, y in sorted_pts:
        if maximize_y and y >= best_y:
            frontier.append((x, y))
            best_y = y
        elif not maximize_y and y <= best_y:
            frontier.append((x, y))
            best_y = y

    return sorted(frontier, key=lambda p: p[0])


# ── Proxy Decision Timeline ──────────────────────────────────────────────────


def plot_proxy_decisions(
    runs: list[dict[str, Any]],
    title: str = '',
) -> Any:
    """Plot proxy confidence and decisions over sequential tasks.

    Shows dual-signal confidence (Laplace + EMA) and marks auto-approvals
    vs escalations. Useful for proxy convergence experiments.

    Args:
        runs: list of metrics dicts (single condition)
        title: plot title

    Returns:
        matplotlib Figure
    """
    plt = _require_matplotlib()

    laplace_vals = []
    ema_vals = []
    auto_rates = []

    for r in runs:
        proxy = r.get('proxy', {})
        laplace_vals.append(proxy.get('mean_confidence_laplace', 0))
        ema_vals.append(proxy.get('mean_confidence_ema', 0))
        total = proxy.get('auto_approvals', 0) + proxy.get('escalations', 0)
        rate = proxy.get('auto_approvals', 0) / total if total > 0 else 0
        auto_rates.append(rate)

    x = list(range(1, len(runs) + 1))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    # Top: confidence signals
    ax1.plot(x, laplace_vals, marker='s', markersize=4,
             label='Laplace', linewidth=1.5)
    ax1.plot(x, ema_vals, marker='^', markersize=4,
             label='EMA', linewidth=1.5)
    ax1.set_ylabel('Mean confidence')
    ax1.set_title(title or 'Proxy Convergence: Confidence Signals')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(0, 1.05)

    # Bottom: auto-approval rate
    ax2.bar(x, auto_rates, alpha=0.6, color='steelblue')
    ax2.set_xlabel('Task sequence')
    ax2.set_ylabel('Auto-approval rate')
    ax2.set_ylim(0, 1.05)
    ax2.grid(True, axis='y', alpha=0.3)

    fig.tight_layout()
    return fig


# ── Phase Timing Stacked Bar ─────────────────────────────────────────────────


def plot_phase_timing(
    runs: list[dict[str, Any]],
    title: str = '',
) -> Any:
    """Stacked bar chart of token usage per CfA phase.

    Shows how tokens distribute across intent, planning, and execution
    phases for each task.

    Args:
        runs: list of metrics dicts
        title: plot title

    Returns:
        matplotlib Figure
    """
    plt = _require_matplotlib()
    import numpy as np

    task_ids = []
    intent_tokens = []
    planning_tokens = []
    execution_tokens = []

    for r in runs:
        task_ids.append(r.get('task_id', '?'))
        phases = r.get('tokens', {}).get('phases', {})
        intent_tokens.append(phases.get('intent', {}).get('total_tokens', 0))
        planning_tokens.append(phases.get('planning', {}).get('total_tokens', 0))
        execution_tokens.append(phases.get('execution', {}).get('total_tokens', 0))

    x = np.arange(len(task_ids))
    width = 0.6

    fig, ax = plt.subplots(figsize=(max(8, len(task_ids) * 0.8), 6))

    p1 = ax.bar(x, intent_tokens, width, label='Intent', color='#2196F3', alpha=0.8)
    p2 = ax.bar(x, planning_tokens, width, bottom=intent_tokens,
                label='Planning', color='#FF9800', alpha=0.8)
    bottoms = [i + p for i, p in zip(intent_tokens, planning_tokens)]
    p3 = ax.bar(x, execution_tokens, width, bottom=bottoms,
                label='Execution', color='#4CAF50', alpha=0.8)

    ax.set_xlabel('Task')
    ax.set_ylabel('Tokens')
    ax.set_title(title or 'Token Distribution by CfA Phase')
    ax.set_xticks(x)
    ax.set_xticklabels(task_ids, rotation=45, ha='right', fontsize=8)
    ax.legend()
    ax.grid(True, axis='y', alpha=0.3)
    fig.tight_layout()

    return fig


# ── Convenience: save all plots for an experiment ─────────────────────────────


def save_experiment_plots(
    experiment: str,
    results_base: str = '',
    output_dir: str = '',
) -> list[str]:
    """Generate and save all standard plots for an experiment.

    Args:
        experiment: experiment name
        results_base: override results directory
        output_dir: where to save PNGs (defaults to experiments/plots/<experiment>/)

    Returns:
        list of saved file paths
    """
    plt = _require_matplotlib()

    runs = load_all_runs(experiment, results_base)
    if not runs:
        return []

    if not output_dir:
        output_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'plots', experiment,
        )
    os.makedirs(output_dir, exist_ok=True)

    saved = []

    # 1. Box plots for key metrics
    for metric, label in [
        ('elapsed_seconds', 'Elapsed Time (seconds)'),
        ('backtrack_count', 'Backtrack Count'),
        ('tokens.total_tokens', 'Total Tokens'),
        ('tokens.cost_usd', 'Cost (USD)'),
    ]:
        try:
            fig = plot_box(runs, metric_path=metric, ylabel=label)
            path = os.path.join(output_dir, f'box_{metric.replace(".", "_")}.png')
            fig.savefig(path, dpi=150)
            plt.close(fig)
            saved.append(path)
        except Exception:
            pass

    # 2. Convergence curves
    for metric, label in [
        ('proxy.mean_confidence', 'Proxy Mean Confidence'),
        ('proxy.auto_approvals', 'Auto Approvals'),
    ]:
        try:
            fig = plot_convergence(runs, metric_path=metric, ylabel=label)
            path = os.path.join(output_dir, f'convergence_{metric.replace(".", "_")}.png')
            fig.savefig(path, dpi=150)
            plt.close(fig)
            saved.append(path)
        except Exception:
            pass

    # 3. Cost-quality frontier (only if quality ratings exist)
    has_quality = any(_extract_metric(r, 'quality_rating') is not None for r in runs)
    if has_quality:
        try:
            fig = plot_cost_quality(runs)
            path = os.path.join(output_dir, 'cost_quality_frontier.png')
            fig.savefig(path, dpi=150)
            plt.close(fig)
            saved.append(path)
        except Exception:
            pass

    # 4. Proxy decision timeline (per condition)
    groups = group_by_condition(runs)
    for cond_name, cond_runs in groups.items():
        has_proxy = any(r.get('proxy', {}).get('mean_confidence_laplace', 0) > 0
                        for r in cond_runs)
        if has_proxy:
            try:
                fig = plot_proxy_decisions(
                    cond_runs,
                    title=f'Proxy Convergence: {cond_name}',
                )
                safe_name = cond_name.replace(' ', '_').replace('/', '_')
                path = os.path.join(output_dir, f'proxy_decisions_{safe_name}.png')
                fig.savefig(path, dpi=150)
                plt.close(fig)
                saved.append(path)
            except Exception:
                pass

    return saved
