# TeaParty — Current Research Priorities

*Updated: 2026-03-16. Read by the triage skill to ground relevance judgments.*

## What TeaParty Is

A research platform for durable, scalable agent coordination. Agents are organized in hierarchical teams that collaborate through a formal Conversation for Action (CfA) protocol — a three-phase state machine (intent, planning, execution) with approval gates, cross-phase backtracks, and human oversight.

## Active Focus Areas

1. **Human proxy agent** — A learned model that stands in for the human at approval gates. Currently uses a confidence model (EMA-based) to decide approve vs. escalate. Active work on: intake dialog (prediction-comparison learning), behavioral ritual detection, generative proxy responses. Key gap: the proxy needs better artifact review capabilities (issue #155).

2. **Dispatch coordination** — Hierarchical teams dispatch work to subteams (coding, research, writing, art, editorial) via worktree isolation. Active work on: parallel dispatch, result assembly, subteam CfA cycles. Key gap: subteam approval gates loop infinitely when the proxy can't meaningfully review (issue #155).

3. **Learning system** — Hierarchical memory with scoped retrieval. Institutional learnings, task learnings, proxy learnings, procedural learnings. Active work on: memory indexing, retrieval relevance, learning extraction post-session.

4. **Session resilience** — Orphan detection, session resume from disk, state recovery. Recently fixed: orphan recovery bypassing approval gates (issue #152).

5. **CfA protocol fidelity** — Ensuring the implementation faithfully follows the state machine spec. Backtracks, escalations, approval gates, cross-phase transitions.

## What We're Looking For

Research and techniques relevant to:
- **Agent-agent coordination** — how multiple AI agents collaborate, delegate, resolve conflicts
- **Human-agent collaboration** — how humans and AI agents work together effectively, adjustable autonomy, trust calibration
- **Preference learning from interaction** — learning human preferences from dialog, corrections, approvals (not just RLHF on ratings)
- **Active learning / uncertainty sampling** — knowing when to ask vs. when to act
- **Multi-agent state machines** — formal protocols for agent coordination (beyond ad-hoc prompting)
- **Agent memory and learning** — how agents accumulate and retrieve knowledge across sessions
- **Agent evaluation** — how to measure whether agent coordination is actually working

## What We're NOT Looking For

- Image/video generation techniques
- GPU supply chain analysis
- Robotics and embodied AI (unless the coordination patterns transfer)
- Benchmark gaming and leaderboard results
- General productivity tools
- Enterprise adoption trends
