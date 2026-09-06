"""Public "try it free" endpoint: a CAPPED hierarchical doc generation for a
public GitHub repo — the engine side of the hosted baddocs.io demo funnel.

This is the ENGINE only. The hosted product must wrap it with the abuse/gating
layer that already exists in daoweb:
  * Turnstile + a global daily cap + per-IP rate limit (see the concierge's
    requireTurnstile / createGlobalCap), for anonymous "try it free".
  * grit/auth for signed-in accounts (higher limits, private repos via the
    GitHub App), and daoweb billing for paid tiers/quotas.
Here we enforce only hard TECHNICAL caps (public https GitHub repos, a file cap,
a clone timeout) so this endpoint is safe to expose behind that gate.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..incremental.incremental_run import run_incremental
from ..incremental.llm_docs import build_callbacks, CODE_EXT

router = APIRouter(tags=["try-it"])

# Free-tier technical caps (tune via env).
MAX_FILES = int(os.getenv("BADDOCS_TRY_MAX_FILES", "6"))
CLONE_TIMEOUT_S = int(os.getenv("BADDOCS_TRY_CLONE_TIMEOUT", "60"))

_GITHUB_RE = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+/?$")


class TryRequest(BaseModel):
    repo_url: str


def _tracked_code_files(repo: str):
    out = subprocess.run(
        ["git", "-C", repo, "ls-files"], capture_output=True, text=True, check=True
    ).stdout
    return [f for f in out.splitlines() if os.path.splitext(f)[1] in CODE_EXT]


@router.post("/api/try-it")
async def try_it(req: TryRequest):
    """Clone a public repo (shallow), document up to MAX_FILES code files with the
    incremental hierarchical engine, and return the docs. No persistence."""
    url = (req.repo_url or "").strip()
    if not _GITHUB_RE.match(url):
        raise HTTPException(status_code=400, detail="Provide a public GitHub repo URL, e.g. https://github.com/owner/repo")

    tmp = tempfile.mkdtemp(prefix="baddocs-try-")
    try:
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", "--quiet", url, tmp],
                check=True, capture_output=True, text=True, timeout=CLONE_TIMEOUT_S,
            )
        except subprocess.CalledProcessError as e:
            raise HTTPException(status_code=400, detail=f"Could not clone that repo (is it public?): {(e.stderr or '').strip()[:200]}")
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=400, detail="Repo clone timed out.")

        code_files = _tracked_code_files(tmp)
        if not code_files:
            raise HTTPException(status_code=400, detail="No supported source files found (Verilog/SystemVerilog, Python, JS/TS, Go, Rust, Java, C/C++).")
        capped = set(code_files[:MAX_FILES])

        docs_dir = os.path.join(tmp, "_bd_docs")
        project = url.rstrip("/").split("/")[-1]
        generator, synthesizer = build_callbacks(tmp, docs_dir, project)  # uses the configured AI_* endpoint
        result = run_incremental(
            tmp, os.path.join(tmp, ".merkle"), generator, synthesizer,
            path_filter=lambda p: p in capped,
        )
        return {
            "repo": url,
            "capped_to_files": len(capped),
            "total_code_files": len(code_files),
            "truncated": len(code_files) > MAX_FILES,
            "unit_docs": result.unit_docs,
            "folder_docs": result.folder_docs,
            "note": f"Free preview is limited to {MAX_FILES} files. Sign in for full-repo runs, private repos, and higher limits.",
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
