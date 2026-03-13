#!/usr/bin/env python3
"""Classify a human's free-text review response into a CfA action.

Replaces discrete menus (y/n/e/r/b) at CfA review points with natural
language understanding.  The human types whatever they want; this script
classifies the scope (approve, correct, backtrack, withdraw) and extracts
the actionable feedback.

Usage:
    classify_review.py --state <STATE> --response "<text>"
        [--intent-summary "<text>"] [--plan-summary "<text>"]

Returns ACTION<TAB>FEEDBACK_TEXT on stdout.
"""
import argparse
import subprocess
import sys

MAX_SUMMARY_CHARS = 500

# ── Valid actions per CfA state ──

STATE_ACTIONS = {
    # ASSERT states — human reviews an artifact
    "INTENT_ASSERT": ["dialog", "approve", "correct", "withdraw"],
    "PLAN_ASSERT": ["dialog", "approve", "correct", "refine-intent", "withdraw"],
    "WORK_ASSERT": ["dialog", "approve", "correct", "revise-plan", "refine-intent", "withdraw"],
    # ESCALATE states — human answers a question or accepts the work as done
    "INTENT_ESCALATE": ["dialog", "clarify", "complete", "withdraw"],
    "PLANNING_ESCALATE": ["dialog", "clarify", "complete", "withdraw"],
    "TASK_ESCALATE": ["dialog", "clarify", "complete", "withdraw"],
    # FAILURE state — infrastructure failure, human decides next step
    "FAILURE": ["retry", "escalate", "backtrack", "withdraw"],
}

# ── Prompt templates ──

ASSERT_PROMPT = """You are a CfA (Conversation for Action) review classifier. A human has just reviewed a document at the {state} decision point. Classify their natural language response into an action.

--- CONTEXT ---
CfA state: {state}
{context_block}
{dialog_history_block}
--- HUMAN RESPONSE ---
{response}

--- CLASSIFICATION RULES ---
1. APPROVE: unqualified positive with NO substantive changes. Signals: "looks good", "ship it", "approved", "make it so", "perfect", "yes", "let's go", "LGTM". The human must express no changes at all.

2. WITHDRAW: explicit abandonment. Signals: "cancel", "stop", "call it off", "let's not", "abandon", "never mind", "kill it".

3. CORRECT: changes scoped to the CURRENT artifact being reviewed.
   - At PLAN_ASSERT: edits to the plan ("add error handling to step 3", "remove the caching layer", "change the success metric").
   - At WORK_ASSERT: fixes to the delivered work ("fix the bug in the output", "the formatting is wrong", "add tests").
   - At INTENT_ASSERT: edits to the intent document ("add a constraint about latency", "clarify the success criteria").

4. REVISE-PLAN (WORK_ASSERT only): the PLAN was wrong, not just the execution. Signals: "the approach is wrong", "we should have used X instead of Y", "rethink the architecture", "the design doesn't work".

5. REFINE-INTENT: the OBJECTIVE or PURPOSE needs changing. This can occur at ANY assert state. Signals: "actually, let's build X instead", "the goal should be Y", "change the objective", "on second thought the problem is really Z". This is a scope-level change to WHAT we're doing, not HOW.

6. DIALOG: the human is asking a question, requesting information, or making a conditional statement that requires a response before they can decide. Signals:
   - Questions: "Have you tested it?", "What approach did you use?", "Did you consider X?"
   - Information requests: "Show me the output", "Can you explain section 2?"
   - Conditionals: "Have you tested it? If not, test it." (needs answer before the instruction applies)
   - Non-decision commentary: "Interesting", "Hmm", "I'm not sure about this"
   DIALOG vs CORRECT — CRITICAL:
   - "Test it." = correct (direct instruction, no question)
   - "Have you tested it?" = dialog (question requiring answer)
   - "Have you tested it? If not, test it." = dialog (conditional — needs answer first)
   - "Why did you use X instead of Y?" = dialog (question, even if it implies disagreement)
   - "Use Y instead of X." = correct (direct instruction)

7. MIXED SIGNALS — CRITICAL: When the human says something positive FOLLOWED BY a substantive change, the CHANGE takes priority. "This looks great, but let's change the objective to X" is refine-intent, NOT approve. Politeness is social; substance is the action. Look for "but", "however", "though", "except", "actually", "on second thought" as pivot markers.

8. MULTIPLE EDITS: If the human describes several changes, combine them into one coherent feedback text. If changes span scopes (e.g., one plan edit AND one intent change), classify at the HIGHEST scope: intent > plan > task.

9. AMBIGUITY: When genuinely ambiguous, prefer "dialog" — it is safer to ask a question than to take an irreversible action.

--- VALID ACTIONS ---
{valid_actions}

--- OUTPUT ---
Return EXACTLY one line: ACTION<TAB>FEEDBACK_TEXT
- ACTION must be one of the valid actions listed above.
- FEEDBACK_TEXT is the extracted, synthesized edit instruction. Empty for approve and withdraw. For dialog, echo back the human's question verbatim.
- No explanation. No quotes around the feedback text. Just action, tab, then text.

Examples:
approve\t
withdraw\t
correct\tChange success criteria in section 1 to measure foos/minute
refine-intent\tChange objective from implementation guide to research paper
dialog\tHave you tested it?
dialog\tWhat approach did you use for the caching layer?"""

