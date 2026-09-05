"""LLM-backed hierarchical documentation callbacks for the Merkle engine.

Shared by the CLI driver (``scripts/hierarchical_generate.py``) and the GitHub
webhook (``baddocs.web.github.doc_runner``). Produces:

    unit (source file) -> folder -> repo/project

Unit docs use the language processors (``VerilogProcessor`` gives real HDL
structure); folder/project docs are synthesized bottom-up from children. LLM
calls target any OpenAI-compatible endpoint (default: the local fleet hub).
"""
import json
import os
import time
import urllib.request
from typing import Callable, Dict, Optional, Tuple

from baddocs.incremental.incremental_run import run_incremental
from baddocs.processors import VerilogProcessor

DEFAULT_HUB = os.environ.get("SWARM_HUB", "http://localhost:4000/v1")
DEFAULT_MODEL = os.environ.get("BD_MODEL", "swarm-coder")

VERILOG_EXT = {".v", ".vh", ".sv", ".svh", ".svi"}
# Document CODE only; markdown/text is already documentation.
CODE_EXT = VERILOG_EXT | {".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h"}

_vproc = VerilogProcessor({})


def code_path_filter(path: str) -> bool:
    return os.path.splitext(path)[1] in CODE_EXT


def _llm(hub: str, model: str, system: str, user: str, max_tokens: int = 1800) -> str:
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": max_tokens, "temperature": 0.2, "stream": False,
    }).encode()
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(f"{hub}/chat/completions", data=payload,
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


def build_callbacks(target: str, docs_dir: str, project_name: str,
                    hub: str = DEFAULT_HUB, model: str = DEFAULT_MODEL
                    ) -> Tuple[Callable[[str], str], Callable[[str, Dict[str, str]], str]]:
    """Return (generator, synthesizer) callables for ``run_incremental``."""

    def _write(rel_md: str, text: str) -> None:
        out = os.path.join(docs_dir, rel_md)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(text + "\n")

    def generator(path: str) -> str:
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
        doc = _llm(hub, model, system, user)
        _write(path + ".md", f"# {path}\n\n{doc}")
        return doc

    def synthesizer(node_id: str, child_docs: Dict[str, str]) -> str:
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
        doc = _llm(hub, model, system, user)
        rel = "__project__.md" if is_project else os.path.join(node_id, "__folder__.md")
        title = f"{project_name} — repository overview" if is_project else node_id
        _write(rel, f"# {title}\n\n{doc}")
        return doc

    return generator, synthesizer


def generate_hierarchical_docs(repo: str, storage_path: Optional[str] = None,
                               docs_dir: str = "bd-docs", hub: str = DEFAULT_HUB,
                               model: str = DEFAULT_MODEL):
    """Run one incremental hierarchical generation over ``repo``.

    Returns the engine's :class:`IncrementalRunResult` (``noop``, ``regenerated``,
    ``reused``, ``resynthesized``, ...). Only files whose git blob changed since
    the last run are re-documented, and only their ancestor folder/project docs
    re-synthesized.
    """
    target = os.path.abspath(os.path.expanduser(repo))
    docs_abs = os.path.join(target, docs_dir)
    storage = storage_path or os.path.join(target, ".baddocs-merkle")
    project_name = os.path.basename(target.rstrip("/"))
    generator, synthesizer = build_callbacks(target, docs_abs, project_name, hub, model)
    return run_incremental(target, storage, generator, synthesizer, path_filter=code_path_filter)
