"""
Leaf (unit-doc) staleness via git blob-SHA diff (US-003).

A *leaf* is a single source file whose unit doc the engine generates. A leaf is
stale iff its git **blob SHA** (content hash) differs from the SHA recorded at
the last successful run -- or the file is new (never recorded) or deleted.

This reuses the content-hash idea from :mod:`hash_tracker`, but instead of
recomputing a SHA-256 over the bytes it keys on git's blob object id
(:func:`blob_sha`). For a git-tracked file that id is exactly what git already
stores, so comparison is cheap and stable across checkouts.

Like the rest of this package we NEVER consult ``st_mtime``: a fresh checkout
resets mtimes and would make every leaf look modified, defeating incremental
generation. Content identity (the blob SHA) is the only staleness signal here.

Per-leaf SHAs are persisted next to the other incremental databases so the next
run can compare against the recorded snapshot without re-reading every file. The
recorded SHA for a leaf is resolved in this order:

1. the persisted per-leaf SHA from the last run, if present;
2. else the blob SHA at the ``last_run_sha`` commit (``committed_blob_sha``),
   if a commit was supplied -- so a first incremental run can still diff against
   git history before any snapshot exists;
3. else ``None`` -- the leaf is new and therefore stale.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Union
import logging

from .blob_sha import blob_sha, committed_blob_sha
from ..core.exceptions import ProcessingError

PathLike = Union[str, Path]


@dataclass
class LeafStatus:
    """
    The staleness verdict for a single leaf.

    ``deleted`` is flagged separately so callers can drop a cached unit doc
    rather than try to regenerate one for a file that no longer exists.
    """

    path: str
    stale: bool
    deleted: bool
    current_sha: Optional[str]
    recorded_sha: Optional[str]


class LeafStaleness:
    """
    Tracks and compares per-leaf blob SHAs to decide unit-doc staleness.

    The store lives next to the change-tracking database under ``storage_path``
    (its own ``leaf_sha.db``), keyed by resolved repository root and the
    repo-relative file path. Callers MUST only call :meth:`record_leaf_shas`
    after a generation run completes successfully, mirroring
    :class:`~baddocs.incremental.run_state.RunState`.
    """

    def __init__(self, storage_path: Path) -> None:
        """
        Initialize the leaf-SHA store.

        Args:
            storage_path: Directory holding the incremental databases (the same
                ``storage_path`` used by the change-tracking DB and RunState).
        """
        self.storage_path = Path(storage_path)
        self.db_path = self.storage_path / 'leaf_sha.db'
        self.logger = logging.getLogger(__name__)

        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._init_database()

    def _init_database(self) -> None:
        """Initialize the leaf-SHA database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS leaf_sha (
                        repo_root TEXT NOT NULL,
                        path TEXT NOT NULL,
                        blob_sha TEXT NOT NULL,
                        PRIMARY KEY (repo_root, path)
                    )
                ''')
                conn.commit()
        except sqlite3.Error as e:
            raise ProcessingError(
                f"Failed to initialize leaf-SHA database: {e}"
            ) from e

    @staticmethod
    def _repo_key(repo: PathLike) -> str:
        """Normalize a repo path to a stable, absolute key."""
        return str(Path(repo).resolve())

    def _fs_path(self, repo: PathLike, path: PathLike) -> Path:
        """Resolve a (possibly repo-relative) leaf path to a filesystem path."""
        p = Path(path)
        return p if p.is_absolute() else Path(repo) / p

    def record_leaf_shas(self, repo: PathLike, shas: Dict[str, str]) -> None:
        """
        Persist the complete per-leaf SHA snapshot for ``repo``.

        Replace semantics: every prior row for the repo is cleared and the
        supplied mapping is written, so leaves absent from ``shas`` (deleted
        files) drop out of the recorded set automatically.

        Call this ONLY after a generation run completes successfully.

        Args:
            repo: Repository root (used as the key).
            shas: Mapping of repo-relative path -> blob SHA for every live leaf.
        """
        repo_key = self._repo_key(repo)
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    'DELETE FROM leaf_sha WHERE repo_root = ?', (repo_key,)
                )
                conn.executemany(
                    'INSERT INTO leaf_sha (repo_root, path, blob_sha) '
                    'VALUES (?, ?, ?)',
                    [(repo_key, path, sha) for path, sha in shas.items()],
                )
                conn.commit()
        except sqlite3.Error as e:
            raise ProcessingError(f"Failed to record leaf SHAs: {e}") from e

    def recorded_shas(self, repo: PathLike) -> Dict[str, str]:
        """Return the persisted per-leaf SHA snapshot for ``repo`` (may be empty)."""
        repo_key = self._repo_key(repo)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT path, blob_sha FROM leaf_sha WHERE repo_root = ?',
                    (repo_key,),
                )
                return {row[0]: row[1] for row in cursor.fetchall()}
        except sqlite3.Error as e:
            raise ProcessingError(f"Failed to read leaf SHAs: {e}") from e

    def get_recorded_sha(self, repo: PathLike, path: str) -> Optional[str]:
        """Return the last recorded blob SHA for one leaf, or None if unrecorded."""
        repo_key = self._repo_key(repo)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT blob_sha FROM leaf_sha '
                    'WHERE repo_root = ? AND path = ?',
                    (repo_key, path),
                )
                row = cursor.fetchone()
                return row[0] if row else None
        except sqlite3.Error as e:
            raise ProcessingError(f"Failed to read leaf SHA: {e}") from e

    def leaf_status(
        self,
        repo: PathLike,
        path: str,
        last_run_sha: Optional[str] = None,
    ) -> LeafStatus:
        """
        Compute the full staleness verdict for one leaf.

        Args:
            repo: Repository root.
            path: Repo-relative path of the leaf.
            last_run_sha: The commit docs were last generated from. Used only as
                a fallback "recorded SHA" source when no per-leaf snapshot exists.

        Returns:
            A :class:`LeafStatus`. A deleted file is always stale and flagged
            ``deleted``; a new file (no recorded SHA) is stale; an unchanged
            file is not stale.
        """
        recorded = self.get_recorded_sha(repo, path)
        if recorded is None and last_run_sha is not None:
            recorded = committed_blob_sha(repo, last_run_sha, path)

        # Deleted: the leaf was known before but no longer exists on disk.
        if not self._fs_path(repo, path).exists():
            return LeafStatus(
                path=path,
                stale=True,
                deleted=True,
                current_sha=None,
                recorded_sha=recorded,
            )

        current = blob_sha(repo, self._fs_path(repo, path))
        return LeafStatus(
            path=path,
            stale=current != recorded,
            deleted=False,
            current_sha=current,
            recorded_sha=recorded,
        )

    def leaf_is_stale(
        self,
        repo: PathLike,
        path: str,
        last_run_sha: Optional[str] = None,
    ) -> bool:
        """
        Return True iff the leaf's blob SHA differs from the recorded SHA.

        A new (unrecorded) or deleted leaf is stale. See :meth:`leaf_status`
        for the richer verdict that also flags deletions.
        """
        return self.leaf_status(repo, path, last_run_sha).stale
