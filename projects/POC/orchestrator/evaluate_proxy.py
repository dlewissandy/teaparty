#!/usr/bin/env python3
"""CLI for ACT-R Phase 1 evaluation metrics.

Usage:
    uv run python -m projects.POC.orchestrator.evaluate_proxy <db_path>
    uv run python -m projects.POC.orchestrator.evaluate_proxy <db_path> --json

Computes all four evaluation metrics and the go/no-go assessment from
a proxy_memory.db file and prints the report.
"""
import argparse
import json
import sys

from projects.POC.orchestrator.proxy_memory import open_proxy_db
from projects.POC.orchestrator.proxy_metrics import generate_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description='ACT-R Phase 1 proxy evaluation report',
    )
    parser.add_argument('db_path', help='Path to proxy_memory.db')
    parser.add_argument('--json', action='store_true', dest='as_json',
                        help='Output as JSON instead of text')
    args = parser.parse_args()

    conn = open_proxy_db(args.db_path)
    try:
        report = generate_report(conn)
    finally:
        conn.close()

    if args.as_json:
        out = {
            'action_match': {
                'rate': report['action_match'].rate,
                'eligible': report['action_match'].eligible,
                'matched': report['action_match'].matched,
            },
            'prior_calibration': {
                'rate': report['prior_calibration'].rate,
                'eligible': report['prior_calibration'].eligible,
                'agreed': report['prior_calibration'].agreed,
            },
            'surprise_calibration': {
                'rate': report['surprise_calibration'].rate,
                'surprises': report['surprise_calibration'].surprises,
                'confirmed': report['surprise_calibration'].confirmed,
            },
            'retrieval_relevance': {
                'chunks_above_threshold': len(report['retrieval_relevance'].retrievals),
                'total_candidates': report['retrieval_relevance'].total_candidates,
            },
            'go_no_go': {
                'total_eligible': report['go_no_go'].total_eligible,
                'distinct_task_types': report['go_no_go'].distinct_task_types,
                'distinct_states': report['go_no_go'].distinct_states,
                'action_match_rate': report['go_no_go'].action_match_rate,
                'sample_sufficient': report['go_no_go'].sample_sufficient,
                'coverage_met': report['go_no_go'].coverage_met,
                'verdict': report['go_no_go'].verdict,
            },
        }
        print(json.dumps(out, indent=2))
    else:
        print(report['text'])


if __name__ == '__main__':
    main()
