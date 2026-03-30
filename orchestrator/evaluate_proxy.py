#!/usr/bin/env python3
"""CLI for ACT-R Phase 1 evaluation metrics and ablations.

Usage:
    uv run python -m orchestrator.evaluate_proxy <db_path>
    uv run python -m orchestrator.evaluate_proxy <db_path> --json
    uv run python -m orchestrator.evaluate_proxy <db_path> --ablation embedding

Computes all four evaluation metrics and the go/no-go assessment from
a proxy_memory.db file and prints the report.  With --ablation embedding,
runs the multi-dimensional vs single-blended embedding comparison.
"""
import argparse
import json
import sys

from orchestrator.proxy_memory import open_proxy_db
from orchestrator.proxy_metrics import generate_report


def _run_evaluation(conn, as_json: bool) -> None:
    report = generate_report(conn)

    if as_json:
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


def _run_embedding_ablation(conn, as_json: bool) -> None:
    from orchestrator.proxy_ablation import (
        generate_ablation_report,
        populate_blended_embeddings,
        run_embedding_ablation,
    )

    # Ensure all chunks have blended embeddings before comparison
    populated = populate_blended_embeddings(conn)
    if populated:
        print(f'Populated blended embeddings for {populated} chunks', file=sys.stderr)

    result = run_embedding_ablation(conn)

    if as_json:
        out = {
            'overall_retrieval_overlap': result.overall_retrieval_overlap,
            'threshold_met': result.threshold_met,
            'recommendation': result.recommendation,
            'per_context': [
                {
                    'state': ctx.state,
                    'task_type': ctx.task_type,
                    'n_interactions': ctx.n_interactions,
                    'mean_overlap': ctx.mean_overlap,
                    'divergent_chunks': ctx.divergent_chunks,
                }
                for ctx in result.per_context
            ],
        }
        print(json.dumps(out, indent=2))
    else:
        print(generate_ablation_report(result))


def main() -> None:
    parser = argparse.ArgumentParser(
        description='ACT-R Phase 1 proxy evaluation report',
    )
    parser.add_argument('db_path', help='Path to proxy_memory.db')
    parser.add_argument('--json', action='store_true', dest='as_json',
                        help='Output as JSON instead of text')
    parser.add_argument('--ablation', choices=['embedding'],
                        help='Run an ablation instead of the standard report')
    args = parser.parse_args()

    conn = open_proxy_db(args.db_path)
    try:
        if args.ablation == 'embedding':
            _run_embedding_ablation(conn, args.as_json)
        else:
            _run_evaluation(conn, args.as_json)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
