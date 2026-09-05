"""
Ancestor re-synthesis (US-008).

After the per-leaf unit docs are brought up to date (US-007), every folder and
project synthesis doc *above* a change must be re-synthesized so the high-level
docs stay consistent with their children. By the Merkle property the set of
nodes needing re-synthesis is exactly ``StaleSet.stale_nodes`` -- the ancestor
chains of every stale or deleted leaf -- and nothing else.

This module spends synthesis work only on those nodes:

* Re-synthesis runs **bottom-up** (deepest node first) so a parent always
  synthesizes from children that have *already* been updated this run. A stale
  folder reads its child folder docs from the synthesis cache (a deeper stale
  child has just been rewritten; an untouched child still holds its prior doc)
  and its child leaf docs from the current unit-doc map.
* Nodes **not** in ``stale_nodes`` are never re-synthesized; their cached
  synthesis from the last successful run is reused as-is.

The synthesis-doc cache is a small SQLite store (``folder_docs.db``) living next
to the other incremental databases under ``storage_path``, keyed by resolved
repo root and node id -- the same convention as
:class:`~baddocs.incremental.unit_regen.UnitDocStore`.

The LLM is never called directly here: the caller passes a ``synthesizer``
callable (node id + its children's current docs -> synthesis text). Production
wires this to the real LLM folder/project synthesizer; tests inject a
deterministic fake and assert call counts and ordering without any network.

As everywhere in this package, *what* is stale is decided by content identity
(Merkle subtree hash via the stale set), never by ``st_mtime``.
"""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional, Set, Union

from ..core.exceptions import ProcessingError
from .merkle import LEAF, MerkleNode, find

PathLike = Union[str, Path]

#: An injected LLM folder/project synthesizer: node id + the current docs of its
#: direct children (``{child_id: doc}``) -> generated synthesis text.
Synthesizer = Callable[[str, Dict[str, str]], str]

__all__ = ['FolderDocStore', 'ResynthResult', 'resynthesize_nodes']


