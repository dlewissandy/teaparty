# TeaParty Task List

Granular task breakdown for [ROADMAP.md](ROADMAP.md) Phases 1-2.

---

## Phase 1: Core Hierarchy Completion (MVP)

### 1.1 Home Level

#### Data Model
- [ ] Define Home concept (user-level, no DB table needed -- derived from org memberships)
- [ ] Home agent creation on user signup (or first login)
- [ ] Home agent configuration (model, personality, tools)

#### Backend
- [ ] `GET /api/home` endpoint: return user's organizations, pending partnership proposals, summary stats
- [ ] Home agent conversation endpoint (DM with the home agent)
- [ ] Home agent tools: `create_organization`, `list_organizations`, `propose_partnership`

#### Frontend
- [ ] Home view: cross-org dashboard showing all user's organizations
- [ ] Home agent chat interface
- [ ] Navigation: Home as the top-level entry point

### 1.2 Partnership Model

#### Data Model
- [ ] `Partnership` model: id, source_org_id, target_org_id, status, proposed_by_user_id, timestamps
- [ ] DB migration for partnerships table
- [ ] Unique constraint: one partnership per (source, target) pair

#### Backend
- [ ] `POST /api/organizations/{org_id}/partnerships` -- propose partnership
- [ ] `GET /api/organizations/{org_id}/partnerships` -- list partnerships (both directions)
- [ ] `PATCH /api/partnerships/{id}` -- accept, decline, revoke
- [ ] Partnership validation: prevent self-partnership, duplicate partnerships
- [ ] Hook into engagement creation: verify active partnership exists in the correct direction

#### Frontend
- [ ] Partnership management panel in org settings
- [ ] Partnership proposal flow (select target org, send proposal)
- [ ] Partnership status indicators (pending, active, revoked)
- [ ] Inbound partnership requests view

#### Tests
- [ ] Partnership CRUD tests
- [ ] Direction validation tests (A->B does not imply B->A)
- [ ] Engagement-partnership linkage tests

### 1.3 Engagement Revision

#### Data Model
- [ ] Migrate `Engagement` model: replace `source_workgroup_id`/`target_workgroup_id` with `source_org_id`/`target_org_id`
- [ ] Add `engagement_chain` field (JSON list of org IDs for cycle prevention)
- [ ] Add `project_ids` field or project-engagement linking
- [ ] DB migration with data transformation for existing engagements

#### Backend
- [ ] Revise engagement creation to require partnership (or be internal)
- [ ] Cycle prevention check at engagement creation (walk the chain)
- [ ] Engagement chain propagation when sub-engagements are created
- [ ] Depth limit enforcement (configurable, default 5)
- [ ] Update engagement endpoints to use org-level scoping
- [ ] Contract-based workspace visibility (deliverables/ visible, workspace/ restricted)

#### Frontend
- [ ] Updated engagement creation flow (select partnered org)
- [ ] Engagement chain visualization
- [ ] Contract-based file visibility in engagement file browser
- [ ] Internal engagement creation flow (human -> org lead)

#### Tests
- [ ] Engagement org-level scoping tests
- [ ] Cycle prevention tests (A->B->C->A rejected)
- [ ] Depth limit tests
- [ ] Contract visibility tests
- [ ] Internal engagement tests

### 1.4 Feedback Bubble-Up

#### Backend
- [ ] Feedback request model or convention (message metadata? dedicated message type?)
- [ ] Routing logic: job conversation -> workgroup lead notification -> org lead notification -> human notification
- [ ] Response routing: human response -> org lead -> workgroup lead -> job conversation
- [ ] Integration with existing agent todo/follow-up system

#### Frontend
- [ ] Feedback request indicators in job/project/engagement views
- [ ] Notification badge when human input is needed
- [ ] Quick response interface from org-level view

#### Tests
- [ ] Feedback routing end-to-end tests
- [ ] Multi-level escalation tests

### 1.5 Human Interaction Restrictions

#### Backend
- [ ] Enforce: block DM creation with workgroup members (non-lead agents)
- [ ] Enforce: block DM creation with workgroup leads (only org lead is DM-able)
- [ ] Allow: DM with org lead
- [ ] Allow: participation in job/project/engagement conversations

#### Frontend
- [ ] Hide DM option for workgroup members and workgroup leads
- [ ] Show DM option only for org lead
- [ ] Clear affordances for joining job/project/engagement conversations

#### Tests
- [ ] DM restriction enforcement tests
- [ ] Conversation participation permission tests

### 1.6 Org Lead Agent

#### Backend
- [ ] Ensure org lead agent is created in Administration workgroup on org creation
- [ ] Org lead tools: `create_project`, `create_job` (cross-workgroup), `list_workgroup_jobs`, `read_job_status`, `post_to_job`, `complete_engagement`
- [ ] Org lead prompt context: org structure, workgroup capabilities, active engagements/projects

#### Tests
- [ ] Org lead creation tests
- [ ] Orchestration tool dispatch tests

---