ESCALATE_PROMPT = """You are a CfA review classifier. A human was asked a clarifying question at the {state} decision point and has responded. Determine if they are accepting the work as complete, answering the question, asking a counter-question, or withdrawing.

{dialog_history_block}
--- HUMAN RESPONSE ---
{response}

--- CLASSIFICATION RULES ---
1. COMPLETE: the human is accepting the work as done and wants to move forward without further clarification. Signals: "the work is complete", "it's done", "we're done here", "accept the work", "mark it complete", "looks good, we're done", "done", "ship it", "that's good enough", "let's move on". The human is closing out the escalation by accepting the current state of the work.

2. WITHDRAW: explicit abandonment ("cancel", "stop", "call it off", "let's not", "never mind", "kill it", "I give up").

3. DIALOG: the human is asking a counter-question about the agent's question, requesting clarification about what the agent is asking, or making a comment that doesn't directly answer. Signals: "What do you mean by X?", "Can you give me an example?", "Why do you need to know that?", "I'm not sure what you're asking".

4. CLARIFY: everything else — the human is providing an answer or clarification. This is the default.

COMPLETE vs CLARIFY — CRITICAL:
- "The work is complete." = complete (acceptance, not an answer to the agent's question)
- "We're done, mark it complete." = complete
- "Use PostgreSQL." = clarify (direct answer to the agent's question)
- "Yes, proceed." = complete (accepting the current state and moving forward)
- "Yes, use the approach I described." = clarify (answering the agent's question)

--- OUTPUT ---
Return EXACTLY one line: ACTION<TAB>FEEDBACK_TEXT
- If complete: complete<TAB>
- If withdrawing: withdraw<TAB>
- If dialog: dialog<TAB>(the human's question, verbatim)
- If clarifying: clarify<TAB>(the full human response, verbatim)

Examples:
complete\t
withdraw\t
dialog\tWhat do you mean by that?
dialog\tCan you explain why you need to know?
clarify\tWe should use PostgreSQL because the data is relational"""

FAILURE_PROMPT = """You are a CfA review classifier. A process has failed (crashed, timed out, or hit an infrastructure error). The human has been shown the failure details and is deciding what to do.

--- HUMAN RESPONSE ---
{response}

--- CLASSIFICATION RULES ---
1. RETRY: try again. Signals: "try again", "retry", "one more time", "rerun", "go again", "redo", "run it again", "yes".

2. ESCALATE: the human wants to intervene, get help, or investigate. Signals: "let me look", "I'll fix it", "help", "I need to check", "investigate", "look into it", "hold on", "pause".

3. BACKTRACK: the approach or plan needs rethinking. Signals: "rethink", "wrong approach", "the plan is wrong", "try a different way", "reconsider", "start over with a new plan".

4. WITHDRAW: give up on this task. Signals: "stop", "cancel", "give up", "abort", "done", "forget it", "never mind", "quit".

5. AMBIGUITY: When genuinely ambiguous, prefer "retry" — it is the lowest-risk default for transient failures.

--- VALID ACTIONS ---
{valid_actions}

--- OUTPUT ---
Return EXACTLY one line: ACTION<TAB>FEEDBACK_TEXT
- ACTION must be one of the valid actions listed above.
- FEEDBACK_TEXT is empty for retry and withdraw. For escalate or backtrack, include any relevant context the human provided.

Examples:
retry\t
withdraw\t
escalate\tI need to check the file permissions first
backtrack\tThe plan assumed network access but this machine is offline"""


