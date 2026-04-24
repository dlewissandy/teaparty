#!/usr/bin/env python3
"""Per-team proxy-model path resolution.

What was here (confidence model, record/decide/generate helpers, retrospective
learning, `.proxy-interactions.jsonl` readers/writers, CLI) has been retired.
The 5-state collapse took out the ASSERT-gate model the confidence store was
built for; the learning signal now flows through ACT-R memory and flat
``proxy-patterns.md``.  The surviving surface is the path resolver the proxy
agent still uses to find per-team sidecar files.
"""
from __future__ import annotations

import os


def resolve_team_model_path(base_path: str, team: str) -> str:
    """Resolve a per-team model file path from a base path.

    resolve_team_model_path('/path/.proxy-confidence.json', 'coding')
    → '/path/.proxy-confidence-coding.json'
    """
    if not team:
        return base_path
    root, ext = os.path.splitext(base_path)
    return f"{root}-{team}{ext}"
