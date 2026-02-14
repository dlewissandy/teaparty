# TeaParty Task List

Actionable task breakdown derived from the [ROADMAP.md](ROADMAP.md) and current code inspection.
Tasks are ordered by phase dependency. Each task includes acceptance criteria.

---

## Phase 0: Foundation Hardening

### 0.1 — Add dev/test dependencies to pyproject.toml
`pyproject.toml` has no `[project.optional-dependencies]` or `[tool.pytest]` section.
- [ ] Add `pytest`, `pytest-asyncio`, `httpx` (for `TestClient`) to `[project.optional-dependencies.dev]`
- [ ] Add `[tool.pytest.ini_options]` with sensible defaults
- [ ] Verify `uv run pytest tests/` passes all 38 existing tests

### 0.2 — Refactor `agent_runtime.py` (1,971 lines) into submodules
Split into focused modules under `teaparty_app/services/agent_runtime/`:
- [ ] `__init__.py` — re-export public API so existing imports don't break
- [ ] `selection.py` — response scoring, mention detection, question heuristics
- [ ] `reply.py` — LLM call construction, system prompt assembly, reply generation
- [ ] `followups.py` — follow-up task creation, tick/scan, overdue processing
- [ ] `learning.py` — signal extraction, learning_state/sentiment_state updates, event logging
- [ ] All existing tests still pass with no import changes needed by callers

### 0.3 — Refactor `admin_workspace.py` (2,258 lines) into submodules
Split into focused modules under `teaparty_app/services/admin_workspace/`:
- [ ] `__init__.py` — re-export public API
- [ ] `bootstrap.py` — admin agent/conversation creation per workgroup
- [ ] `parsing.py` — command pattern matching, deterministic fallback parsing
- [ ] `tools.py` — admin tool implementations (topic, member, file, deletion ops)
- [ ] `sdk_integration.py` — OpenAI Agents SDK wiring (isolated from core logic)
- [ ] All existing tests still pass with no import changes needed by callers

### 0.4 — Add integration tests for critical workflows
Current tests are helper-level only. Add workflow tests:
- [ ] **Workgroup bootstrap**: create workgroup from template → verify agents, files, conversations created
- [ ] **Message → agent reply chain**: post user message → verify agent scoring → verify reply generated
- [ ] **Admin destructive actions**: test permission enforcement for `delete_workgroup`, `remove_member`, `remove_topic`, `clear_topic_messages`
- [ ] **Invite flow**: create invite → accept with different user → verify membership
- [ ] **File CRUD via tools**: add_file → edit_file → rename_file → delete_file through the tool registry
- [ ] **Follow-up tick**: create overdue follow-up task → call tick → verify follow-up message emitted

### 0.5 — Add request IDs and consistent API error envelope
- [ ] Add middleware that generates a `X-Request-Id` header (UUID) for every request
- [ ] Define a standard error response schema: `{ "error": { "code": str, "message": str, "request_id": str } }`
- [ ] Update all `HTTPException` raises to use the envelope format
- [ ] Add request ID to log output for correlation

### 0.6 — Create architecture documentation
- [ ] Create `docs/architecture/` directory
- [ ] Add bounded-context diagram (workgroups, conversations, agents, files, tools)
- [ ] Add sequence diagrams for: message → agent reply, admin command flow, file mutation flow
- [ ] Add data model diagram showing table relationships

---

## Phase 1: Revisioned File Authoring

### 1.1 — Design and add file revision tables
- [ ] Add `files` table: `id`, `workgroup_id`, `path`, `created_by`, `created_at`, `deleted_at`
- [ ] Add `file_revisions` table: `id`, `file_id`, `revision_number`, `content`, `author_id`, `author_type` (user/agent), `created_at`, `parent_revision_id`
- [ ] Optional: `file_edit_sessions` table for collaborative editing metadata
- [ ] Add migration logic in `db.py` (or introduce Alembic at this point)

### 1.2 — Migrate existing `workgroups.files` JSON data
- [ ] Write migration that reads `workgroups.files` JSON blobs → creates `files` + initial `file_revisions` rows
- [ ] Preserve file paths, content, and ownership where available
- [ ] Verify round-trip: migrated data readable through new model matches old JSON data
- [ ] Remove `files` column from `workgroups` table after migration confirmed

### 1.3 — Add file revision API endpoints
- [ ] `GET /api/workgroups/{id}/files` — list files (from `files` table)
- [ ] `GET /api/workgroups/{id}/files/{file_id}` — get file with latest revision
- [ ] `GET /api/workgroups/{id}/files/{file_id}/revisions` — list revision history
- [ ] `PUT /api/workgroups/{id}/files/{file_id}` — write with `expected_revision` for conflict detection
- [ ] `POST /api/workgroups/{id}/files` — create new file (first revision)
- [ ] `DELETE /api/workgroups/{id}/files/{file_id}` — soft-delete

