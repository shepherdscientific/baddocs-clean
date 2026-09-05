#!/usr/bin/env python3
"""Hierarchical, incremental documentation generation.

    unit (source file) -> folder -> repo/project

Built on the Merkle incremental engine (``baddocs.incremental``): a content-keyed
tree where each source file is a leaf (git blob SHA), each directory an internal
node, and the repo root the project node. On every run only the files whose blob
changed are re-documented, and only their ancestor folder/project docs are
re-synthesized -- everything else is reused byte-identical. A run with no change
is a zero-LLM no-op.

Unit docs use the language processors (``VerilogProcessor`` gives HDL structure);
folder and project docs are synthesized bottom-up from their children's docs.
LLM calls target any OpenAI-compatible endpoint (default: the local fleet hub).

Usage:
    python scripts/hierarchical_generate.py <repo_path> [--docs-dir bd-docs]

Env:
    SWARM_HUB   OpenAI-compatible base URL (default http://localhost:4000/v1)
    BD_MODEL    model/role name (default swarm-coder)
"""
import argparse
import json
import os
import time
import urllib.request

from baddocs.incremental.incremental_run import run_incremental
from baddocs.processors import VerilogProcessor

HUB = os.environ.get("SWARM_HUB", "http://localhost:4000/v1")
MODEL = os.environ.get("BD_MODEL", "swarm-coder")

VERILOG_EXT = {".v", ".vh", ".sv", ".svh", ".svi"}
# Document CODE only; markdown/text is already documentation.
CODE_EXT = VERILOG_EXT | {".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h"}

_vproc = VerilogProcessor({})


def _llm(system, user, max_tokens=1800):
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": max_tokens, "temperature": 0.2, "stream": False,
    }).encode()
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(f"{HUB}/chat/completions", data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                out = json.loads(r.read())["choices"][0]["message"]["content"].strip()
            if out:
                return out
            last = "empty response"
        except Exception as e:  # noqa: BLE001
            last = repr(e)
        time.sleep(5 * (attempt + 1))
    return f"*(doc generation failed after retries: {last})*"


def build_callbacks(target, docs_dir, project_name):
    def _write(rel_md, text):
        out = os.path.join(docs_dir, rel_md)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(text + "\n")

    def generator(path):
        ext = os.path.splitext(path)[1]
        try:
            code = open(os.path.join(target, path), encoding="utf-8", errors="replace").read()
        except Exception as e:  # noqa: BLE001
            return f"*(could not read {path}: {e})*"
        if ext in VERILOG_EXT:
            summary = []
            for m in _vproc.parse(code)["modules"]:
                ports = ", ".join(f"{p['direction']} {p['width']} {p['name']}".replace("  ", " ") for p in m["ports"])
                params = ", ".join(f"{p['name']}={p['default']}" for p in m["parameters"])
                insts = ", ".join(f"{i['instance_name']}:{i['module_type']}" for i in m["instances"])
                summary.append(f"module {m['name']} | params: {params} | ports: {ports} | "
                               f"instances: {insts or 'none'} | always={m['always_blocks']} | "
                               f"infers_multiplier={m['infers_multiplier']}")
            system = "You are a precise hardware documentation writer for Verilog/SystemVerilog."
            user = (f"File: {path}\nExtracted structure:\n" + "\n".join(summary) +
                    f"\n\nSource:\n```verilog\n{code}\n```\n\n"
                    "Write concise Markdown: ## Overview, ## Parameters (table), "
                    "## Ports (table: name, dir, width, description), ## Behavior, ## Notes. "
                    "Do not invent ports/parameters beyond those listed.")
        else:
            lang = {".py": "python", ".ts": "typescript", ".js": "javascript"}.get(ext, ext.lstrip("."))
            system = "You are a precise software documentation writer."
            user = (f"File: {path}\n\n```{lang}\n{code}\n```\n\n"
                    "Write concise Markdown docs: ## Overview, ## Key functions/classes, ## Usage/notes.")
        doc = _llm(system, user)
        _write(path + ".md", f"# {path}\n\n{doc}")
        print(f"  [unit] {path}", flush=True)
        return doc

    def synthesizer(node_id, child_docs):
        is_project = node_id in ("", ".")
        children_blob = "\n\n".join(f"### {cid}\n{doc[:1500]}" for cid, doc in sorted(child_docs.items()))
        system = "You write clear, high-level module/architecture documentation."
        if is_project:
            user = (f"Below are per-folder documentation summaries for the project `{project_name}`. "
                    f"Write a top-level Markdown overview: what the project is, how the pieces fit "
                    f"together, and the key design ideas.\n\n{children_blob}")
        else:
            user = (f"Below are documentation entries for the direct children of folder `{node_id}`. "
                    f"Write a concise Markdown overview of what this folder contains and how its "
                    f"parts relate.\n\n{children_blob}")
        doc = _llm(system, user)
        rel = "__project__.md" if is_project else os.path.join(node_id, "__folder__.md")
        title = f"{project_name} — repository overview" if is_project else node_id
        _write(rel, f"# {title}\n\n{doc}")
        print(f"  [synth] {node_id or '.'}", flush=True)
        return doc

    return generator, synthesizer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", help="path to the git repository to document")
    ap.add_argument("--docs-dir", default="bd-docs", help="output docs dir (relative to repo)")
    args = ap.parse_args()

    target = os.path.abspath(os.path.expanduser(args.repo))
    docs_dir = os.path.join(target, args.docs_dir)
    storage = os.path.join(target, ".baddocs-merkle")
    project_name = os.path.basename(target.rstrip("/"))

    generator, synthesizer = build_callbacks(target, docs_dir, project_name)
    path_filter = lambda p: os.path.splitext(p)[1] in CODE_EXT  # noqa: E731

    print(f"=== hierarchical generation over {target} ===", flush=True)
    result = run_incremental(target, storage, generator, synthesizer, path_filter=path_filter)
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
