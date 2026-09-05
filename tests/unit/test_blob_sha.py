"""
Unit tests for git blob-SHA helpers (US-002).

Builds a temp git repo and asserts:
  * blob_sha matches ``git hash-object``;
  * mutating a file changes its blob SHA while an untouched sibling's is stable;
  * changed_paths reports added/modified/deleted correctly and falls back to a
    full file set when the base SHA is missing or not an ancestor of HEAD.
"""

import subprocess
from pathlib import Path

from baddocs.incremental.blob_sha import (
    ChangedPaths,
    blob_sha,
    changed_paths,
    committed_blob_sha,
)


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


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', message)
    return _git(repo, 'rev-parse', 'HEAD')


def test_blob_sha_matches_git_hash_object(tmp_path):
    """blob_sha equals git's own hash-object output for the same content."""
    repo = tmp_path / 'repo'
    _init_repo(repo)
    (repo / 'a.txt').write_text('hello\n')
    _commit_all(repo, 'add a')

    expected = _git(repo, 'hash-object', 'a.txt')
    assert blob_sha(repo, repo / 'a.txt') == expected


def test_blob_sha_changes_on_edit_sibling_stable(tmp_path):
    """Editing one file changes its SHA; an untouched sibling's is unchanged."""
    repo = tmp_path / 'repo'
    _init_repo(repo)
    (repo / 'a.txt').write_text('alpha\n')
    (repo / 'b.txt').write_text('beta\n')
    _commit_all(repo, 'add a and b')

    a_before = blob_sha(repo, repo / 'a.txt')
    b_before = blob_sha(repo, repo / 'b.txt')

    (repo / 'a.txt').write_text('alpha changed\n')

    a_after = blob_sha(repo, repo / 'a.txt')
    b_after = blob_sha(repo, repo / 'b.txt')

    assert a_after != a_before
    assert b_after == b_before


def test_blob_sha_untracked_file(tmp_path):
    """An untracked working-tree file still gets a content-derived blob SHA."""
    repo = tmp_path / 'repo'
    _init_repo(repo)
    (repo / 'committed.txt').write_text('x\n')
    _commit_all(repo, 'init')

    (repo / 'new.txt').write_text('brand new\n')
    expected = _git(repo, 'hash-object', 'new.txt')
    assert blob_sha(repo, repo / 'new.txt') == expected


def test_committed_blob_sha_reads_tree(tmp_path):
    """committed_blob_sha reads the blob recorded at a commit, None if absent."""
    repo = tmp_path / 'repo'
    _init_repo(repo)
    (repo / 'a.txt').write_text('first\n')
    sha = _commit_all(repo, 'first')

    recorded = committed_blob_sha(repo, sha, 'a.txt')
    assert recorded == _git(repo, 'rev-parse', f'{sha}:a.txt')
    assert committed_blob_sha(repo, sha, 'missing.txt') is None


def test_changed_paths_add_modify_delete(tmp_path):
    """changed_paths reports added/modified in .changed and deleted in .deleted."""
    repo = tmp_path / 'repo'
    _init_repo(repo)
    (repo / 'keep.txt').write_text('keep\n')
    (repo / 'gone.txt').write_text('gone\n')
    (repo / 'edit.txt').write_text('v1\n')
    base = _commit_all(repo, 'base')

    (repo / 'edit.txt').write_text('v2\n')      # modified
    (repo / 'gone.txt').unlink()                # deleted
    (repo / 'added.txt').write_text('new\n')    # added
    head = _commit_all(repo, 'head')

    result = changed_paths(repo, base, head)
    assert isinstance(result, ChangedPaths)
    assert 'edit.txt' in result.changed
    assert 'added.txt' in result.changed
    assert 'gone.txt' in result.deleted
    assert 'keep.txt' not in result.all
    assert result.all == {'edit.txt', 'added.txt', 'gone.txt'}


def test_changed_paths_none_base_returns_full_set(tmp_path):
    """A None base SHA triggers the full-rebuild fallback (all tracked files)."""
    repo = tmp_path / 'repo'
    _init_repo(repo)
    (repo / 'a.txt').write_text('a\n')
    (repo / 'b.txt').write_text('b\n')
    _commit_all(repo, 'init')

    result = changed_paths(repo, None, 'HEAD')
    assert result.changed == {'a.txt', 'b.txt'}
    assert result.deleted == set()


def test_changed_paths_non_ancestor_returns_full_set(tmp_path):
    """A base that is not an ancestor of HEAD falls back to a full rebuild."""
    repo = tmp_path / 'repo'
    _init_repo(repo)
    (repo / 'a.txt').write_text('a\n')
    _commit_all(repo, 'init')

    # A fabricated SHA that is not in history -> not an ancestor.
    bogus = '0' * 40
    result = changed_paths(repo, bogus, 'HEAD')
    assert result.changed == {'a.txt'}
    assert result.deleted == set()
