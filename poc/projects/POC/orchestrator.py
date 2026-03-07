#!/usr/bin/env python3
"""orchestrator.py — Multi-agent message broker.

Each agent is an actor with:
  - inbox:   messages received, in arrival order
  - pending: dispatches sent, awaiting response

The orchestrator delivers messages. When an agent is woken up, it sees
its full inbox and pending list — like checking your messages and todo
list. The agent decides what's important, what's blocked, what to act on.

The orchestrator does not assign priority or order. Agents are agents.

Usage:
    orchestrator.py --agents <json> --agent <lead> \
        --settings <file> --cwd <dir> --stream <file> \
        [--session-log <file>] [--resume <session-id>] \
        [--max-turns N] "<task>"
"""
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass, field


# ── Data structures ──

@dataclass
class Message:
    """A message in an agent's inbox."""
    sender: str
    content: str
    summary: str
    arrived_at: float = field(default_factory=time.time)


@dataclass
class PendingItem:
    """An outgoing dispatch awaiting response."""
    recipient: str
    summary: str
    dispatched_at: float = field(default_factory=time.time)


class Mailbox:
    """Per-agent inbox and pending list."""

    def __init__(self, name):
        self.name = name
        self.inbox: list[Message] = []
        self.pending: list[PendingItem] = []
        self.session_id: str | None = None
        self.running = False

    def enqueue(self, sender, content, summary):
        self.inbox.append(Message(sender=sender, content=content,
                                  summary=summary))

    def add_pending(self, recipient, summary):
        self.pending.append(PendingItem(recipient=recipient, summary=summary))

    def resolve_pending(self, responder):
        """Remove the oldest pending item for `responder`."""
        for i, p in enumerate(self.pending):
            if p.recipient == responder:
                return self.pending.pop(i)
        return None

    def drain_inbox(self):
        """Take all messages out of inbox. Returns list, clears inbox."""
        msgs = list(self.inbox)
        self.inbox.clear()
        return msgs

    def format_wakeup(self, messages):
        """Format the agent's input: inbox + pending list.

        The agent sees everything and decides what to do.
        """
        parts = []
        for msg in messages:
            parts.append(f"From {msg.sender}:\n{msg.content}")

        text = "\n\n---\n\n".join(parts)

        if self.pending:
            lines = []
            for p in self.pending:
                age = int(time.time() - p.dispatched_at)
                age_str = f"{age}s ago" if age < 60 else f"{age // 60}m ago"
                lines.append(
                    f"  - {p.recipient}: \"{p.summary}\" ({age_str})")
            text += (
                f"\n\n[PENDING — {len(self.pending)} dispatches outstanding]\n"
                + "\n".join(lines)
            )

        return text


# ── Logging ──

def log(session_log, category, message):
    if not session_log:
        return
    ts = time.strftime("%H:%M:%S")
    try:
        with open(session_log, "a") as f:
            f.write(f"[{ts}] {category:<8s} | {message}\n")
    except OSError:
        pass


# ── Stream parsing ──

