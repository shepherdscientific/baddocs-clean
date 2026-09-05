"""
Stale-set computation: the single planning pass (US-006).

Combines the two staleness layers built in the preceding stories into the exact
set of work an incremental run must do:

* **Leaves** (US-003, :mod:`leaf_staleness`): a unit doc is stale iff its
  source file's git **blob SHA** changed since the last run -- or the file is
  new (never recorded) or deleted.
* **Folder/project nodes** (US-004 :mod:`merkle` + US-005
  :mod:`subtree_staleness`): a synthesis doc is stale iff its Merkle **subtree
  hash** changed since the last run.

By the Merkle property an internal node's hash changes iff some leaf beneath it
changed, so the stale node set is *exactly* the set of ancestors of any stale or
deleted leaf -- no more, no less. An untouched leaf whose whole subtree is
untouched appears in neither set, giving the minimal correct plan.

This pass is deterministic and side-effect free with respect to run state: it
reads the persisted leaf snapshot and Merkle tree to compute the plan but never
calls the LLM, writes docs, or advances ``last_run_sha``. (Constructing the
underlying stores creates their empty SQLite files if absent, the same as any
read against them.)

As everywhere in this package we NEVER consult ``st_mtime``: leaves are keyed on
blob SHA and folders on subtree hash, both content-derived and stable across a
fresh checkout.

Note on minimality: the *node* layer is minimal only when a previous Merkle tree
was persisted by the last successful run (via :class:`MerkleStore`). With no
prior tree (first-ever run) every node is reported stale, which is correct --
there is simply nothing cached to reuse yet.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional, Set, Union

from .blob_sha import all_tracked_files, changed_paths
from .leaf_staleness import LeafStaleness
from .merkle import MerkleStore, build_tree
from .subtree_staleness import stale_node_ids

PathLike = Union[str, Path]

#: An optional predicate over repo-relative paths: return True to keep a file as
#: a doc leaf, False to ignore it (e.g. files excluded by file-discovery
#: filters). When None every tracked file is a leaf.
PathFilter = Callable[[str], bool]

__all__ = ['StaleSet', 'compute_stale_set']


@dataclass
class StaleSet:
    """
    The plan: exactly which work an incremental run must perform.

    ``stale_leaves`` are repo-relative paths of unit docs to regenerate (their
    file content changed or the file is new). ``deleted`` are repo-relative
    paths whose source file vanished -- their cached unit docs should be dropped
    rather than regenerated. ``stale_nodes`` are the ids of folder/project nodes
    to re-synthesize (the ancestor chains of every stale or deleted leaf).
    """

    stale_leaves: Set[str] = field(default_factory=set)
    stale_nodes: Set[str] = field(default_factory=set)
    deleted: Set[str] = field(default_factory=set)

    @property
    def is_empty(self) -> bool:
        """True iff there is nothing to do (no stale leaves, nodes, or deletions)."""
        return not (self.stale_leaves or self.stale_nodes or self.deleted)


def compute_stale_set(
    repo: PathLike,
    last_run_sha: Optional[str],
    storage_path: PathLike,
    path_filter: Optional[PathFilter] = None,
) -> StaleSet:
    """
    Compute the minimal set of regeneration work for an incremental run.

    Args:
        repo: Repository root.
        last_run_sha: The commit docs were last generated from, or None on a
            never-run repo. Used as a fallback recorded-SHA source for the leaf
            layer and to recover deletions from git history.
        storage_path: Directory holding the incremental databases (the same
            ``storage_path`` used by RunState, LeafStaleness, and MerkleStore).
        path_filter: Optional predicate over repo-relative paths; when given,
            only files it accepts are treated as doc leaves. Files it rejects
            (e.g. excluded by file-discovery filters) never appear as stale or
            deleted, so a push that touches only such files yields an empty plan.

    Returns:
        A :class:`StaleSet`. On a first-ever run (no persisted snapshot/tree)
        every live leaf and node is reported stale; on a subsequent run the
        result is the minimal correct plan.
    """
    storage_path = Path(storage_path)
    leaf_store = LeafStaleness(storage_path)
    merkle_store = MerkleStore(storage_path)

    # --- Leaf layer (US-003) ------------------------------------------------
    # Classify every currently-tracked file by blob-SHA staleness, and capture
    # its current blob SHA to build the fresh Merkle tree from the same numbers.
    current_paths = all_tracked_files(repo)
    if path_filter is not None:
        current_paths = {p for p in current_paths if path_filter(p)}
    current_leaf_shas: Dict[str, str] = {}
    stale_leaves: Set[str] = set()
    for path in current_paths:
        status = leaf_store.leaf_status(repo, path, last_run_sha)
        if status.current_sha is not None:
            current_leaf_shas[path] = status.current_sha
        if status.stale and not status.deleted:
            stale_leaves.add(path)

    # --- Deletions ----------------------------------------------------------
    # A leaf is deleted if it was known on the last run but is gone now. Prefer
    # the persisted per-leaf snapshot; fall back to git history when no snapshot
    # exists yet (e.g. the first incremental run after a manual full build).
    recorded = leaf_store.recorded_shas(repo)
    deleted: Set[str] = set(recorded) - current_paths
    if not recorded and last_run_sha:
        deleted |= changed_paths(repo, last_run_sha).deleted
    deleted -= current_paths
    if path_filter is not None:
        deleted = {p for p in deleted if path_filter(p)}

    # --- Folder/project layer (US-004 + US-005) -----------------------------
    # Build the fresh tree from the current leaf SHAs and diff it against the
    # tree persisted on the last successful run. By the Merkle property the
    # stale internal nodes are exactly the ancestor chains of the changed and
    # deleted leaves.
    current_tree = build_tree(current_leaf_shas)
    prev_tree = merkle_store.get_tree(repo)
    stale_nodes = stale_node_ids(current_tree, prev_tree)

    return StaleSet(
        stale_leaves=stale_leaves,
        stale_nodes=stale_nodes,
        deleted=deleted,
    )
