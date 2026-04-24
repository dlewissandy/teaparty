"""CLI entry point for the experimentation harness.

Usage:
    # Run a single experiment task
    python -m experiments run \\
        --experiment proxy-convergence \\
        --condition dual-signal \\
        --task "Add a health check endpoint" \\
        --task-id pc-001

    # Run all tasks in a corpus file
    python -m experiments run-corpus \\
        --corpus experiments/corpus/proxy-convergence.yaml \\
        --condition dual-signal

    # Add quality ratings to completed runs
    python -m experiments rate \\
        --experiment proxy-convergence

    # Analyze collected results
    python -m experiments analyze \\
        --experiment proxy-convergence

    # Generate markdown report
    python -m experiments report \\
        --experiment proxy-convergence

    # Generate plots
    python -m experiments plot \\
        --experiment proxy-convergence
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add flags shared across run subcommands."""
    parser.add_argument('--project', default='POC', help='Project slug (default: POC)')
    parser.add_argument('--flat', action='store_true', help='Disable hierarchical dispatch')
    parser.add_argument('--skip-intent', action='store_true', help='Skip intent phase')
    parser.add_argument('--skip-learnings', action='store_true', help='Skip learning extraction')
    parser.add_argument('--execute-only', action='store_true', help='Skip intent+planning')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose event output')
    parser.add_argument('--results-base', default='', help='Override results directory base')

    # Input provider options
    parser.add_argument('--input-mode', default='pattern',
                        choices=['pattern', 'scripted', 'auto-approve'],
                        help='Input provider mode (default: pattern)')
    parser.add_argument('--approval-seed', type=int, default=42,
                        help='RNG seed for pattern provider')
    parser.add_argument('--default-rate', type=float, default=0.85,
                        help='Default approval rate for pattern provider')
    parser.add_argument('--correction-feedback', default='Please add error handling',
                        help='Feedback text for corrections')

    # Experiment overrides
    parser.add_argument('--no-backtracks', action='store_true',
                        help='Suppress CfA backtracks (forward-only baseline)')

    # Rating collection
    parser.add_argument('--collect-ratings', action='store_true',
                        help='Prompt for human quality ratings after each run')


def _build_overrides(args: argparse.Namespace) -> dict:
    """Extract override kwargs from parsed args."""
    overrides = {}
    if args.flat:
        overrides['flat'] = True
    if args.skip_intent:
        overrides['skip_intent'] = True
    if args.skip_learnings:
        overrides['skip_learnings'] = True
    if args.execute_only:
        overrides['execute_only'] = True
    if args.project != 'POC':
        overrides['project'] = args.project
    if args.results_base:
        overrides['results_base'] = args.results_base
    if args.no_backtracks:
        overrides['backtracks_enabled'] = False
    return overrides


def cmd_run(args: argparse.Namespace) -> int:
    """Run a single experiment task."""
    from experiments.config import ExperimentConfig
    from experiments.runner import ExperimentRunner

    overrides = _build_overrides(args)

    config = ExperimentConfig(
        experiment=args.experiment,
        condition=args.condition,
        task=args.task,
        task_id=args.task_id,
        project=args.project,
        flat=overrides.get('flat', False),
        skip_intent=overrides.get('skip_intent', False),
        skip_learnings=overrides.get('skip_learnings', False),
        execute_only=overrides.get('execute_only', False),
        backtracks_enabled=not args.no_backtracks,
        input_mode=args.input_mode,
        approval_seed=args.approval_seed,
        correction_feedback=args.correction_feedback,
        default_rate=args.default_rate,
        results_base=args.results_base,
    )

    runner = ExperimentRunner(
        config, verbose=args.verbose, collect_ratings=args.collect_ratings,
    )
    metrics = asyncio.run(runner.run())

    # Print summary to stdout
    print(json.dumps(metrics, indent=2))
    return 0


def cmd_run_corpus(args: argparse.Namespace) -> int:
    """Run all tasks in a corpus file."""
    from experiments.runner import run_corpus

    overrides = _build_overrides(args)
    overrides['input_mode'] = args.input_mode
    overrides['approval_seed'] = args.approval_seed
    overrides['correction_feedback'] = args.correction_feedback
    overrides['default_rate'] = args.default_rate

    results = asyncio.run(run_corpus(
        corpus_path=args.corpus,
        condition=args.condition,
        verbose=args.verbose,
        **overrides,
    ))

    # Print summary
    completed = sum(1 for r in results if r.get('terminal_state') == 'COMPLETED_WORK')
    total = len(results)
    print(f'\n{completed}/{total} tasks completed successfully', file=sys.stderr)
    print(json.dumps(results, indent=2))
    return 0 if completed == total else 1


