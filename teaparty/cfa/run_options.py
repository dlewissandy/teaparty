"""Resolved-configuration bundle for ``Orchestrator``.

Cut 23: ``Orchestrator.__init__`` used to take 33 positional/keyword
arguments — required dependencies, optional dependencies, and CLI
knobs all jumbled together.  This dataclass collects the optional
knobs and injected dependencies into one bundle so the constructor
shrinks to its required-infrastructure subset plus a single
``options`` argument.

Required core dependencies (cfa_state, phase_config, event_bus,
input_provider, the path quartet, project_slug, poc_root, task,
session_id) stay as kwargs on ``__init__`` — those are infrastructure
the engine cannot run without.

Everything else lives here:

* **Run-mode flags** — ``skip_intent`` / ``intent_only`` / ``plan_only``
  / ``execute_only`` / ``flat`` / ``suppress_backtracks`` /
  ``proxy_enabled`` / ``never_escalate`` / ``team_override``.  These are
  CLI knobs the driver (``cfa/session.py``) resolves before calling
  the engine.
* **Resume context** — ``phase_session_ids`` / ``last_actor_data`` /
  ``parent_heartbeat``.  Populated when a session is being resumed
  from disk; empty for a fresh session.
* **Injected dependencies** — ``project_dir`` (often equal to
  ``project_workdir`` but allowed to differ for the dispatch CLI),
  ``role_enforcer`` / ``escalation_modes``, ``llm_backend`` /
  ``llm_caller``, ``proxy_invoker_fn`` / ``on_dispatch`` /
  ``paused_check``.  Wired by the driver — engine owns nothing about
  how they're constructed.

Defaults match the pre-#23 engine semantics: empty strings, ``False``,
``None`` as appropriate.  Callers that constructed engines without
these kwargs continue to work unchanged when they pass ``RunOptions()``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from teaparty.util.role_enforcer import RoleEnforcer


@dataclass
class RunOptions:
    """Resolved configuration the engine treats as read-only after construction."""

    # ── Run-mode flags ──────────────────────────────────────────────────────
    # These are CLI knobs resolved by cfa/session.py before construction.
    skip_intent: bool = False
    intent_only: bool = False
    plan_only: bool = False
    execute_only: bool = False
    flat: bool = False
    suppress_backtracks: bool = False
    proxy_enabled: bool = True
    never_escalate: bool = False
    team_override: str = ''

    # ── Resume context ──────────────────────────────────────────────────────
    # Populated when resuming from a prior session; empty for a fresh start.
    phase_session_ids: dict[str, str] | None = None
    last_actor_data: dict[str, Any] | None = None
    parent_heartbeat: str = ''

    # ── Injected dependencies ──────────────────────────────────────────────
    # The driver (cfa/session.py / cfa/dispatch.py) constructs these and
    # hands the engine a ready-to-use instance.
    project_dir: str = ''
    role_enforcer: RoleEnforcer | None = None
    escalation_modes: dict[str, str] | None = None
    llm_backend: str = 'claude'
    llm_caller: Any = None
    proxy_invoker_fn: Callable[..., Awaitable[None]] | None = None
    on_dispatch: Callable[[dict], Any] | None = None
    paused_check: Callable[[], bool] | None = None
