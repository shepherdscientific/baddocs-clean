"""
Git blob-SHA helpers for BadDocs incremental processing (US-002).

Each file is keyed by its git **blob SHA** (a content hash), so staleness
reflects file *content* rather than checkout time.

We deliberately NEVER read ``st_mtime`` anywhere in this module. A fresh git
checkout (for example, a CI runner doing ``actions/checkout``) resets every
file's mtime to the checkout time, which would make the whole tree look
"modified" and defeat incremental generation. Git's blob object id, by
contrast, is a pure function of the content -- ``sha1("blob <len>\\0" + bytes)``
-- so it is stable across checkouts and is the correct content key for a leaf.
"""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Set, Optional, Union

from ..core.exceptions import ProcessingError

PathLike = Union[str, Path]


@dataclass
class ChangedPaths:
    """
    Result of diffing two commits.

    ``changed`` holds files that were added or modified (they exist at the head
    commit). ``deleted`` holds files removed since the base commit. Deletions
    are flagged separately so callers can drop their cached docs rather than try
    to regenerate them.
    """

    changed: Set[str] = field(default_factory=set)
    deleted: Set[str] = field(default_factory=set)

    @property
    def all(self) -> Set[str]:
        """Every path touched between base and head (changed plus deleted)."""
        return self.changed | self.deleted


def _git(repo: PathLike, args: List[str]) -> str:
    """Run a git command in ``repo`` and return stripped stdout."""
    try:
        result = subprocess.run(
            ['git', *args],
            cwd=str(Path(repo)),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise ProcessingError(
            f"Git command failed: git {' '.join(args)}: {e.stderr}"
        ) from e
    except Exception as e:  # pragma: no cover - defensive
        raise ProcessingError(f"Failed to run git command: {e}") from e


def _git_ok(repo: PathLike, args: List[str]) -> bool:
    """Run a git command, returning True iff it exits zero (no output needed)."""
    try:
        result = subprocess.run(
            ['git', *args],
            cwd=str(Path(repo)),
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:  # pragma: no cover - defensive
        return False


def blob_sha(repo: PathLike, path: PathLike) -> str:
    """
    Return the git blob SHA of a file's current working-tree content.

    Uses ``git hash-object`` on the bytes on disk. This yields exactly the
    object id git would store for that content, so for a tracked-and-clean file
    it equals the committed blob SHA, while for an untracked or dirty file it
    reflects the working-tree content. One code path therefore covers tracked,
    untracked, and dirty files uniformly -- and none of them consult mtime.

    Args:
        repo: Repository root.
        path: File path (absolute, or relative to ``repo``).

    Returns:
        The 40-char (or longer, for SHA-256 repos) blob object id.
    """
    return _git(repo, ['hash-object', '--', str(path)])


def committed_blob_sha(repo: PathLike, ref: str, path: PathLike) -> Optional[str]:
    """
    Return the blob SHA recorded for ``path`` at commit ``ref``.

    This reads the blob id straight out of the commit's tree via
    ``git rev-parse <ref>:<path>`` (equivalent to ``git ls-files -s`` for the
    index). Returns None when the path does not exist at that commit.

    Args:
        repo: Repository root.
        ref: Commit-ish to read from (e.g. a SHA or ``HEAD``).
        path: File path relative to the repository root.

    Returns:
        The blob object id at ``ref``, or None if the path is absent there.
    """
    try:
        return _git(repo, ['rev-parse', f'{ref}:{path}'])
    except ProcessingError:
        return None


def all_tracked_files(repo: PathLike) -> Set[str]:
    """Return every git-tracked path in ``repo`` (relative to its root)."""
    output = _git(repo, ['ls-files'])
    return {line for line in output.splitlines() if line}


def changed_paths(
    repo: PathLike,
    base_sha: Optional[str],
    head_sha: str = 'HEAD',
) -> ChangedPaths:
    """
    Return the files added/modified/deleted between two commits.

    Computed from ``git diff --name-status base head``: status ``A``/``M`` (and
    the new name of a rename) land in ``changed``; status ``D`` lands in
    ``deleted``.

    Falls back to treating the *entire* tracked file set as ``changed`` (a full
    rebuild) when ``base_sha`` is None (never run before) or when it is not an
    ancestor of ``head_sha`` (e.g. a force-push or rebase rewrote history, so a
    diff against it is meaningless).

    Args:
        repo: Repository root.
        base_sha: The commit docs were last generated from, or None.
        head_sha: The commit to diff up to (defaults to ``HEAD``).

    Returns:
        A :class:`ChangedPaths` describing the work.
    """
    # Full-rebuild fallback: no prior run, or base is not reachable from head.
    if not base_sha or not _git_ok(
        repo, ['merge-base', '--is-ancestor', base_sha, head_sha]
    ):
        return ChangedPaths(changed=all_tracked_files(repo), deleted=set())

    output = _git(repo, ['diff', '--name-status', base_sha, head_sha])

    result = ChangedPaths()
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split('\t')
        status = parts[0]
        code = status[0]
        if code == 'D':
            result.deleted.add(parts[1])
        elif code == 'R':
            # Rename: parts = [Rxxx, old, new]. The new name is the live file;
            # the old name vanished, so flag it as deleted.
            if len(parts) >= 3:
                result.deleted.add(parts[1])
                result.changed.add(parts[2])
            else:  # pragma: no cover - defensive
                result.changed.add(parts[-1])
        else:  # A, M, C, T, etc. -- the path exists at head.
            result.changed.add(parts[-1])

    return result
