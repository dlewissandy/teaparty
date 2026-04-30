# Collaborate

A teammate is stuck and needs clarification that only you or the human can give.  The project's policy on this decision is collaborative: answer from memory when you're confident, dialog with the human when you're not.  Use your judgment about which applies here.

Your ACT-R memory introspection is in your prompt: activation levels, behavioral patterns, prediction history.  Treat that as the source of truth for what you know about the human.  Do not invent preferences you cannot ground there.

## START

Your teammate's question is in your conversation history (the most recent message from them).  Your cwd is a real-file clone of the caller's worktree — every file the caller had is there at `./<relpath>`.

Now do diligence on the work itself.  This is required, not advisory — your reply must be grounded in what was actually delivered, not in how the question describes it.

1. Walk the worktree (your cwd).  List directories.  Identify what is a deliverable (manuscript, code, document), what is planning artifact (`INTENT.md`, `PLAN.md`, `RESEARCH.md`, `.scratch/`), and what is configuration.
2. Read the relevant artifacts directly.  For an approval gate, read the actual deliverable — chapter files, generated code, written documents.  For a status query, read the state files.  For a configuration question, read the configs.
3. Verify the question's claims against the artifacts — counts, paths, presence/absence.  Trust-but-verify is the literal procedure.  When the prose says the work is done, the burden is on the artifacts to show it.
4. Form an opinion from what was actually delivered, not from the question's framing.  If the prose disagrees with the artifacts, name the gap.  Your reply must name the specific files you inspected.

Now weigh what the question is really asking against what your memory tells you the human would say.

- If you are confident you know how the human would answer, read `respond.md` in this skill directory and execute it.
- If you are uncertain and need to dialog with the human, continue to ESCALATE.

## ESCALATE

Conduct a dialog with the human.  Start with a clarifying question that will help you answer your teammate.  Keep it conversational.  No walls of text.  Speak as if to a respected colleague — you are participating in their thinking, not extracting requirements from them.  This may open a multi-turn dialog.  Stay on topic — the goal is ultimately to respond to your teammate.

The human may introduce topics you didn't ask about, or push back on your framing.  That is data, not noise: they may be telling you the right question is different from the one you asked.  Integrate what they say into what you intend to say back to your teammate.

If the human says something you didn't know, or corrects a pattern you held, include a `[CORRECTION: <concise description>]` inline in your message.  If they confirm an existing pattern in your memory, include `[REINFORCE: <chunk_id>]` using an actual chunk id from your memory context.  These signals update your learned model for future escalations.

Continue until you have enough clarity to answer your teammate's question with confidence.

- If you and the human reach consensus on how to reply to the teammate, read `respond.md` in this skill directory and execute it.
- If the conversation confirms the work is no longer necessary, read `withdraw.md` in this skill directory and execute it.
