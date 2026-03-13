# Python State Machine Libraries: Survey for Orchestrator Design

**Research date:** 2026-03-13
**Researcher:** Teaparty Research Agent
**Purpose:** Evaluate Python state machine and workflow libraries to replace bespoke orchestrator state management in `projects/POC/orchestrator/`. The goal is conceptual clarity and native async support without heavyweight infrastructure overhead.

---

## Context and Evaluation Criteria

The TeaParty POC orchestrator (`projects/POC/orchestrator/claude_runner.py`) already uses native asyncio throughout (async subprocess streams, watchdog tasks, event bus publishing). Any state machine library must integrate cleanly with that model.

**Must-have:** native asyncio support (not thread-based fake async)
**Strong preference:** hierarchical/nested states, guards/conditions, entry/exit actions
**Reject if:** requires external server, DSL files, or breaks the "just Python" principle

---

## Libraries Evaluated

### 1. `transitions` (pytransitions)

- **GitHub:** https://github.com/pytransitions/transitions
- **Stars:** ~6,500
- **Latest release:** 0.9.3 (July 2025) / 0.9.4 (Nov 2024 hotfix)
- **License:** MIT
- **Maintenance:** Actively maintained; recent async type annotation improvements

**Async support:** Yes — `AsyncMachine` and `HierarchicalAsyncMachine` use native asyncio. Callbacks are awaited if they are coroutines. User must `await` trigger calls themselves (e.g., `await model.evaporate()`). A companion package `transitions-anyio` also exists for anyio-based environments.

**Hierarchical states:** Yes — `HierarchicalMachine` / `HierarchicalAsyncMachine` support nested states with proper entry/exit semantics inherited from parent states.

**Guards/conditions:** Yes — `conditions` list on each transition definition; a transition only fires if all conditions return truthy. Also `unless` for negated guards.

**Entry/exit/transition actions:** Yes — `on_enter_<state>()` and `on_exit_<state>()` methods are auto-discovered on the model. Transitions support `before`, `after`, `prepare`, and `finalize` callbacks.

**API style:** Dictionary-based definition (or list of dicts). Readable but a bit ceremonious:

```python
from transitions.extensions.asyncio import AsyncMachine

class Orchestrator:
    async def on_enter_running(self):
        await self._start_agent()

    async def is_not_stalled(self):
        return not self._stall_detected

machine = AsyncMachine(
    model=orchestrator,
    states=['idle', 'running', 'paused', 'done', 'failed'],
    transitions=[
        {'trigger': 'start',   'source': 'idle',    'dest': 'running'},
        {'trigger': 'pause',   'source': 'running', 'dest': 'paused',
         'conditions': ['is_not_stalled']},
        {'trigger': 'finish',  'source': 'running', 'dest': 'done'},
        {'trigger': 'fail',    'source': '*',       'dest': 'failed'},
    ],
    initial='idle',
)

await orchestrator.start()  # triggers async on_enter_running
```

**Notable drawbacks:**
- Dictionary-based transition definitions are verbose for many transitions.
- The `HierarchicalAsyncMachine` has more complexity/bugs historically than the flat version.
- No built-in serialization of state for resume/recovery.
- The library has grown organically; the API surface is large and sometimes inconsistent between Machine variants.

---

### 2. `python-statemachine` (fgmacedo)

- **GitHub:** https://github.com/fgmacedo/python-statemachine
- **Stars:** ~1,200
- **Latest release:** 3.0.0 (February 2026)
- **License:** MIT
- **Maintenance:** Actively maintained; version 3.0.0 released 2026-02-24 — very recent

**Async support:** Yes — native asyncio, automatic. If any callback is `async def`, the engine automatically switches to `AsyncEngine`. The public API is identical for sync and async code. Caveat: `activate_initial_state()` must be awaited explicitly before inspecting state if no event has been sent yet.

**Hierarchical states:** Yes — `State.Compound` for nested states, `State.Parallel` for concurrent regions, `HistoryState()` for re-entering prior child states. Full statechart support per the W3C SCXML model.

**Guards/conditions:** Yes — `cond=` (positive) and `unless=` (negative) parameters on transitions. Evaluated in declaration order; first matching guard wins. Guards can reference instance methods by name (string) or as callables.

