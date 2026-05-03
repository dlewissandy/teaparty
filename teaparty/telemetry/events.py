"""Event type constants for the telemetry store.

Defining these as module constants means typos fail at import time, not
silently at write time. Aggregation helpers and tests reference these names
directly instead of duplicating strings.

The full catalog is ~55 event types, grouped by category below.
"""
from __future__ import annotations

# ── Turn lifecycle ───────────────────────────────────────────────────────────
TURN_START = 'turn_start'
TURN_COMPLETE = 'turn_complete'

# ── Session lifecycle ────────────────────────────────────────────────────────
SESSION_CREATE = 'session_create'
SESSION_COMPLETE = 'session_complete'
SESSION_CLOSED = 'session_closed'
SESSION_WITHDRAWN = 'session_withdrawn'
SESSION_TIMED_OUT = 'session_timed_out'
SESSION_ABANDONED = 'session_abandoned'

# ── Phase transitions ────────────────────────────────────────────────────────
PHASE_CHANGED = 'phase_changed'
PHASE_BACKTRACK = 'phase_backtrack'

# ── Gates ────────────────────────────────────────────────────────────────────
GATE_OPENED = 'gate_opened'
GATE_PASSED = 'gate_passed'
GATE_FAILED = 'gate_failed'
GATE_INPUT_REQUESTED = 'gate_input_requested'
GATE_INPUT_RECEIVED = 'gate_input_received'

# ── Escalations (proxy chain) ────────────────────────────────────────────────
ESCALATION_REQUESTED = 'escalation_requested'
PROXY_CONSIDERED = 'proxy_considered'
PROXY_ANSWERED = 'proxy_answered'
PROXY_ESCALATED_TO_HUMAN = 'proxy_escalated_to_human'
HUMAN_ANSWERED = 'human_answered'
ESCALATION_RESOLVED = 'escalation_resolved'
PROXY_ANSWER_OVERRIDDEN = 'proxy_answer_overridden'

# ── Interjections ────────────────────────────────────────────────────────────
INTERJECTION_RECEIVED = 'interjection_received'
INTERJECTION_APPLIED = 'interjection_applied'
INTERJECTION_CAUSED_BACKTRACK = 'interjection_caused_backtrack'

# ── Corrections ──────────────────────────────────────────────────────────────
CORRECTION_RECEIVED = 'correction_received'
CORRECTION_APPLIED = 'correction_applied'

# ── Retries and friction ─────────────────────────────────────────────────────
TOOL_CALL_RETRY = 'tool_call_retry'
SESSION_RETRY = 'session_retry'
RATELIMIT_BACKOFF = 'ratelimit_backoff'

# ── Stalls ───────────────────────────────────────────────────────────────────
STALL_DETECTED = 'stall_detected'
STALL_RECOVERED = 'stall_recovered'

# ── Context management ───────────────────────────────────────────────────────
CONTEXT_COMPACTED = 'context_compacted'
CONTEXT_CLEARED = 'context_cleared'
CONTEXT_SATURATION_WARNED = 'context_saturation_warned'

# ── Work artifacts ───────────────────────────────────────────────────────────
COMMIT_MADE = 'commit_made'
COMMIT_REVERTED = 'commit_reverted'

# ── Dispatch patterns ────────────────────────────────────────────────────────
FAN_OUT_DETECTED = 'fan_out_detected'
DISPATCH_DEPTH_EXCEEDED = 'dispatch_depth_exceeded'
# A lead-tier turn that produced filesystem-mutating tool calls
# (Write/Edit/Bash) and zero ``Send`` calls.  The role tells leads to
# delegate; this signal converts a silent skip into an operator-visible
# event so the catalog → role drift can be addressed at the prompt or
# config level rather than discovered by reading bus history.
DELEGATION_SKIPPED = 'delegation_skipped'

# ── Errors and degradation ───────────────────────────────────────────────────
RATE_LIMIT = 'rate_limit'
MCP_SERVER_FAILURE = 'mcp_server_failure'
SESSION_POISONED = 'session_poisoned'
SUBPROCESS_KILLED = 'subprocess_killed'
TURN_ERROR = 'turn_error'

# ── Human operational actions ────────────────────────────────────────────────
PAUSE_ALL = 'pause_all'
RESUME_ALL = 'resume_all'
CLOSE_CONVERSATION = 'close_conversation'
JOB_CREATED = 'job_created'
WITHDRAW_CLICKED = 'withdraw_clicked'
REPRIORITIZE_DISPATCH_CLICKED = 'reprioritize_dispatch_clicked'
CHAT_BLADE_OPENED = 'chat_blade_opened'
CHAT_BLADE_CLOSED = 'chat_blade_closed'
CHAT_MESSAGE_SENT = 'chat_message_sent'

