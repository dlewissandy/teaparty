# Hook Removal Safety Checklist

## Before removing

- [ ] Confirm which hook entry is being removed (event + matcher + handler)
- [ ] If `command` type: note whether the referenced script should also be deleted or kept
- [ ] If this was the only handler in a matcher group: the entire matcher group will be removed
- [ ] If this was the only matcher group under an event: the event key will be removed

## JSON integrity

After editing, confirm the resulting JSON is valid:
```bash
python3 -m json.tool .claude/settings.json > /dev/null && echo "valid"
```

## After removal

Report: "Removed {event}/{matcher} hook. Settings file updated."
If the handler script is now orphaned: mention it so the human can decide whether to delete it.
