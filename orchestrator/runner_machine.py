"""ClaudeRunner lifecycle as a declared state machine.

Makes the subprocess states (idle, launching, streaming, stalled, killed,
done, failed) and their transitions explicit, auditable, and independently
testable — replacing the implicit lifecycle managed through instance
variables and linear async flow.
"""
from __future__ import annotations

import logging

from statemachine import State, StateMachine

_log = logging.getLogger('runner_machine')


class RunnerSM(StateMachine):
    """Claude CLI subprocess lifecycle.

    States:
        idle       — runner constructed, not yet started
        launching  — subprocess created, stdin fed, awaiting first output
        streaming  — actively receiving stdout from the CLI
        stalled    — watchdog detected no output for stall_timeout seconds
        done       — subprocess exited cleanly (exit code 0)
        failed     — subprocess exited with error or could not start
        killed     — subprocess was killed (stall timeout or cancellation)
    """
    idle      = State(initial=True)
    launching = State()
    streaming = State()
    stalled   = State()
    done      = State(final=True)
    failed    = State(final=True)
    killed    = State(final=True)

    # Transitions
    launch = idle.to(launching)
    stream = launching.to(streaming)
    stall  = streaming.to(stalled)
    kill   = stalled.to(killed) | streaming.to(killed)
    finish = streaming.to(done) | stalled.to(done)
    error  = launching.to(failed) | streaming.to(failed) | stalled.to(failed)
