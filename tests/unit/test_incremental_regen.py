"""
Unit tests for incremental unit-doc regeneration (US-007).

The core promise: with 1 of N leaves changed, the (mock) LLM unit-doc generator
is called exactly once -- for the changed leaf -- and the N-1 cached docs are
returned unchanged. Deleted leaves have their cached docs dropped.

A fake generator records its calls so we can assert counts without any network.
"""

from baddocs.incremental.stale_set import StaleSet
from baddocs.incremental.unit_regen import (
    RegenResult,
    UnitDocStore,
    regenerate_units,
)


class _SpyGenerator:
    """A deterministic fake LLM unit-doc generator that records its calls."""

    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, path: str) -> str:
        self.calls.append(path)
        return f"DOC<{path}>@v{self.calls.count(path)}"


# N leaves; we will edit exactly one of them.
LEAVES = ['src/a.py', 'src/util/b.py', 'docs/c.md', 'pkg/d.py']


def _seed_cache(repo, storage) -> UnitDocStore:
    """Populate the cache as a prior successful run would have."""
    store = UnitDocStore(storage)
    for path in LEAVES:
        store.save_doc(repo, path, f"CACHED<{path}>")
    return store


def test_only_stale_leaf_is_regenerated(tmp_path):
    """1 of N leaves stale -> generator called exactly once, rest reused."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    cache = _seed_cache(repo, storage)

    gen = _SpyGenerator()
    stale = StaleSet(stale_leaves={'src/util/b.py'})

    result = regenerate_units(repo, stale, gen, storage)

    # Exactly one LLM call, for the changed leaf only.
    assert gen.calls == ['src/util/b.py']
    assert result.regenerated == {'src/util/b.py'}

    # The N-1 untouched leaves are reused unchanged.
    assert result.reused == set(LEAVES) - {'src/util/b.py'}
    for path in result.reused:
        assert result.docs[path] == f"CACHED<{path}>"

    # The stale leaf now holds the freshly generated doc.
    assert result.docs['src/util/b.py'] == "DOC<src/util/b.py>@v1"
    # ...and that fresh doc is persisted for next time.
    assert cache.get_doc(repo, 'src/util/b.py') == "DOC<src/util/b.py>@v1"


def test_deleted_leaf_doc_is_removed(tmp_path):
    """A deleted leaf's cached doc is dropped and absent from the result."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    cache = _seed_cache(repo, storage)

    gen = _SpyGenerator()
    stale = StaleSet(deleted={'docs/c.md'})

    result = regenerate_units(repo, stale, gen, storage)

    assert gen.calls == []  # deletion never calls the LLM
    assert result.deleted == {'docs/c.md'}
    assert 'docs/c.md' not in result.docs
    assert cache.get_doc(repo, 'docs/c.md') is None
    # Survivors untouched.
    assert set(result.docs) == set(LEAVES) - {'docs/c.md'}


def test_no_changes_calls_llm_zero_times(tmp_path):
    """An empty plan regenerates nothing and returns every cached doc as-is."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    _seed_cache(repo, storage)

    gen = _SpyGenerator()
    result = regenerate_units(repo, StaleSet(), gen, storage)

    assert gen.calls == []
    assert result.regenerated == set()
    assert result.reused == set(LEAVES)
    assert result.docs == {p: f"CACHED<{p}>" for p in LEAVES}


def test_new_leaf_is_generated_and_added(tmp_path):
    """A brand-new (uncached) stale leaf is generated and joins the doc set."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    _seed_cache(repo, storage)

    gen = _SpyGenerator()
    stale = StaleSet(stale_leaves={'pkg/new.py'})

    result = regenerate_units(repo, stale, gen, storage)

    assert gen.calls == ['pkg/new.py']
    assert result.docs['pkg/new.py'] == "DOC<pkg/new.py>@v1"
    assert set(result.docs) == set(LEAVES) | {'pkg/new.py'}


def test_result_type(tmp_path):
    """regenerate_units returns a RegenResult."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    result = regenerate_units(repo, StaleSet(), _SpyGenerator(), storage)
    assert isinstance(result, RegenResult)
