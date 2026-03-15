"""Tests for issue #133: Proxy persistence and hierarchical event merging.

Bug 1: run_corpus() creates a fresh proxy per task instead of carrying
state across sequential tasks. Each task's metrics should include
cumulative proxy state.

Bug 2: Hierarchical dispatch child processes write events to their own
EventBus which never reaches the parent's EventCollector. Child events
should be written to events.jsonl in the child's infra_dir so they can
be merged post-hoc.
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _run(coro):
    return asyncio.run(coro)


class TestProxyPersistenceInCorpus(unittest.TestCase):
    """run_corpus() must carry proxy state across sequential tasks."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_run_corpus_passes_proxy_model_path_to_runner(self):
        """run_corpus() should pass a shared proxy_model_path so proxy
        state persists across sequential tasks in the corpus.
        """
        from experiments.runner import run_corpus, ExperimentRunner

        # Create a minimal corpus YAML
        corpus_yaml = os.path.join(self.tmpdir, 'test-corpus.yaml')
        Path(corpus_yaml).write_text(
            'experiment: test-proxy\n'
            'default_condition: baseline\n'
            'tasks:\n'
            '  - id: task-1\n'
            '    text: "First task"\n'
            '  - id: task-2\n'
            '    text: "Second task"\n'
        )

        configs_seen = []

        async def fake_run(self_runner):
            configs_seen.append(self_runner.config)
            return {'terminal_state': 'COMPLETED_WORK', 'elapsed_seconds': 1.0}

        with patch.object(ExperimentRunner, 'run', fake_run):
            _run(run_corpus(
                corpus_yaml,
                results_base=self.tmpdir,
                proxy_model_path=os.path.join(self.tmpdir, 'shared-proxy.json'),
            ))

        self.assertEqual(len(configs_seen), 2)
        # Both tasks should have the same proxy_model_path
        for config in configs_seen:
            self.assertEqual(
                config.proxy_model_path,
                os.path.join(self.tmpdir, 'shared-proxy.json'),
                "All corpus tasks must share the same proxy_model_path",
            )

    def test_metrics_include_cumulative_proxy_state(self):
        """Each task's metrics.json should include cumulative proxy state
        (total decisions, confidence per state) from the shared model.
        """
        from experiments.runner import ExperimentRunner
        from experiments.config import ExperimentConfig

        config = ExperimentConfig(
            experiment='test',
            condition='test',
            task='Test task',
            task_id='t1',
            results_base=self.tmpdir,
            proxy_model_path=os.path.join(self.tmpdir, 'proxy.json'),
        )

        # Create a proxy model file with some history
        proxy_model = {
            'entries': {
                'INTENT_ASSERT': {
                    'total_decisions': 5,
                    'auto_approved': 3,
                    'escalated': 2,
                },
            },
            'global_threshold': 0.8,
        }
        Path(config.proxy_model_path).write_text(json.dumps(proxy_model))

        runner = ExperimentRunner(config)

        # Mock Session.run to return quickly
        with patch('experiments.runner.Session') as MockSession:
            mock_session = MockSession.return_value
            mock_session.run = AsyncMock(return_value=MagicMock(
                terminal_state='COMPLETED_WORK',
                project='test',
                session_id='s1',
                backtrack_count=0,
            ))

            metrics = _run(runner.run())

        # Metrics should include cumulative proxy state from the model file
        self.assertIn('proxy_cumulative', metrics,
                      "metrics must include 'proxy_cumulative' with model state")
        cumulative = metrics['proxy_cumulative']
        self.assertIn('total_decisions', cumulative)
        self.assertGreaterEqual(cumulative['total_decisions'], 5)


class TestExperimentConfigProxyModelPath(unittest.TestCase):
    """ExperimentConfig must support proxy_model_path field."""

    def test_config_has_proxy_model_path_field(self):
        from experiments.config import ExperimentConfig
        config = ExperimentConfig(
            experiment='test',
            condition='test',
            task='Test',
            task_id='t1',
            proxy_model_path='/tmp/proxy.json',
        )
        self.assertEqual(config.proxy_model_path, '/tmp/proxy.json')

    def test_config_proxy_model_path_defaults_empty(self):
        from experiments.config import ExperimentConfig
        config = ExperimentConfig(
            experiment='test',
            condition='test',
            task='Test',
            task_id='t1',
        )
        self.assertEqual(config.proxy_model_path, '')


class TestDispatchWritesChildEvents(unittest.TestCase):
    """dispatch_cli must write child events to events.jsonl in infra_dir."""

    def test_dispatch_cli_creates_event_collector(self):
        """dispatch_cli should attach an EventCollector to the child
        EventBus so events are written to the child's infra_dir.
        """
        from projects.POC.orchestrator.dispatch_cli import dispatch
        import inspect
        source = inspect.getsource(dispatch)

        # The dispatch function must create an EventCollector or write events
        has_collector = 'EventCollector' in source or 'events.jsonl' in source
        self.assertTrue(
            has_collector,
            "dispatch() must write child events to events.jsonl "
            "(EventCollector or direct events.jsonl write)",
        )


class TestEventCollectorMergeChildEvents(unittest.TestCase):
    """EventCollector must support merging child process events."""

    def test_collector_has_merge_method(self):
        """EventCollector should have a method to merge child events.jsonl files."""
        from experiments.collector import EventCollector
        self.assertTrue(
            hasattr(EventCollector, 'merge_child_events'),
            "EventCollector must have merge_child_events() method",
        )

    def test_merge_child_events_combines_files(self):
        """merge_child_events() reads child events.jsonl and appends to parent."""
        from experiments.collector import EventCollector

        tmpdir = tempfile.mkdtemp()
        try:
            # Create parent collector
            collector = EventCollector(
                output_dir=tmpdir,
                experiment='test',
                condition='test',
                run_id='r1',
            )

            # Create child events.jsonl
            child_dir = os.path.join(tmpdir, 'child1')
            os.makedirs(child_dir)
            child_events = [
                {'type': 'state_changed', 'source': 'child1', 'timestamp': 1.0},
                {'type': 'phase_started', 'source': 'child1', 'timestamp': 2.0},
            ]
            with open(os.path.join(child_dir, 'events.jsonl'), 'w') as f:
                for ev in child_events:
                    f.write(json.dumps(ev) + '\n')

            # Merge
            collector.merge_child_events([child_dir])

            # Verify merged events appear in parent's events.jsonl
            merged = []
            with open(os.path.join(tmpdir, 'events.jsonl')) as f:
                for line in f:
                    if line.strip():
                        merged.append(json.loads(line))

            child_sourced = [e for e in merged if e.get('source') == 'child1']
            self.assertEqual(len(child_sourced), 2,
                             "Both child events should appear in merged output")
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
