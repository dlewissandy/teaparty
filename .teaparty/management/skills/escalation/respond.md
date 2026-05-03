# Respond

Terminal.  Your entire output for this turn must be the JSON envelope below — nothing before it, nothing after it, no prose, no commentary.  The listener parses this exact shape to recognize the escalation as complete; any other text blocks termination.

```json
{
  "status": "RESPONSE",
  "message": "<your message to the teammate, with full context and rationale>"
}
```

Replace the `message` value with the decision you are relaying to the teammate, exactly as the workflow that led here described.
