"""Experimentation harness for TeaParty ablative experiments.

Wraps the POC orchestrator (Session + EventBus) to run controlled
experiments with scripted approval providers, event collection, and
statistical analysis.

Usage:
    python -m experiments run --experiment proxy-convergence --condition dual-signal --task-id pc-001
    python -m experiments run-corpus --corpus experiments/corpus/proxy-convergence.yaml
    python -m experiments analyze --experiment proxy-convergence
    python -m experiments report --experiment proxy-convergence
"""