**Entry/exit/transition actions:** Yes — `on_enter_<state>()` and `on_exit_<state>()` methods auto-discovered. Transition-level `on=`, `before=`, `after=` callbacks. Parameters are **automatically injected by signature inspection** — callbacks only receive the arguments they declare.

**API style:** Declarative class-based DSL using fluent method chaining. Substantially more readable than `transitions`:

```python
from statemachine import StateMachine, State

class OrchestratorSM(StateMachine):
    # States
    idle    = State(initial=True)
    running = State()
    paused  = State()
    done    = State(final=True)
    failed  = State(final=True)

    # Transitions — reads like English
    start  = idle.to(running)
    pause  = running.to(paused, cond="not_stalled")
    resume = paused.to(running)
    finish = running.to(done)
    fail   = running.to(failed) | paused.to(failed)

    # Actions
    async def on_enter_running(self):
        await self._start_agent()

    def not_stalled(self):
        return not self._stall_detected
```

**Notable drawbacks:**
- Newer library; fewer Stack Overflow answers and community examples than `transitions`.
- `activate_initial_state()` must be awaited in async contexts before first use — easy to miss.
- Error handling converts exceptions into `error.execution` events, which requires defensive programming awareness.
- Parallel states add complexity; not needed for sequential orchestration.

---

### 3. `sismic`

- **GitHub:** https://github.com/AlexandreDecan/sismic
- **Stars:** ~159
- **Latest release:** 1.6.11 (October 2025)
- **License:** LGPLv3
- **Maintenance:** Actively maintained at University of Mons; 1,081 commits; published in SoftwareX journal (peer-reviewed)

**Async support:** Threading-based, NOT native asyncio. The `AsyncRunner` class runs the interpreter in a background thread at fixed intervals. This is fundamentally incompatible with asyncio-first code; it does not support `await`-ing callbacks.

**Hierarchical states:** Yes — full SCXML-compliant hierarchical states, composite states, parallel regions, history states.

**Guards/conditions:** Yes — Python expressions evaluated as guards.

**Entry/exit/transition actions:** Yes — full action model; Python code is executed for actions and guards.

**API style:** YAML statechart definition files interpreted by the engine. Statecharts are defined in a separate file, not inline Python. This is academically rigorous but is a mismatch for "just Python" projects.

**Notable drawbacks:**
- Thread-based async is a hard dealbreaker for asyncio orchestrators.
- YAML-based statechart definitions break the "just Python" principle.
- Low community adoption (159 stars) compared to alternatives.
- LGPLv3 license may constrain commercial use.
- Academic focus: better suited for formal verification than production orchestration.

---

### 4. `automat` (glyph/Twisted)

- **GitHub:** https://github.com/glyph/automat
- **Stars:** ~645
- **Latest release:** Multiple tags; active development
- **License:** MIT
- **Maintenance:** Maintained; originally created for Twisted (callback-based async), not asyncio

**Async support:** Designed for Twisted's callback model, not asyncio. No native `async`/`await` support documented. Porting to asyncio contexts is non-trivial.

**Hierarchical states:** No.

**Guards/conditions:** Not explicitly documented in the standard API.

**Entry/exit/transition actions:** Yes — decorators define outputs (actions) triggered by transitions.

**API style:** Decorator-based; transitions are defined as methods decorated with `@input_state.upon(Event).to(output_state)`. Clean for Twisted-style code but awkward in asyncio.

**Notable drawbacks:**
- Twisted-era design; not an asyncio-native library.
- No hierarchical states.
- Limited adoption outside Twisted ecosystem.
- Inadequate for complex orchestration requiring guards and hierarchical states.

---

### 5. `pysm`

- **GitHub:** https://github.com/pgularski/pysm
- **Stars:** ~76
- **Latest release:** v0.3.9-alpha (April 2019)
- **License:** Not specified (MIT assumed from repo)
- **Maintenance:** Effectively abandoned; last release 2019, no recent commits

**Async support:** None documented.

**Hierarchical states:** Yes — HSM and PDA support.

**Guards/conditions:** Yes.

**Entry/exit/transition actions:** Yes.

**Notable drawbacks:** Abandonware. Last release 7 years ago. Do not use.

---

### 6. `maquina`

No Python library named `maquina` with meaningful adoption was found in PyPI or GitHub searches as of March 2026. The name may refer to a very small or unreleased project. Not evaluated further.

---

