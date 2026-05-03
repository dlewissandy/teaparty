"""Intervention prompt builder — frames bus-sourced human messages
for ``--resume`` injection at turn boundary.

Cut 29: ``InterventionQueue`` is gone.  The bus is the single source
of truth for human messages — the bridge writes them via
``bus.send(conv_id, 'human', content)``; the orchestrator reads them
at turn boundary using a ``_last_intervention_ts`` watermark, no
separate queue.  ``build_intervention_prompt`` survives because the
prompt formatting (CfA INTERVENE framing, advisor-vs-human framing,
discretion language) is its own concern.

The function accepts any message-shaped object with ``content``,
``sender``, and ``timestamp`` attributes — bus ``Message`` objects
match that shape directly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from teaparty.util.role_enforcer import RoleEnforcer


def build_intervention_prompt(
    messages: list[Any],
    role_enforcer: 'RoleEnforcer | None' = None,
) -> str:
    """Build the prompt injected via --resume when delivering an intervention.

    Multiple messages are coalesced into a single prompt.  The prompt
    frames the intervention per the CfA extensions spec: the lead has
    full discretion to continue with adjustment, backtrack, or withdraw.

    When a ``role_enforcer`` is provided, advisor messages are framed as
    advisory input (lower weight than authoritative decider input).
    """
    has_advisory = False
    parts: list[str] = []
    for msg in messages:
        is_advisor = role_enforcer and role_enforcer.is_advisory(msg.sender)
        if is_advisor:
            has_advisory = True
            parts.append(f'[Advisory input from {msg.sender}]: {msg.content}')
        elif msg.sender == 'human':
            parts.append(msg.content)
        else:
            parts.append(f'[{msg.sender}]: {msg.content}')

    body = '\n\n'.join(parts)

    prompt = (
        '[CfA INTERVENE: Unsolicited human input received at turn boundary.]\n\n'
        f'{body}\n\n'
        'You have full discretion: continue with adjustment, '
        'backtrack to an earlier phase, or withdraw. '
        'Assess whether this changes the current trajectory.'
    )

    if has_advisory:
        prompt += (
            '\n\nNote: advisory input carries lower weight than '
            'authoritative decider input. Consider it but you are '
            'not obligated to follow it.'
        )

    return prompt