### 1.4 — Update tool registry for revisioned files
- [ ] Update `add_file`, `edit_file`, `rename_file`, `delete_file` tools to use new `files`/`file_revisions` tables
- [ ] `edit_file` must create a new revision, not overwrite
- [ ] `list_files` reads from `files` table instead of JSON blob
- [ ] Add revision info to tool output (revision number, author, timestamp)

### 1.5 — Update frontend for file revisions
- [ ] Show revision number and last-modified metadata in file list
- [ ] Handle 409 Conflict responses (stale write) with user-facing message
- [ ] Add revision history view (list of revisions with author/timestamp)
- [ ] Add diff or "view previous version" capability

### 1.6 — Add file revision tests
- [ ] Unit tests for revision model creation and conflict detection
- [ ] Integration tests for file CRUD through API with revision tracking
- [ ] Migration test: verify JSON blob → revision model conversion
- [ ] Conflict test: two concurrent writes, second gets 409

---

## Phase 2: Tool Plugin System v1

### 2.1 — Design tool manifest and scope taxonomy
- [ ] Define JSON schema for tool manifests (name, description, input schema, output schema, required scopes)
- [ ] Define scope taxonomy: `read_files`, `write_files`, `manage_members`, `manage_topics`, `execute_code`, etc.
- [ ] Document the contract in `docs/architecture/tool-manifest.md`
- [ ] Review and finalize before implementation

### 2.2 — Add tool metadata tables
- [ ] `tool_definitions` table: `id`, `name`, `description`, `manifest_json`, `scope`, `enabled`, `created_at`
- [ ] `tool_bindings` table: `id`, `tool_definition_id`, `workgroup_id`, `agent_id` (nullable), `enabled`
- [ ] `tool_runs` table: `id`, `tool_definition_id`, `caller_type`, `caller_id`, `workgroup_id`, `args_json`, `result_json`, `status`, `latency_ms`, `created_at`

### 2.3 — Replace static tool registry with runtime registry
- [ ] Load tool definitions from database at startup and on-demand
- [ ] Migrate existing built-in tools (`summarize_topic`, `list_files`, etc.) to tool_definitions rows
- [ ] Keep built-in tools as code implementations but register them through the new system
- [ ] New tools can be added via API/admin without code changes

### 2.4 — Add scope-based authorization
- [ ] Tools declare required scopes in their manifest
- [ ] Agent tool bindings specify allowed scopes per workgroup
- [ ] Runtime checks scope before executing tool
- [ ] Add optional human-approval gate for destructive scopes (`write_files`, `manage_members`)

### 2.5 — Add tool run audit trail
- [ ] Every tool execution logs to `tool_runs`: caller, args, outcome, latency
- [ ] Add API endpoint to query tool run history per workgroup
- [ ] Add UI for viewing tool execution history (admin view)

### 2.6 — Add tool plugin tests
- [ ] Unit tests for manifest validation and scope checking
- [ ] Integration test: register new tool via API → bind to agent → trigger via message → verify audit log
- [ ] Permission tests: tool without required scope is rejected

---

## Phase 3: Scalable Runtime + Real-Time Delivery

### 3.1 — Introduce Alembic migration framework
- [ ] Add `alembic` to dependencies
- [ ] Generate initial migration from current SQLModel models
- [ ] Replace startup migration logic in `db.py` with Alembic runner
- [ ] Verify clean migration on fresh database and upgrade from existing SQLite

### 3.2 — Migrate to PostgreSQL
- [ ] Update `config.py` to support Postgres connection strings
- [ ] Audit all queries for SQLite-specific syntax (e.g., `datetime('now')`, `json_extract`)
- [ ] Test full application against Postgres
- [ ] Update `.env.example` with Postgres connection template
- [ ] Keep SQLite as supported option for local dev

### 3.3 — Add background worker queue
- [ ] Choose and add queue library (RQ, Celery, or arq) to dependencies
- [ ] Move follow-up scan (`/api/agents/tick`) to periodic worker task
- [ ] Move agent reply generation to async worker (post message → enqueue → worker generates reply)
- [ ] Add worker health check endpoint
- [ ] Add retry logic with backoff for failed agent calls

