# TeaParty Roadmap

## Vision

TeaParty is a platform where teams of humans and AI agents co-author files and collaborate in chat, organized through a corporate hierarchy that mirrors real organizations. The goal is a system where humans focus on direction and review while agents handle execution, coordination, and routine communication.

## Current State

The following exists and works today:

- **Organizations and workgroups**: Org/workgroup hierarchy with CRUD, membership, and invites
- **Agents**: Configurable agents with roles, personalities, models, tools, learning state
- **Conversations**: Job, direct, task, engagement, admin, and activity conversations
- **Agent runtime**: Claude Code CLI team sessions with bidirectional `stream-json` I/O; single-agent and multi-agent dispatch
- **Engagements**: Basic workgroup-to-workgroup engagement model with lifecycle tracking and message syncing (Phase 1 migrates to org-level scoping)
- **Jobs**: Job model with conversation, workflow state, and engagement linking
- **Workspaces**: Basic git repo + worktree integration for workspace-enabled workgroups
- **Virtual files**: JSON-based file store with topic-scoped isolation and file materialization
- **Workflows**: Markdown-based workflow definitions with agent-driven execution
- **Admin workspace**: Claude SDK-based administration conversation per workgroup
- **Frontend**: Vanilla JS single-page app with org/workgroup navigation, chat, file browser
- **Auth**: Google OAuth + dev auth

## Phase 1: Core Hierarchy Completion (MVP)

Establish the full corporate hierarchy and interaction model.

### Home Level
- Home concept: user-level aggregation of all owned/joined organizations
- Home agent: can create organizations, propose partnerships, onboard users
- Home view in the frontend

### Partnership Model
- Partnership data model (directional trust links between orgs)
- Partnership lifecycle: proposed -> accepted -> active -> revoked
- Partnership CRUD endpoints
- Partnership management UI

### Engagement Revision
- Revise engagement model from workgroup-to-workgroup to org-to-org (via partnerships)
- Engagement chain tracking for cycle prevention
- Contract-based workspace visibility for engagements
- Org lead as the engagement handler (replacing "coordinator" concept)
- Updated engagement UI

### Feedback Bubble-Up
- Mechanism for feedback requests to flow: job agent -> workgroup lead -> org lead -> human
- Response routing back down the hierarchy
- Notification when human input is needed

### Human Interaction Restrictions
- Enforce: humans can DM org lead but not workgroup leads or members directly
- Ensure all human-agent interaction goes through proper channels
- Update frontend to reflect permitted interaction patterns

## Phase 2: Projects

Cross-workgroup collaboration within a single organization.

### Project Model
- Project data model (status, participating workgroups, engagement_id)
- Project conversation kind
- Project workspace (shared files accessible to workgroup leads)
- Project CRUD endpoints

### Cross-Workgroup Agent Teams
- Project conversations with workgroup leads as participants
- Workgroup leads can create jobs in their workgroup from project context
- Project-to-job linking

### Project Orchestration
- Org lead tools for project creation and management (`create_project`)
- Sequencing and dependency tracking between project jobs
- Project status aggregation from constituent jobs

## Phase 3: Agent Cognition

Equip agents with memory, reflection, and adaptive learning.

- Memory retrieval pipeline (recency, relevance, importance weighting)
- Reflection engine (periodic synthesis of higher-level insights from raw memories)
- Memory types: episodic (what happened), semantic (what I know), procedural (how to do things)
- Agent learning events with structured signals
- Cross-agent shared memory within a workgroup (with access control)

See [docs/cognitive-architecture.md](docs/cognitive-architecture.md) for the full design.

## Phase 4: Workspace and Git

Complete the workspace system for code-centric workgroups.

- Full workspace manager with robust branch-per-job
- Merge workflows (conflict detection, resolution UI)
- File sync between git worktrees and virtual file store
- Branch comparison and diff views in the frontend
- Commit history per job

## Phase 5: Sandbox and Code Execution (Future)

Isolated execution environments for agent code work.

- Docker sandbox containers with resource limits
- Claude Code CLI delegation (agents describe tasks, Claude Code executes)
- Warm container pool for low-latency job startup
- Network isolation presets (isolated vs. connected)
- Custom Docker images per workgroup

See [docs/sandbox-design.md](docs/sandbox-design.md) for the full architecture.

## Phase 6: Advanced Features (Future)

- Organization custom tools (prompt tools, webhook tools, code tools)
- Tool grants between partnered organizations
- Organization templates with richer bootstrapping
- Remote git integration (push/pull to GitHub, GitLab)
- Agent skill libraries (reusable capability packages)
- Org directory for public discovery (complement to partnerships)
- Real-time updates via WebSocket (replace polling)
