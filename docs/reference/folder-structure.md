# Folder Structure

TeaParty's on-disk layout: the source package, the configuration tree, and the runtime session hierarchy.

---

## Source Code

All source code lives under a single `teaparty/` top-level Python package. Subpackages are domain-aligned for progressive discovery — the top-level listing reveals the system's shape.

```
teaparty/                           # top-level package
  __main__.py                       # CLI entry point
  cfa/                              # CfA protocol engine
    engine.py                       # state machine execution, approval gates
    session.py                      # session lifecycle, phase orchestration
    actors.py                       # actor definitions (agent runner, gate)
    dispatch.py                     # hierarchical dispatch
    phase_config.py                 # per-phase Claude Code configuration
    statemachine/
      cfa_state.py                  # 5-state machine: literal TRANSITIONS dict + transition()
    gates/                          # escalation / intervention pipeline
      queue.py                      # gate queue
      escalation.py                 # escalation listener
      intervention.py               # intervention handling
      intervention_listener.py      # intervention socket
  proxy/                            # human proxy system (independent of CfA)
    agent.py                        # proxy agent, consult_proxy()
    approval_gate.py                # confidence-based gate decisions (monitoring-only)
    memory.py                       # ACT-R memory retrieval
    metrics.py                      # prediction tracking
    hooks.py                        # proxy hook handlers
    presence.py                     # proxy presence tracking
    record_approval.py              # approval outcome recording
    ablation.py                     # ablation harness
    evaluate.py                     # evaluation harness
    merge_model.py                  # cross-session model merge
  learning/                         # hierarchical memory & learning (independent of CfA)
    extract.py                      # post-session learning extraction
    consolidation.py                # learning consolidation
    cluster.py                      # learning clustering
    promotion.py                    # session → project → global promotion
    episodic/                       # session entries, indexing, compaction
    procedural/                     # skill and pattern acquisition
    research/                       # PDF extraction, arXiv, Semantic Scholar
  bridge/                           # HTML dashboard + bridge server
    server.py                       # aiohttp bridge server (localhost:8081)
    message_relay.py                # WebSocket message relay
    poller.py                       # state polling
    stats.py                        # statistics computation
    state/                          # state management
      reader.py                     # state reader
      writer.py                     # state writer
      heartbeat.py                  # session heartbeat / liveness
      dashboard_stats.py            # dashboard statistics
      navigation.py                 # navigation state
    static/                         # HTML/CSS/JS frontend
  mcp/                              # MCP server
    server/main.py                  # MCP server entry point
    tools/                          # MCP tool implementations
      config_crud.py                # configuration CRUD (19 tools)
      escalation.py                 # escalation tools
      intervention.py               # intervention tools
      messaging.py                  # Send, Reply, CloseConversation, etc.
  runners/                          # LLM execution backends
    launcher.py                     # unified agent launch function
    claude.py                       # ClaudeRunner subprocess wrapper
    ollama.py                       # Ollama backend
    deterministic.py                # deterministic backend (testing)
    machine.py                      # runner state machine
  messaging/                        # event bus, conversations, routing
    bus.py                          # event bus
    conversations.py                # SqliteMessageBus, conversation state
    dispatcher.py                   # message dispatch
    listener.py                     # BusEventListener, agent contexts
  teams/                            # agent session management
    session.py                      # AgentSession (unified, all agent types)
    stream.py                       # stream event relay
    office_manager_tools.py         # OM-specific MCP tool handlers
  workspace/                        # git worktree and job lifecycle
    worktree.py                     # worktree creation and management
    job_store.py                    # job catalog
    merge.py                        # task merge
    withdraw.py                     # withdrawal and cleanup
  config/                           # runtime config loading
    config_reader.py                # YAML config reader, catalog merging
    roster.py                       # roster derivation
  scheduling/                       # cron execution
    scheduler.py                    # task scheduler
    driver.py                       # scheduler driver
  scripts/                          # LLM-powered utility scripts
  util/                             # shared utilities
    context_budget.py               # context budget monitoring
    scratch.py                      # scratch file lifecycle
    cost_tracker.py                 # cost tracking
```

---

## Configuration Tree

The `.teaparty/` directory holds all agent, workgroup, and project configuration. It has two scopes with identical internal structure:

```
.teaparty/
  teaparty.yaml                     # management-level config (projects, humans, etc.)
  management/                       # management scope (cross-project)
    teaparty.yaml                   # management team definition
    management.md                   # management CLAUDE.md
    settings.yaml                   # base settings for management agents
    agents/{name}/                  # agent definitions (catalog)
      agent.md                      # agent definition (YAML frontmatter + prose)
      settings.yaml                 # per-agent settings override (optional)
      pins.yaml                     # pinned artifacts (optional)
    workgroups/{name}.yaml          # workgroup definitions
    skills/{name}/                  # skill definitions
      SKILL.md                      # skill entry point
    sessions/                       # runtime: chat-tier sessions
      {session-id}/                 # one per chat conversation
        metadata.json               # session state, conversation map

{project_root}/.teaparty/
  project.yaml                      # project-level config
  project/                          # project scope
    agents/{name}/agent.md          # project-specific agent overrides
    workgroups/{name}.yaml          # project-scoped workgroups
    skills/{name}/                  # project-scoped skills
    settings.yaml                   # base settings for project agents
    sessions/                       # runtime: chat-tier sessions
      {conversation-id}/            # one per chat conversation
        metadata.json               # session state
```

Config (agents, skills, workgroups, settings) is checked into git. Sessions and jobs are ephemeral (gitignored under `.teaparty/jobs/` and the `sessions/` directories).

### Agent definition resolution

The launcher resolves agent definitions by looking in the invocation scope first, then falling back to management scope. A project can override any management-level agent definition by providing its own version.

### Session vs. job placement

There are two runtime tiers with separate on-disk layouts:

- **Chat-tier sessions** (OM conversations, project-lead conversations, configuration interactions) → `.teaparty/{scope}/sessions/{conversation-id}/`. No worktree — chat does not produce file artifacts.
- **Job-tier worktrees** (CfA-driven work) → `{project}/.teaparty/jobs/job-{id}--{slug}/worktree/`. Every job and every dispatched task gets its own git worktree (see Job Worktrees below).

---

## Job Worktrees

Jobs are user-initiated work requests tracked per project:

```
{project_root}/.teaparty/
  jobs/
    jobs.json                       # index (derived, not authoritative)
    job-{id}--{slug}/
      worktree/                     # git worktree for the job
      job.json                      # job state
      tasks/
        tasks.json                  # task index
        task-{id}--{slug}/
          worktree/                 # git worktree for the task
          task.json                 # task state
```

Every job and every task gets its own git worktree. Task branches fork from the job branch; the lead merges them back. Removing a job directory removes all child tasks.

---

## Tests

All tests live in `tests/` at the repo root. Tests use `unittest.TestCase` with `_make_*()` helpers, not pytest fixtures.

---

## Dashboard

The dashboard is an HTML application served by `teaparty/bridge/server.py` on `localhost:8081`. Static files live in `teaparty/bridge/static/`:

- `index.html` — main dashboard with project cards
- `config.html` — hierarchical config screens (management → project → workgroup → agent)
- `chat.html` — chat window with filters and subtask navigation
- `artifacts.html` — file viewer with chat-in-context blade
- `stats.html` — statistics and charts
- `styles.css` — shared stylesheet

---

## Further Reading

- [Overview](../overview.md) — master conceptual model
- [Team Configuration](team-configuration.md) — `.teaparty/` config tree design
- [Agent Dispatch](../systems/messaging/index.md) — message routing and dispatch
