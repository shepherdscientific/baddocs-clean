"""
Unit tests for ancestor re-synthesis (US-008).

The core promise: after a deep leaf changes, every ancestor folder/project
synthesis is re-synthesized exactly once, **child-before-parent**, consuming
already-updated children; an unrelated sibling folder is never re-synthesized
and its cached synthesis is reused unchanged.

A spy synthesizer records its calls (node id + the child docs it was handed) so
we can assert call count, ordering, and inputs without any network.
"""

from baddocs.incremental.ancestor_resynth import (
    FolderDocStore,
    ResynthResult,
    resynthesize_nodes,
)
from baddocs.incremental.merkle import build_tree


class _SpySynthesizer:
    """A deterministic fake LLM synthesizer that records its calls in order."""

    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, node_id: str, child_docs: dict) -> str:
        # Record the node and a snapshot of the child docs handed to it.
        self.calls.append((node_id, dict(child_docs)))
        return f"SYNTH<{node_id}>"

    @property
    def order(self) -> list:
        return [nid for nid, _ in self.calls]


# A nested tree. The deep leaf src/util/b.py has ancestor chain
# {src/util, src, .}; docs/ and pkg/ are unrelated siblings.
LEAF_SHAS = {
    'src/util/b.py': 'sha-b',
    'src/a.py': 'sha-a',
    'docs/c.md': 'sha-c',
    'pkg/d.py': 'sha-d',
}

UNIT_DOCS = {
    'src/util/b.py': 'UDOC<src/util/b.py>',
    'src/a.py': 'UDOC<src/a.py>',
    'docs/c.md': 'UDOC<docs/c.md>',
    'pkg/d.py': 'UDOC<pkg/d.py>',
}

# Every folder/project node in the tree.
ALL_NODES = {'.', 'src', 'src/util', 'docs', 'pkg'}

# The ancestor chain of the edited deep leaf src/util/b.py.
ANCESTOR_CHAIN = {'src/util', 'src', '.'}


def _seed_folder_cache(repo, storage) -> FolderDocStore:
    """Populate the synthesis cache as a prior successful run would have."""
    store = FolderDocStore(storage)
    for node_id in ALL_NODES:
        store.save_doc(repo, node_id, f"CACHED<{node_id}>")
    return store


def test_each_ancestor_resynthesized_once_child_before_parent(tmp_path):
    """Exactly the ancestor chain is re-synthesized, deepest node first."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    _seed_folder_cache(repo, storage)
    tree = build_tree(LEAF_SHAS)

    syn = _SpySynthesizer()
    result = resynthesize_nodes(
        repo, tree, ANCESTOR_CHAIN, UNIT_DOCS, syn, storage
    )

    # Each ancestor synthesized exactly once...
    assert sorted(syn.order) == sorted(ANCESTOR_CHAIN)
    assert len(syn.calls) == len(ANCESTOR_CHAIN)
    assert result.resynthesized == ANCESTOR_CHAIN

    # ...child-before-parent: src/util before src before the project root.
    assert syn.order.index('src/util') < syn.order.index('src')
    assert syn.order.index('src') < syn.order.index('.')


def test_unrelated_sibling_not_resynthesized_and_reused(tmp_path):
    """Sibling folders outside the chain keep their cached synthesis."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    _seed_folder_cache(repo, storage)
    tree = build_tree(LEAF_SHAS)

    syn = _SpySynthesizer()
    result = resynthesize_nodes(
        repo, tree, ANCESTOR_CHAIN, UNIT_DOCS, syn, storage
    )

    # docs/ and pkg/ were never touched.
    assert 'docs' not in syn.order
    assert 'pkg' not in syn.order
    # Their cached docs survive verbatim in the merged result.
    assert result.docs['docs'] == "CACHED<docs>"
    assert result.docs['pkg'] == "CACHED<pkg>"


def test_parent_consumes_updated_children(tmp_path):
    """A re-synthesized parent reads the fresh docs of its children."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    _seed_folder_cache(repo, storage)
    tree = build_tree(LEAF_SHAS)

    syn = _SpySynthesizer()
    resynthesize_nodes(repo, tree, ANCESTOR_CHAIN, UNIT_DOCS, syn, storage)

    calls = dict(syn.calls)

    # src/util synthesizes from its leaf child's current unit doc.
    assert calls['src/util'] == {'src/util/b.py': 'UDOC<src/util/b.py>'}

    # src synthesizes from the JUST-updated src/util folder doc plus the
    # current unit doc of its own leaf child src/a.py.
    assert calls['src'] == {
        'src/util': 'SYNTH<src/util>',
        'src/a.py': 'UDOC<src/a.py>',
    }

    # The project root synthesizes from its three folder children: the freshly
    # re-synthesized src plus the still-cached docs/ and pkg/.
    assert calls['.'] == {
        'src': 'SYNTH<src>',
        'docs': 'CACHED<docs>',
        'pkg': 'CACHED<pkg>',
    }


def test_merged_docs_combine_fresh_and_cached(tmp_path):
    """Result docs = freshly synthesized chain + reused cached siblings."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    _seed_folder_cache(repo, storage)
    tree = build_tree(LEAF_SHAS)

    syn = _SpySynthesizer()
    result = resynthesize_nodes(
        repo, tree, ANCESTOR_CHAIN, UNIT_DOCS, syn, storage
    )

    assert result.docs == {
        '.': 'SYNTH<.>',
        'src': 'SYNTH<src>',
        'src/util': 'SYNTH<src/util>',
        'docs': 'CACHED<docs>',
        'pkg': 'CACHED<pkg>',
    }


def test_empty_stale_nodes_is_noop(tmp_path):
    """No stale nodes -> zero synthesis calls; cache returned untouched."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    _seed_folder_cache(repo, storage)
    tree = build_tree(LEAF_SHAS)

    syn = _SpySynthesizer()
    result = resynthesize_nodes(repo, tree, set(), UNIT_DOCS, syn, storage)

    assert syn.calls == []
    assert result.resynthesized == set()
    assert result.docs == {n: f"CACHED<{n}>" for n in ALL_NODES}


def test_result_type(tmp_path):
    """resynthesize_nodes returns a ResynthResult."""
    repo = tmp_path / 'repo'
    storage = tmp_path / 'store'
    tree = build_tree(LEAF_SHAS)
    result = resynthesize_nodes(
        repo, tree, set(), {}, _SpySynthesizer(), storage
    )
    assert isinstance(result, ResynthResult)
