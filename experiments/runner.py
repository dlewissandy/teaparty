"""ExperimentRunner — wraps Session with event collection.

Orchestrates a single experiment run:
  1. Creates the results directory
  2. Sets up EventBus with EventCollector
  3. Selects the InputProvider based on config
  4. Runs the Session
  5. Writes summary metrics
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import asdict
from typing import Any

from experiments.collector import EventCollector
from experiments.config import ExperimentConfig
from experiments.input_providers import make_provider
from teaparty.messaging.bus import EventBus
from teaparty.cfa.session import Session, SessionResult

_log = logging.getLogger('experiments.runner')


class ExperimentRunner:
    """Run a single experiment configuration and collect structured results.

    Usage:
        runner = ExperimentRunner(config)
        result = await runner.run()
        # Results are written to config.results_dir/
    """

    def __init__(
        self,
        config: ExperimentConfig,
        *,
        verbose: bool = False,
        collect_ratings: bool = False,
    ):
        self.config = config
        self.verbose = verbose
        self.collect_ratings = collect_ratings
        self._collector: EventCollector | None = None

    async def run(self) -> dict[str, Any]:
        """Execute the experiment run. Returns the summary metrics dict."""
        config = self.config
        results_dir = config.results_dir
        os.makedirs(results_dir, exist_ok=True)

        # 1. Write config snapshot
        config_path = os.path.join(results_dir, 'config.json')
        with open(config_path, 'w') as f:
            json.dump(asdict(config), f, indent=2, default=str)

        # 2. Set up EventBus + collector
        event_bus = EventBus()
        collector = EventCollector(
            output_dir=results_dir,
            experiment=config.experiment,
            condition=config.condition,
            run_id=config.task_id,
        )
        self._collector = collector
        event_bus.subscribe(collector.on_event)

        # 3. Optional: verbose event printer for debugging
        if self.verbose:
            from teaparty.__main__ import CLIEventPrinter
            printer = CLIEventPrinter(verbose=True)
            event_bus.subscribe(printer)

        # 4. Create input provider
        provider = make_provider(
            mode=config.input_mode,
            rates=config.approval_rates or None,
            seed=config.approval_seed,
            script=config.scripted_decisions or None,
            correction_feedback=config.correction_feedback,
            default_rate=config.default_rate,
        )

        # 5. Find POC root
        poc_root = self._find_poc_root()

        # 6. Create and run Session
        start_time = time.time()
        try:
            session = Session(
                task=config.task,
                poc_root=poc_root,
                project_override=config.project,
                skip_learnings=config.skip_learnings,
                flat=config.flat,
                suppress_backtracks=not config.backtracks_enabled,
                proxy_enabled=config.proxy_enabled,
                event_bus=event_bus,
                input_provider=provider,
            )

            session_result = await session.run()
        except Exception as exc:
            _log.error('Session failed: %s', exc, exc_info=True)
            session_result = SessionResult(
                terminal_state='EXPERIMENT_ERROR',
                project=config.project,
                session_id='',
                backtrack_count=0,
            )

        elapsed = time.time() - start_time

        # 8. Write session result
        session_result_path = os.path.join(results_dir, 'session_result.json')
        with open(session_result_path, 'w') as f:
            json.dump({
                'terminal_state': session_result.terminal_state,
                'project': session_result.project,
                'session_id': session_result.session_id,
                'backtrack_count': session_result.backtrack_count,
                'elapsed_seconds': round(elapsed, 2),
            }, f, indent=2)

        # 9. Write summary metrics
        metrics_path = collector.write_metrics()

        # 10. Augment metrics with timing and cumulative proxy state
        metrics = collector.summarize()
        metrics['elapsed_seconds'] = round(elapsed, 2)

        # Include cumulative proxy state from the model file (for corpus runs)
        proxy_path = config.proxy_model_path
        if os.path.isfile(proxy_path):
            try:
                with open(proxy_path) as f:
                    proxy_model = json.load(f)
                entries = proxy_model.get('entries', {})
                total = sum(e.get('total_decisions', 0) for e in entries.values())
                metrics['proxy_cumulative'] = {
                    'total_decisions': total,
                    'states_seen': list(entries.keys()),
                    'model_path': proxy_path,
                    'per_state': {
                        state: {
                            'total_decisions': e.get('total_decisions', 0),
                            'auto_approved': e.get('auto_approved', 0),
                            'escalated': e.get('escalated', 0),
                        }
                        for state, e in entries.items()
                    },
                }
            except Exception:
                pass

        # Re-write with elapsed and proxy_cumulative included
        with open(metrics_path, 'w') as f:
            json.dump(metrics, f, indent=2, default=str)

        # 11. Collect human quality ratings if requested
        if self.collect_ratings:
            from experiments.ratings import collect_rating_interactive, write_ratings
            rating = collect_rating_interactive(task_description=config.task)
            write_ratings(results_dir, rating)
            metrics['quality_rating'] = rating.overall
            metrics['ratings'] = rating.to_dict()
            # Re-write metrics with ratings included
            with open(metrics_path, 'w') as f:
                json.dump(metrics, f, indent=2, default=str)

        _log.info(
            'Run complete: %s/%s/%s → %s (%.1fs)',
            config.experiment, config.condition, config.task_id,
            session_result.terminal_state, elapsed,
        )

        return metrics

    @staticmethod
    def _find_poc_root() -> str:
        """Locate the repo root (contains pyproject.toml)."""
        d = os.path.dirname(os.path.abspath(__file__))
        while d != '/':
            if os.path.exists(os.path.join(d, 'pyproject.toml')):
                return d
            d = os.path.dirname(d)

        raise RuntimeError('Could not find repo root (pyproject.toml)')


async def run_corpus(
    corpus_path: str,
    condition: str = '',
    *,
    verbose: bool = False,
    proxy_model_path: str = '',
    **overrides: Any,
) -> list[dict[str, Any]]:
    """Run all tasks in a corpus file under a single condition.

    Args:
        corpus_path: path to the YAML corpus file
        condition: condition name (overrides corpus default)
        verbose: enable verbose event printing
        proxy_model_path: shared proxy model path for cross-task persistence.
            When set, all tasks in the corpus share this proxy model file
            so the proxy's confidence evolves across the full corpus.
        **overrides: passed to CorpusConfig.make_config()

    Returns:
        List of metrics dicts, one per task.
    """
    from experiments.config import load_corpus

    corpus = load_corpus(corpus_path)
    results = []

    # Pass shared proxy model path to all tasks for cross-task persistence
    if proxy_model_path:
        overrides['proxy_model_path'] = proxy_model_path

    for i, task in enumerate(corpus.tasks):
        config = corpus.make_config(task, condition=condition, **overrides)
        print(
            f'\n{"=" * 60}\n'
            f'[{i + 1}/{len(corpus.tasks)}] {config.experiment}/{config.condition}/{config.task_id}\n'
            f'  Task: {config.task[:80]}\n'
            f'{"=" * 60}',
            file=sys.stderr,
        )

        runner = ExperimentRunner(config, verbose=verbose)
        metrics = await runner.run()
        results.append(metrics)

        print(
            f'  → {metrics.get("terminal_state", "?")} '
            f'({metrics.get("elapsed_seconds", 0):.1f}s, '
            f'{metrics.get("backtrack_count", 0)} backtracks)',
            file=sys.stderr,
        )

    return results
