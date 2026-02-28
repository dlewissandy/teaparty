#!/usr/bin/env python3
"""Extract the final result from claude stream-json output.

Usage: echo "<stream-json-lines>" | python3 extract_result.py
"""
import json
import sys

result = ""
last_assistant = ""

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        continue

    ev_type = ev.get("type", "")

    if ev_type == "result":
        result = ev.get("result", "") or ev.get("subResult", "")

    elif ev_type == "assistant":
        content = ev.get("message", {}).get("content", [])
        texts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        if texts:
            last_assistant = "\n".join(texts)

output = result or last_assistant or "(no output)"
print(output[:3000])
