[Agent Dispatch](../proposal.md) >

# Invocation Model

## Worktree Composition

Before spawning an agent, TeaParty creates a git worktree for the target project and composes its `.claude/skills/` directory from the central skill library:

```bash
git worktree add /tmp/tp/agent-{id} HEAD
mkdir -p /tmp/tp/agent-{id}/.claude/skills

# Compose: common + role + project (project wins on name collision)
ln -s $SKILLS_LIB/common/*         /tmp/tp/agent-{id}/.claude/skills/
ln -s $SKILLS_LIB/roles/{role}/*   /tmp/tp/agent-{id}/.claude/skills/
ln -s $PROJECT/.claude/skills/*    /tmp/tp/agent-{id}/.claude/skills/
```

The skill library lives under `teaparty_home/skills/` with subdirectories `common/`, `roles/{role}/`. Project skills live in the project's own `.claude/skills/`. Symlinks are cheap. Name collisions are resolved by composition order — project overrides role overrides common — following the same override semantics as the workgroup skills catalog.

The orchestrator writes any required `.claude/settings.json` (hooks, permissions) into the worktree before spawning. Worktrees are cleaned up by the orchestrator on agent exit.

## Skill Scope Suppression

```bash
claude -p \
  --setting-sources project \
  --settings "{...agent-specific MCP config...}" \
  --agent {agent-name} \
  "$TASK"
```

`--setting-sources project` suppresses user-scope discovery (`~/.claude/skills/`), so the agent sees exactly the composed set. TeaParty's own orchestration skills — config, workflow, crystallization — live outside any role composition. Project agents never see them.

## MCP Scoping

Each invocation receives its MCP configuration via `--settings` inline JSON. The MCP server is always the TeaParty MCP server, but the tools surface varies by role:

- Config team agents: AddProject, CreateProject, CreateAgent, CreateSkill, etc.
- Coding agents: no config tools; code tools only
- Research agents: no config or code tools; research tools only

`disallowedTools` in the agent definition provides the denylist. The `--settings` override narrows further at invocation time if needed.

## Worktree Reuse

For multi-turn conversations (the caller posts a follow-up), the same worktree is reused — the agent is re-invoked via `--resume` with the updated conversation history. The worktree is not recreated per turn, only per conversation context. Cleanup happens when the conversation closes.
