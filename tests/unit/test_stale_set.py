"""
Unit tests for stale-set computation (US-006).

Builds a temp git repo with a nested source tree, simulates a completed run by
persisting the per-leaf SHA snapshot (US-003) and the Merkle tree (US-004), then
asserts that :func:`compute_stale_set` returns the minimal correct plan:

  * no changes               -> both sets empty;
  * one edited leaf          -> that leaf + exactly its ancestor chain;
  * one deleted leaf         -> deletion flagged + ancestor chain re-synthesis.
"""

import subprocess
from pathlib import Path

from baddocs.incremental.blob_sha import all_tracked_files, blob_sha
from baddocs.incremental.leaf_staleness import LeafStaleness
from baddocs.incremental.merkle import MerkleStore, build_tree
from baddocs.incremental.stale_set import compute_stale_set


# Nested tree with two independent subtrees so we can prove isolation:
#   src/a.py, src/util/b.py   (the side we edit / delete)
#   docs/c.md                 (the untouched sibling)
FILES = {
    'src/a.py': 'print("a")\n',
    'src/util/b.py': 'print("b")\n',
    'docs/c.md': '# c\n',
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ['git', *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _init_repo(repo: Path, files: dict) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, 'init')
    _git(repo, 'config', 'user.email', 'test@example.com')
    _git(repo, 'config', 'user.name', 'Test')
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', 'init')
    return _git(repo, 'rev-parse', 'HEAD')


def _record_run(repo: Path, storage: Path) -> None:
    """Persist the leaf snapshot + Merkle tree, as a successful run would."""
    shas = {p: blob_sha(repo, repo / p) for p in all_tracked_files(repo)}
    LeafStaleness(storage).record_leaf_shas(repo, shas)
    MerkleStore(storage).save_tree(repo, build_tree(shas))


def test_no_changes_both_sets_empty(tmp_path):
    """A run with nothing changed since the snapshot has no work to do."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    sha = _init_repo(repo, FILES)
    _record_run(repo, storage)

    result = compute_stale_set(repo, sha, storage)

    assert result.stale_leaves == set()
    assert result.stale_nodes == set()
    assert result.deleted == set()
    assert result.is_empty is True


def test_one_edited_leaf_marks_leaf_and_ancestor_chain(tmp_path):
    """Editing src/util/b.py marks that leaf and exactly its ancestor folders."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    sha = _init_repo(repo, FILES)
    _record_run(repo, storage)

    # Edit one deep leaf in the working tree (no new commit needed: staleness is
    # keyed on working-tree blob SHA, not commit identity).
    (repo / 'src/util/b.py').write_text('print("b v2")\n')

    result = compute_stale_set(repo, sha, storage)

    assert result.stale_leaves == {'src/util/b.py'}
    assert result.stale_nodes == {'src/util', 'src', '.'}
    assert result.deleted == set()
    # The untouched sibling subtree appears nowhere.
    assert 'docs' not in result.stale_nodes
    assert 'src/a.py' not in result.stale_leaves


def test_one_deleted_leaf_flags_deletion_and_ancestor_chain(tmp_path):
    """Deleting src/util/b.py flags the deletion and re-synthesizes its chain."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    sha = _init_repo(repo, FILES)
    _record_run(repo, storage)

    # Remove the deep leaf and stage the deletion.
    _git(repo, 'rm', 'src/util/b.py')

    result = compute_stale_set(repo, sha, storage)

    assert result.deleted == {'src/util/b.py'}
    # A deleted leaf is not something to regenerate.
    assert result.stale_leaves == set()
    # Its surviving ancestors must be re-synthesized; the sibling is untouched.
    assert 'src' in result.stale_nodes
    assert '.' in result.stale_nodes
    assert 'docs' not in result.stale_nodes


def test_added_leaf_is_stale_with_ancestors(tmp_path):
    """A brand-new file is stale and grows its ancestor chain's staleness."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    sha = _init_repo(repo, FILES)
    _record_run(repo, storage)

    new = repo / 'pkg' / 'new.py'
    new.parent.mkdir(parents=True, exist_ok=True)
    new.write_text('print("new")\n')
    _git(repo, 'add', '-A')

    result = compute_stale_set(repo, sha, storage)

    assert 'pkg/new.py' in result.stale_leaves
    assert {'pkg', '.'} <= result.stale_nodes
    assert result.deleted == set()
    # Unrelated subtrees stay clean.
    assert 'docs' not in result.stale_nodes
    assert 'src' not in result.stale_nodes
