"""Experiment configuration — dataclass + YAML loading.

Each experiment run is fully described by an ExperimentConfig. Configs
can be constructed programmatically or loaded from YAML corpus files.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass
class ExperimentConfig:
    """Full configuration for a single experiment run."""

    # Identity
    experiment: str          # e.g. "proxy-convergence"
    condition: str           # e.g. "dual-signal"
    task: str                # task description text
    task_id: str             # unique ID for result organization

    # Project
    project: str = 'POC'

    # Session flags (passed directly to Session)
    flat: bool = False
    skip_learnings: bool = False

    # Overrides
    backtracks_enabled: bool = True
    proxy_enabled: bool = True

    # Input provider config
    input_mode: str = 'pattern'           # "pattern", "scripted", "auto-approve"
    approval_rates: dict[str, float] = field(default_factory=dict)
    approval_seed: int = 42
    correction_feedback: str = 'Please add error handling'
    default_rate: float = 0.85
    scripted_decisions: dict[str, list[str]] = field(default_factory=dict)

    # Proxy state persistence (corpus runs)
    proxy_model_path: str = ''  # shared path for cross-task proxy persistence

    # Results location
    results_base: str = ''

    @property
    def results_dir(self) -> str:
        """Compute the results directory for this run."""
        base = self.results_base or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'results',
        )
        return os.path.join(base, self.experiment, self.condition, self.task_id)


@dataclass
class TaskDefinition:
    """A single task in a corpus file."""
    id: str
    text: str
    tier: str = 'medium'     # simple, medium, complex


@dataclass
class CorpusConfig:
    """A corpus file defining an experiment and its tasks."""
    experiment: str
    tasks: list[TaskDefinition] = field(default_factory=list)

    # Default condition settings (can be overridden per-run)
    default_condition: str = ''
    default_input_mode: str = 'pattern'
    default_approval_rates: dict[str, float] = field(default_factory=dict)
    default_approval_seed: int = 42
    default_correction_feedback: str = 'Please add error handling'
    default_rate: float = 0.85

    def make_config(
        self,
        task: TaskDefinition,
        condition: str = '',
        **overrides: Any,
    ) -> ExperimentConfig:
        """Build an ExperimentConfig for a specific task and condition."""
        return ExperimentConfig(
            experiment=self.experiment,
            condition=condition or self.default_condition,
            task=task.text,
            task_id=task.id,
            input_mode=overrides.get('input_mode', self.default_input_mode),
            approval_rates=overrides.get('approval_rates', dict(self.default_approval_rates)),
            approval_seed=overrides.get('approval_seed', self.default_approval_seed),
            correction_feedback=overrides.get(
                'correction_feedback', self.default_correction_feedback,
            ),
            default_rate=overrides.get('default_rate', self.default_rate),
            **{k: v for k, v in overrides.items()
               if k in ('flat', 'skip_learnings',
                         'backtracks_enabled', 'proxy_enabled',
                         'project', 'results_base', 'scripted_decisions',
                         'proxy_model_path')},
        )


def load_corpus(path: str) -> CorpusConfig:
    """Load a corpus YAML file.

    Expected format:
        experiment: proxy-convergence
        default_condition: dual-signal
        default_approval_rates:
          INTENT_ASSERT: 0.95
          PLAN_ASSERT: 0.80
          WORK_ASSERT: 0.85
        tasks:
          - id: pc-001
            text: "Add a health check endpoint that returns service status"
            tier: simple
          - id: pc-002
            text: "Implement rate limiting middleware"
            tier: medium
    """
    with open(path) as f:
        raw = yaml.safe_load(f)

    tasks = [
        TaskDefinition(
            id=t['id'],
            text=t['text'],
            tier=t.get('tier', 'medium'),
        )
        for t in raw.get('tasks', [])
    ]

    return CorpusConfig(
        experiment=raw['experiment'],
        tasks=tasks,
        default_condition=raw.get('default_condition', ''),
        default_input_mode=raw.get('default_input_mode', 'pattern'),
        default_approval_rates=raw.get('default_approval_rates', {}),
        default_approval_seed=raw.get('default_approval_seed', 42),
        default_correction_feedback=raw.get(
            'default_correction_feedback', 'Please add error handling',
        ),
        default_rate=raw.get('default_rate', 0.85),
    )
