# Instrumentation Points

Added 2026-04-05 to `agent_spawner.py`, `bus_event_listener.py`, `office_manager.py`, `mcp_server.py`.

All timing goes to `.teaparty/logs/bridge.log` (orchestrator namespace) and `.teaparty/logs/mcp-server.log`.

## Spawner (`spawn_timing` in bridge.log)

Emitted by `AgentSpawner.spawn()` after process completes.

```
spawn_timing: role='X' compose=0.12s roster=0.03s cmd_build=0.00s proc_start=0.05s proc_run=7.23s parse=0.00s total=7.43s
```

| Field | What it measures |
|-------|-----------------|
| `compose` | `compose_worktree()` — CLAUDE.md + agents + skills + settings |
| `roster` | `_derive_roster()` — workgroup YAML scan |
| `cmd_build` | Command array construction |
| `proc_start` | `asyncio.create_subprocess_exec` — process fork |
| `proc_run` | `await proc.communicate()` — the actual `claude -p` execution |
| `parse` | `_parse_json_output()` — extract session_id + result from stdout |

## Compose Breakdown (`compose_worktree_timing` in bridge.log)

Emitted by `compose_worktree()`.

```
compose_worktree_timing: role='X' claude_md=0.001s agents=0.005s skills=0.003s settings=0.008s total=0.017s
```

| Field | What it measures |
|-------|-----------------|
| `claude_md` | Copy CLAUDE.md from management.md or project.md |
| `agents` | Symlink agent definitions from .teaparty/management/agents/ |
| `skills` | Layered skill composition (common → role → project) |
| `settings` | YAML merge + JSON write for .claude/settings.json |

## OM spawn_fn (`spawn_fn_timing` in bridge.log)

Emitted by the OM's `spawn_fn` closure.

```
spawn_fn_timing: member='X' git_worktree=0.45s spawner=7.43s total=7.88s
```

| Field | What it measures |
|-------|-----------------|
| `git_worktree` | `git worktree add --detach` |
| `spawner` | Full `spawner.spawn()` call (includes compose + claude -p) |

## Bus Listener (`Send complete ... e2e=` in bridge.log)

Emitted by `_handle_send_connection`.

```
Send complete: context_id='X' member='Y' result_len=N e2e=12.34s
```

End-to-end from socket receive to response write back to caller.

## MCP Send Handler (`send_post_timing` in mcp-server.log)

Emitted by `_default_send_post()` inside the spawned agent's MCP server process.

```
send_post_timing: member='X' connect=0.001s write=0.000s wait=11.70s total=11.70s
```

| Field | What it measures |
|-------|-----------------|
| `connect` | Unix socket connection to parent's BusEventListener |
| `write` | Request serialization + send |
| `wait` | Blocking on parent to spawn recipient and return result |

## Session JSONL Timestamps

Each spawned agent's session at `~/.claude/projects/{hash}/{session_id}.jsonl` has timestamps on every event. Parse with:

```bash
cat SESSION.jsonl | python3 -c "
import json, sys
from datetime import datetime
prev = None
for line in sys.stdin:
    obj = json.loads(line.strip())
    ts = obj.get('timestamp', '')
    if not ts: continue
    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    delta = f'+{(dt - prev).total_seconds():.1f}s' if prev else ''
    prev = dt
    t = obj.get('type', '')
    print(f'{ts}  {delta:>8s}  {t}')
"
```
