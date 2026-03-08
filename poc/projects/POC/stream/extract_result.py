#!/usr/bin/env python3
"""Extract the final result from claude stream-json output.

Usage: echo "<stream-json-lines>" | python3 stream/extract_result.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stream._common import parse_events

result = ""
last_assistant = ""

for ev in parse_events():
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
