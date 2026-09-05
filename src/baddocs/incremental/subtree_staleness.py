"""
Subtree-hash staleness for folder/project synthesis (US-005).

A folder or project *synthesis* doc summarizes everything beneath a node, so it
must be regenerated whenever anything in its subtree changed. The Merkle tree
from :mod:`merkle` gives us exactly that signal: an internal node's hash is a
pure function of its subtree, so a node is stale iff its current subtree hash
differs from the hash recorded on the last run.

This mirrors leaf staleness (:mod:`leaf_staleness`) one level up: leaves are
keyed on git blob SHA, internal nodes on Merkle subtree hash. As everywhere in
this package we NEVER consult ``st_mtime`` -- the subtree hash is content-derived
and therefore stable across fresh checkouts.

The previous tree is obtained from :class:`~baddocs.incremental.merkle.MerkleStore`;
the current tree is built fresh from the working tree's leaf SHAs. A node absent
from the previous tree (new folder, or first-ever run) is stale.
"""

from typing import Optional, Set

from .merkle import FOLDER, PROJECT, MerkleNode, find

__all__ = ['node_is_stale', 'stale_node_ids']


def node_is_stale(node: MerkleNode, prev_tree: Optional[MerkleNode]) -> bool:
    """
    Return True iff ``node``'s subtree changed since the last run.

    The current ``node`` (from a freshly built tree) is compared by ``node_id``
    against the persisted previous tree. It is stale when:

      * there is no previous tree at all (first-ever run), or
      * no node with the same ``node_id`` exists in the previous tree (a new
        folder/project node), or
      * the matched node's ``node_hash`` differs (its subtree changed).

    A node whose subtree is byte-identical to last run's is NOT stale. Works for
    both ``FOLDER`` nodes and the ``PROJECT`` root node (and, harmlessly, leaves
    -- though leaf staleness is the job of :mod:`leaf_staleness`).

    Args:
        node: The node from the current tree to test.
        prev_tree: The root of the previous run's tree, or None if never run.

    Returns:
        True if the node should be re-synthesized, False otherwise.
    """
    if prev_tree is None:
        return True
    prev = find(prev_tree, node.node_id)
    if prev is None:
        return True
    return node.node_hash != prev.node_hash


def stale_node_ids(
    current_tree: MerkleNode, prev_tree: Optional[MerkleNode]
) -> Set[str]:
    """
    Return the ids of every stale folder/project node in ``current_tree``.

    Walks the current tree and collects the ``node_id`` of each internal
    (``FOLDER``/``PROJECT``) node for which :func:`node_is_stale` is True. Leaf
    nodes are excluded -- those are handled by leaf staleness. This is the
    folder/project layer that US-006's stale-set computation builds on.

    Args:
        current_tree: Root of the freshly built tree.
        prev_tree: Root of the previous run's tree, or None if never run.

    Returns:
        Set of repo-relative node ids (e.g. ``"src/util"``, ``"."``) to
        re-synthesize.
    """
    stale: Set[str] = set()

    def _walk(node: MerkleNode) -> None:
        if node.kind in (FOLDER, PROJECT) and node_is_stale(node, prev_tree):
            stale.add(node.node_id)
        for child in node.children:
            _walk(child)

    _walk(current_tree)
    return stale
