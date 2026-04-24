"""Subprocess env vars for the CfA dispatch CLI fallback path.

Agents inside a claude subprocess can invoke the dispatch CLI directly
(``python3 -m teaparty.cfa.dispatch --team ...``).  The CLI accepts
``--session-worktree`` / ``--infra-dir`` / ``--project-slug`` /
``--cfa-parent-state`` explicitly, but also falls back to ``POC_*``
env vars when those flags aren't passed (see ``cfa/dispatch.py``).

This module is the single home of the env-var convention used for
that CLI fallback.  Engine used to compose this dict inline as
``_build_env_vars`` — but it's a launch-time subprocess-env concern,
not engine state, so it lives here instead.

Returned dict is intended for ``launch(env_vars=...)``, which passes
it to ``ClaudeRunner`` which adds it to the subprocess environment.
"""
from __future__ import annotations

import os


def cfa_dispatch_env_vars(
    *,
    project_slug: str,
    project_workdir: str,
    infra_dir: str,
    session_worktree: str,
) -> dict[str, str]:
    """Build the POC_* env vars an agent's dispatch-CLI subprocess reads.

    The four ``POC_*`` keys map to the dispatch CLI's positional context
    (project, project repo root, session infra dir, session worktree)
    and ``POC_CFA_STATE`` is the parent CfA state path the CLI uses as
    a default for ``--cfa-parent-state``.

    These vars only matter when an agent shells out to the dispatch
    CLI inside its session.  Other launches (chat tier, leaf workers
    that don't dispatch via CLI) don't need them — but setting them
    is harmless: they're inherited but unused.
    """
    return {
        'POC_PROJECT': project_slug,
        'POC_PROJECT_DIR': project_workdir,
        'POC_SESSION_DIR': infra_dir,
        'POC_SESSION_WORKTREE': session_worktree,
        'POC_CFA_STATE': os.path.join(infra_dir, '.cfa-state.json'),
    }
