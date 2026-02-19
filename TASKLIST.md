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

## Phase 2: Projects

### 2.1 Project Model

#### Data Model
- [ ] `Project` model: id, org_id, title, scope, status, engagement_id, created_by_agent_id, timestamps
- [ ] `ProjectWorkgroup` join model: project_id, workgroup_id (participating workgroups)
- [ ] Project conversation (kind: "project")
- [ ] DB migration

#### Backend
- [ ] `POST /api/organizations/{org_id}/projects` -- create project
- [ ] `GET /api/organizations/{org_id}/projects` -- list projects
- [ ] `GET /api/projects/{id}` -- project details with status, workgroups, jobs
- [ ] `PATCH /api/projects/{id}` -- update status
- [ ] Project conversation creation with workgroup leads as participants
- [ ] Project-to-job linking (jobs carry `project_id`)

#### Frontend
- [ ] Project list view within organization
- [ ] Project detail view with participating workgroups and constituent jobs
- [ ] Project conversation chat interface
- [ ] Project creation flow (select workgroups, describe scope)

#### Tests
- [ ] Project CRUD tests
- [ ] Project-workgroup association tests
- [ ] Project-job linking tests
- [ ] Project conversation participant tests

### 2.2 Cross-Workgroup Agent Teams

#### Backend
- [ ] Project conversation dispatch routing (new `kind` in agent_dispatch routing table)
- [ ] Workgroup leads as project conversation participants
- [ ] Workgroup lead tools from project context: `create_job` (in own workgroup, linked to project)
- [ ] Project workspace file scoping

#### Agent Runtime
- [ ] Add `project` to conversation kinds in dispatch routing
- [ ] Project-level team session with workgroup leads

#### Tests
- [ ] Project dispatch routing tests
- [ ] Cross-workgroup job creation tests
- [ ] Project workspace isolation tests

### 2.3 Project Orchestration

#### Backend
- [ ] Org lead tool: `create_project` with workgroup selection
- [ ] Project status aggregation from constituent jobs
- [ ] Job sequencing support (dependency hints in project.json)
- [ ] Project completion logic (all jobs completed -> project completed)

#### Tests
- [ ] Project orchestration end-to-end tests
- [ ] Status aggregation tests
- [ ] Completion propagation tests
