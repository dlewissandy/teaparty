"""EventCollector — subscribes to the orchestrator EventBus and captures
structured experiment data to JSONL files.

Each event is enriched with experiment metadata (experiment name, condition,
run ID) so results can be aggregated across runs.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from orchestrator.events import Event, EventType


@dataclass
class PhaseTimings:
    """Start/end timestamps for a single CfA phase."""
    phase: str
    start: float = 0.0
    end: float = 0.0

    @property
    def duration(self) -> float:
        if self.start and self.end:
            return self.end - self.start
        return 0.0


@dataclass
class TokenUsage:
    """Accumulated token counts and cost for a scope (phase or session)."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    num_turns: int = 0
    invocations: int = 0

    def add_usage(self, usage: dict[str, Any], cost: float = 0.0, turns: int = 0) -> None:
        """Accumulate from a stream-json usage dict."""
        self.input_tokens += usage.get('input_tokens', 0)
        self.output_tokens += usage.get('output_tokens', 0)
        self.cache_read_tokens += usage.get('cache_read_input_tokens', 0)
        self.cache_creation_tokens += usage.get('cache_creation_input_tokens', 0)
        self.cost_usd += cost
        self.num_turns += turns
        self.invocations += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            'input_tokens': self.input_tokens,
            'output_tokens': self.output_tokens,
            'cache_read_tokens': self.cache_read_tokens,
            'cache_creation_tokens': self.cache_creation_tokens,
            'total_tokens': self.input_tokens + self.output_tokens,
            'cost_usd': round(self.cost_usd, 6),
            'num_turns': self.num_turns,
            'invocations': self.invocations,
        }


