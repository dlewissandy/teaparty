# TeaParty Roadmap

## Purpose
Build TeaParty into a scalable platform where multidisciplinary teams of humans and agents co-author files (books, scripts, presentations, software), and where tools can be added safely for human or agent automation.

This roadmap is based on direct inspection of the current code in `/Users/darrell/git/teaparty`.

## Current State
- The core domain model exists: workgroups, memberships, agents, conversations, participants, messages, invites, learning events, follow-up tasks.
- Human + agent chat works for topic, direct, and admin conversations.
- Agent runtime supports heuristic and LLM-assisted response selection.
- Workgroup files exist, but are stored in `workgroups.files` JSON (not revisioned, no merge/conflict model).
- Tooling is static and in-process (`TOOL_REGISTRY` in `teaparty_app/services/tools.py`).
- Admin command/tool orchestration is centralized in `teaparty_app/services/admin_workspace.py`.
- Agent orchestration is centralized in `teaparty_app/services/agent_runtime.py`.
- Real-time UX is polling-based (`/api/agents/tick` plus 4-second browser polling).
- Persistence is SQLite, with startup-time schema migration logic in `teaparty_app/db.py`.
- Automated tests pass locally (`38` unit tests), but coverage is mostly helper-level, not workflow-level.

## Key Gaps
1. Scalability: SQLite, in-request processing, and polling will bottleneck under concurrency.
2. Collaboration depth: file data lacks revision history, conflict detection, and edit provenance.
3. Extensibility: tools are code-registered only; there is no runtime plugin lifecycle or policy layer.
4. Maintainability: large service files raise change risk and slow safe iteration.
5. Operations: no queue-backed workers, limited observability, and incomplete audit posture.

## Target Architecture (Incremental)
1. Keep a modular monolith first, then split services only where operationally justified.
2. Move to Postgres with real migrations.
3. Add queue-backed workers for follow-ups, agent runs, and tool execution retries.
4. Add real-time transport (WebSocket preferred, SSE acceptable) for message/file updates.
5. Introduce a formal tool/plugin subsystem with schema, scope checks, approvals, and audit logs.
6. Introduce a file-collaboration subsystem with append-only revisions and provenance.

## Phased Plan

### Phase 0: Foundation Hardening (2-3 weeks)
Goal: make current behavior safer to evolve.

Deliverables:
1. Split `agent_runtime.py` into focused modules (selection, reply generation, follow-ups, learning).
2. Split `admin_workspace.py` into focused modules (workspace bootstrap, command parsing, admin tools, deletion flows).
3. Add integration tests for workgroup bootstrap, user message -> agent chain, and destructive admin actions with permission checks.
4. Introduce request IDs and a consistent API error envelope.

Exit criteria:
1. Existing behavior preserved.
2. Integration tests validate critical user workflows, not only helpers.

### Phase 1: Revisioned File Authoring (3-5 weeks)
Goal: replace JSON file blobs with revisioned collaboration primitives.

Deliverables:
1. Add tables: `files`, `file_revisions`, optional `file_edit_sessions`.
2. Migrate `workgroups.files` data to the new model.
3. Add APIs: list files, get latest revision, write with expected revision, list revision history.
4. Update UI with revision metadata and stale-write conflict handling.

Exit criteria:
1. Every file write creates an append-only revision.
2. Stale writes fail predictably with conflict responses.

### Phase 2: Tool Plugin System v1 (4-6 weeks)
Goal: let users add tools without core code edits.

Deliverables:
1. Add tool metadata tables: `tool_definitions`, `tool_bindings`, `tool_runs`.
2. Define tool manifest + JSON schema contract for input/output.
3. Replace static tool registry with runtime registry loading.
4. Add scope-based authorization (for example: `read_files`, `write_files`, `manage_members`).
5. Add optional human approval for destructive scopes.

Exit criteria:
1. At least one new tool can be added by configuration + registration path only.
2. Every tool run is audited with caller, args, outcome, and latency.

### Phase 3: Scalable Runtime + Real-Time Delivery (4-6 weeks)
Goal: improve concurrency and collaboration latency.

Deliverables:
1. Migrate SQLite to Postgres.
2. Introduce migration tooling (Alembic or equivalent).
3. Move follow-up scans and agent-trigger chains to worker queue.
4. Add push updates for messages, agent status, and file changes.
5. Remove polling dependency from the primary UX path.

Exit criteria:
1. No long-running agent work on synchronous request threads.
2. Median update propagation is near-real-time (<2 seconds).

### Phase 4: Structured Multi-Agent Teamwork (4-8 weeks)
Goal: support repeatable multidisciplinary workflows, not only ad hoc replies.

Deliverables:
1. Add reusable role templates (researcher, critic, editor, implementer, etc.).
2. ~~Add workflow graph/state model (planner -> contributors -> reviewer -> publisher).~~ Multi-agent team support is now available via Claude's native `--agents` feature. Job conversations use a single `claude -p` invocation with all agents passed as `--agents`, and the verbose output is parsed to attribute contributions to individual agents.
3. Add task objects linked to conversation threads and file revisions.
4. Separate short-term thread context from long-term workgroup knowledge.

Remaining work:
- Workflow state integration with multi-agent teams
- Provenance tracking for agent contributions across file revisions
- Cross-job learning and context sharing

Exit criteria:
1. Users can run a defined multi-agent workflow to create or revise a file artifact.
2. Outputs include provenance of human and agent contributions.

### Phase 5: Governance + Operations (ongoing)
Goal: production readiness for larger organizations.

Deliverables:
1. Expand RBAC beyond owner/member.
2. Add comprehensive audit pipeline for memberships, file changes, and tool runs.
3. Add rate limits, abuse controls, and execution quotas.
4. Add structured logging, tracing, metrics dashboards, and alerts.
5. Define backup, restore, and disaster recovery procedures.

Exit criteria:
1. Security and operations standards support production deployment.

## Cross-Cutting Standards
- Keep destructive actions deterministic and confirmation-gated.
- Keep policy logic testable and data-driven (not prompt-only behavior).
- Use idempotency keys for side-effecting operations.
- Treat tool execution as untrusted by default; scope and audit all tool calls.
- Preserve backward compatibility across migrations with explicit deprecation windows.

## First Sprint Recommendation
1. Create `docs/architecture/` with bounded-context diagrams and sequence diagrams.
2. Refactor `agent_runtime.py` and `admin_workspace.py` into modules without behavior changes.
3. Add migration framework and initial Postgres-compatible schemas for revisioned files.
4. Add integration tests for end-to-end collaboration and admin destructive flows.
5. Draft and review tool manifest and scope taxonomy before implementation.

## Success Metrics
1. Collaboration latency: median message/file update propagation < 2s.
2. File integrity: 100% of file mutations captured as immutable revisions.
3. Extensibility: time to add a new tool without core code edits < 1 day.
4. Auditability: 100% of tool runs include caller, scope, result, and timestamp.
5. Runtime reliability: agent/task processing success rate >= 99%.
