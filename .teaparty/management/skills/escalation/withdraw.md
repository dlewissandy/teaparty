# Withdraw

Terminal.  Your entire output for this turn must be the JSON envelope below — nothing before it, nothing after it, no prose, no commentary.  The listener parses this exact shape to recognize the escalation as withdrawn; any other text blocks termination.

```json
{
  "status": "WITHDRAW",
  "message": "<short summary of why the work was withdrawn>"
}
```

Replace the `message` value with the reason the workflow that led here described — grounded in memory for the delegate path, grounded in the human's rationale for the escalate path, grounded in the consensus reached for the collaborate path.
