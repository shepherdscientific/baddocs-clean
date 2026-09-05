"""Parallel unit generation matches sequential output and actually runs concurrently."""
import subprocess
import threading
import time
from pathlib import Path

from baddocs.incremental.incremental_run import run_incremental

FILES = {
    "pkg/core/engine.py": "def run():\n    return 1\n",
    "pkg/core/utils.py": "def helper():\n    return 2\n",
    "pkg/api/handler.py": "def handle():\n    return 3\n",
    "pkg/api/router.py": "def route():\n    return 4\n",
    "top.py": "def main():\n    return 0\n",
}


def _git(repo, *a):
    subprocess.run(["git", *a], cwd=str(repo), check=True, capture_output=True, text=True)


def _init(repo):
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@e.com")
    _git(repo, "config", "user.name", "T")
    for rel, c in FILES.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(c)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "A")


class _Gen:
    def __init__(self, repo):
        self.repo = repo
        self.max_concurrent = 0
        self._n = 0
        self._lock = threading.Lock()

    def __call__(self, path):
        with self._lock:
            self._n += 1
            self.max_concurrent = max(self.max_concurrent, self._n)
        time.sleep(0.15)  # simulate an LLM call so concurrency is observable
        with self._lock:
            self._n -= 1
        return f"UDOC[{path}]\n{(self.repo / path).read_text()}"


def _synth(node_id, child_docs):
    return f"SYNTH[{node_id}]\n" + "\n".join(f"{k}:{v}" for k, v in sorted(child_docs.items()))


def test_parallel_matches_sequential_and_is_concurrent(tmp_path):
    repo = tmp_path / "repo"
    _init(repo)
    filt = lambda p: p.endswith(".py")  # noqa: E731

    r_seq = run_incremental(repo, tmp_path / "seq", _Gen(repo), _synth, path_filter=filt, max_workers=1)
    g = _Gen(repo)
    r_par = run_incremental(repo, tmp_path / "par", g, _synth, path_filter=filt, max_workers=4)

    assert r_par.regenerated == r_seq.regenerated
    assert len(r_par.regenerated) == 5
    assert r_par.unit_docs == r_seq.unit_docs  # parallelism must not change output
    assert g.max_concurrent >= 2  # actually ran leaves concurrently


def test_no_change_is_still_noop_under_parallel(tmp_path):
    repo = tmp_path / "repo"
    _init(repo)
    filt = lambda p: p.endswith(".py")  # noqa: E731
    store = tmp_path / "store"
    run_incremental(repo, store, _Gen(repo), _synth, path_filter=filt, max_workers=4)
    g = _Gen(repo)
    r2 = run_incremental(repo, store, g, _synth, path_filter=filt, max_workers=4)
    assert r2.noop is True
    assert g.max_concurrent == 0  # zero LLM calls on a no-op
