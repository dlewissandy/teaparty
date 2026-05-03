# Unknown Escalation Policy

Terminal.  Your entire output for this turn must be the JSON envelope below — nothing before it, nothing after it, no prose, no commentary.  The listener parses this exact shape to recognize the escalation as withdrawn; any other text blocks termination.

```json
{
  "status": "UNKNOWN POLICY",
  "message": "Was expecting argument to be `never`, `when_unsure` or `always`.  received `$ARGUMENTS`"
}
```