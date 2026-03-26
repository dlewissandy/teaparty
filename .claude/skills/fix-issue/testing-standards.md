# Testing Standards

Write **specification-based tests** — tests that verify the issue's requirements, not just that your code runs. A passing test must mean the requirement is met; a thin test that passes on broken code is worse than no test.

## What makes a good test

- Test **behavior and contracts**, not implementation details. Assert on outputs, side effects, and state changes that matter to the caller.
- Cover **edge cases from the spec**: empty inputs, boundary values, error paths, the specific scenarios the issue describes.
- If the issue describes a multi-step flow, test the **full flow**, not just the final step in isolation.
- If a function should integrate with callers, test it **through the caller** — not just in unit isolation where wiring bugs are invisible.
- Each test name should read as a specification: `test_conflicting_pairs_with_same_context_different_outcome_are_detected`, not `test_classify`.

## Project conventions

`unittest.TestCase`, `_make_*()` helpers, no pytest fixtures, no `conftest.py`.
