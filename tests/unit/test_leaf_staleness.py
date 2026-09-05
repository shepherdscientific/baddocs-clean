"""
Unit tests for leaf staleness via blob-SHA diff (US-003).

Builds a temp git repo, records a per-leaf SHA snapshot, then asserts:
  * an unchanged file is not stale;
  * an edited file is stale;
  * a new (unrecorded) file is stale;
  * a deleted file is stale and flagged deleted.
"""

import subprocess
from pathlib import Path

from baddocs.incremental.blob_sha import blob_sha
from baddocs.incremental.leaf_staleness import LeafStaleness


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ['git', *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, 'init')
    _git(repo, 'config', 'user.email', 'test@example.com')
    _git(repo, 'config', 'user.name', 'Test')


def _snapshot(repo: Path, *paths: str) -> dict:
    """Current blob SHAs for the given repo-relative paths."""
    return {p: blob_sha(repo, repo / p) for p in paths}


def test_unchanged_file_not_stale(tmp_path):
    """A leaf whose content is byte-identical to the snapshot is not stale."""
    repo = tmp_path / 'repo'
    _init_repo(repo)
    (repo / 'a.txt').write_text('alpha\n')
    (repo / 'b.txt').write_text('beta\n')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', 'init')

    leaf = LeafStaleness(tmp_path / 'store')
    leaf.record_leaf_shas(repo, _snapshot(repo, 'a.txt', 'b.txt'))

    assert leaf.leaf_is_stale(repo, 'a.txt') is False
    status = leaf.leaf_status(repo, 'a.txt')
    assert status.stale is False and status.deleted is False


def test_edited_file_is_stale(tmp_path):
    """Editing a leaf's content makes it stale vs the recorded snapshot."""
    repo = tmp_path / 'repo'
    _init_repo(repo)
    (repo / 'a.txt').write_text('alpha\n')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', 'init')

    leaf = LeafStaleness(tmp_path / 'store')
    leaf.record_leaf_shas(repo, _snapshot(repo, 'a.txt'))

    (repo / 'a.txt').write_text('alpha changed\n')

    assert leaf.leaf_is_stale(repo, 'a.txt') is True


def test_new_file_is_stale(tmp_path):
    """A leaf with no recorded SHA (never seen) is stale."""
    repo = tmp_path / 'repo'
    _init_repo(repo)
    (repo / 'a.txt').write_text('alpha\n')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', 'init')

    leaf = LeafStaleness(tmp_path / 'store')
    leaf.record_leaf_shas(repo, _snapshot(repo, 'a.txt'))

    # b.txt was never recorded.
    (repo / 'b.txt').write_text('beta\n')

    assert leaf.leaf_is_stale(repo, 'b.txt') is True
    assert leaf.leaf_status(repo, 'b.txt').recorded_sha is None


def test_deleted_file_is_stale_and_flagged(tmp_path):
    """A recorded leaf removed from disk is stale and flagged deleted."""
    repo = tmp_path / 'repo'
    _init_repo(repo)
    (repo / 'a.txt').write_text('alpha\n')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', 'init')

    leaf = LeafStaleness(tmp_path / 'store')
    leaf.record_leaf_shas(repo, _snapshot(repo, 'a.txt'))

    (repo / 'a.txt').unlink()

    status = leaf.leaf_status(repo, 'a.txt')
    assert status.stale is True
    assert status.deleted is True
    assert status.current_sha is None


def test_fallback_to_commit_sha_without_snapshot(tmp_path):
    """Without a per-leaf snapshot, staleness falls back to the commit blob SHA."""
    repo = tmp_path / 'repo'
    _init_repo(repo)
    (repo / 'a.txt').write_text('alpha\n')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', 'init')
    head = _git(repo, 'rev-parse', 'HEAD')

    leaf = LeafStaleness(tmp_path / 'store')
    # No record_leaf_shas call: rely on the last_run_sha fallback.
    assert leaf.leaf_is_stale(repo, 'a.txt', last_run_sha=head) is False

    (repo / 'a.txt').write_text('edited\n')
    assert leaf.leaf_is_stale(repo, 'a.txt', last_run_sha=head) is True


def test_snapshot_round_trips_across_instances(tmp_path):
    """Recorded SHAs persist and are readable from a fresh store instance."""
    repo = tmp_path / 'repo'
    _init_repo(repo)
    (repo / 'a.txt').write_text('alpha\n')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', 'init')

    snap = _snapshot(repo, 'a.txt')
    LeafStaleness(tmp_path / 'store').record_leaf_shas(repo, snap)

    reopened = LeafStaleness(tmp_path / 'store')
    assert reopened.recorded_shas(repo) == snap
    assert reopened.get_recorded_sha(repo, 'a.txt') == snap['a.txt']
