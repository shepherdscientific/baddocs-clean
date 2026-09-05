"""Clone-and-generate glue between the GitHub webhook and the Merkle engine.

On a push, we materialize the repo at the pushed commit into a persistent
workspace (so the Merkle store survives across pushes and stays incremental),
run the hierarchical generator, and return a summary. Cloning uses the App
installation token so private repos work.

Running the LLM generation is blocking and can take minutes, so callers should
invoke :func:`run_docs_job` from a background task (see the webhook handler),
never inline in the request path.
"""
import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

from baddocs.incremental.llm_docs import generate_hierarchical_docs

logger = logging.getLogger(__name__)

# Where per-repo working checkouts + Merkle stores live between pushes.
WORKSPACE_ROOT = os.environ.get("BADDOCS_WORKSPACE", os.path.expanduser("~/.baddocs/workspaces"))


@dataclass
class DocJobResult:
    repository: str
    status: str
    regenerated: List[str] = field(default_factory=list)
    reused: int = 0
    resynthesized: List[str] = field(default_factory=list)
    noop: bool = False
    error: Optional[str] = None


def _run_git(args: List[str], cwd: Optional[str] = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   capture_output=True, text=True)


def _ensure_checkout(clone_url: str, repo_full_name: str, commit_sha: Optional[str],
                     token: Optional[str]) -> str:
    """Clone (first time) or fetch (subsequent) the repo into the workspace and
    check out ``commit_sha``. Returns the local repo path."""
    safe = repo_full_name.replace("/", "__")
    dest = os.path.join(WORKSPACE_ROOT, safe)
    url = clone_url
    if token and url.startswith("https://"):
        url = url.replace("https://", f"https://x-access-token:{token}@", 1)

    if not os.path.isdir(os.path.join(dest, ".git")):
        os.makedirs(WORKSPACE_ROOT, exist_ok=True)
        _run_git(["clone", "--quiet", url, dest])
    else:
        _run_git(["remote", "set-url", "origin", url], cwd=dest)
        _run_git(["fetch", "--quiet", "origin"], cwd=dest)

    if commit_sha:
        _run_git(["checkout", "--quiet", "--force", commit_sha], cwd=dest)
    else:
        _run_git(["checkout", "--quiet", "--force", "HEAD"], cwd=dest)
    return dest


def run_docs_job(clone_url: str, repo_full_name: str, commit_sha: Optional[str],
                 token: Optional[str], hub: Optional[str] = None,
                 model: Optional[str] = None) -> DocJobResult:
    """Blocking: check out the repo and run one incremental hierarchical generation."""
    try:
        repo_path = _ensure_checkout(clone_url, repo_full_name, commit_sha, token)
        kwargs = {}
        if hub:
            kwargs["hub"] = hub
        if model:
            kwargs["model"] = model
        result = generate_hierarchical_docs(repo_path, **kwargs)
        logger.info("docs job %s: noop=%s regenerated=%d resynthesized=%d",
                    repo_full_name, result.noop, len(result.regenerated), len(result.resynthesized))
        return DocJobResult(
            repository=repo_full_name,
            status="noop" if result.noop else "generated",
            regenerated=sorted(result.regenerated),
            reused=len(result.reused),
            resynthesized=sorted(result.resynthesized),
            noop=result.noop,
        )
    except subprocess.CalledProcessError as e:  # noqa: PERF203
        logger.error("git error for %s: %s", repo_full_name, e.stderr)
        return DocJobResult(repository=repo_full_name, status="error", error=f"git: {e.stderr.strip()[:300]}")
    except Exception as e:  # noqa: BLE001
        logger.error("docs job failed for %s: %s", repo_full_name, e)
        return DocJobResult(repository=repo_full_name, status="error", error=str(e))


async def run_docs_job_async(*args, **kwargs) -> DocJobResult:
    """Run :func:`run_docs_job` in a thread so it never blocks the event loop."""
    return await asyncio.to_thread(run_docs_job, *args, **kwargs)
