"""
Incremental unit-doc regeneration (US-007).

The expensive part of doc generation is the per-unit (per-file) LLM call. This
module spends those calls only where they are needed: it consumes the plan from
:func:`~baddocs.incremental.stale_set.compute_stale_set` and invokes the
injected LLM unit-doc generator *only* for stale leaves. Every untouched leaf
reuses the unit doc cached from the last successful run, and every deleted leaf
has its cached doc dropped.

The unit-doc cache is a small SQLite store (``unit_docs.db``) living next to the
other incremental databases under ``storage_path``, keyed by resolved repo root
and repo-relative path -- the same convention as
:class:`~baddocs.incremental.run_state.RunState` and
:class:`~baddocs.incremental.leaf_staleness.LeafStaleness`.

The LLM is never called directly here: the caller passes a ``generator``
callable (repo-relative path -> doc text). Production wires this to the real LLM
unit-doc generator; tests inject a deterministic fake and assert call counts
without any network access.

As everywhere in this package, staleness is decided by content identity (blob
SHA / Merkle subtree hash via the stale set), never by ``st_mtime``.
"""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional, Set, Union

from ..core.exceptions import ProcessingError
from .stale_set import StaleSet

PathLike = Union[str, Path]

#: An injected LLM unit-doc generator: repo-relative path -> generated doc text.
UnitDocGenerator = Callable[[str], str]

__all__ = ['UnitDocStore', 'RegenResult', 'regenerate_units']


class UnitDocStore:
    """
    Caches generated unit (per-file) docs so untouched leaves skip the LLM.

    The store lives next to the other incremental databases under
    ``storage_path`` (its own ``unit_docs.db``), keyed by resolved repository
    root and the repo-relative file path.
    """

    def __init__(self, storage_path: Path) -> None:
        """
        Initialize the unit-doc store.

        Args:
            storage_path: Directory holding the incremental databases (the same
                ``storage_path`` used by RunState/LeafStaleness/MerkleStore).
        """
        self.storage_path = Path(storage_path)
        self.db_path = self.storage_path / 'unit_docs.db'

        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._init_database()

    def _init_database(self) -> None:
        """Initialize the unit-doc database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS unit_doc (
                        repo_root TEXT NOT NULL,
                        path TEXT NOT NULL,
                        doc TEXT NOT NULL,
                        PRIMARY KEY (repo_root, path)
                    )
                ''')
                conn.commit()
        except sqlite3.Error as e:
            raise ProcessingError(
                f"Failed to initialize unit-doc database: {e}"
            ) from e

    @staticmethod
    def _repo_key(repo: PathLike) -> str:
        """Normalize a repo path to a stable, absolute key."""
        return str(Path(repo).resolve())

    def save_doc(self, repo: PathLike, path: str, doc: str) -> None:
        """Insert or replace the cached unit doc for one leaf."""
        repo_key = self._repo_key(repo)
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    '''
                    INSERT INTO unit_doc (repo_root, path, doc)
                    VALUES (?, ?, ?)
                    ON CONFLICT(repo_root, path) DO UPDATE SET
                        doc = excluded.doc
                    ''',
                    (repo_key, path, doc),
                )
                conn.commit()
        except sqlite3.Error as e:
            raise ProcessingError(f"Failed to save unit doc: {e}") from e

    def get_doc(self, repo: PathLike, path: str) -> Optional[str]:
        """Return the cached unit doc for one leaf, or None if uncached."""
        repo_key = self._repo_key(repo)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT doc FROM unit_doc '
                    'WHERE repo_root = ? AND path = ?',
                    (repo_key, path),
                )
                row = cursor.fetchone()
                return row[0] if row else None
        except sqlite3.Error as e:
            raise ProcessingError(f"Failed to read unit doc: {e}") from e

    def delete_doc(self, repo: PathLike, path: str) -> None:
        """Drop the cached unit doc for one leaf (no-op if absent)."""
        repo_key = self._repo_key(repo)
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    'DELETE FROM unit_doc WHERE repo_root = ? AND path = ?',
                    (repo_key, path),
                )
                conn.commit()
        except sqlite3.Error as e:
            raise ProcessingError(f"Failed to delete unit doc: {e}") from e

    def all_docs(self, repo: PathLike) -> Dict[str, str]:
        """Return the complete cached unit-doc map for ``repo`` (may be empty)."""
        repo_key = self._repo_key(repo)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT path, doc FROM unit_doc WHERE repo_root = ?',
                    (repo_key,),
                )
                return {row[0]: row[1] for row in cursor.fetchall()}
        except sqlite3.Error as e:
            raise ProcessingError(f"Failed to read unit docs: {e}") from e


@dataclass
class RegenResult:
    """
    The outcome of an incremental unit-regeneration pass.

    ``docs`` is the complete current unit-doc map (path -> doc) after the run:
    freshly regenerated stale leaves merged with reused cached docs.
    ``regenerated`` / ``reused`` / ``deleted`` partition what happened, so a
    caller (and tests) can assert exactly which leaves cost an LLM call.
    """

    docs: Dict[str, str] = field(default_factory=dict)
    regenerated: Set[str] = field(default_factory=set)
    reused: Set[str] = field(default_factory=set)
    deleted: Set[str] = field(default_factory=set)


def regenerate_units(
    repo: PathLike,
    stale_set: StaleSet,
    generator: UnitDocGenerator,
    storage_path: PathLike,
) -> RegenResult:
    """
    Regenerate unit docs for stale leaves only; reuse cached docs otherwise.

    The LLM-backed ``generator`` is invoked exactly once per path in
    ``stale_set.stale_leaves`` and never for any other leaf. Cached docs for
    deleted leaves are removed from storage. The returned
    :attr:`RegenResult.docs` is the complete current unit-doc set.

    This function performs the work of the plan; it does not advance run state
    (``last_run_sha``, the leaf snapshot, or the Merkle tree) -- the caller does
    that only after the whole run, including ancestor re-synthesis, succeeds.

    Args:
        repo: Repository root.
        stale_set: The plan from :func:`compute_stale_set`.
        generator: Injected LLM unit-doc generator (path -> doc text).
        storage_path: Directory holding the incremental databases.

    Returns:
        A :class:`RegenResult` describing the regenerated, reused, and deleted
        leaves plus the merged current unit-doc map.
    """
    store = UnitDocStore(Path(storage_path))

    # Drop cached docs for files that no longer exist.
    for path in stale_set.deleted:
        store.delete_doc(repo, path)

    # Spend an LLM call only on stale leaves. Sorted for deterministic order.
    regenerated: Set[str] = set()
    for path in sorted(stale_set.stale_leaves):
        store.save_doc(repo, path, generator(path))
        regenerated.add(path)

    # The merged current set = freshly regenerated docs + untouched cached docs.
    docs = store.all_docs(repo)
    reused = set(docs) - regenerated
    return RegenResult(
        docs=docs,
        regenerated=regenerated,
        reused=reused,
        deleted=set(stale_set.deleted),
    )