## Phase 2: Hierarchical Agent Teams (Projects)

See [docs/hierarchical-teams.md](docs/hierarchical-teams.md) for the full design.

### 2.1 Liaison Agent Infrastructure

#### Agent Definition
- [ ] Liaison agent definition generator: builds ephemeral `AgentDefinition` from workgroup metadata
- [ ] Liaison spawn prompt template with behavioral constraints (relay-only, must use `relay_to_subteam`)
- [ ] Liaison naming convention: `liaison-{workgroup-slug}`

#### `relay_to_subteam` Tool
- [ ] Tool implementation: first call creates Job + conversation + launches sub-team session
- [ ] Tool implementation: subsequent calls send message to existing sub-team via `TeamSession.send_message()`
- [ ] Tool response: returns sub-team status/output summary to liaison
- [ ] Job creation with linkage: sets `project_id` and `engagement_id` on created jobs
- [ ] Team parameter inheritance: job session uses workgroup defaults, overridden by project config

#### `relay_to_partner` Tool (External Liaisons)
- [ ] Tool implementation: reads/writes to engagement conversation for cross-org communication
- [ ] External liaison definition generator

#### Async Notification Bridge
- [ ] Detect sub-team events in `team_bridge.py` (completion, question, stall, timeout)
- [ ] Inject notification messages into parent team session addressed to the relevant liaison
- [ ] Event types: `sub_team_completed`, `sub_team_question`, `sub_team_stalled`, `sub_team_timeout`

#### Tests
- [ ] Liaison definition generation tests
- [ ] `relay_to_subteam` tool: first-call job creation tests
- [ ] `relay_to_subteam` tool: subsequent-call message relay tests
- [ ] Async notification bridge tests
- [ ] Team parameter inheritance tests

### 2.2 Project Team Lifecycle

#### Backend
- [ ] Project team session creation: generates org lead + liaison definitions, launches `claude` process
- [ ] Project dispatch routing: kind `project` -> hierarchical team session (update routing table)
- [ ] Project prompt injection: sends `project.prompt` as initial message to team session
- [ ] Project status transitions: `pending -> in_progress` on team session start
- [ ] Project completion detection: all linked jobs completed -> notify org lead -> mark project complete
- [ ] Graceful shutdown cascade: project complete -> shutdown liaisons -> shutdown sub-teams
- [ ] Resource limit enforcement: `max_turns`, `max_cost_usd`, `max_time_seconds` per level

#### Failure Handling
- [ ] Sub-team stall detection (no output within `max_time_seconds`)
- [ ] Stall notification to liaison and team lead
- [ ] Liaison non-responsiveness detection
- [ ] Replacement liaison spawning (picks up sub-team state from Job record)

#### Tests
- [ ] Project team session creation tests
- [ ] Project dispatch routing tests
- [ ] Completion detection and propagation tests
- [ ] Graceful shutdown cascade tests
- [ ] Stall detection and notification tests
- [ ] Resource limit enforcement tests

### 2.3 Workgroup Team Configuration

#### Data Model
- [ ] Add team config fields to Workgroup model: `team_model`, `team_permission_mode`, `team_max_turns`, `team_max_cost_usd`, `team_max_time_seconds`
- [ ] DB migration for new workgroup fields
- [ ] Default values: `permission_mode=acceptEdits`, `model=claude-sonnet-4-6`, `max_turns=30`

#### Backend
- [ ] Configuration inheritance logic: workgroup defaults <- project overrides <- job overrides
- [ ] `PATCH /api/workgroups/{id}` -- update team config fields
- [ ] Validation: permission_mode must be valid Claude Code mode

#### Frontend
- [ ] Workgroup team configuration screen (model selector, permission mode, limits)
- [ ] Configuration display in workgroup settings panel

#### Tests
- [ ] Configuration inheritance tests (workgroup -> project -> job)
- [ ] Configuration validation tests
- [ ] API endpoint tests

### 2.4 Project CRUD and UI

#### Data Model
- [ ] Extend existing `Project` model if needed (already has `model`, `max_turns`, `permission_mode`, `workgroup_ids`)
- [ ] Ensure `project_id` foreign key on Job model

#### Backend
- [ ] `POST /api/organizations/{org_id}/projects` -- create project (triggers team session)
- [ ] `GET /api/organizations/{org_id}/projects` -- list projects with status
- [ ] `GET /api/projects/{id}` -- project details with workgroups, jobs, team session status
- [ ] `PATCH /api/projects/{id}` -- update status, cancel
- [ ] Project-to-job aggregation: list jobs per project with status

#### Frontend
- [ ] Project list view within organization
- [ ] Project detail view: participating workgroups, constituent jobs, status per job
- [ ] Project conversation chat interface (messages from project team session)
- [ ] Project creation flow: select workgroups, describe scope, configure overrides
- [ ] Job status indicators within project view (linked from sub-teams)

#### Tests
- [ ] Project CRUD tests
- [ ] Project-job aggregation tests
- [ ] Project conversation tests
- [ ] Frontend rendering tests
