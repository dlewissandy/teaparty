"""Phase-completion learning hooks — what the engine fires at phase boundaries.

Currently one hook lives here: a premortem generator that runs at the
planning → execution boundary so the post-session prospective-extraction
pipeline has input.  Skill-selection and skill-correction archival used
to live here too, but those concerns moved into the planning skill
itself (it owns SELECT / APPLY / RECONCILE).

Best-effort by design: a learning failure must not abort a CfA session.
Errors are caught + logged + swallowed.
"""
from __future__ import annotations

import logging

_log = logging.getLogger('teaparty.learning.phase_hooks')


def try_write_premortem(*, infra_dir: str, task: str) -> None:
    """Write a premortem for the next phase, swallowing errors.

    Called at the planning → execution boundary so the prospective-
    extraction pipeline has a premortem to work with.  Any failure
    (missing PLAN.md, LLM unreachable, write error) is logged and
    swallowed — premortem generation must not abort a CfA session.
    """
    try:
        from teaparty.learning.extract import write_premortem
        write_premortem(infra_dir=infra_dir, task=task)
    except Exception as exc:
        _log.warning('Premortem generation failed (non-fatal): %s', exc)
