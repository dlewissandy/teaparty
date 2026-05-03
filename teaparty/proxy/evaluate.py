#!/usr/bin/env python3
"""CLI for ACT-R evaluation metrics and ablations.

Usage:
    uv run python -m teaparty.proxy.evaluate <db_path>
    uv run python -m teaparty.proxy.evaluate <db_path> --json
    uv run python -m teaparty.proxy.evaluate <db_path> --ablation embedding

Computes evaluation metrics (surprise calibration, retrieval relevance)
from a proxy_memory.db file and prints the report.  With --ablation
embedding, runs the multi-dimensional vs single-blended embedding
comparison.  Action-based metrics (action match rate, prior calibration,
go/no-go) were retired in the 583cccd8 conversational-prompts migration
and replaced by downstream classification via _classify_review.
"""
import argparse
import json
import sys

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


def _run_embedding_ablation(conn, as_json: bool) -> None:
    from teaparty.proxy.ablation import (
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
