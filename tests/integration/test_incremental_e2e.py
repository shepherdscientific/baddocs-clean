"""
End-to-end integration test for the incremental Merkle doc engine (US-010).

This proves the *whole* incremental loop on a real temp git repo across two
commits, exercising the public driver
:func:`~baddocs.incremental.incremental_run.run_incremental` exactly as a CI
caller would -- no internals are poked.

The promise being verified:

1. Commit A: a full build generates one unit doc per leaf and synthesizes every
   folder/project node.
2. Commit B (one deep file edited): the next run regenerates *exactly one* unit
   doc, re-synthesizes *exactly that file's ancestor chain*, and leaves every
   other unit doc and every off-chain folder doc **byte-identical** to the
   commit-A output.
3. A third run with no change is a no-op with **zero** LLM calls.

The "LLM" is an injected deterministic fake (the generator reads file content so
an edit changes that leaf's doc; the synthesizer folds its children's docs), so
the test is hermetic and offline. Staleness is content-keyed (blob SHA / Merkle
subtree hash), never mtime -- a fresh checkout would reset mtimes but not blobs.
"""

import subprocess
from pathlib import Path
from typing import Dict, List

from baddocs.incremental.incremental_run import run_incremental


# A small nested source tree. Editing ``pkg/core/engine.py`` has the ancestor
# chain {'pkg/core', 'pkg', '.'} while ``pkg/api`` is an untouched sibling.
FILES = {
    'pkg/core/engine.py': 'def run():\n    return 1\n',
    'pkg/core/utils.py': 'def helper():\n    return 2\n',
    'pkg/api/handler.py': 'def handle():\n    return 3\n',
    'README.md': '# project\n',
}


class _FakeGenerator:
    """
    Deterministic fake LLM unit-doc generator that reads file content.

    Output depends only on (path, file bytes), so an unchanged file always yields
    a byte-identical doc and an edited file yields a different one. Records calls
    so the test can assert "exactly one leaf regenerated" without a network.
    """

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.calls: List[str] = []

    def __call__(self, path: str) -> str:
        self.calls.append(path)
        content = (self.repo / path).read_text()
        return f"UDOC[{path}]\n{content}"


class _FakeSynthesizer:
    """
    Deterministic fake LLM folder/project synthesizer.

    Output folds the node id and its children's docs, so it is reproducible and
    changes iff a child doc changed. Records calls (in order) so the test can
    assert the exact ancestor chain was re-synthesized bottom-up.
    """

    def __init__(self) -> None:
        self.calls: List[str] = []

    def __call__(self, node_id: str, child_docs: Dict[str, str]) -> str:
        self.calls.append(node_id)
        body = "\n".join(f"{cid}:{doc}" for cid, doc in sorted(child_docs.items()))
        return f"SYNTH[{node_id}]\n{body}"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ['git', *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _init_repo(repo: Path, files: Dict[str, str]) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, 'init')
    _git(repo, 'config', 'user.email', 'test@example.com')
    _git(repo, 'config', 'user.name', 'Test')
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', 'commit A')
    return _git(repo, 'rev-parse', 'HEAD')


def _edit_commit(repo: Path, rel: str, content: str, msg: str) -> str:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', msg)
    return _git(repo, 'rev-parse', 'HEAD')


def test_incremental_e2e_across_two_commits(tmp_path: Path) -> None:
    """Full build, one-leaf edit, then a no-op -- the whole loop end to end."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    sha_a = _init_repo(repo, FILES)

    # --- Commit A: full build ------------------------------------------------
    gen_a = _FakeGenerator(repo)
    syn_a = _FakeSynthesizer()
    run_a = run_incremental(repo, storage, gen_a, syn_a)

    assert run_a.noop is False
    assert run_a.head_sha == sha_a
    # Every leaf was generated exactly once; every folder/project node synthesized.
    assert run_a.regenerated == set(FILES)
    assert sorted(gen_a.calls) == sorted(FILES)
    assert run_a.resynthesized == {'pkg/core', 'pkg/api', 'pkg', '.'}
    # Snapshot the commit-A docs for the byte-identical comparison after edit.
    units_a = dict(run_a.unit_docs)
    folders_a = dict(run_a.folder_docs)

    # --- Commit B: edit exactly one deep file --------------------------------
    edited = 'pkg/core/engine.py'
    sha_b = _edit_commit(repo, edited, 'def run():\n    return 99\n', 'edit engine')

    gen_b = _FakeGenerator(repo)
    syn_b = _FakeSynthesizer()
    run_b = run_incremental(repo, storage, gen_b, syn_b)

    assert run_b.noop is False
    assert run_b.head_sha == sha_b
    # Exactly the edited leaf was regenerated -- one and only one LLM unit call.
    assert run_b.regenerated == {edited}
    assert gen_b.calls == [edited]
    # Exactly that leaf's ancestor chain was re-synthesized, bottom-up.
    chain = {'pkg/core', 'pkg', '.'}
    assert run_b.resynthesized == chain
    # Bottom-up order: each parent appears after its child.
    order = syn_b.calls
    assert order.index('pkg/core') < order.index('pkg') < order.index('.')
    # The untouched sibling folder was NOT re-synthesized.
    assert 'pkg/api' not in syn_b.calls

    # The edited leaf's doc actually changed...
    assert run_b.unit_docs[edited] != units_a[edited]
    # ...while every OTHER unit doc is byte-identical to commit A.
    for path in FILES:
        if path == edited:
            continue
        assert run_b.unit_docs[path] == units_a[path], path
    # Off-chain folder docs are byte-identical; on-chain ones were rewritten.
    assert run_b.folder_docs['pkg/api'] == folders_a['pkg/api']
    for node in chain:
        assert run_b.folder_docs[node] != folders_a[node], node

    # --- Third run: no change -> no-op, zero LLM calls -----------------------
    gen_c = _FakeGenerator(repo)
    syn_c = _FakeSynthesizer()
    run_c = run_incremental(repo, storage, gen_c, syn_c)

    assert run_c.noop is True
    assert run_c.head_sha == sha_b
    assert gen_c.calls == []
    assert syn_c.calls == []
    assert run_c.regenerated == set()
    assert run_c.resynthesized == set()
