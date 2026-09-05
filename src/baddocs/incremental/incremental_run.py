"""
Incremental run orchestration with a no-op short-circuit (US-009).

This is the top-level driver that stitches the planning and work stages built in
the preceding stories into a single run:

1. read ``last_run_sha`` (US-001) and the current HEAD;
2. compute the minimal plan via
   :func:`~baddocs.incremental.stale_set.compute_stale_set` (US-006);
3. if the plan is empty -> **short-circuit**: log "nothing to do", make zero LLM
   calls, write no docs, but still advance ``last_run_sha`` to HEAD so the next
   run diffs from the right base;
4. otherwise regenerate only the stale unit docs (US-007), re-synthesize only
   the stale ancestor nodes bottom-up (US-008), then persist the leaf snapshot,
   the Merkle tree, and the new ``last_run_sha`` -- all only *after* the whole
   run succeeds, so a crash leaves the previous known-good state intact.

The short-circuit fires both when HEAD equals ``last_run_sha`` (nothing changed
at all) and when the diff touches only files irrelevant to docs: an optional
``path_filter`` restricts which tracked files count as leaves, so a push that
edits only excluded files produces an empty plan and a no-op.

The LLM is never called directly here: the caller injects a unit-doc
``generator`` and a folder/project ``synthesizer`` (the same callables consumed
by US-007/US-008). Production wires these to the real LLM; tests inject
deterministic fakes and assert zero calls on a no-op without any network access.

As everywhere in this package, staleness is decided by content identity (blob
SHA / Merkle subtree hash), never by ``st_mtime``.
"""

import argparse
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

from .ancestor_resynth import Synthesizer, resynthesize_nodes
from .blob_sha import all_tracked_files, blob_sha
from .cost_ceiling import (
    DEFAULT_MAX_COST_USD,
    BudgetExceededError,
    CostBudget,
    budgeted,
)
from .leaf_staleness import LeafStaleness
from .merkle import MerkleStore, build_tree
from .run_state import RunState
from .stale_set import PathFilter, compute_stale_set
from .unit_regen import UnitDocGenerator, regenerate_units

PathLike = Union[str, Path]

__all__ = ['IncrementalRunResult', 'run_incremental', 'main']


@dataclass
class IncrementalRunResult:
    """
    The outcome of one incremental run.

    ``noop`` is the distinguishable no-op signal: True iff there was nothing to
    do, in which case no LLM calls were made and no docs were written, so callers
    can branch and CI can report "nothing to do" without inspecting the other
    fields. ``head_sha`` is the commit the run advanced ``last_run_sha``
    to -- set on both a no-op and a real run. The remaining fields mirror
    :class:`~baddocs.incremental.unit_regen.RegenResult` and
    :class:`~baddocs.incremental.ancestor_resynth.ResynthResult` and stay empty
    on a no-op.

    ``halted_on_budget`` is True iff a per-run cost ceiling (US-013) stopped the
    run before the next LLM call. On a halt the docs that *did* complete are kept
    (they are persisted as they are produced), but ``last_run_sha`` is **not**
    advanced, so the next run retries the unfinished work. ``cost_spent`` is the
    accumulated USD cost of the LLM calls actually made this run (0.0 when no
    budget was supplied).
    """

    head_sha: str
    noop: bool
    regenerated: Set[str] = field(default_factory=set)
    reused: Set[str] = field(default_factory=set)
    deleted: Set[str] = field(default_factory=set)
    resynthesized: Set[str] = field(default_factory=set)
    unit_docs: Dict[str, str] = field(default_factory=dict)
    folder_docs: Dict[str, str] = field(default_factory=dict)
    halted_on_budget: bool = False
    cost_spent: float = 0.0


def _current_leaf_shas(
    repo: PathLike,
    path_filter: Optional[PathFilter],
) -> Dict[str, str]:
    """Map every (filtered) tracked file to its current working-tree blob SHA."""
    shas: Dict[str, str] = {}
    for path in all_tracked_files(repo):
        if path_filter is not None and not path_filter(path):
            continue
        shas[path] = blob_sha(repo, Path(repo) / path)
    return shas


