"""Materialize a worktree as a real-file copy.

Used by the proxy launcher (#425) to give the proxy a stable, reviewable
snapshot of the caller's worktree.  The proxy walks files inside this
snapshot through Read/Glob/Grep; the worktree-jail hook constrains those
reads to the cwd subtree, and symlinks would resolve outside it via
realpath, so symlinks are not viable — every entry must be a real file
or directory.

Two cases:

  * Source is a git repository (``.git`` present).  We use ``git clone
    --no-hardlinks`` so the working tree is independent of the source
    repo and survives caller teardown.  ``--no-hardlinks`` ensures that
    even though both directories share git history, each has its own
    object copies — destroying the caller's repo cannot corrupt the
    proxy's snapshot.  ``git clone`` only checks out HEAD, so gitignored
    files (notably the canonical CfA artifacts ``INTENT.md`` / ``PLAN.md``
    / ``IDEA.md`` / ``WORK_SUMMARY.md``) are copied explicitly afterwards
    — they describe the work the proxy is being asked to review and
    would otherwise be invisible.

  * Source is a plain directory.  We use ``shutil.copytree(symlinks=False)``
    so any symlinks inside the source are followed and the destination
    contains only real files.

The destination must not exist (or must be empty).  We do not merge into
an existing tree — that would silently mix the caller's content with
unrelated state.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from teaparty.workspace.worktree import CANONICAL_ARTIFACT_NAMES


class MaterializationError(RuntimeError):
    """Raised when the destination is invalid or the copy fails."""


def materialize_worktree(src: str, dest: str) -> None:
    """Copy every file in ``src`` to ``dest`` as real files.

    ``src`` must be a directory.  ``dest`` must either not exist or be
    empty — we refuse to merge into a non-empty target.

    For git worktrees, this uses ``git clone --no-hardlinks`` so the
    snapshot is independent of the source.  For plain directories, it
    uses ``shutil.copytree`` with ``symlinks=False`` so symlinks are
    resolved into real files.
    """
    if not os.path.isdir(src):
        raise MaterializationError(
            f'source {src!r} is not a directory',
        )

    if os.path.exists(dest):
        if not os.path.isdir(dest):
            raise MaterializationError(
                f'destination {dest!r} exists and is not a directory',
            )
        if os.listdir(dest):
            raise MaterializationError(
                f'destination {dest!r} is not empty; refusing to merge '
                f'into an existing tree',
            )
        # Empty existing dir: remove it so copytree can create it.
        os.rmdir(dest)

    os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)

    if os.path.isdir(os.path.join(src, '.git')):
        _git_clone(src, dest)
        _copy_canonical_artifacts(src, dest)
    else:
        shutil.copytree(src, dest, symlinks=False)


def _copy_canonical_artifacts(src: str, dest: str) -> None:
    """Copy gitignored CfA artifacts that ``git clone`` skipped.

    ``INTENT.md`` / ``PLAN.md`` / ``IDEA.md`` / ``WORK_SUMMARY.md`` live
    at the worktree root and are gitignored so they never reach main —
    but they describe the work the proxy is being asked to review.
    Without this step the proxy's snapshot is missing the very files
    it needs to read.  Mirrors ``create_subchat_worktree`` in
    ``workspace.worktree``, which has the same problem class.
    """
    for name in CANONICAL_ARTIFACT_NAMES:
        s = os.path.join(src, name)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(dest, name))


def _git_clone(src: str, dest: str) -> None:
    """``git clone --no-hardlinks`` ``src`` into ``dest``.

    ``--no-hardlinks`` keeps the snapshot independent: destroying the
    source repo cannot corrupt the destination.  ``--quiet`` suppresses
    progress output (we don't surface clone progress to the proxy).
    """
    try:
        subprocess.run(
            [
                'git', 'clone', '--no-hardlinks', '--quiet',
                src, dest,
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        raise MaterializationError(
            f'git clone {src} -> {dest} failed: '
            f'{exc.stderr.decode("utf-8", errors="replace")}',
        ) from exc
