"""
Unit tests for the per-run cost ceiling (US-013).

The promise: a CI run can never blow the LLM budget. A :class:`CostBudget`
accumulates spend across both work phases of a run and is checked *before* every
LLM call; the call that would push past the ceiling is refused, so the run stops
before it and the accumulated cost never exceeds the ceiling. The driver keeps
whatever docs completed (they are persisted as produced) but does NOT advance
``last_run_sha``, so the unfinished work is retried next run.

A priced fake LLM (a fixed per-call cost on the budget) lets us assert the run
halts at exactly the ceiling without any network access.
"""

import subprocess
from pathlib import Path

import pytest

from baddocs.incremental.cost_ceiling import (
    DEFAULT_MAX_COST_USD,
    BudgetExceededError,
    CostBudget,
    budgeted,
)
from baddocs.incremental.incremental_run import run_incremental
from baddocs.incremental.run_state import RunState
from baddocs.incremental.unit_regen import UnitDocStore


FILES = {
    'src/a.py': 'print("a")\n',
    'src/util/b.py': 'print("b")\n',
    'src/util/c.py': 'print("c")\n',
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


# --- CostBudget: charge-before-spend, never exceeds --------------------------

def test_charge_advances_spend_within_ceiling():
    """Charges that stay within the ceiling advance ``spent``."""
    budget = CostBudget(max_cost_usd=1.0, cost_per_call=0.25)
    budget.charge()
    budget.charge()
    assert budget.spent == pytest.approx(0.50)
    assert budget.remaining() == pytest.approx(0.50)


def test_charge_refuses_call_that_would_exceed():
    """The charge that would breach the ceiling raises and leaves spend intact."""
    budget = CostBudget(max_cost_usd=0.25, cost_per_call=0.10)
    budget.charge()  # 0.10
    budget.charge()  # 0.20
    with pytest.raises(BudgetExceededError) as exc:
        budget.charge()  # would be 0.30 > 0.25 -> refused
    # Spend is unchanged by the refused charge, so it never exceeds the ceiling.
    assert budget.spent == pytest.approx(0.20)
    assert budget.spent <= budget.max_cost_usd
    assert exc.value.ceiling == pytest.approx(0.25)
    assert exc.value.next_call == pytest.approx(0.10)


def test_budgeted_wrapper_skips_the_call_when_exhausted():
    """A budgeted callable is never invoked once the budget is exhausted."""
    budget = CostBudget(max_cost_usd=0.10, cost_per_call=0.10)
    spy = _SpyGenerator()
    wrapped = budgeted(spy, budget)

    assert wrapped('x.py') == 'UDOC<x.py>'  # first call fits
    with pytest.raises(BudgetExceededError):
        wrapped('y.py')  # second would exceed -> refused before calling spy
    # The real callable ran exactly once: the refused call was skipped, not made.
    assert spy.calls == ['x.py']


def test_default_ceiling_is_conservative():
    """The documented default ceiling is a small, conservative dollar amount."""
    assert DEFAULT_MAX_COST_USD == pytest.approx(1.0)


# --- run_incremental: halts at the ceiling, does not exceed, does not advance -

def test_run_halts_at_ceiling_without_exceeding(tmp_path):
    """A tiny ceiling halts the build before the call that would exceed it."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    _init_repo(repo, FILES)

    gen, syn = _SpyGenerator(), _SpySynthesizer()
    # 3 leaves at $0.10 each; ceiling $0.25 -> exactly 2 calls fit (0.20), the
    # third (0.30) is refused before it runs.
    budget = CostBudget(max_cost_usd=0.25, cost_per_call=0.10)

    result = run_incremental(repo, storage, gen, syn, budget=budget)

    assert result.halted_on_budget is True
    assert result.noop is False
    # Exactly two generator calls were made; the budget halted before the third.
    assert len(gen.calls) == 2
    # Accumulated cost never exceeded the ceiling.
    assert result.cost_spent == pytest.approx(0.20)
    assert result.cost_spent <= budget.max_cost_usd
    # The base was NOT advanced, so the unfinished work is retried next run.
    assert RunState(storage).get_run_sha(repo) is None


def test_halt_keeps_completed_docs(tmp_path):
    """Whatever completed before the halt is persisted (committed)."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    _init_repo(repo, FILES)

    gen, syn = _SpyGenerator(), _SpySynthesizer()
    budget = CostBudget(max_cost_usd=0.25, cost_per_call=0.10)
    run_incremental(repo, storage, gen, syn, budget=budget)

    # The two leaves generated before the ceiling was hit are cached.
    cached = UnitDocStore(storage).all_docs(repo)
    assert len(cached) == 2
    for path in cached:
        assert cached[path] == f"UDOC<{path}>"


def test_generous_budget_completes_and_tracks_cost(tmp_path):
    """A generous ceiling lets the whole run finish and reports the spend."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    sha = _init_repo(repo, FILES)

    gen, syn = _SpyGenerator(), _SpySynthesizer()
    # 3 leaves + 3 nodes (src/util, src, .) = 6 calls at $0.10 = $0.60 < $100.
    budget = CostBudget(max_cost_usd=100.0, cost_per_call=0.10)

    result = run_incremental(repo, storage, gen, syn, budget=budget)

    assert result.halted_on_budget is False
    assert result.regenerated == set(FILES)
    assert result.cost_spent == pytest.approx(0.60)
    # The full run advanced the base to HEAD as usual.
    assert RunState(storage).get_run_sha(repo) == sha


def test_no_budget_is_unbounded(tmp_path):
    """Without a budget the run is unbounded and reports zero tracked cost."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    _init_repo(repo, FILES)

    result = run_incremental(repo, storage, _SpyGenerator(), _SpySynthesizer())

    assert result.halted_on_budget is False
    assert result.cost_spent == pytest.approx(0.0)
    assert result.regenerated == set(FILES)