def run_incremental(
    repo: PathLike,
    storage_path: PathLike,
    generator: UnitDocGenerator,
    synthesizer: Synthesizer,
    path_filter: Optional[PathFilter] = None,
    logger: Optional[logging.Logger] = None,
    budget: Optional[CostBudget] = None,
    max_workers: int = 1,
) -> IncrementalRunResult:
    """
    Run one incremental doc generation, short-circuiting when there's no work.

    Args:
        repo: Repository root.
        storage_path: Directory holding the incremental databases (RunState,
            LeafStaleness, MerkleStore, UnitDocStore, FolderDocStore).
        generator: Injected LLM unit-doc generator (path -> doc text); called
            only for stale leaves, and never on a no-op.
        synthesizer: Injected LLM folder/project synthesizer (node id + child
            docs -> synthesis text); called only for stale nodes, never on a
            no-op.
        path_filter: Optional predicate selecting which tracked files are doc
            leaves. A push touching only rejected files yields a no-op.
        logger: Optional logger for the "nothing to do" message; defaults to the
            module logger.
        budget: Optional per-run cost ceiling (US-013). When supplied, every LLM
            call is charged against it *before* being made; once the projected
            cost would exceed the ceiling the run stops before that call, keeps
            the docs already produced, and returns ``halted_on_budget=True``
            **without** advancing ``last_run_sha`` (so the rest is retried next
            run). When None, generation is unbounded.

    Returns:
        An :class:`IncrementalRunResult`. On a no-op ``noop`` is True, the work
        fields are empty, and ``last_run_sha`` has still been advanced to HEAD.
        On a budget halt ``halted_on_budget`` is True and the base is unchanged.
    """
    log = logger or logging.getLogger(__name__)
    repo_p = Path(repo)
    storage_p = Path(storage_path)

    run_state = RunState(storage_p)
    last_run_sha = run_state.get_run_sha(repo_p)
    head_sha = run_state.get_current_sha(repo_p)

    stale = compute_stale_set(
        repo_p, last_run_sha, storage_p, path_filter=path_filter
    )

    # --- No-op short-circuit ------------------------------------------------
    # Nothing relevant changed: spend zero LLM calls, write no docs. Still
    # advance last_run_sha so the next run diffs from HEAD rather than re-walking
    # history from the old base.
    if stale.is_empty:
        log.info(
            "baddocs incremental: nothing to do (HEAD %s); advancing base",
            head_sha,
        )
        run_state.save_run_sha(repo_p, head_sha)
        return IncrementalRunResult(head_sha=head_sha, noop=True)

    # Bound the expensive LLM calls with the per-run cost ceiling (US-013). Each
    # wrapped call charges the budget *before* delegating, so a call that would
    # breach the ceiling is skipped, not merely discarded.
    gen = generator if budget is None else budgeted(generator, budget)
    synth = synthesizer if budget is None else budgeted(synthesizer, budget)

    # --- Work: regenerate stale leaves, then re-synthesize stale ancestors --
    # Parallel unit generation only when there is no cost ceiling: the budget
    # path must charge calls in order so it can stop before the breaching call.
    unit_workers = 1 if budget is not None else max_workers
    try:
        regen = regenerate_units(repo_p, stale, gen, storage_p, max_workers=unit_workers)

        # Build the current Merkle tree from the same (filtered) leaf set the
        # plan was computed from, so the persisted tree matches what the next run
        # diffs.
        current_leaf_shas = _current_leaf_shas(repo_p, path_filter)
        tree = build_tree(current_leaf_shas)
        resynth = resynthesize_nodes(
            repo_p, tree, stale.stale_nodes, regen.docs, synth, storage_p
        )
    except BudgetExceededError as exc:
        # The ceiling was hit before an LLM call: keep whatever docs already
        # completed (they were persisted as produced) but DO NOT advance the run
        # state, so the unfinished work is retried next run. The caller maps the
        # halt to a clear non-zero/warning CI exit.
        log.warning("baddocs incremental: %s; halting run", exc)
        return IncrementalRunResult(
            head_sha=head_sha,
            noop=False,
            halted_on_budget=True,
            cost_spent=exc.spent,
        )

    # Advance run state only after the whole run succeeds (US-001 contract): a
    # crash above leaves the previous snapshot/tree/SHA intact.
    LeafStaleness(storage_p).record_leaf_shas(repo_p, current_leaf_shas)
    MerkleStore(storage_p).save_tree(repo_p, tree)
    run_state.save_run_sha(repo_p, head_sha)

    return IncrementalRunResult(
        head_sha=head_sha,
        noop=False,
        regenerated=regen.regenerated,
        reused=regen.reused,
        deleted=regen.deleted,
        resynthesized=resynth.resynthesized,
        unit_docs=regen.docs,
        folder_docs=resynth.docs,
        cost_spent=budget.spent if budget is not None else 0.0,
    )


