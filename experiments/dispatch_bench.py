"""Benchmark for hierarchical dispatch round-trip time.

Measures: Human → OM listener → config-lead → project-specialist → result
Uses AgentSession — the same codepath as the production bridge server —
so session state, worktrees, and cleanup all follow the standard lifecycle.

Usage: uv run python experiments/dispatch_bench.py [--label LABEL] [single|hier|both]
"""
import asyncio
import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEAPARTY_HOME = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.teaparty')
REPO_ROOT = os.path.dirname(TEAPARTY_HOME)


async def bench_single_dispatch(label: str = ''):
    """Benchmark: single config-lead invocation."""
    from teaparty.teams.session import AgentSession
    from teaparty.messaging.conversations import ConversationType

    qualifier = f'bench-{uuid.uuid4().hex[:8]}'
    session = AgentSession(
        TEAPARTY_HOME,
        agent_name='configuration-lead',
        scope='management',
        qualifier=qualifier,
        conversation_type=ConversationType.CONFIG_LEAD,
        dispatches=False,
    )
    session._bus.create_conversation(ConversationType.CONFIG_LEAD, qualifier)
    session._bus.send(session.conversation_id, 'human', 'Tell me a joke.')

    t0 = time.monotonic()
    result = await session.invoke(cwd=REPO_ROOT)
    elapsed = time.monotonic() - t0

    print(json.dumps({
        'label': label or 'single-dispatch',
        'elapsed_s': round(elapsed, 2),
        'result_len': len(result),
        'session_id': (session.claude_session_id or '')[:8],
        'result_preview': result[:100],
    }))
    return elapsed


async def bench_hierarchical_dispatch(label: str = ''):
    """Benchmark: config-lead → project-specialist (two levels)."""
    from teaparty.teams.session import AgentSession
    from teaparty.messaging.conversations import ConversationType

    qualifier = f'bench-{uuid.uuid4().hex[:8]}'
    session = AgentSession(
        TEAPARTY_HOME,
        agent_name='configuration-lead',
        scope='management',
        qualifier=qualifier,
        conversation_type=ConversationType.CONFIG_LEAD,
        dispatches=True,
    )
    session._bus.create_conversation(ConversationType.CONFIG_LEAD, qualifier)
    session._bus.send(
        session.conversation_id,
        'human',
        'Ask the project-specialist to tell you a joke. '
        'Use the Send tool to reach them. '
        'If you cannot reach them, say so.',
    )

    t0 = time.monotonic()
    result = await session.invoke(cwd=REPO_ROOT)
    elapsed = time.monotonic() - t0

    await session.stop()

    print(json.dumps({
        'label': label or 'hierarchical-dispatch',
        'elapsed_s': round(elapsed, 2),
        'result_len': len(result),
        'session_id': (session.claude_session_id or '')[:8],
        'result_preview': result[:150],
    }))
    return elapsed


async def main():
    label = ''
    if '--label' in sys.argv:
        idx = sys.argv.index('--label')
        if idx + 1 < len(sys.argv):
            label = sys.argv[idx + 1]

    mode = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else 'both'

    if mode in ('single', 'both'):
        await bench_single_dispatch(label=label or 'single')
    if mode in ('hier', 'both'):
        await bench_hierarchical_dispatch(label=label or 'hierarchical')


if __name__ == '__main__':
    asyncio.run(main())
