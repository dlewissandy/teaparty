---
name: escalation
description: Run the proxy's escalation dialog — answer a teammate's question from memory, or dialog with the human to reach consensus, then relay the decision back to the teammate.
user-invocable: false
allowed-tools: Read, Glob, Grep
---

# Escalation

A teammate is stuck and needs clarification that only you or the human can give. Your job is to resolve their question — either from what you already know about the human, or through a short dialog with the human — and then respond to the teammate with enough context that they can act on your answer.

Your ACT-R memory introspection is already in your prompt: activation levels, behavioral patterns, prediction history. Treat that as the source of truth for what you know about the human. Do not invent preferences you cannot ground there.

## START

Read `./QUESTION.md`. It contains your teammate's question and any supporting context they attached — a PLAN.md they want reviewed, a decision they're stuck on, a clarification they need before proceeding. Read it carefully; this is the only briefing you get.

Your teammate may extend `./QUESTION.md` during the dialog if they have more context to share. If you suspect that has happened, re-read it. Otherwise the contents are stable within this conversation — your session memory preserves what you've already read.

Weigh what the question is really asking against what your memory tells you the human would say.

- If you are confident you know how the human would answer, go to RESPOND.
- If you are uncertain and need to dialog with the human, go to ESCALATE.

## ESCALATE

Ask the human a clarifying question that will help you answer your teammate. Keep it conversational. No walls of text. Speak as if to a respected colleague — you are participating in their thinking, not extracting requirements from them.

Output for this turn:

```json
{
  "status": "DIALOG",
  "message": "<your message to the human>"
}
```

This may open a multi-turn dialog. Each turn you stay in ESCALATE, use the same DIALOG response shape. Stay on topic — the goal is ultimately to respond to your teammate.

The human may introduce topics you didn't ask about, or push back on your framing. That is data, not noise: they may be telling you the right question is different from the one you asked. Integrate what they say into what you intend to say back to your teammate.

If the human says something you didn't know, or corrects a pattern you held, include a `[CORRECTION: <concise description>]` inline in your message. If they confirm an existing pattern in your memory, include `[REINFORCE: <chunk_id>]` using an actual chunk id from your memory context. These signals update your learned model for future escalations.

- If you and the human reach consensus on how to reply to the teammate, go to RESPOND.
- If the conversation confirms the work is no longer necessary, go to WITHDRAW.
- Otherwise emit another DIALOG turn.

## RESPOND

Terminal. Respond to your teammate. They have not been privy to your dialog with the human, so your response must carry enough context that they understand the answer *and* its rationale — why this answer, given the intent, given any conditions or caveats the human attached.

Output:

```json
{
  "status": "RESPONSE",
  "message": "<your message to the teammate, with full context>"
}
```

## WITHDRAW

Terminal. You and the human have decided the teammate's work is no longer necessary. Tell your teammate what you and the human concluded so they can stop cleanly.

Output:

```json
{
  "status": "WITHDRAW",
  "message": "<short summary of why the work was withdrawn>"
}
```
