"""Benchmark for hierarchical dispatch round-trip time.

Measures: Human → OM listener → config-lead → project-specialist → result
Bypasses the bridge/OM — directly exercises the BusEventListener + AgentSpawner
pipeline to isolate dispatch overhead from the OM's own claude session.

Usage: uv run python experiments/dispatch_bench.py [--label LABEL]
"""
import asyncio
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEAPARTY_HOME = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.teaparty')
REPO_ROOT = os.path.dirname(TEAPARTY_HOME)


async def bench_single_dispatch(label: str = ''):
    """Benchmark: OM → config-lead (single level)."""
    from teaparty.cfa.agent_spawner import AgentSpawner

    spawner = AgentSpawner(teaparty_home=TEAPARTY_HOME)

    # Create worktree
    context_id = f'bench-single-{int(time.time())}'
    agent_dir = os.path.join(TEAPARTY_HOME, 'management', 'agents', 'office-manager', 'agents', f'bench_{context_id}')
    subprocess.run(['git', 'worktree', 'add', '--detach', agent_dir], cwd=REPO_ROOT, capture_output=True)

    # Build MCP config (no sockets — leaf agent, doesn't need Send)
    venv_python = os.path.join(REPO_ROOT, '.venv', 'bin', 'python3')
    mcp_config = {
        'teaparty-config': {
            'command': venv_python,
            'args': ['-m', 'teaparty.mcp.server.main'],
            'env': {},
        },
    }

    composite = '## Task\nTell me a joke.\n\n## Context\n'

    t0 = time.monotonic()
    session_id, result_text = await spawner.spawn(
        composite, worktree=agent_dir, role='configuration-lead',
        project_dir=REPO_ROOT, is_management=True,
        mcp_config=mcp_config,
    )
    elapsed = time.monotonic() - t0

    # Cleanup
    subprocess.run(['git', 'worktree', 'remove', '--force', agent_dir], cwd=REPO_ROOT, capture_output=True)

    print(json.dumps({
        'label': label or 'single-dispatch',
        'elapsed_s': round(elapsed, 2),
        'result_len': len(result_text),
        'session_id': session_id[:8] if session_id else '',
        'result_preview': result_text[:100] if result_text else '(empty)',
    }))
    return elapsed


async def bench_hierarchical_dispatch(label: str = ''):
    """Benchmark: OM → config-lead → project-specialist (two levels)."""
    from teaparty.cfa.agent_spawner import AgentSpawner
    from teaparty.messaging.listener import BusEventListener
    from teaparty.messaging.conversations import SqliteMessageBus
    import tempfile
    import uuid

    spawner = AgentSpawner(teaparty_home=TEAPARTY_HOME)
    infra_dir = os.path.join(TEAPARTY_HOME, 'management', 'agents', 'office-manager')
    bus_db_path = os.path.join(infra_dir, 'bench-messages.db')

    # Parent context
    parent_ctx = f'agent:bench:lead:{uuid.uuid4()}'
    bus = SqliteMessageBus(bus_db_path)
    bus.create_agent_context(parent_ctx, initiator_agent_id='bench', recipient_agent_id='bench')
    bus.close()

    venv_python = os.path.join(REPO_ROOT, '.venv', 'bin', 'python3')

    def _child_mcp_config(member, context_id, sockets):
        return {
            'teaparty-config': {
                'command': venv_python,
                'args': ['-m', 'teaparty.mcp.server.main'],
                'env': {
                    'SEND_SOCKET': sockets[0],
                    'REPLY_SOCKET': sockets[1],
                    'CLOSE_CONV_SOCKET': sockets[2],
                    'AGENT_ID': member,
                    'CONTEXT_ID': context_id,
                },
            },
        }

    async def spawn_fn(member, composite, context_id):
        safe_id = context_id.replace(':', '_').replace('/', '_')
        agent_dir = os.path.join(infra_dir, 'agents', f'bench_{safe_id}')
        subprocess.run(['git', 'worktree', 'add', '--detach', agent_dir], cwd=REPO_ROOT, capture_output=True)
        if not os.path.isdir(agent_dir):
            os.makedirs(agent_dir, exist_ok=True)
        session_id, result_text = await spawner.spawn(
            composite, worktree=agent_dir, role=member,
            project_dir=REPO_ROOT, is_management=True,
            extra_env={'CONTEXT_ID': context_id, 'AGENT_ID': member},
            mcp_config=_child_mcp_config(member, context_id, listener_sockets),
        )
        return (session_id, agent_dir, result_text)

    async def resume_fn(member, composite, session_id, context_id):
        return session_id

    async def reply_fn(context_id, session_id, message):
        pass

    async def reinvoke_fn(context_id, session_id, message):
        pass

    async def cleanup_fn(worktree_path):
        subprocess.run(['git', 'worktree', 'remove', '--force', worktree_path], cwd=REPO_ROOT, capture_output=True)

    listener = BusEventListener(
        bus_db_path=bus_db_path,
        initiator_agent_id='bench',
        current_context_id=parent_ctx,
        spawn_fn=spawn_fn,
        resume_fn=resume_fn,
        reply_fn=reply_fn,
        reinvoke_fn=reinvoke_fn,
        cleanup_fn=cleanup_fn,
    )
    listener_sockets = await listener.start()

    composite = (
        '## Task\n'
        'Ask the project-specialist to tell you a joke. '
        'Use the Send tool to reach them. '
        'If you cannot reach them, say so.\n\n'
        '## Context\n'
    )

    lead_dir = os.path.join(infra_dir, 'agents', f'bench_lead_{int(time.time())}')
    subprocess.run(['git', 'worktree', 'add', '--detach', lead_dir], cwd=REPO_ROOT, capture_output=True)
    if not os.path.isdir(lead_dir):
        os.makedirs(lead_dir, exist_ok=True)

    t0 = time.monotonic()
    session_id, result_text = await spawner.spawn(
        composite,
        worktree=lead_dir,
        role='configuration-lead',
        project_dir=REPO_ROOT,
        is_management=True,
        extra_env={'CONTEXT_ID': parent_ctx, 'AGENT_ID': 'configuration-lead'},
        mcp_config=_child_mcp_config('configuration-lead', parent_ctx, listener_sockets),
    )
    elapsed = time.monotonic() - t0

    await listener.stop()

    # Cleanup bench DB
    try:
        os.unlink(bus_db_path)
    except OSError:
        pass

    print(json.dumps({
        'label': label or 'hierarchical-dispatch',
        'elapsed_s': round(elapsed, 2),
        'result_len': len(result_text),
        'session_id': session_id[:8] if session_id else '',
        'result_preview': result_text[:150] if result_text else '(empty)',
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