### 7. `dramatiq`

- **GitHub:** https://github.com/Bogdanp/dramatiq
- **Stars:** ~5,200
- **Latest release:** v2.1.0 (March 2026)
- **License:** LGPL 2.1
- **Maintenance:** Actively maintained

**Classification:** This is a **distributed task queue**, not a state machine library. It handles background job processing via message brokers (Redis, RabbitMQ). It is not applicable to the orchestrator state management problem.

**Async support:** Via `AsyncMiddleware`; not native asyncio throughout.

**Notable drawbacks for this use case:** Wrong tool entirely. Dramatiq models the queuing and execution of discrete background tasks, not the lifecycle states of an orchestration session. Including it would add broker infrastructure (Redis/RabbitMQ) that the orchestrator does not need.

---

### 8. `temporalio` (Temporal Python SDK)

- **GitHub:** https://github.com/temporalio/sdk-python
- **Stars:** ~983
- **Latest release:** Active; Python 3.9 support dropped in 2025
- **License:** MIT
- **Maintenance:** Actively maintained by Temporal Technologies

**Async support:** Yes — workflows are `async def` functions backed by a custom asyncio event loop. First-class asyncio integration.

**Hierarchical states:** Not applicable — Temporal models workflows as durable async functions with activities, not explicit state machines. You get implicit state through code structure.

**Guards/conditions:** Implemented via normal Python control flow inside workflow functions.

**Entry/exit/transition actions:** Implemented via normal Python code; no formal state machine model.

**API style:** Workflows are decorated async functions. Clean for durable execution, but requires a running Temporal server cluster.

**Notable drawbacks:**
- Requires a **separate Temporal server deployment** (Docker/Kubernetes). This is the defining blocker for TeaParty's use case.
- Workflows must be **deterministic** — no random UUIDs or timestamps inside workflow functions; strict sandboxing requirements.
- Substantial learning curve: workers, activities, signals, queries, schedules.
- Designed for distributed, long-running, fault-tolerant workflows across services — overkill for a single-process orchestrator.
- Correct use case: multi-service systems where you need durable execution across restarts, not in-process state machines.

---

### 9. `prefect`

- **GitHub:** https://github.com/PrefectHQ/prefect
- **Stars:** Large (data engineering community)
- **Latest release:** Active in 2025-2026
- **License:** Apache 2.0
- **Maintenance:** Actively maintained by Prefect Technologies

**Classification:** A **workflow orchestration framework** for data pipelines and MLOps, not a state machine library for in-process orchestration.

**Async support:** Yes — flows and tasks support async.

**Hierarchical states:** Not via explicit state machines; flows nest inside flows via subflows.

**Guards/conditions:** Via normal Python control flow.

**Notable drawbacks:**
- Heavyweight: requires Prefect server or Prefect Cloud for full features; persistent task run storage; UI dashboard.
- Designed for data engineering pipelines with observability needs (DAGs, schedules, retries at the task level).
- Not appropriate for replacing in-process state management in an async orchestrator.
- Correct use case: scheduling and monitoring batch data jobs, not managing agent session lifecycle.

---

### 10. `xstate-python` (Stately's official Python port)

- **GitHub:** https://github.com/statelyai/xstate-python
- **Stars:** ~191
- **Latest release:** Work in progress; no stable release
- **License:** MIT
- **Maintenance:** Officially maintained by Stately.ai but explicitly "work in progress"

**Async support:** Unknown; not documented for the Python port.

**Hierarchical states:** Intended (mirrors JavaScript XState v5 which supports statecharts fully), but not yet complete.

**SCXML compliance:** Yes (partial) — SCXML compliance tests present in the repo.

**Notable drawbacks:**
- Explicitly "work in progress" — not production-ready.
- Limited documentation for the Python port.
- The JavaScript XState is mature and excellent; the Python port is not.
- Do not use for production until a stable release is announced.

---

## Comparison Matrix

