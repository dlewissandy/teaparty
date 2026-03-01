#!/usr/bin/env python3
"""One-shot retroactive extraction from all intent streams in .sessions/.

Run this once to populate OBSERVATIONS.md and ESCALATION.md from existing
intent streams. Safe to re-run — appends only; does not deduplicate.

Usage:
    python3 retroactive_extract.py --sessions-dir <path> --project-dir <path>
"""
import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

# Import from sibling module
sys.path.insert(0, str(Path(__file__).parent))
from summarize_session import extract_human_turns, summarize


def main():
    parser = argparse.ArgumentParser(description="Retroactive intent extraction")
    parser.add_argument("--sessions-dir", required=True, help="Path to .sessions/ directory")
    parser.add_argument("--project-dir", required=True, help="Path to project directory (for OBSERVATIONS.md etc.)")
    args = parser.parse_args()

    sessions_dir = Path(args.sessions_dir)
    project_dir = Path(args.project_dir)
    observations_path = project_dir / "OBSERVATIONS.md"
    escalation_path = project_dir / "ESCALATION.md"

    # Find all intent streams, sorted chronologically
    streams = sorted(sessions_dir.glob("*/.intent-stream.jsonl"))
    if not streams:
        print(f"[retroactive] No .intent-stream.jsonl files found in {sessions_dir}", file=sys.stderr)
        return 0

    print(f"[retroactive] Found {len(streams)} intent streams", file=sys.stderr)

    for stream in streams:
        session_ts = stream.parent.name
        print(f"\n[retroactive] === {session_ts} ===", file=sys.stderr)

        # Check if stream has human turns worth extracting
        human_text = extract_human_turns(str(stream))
        if not human_text.strip():
            print(f"[retroactive] No human turns found, skipping", file=sys.stderr)
            continue

        print(f"[retroactive] Found human turns ({len(human_text)} chars), extracting...", file=sys.stderr)

        # Extract observations
        rc = summarize(str(stream), str(observations_path), [], "observations")
        if rc == 0:
            print(f"[retroactive] Observations done", file=sys.stderr)
        else:
            print(f"[retroactive] Observations extraction failed (rc={rc})", file=sys.stderr)

        # Extract escalation calibrations
        rc = summarize(str(stream), str(escalation_path), [], "escalation")
        if rc == 0:
            print(f"[retroactive] Escalation done", file=sys.stderr)
        else:
            print(f"[retroactive] Escalation extraction failed (rc={rc})", file=sys.stderr)

    print(f"\n[retroactive] Done. Check {observations_path} and {escalation_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