def parse_stream(stream_file):
    """Parse JSONL stream for session_id, outgoing SendMessage calls, result."""
    session_id = None
    outgoing = []
    result_text = None

    with open(stream_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = ev.get("type", "")

            if etype == "system" and ev.get("subtype") == "init":
                session_id = ev.get("session_id")

            if etype == "assistant":
                for block in ev.get("message", {}).get("content", []):
                    if not isinstance(block, dict):
                        continue
                    if (block.get("type") == "tool_use"
                            and block.get("name") == "SendMessage"):
                        inp = block.get("input", {})
                        outgoing.append({
                            "recipient": inp.get("recipient", ""),
                            "content": inp.get("content", ""),
                            "summary": inp.get("summary", ""),
                        })

            if etype == "result":
                result_text = ev.get("result", "")

    return session_id, outgoing, result_text


def extract_result_text(stream_file):
    last_text = ""
    with open(stream_file) as f:
        for line in f:
            try:
                ev = json.loads(line.strip())
            except (json.JSONDecodeError, ValueError):
                continue
            if ev.get("type") == "result":
                return ev.get("result", "")
            if ev.get("type") == "assistant":
                for block in ev.get("message", {}).get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        last_text = block.get("text", "")
    return last_text


# ── Agent execution ──

def run_agent(agents_json, agent_name, task, settings_file, cwd,
              stream_file, extra_args=None, resume_session=None):
    cmd = [
        "claude", "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--setting-sources", "user",
        "--agents", agents_json,
        "--agent", agent_name,
        "--permission-mode", "acceptEdits",
    ]
    if settings_file:
        cmd += ["--settings", settings_file]
    if resume_session:
        cmd += ["--resume", resume_session]
    if extra_args:
        cmd += extra_args

    with open(stream_file, "w") as sf:
        subprocess.run(
            cmd, input=task, stdout=sf, stderr=sys.stderr,
            text=True, cwd=cwd, timeout=3600,
        )

    return parse_stream(stream_file)


def append_stream(src_file, dst_file):
    with open(src_file) as src, open(dst_file, "a") as dst:
        for line in src:
            dst.write(line)


# ── Agent wakeup ──

_run_counter = 0
_counter_lock = threading.Lock()


def _next_run_id():
    global _run_counter
    with _counter_lock:
        _run_counter += 1
        return _run_counter


def _wake_agent(pool, mbox, agents_json, settings_file, cwd,
                output_stream, session_log, extra_args, running_futures):
    """Drain inbox, format input, start agent in thread pool."""
    messages = mbox.drain_inbox()
    if not messages:
        return

    task_input = mbox.format_wakeup(messages)
    rid = _next_run_id()
    stream = f"{output_stream}.{mbox.name}-{rid:03d}"
    resume = mbox.session_id
    senders = list({m.sender for m in messages})

    # Log each message being delivered so communication is visible
    summaries = [m.summary or m.content[:60] for m in messages]
    log(session_log, "WAKE",
        f"#{rid} {mbox.name}: {'; '.join(summaries)}"
        + (f" [{len(mbox.pending)} pending]" if mbox.pending else ""))

    def run():
        session_id, outgoing, result = run_agent(
            agents_json, mbox.name, task_input,
            settings_file, cwd, stream,
            extra_args=extra_args, resume_session=resume,
        )
        return {
            "agent": mbox.name,
            "stream_file": stream,
            "session_id": session_id,
            "outgoing": outgoing,
            "result_text": result or extract_result_text(stream),
            "senders": senders,
        }

    fut = pool.submit(run)
    mbox.running = True
    running_futures[fut] = mbox.name


# ── Routing helpers ──

def _route_outgoing(sender, outgoing, mailboxes, session_log):
    """Deliver an agent's SendMessage calls to recipient inboxes."""
    for msg in outgoing:
        recipient = msg.get("recipient", "")
        if recipient not in mailboxes:
            log(session_log, "WARN",
                f"{sender} -> unknown '{recipient}' — dropped")
            continue

        content = msg.get("content", "")
        summary = msg.get("summary", content[:60])

        mailboxes[recipient].enqueue(sender, content, summary)
        mailboxes[sender].add_pending(recipient, summary)

        log(session_log, "ROUTE", f"{sender} -> {recipient}: {summary}")


def _wake_idle(pool, mailboxes, agents_json, settings_file, cwd,
               output_stream, session_log, extra_args, running_futures):
    """Wake any agent that has mail and isn't running."""
    for mbox in mailboxes.values():
        if mbox.inbox and not mbox.running:
            _wake_agent(pool, mbox, agents_json, settings_file, cwd,
                        output_stream, session_log, extra_args,
                        running_futures)


# ── Main orchestration ──

def orchestrate(agents_json, lead_name, task, settings_file, cwd,
                output_stream, session_log=None, resume_session=None,
                extra_args=None, max_turns=20):
    """
    Message broker loop.

    Delivers messages between agents. Each agent sees its inbox and
    pending list and decides what to do. Terminates when all inboxes
    are empty, nothing is running, and the lead has no pending items.
    """
    global _run_counter
    _run_counter = 0

    pool = ThreadPoolExecutor(max_workers=10)
    running_futures = {}
    result = None

    # Init mailboxes
    agent_names = list(json.loads(agents_json).keys()) \
        if isinstance(agents_json, str) else list(agents_json.keys())
    mailboxes = {name: Mailbox(name) for name in agent_names}
    lead = mailboxes[lead_name]

    open(output_stream, "w").close()

    # ── Initial lead run ──
    rid = _next_run_id()
    lead_stream = f"{output_stream}.{lead_name}-{rid:03d}"
    log(session_log, "ORCH", f"Initial: {lead_name}")

    session_id, outgoing, result = run_agent(
        agents_json, lead_name, task,
        settings_file, cwd, lead_stream,
        extra_args=extra_args, resume_session=resume_session,
    )
    lead.session_id = session_id or resume_session
    append_stream(lead_stream, output_stream)

    _route_outgoing(lead_name, outgoing, mailboxes, session_log)
    _wake_idle(pool, mailboxes, agents_json, settings_file, cwd,
               output_stream, session_log, extra_args, running_futures)

    lead_turns = 1

    # ── Event loop ──
    while running_futures:
        if lead_turns >= max_turns:
            log(session_log, "ORCH", f"Max lead turns ({max_turns})")
            break

        done, _ = wait(set(running_futures.keys()),
                       return_when=FIRST_COMPLETED)

        for fut in done:
            agent_name = running_futures.pop(fut)
            mbox = mailboxes[agent_name]
            mbox.running = False

            try:
                r = fut.result()
            except Exception as exc:
                log(session_log, "ERROR", f"{agent_name}: {exc}")
                # Notify anyone waiting on this agent
                for mb in mailboxes.values():
                    if mb.resolve_pending(agent_name):
                        mb.enqueue(agent_name,
                                   f"{agent_name} failed: {exc}",
                                   f"{agent_name} error")
                continue

            append_stream(r["stream_file"], output_stream)

            if r.get("session_id"):
                mbox.session_id = r["session_id"]

            if agent_name == lead_name:
                lead_turns += 1
                result = r.get("result_text", "")

            # Route outgoing messages
            _route_outgoing(agent_name, r.get("outgoing", []),
                            mailboxes, session_log)

            # Resolve pending for senders who were waiting on this agent
            for sender in r.get("senders", []):
                if sender in mailboxes:
                    mailboxes[sender].resolve_pending(agent_name)

            # If agent finished without sending any messages, notify
            # the senders so they know it completed
            if not r.get("outgoing"):
                text = r.get("result_text", "")
                summary = f"{agent_name} done"
                for sender in r.get("senders", []):
                    if sender in mailboxes and sender != agent_name:
                        mailboxes[sender].enqueue(
                            agent_name,
                            text or f"{agent_name} completed.",
                            summary)
                        log(session_log, "ROUTE",
                            f"{agent_name} -> {sender}: {summary}")

        # Wake any agent that now has mail
        _wake_idle(pool, mailboxes, agents_json, settings_file, cwd,
                   output_stream, session_log, extra_args, running_futures)

        # Termination: nothing running, all inboxes empty, lead has
        # nothing pending
        if (not running_futures
                and all(not mb.inbox for mb in mailboxes.values())
                and not lead.pending):
            log(session_log, "ORCH", "Complete — all clear")
            break

    pool.shutdown(wait=True)

    if lead.session_id:
        with open(f"{output_stream}.session-id", "w") as f:
            f.write(lead.session_id)

    return lead.session_id, result


# ── CLI ──

def main():
    import argparse
    p = argparse.ArgumentParser(description="Multi-agent message broker")
    p.add_argument("--agents", required=True)
    p.add_argument("--agent", required=True, help="Lead agent name")
    p.add_argument("--settings", default="")
    p.add_argument("--cwd", default=".")
    p.add_argument("--stream", required=True)
    p.add_argument("--session-log", default="")
    p.add_argument("--resume", default="")
    p.add_argument("--max-turns", type=int, default=20)
    p.add_argument("task")

    args, extra = p.parse_known_args()

    sid, result = orchestrate(
        agents_json=args.agents,
        lead_name=args.agent,
        task=args.task,
        settings_file=args.settings or None,
        cwd=args.cwd,
        output_stream=args.stream,
        session_log=args.session_log or None,
        resume_session=args.resume or None,
        extra_args=extra or None,
        max_turns=args.max_turns,
    )

    if result:
        print(result)


if __name__ == "__main__":
    main()
