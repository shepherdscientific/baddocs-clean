"""
Unit tests for Merkle subtree hashing (US-004).

Asserts the three properties the engine relies on:
  * determinism -- the same leaf SHAs (in any discovery order) yield the same
    root hash;
  * propagation -- editing one leaf changes that leaf's hash and the hash of
    every ancestor up to the root;
  * isolation -- an untouched sibling subtree's hash is unchanged;
plus serialize/persist round-trips.
"""

from baddocs.incremental.merkle import (
    FOLDER,
    LEAF,
    PROJECT,
    MerkleStore,
    build_tree,
    find,
    from_dict,
    node_hashes,
    to_dict,
)


# A small nested tree: src/a.py, src/util/b.py, docs/c.md.
BASE = {
    'src/a.py': 'sha_a',
    'src/util/b.py': 'sha_b',
    'docs/c.md': 'sha_c',
}


def test_determinism_independent_of_insertion_order():
    """Same leaf SHAs in different dict orders -> identical root hash."""
    reordered = {
        'docs/c.md': 'sha_c',
        'src/util/b.py': 'sha_b',
        'src/a.py': 'sha_a',
    }
    assert build_tree(BASE).node_hash == build_tree(reordered).node_hash


def test_root_and_node_kinds():
    """Root is a PROJECT node; folders are FOLDER; files are LEAF keyed on SHA."""
    root = build_tree(BASE)
    assert root.kind == PROJECT
    assert find(root, 'src').kind == FOLDER
    leaf = find(root, 'src/a.py')
    assert leaf.kind == LEAF
    assert leaf.node_hash == 'sha_a'
    assert leaf.children == []


def test_single_leaf_edit_propagates_to_root():
    """Editing one leaf changes its hash and every ancestor up to the root."""
    before = build_tree(BASE)
    edited = build_tree({**BASE, 'src/util/b.py': 'sha_b_v2'})

    h0, h1 = node_hashes(before), node_hashes(edited)

    # The edited leaf and its full ancestor chain change.
    for changed_id in ('src/util/b.py', 'src/util', 'src', '.'):
        assert h0[changed_id] != h1[changed_id], f"{changed_id} should change"


def test_sibling_subtree_hash_unchanged():
    """An untouched sibling subtree's hash is identical after an unrelated edit."""
    before = build_tree(BASE)
    edited = build_tree({**BASE, 'src/util/b.py': 'sha_b_v2'})

    h0, h1 = node_hashes(before), node_hashes(edited)

    # docs/ and src/a.py are unrelated to the edit under src/util/.
    for untouched_id in ('docs', 'docs/c.md', 'src/a.py'):
        assert h0[untouched_id] == h1[untouched_id], f"{untouched_id} unchanged"


def test_folder_salt_distinguishes_identical_children():
    """Two folders with byte-identical children but different names differ."""
    a = build_tree({'x/f.py': 'sha'})
    b = build_tree({'y/f.py': 'sha'})
    assert find(a, 'x').node_hash != find(b, 'y').node_hash


def test_to_from_dict_round_trip():
    """Serializing then deserializing preserves every node hash."""
    root = build_tree(BASE)
    revived = from_dict(to_dict(root))
    assert node_hashes(revived) == node_hashes(root)
    assert revived.node_hash == root.node_hash


def test_store_round_trips_across_instances(tmp_path):
    """A persisted tree reloads byte-identically from a fresh store instance."""
    root = build_tree(BASE)
    MerkleStore(tmp_path / 'store').save_tree(tmp_path / 'repo', root)

    reopened = MerkleStore(tmp_path / 'store')
    loaded = reopened.get_tree(tmp_path / 'repo')
    assert loaded is not None
    assert node_hashes(loaded) == node_hashes(root)


def test_store_returns_none_for_unknown_repo(tmp_path):
    """A never-saved repo yields None."""
    assert MerkleStore(tmp_path / 'store').get_tree(tmp_path / 'repo') is None