def cmd_analyze(args: argparse.Namespace) -> int:
    """Analyze collected experiment results."""
    from experiments.analyze import analyze_experiment

    report = analyze_experiment(
        experiment=args.experiment,
        results_base=args.results_base,
    )

    if args.format == 'json':
        print(json.dumps(report, indent=2, default=str))
    else:
        from experiments.report import format_analysis
        print(format_analysis(report))

    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Generate a markdown report for an experiment."""
    from experiments.analyze import analyze_experiment
    from experiments.report import full_report

    report = analyze_experiment(
        experiment=args.experiment,
        results_base=args.results_base,
    )
    print(full_report(report))
    return 0


def cmd_rate(args: argparse.Namespace) -> int:
    """Add or update quality ratings for experiment results."""
    import os
    from experiments.analyze import _default_results_base, load_all_runs
    from experiments.ratings import (
        collect_rating_interactive,
        load_ratings,
        write_ratings,
    )

    base = args.results_base or _default_results_base()
    runs = load_all_runs(args.experiment, results_base=base)

    if not runs:
        print(f'No results found for experiment {args.experiment!r}', file=sys.stderr)
        return 1

    rated = 0
    skipped = 0
    for run in runs:
        results_dir = run.get('results_dir', '')
        if not results_dir:
            continue

        existing = load_ratings(results_dir)
        if existing and existing.is_valid() and not args.force:
            skipped += 1
            continue

        task = run.get('task', run.get('task_id', '?'))
        cond = run.get('condition', '?')
        task_id = run.get('task_id', os.path.basename(results_dir))

        print(f'\n--- {args.experiment}/{cond}/{task_id} ---', file=sys.stderr)

        rating = collect_rating_interactive(task_description=task)
        write_ratings(results_dir, rating)

        # Update metrics.json with quality_rating
        metrics_path = os.path.join(results_dir, 'metrics.json')
        if os.path.isfile(metrics_path):
            with open(metrics_path) as f:
                metrics = json.load(f)
            metrics['quality_rating'] = rating.overall
            metrics['ratings'] = rating.to_dict()
            with open(metrics_path, 'w') as f:
                json.dump(metrics, f, indent=2, default=str)

        rated += 1

    print(f'\nRated {rated} runs, skipped {skipped} (already rated)', file=sys.stderr)
    return 0


def cmd_plot(args: argparse.Namespace) -> int:
    """Generate plots for an experiment."""
    from experiments.plotting import save_experiment_plots

    saved = save_experiment_plots(
        experiment=args.experiment,
        results_base=args.results_base,
        output_dir=args.output_dir,
    )

    if not saved:
        print(f'No results found for experiment {args.experiment!r}', file=sys.stderr)
        return 1

    for path in saved:
        print(path)
    print(f'\n{len(saved)} plots saved', file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog='python -m experiments',
        description='TeaParty experimentation harness',
    )
    sub = parser.add_subparsers(dest='command')

    # ── run ──
    p_run = sub.add_parser('run', help='Run a single experiment task')
    p_run.add_argument('--experiment', required=True, help='Experiment name')
    p_run.add_argument('--condition', required=True, help='Condition name')
    p_run.add_argument('--task', required=True, help='Task description text')
    p_run.add_argument('--task-id', required=True, help='Task ID for result organization')
    _add_common_args(p_run)

    # ── run-corpus ──
    p_corpus = sub.add_parser('run-corpus', help='Run all tasks in a corpus file')
    p_corpus.add_argument('--corpus', required=True, help='Path to corpus YAML file')
    p_corpus.add_argument('--condition', default='', help='Condition override')
    _add_common_args(p_corpus)

    # ── analyze ──
    p_analyze = sub.add_parser('analyze', help='Analyze collected results')
    p_analyze.add_argument('--experiment', required=True, help='Experiment name')
    p_analyze.add_argument('--results-base', default='', help='Results directory override')
    p_analyze.add_argument('--format', choices=['markdown', 'json'], default='markdown',
                           help='Output format')

    # ── report ──
    p_report = sub.add_parser('report', help='Generate markdown report')
    p_report.add_argument('--experiment', required=True, help='Experiment name')
    p_report.add_argument('--results-base', default='', help='Results directory override')

    # ── rate ──
    p_rate = sub.add_parser('rate', help='Add quality ratings to experiment results')
    p_rate.add_argument('--experiment', required=True, help='Experiment name')
    p_rate.add_argument('--results-base', default='', help='Results directory override')
    p_rate.add_argument('--force', action='store_true',
                        help='Re-rate runs that already have ratings')

    # ── plot ──
    p_plot = sub.add_parser('plot', help='Generate plots for an experiment')
    p_plot.add_argument('--experiment', required=True, help='Experiment name')
    p_plot.add_argument('--results-base', default='', help='Results directory override')
    p_plot.add_argument('--output-dir', default='', help='Output directory for PNGs')

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    commands = {
        'run': cmd_run,
        'run-corpus': cmd_run_corpus,
        'analyze': cmd_analyze,
        'report': cmd_report,
        'rate': cmd_rate,
        'plot': cmd_plot,
    }
    return commands[args.command](args)


if __name__ == '__main__':
    sys.exit(main())