class FolderDocStore:
    """
    Caches folder/project synthesis docs so untouched nodes skip re-synthesis.

    The store lives next to the other incremental databases under
    ``storage_path`` (its own ``folder_docs.db``), keyed by resolved repository
    root and the node id (repo-relative folder path; the project root is
    ``"."``).
    """

    def __init__(self, storage_path: Path) -> None:
        """
        Initialize the folder-doc store.

        Args:
            storage_path: Directory holding the incremental databases (the same
                ``storage_path`` used by RunState/UnitDocStore/MerkleStore).
        """
        self.storage_path = Path(storage_path)
        self.db_path = self.storage_path / 'folder_docs.db'

        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._init_database()

    def _init_database(self) -> None:
        """Initialize the folder-doc database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS folder_doc (
                        repo_root TEXT NOT NULL,
                        node_id TEXT NOT NULL,
                        doc TEXT NOT NULL,
                        PRIMARY KEY (repo_root, node_id)
                    )
                ''')
                conn.commit()
        except sqlite3.Error as e:
            raise ProcessingError(
                f"Failed to initialize folder-doc database: {e}"
            ) from e

    @staticmethod
    def _repo_key(repo: PathLike) -> str:
        """Normalize a repo path to a stable, absolute key."""
        return str(Path(repo).resolve())

    def save_doc(self, repo: PathLike, node_id: str, doc: str) -> None:
        """Insert or replace the cached synthesis doc for one node."""
        repo_key = self._repo_key(repo)
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    '''
                    INSERT INTO folder_doc (repo_root, node_id, doc)
                    VALUES (?, ?, ?)
                    ON CONFLICT(repo_root, node_id) DO UPDATE SET
                        doc = excluded.doc
                    ''',
                    (repo_key, node_id, doc),
                )
                conn.commit()
        except sqlite3.Error as e:
            raise ProcessingError(f"Failed to save folder doc: {e}") from e

    def get_doc(self, repo: PathLike, node_id: str) -> Optional[str]:
        """Return the cached synthesis doc for one node, or None if uncached."""
        repo_key = self._repo_key(repo)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT doc FROM folder_doc '
                    'WHERE repo_root = ? AND node_id = ?',
                    (repo_key, node_id),
                )
                row = cursor.fetchone()
                return row[0] if row else None
        except sqlite3.Error as e:
            raise ProcessingError(f"Failed to read folder doc: {e}") from e

    def delete_doc(self, repo: PathLike, node_id: str) -> None:
        """Drop the cached synthesis doc for one node (no-op if absent)."""
        repo_key = self._repo_key(repo)
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    'DELETE FROM folder_doc '
                    'WHERE repo_root = ? AND node_id = ?',
                    (repo_key, node_id),
                )
                conn.commit()
        except sqlite3.Error as e:
            raise ProcessingError(f"Failed to delete folder doc: {e}") from e

    def all_docs(self, repo: PathLike) -> Dict[str, str]:
        """Return the complete cached synthesis-doc map for ``repo``."""
        repo_key = self._repo_key(repo)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT node_id, doc FROM folder_doc WHERE repo_root = ?',
                    (repo_key,),
                )
                return {row[0]: row[1] for row in cursor.fetchall()}
        except sqlite3.Error as e:
            raise ProcessingError(f"Failed to read folder docs: {e}") from e


@dataclass
class ResynthResult:
    """
    The outcome of an ancestor re-synthesis pass.

    ``docs`` is the complete current synthesis-doc map (node id -> doc) after the
    run: freshly re-synthesized stale nodes merged with the reused cached docs of
    untouched nodes. ``resynthesized`` is exactly the set of node ids that cost a
    synthesis call (the stale ancestor chain), in support of test assertions.
    """

    docs: Dict[str, str] = field(default_factory=dict)
    resynthesized: Set[str] = field(default_factory=set)


def _depth(node_id: str) -> int:
    """
    Sort key putting deeper nodes first under a reverse sort.

    The project root (``"."`` / ``""``) is the shallowest so it is always
    re-synthesized last, after every descendant folder. Other nodes are ordered
    by their number of path separators.
    """
    if node_id in ('.', ''):
        return -1
    return node_id.count('/')


def resynthesize_nodes(
    repo: PathLike,
    tree: MerkleNode,
    stale_nodes: Set[str],
    unit_docs: Dict[str, str],
    synthesizer: Synthesizer,
    storage_path: PathLike,
) -> ResynthResult:
    """
    Re-synthesize every stale folder/project node bottom-up; reuse the rest.

    The ``synthesizer`` is invoked exactly once per node in ``stale_nodes``,
    deepest node first, so a parent always synthesizes from children that have
    already been updated this run. Each call receives the node id and a
    ``{child_id: doc}`` map of its direct children's current docs (leaf children
    from ``unit_docs``; folder children from the synthesis cache, where a deeper
    stale child has just been rewritten and an untouched child still holds its
    prior doc). Nodes outside ``stale_nodes`` are never re-synthesized.

    This function performs the work of the plan; it does not advance run state --
    the caller persists the leaf snapshot / Merkle tree only after the whole run
    succeeds.

    Args:
        repo: Repository root.
        tree: The current Merkle tree (from :func:`build_tree`), used to resolve
            each stale node's direct children.
        stale_nodes: The ids of folder/project nodes to re-synthesize, from
            :attr:`~baddocs.incremental.stale_set.StaleSet.stale_nodes`.
        unit_docs: The current unit-doc map (path -> doc), typically
            :attr:`~baddocs.incremental.unit_regen.RegenResult.docs`.
        synthesizer: Injected LLM folder/project synthesizer.
        storage_path: Directory holding the incremental databases.

    Returns:
        A :class:`ResynthResult` with the merged current synthesis-doc map and
        the set of re-synthesized node ids.
    """
    store = FolderDocStore(Path(storage_path))

    # Bottom-up: deepest nodes first so each parent reads already-updated
    # children. Ties (same depth) are broken by node id for determinism.
    ordered = sorted(stale_nodes, key=lambda nid: (_depth(nid), nid), reverse=True)

    resynthesized: Set[str] = set()
    for node_id in ordered:
        node = find(tree, node_id)
        if node is None:  # defensive: a planned node absent from the live tree.
            continue
        child_docs: Dict[str, str] = {}
        for child in node.children:
            if child.kind == LEAF:
                doc = unit_docs.get(child.node_id)
            else:
                doc = store.get_doc(repo, child.node_id)
            if doc is not None:
                child_docs[child.node_id] = doc
        store.save_doc(repo, node_id, synthesizer(node_id, child_docs))
        resynthesized.add(node_id)

    return ResynthResult(docs=store.all_docs(repo), resynthesized=resynthesized)
