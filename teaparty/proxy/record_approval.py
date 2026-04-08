#!/usr/bin/env python3
import argparse, json, os, sys
from datetime import datetime, timezone

def main():
    parser = argparse.ArgumentParser(description='Append an approval decision to approvals.jsonl')
    parser.add_argument('--file', required=True, help='Path to approvals.jsonl')
    parser.add_argument('--state', required=True, help='CfA state name (e.g. PLAN_ASSERT)')
    parser.add_argument('--outcome', required=True, help='Decision outcome (approve/correct/reject/withdraw/clarify)')
    parser.add_argument('--task-type', default='', help='Project/task type slug')
    parser.add_argument('--actor', default='human', help='Who decided: human or proxy')
    parser.add_argument('--diff', default='', help='Short diff summary if corrected')
    parser.add_argument('--conversation', default='', help='Conversation text (truncated to 500 chars)')
    args = parser.parse_args()
    record = {
        'ts': datetime.now(timezone.utc).isoformat(),
        'state': args.state,
        'outcome': args.outcome,
        'task_type': args.task_type,
        'actor': args.actor,
        'diff': args.diff,
        'conversation': args.conversation[:500] if args.conversation else '',
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.file)), exist_ok=True)
    with open(args.file, 'a') as f:
        f.write(json.dumps(record) + '\n')
        f.flush()
        os.fsync(f.fileno())

if __name__ == '__main__':
    main()