def build_context_block(intent_summary: str, plan_summary: str) -> str:
    """Build the context block for the prompt."""
    parts = []
    if intent_summary:
        parts.append(f"Intent summary:\n{intent_summary[:MAX_SUMMARY_CHARS]}")
    if plan_summary:
        parts.append(f"Plan summary:\n{plan_summary[:MAX_SUMMARY_CHARS]}")
    return "\n\n".join(parts) if parts else "(no document context available)"


def build_dialog_history_block(dialog_history: str) -> str:
    """Build the dialog history block for the prompt."""
    if not dialog_history or not dialog_history.strip():
        return ""
    return (
        "\n--- DIALOG HISTORY (prior Q&A in this review session) ---\n"
        f"{dialog_history.strip()}\n"
    )


def build_prompt(state: str, response: str,
                 intent_summary: str = "", plan_summary: str = "",
                 dialog_history: str = "") -> str:
    """Build the classification prompt for the given state."""
    actions = STATE_ACTIONS.get(state)
    if actions is None:
        # Unknown state — treat as generic assert
        actions = ["dialog", "approve", "correct", "withdraw"]

    history_block = build_dialog_history_block(dialog_history)

    if state == "FAILURE":
        return FAILURE_PROMPT.format(
            response=response,
            valid_actions=", ".join(actions),
        )

    is_escalate = state.endswith("_ESCALATE")
    if is_escalate:
        return ESCALATE_PROMPT.format(
            state=state,
            response=response,
            dialog_history_block=history_block,
        )

    return ASSERT_PROMPT.format(
        state=state,
        response=response,
        context_block=build_context_block(intent_summary, plan_summary),
        dialog_history_block=history_block,
        valid_actions=", ".join(actions),
    )


def parse_output(raw: str, valid_actions: set) -> tuple:
    """Parse tab-separated output. Returns (action, feedback_text).

    Returns ('__fallback__', '') if parsing fails or action is invalid.
    """
    if not raw or not raw.strip():
        return ("__fallback__", "")

    line = raw.strip().split('\n')[0]  # First line only
    parts = line.split('\t', 1)
    action = parts[0].strip().lower()
    feedback = parts[1].strip() if len(parts) > 1 else ""

    if action not in valid_actions:
        return ("__fallback__", "")
    return (action, feedback)


def classify(state: str, response: str,
             intent_summary: str = "", plan_summary: str = "",
             dialog_history: str = "") -> str:
    """Classify a human review response into a CfA action."""
    if not response or not response.strip():
        return "__fallback__\t"

    valid = STATE_ACTIONS.get(state)
    if valid is None:
        valid = ["dialog", "approve", "correct", "withdraw"]
    valid_set = set(valid)

    prompt = build_prompt(state, response, intent_summary, plan_summary,
                          dialog_history)

    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "claude-haiku-4-5",
             "--output-format", "text"],
            input=prompt, capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "__fallback__\t"

    if result.returncode != 0 or not result.stdout.strip():
        return "__fallback__\t"

    action, feedback = parse_output(result.stdout, valid_set)
    return f"{action}\t{feedback}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classify CfA review response")
    parser.add_argument("--state", required=True, help="CfA state name")
    parser.add_argument("--response", required=True, help="Human's response text")
    parser.add_argument("--intent-summary", default="", help="First ~500 chars of INTENT.md")
    parser.add_argument("--plan-summary", default="", help="First ~500 chars of plan.md")
    parser.add_argument("--dialog-history", default="",
                        help="Prior Q&A turns (HUMAN:/AGENT: lines)")
    args = parser.parse_args()
    print(classify(args.state, args.response, args.intent_summary,
                   args.plan_summary, args.dialog_history))
