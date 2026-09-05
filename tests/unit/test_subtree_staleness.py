"""
Unit tests for subtree-hash staleness (US-005).

Asserts the core property: after editing one deep leaf, exactly the chain of
ancestor folders (plus the project root) is stale and every unrelated folder is
not. Also covers the new-node and first-run cases.
"""

from baddocs.incremental.merkle import build_tree, find
from baddocs.incremental.subtree_staleness import node_is_stale, stale_node_ids


# A nested tree with two independent subtrees so we can prove isolation:
#   src/a.py, src/util/b.py   (the side we edit)
#   docs/c.md                 (the untouched sibling)
BASE = {
    'src/a.py': 'sha_a',
    'src/util/b.py': 'sha_b',
    'docs/c.md': 'sha_c',
}


def test_first_run_everything_stale():
    """With no previous tree, every node (root included) is stale."""
    root = build_tree(BASE)
    assert node_is_stale(root, None) is True
    assert node_is_stale(find(root, 'src/util'), None) is True


def test_unchanged_subtree_not_stale():
    """Rebuilding the identical tree marks no internal node stale."""
    prev = build_tree(BASE)
    current = build_tree(BASE)
    assert node_is_stale(current, prev) is False
    assert stale_node_ids(current, prev) == set()


def test_deep_leaf_edit_marks_exactly_the_ancestor_chain():
    """Editing src/util/b.py marks src/util, src and the root stale -- no others."""
    prev = build_tree(BASE)
    current = build_tree({**BASE, 'src/util/b.py': 'sha_b_v2'})

    # The edited leaf's ancestor chain of folder/project nodes.
    assert stale_node_ids(current, prev) == {'src/util', 'src', '.'}

    # Spot-check via node_is_stale directly: ancestors stale, sibling not.
    assert node_is_stale(find(current, 'src/util'), prev) is True
    assert node_is_stale(find(current, 'src'), prev) is True
    assert node_is_stale(current, prev) is True
    assert node_is_stale(find(current, 'docs'), prev) is False


def test_new_folder_is_stale():
    """A folder absent from the previous tree is stale."""
    prev = build_tree(BASE)
    current = build_tree({**BASE, 'pkg/new/d.py': 'sha_d'})

    stale = stale_node_ids(current, prev)
    # The brand-new folders and the root (its subtree grew) are stale.
    assert 'pkg' in stale
    assert 'pkg/new' in stale
    assert '.' in stale
    # The unrelated docs/ subtree is untouched.
    assert 'docs' not in stale
    assert node_is_stale(find(current, 'pkg/new'), prev) is True