class EventCollector:
    """Captures EventBus events to JSONL and computes summary metrics.

    Usage:
        collector = EventCollector(output_dir, "proxy-convergence", "dual-signal", "pc-001")
        bus.subscribe(collector.on_event)
        # ... run session ...
        metrics = collector.summarize()
        collector.write_metrics()
    """

    def __init__(
        self,
        output_dir: str,
        experiment: str,
        condition: str,
        run_id: str,
    ):
        self.output_dir = output_dir
        self.experiment = experiment
        self.condition = condition
        self.run_id = run_id

        # In-memory event store for summarization
        self._events: list[dict[str, Any]] = []
        self._phase_timings: dict[str, PhaseTimings] = {}
        self._proxy_decisions: list[dict[str, Any]] = []
        self._state_transitions: list[dict[str, Any]] = []
        self._input_responses: list[dict[str, Any]] = []

        # Token accounting
        self._session_tokens = TokenUsage()
        self._phase_tokens: dict[str, TokenUsage] = {}
        self._current_phase: str = ''

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        self._events_path = os.path.join(output_dir, 'events.jsonl')

        # Terminal state captured from SESSION_COMPLETED
        self._terminal_state = ''
        self._backtrack_count = 0

    async def on_event(self, event: Event) -> None:
        """EventBus callback — capture and persist each event."""
        record = {
            'timestamp': event.timestamp or time.time(),
            'type': event.type.value,
            'session_id': event.session_id,
            'experiment': self.experiment,
            'condition': self.condition,
            'run_id': self.run_id,
            **event.data,
        }
        self._events.append(record)

        # Write immediately to JSONL (append mode)
        with open(self._events_path, 'a') as f:
            f.write(json.dumps(record, default=str) + '\n')

        # Index specific event types for fast summarization
        if event.type == EventType.STATE_CHANGED:
            self._state_transitions.append({
                'previous_state': event.data.get('previous_state', ''),
                'state': event.data.get('state', ''),
                'action': event.data.get('action', ''),
                'phase': event.data.get('phase', ''),
                'timestamp': event.timestamp,
                'backtrack_count': event.data.get('backtrack_count', 0),
            })
            self._backtrack_count = event.data.get('backtrack_count', 0)

        elif event.type == EventType.PHASE_STARTED:
            phase = event.data.get('phase', '')
            self._current_phase = phase
            self._phase_timings[phase] = PhaseTimings(
                phase=phase, start=event.timestamp,
            )
            if phase not in self._phase_tokens:
                self._phase_tokens[phase] = TokenUsage()

        elif event.type == EventType.PHASE_COMPLETED:
            phase = event.data.get('phase', '')
            if phase in self._phase_timings:
                self._phase_timings[phase].end = event.timestamp
            self._current_phase = ''

        elif event.type == EventType.STREAM_DATA:
            self._handle_stream_data(event.data)

        elif event.type == EventType.LOG:
            category = event.data.get('category', '')
            if category == 'proxy_decision':
                self._proxy_decisions.append({
                    'state': event.data.get('state', ''),
                    'decision': event.data.get('decision', ''),
                    'confidence': event.data.get('confidence', 0.0),
                    'confidence_laplace': event.data.get('confidence_laplace', 0.0),
                    'confidence_ema': event.data.get('confidence_ema', 0.0),
                    'exploration_forced': event.data.get('exploration_forced', False),
                    'reasoning': event.data.get('reasoning', ''),
                    'timestamp': event.timestamp,
                })

        elif event.type == EventType.INPUT_RECEIVED:
            self._input_responses.append({
                'response': event.data.get('response', ''),
                'timestamp': event.timestamp,
            })

        elif event.type == EventType.SESSION_COMPLETED:
            self._terminal_state = event.data.get('terminal_state', '')
            self._backtrack_count = event.data.get('backtrack_count', 0)

    def _handle_stream_data(self, data: dict[str, Any]) -> None:
        """Extract token/cost data from stream-json events.

        Captures data from:
        - result/success: total_cost_usd, num_turns, usage (per-invocation final)
        - system/task_notification: usage (background task completion)
        """
        event_type = data.get('type', '')
        subtype = data.get('subtype', '')

        if event_type == 'result' and subtype == 'success':
            usage = data.get('usage', {})
            cost = data.get('total_cost_usd', 0.0)
            turns = data.get('num_turns', 0)
            self._session_tokens.add_usage(usage, cost=cost, turns=turns)
            if self._current_phase and self._current_phase in self._phase_tokens:
                self._phase_tokens[self._current_phase].add_usage(
                    usage, cost=cost, turns=turns,
                )

        elif event_type == 'system' and subtype == 'task_notification':
            usage = data.get('usage', {})
            if usage:
                self._session_tokens.add_usage(usage)
                if self._current_phase and self._current_phase in self._phase_tokens:
                    self._phase_tokens[self._current_phase].add_usage(usage)

    def summarize(self) -> dict[str, Any]:
        """Compute summary metrics from collected events."""
        phase_durations = {}
        for phase, timing in self._phase_timings.items():
            phase_durations[phase] = round(timing.duration, 2)

        proxy_summary = {
            'total_decisions': len(self._proxy_decisions),
            'auto_approvals': sum(
                1 for d in self._proxy_decisions if d['decision'] == 'auto-approve'
            ),
            'escalations': sum(
                1 for d in self._proxy_decisions if d['decision'] == 'escalate'
            ),
            'exploration_escalations': sum(
                1 for d in self._proxy_decisions if d.get('exploration_forced', False)
            ),
            'mean_confidence': (
                sum(d['confidence'] for d in self._proxy_decisions)
                / len(self._proxy_decisions)
                if self._proxy_decisions else 0.0
            ),
            'mean_confidence_laplace': (
                sum(d.get('confidence_laplace', 0.0) for d in self._proxy_decisions)
                / len(self._proxy_decisions)
                if self._proxy_decisions else 0.0
            ),
            'mean_confidence_ema': (
                sum(d.get('confidence_ema', 0.0) for d in self._proxy_decisions)
                / len(self._proxy_decisions)
                if self._proxy_decisions else 0.0
            ),
        }

        # Token accounting
        tokens_summary = self._session_tokens.to_dict()
        tokens_summary['by_phase'] = {
            phase: usage.to_dict()
            for phase, usage in self._phase_tokens.items()
        }

        return {
            'experiment': self.experiment,
            'condition': self.condition,
            'run_id': self.run_id,
            'terminal_state': self._terminal_state,
            'backtrack_count': self._backtrack_count,
            'total_events': len(self._events),
            'state_transitions': len(self._state_transitions),
            'phase_durations': phase_durations,
            'proxy': proxy_summary,
            'tokens': tokens_summary,
            'input_responses': len(self._input_responses),
        }

    def write_metrics(self) -> str:
        """Write summary metrics to metrics.json. Returns the file path."""
        metrics = self.summarize()
        path = os.path.join(self.output_dir, 'metrics.json')
        with open(path, 'w') as f:
            json.dump(metrics, f, indent=2, default=str)
        return path

    def merge_child_events(self, child_dirs: list[str]) -> int:
        """Merge events.jsonl files from child process directories.

        Reads each child's events.jsonl, tags events with their source
        directory, and appends them to this collector's events.jsonl.
        Returns the number of child events merged.
        """
        merged_count = 0
        for child_dir in child_dirs:
            child_events_path = os.path.join(child_dir, 'events.jsonl')
            if not os.path.isfile(child_events_path):
                continue
            try:
                with open(child_events_path) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if 'source' not in record:
                            record['source'] = os.path.basename(child_dir)
                        self._events.append(record)
                        with open(self._events_path, 'a') as out:
                            out.write(json.dumps(record, default=str) + '\n')
                        merged_count += 1
            except OSError:
                continue
        return merged_count

    @staticmethod
    def load_metrics(metrics_path: str) -> dict[str, Any]:
        """Load metrics.json from a results directory."""
        with open(metrics_path) as f:
            return json.load(f)

    @staticmethod
    def load_events(events_path: str) -> list[dict[str, Any]]:
        """Load events.jsonl from a results directory."""
        events = []
        with open(events_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events
