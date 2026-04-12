"""Event-sourced telemetry store (Issue #405).

One SQLite database at ``{teaparty_home}/telemetry.db``. One append-only
``events`` table. One write path (``record_event``). One read path
(``query_events`` plus aggregation helpers). One WebSocket broadcast on every
write so consumers update in real time.

The design principle is event sourcing: capture atomic events, compute
aggregates on read, never store aggregates. A new metric is a new query
over existing events, not a new table or a new writer.

See ``docs/detailed-design/telemetry.md`` for the full event catalog and
the design rationale.
"""
from __future__ import annotations

from teaparty.telemetry.events import (
    # Turn lifecycle
    TURN_START, TURN_COMPLETE,
    # Session lifecycle
    SESSION_CREATE, SESSION_COMPLETE, SESSION_CLOSED, SESSION_WITHDRAWN,
    SESSION_TIMED_OUT, SESSION_ABANDONED,
    # Phase transitions
    PHASE_CHANGED, PHASE_BACKTRACK,
    # Gates
    GATE_OPENED, GATE_PASSED, GATE_FAILED,
    GATE_INPUT_REQUESTED, GATE_INPUT_RECEIVED,
    # Escalations
    ESCALATION_REQUESTED, PROXY_CONSIDERED, PROXY_ANSWERED,
    PROXY_ESCALATED_TO_HUMAN, HUMAN_ANSWERED, ESCALATION_RESOLVED,
    PROXY_ANSWER_OVERRIDDEN,
    # Interjections
    INTERJECTION_RECEIVED, INTERJECTION_APPLIED, INTERJECTION_CAUSED_BACKTRACK,
    # Corrections
    CORRECTION_RECEIVED, CORRECTION_APPLIED,
    # Retries and friction
    TOOL_CALL_RETRY, SESSION_RETRY, RATELIMIT_BACKOFF,
    # Stalls
    STALL_DETECTED, STALL_RECOVERED,
    # Context management
    CONTEXT_COMPACTED, CONTEXT_CLEARED, CONTEXT_SATURATION_WARNED,
    # Work artifacts
    COMMIT_MADE, COMMIT_REVERTED,
    # Dispatch patterns
    FAN_OUT_DETECTED, DISPATCH_DEPTH_EXCEEDED,
    # Errors
    RATE_LIMIT, MCP_SERVER_FAILURE, SESSION_POISONED,
    SUBPROCESS_KILLED, TURN_ERROR,
    # Human operational actions
    PAUSE_ALL, RESUME_ALL, CLOSE_CONVERSATION, JOB_CREATED,
    WITHDRAW_CLICKED, REPRIORITIZE_DISPATCH_CLICKED,
    CHAT_BLADE_OPENED, CHAT_BLADE_CLOSED, CHAT_MESSAGE_SENT,
    CONFIG_PROJECT_ADDED, CONFIG_PROJECT_REMOVED,
    CONFIG_AGENT_CREATED, CONFIG_AGENT_EDITED, CONFIG_AGENT_REMOVED,
    CONFIG_SKILL_CREATED, CONFIG_SKILL_EDITED, CONFIG_SKILL_REMOVED,
    CONFIG_WORKGROUP_CREATED, CONFIG_WORKGROUP_EDITED, CONFIG_WORKGROUP_REMOVED,
    CONFIG_HOOK_CREATED, CONFIG_HOOK_EDITED, CONFIG_HOOK_REMOVED,
    PIN_ARTIFACT, UNPIN_ARTIFACT,
    # System
    SERVER_START, SERVER_SHUTDOWN, CONFIG_LOADED, MIGRATION_RUN,
    # Proxy evolution
    PROXY_UPDATED, PROXY_DIVERGED_FROM_HUMAN,
    # All event types (for tests / coverage)
    ALL_EVENT_TYPES,
)
from teaparty.telemetry.record import (
    record_event,
    set_broadcaster,
    set_teaparty_home,
    configure,
    reset_for_tests,
)
from teaparty.telemetry.query import (
    Event,
    query_events,
    total_cost,
    turn_count,
    active_sessions,
    gates_awaiting_input,
    backtrack_count,
    backtrack_cost,
    phase_distribution,
    escalation_stats,
    proxy_answer_rate,
    withdrawal_phase_distribution,
)
from teaparty.telemetry.migration import migrate_metrics_db

__all__ = [
    'record_event', 'set_broadcaster', 'set_teaparty_home', 'configure',
    'reset_for_tests',
    'Event', 'query_events',
    'total_cost', 'turn_count', 'active_sessions', 'gates_awaiting_input',
    'backtrack_count', 'backtrack_cost', 'phase_distribution',
    'escalation_stats', 'proxy_answer_rate', 'withdrawal_phase_distribution',
    'migrate_metrics_db',
    'ALL_EVENT_TYPES',
]