def main(argv: Optional[List[str]] = None) -> int:
    """
    CLI entrypoint for the CI docs-regen workflow (US-011).

    The GitHub Action (``.github/workflows/baddocs-docs.yml``) invokes this via
    ``python -m baddocs.incremental.incremental_run`` after checking out the repo
    with full history and restoring the prior ``last_run_sha``. It computes the
    minimal incremental plan (US-006) and prints which unit docs would be
    regenerated and which folder/project nodes would be re-synthesized.

    Plan-only is the default because the expensive LLM generation/synthesis is
    wired to a real API key by the *next* stories: US-012 supplies the key from a
    CI secret and US-013 enforces a per-run cost ceiling. Until generation is
    wired, this still gives CI an honest, offline preview of the work a push
    created -- and exercises exactly the engine path (RunState base + blob-SHA /
    Merkle staleness) the action depends on, never ``st_mtime``.

    ``--since`` carries the prior ``last_run_sha`` the action restored: if the
    persisted RunState has no base yet (e.g. the state cache was cold) it is
    seeded so the engine diffs from that commit; on a genuine first run it is
    empty, so the plan is a full build.

    Returns a process exit code (0 = success).
    """
    parser = argparse.ArgumentParser(
        prog='baddocs-incremental',
        description='Compute the incremental doc-regen plan for a repo (US-011).',
    )
    parser.add_argument(
        '--repo', default='.', help='Repository root (default: current dir).'
    )
    parser.add_argument(
        '--storage',
        default='.baddocs',
        help='Directory holding the incremental state DBs (default: .baddocs).',
    )
    parser.add_argument(
        '--since',
        default=None,
        help=(
            "Prior last-run commit SHA the CI step restored. Seeds the RunState "
            "base when none is persisted yet; empty on a first run (full build)."
        ),
    )
    parser.add_argument(
        '--max-cost',
        type=float,
        default=DEFAULT_MAX_COST_USD,
        help=(
            "Per-run LLM cost ceiling in USD (US-013). Generation stops before "
            "the call that would exceed it, keeping completed docs and failing "
            f"the run. Default: {DEFAULT_MAX_COST_USD:.2f}."
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format='%(message)s')
    log = logging.getLogger(__name__)

    repo_p = Path(args.repo).resolve()
    storage_p = Path(args.storage)
    storage_p.mkdir(parents=True, exist_ok=True)

    run_state = RunState(storage_p)
    # If the action passed a prior SHA and we have no persisted base (cold state
    # cache), seed it so the engine diffs from there instead of doing a full
    # rebuild. A blank --since on a true first run leaves the base None -> full
    # build, exactly as the acceptance criteria require.
    since = (args.since or '').strip()
    if since and run_state.get_run_sha(repo_p) is None:
        run_state.save_run_sha(repo_p, since)

    last_run_sha = run_state.get_run_sha(repo_p)
    head_sha = run_state.get_current_sha(repo_p)
    plan = compute_stale_set(repo_p, last_run_sha, storage_p)

    log.info('baddocs incremental plan for %s', repo_p)
    log.info('  base last_run_sha : %s', last_run_sha or '(none -> full build)')
    log.info('  head_sha          : %s', head_sha)
    log.info('  cost ceiling      : $%.2f (US-013)', args.max_cost)
    if plan.is_empty:
        log.info('  nothing to do (no stale leaves or nodes)')
        return 0

    log.info('  stale unit docs   : %d', len(plan.stale_leaves))
    for leaf in sorted(plan.stale_leaves):
        log.info('    regen  %s', leaf)
    log.info('  re-synth nodes    : %d', len(plan.stale_nodes))
    for node in sorted(plan.stale_nodes):
        log.info('    synth  %s', node)
    if plan.deleted:
        log.info('  deleted leaves    : %d', len(plan.deleted))
        for path in sorted(plan.deleted):
            log.info('    delete %s', path)
    log.info(
        '  (LLM generation is wired with the CI API key in US-012; the cost '
        'ceiling above bounds it via run_incremental(budget=...) in US-013.)'
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
