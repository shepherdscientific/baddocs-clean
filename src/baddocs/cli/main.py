#!/usr/bin/env python3
"""BadDocs CLI main entry point."""

import click


@click.group()
def cli():
    """BadDocs - incremental, local-first documentation (with Verilog/RTL support)."""
    pass


@cli.command()
@click.argument('repo_path')
def init(repo_path):
    """Initialize BadDocs for a repository."""
    click.echo(f'Initialized BadDocs for {repo_path}')


@cli.command()
@click.argument('repo_path')
@click.option('--docs-dir', default='bd-docs', show_default=True,
              help='Output docs directory (relative to the repo).')
@click.option('--workers', default=1, show_default=True, type=int,
              help='Parallel unit-doc workers (fan out across the model fleet).')
def generate(repo_path, docs_dir, workers):
    """Generate hierarchical docs (unit -> folder -> repo), incrementally.

    Only files whose git blob changed since the last run are re-documented, and
    only their ancestor folder/project docs re-synthesized. A run with no change
    is a zero-LLM no-op.
    """
    from baddocs.incremental.llm_docs import generate_hierarchical_docs

    result = generate_hierarchical_docs(repo_path, docs_dir=docs_dir, max_workers=workers)
    if result.noop:
        click.echo('No changes since last run — nothing to do.')
        return
    click.echo(f'Regenerated {len(result.regenerated)} unit doc(s), '
               f'reused {len(result.reused)}, '
               f're-synthesized {len(result.resynthesized)} folder/project doc(s).')
    for p in sorted(result.regenerated):
        click.echo(f'  + {p}')


@cli.command()
@click.argument('repo_path')
def analyze(repo_path):
    """Alias for `generate` (kept for compatibility)."""
    from baddocs.incremental.llm_docs import generate_hierarchical_docs

    result = generate_hierarchical_docs(repo_path)
    click.echo(f'noop={result.noop} regenerated={len(result.regenerated)} '
               f'resynthesized={len(result.resynthesized)}')


if __name__ == '__main__':
    cli()