CONFIG_PROJECT_ADDED = 'config_project_added'
CONFIG_PROJECT_REMOVED = 'config_project_removed'
CONFIG_AGENT_CREATED = 'config_agent_created'
CONFIG_AGENT_EDITED = 'config_agent_edited'
CONFIG_AGENT_REMOVED = 'config_agent_removed'
CONFIG_SKILL_CREATED = 'config_skill_created'
CONFIG_SKILL_EDITED = 'config_skill_edited'
CONFIG_SKILL_REMOVED = 'config_skill_removed'
CONFIG_WORKGROUP_CREATED = 'config_workgroup_created'
CONFIG_WORKGROUP_EDITED = 'config_workgroup_edited'
CONFIG_WORKGROUP_REMOVED = 'config_workgroup_removed'
CONFIG_HOOK_CREATED = 'config_hook_created'
CONFIG_HOOK_EDITED = 'config_hook_edited'
CONFIG_HOOK_REMOVED = 'config_hook_removed'

PIN_ARTIFACT = 'pin_artifact'
UNPIN_ARTIFACT = 'unpin_artifact'

# ── System and audit ─────────────────────────────────────────────────────────
SERVER_START = 'server_start'
SERVER_SHUTDOWN = 'server_shutdown'
CONFIG_LOADED = 'config_loaded'
MIGRATION_RUN = 'migration_run'

# ── Proxy evolution (Tier 4 stubs) ───────────────────────────────────────────
PROXY_UPDATED = 'proxy_updated'
PROXY_DIVERGED_FROM_HUMAN = 'proxy_diverged_from_human'


ALL_EVENT_TYPES: frozenset[str] = frozenset({
    TURN_START, TURN_COMPLETE,
    SESSION_CREATE, SESSION_COMPLETE, SESSION_CLOSED, SESSION_WITHDRAWN,
    SESSION_TIMED_OUT, SESSION_ABANDONED,
    PHASE_CHANGED, PHASE_BACKTRACK,
    GATE_OPENED, GATE_PASSED, GATE_FAILED,
    GATE_INPUT_REQUESTED, GATE_INPUT_RECEIVED,
    ESCALATION_REQUESTED, PROXY_CONSIDERED, PROXY_ANSWERED,
    PROXY_ESCALATED_TO_HUMAN, HUMAN_ANSWERED, ESCALATION_RESOLVED,
    PROXY_ANSWER_OVERRIDDEN,
    INTERJECTION_RECEIVED, INTERJECTION_APPLIED, INTERJECTION_CAUSED_BACKTRACK,
    CORRECTION_RECEIVED, CORRECTION_APPLIED,
    TOOL_CALL_RETRY, SESSION_RETRY, RATELIMIT_BACKOFF,
    STALL_DETECTED, STALL_RECOVERED,
    CONTEXT_COMPACTED, CONTEXT_CLEARED, CONTEXT_SATURATION_WARNED,
    COMMIT_MADE, COMMIT_REVERTED,
    FAN_OUT_DETECTED, DISPATCH_DEPTH_EXCEEDED, DELEGATION_SKIPPED,
    RATE_LIMIT, MCP_SERVER_FAILURE, SESSION_POISONED,
    SUBPROCESS_KILLED, TURN_ERROR,
    PAUSE_ALL, RESUME_ALL, CLOSE_CONVERSATION, JOB_CREATED,
    WITHDRAW_CLICKED, REPRIORITIZE_DISPATCH_CLICKED,
    CHAT_BLADE_OPENED, CHAT_BLADE_CLOSED, CHAT_MESSAGE_SENT,
    CONFIG_PROJECT_ADDED, CONFIG_PROJECT_REMOVED,
    CONFIG_AGENT_CREATED, CONFIG_AGENT_EDITED, CONFIG_AGENT_REMOVED,
    CONFIG_SKILL_CREATED, CONFIG_SKILL_EDITED, CONFIG_SKILL_REMOVED,
    CONFIG_WORKGROUP_CREATED, CONFIG_WORKGROUP_EDITED, CONFIG_WORKGROUP_REMOVED,
    CONFIG_HOOK_CREATED, CONFIG_HOOK_EDITED, CONFIG_HOOK_REMOVED,
    PIN_ARTIFACT, UNPIN_ARTIFACT,
    SERVER_START, SERVER_SHUTDOWN, CONFIG_LOADED, MIGRATION_RUN,
    PROXY_UPDATED, PROXY_DIVERGED_FROM_HUMAN,
})
