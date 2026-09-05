"""
Unit tests for the no-op short-circuit (US-009).

The promise: when a push changed nothing relevant, the run exits immediately as
a no-op -- zero LLM calls, no docs written -- yet still advances ``last_run_sha``
to HEAD so the next run diffs from the right base. The short-circuit fires both
when HEAD equals the last run and when the diff touches only files irrelevant to
docs (excluded by a ``path_filter``).

Spy generator/synthesizer record their call counts so we can assert "zero LLM
calls" on a no-op without any network access.
"""

import subprocess
from pathlib import Path

from baddocs.incremental.incremental_run import (
    IncrementalRunResult,
    run_incremental,
)
from baddocs.incremental.run_state import RunState


FILES = {
    'src/a.py': 'print("a")\n',
    'src/util/b.py': 'print("b")\n',
    'docs/c.md': '# c\n',
}


class _SpyGenerator:
    """A deterministic fake LLM unit-doc generator that counts its calls."""

    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, path: str) -> str:
        self.calls.append(path)
        return f"UDOC<{path}>"


class _SpySynthesizer:
    """A deterministic fake LLM synthesizer that counts its calls."""

    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, node_id: str, child_docs: dict) -> str:
        self.calls.append(node_id)
        return f"SYNTH<{node_id}>"


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


def _write_commit(repo: Path, rel: str, content: str, msg: str) -> str:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', msg)
    return _git(repo, 'rev-parse', 'HEAD')


def test_second_identical_run_is_noop_with_zero_llm_calls(tmp_path):
    """Run twice with no change: the second run is a no-op, zero LLM calls."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    _init_repo(repo, FILES)

    gen, syn = _SpyGenerator(), _SpySynthesizer()

    first = run_incremental(repo, storage, gen, syn)
    assert first.noop is False
    # First run is a full build: every leaf cost a generator call.
    assert first.regenerated == set(FILES)
    first_gen_calls = len(gen.calls)
    first_syn_calls = len(syn.calls)
    assert first_gen_calls > 0 and first_syn_calls > 0

    second = run_incremental(repo, storage, gen, syn)
    assert second.noop is True
    # No new LLM calls were made on the no-op run.
    assert len(gen.calls) == first_gen_calls
    assert len(syn.calls) == first_syn_calls
    # And nothing was reported as work.
    assert second.regenerated == set()
    assert second.resynthesized == set()
    assert second.deleted == set()


def test_noop_advances_last_run_sha(tmp_path):
    """A no-op still advances last_run_sha to HEAD for the next diff base."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    sha_a = _init_repo(repo, FILES)

    # The same path_filter is applied on every run, as a real caller would.
    py_only = lambda p: p.endswith('.py')  # noqa: E731
    gen, syn = _SpyGenerator(), _SpySynthesizer()
    run_incremental(repo, storage, gen, syn, path_filter=py_only)

    run_state = RunState(storage)
    assert run_state.get_run_sha(repo) == sha_a

    # New commit that changes only a file irrelevant to docs (.py filter).
    sha_b = _write_commit(repo, 'notes.txt', 'just notes\n', 'add notes')

    gen2, syn2 = _SpyGenerator(), _SpySynthesizer()
    result = run_incremental(
        repo, storage, gen2, syn2, path_filter=py_only
    )

    # Irrelevant change -> no-op with zero LLM calls...
    assert result.noop is True
    assert gen2.calls == []
    assert syn2.calls == []
    # ...but the base advanced to the new HEAD so the next run diffs from there.
    assert run_state.get_run_sha(repo) == sha_b
    assert result.head_sha == sha_b


def test_irrelevant_file_edit_is_noop(tmp_path):
    """Editing only an excluded file short-circuits to a no-op."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    _init_repo(repo, FILES)

    py_only = lambda p: p.endswith('.py')  # noqa: E731
    gen, syn = _SpyGenerator(), _SpySynthesizer()
    run_incremental(repo, storage, gen, syn, path_filter=py_only)

    # Edit only the excluded markdown file.
    _write_commit(repo, 'docs/c.md', '# c v2\n', 'edit docs')

    gen2, syn2 = _SpyGenerator(), _SpySynthesizer()
    result = run_incremental(repo, storage, gen2, syn2, path_filter=py_only)

    assert result.noop is True
    assert gen2.calls == []
    assert syn2.calls == []


def test_relevant_change_is_not_noop(tmp_path):
    """Sanity: editing a real source leaf makes the next run do work."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    _init_repo(repo, FILES)

    gen, syn = _SpyGenerator(), _SpySynthesizer()
    run_incremental(repo, storage, gen, syn)

    _write_commit(repo, 'src/util/b.py', 'print("b v2")\n', 'edit b')

    gen2, syn2 = _SpyGenerator(), _SpySynthesizer()
    result = run_incremental(repo, storage, gen2, syn2)

    assert result.noop is False
    # Exactly the edited leaf was regenerated...
    assert result.regenerated == {'src/util/b.py'}
    assert gen2.calls == ['src/util/b.py']
    # ...and its ancestor chain was re-synthesized.
    assert result.resynthesized == {'src/util', 'src', '.'}


def test_result_type(tmp_path):
    """run_incremental returns an IncrementalRunResult."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    _init_repo(repo, FILES)
    result = run_incremental(repo, storage, _SpyGenerator(), _SpySynthesizer())
    assert isinstance(result, IncrementalRunResult)
