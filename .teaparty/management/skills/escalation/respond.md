# Respond

Before you respond, if the message you are about to send turns on the state of any artifact (a deliverable, a plan, a config), re-read that artifact from disk — even if you read it earlier in this dialog.  The lead may have edited it in response to your feedback or the human's input.  Your reply must reflect the current state, not your memory of an earlier read.

Terminal.  Your entire output for this turn must be the JSON envelope below — nothing before it, nothing after it, no prose, no commentary.  The listener parses this exact shape to recognize the escalation as complete; any other text blocks termination.

```json
{
  "status": "RESPONSE",
  "message": "<your message to the teammate, with full context and rationale>"
}
```

Replace the `message` value with the decision you are relaying to the teammate, exactly as the workflow that led here described.
