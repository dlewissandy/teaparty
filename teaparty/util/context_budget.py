"""Context budget monitoring — token tracking and ``/compact`` trigger.

Extracts token usage from stream-json ``result`` events and signals
when the compact threshold is crossed.  The orchestrator checks
:attr:`should_compact` at turn boundaries and, when True, injects a
``/compact`` prompt on the next ``--resume`` so the agent stays under
Claude's 200k context window.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Default context window size for Claude models (tokens).
DEFAULT_CONTEXT_WINDOW = 200_000

# Fraction of context window at which to inject ``/compact``.
DEFAULT_COMPACT_THRESHOLD = 0.78


@dataclass
class ContextBudget:
    """Tracks context utilization from stream-json result events.

    The orchestrator feeds every parsed stream-json event via
    :meth:`update`.  When a ``result`` event contains token usage,
    the utilization is recomputed.  Callers check :attr:`should_compact`
    at turn boundaries.
    """

    context_window: int = DEFAULT_CONTEXT_WINDOW
    compact_threshold: float = DEFAULT_COMPACT_THRESHOLD

    # ── Observed state ──────────────────────────────────────────────────
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    # Latched at threshold crossing — cleared by caller after acting.
    _compact_fired: bool = field(default=False, repr=False)

    # ── Public API ──────────────────────────────────────────────────────

    def update(self, event: dict) -> None:
        """Process a stream-json event.  Only ``result`` events with
        token usage are relevant; all others are ignored.
        """
        if event.get('type') != 'result':
            return

        # Token counts may appear at the top level or nested under 'usage'.
        source = event.get('usage') or event
        it = source.get('input_tokens')
        if it is None:
            return  # No token data in this result event

        self.input_tokens = int(it)
        self.cache_creation_input_tokens = int(
            source.get('cache_creation_input_tokens', 0),
        )
        self.cache_read_input_tokens = int(
            source.get('cache_read_input_tokens', 0),
        )

        if self.utilization >= self.compact_threshold:
            self._compact_fired = True

    @property
    def used_tokens(self) -> int:
        """Total tokens contributing to context pressure."""
        return (
            self.input_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )

    @property
    def utilization(self) -> float:
        """Current context utilization as a fraction (0.0–1.0+)."""
        if self.context_window <= 0:
            return 0.0
        return self.used_tokens / self.context_window

    @property
    def should_compact(self) -> bool:
        """True if compaction threshold was crossed since last clear."""
        return self._compact_fired

    def clear_compact(self) -> None:
        """Acknowledge compaction — resets the flag."""
        self._compact_fired = False


def build_compact_prompt(*, cfa_state: str, task: str, scratch_path: str = '') -> str:
    """Build the ``/compact`` command with a focus argument.

    The focus is derived from the current CfA state and task description.
    """
    focus = f'focus on {task} -- current CfA state is {cfa_state}'
    parts = [f'/compact {focus}']
    if scratch_path:
        parts.append(
            f'After compaction, read {scratch_path} for preserved context.',
        )
    return '\n'.join(parts)
