"""
Unit tests for the RunState store (US-001).

Covers first-run None, save+get round-trip, and overwrite-on-newer-run.
"""

import subprocess
from pathlib import Path

import pytest

from baddocs.incremental.run_state import RunState


def _init_git_repo(path: Path) -> str:
    """Create a tiny git repo with one commit and return its HEAD SHA."""
    def git(*args: str) -> str:
        return subprocess.run(
            ['git', *args],
            cwd=str(path),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    git('init')
    git('config', 'user.email', 'test@example.com')
    git('config', 'user.name', 'Test')
    (path / 'a.txt').write_text('hello\n')
    git('add', '-A')
    git('commit', '-m', 'initial')
    return git('rev-parse', 'HEAD')


def test_first_run_returns_none(tmp_path):
    """A repo that has never been generated returns None."""
    storage = tmp_path / 'store'
    state = RunState(storage)
    repo = tmp_path / 'repo'
    repo.mkdir()
    assert state.get_run_sha(repo) is None


def test_save_get_round_trip(tmp_path):
    """save_run_sha followed by get_run_sha returns the same SHA."""
    storage = tmp_path / 'store'
    state = RunState(storage)
    repo = tmp_path / 'repo'
    repo.mkdir()

    sha = 'a' * 40
    state.save_run_sha(repo, sha)
    assert state.get_run_sha(repo) == sha


def test_overwrite_on_newer_run(tmp_path):
    """A later run overwrites the recorded SHA for the same repo."""
    storage = tmp_path / 'store'
    state = RunState(storage)
    repo = tmp_path / 'repo'
    repo.mkdir()

    first = 'a' * 40
    second = 'b' * 40
    state.save_run_sha(repo, first)
    state.save_run_sha(repo, second)
    assert state.get_run_sha(repo) == second


def test_keyed_by_repo_root(tmp_path):
    """SHAs are isolated per repo root and survive a new RunState instance."""
    storage = tmp_path / 'store'
    state = RunState(storage)
    repo_a = tmp_path / 'a'
    repo_b = tmp_path / 'b'
    repo_a.mkdir()
    repo_b.mkdir()

    state.save_run_sha(repo_a, 'a' * 40)
    state.save_run_sha(repo_b, 'b' * 40)

    # Reopen to prove persistence across instances.
    reopened = RunState(storage)
    assert reopened.get_run_sha(repo_a) == 'a' * 40
    assert reopened.get_run_sha(repo_b) == 'b' * 40


def test_get_current_sha_uses_git_head(tmp_path):
    """get_current_sha reflects git rev-parse HEAD (no mtime dependence)."""
    repo = tmp_path / 'repo'
    repo.mkdir()
    head = _init_git_repo(repo)

    state = RunState(tmp_path / 'store')
    assert state.get_current_sha(repo) == head


def test_save_empty_sha_rejected(tmp_path):
    """An empty SHA is rejected rather than silently stored."""
    state = RunState(tmp_path / 'store')
    repo = tmp_path / 'repo'
    repo.mkdir()
    with pytest.raises(Exception):
        state.save_run_sha(repo, '')
