---
name: code-cleanup
description: Multipass code cleanup for demo readiness. Systematic passes for dead code removal, naming, comments, consistency, structure, and conceptual clarity. Never breaks tests.
argument-hint: [directory or file scope, e.g. "projects/POC/orchestrator/"]
user-invocable: true
---

# Multipass Code Cleanup

Systematic cleanup that makes the codebase look deliberate, curated, and cared for. Each pass has a single focus. Tests must pass after every pass. The question guiding every edit: "Would a hiring manager look at this code and feel that someone thoughtful wrote it?"

## Ground Rules

- **Run tests after every pass.** `uv run python -m pytest projects/POC/orchestrator/tests/ --tb=short -q`. If tests fail, fix or revert before proceeding.
- **Smallest semantic footprint.** Each edit should be the minimal change that achieves its goal. Don't restructure a file while renaming a variable.
- **Commit after each pass.** One commit per pass, message describes what the pass did and why.
- **No behavior changes.** Cleanup changes how code reads, not what it does. If a change could alter behavior, it's not cleanup — it's a refactor. Skip it.
- **When in doubt, don't touch it.** If you're unsure whether an edit improves clarity, leave it alone.

## Scope

The argument specifies the directory or file to clean. Default: `projects/POC/orchestrator/`. Each pass processes all files in scope before moving to the next pass. Don't interleave passes.

---

## Pass 1: Dead Code and Dead Weight

Remove things that serve no purpose. Every line should earn its place.

- **Unused imports.** Remove imports that nothing references. Check with grep before removing — the import may be used via reflection or string reference.
- **Dead functions and classes.** Functions/methods that are never called. Verify with grep across the entire codebase, not just the current file.
- **Commented-out code.** Code in comments is not documentation — it's clutter. If it was worth keeping, it would be uncommented. Delete it.
- **Orphaned files.** Scripts, modules, or test files that nothing imports or invokes. Verify before removing.
- **Unnecessary pass statements.** `pass` in a block that already has code.
- **Vestigial TODO/FIXME/HACK comments** that reference completed work or closed issues.

Do NOT remove: docstrings, type annotations, or code that looks unused but is accessed via string-based dispatch (e.g., `getattr`, dynamic import).

## Pass 2: Naming

Names should be self-documenting. A reader should not need a comment to understand what a variable, function, or class does.

- **Vague names.** `data`, `result`, `info`, `tmp`, `ctx` (when not a well-known pattern), `val`, `item`. Replace with what the thing actually is.
- **Misleading names.** A function called `_generate_bridge` that returns a static string. A variable called `count` that holds a ratio.
- **Inconsistent naming.** If the codebase uses `session_worktree` in some places and `worktree_path` in others for the same concept, pick one.
- **Abbreviations that save nothing.** `evt` → `event`, `msg` → `message`, `cb` → `callback` — unless the abbreviation is universal (e.g., `ctx` for context in a dataclass field is fine).

Do NOT rename: public API surfaces, CLI flags, JSON field names, or anything that would require changes outside the scope.

## Pass 3: Comments and Docstrings

Comments should explain WHY, not WHAT. The code says what; the comment says why.

- **Remove comments that restate the code.** `# increment counter` above `counter += 1`.
- **Remove stale comments.** Comments that describe behavior the code no longer has.
- **Add comments where the WHY isn't obvious.** Magic numbers, non-obvious algorithm choices, workarounds for external bugs.
- **Fix misleading docstrings.** If a docstring describes parameters that don't exist or behavior that changed, update it.
- **Remove AI-generated boilerplate.** Docstrings that just restate the function signature in prose ("This function takes X and returns Y"). If the signature is clear, the docstring adds nothing.

## Pass 4: Consistency

The codebase should read like one person wrote it.

- **Import style.** Pick one pattern and apply it everywhere. If most files use `from X import Y`, don't have one file that uses `import X` and accesses `X.Y`.
- **String formatting.** f-strings, `.format()`, or `%` — pick one (prefer f-strings) and use it everywhere.
- **Error handling patterns.** If most code uses `try/except OSError: pass`, don't have one place that uses `except Exception as e: logging.warning(e)` for the same category of error.
- **Logging patterns.** Consistent use of `_log.info()` vs `print()` vs `sys.stderr`.
- **Return patterns.** If functions return early on error, they should all return early on error. If they use else blocks, they should all use else blocks.

## Pass 5: AI Smell Removal

AI-generated code has tells. Remove them.

- **Over-documentation.** Every function doesn't need a docstring. Simple, well-named functions document themselves.
- **Defensive programming theater.** `if x is not None and isinstance(x, str) and len(x) > 0` when `if x:` suffices.
- **Unnecessary abstractions.** A helper function called once from one place. Inline it.
- **Hedge comments.** "This might need to be updated", "Consider refactoring this", "TODO: optimize" with no issue reference.
- **Over-structured error handling.** Catching and re-raising the same exception. Catching `Exception` to log and continue when the caller already handles the error.
- **Excessive type annotations on internal code.** Type annotations on local variables that are obvious from context.

## Pass 6: Structure

File and directory organization should reflect conceptual boundaries.

- **Files over 500 lines.** Consider whether the file contains multiple distinct concepts that should be separate modules. Only split if the concepts are genuinely independent.
- **Files under 30 lines.** Consider whether the file's content belongs in an adjacent module.
- **Misplaced code.** A utility function in an unrelated module. A constant defined far from where it's used.
- **Folder structure.** Do the directories reflect the conceptual architecture? Is there a directory that's become a dumping ground?

Do NOT: reorganize for the sake of reorganizing. Only move code if the current location actively confuses readers.

## Pass 7: Final Review

Read through the changed files as a whole. Ask:

- Does the code read like it was written by someone who cares?
- Is the conceptual structure visible in the file organization?
- Would a new contributor understand the architecture from the code alone?
- Are there any edits from earlier passes that, in context, made things worse?

Revert any edits that don't clearly improve the code.
