# TeaParty: Workgroup Chat (Humans + AI Agents)

Python/FastAPI MVP for team chat with:
- Google login
- Workgroup ownership and member invites
- AI agents as first-class members
- Hidden admin agent + administration conversation per workgroup (OpenAI Agents SDK)
- Direct or topic-based conversations
- Agent response gating (respond only when useful)
- Agent follow-up tasks when no response arrives
- Per-agent tools and evolving preference profile

## Stack
- Backend: FastAPI + SQLModel + SQLite
- Auth: Google ID token verification + app bearer token
- Web client: static HTML/CSS/JS served by FastAPI
- Admin orchestration: OpenAI Agents SDK tools

## Quick Start
1. Install dependencies.
```bash
uv sync
```
2. Set environment variables.
```bash
cp .env.example .env
```
3. Run the app.
```bash
uv run uvicorn teaparty_app.main:app --reload
```
4. Open `http://localhost:8000`.

## Environment Variables
Create `.env` in project root:
```env
TEAPARTY_APP_SECRET=replace-with-strong-secret
TEAPARTY_DATABASE_URL=sqlite:///./teaparty.db
TEAPARTY_GOOGLE_CLIENT_ID=your-google-oauth-client-id.apps.googleusercontent.com
TEAPARTY_ALLOW_DEV_AUTH=true
OPENAI_API_KEY=your-openai-api-key
TEAPARTY_ADMIN_AGENT_USE_SDK=true
TEAPARTY_ADMIN_AGENT_MODEL=gpt-5-nano
```

`TEAPARTY_ALLOW_DEV_AUTH=true` keeps local iteration simple when Google OAuth is not configured.

## Core Concepts
### Workgroup
- Owned by a user (`role=owner`)
- Owner can invite members by email
- Owner can add AI agents
- Can be created from a template (`coding`, `debate`, `roleplay`)
- Template definitions are stored in each owner’s `Administration` workgroup under `.templates/workgroups/`
- Includes a built-in `Administration` conversation and hidden `Admin Agent`

### Agent
Each agent has:
- `name` identity
- `role` functional remit in the team
- `personality` prompt text
- `backstory` context for voice and viewpoint
- `model` and `temperature` generation settings
- `tool_names` capability list
- `response_threshold` gate for deciding when to speak
- `follow_up_minutes` cadence for nudge timing
- `learning_state` profile (`brevity_bias`, `engagement_bias`, `initiative_bias`, `confidence_bias`)
- `sentiment_state` (`valence`, `arousal`, `confidence`)

### Conversations
- `direct`: narrower participant set
- `topic`: group chat with a topic key plus `name` and optional `description`
- `admin`: system conversation for workgroup administration

### Messages
- User and agent messages live in one timeline
- `requires_response` drives follow-up task creation
- Agent replies may be auto-generated when threshold criteria are met

### Admin Conversation
Each workgroup has a hidden `Admin Agent` in an `Administration` conversation backed by the OpenAI Agents SDK.  
The admin agent is configured with explicit tools:
- `add topic <name> [description=<text>]`
- `archive topic <topic|id>`
- `unarchive topic <topic|id>`
- `clear topic <topic|id>` (owner only)
- `remove topic <topic|id>` (owner only)
- `add agent <name> [role=<text>] [personality=<text>] [backstory=<text>] [model=<name>] [temperature=<0..2>]` (owner only)
- `add user <email>` (owner only)
- `remove member <id|email|name>` (owner only)
- `list topics [open|archived|both]`
- `list members` (includes human users and agents with type flag)
- `delete workgroup confirm` (owner only)

If `OPENAI_API_KEY` is missing or SDK calls fail, the server falls back to deterministic command parsing for the same commands.
Recent administration conversation history is passed into the SDK run as context so the agent can resolve references across turns.

## Agent Behavior (Current MVP Logic)
### Respond-or-Not Decision
Score based on:
- direct chat context
- explicit mention (`@agent_name`)
- question presence (`?`)
- prior engagement bias learned from team interactions

Response occurs when score >= `response_threshold`.

### Learning Team Preferences
On incoming user messages, each agent updates:
- `brevity_bias` (signals from words like `brief`, `detailed`)
- `engagement_bias` (mention/question frequency)
- `initiative_bias` and `confidence_bias` (interaction feedback)
- `sentiment_state` (`valence`, `arousal`, `confidence`)

Learning events are logged in `agent_learning_events`.

### Follow-Up
When an agent sends a message that requires response:
- Creates pending `agent_followup_tasks` with `due_at`
- If target user replies, task closes
- `/api/agents/tick` emits follow-up messages for overdue tasks

## Tooling Model
Built-in tools:
- `summarize_topic`
- `list_open_followups`
- `suggest_next_step`

Agents can only call tools listed in their `tool_names`.

## API Overview
### Auth
- `GET /api/config`
- `POST /api/auth/google`
- `POST /api/auth/dev-login` (optional)
- `GET /api/auth/me`

### Workgroups
- `GET /api/workgroup-templates`
- `POST /api/workgroups`
- `GET /api/workgroups`
- `GET /api/workgroups/{workgroup_id}/administration`
- `GET /api/workgroups/{workgroup_id}/members`
- `POST /api/workgroups/{workgroup_id}/invites`
- `GET /api/workgroups/{workgroup_id}/invites`
- `POST /api/workgroups/{workgroup_id}/invites/{token}/accept`
- `POST /api/workgroups/{workgroup_id}/agents`
- `GET /api/workgroups/{workgroup_id}/agents`
- `GET /api/workgroups/{workgroup_id}/tools`

### Conversations
- `POST /api/workgroups/{workgroup_id}/conversations`
- `GET /api/workgroups/{workgroup_id}/conversations` (`include_archived=true` optional)
- `POST /api/workgroups/{workgroup_id}/members/{member_user_id}/direct-conversation`
- `GET /api/conversations/{conversation_id}/messages`
- `POST /api/conversations/{conversation_id}/messages`

### Agent Runtime
- `GET /api/agents/{agent_id}`
- `POST /api/agents/tick`

## Suggested Next Enhancements
1. Replace heuristic response logic with LLM policy + structured evaluator.
2. Add websocket streaming for real-time chat updates.
3. Add robust invite email delivery and deep links.
4. Add agent tool plugins with permission scopes and audit logs.
5. Add durable job queue (RQ/Celery) for follow-up scheduler.
6. Add retrieval memory per workgroup/agent for richer preference learning.
