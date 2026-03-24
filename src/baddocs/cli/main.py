#!/usr/bin/env python3
"""BadDocs CLI main entry point."""

import click
from baddocs.cli.output import OutputFormatter

@click.group()
def cli():
    """BadDocs - AI-powered documentation for legacy codebases."""
    pass

@cli.command()
@click.argument('repo_path')
def init(repo_path):
    """Initialize BadDocs for a repository."""
    click.echo(f'Initializing BadDocs for {repo_path}')

@cli.command()
@click.argument('repo_path')
def analyze(repo_path):
    """Analyze a repository."""
    click.echo(f'Analyzing {repo_path}')

if __name__ == '__main__':
    cli()
