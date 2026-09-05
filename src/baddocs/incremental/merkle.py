"""
Merkle subtree hashing for BadDocs incremental processing (US-004).

A *leaf* is a single source file, keyed by its git **blob SHA** (the content
key from :mod:`blob_sha`). An *internal* node is a folder, and the tree's root
is the *project* node. Each internal node's hash is a pure function of its own
identity plus the (sorted) hashes of its children, so a subtree's hash captures
everything beneath it:

    internal_hash = sha256(node_id + "\\0".join(sorted("child_id:child_hash")))

Sorting the child contributions makes the hash deterministic regardless of the
order children were discovered in (filesystem walk order, dict iteration, etc.).
Folding the node's own ``node_id`` in as a salt means two folders with
byte-identical children but different names still hash differently.

The key property the rest of the engine relies on: changing one leaf changes
that leaf's hash and the hash of every ancestor up to the root, but leaves every
sibling subtree's hash untouched. That lets US-005 mark exactly the ancestor
chain of a change as stale.

Like the rest of this package we NEVER consult ``st_mtime``: a leaf is keyed on
its blob SHA (content), so the tree is stable across fresh checkouts. The tree
round-trips to/from a serializable form (:func:`to_dict`/:func:`from_dict`) and
is persisted next to RunState via :class:`MerkleStore`.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ..core.exceptions import ProcessingError

PathLike = Union[str, Path]

# Node kinds.
LEAF = 'leaf'
FOLDER = 'folder'
PROJECT = 'project'

# Sentinel ids that denote the tree root (the project node).
_ROOT_IDS = ('', '.')


@dataclass
class MerkleNode:
    """
    A node in the repo's Merkle tree.

    For a ``LEAF`` the ``node_hash`` is the file's git blob SHA and ``children``
    is empty. For a ``FOLDER`` or ``PROJECT`` node the ``node_hash`` is the
    subtree hash computed by :func:`_internal_hash` over its children.

    ``node_id`` is the repo-relative path (posix-style, ``/``-separated) of the
    file or folder; the project root uses ``"."``.
    """

    node_id: str
    kind: str
    node_hash: str
    children: List['MerkleNode'] = field(default_factory=list)


def _internal_hash(node_id: str, children: List[MerkleNode]) -> str:
    """
    Compute a folder/project node's subtree hash.

    The hash folds in the node's own id (a per-node salt) and the sorted
    ``child_id:child_hash`` pairs of its children. Sorting makes the result
    independent of child discovery order.
    """
    h = hashlib.sha256()
    h.update(node_id.encode('utf-8'))
    for part in sorted(f"{c.node_id}:{c.node_hash}" for c in children):
        h.update(b'\0')
        h.update(part.encode('utf-8'))
    return h.hexdigest()


def build_tree(leaf_shas: Dict[str, str], root_id: str = '.') -> MerkleNode:
    """
    Build a Merkle tree from a mapping of repo-relative path -> blob SHA.

    The folder hierarchy is reconstructed from the path components; each file
    becomes a ``LEAF`` keyed on its blob SHA, each intermediate directory a
    ``FOLDER`` node, and the root a ``PROJECT`` node. Children are stored in
    sorted ``node_id`` order so the serialized tree is itself deterministic (the
    hash is order-independent regardless).

    Args:
        leaf_shas: Mapping of repo-relative file path -> git blob SHA. Paths may
            use either ``os.sep`` or ``/`` separators.
        root_id: Identity of the project root node (defaults to ``"."``).

    Returns:
        The root :class:`MerkleNode` of the built tree.
    """
    # Nested-dict intermediate form: dir -> dict, file -> sha string.
    nested: Dict[str, Any] = {}
    for path, sha in leaf_shas.items():
        parts = Path(path).parts
        if not parts:  # pragma: no cover - defensive
            continue
        node = nested
        for part in parts[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):  # pragma: no cover - defensive
                raise ProcessingError(
                    f"Path conflict building Merkle tree at {part!r}"
                )
            node = child
        node[parts[-1]] = sha

    def _build(node_id: str, mapping: Dict[str, Any]) -> MerkleNode:
        is_root = node_id in _ROOT_IDS
        children: List[MerkleNode] = []
        for name in sorted(mapping):
            value = mapping[name]
            child_id = name if is_root else f"{node_id}/{name}"
            if isinstance(value, dict):
                children.append(_build(child_id, value))
            else:
                children.append(MerkleNode(child_id, LEAF, value, []))
        kind = PROJECT if is_root else FOLDER
        return MerkleNode(node_id, kind, _internal_hash(node_id, children), children)

    return _build(root_id, nested)


def to_dict(node: MerkleNode) -> Dict[str, Any]:
    """Convert a tree to a JSON-serializable nested dict."""
    return {
        'node_id': node.node_id,
        'kind': node.kind,
        'node_hash': node.node_hash,
        'children': [to_dict(c) for c in node.children],
    }


def from_dict(data: Dict[str, Any]) -> MerkleNode:
    """Reconstruct a tree from the form produced by :func:`to_dict`."""
    return MerkleNode(
        node_id=data['node_id'],
        kind=data['kind'],
        node_hash=data['node_hash'],
        children=[from_dict(c) for c in data.get('children', [])],
    )


def node_hashes(node: MerkleNode) -> Dict[str, str]:
    """Flatten a tree to a ``{node_id: node_hash}`` map over every node."""
    out: Dict[str, str] = {node.node_id: node.node_hash}
    for child in node.children:
        out.update(node_hashes(child))
    return out


def find(node: MerkleNode, node_id: str) -> Optional[MerkleNode]:
    """Return the node with ``node_id`` in the subtree, or None if absent."""
    if node.node_id == node_id:
        return node
    for child in node.children:
        hit = find(child, node_id)
        if hit is not None:
            return hit
    return None


class MerkleStore:
    """
    Persists a repo's serialized Merkle tree next to the other incremental DBs.

    The store lives under ``storage_path`` in its own ``merkle.db``, keyed by
    resolved repository root. Callers MUST only call :meth:`save_tree` after a
    generation run completes successfully, mirroring
    :class:`~baddocs.incremental.run_state.RunState`.
    """

    def __init__(self, storage_path: Path) -> None:
        """
        Args:
            storage_path: Directory holding the incremental databases (the same
                ``storage_path`` used by the change-tracking DB and RunState).
        """
        self.storage_path = Path(storage_path)
        self.db_path = self.storage_path / 'merkle.db'
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._init_database()

    def _init_database(self) -> None:
        """Initialize the Merkle-tree database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS merkle_tree (
                        repo_root TEXT PRIMARY KEY,
                        tree_json TEXT NOT NULL
                    )
                ''')
                conn.commit()
        except sqlite3.Error as e:
            raise ProcessingError(
                f"Failed to initialize Merkle database: {e}"
            ) from e

    @staticmethod
    def _repo_key(repo: PathLike) -> str:
        """Normalize a repo path to a stable, absolute key."""
        return str(Path(repo).resolve())

    def save_tree(self, repo: PathLike, tree: MerkleNode) -> None:
        """
        Persist the serialized Merkle tree for ``repo`` (REPLACE semantics).

        Call this ONLY after a generation run completes successfully.
        """
        repo_key = self._repo_key(repo)
        tree_json = json.dumps(to_dict(tree), sort_keys=True)
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    '''
                    INSERT INTO merkle_tree (repo_root, tree_json)
                    VALUES (?, ?)
                    ON CONFLICT(repo_root) DO UPDATE SET
                        tree_json = excluded.tree_json
                    ''',
                    (repo_key, tree_json),
                )
                conn.commit()
        except sqlite3.Error as e:
            raise ProcessingError(f"Failed to save Merkle tree: {e}") from e

    def get_tree(self, repo: PathLike) -> Optional[MerkleNode]:
        """Return the persisted tree for ``repo``, or None if never saved."""
        repo_key = self._repo_key(repo)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT tree_json FROM merkle_tree WHERE repo_root = ?',
                    (repo_key,),
                )
                row = cursor.fetchone()
        except sqlite3.Error as e:
            raise ProcessingError(f"Failed to read Merkle tree: {e}") from e
        if not row:
            return None
        return from_dict(json.loads(row[0]))
