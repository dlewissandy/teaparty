#!/usr/bin/env python3
"""CLI for ACT-R evaluation metrics.

Usage:
    uv run python -m teaparty.proxy.evaluate <db_path>
    uv run python -m teaparty.proxy.evaluate <db_path> --json

Computes evaluation metrics (surprise calibration, retrieval relevance)
from a proxy_memory.db file and prints the report.
"""
import argparse
import json

from teaparty.proxy.memory import open_proxy_db
from teaparty.proxy.metrics import generate_report


def _run_evaluation(conn, as_json: bool) -> None:
    report = generate_report(conn)

    if as_json:
        out = {
            'surprise_calibration': {
                'rate': report['surprise_calibration'].rate,
                'surprises': report['surprise_calibration'].surprises,
                'confirmed': report['surprise_calibration'].confirmed,
            },
            'retrieval_relevance': {
                'chunks_above_threshold': len(report['retrieval_relevance'].retrievals),
                'total_candidates': report['retrieval_relevance'].total_candidates,
            },
        }
        print(json.dumps(out, indent=2))
    else:
        print(report['text'])


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
        _run_evaluation(conn, args.as_json)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
