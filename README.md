# TeaParty

A platform where teams of humans and AI agents co-author files and collaborate in chat, organized through a corporate hierarchy.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full conceptual model.

## Stack

- **Backend**: FastAPI + SQLModel + SQLite
- **Frontend**: Vanilla JS (no framework, no build tools)
- **Auth**: Google ID token verification + app bearer token
- **Agent runtime**: Claude Code CLI (team sessions via `stream-json`)
- **LLM calls**: All through `llm_client.create_message()`

## Quick Start

```bash
uv sync
cp .env.example .env
uv run uvicorn teaparty_app.main:app --reload
```

Open `http://localhost:8000`.

### Environment Variables

Create `.env` in project root:

```env
TEAPARTY_APP_SECRET=replace-with-strong-secret
TEAPARTY_DATABASE_URL=sqlite:///./teaparty.db
TEAPARTY_GOOGLE_CLIENT_ID=your-google-oauth-client-id.apps.googleusercontent.com
TEAPARTY_ALLOW_DEV_AUTH=true
ANTHROPIC_API_KEY=your-anthropic-api-key
```

`TEAPARTY_ALLOW_DEV_AUTH=true` enables local dev login when Google OAuth is not configured.

### Running Tests

```bash
PYTHONPATH=. uv run pytest tests/ --tb=short -q
```

## Core Concepts

### Corporate Hierarchy

**Home** > **Organization** > **Workgroup**

- **Home**: A user's view across all their organizations. Has a home agent that can create orgs and manage partnerships.
- **Organization**: Contains workgroups, members, partnerships, engagements, and projects. Has an org lead agent in the Administration workgroup.
- **Workgroup**: A department-like unit with agents and jobs. Has a workgroup lead agent.
- **Partnerships**: Directional trust links between organizations that enable cross-org engagements.

### Work Units

Each work unit gets its own agent team, workspace, and conversation.

- **Job**: Single-workgroup work. Agents execute tasks within a workgroup's scope.
- **Project**: Cross-workgroup collaboration within an org. Workgroup leads coordinate.
- **Engagement**: Cross-org work between partnered organizations. Org leads negotiate and coordinate.

### Agents

Each agent has: `name`, `role`, `personality`, `backstory`, `model`, `temperature`, `tool_names`, and `is_lead`.

Agents are autonomous -- they decide what to do based on context, not scripts. Agent output is never truncated. Workflows are advisory, not mandatory.

### Conversations

- **job**: Work execution with workgroup agents
- **project**: Cross-workgroup coordination with workgroup leads
- **engagement**: Cross-org negotiation and tracking
- **direct**: DM with an agent (org lead only for humans)
- **task**: Single-agent persistent session
- **admin**: Workgroup administration

### Human Interaction

Humans interact primarily through agents. They can participate in job, project, and engagement conversations, and DM the org lead. They cannot DM workgroup members or workgroup leads directly. Feedback requests bubble up: job -> workgroup lead -> org lead -> human.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) -- Full conceptual model
- [Engagements and Partnerships](docs/engagements-and-partnerships.md) -- Cross-org collaboration
- [File Layout](docs/file-layout.md) -- Virtual file tree structure
- [Workflows](docs/workflows.md) -- Workgroup-internal playbooks
- [Agent Dispatch](docs/agent-dispatch.md) -- Message routing and team sessions
- [Sandbox Design](docs/sandbox-design.md) -- Future: Docker containers and git integration
- [Cognitive Architecture](docs/cognitive-architecture.md) -- Future: Agent learning and memory
- [Roadmap](ROADMAP.md) -- Phased implementation plan
- [Task List](TASKLIST.md) -- Granular task breakdown
