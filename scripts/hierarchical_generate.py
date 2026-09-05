#!/usr/bin/env python3
"""CLI: hierarchical, incremental documentation generation.

    unit (source file) -> folder -> repo/project

A thin wrapper over :func:`baddocs.incremental.llm_docs.generate_hierarchical_docs`.
Only files whose git blob changed since the last run are re-documented, and only
their ancestor folder/project docs re-synthesized; a run with no change is a
zero-LLM no-op.

Usage:
    python scripts/hierarchical_generate.py <repo_path> [--docs-dir bd-docs]

Env:
    SWARM_HUB   OpenAI-compatible base URL (default http://localhost:4000/v1)
    BD_MODEL    model/role name (default swarm-coder)
"""
import argparse

from baddocs.incremental.llm_docs import generate_hierarchical_docs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", help="path to the git repository to document")
    ap.add_argument("--docs-dir", default="bd-docs", help="output docs dir (relative to repo)")
    args = ap.parse_args()

    print(f"=== hierarchical generation over {args.repo} ===", flush=True)
    result = generate_hierarchical_docs(args.repo, docs_dir=args.docs_dir)
    print("\n=== RESULT ===")
    for attr in ("noop", "regenerated", "reused", "resynthesized", "deleted",
                 "head_sha", "halted_on_budget", "cost_spent"):
        val = getattr(result, attr)
        if isinstance(val, (list, set, tuple)):
            print(f"{attr}: {len(val)} -> {sorted(val)}")
        else:
            print(f"{attr}: {val}")


if __name__ == "__main__":
    main()