| Library | Stars | Async | Hierarchical | Guards | Enter/Exit Actions | API Clarity | Infra Needed | License | Verdict |
|---------|-------|-------|-------------|--------|-------------------|-------------|-------------|---------|---------|
| `transitions` | ~6,500 | Yes (native asyncio) | Yes | Yes | Yes | Good (dict-based) | None | MIT | Strong contender |
| `python-statemachine` | ~1,200 | Yes (native asyncio, auto) | Yes | Yes | Yes | Excellent (fluent DSL) | None | MIT | **Recommended** |
| `sismic` | ~159 | No (thread-based) | Yes | Yes | Yes | Poor (YAML files) | None | LGPL | Reject |
| `automat` | ~645 | No (Twisted-era) | No | Limited | Yes | OK | None | MIT | Reject |
| `pysm` | ~76 | No | Yes | Yes | Yes | OK | None | Unknown | Reject (abandoned) |
| `maquina` | N/A | Unknown | Unknown | Unknown | Unknown | Unknown | None | Unknown | Not found |
| `dramatiq` | ~5,200 | Partial | No | No | No | N/A (task queue) | Broker required | LGPL | Wrong tool |
| `temporalio` | ~983 | Yes (asyncio) | No (implicit) | Via code | Via code | Good | Temporal server | MIT | Wrong scale |
| `prefect` | Large | Yes | Via subflows | Via code | Via code | Good | Prefect server | Apache 2.0 | Wrong tool |
| `xstate-python` | ~191 | Unknown | Intended | Intended | Intended | N/A (WIP) | None | MIT | Not ready |

---

## Recommendation

### First choice: `python-statemachine` (v3.0.0)

The February 2026 release of `python-statemachine` 3.0.0 makes it the best match for TeaParty's orchestrator needs:

1. **Clearest API.** The class-based declarative DSL reads like a state diagram. States and transitions are first-class Python objects, not dicts.

2. **Native asyncio, zero ceremony.** Declare callbacks as `async def` and the library switches to its async engine automatically. No separate `AsyncMachine` class to import; no wrapping.

3. **Full statechart support.** Compound states, parallel regions, history states — far more than a flat FSM, useful if the orchestrator gains sub-phases.

4. **Guards are clean.** `cond="not_stalled"` and `unless="is_cancelled"` read as English sentences. The `|` operator composes transitions naturally.

5. **Actively maintained.** 3.0.0 released 17 days before this writing.

**One gotcha to track:** In async contexts, `await sm.activate_initial_state()` is required before any state inspection if no event has been sent. Document this in implementation.

### Second choice: `transitions`

If team familiarity or ecosystem maturity is the priority, `transitions` is the battle-tested option with 6,500 stars and 10+ years of production use. The `AsyncMachine` / `HierarchicalAsyncMachine` are solid but more ceremonious to define. Use `python-statemachine` unless there is a specific reason to prefer `transitions`'s larger existing community.

### Reject for this use case

- `sismic` — thread-based async is incompatible with asyncio-first code
- `automat` — Twisted-era, no asyncio, no hierarchical states
- `pysm` — abandoned since 2019
- `maquina` — not found
- `dramatiq` — task queue, not a state machine
- `temporalio` — correct concept but requires a Temporal server; overkill for in-process orchestration
- `prefect` — data pipeline tool requiring server infrastructure
- `xstate-python` — not production-ready

---

## Implications for TeaParty Orchestrator

The current `ClaudeRunner` in `projects/POC/orchestrator/claude_runner.py` implicitly manages state through instance variables (`_process`, `_extracted_session_id`, `stall_killed`) and linear async flow. A state machine would make the lifecycle explicit:

```
idle → launching → streaming → done
              ↘              ↘
               failed    stalled → killed
```

With `python-statemachine`:

```python
from statemachine import StateMachine, State

class RunnerSM(StateMachine):
    idle       = State(initial=True)
    launching  = State()
    streaming  = State()
    stalled    = State()
    done       = State(final=True)
    failed     = State(final=True)
    killed     = State(final=True)

    launch    = idle.to(launching)
    stream    = launching.to(streaming)
    stall     = streaming.to(stalled)
    kill      = stalled.to(killed)
    finish    = streaming.to(done)
    error     = launching.to(failed) | streaming.to(failed)

    async def on_enter_streaming(self):
        await self._begin_stream_read()

    async def on_enter_stalled(self, elapsed: float):
        await self.event_bus.publish(Event(type=EventType.STALL_DETECTED, ...))

    async def on_enter_done(self, exit_code: int):
        await self.event_bus.publish(Event(type=EventType.RUN_COMPLETE, ...))
```

This makes the orchestrator's state transitions auditable and testable independent of subprocess mechanics.