### 3.4 — Add WebSocket/SSE push transport
- [ ] Add WebSocket endpoint for real-time message delivery
- [ ] Push new messages, agent status changes, and file updates to connected clients
- [ ] Update frontend to connect via WebSocket with polling fallback
- [ ] Add connection management (auth, reconnection, heartbeat)
- [ ] Remove polling as primary UX path (keep as fallback)

### 3.5 — Add real-time delivery tests
- [ ] Integration test: post message → verify WebSocket client receives it
- [ ] Worker test: enqueue agent reply → verify message created
- [ ] Failover test: WebSocket disconnect → polling fallback activates

---

## Phase 4: Structured Multi-Agent Teamwork

### 4.1 — Add reusable role templates
- [ ] Define role template schema (name, personality traits, default tools, typical responsibilities)
- [ ] Create built-in roles: researcher, critic, editor, implementer, reviewer, moderator
- [ ] Add API for listing and applying role templates to agents
- [ ] Update workgroup templates to reference role templates

### 4.2 — Add workflow graph/state model
- [ ] Design workflow schema: stages, transitions, assignments, completion criteria
- [ ] Add `workflows` and `workflow_stages` tables
- [ ] Built-in workflow: planner → contributors → reviewer → publisher
- [ ] Add API for creating, advancing, and querying workflow state
- [ ] Agent runtime can advance workflow stages based on completion signals

### 4.3 — Add task objects
- [ ] Add `tasks` table linked to conversations, files, and workflow stages
- [ ] Tasks have assignee (user or agent), status, priority, description
- [ ] Agents can create/update tasks through tool system
- [ ] UI for task board view within a workgroup

### 4.4 — Add provenance tracking
- [ ] Track which agent/user contributed to each section of a file
- [ ] Link file revisions to conversation messages that triggered them
- [ ] Add provenance view in UI showing contribution history
- [ ] Support "authored by" metadata in exports

### 4.5 — Separate short-term and long-term context
- [ ] Define workgroup knowledge store (persistent facts, decisions, guidelines)
- [ ] Thread context = recent conversation; workgroup context = accumulated knowledge
- [ ] Agents reference both when generating replies
- [ ] Add tools for agents to read/write workgroup knowledge

---

## Phase 5: Governance + Operations

### 5.1 — Expand RBAC beyond owner/member
- [ ] Add roles: `admin`, `editor`, `viewer` (in addition to `owner`, `member`)
- [ ] Define permission matrix: who can do what per role
- [ ] Update all permission checks to use role-based logic
- [ ] Add role management API and UI

### 5.2 — Add comprehensive audit pipeline
- [ ] Centralized audit log table for all state-changing operations
- [ ] Log: memberships, file changes, tool runs, admin actions, agent config changes
- [ ] Add API for querying audit log with filters (by user, by type, by time range)
- [ ] Add export capability for compliance

### 5.3 — Add rate limits and abuse controls
- [ ] Per-user rate limits on message posting and API calls
- [ ] Per-agent rate limits on LLM calls
- [ ] Execution quotas per workgroup (total LLM tokens, tool runs)
- [ ] Add quota tracking and alerting

### 5.4 — Add observability stack
- [ ] Structured logging with consistent format (JSON logs)
- [ ] Request tracing (OpenTelemetry or equivalent)
- [ ] Metrics: request latency, agent reply latency, queue depth, error rates
- [ ] Health check endpoints for all services (API, worker, database)
- [ ] Dashboard and alerting configuration

### 5.5 — Add backup and disaster recovery
- [ ] Automated database backup procedures
- [ ] Point-in-time restore capability
- [ ] Document DR procedures and runbooks
- [ ] Test restore from backup

---

## Cross-Cutting Tasks (Apply Throughout)

### CC.1 — Idempotency keys for side-effecting operations
- [ ] Add `idempotency_key` support to message creation and file writes
- [ ] Prevent duplicate processing on retries

### CC.2 — Confirmation gates for destructive actions
- [ ] All destructive operations (delete workgroup, remove member, clear messages) require confirmation
- [ ] Agent-initiated destructive tool calls require human approval

### CC.3 — Backward compatibility
- [ ] Each migration includes rollback path
- [ ] API versioning strategy (header or path-based)
- [ ] Deprecation windows documented for removed features

---

## Current Stats (Baseline)
| Metric | Value |
|---|---|
| Unit tests | 38 |
| Integration tests | 0 |
| `agent_runtime.py` | 1,971 lines |
| `admin_workspace.py` | 2,258 lines |
| `tools.py` | 343 lines |
| `app.js` (frontend) | 2,642 lines |
| `models.py` | 154 lines |
| Test framework | not yet in dependencies |
| Database | SQLite only |
| Real-time transport | 4s polling |
