# BadDocs QA Testing Guide

> Version: 0.1.0-alpha | Repo: [shepherdscientific/baddocs-clean](https://github.com/shepherdscientific/baddocs-clean) | Branch: `dev`

---

## Overview

This guide covers the full QA testing strategy for BadDocs — automated unit and integration tests, CLI and API smoke tests, the GitHub Action plugin, language processor validation, LLM provider testing across both local and cloud setups, benchmarking across hardware and models, and OSS project integration tests.

BadDocs is a Python CLI + web service that clones GitHub repos, processes source files via language-specific parsers, calls an LLM to generate documentation, and stores results in a SQLite database with full-text search. It also ships as a GitHub Action that can be dropped into any CI/CD workflow.

---

## 1. Environment Setup

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10+ | 3.12 recommended |
| Git | Any | Must be in PATH |
| Node.js | 20+ | GitHub Action testing only |
| Docker | 24+ | Docker-mode and compose testing |

### Installation

```bash
git clone https://github.com/shepherdscientific/baddocs-clean
cd baddocs-clean
pip install -e ".[dev]"

# Verify
baddocs --version
```

### Choosing Your LLM Provider

BadDocs works with any combination of local and cloud providers. **There is no required provider** — pick whichever you have access to and test with that first. The goal is to test both local and cloud paths before sign-off; the order is up to you.

| Path | What you need | Cost | Best for |
|------|--------------|------|---------|
| **Local — Ollama** | Ollama installed, model pulled | Free | Privacy, offline, benchmarking local speed |
| **Local — llama.cpp** | llama-server running | Free | Benchmarking raw inference speed |
| **Cloud — DeepSeek** | `DEEPSEEK_API_KEY` | ~$0.14/1M tokens | Cheapest cloud option |
| **Cloud — Qwen** | `QWEN_API_KEY` | ~$0.40/1M tokens | Alternative budget cloud |
| **Cloud — OpenAI** | `OPENAI_API_KEY` | $0.30–$2.50/1M tokens | Premium quality benchmark |
| **Cloud — Anthropic** | `ANTHROPIC_API_KEY` | $0.50–$15/1M tokens | Premium quality benchmark |

Set at least one in your `.env` before running smoke tests:

```env
# Option A — local Ollama
OLLAMA_URL=http://localhost:11434

# Option B — local llama.cpp
LLAMACPP_URL=http://localhost:8080

# Option C — cloud (pick one or more)
DEEPSEEK_API_KEY=sk-...
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Always set these
BADDOCS_MVP_TIER=budget
BADDOCS_LOG_LEVEL=DEBUG
```

**Local Ollama quick setup:**
```bash
ollama pull qwen2.5-coder:7b       # good all-rounder
ollama pull deepseek-coder-v2:16b  # higher quality, slower
curl http://localhost:11434/api/tags  # verify running
```

**For GitHub App / private repo tests:**
```env
GITHUB_APP_ID=your_app_id
GITHUB_APP_PRIVATE_KEY_PATH=/path/to/key.pem
GITHUB_WEBHOOK_SECRET=your_secret
```

---

## 2. Automated Test Suite

### Quick Check

```bash
pytest tests/unit/ -v
```

### Full Suite with Coverage

```bash
pytest tests/ -v --cov=src/baddocs --cov-report=html
open htmlcov/index.html
```

### Run by Category

```bash
# Markers
pytest -m "not slow"        # skip long-running tests
pytest -m "integration"     # integration tests only
pytest -m "requires_api"    # tests that need real API keys

# Individual files
pytest tests/unit/test_cli.py -v
pytest tests/unit/test_processors.py -v
pytest tests/unit/test_storage.py -v
pytest tests/unit/test_llm_providers.py -v
pytest tests/unit/test_cost_tracking.py -v
pytest tests/unit/test_git_operations.py -v
pytest tests/unit/test_llamacpp_provider.py -v
pytest tests/integration/test_e2e_pipeline.py -v
```

### Expected Results

| Suite | Target | Notes |
|-------|--------|-------|
| Unit tests | All pass | Fully mocked — no LLM key needed |
| Integration tests | All pass | Uses mock LLM by default |
| Coverage | ≥ 50% | Configured minimum |

---

## 3. Test File Reference

| File | What It Tests |
|------|--------------|
| `tests/unit/test_cli.py` | `init`, `generate`, `search`, `status`, `version` — argument parsing, output formats, error handling |
| `tests/unit/test_processors.py` | Language processors for Python, JavaScript, Java — function/class/import extraction |
| `tests/unit/test_llm_providers.py` | Provider routing, model selection, cost-tier filtering, fallback logic |
| `tests/unit/test_storage.py` | SQLite file records, document upserts, FTS5 search |
| `tests/unit/test_git_operations.py` | Git clone, pull, branch detection, commit parsing |
| `tests/unit/test_cost_tracking.py` | Budget enforcement, monthly limits, tier filtering |
| `tests/unit/test_llamacpp_provider.py` | llama.cpp HTTP integration, health checks |
| `tests/integration/test_e2e_pipeline.py` | Full pipeline: repo → language detection → mock LLM → storage → search |
| `tests/test_github_serialization.py` | GitHub webhook payload parsing and validation |

---

## 4. CLI Smoke Tests

### 4.1 Basic Commands

```bash
baddocs --version
baddocs --help
baddocs generate --help
baddocs search --help

mkdir /tmp/baddocs-test && cd /tmp/baddocs-test
baddocs init
ls .baddocs/    # should contain config files
```

### 4.2 Documentation Generation

```bash
# Small public repo — fast, good for smoke testing
baddocs generate --repo https://github.com/shepherdscientific/optimized-sssp

baddocs status
baddocs search "graph algorithm"
baddocs search "shortest path"
baddocs search "graph" --output-format json | python3 -m json.tool
```

### 4.3 Output Formats

```bash
baddocs status --output-format human
baddocs status --output-format json
baddocs status --output-format yaml
```

### 4.4 Error Handling

```bash
# Non-existent repo — should fail gracefully with clear message
baddocs generate --repo https://github.com/nonexistent/xyz-does-not-exist

# Empty search — no crash
baddocs search ""

# Generate without init — should prompt or fail clearly
cd /tmp/uninitialised-dir && baddocs generate
```

---

## 5. Web API Tests

### 5.1 Start the Server

```bash
cp .env.example .env    # configure at least one LLM provider
uvicorn src.baddocs.web.main:app --reload --port 8000
```

### 5.2 Core Endpoint Checklist

| Endpoint | Method | Command | Expected |
|----------|--------|---------|----------|
| `/health` | GET | `curl localhost:8000/health` | `{"status":"healthy"}` |
| `/api` | GET | `curl localhost:8000/api` | Service info JSON |
| `/api/mcp-status` | GET | `curl localhost:8000/api/mcp-status` | MCP availability status |
| `/status` | GET | `curl localhost:8000/status` | Provider list + tier |
| `/providers` | GET | `curl localhost:8000/providers` | Available providers |

### 5.3 Repository Analysis Flow

```bash
# 1. Trigger analysis
REPO_RESP=$(curl -s -X POST localhost:8000/api/repositories/analyze \
  -H "Content-Type: application/json" \
  -d '{"repository_url": "https://github.com/shepherdscientific/optimized-sssp"}')
echo $REPO_RESP

# 2. Extract repo_id and poll status
REPO_ID=$(echo $REPO_RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['repository_id'])")
curl localhost:8000/api/repositories/$REPO_ID/status

# 3. List all repos
curl localhost:8000/api/repositories

# 4. Get documentation
curl localhost:8000/api/repositories/$REPO_ID/docs

# 5. Search within repo
curl "localhost:8000/api/repositories/$REPO_ID/search?q=graph"
```

### 5.4 Global Search

```bash
curl -X POST localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "graph algorithm", "limit": 10}'
```

### 5.5 Error Handling

```bash
# Invalid URL — expect 422
curl -X POST localhost:8000/api/repositories/analyze \
  -H "Content-Type: application/json" \
  -d '{"repository_url": "not-a-url"}'

# Non-existent repo ID — expect 404
curl localhost:8000/api/repositories/fake-id-xyz/status

# Regenerate non-existent repo — expect 404
curl -X POST localhost:8000/api/repositories/fake-id-xyz/regenerate
```

### 5.6 Docker Mode

```bash
cp .env.example .env
docker-compose up -d
curl localhost:8000/health
docker-compose logs -f baddocs
docker-compose down
```

---

## 6. GitHub Action Plugin Tests

The BadDocs GitHub Action (`github-action/`) runs as a Node 20 action. It accepts `repository`, `provider`, and `output` inputs and sets a `status` output. Testing covers the action locally, via its embedded test workflow, and as a live integration in a target repository.

### 6.1 Unit Tests (Action Internal)

```bash
cd github-action
npm install
npm test
```

Expected: all action unit tests pass, no Node.js errors.

### 6.2 Build Validation

```bash
cd github-action
npm install
node dist/index.js   # smoke-run the bundled entry point

# Verify dist/index.js is current
npm run build 2>/dev/null || true
git diff --stat dist/   # should be empty if dist is committed and up to date
```

### 6.3 Action Input/Output Contract

Verify `action.yml` defines the correct interface:

| Input | Default | Test |
|-------|---------|------|
| `repository` | `.` (current repo) | Pass a GitHub URL; verify it appears in logs |
| `provider` | `anthropic` | Pass `ollama`, `deepseek`, `openai`; verify correct routing |
| `output` | `json` | Pass `json` and `markdown`; verify format differs |

**Output to verify:**
- `status` → `success` on clean run, `failure` on error with message

### 6.4 Local Testing with `act`

[act](https://github.com/nektos/act) runs GitHub Actions locally without pushing:

```bash
# Install (macOS)
brew install act

cd github-action

# Run the test workflow
act push -W .github/workflows/test.yml

# Run with specific inputs
act workflow_dispatch \
  -W .github/workflows/test.yml \
  --input repository=https://github.com/shepherdscientific/optimized-sssp \
  --input provider=anthropic
```

### 6.5 Live Integration — Install in a Test Repo

Create a test repository and add this workflow:

```yaml
# .github/workflows/baddocs.yml (in your test repo)
name: BadDocs Documentation
on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  document:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run BadDocs Analysis
        id: baddocs
        uses: shepherdscientific/baddocs-clean/github-action@main
        with:
          repository: ${{ github.repository }}
          provider: anthropic
          output: json
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      - name: Check output
        run: echo "Status was ${{ steps.baddocs.outputs.status }}"
```

**Test matrix for live integration:**

| Test | `provider` input | Trigger | Expected |
|------|-----------------|---------|----------|
| Default (cloud) | `anthropic` | `workflow_dispatch` | `status=success` |
| Budget cloud | `deepseek` | Push to main | Analysis runs, `status=success` |
| Local (self-hosted runner) | `ollama` | `workflow_dispatch` | Analysis uses Ollama |
| Invalid provider | `badprovider` | `workflow_dispatch` | `status=failure` with clear error |
| Missing API key | `anthropic` (no secret set) | `workflow_dispatch` | Fails with auth error, not crash |
| Large repo | `anthropic` | `workflow_dispatch` | Completes or times out gracefully |

### 6.6 Provider Switching via Action Input

For each available provider, trigger with `provider: <name>` and confirm the correct provider appears in the job logs and `status=success`:

```bash
# Test each via act
for PROVIDER in anthropic openai deepseek ollama; do
  echo "--- Testing provider: $PROVIDER ---"
  act workflow_dispatch --input provider=$PROVIDER -W .github/workflows/test.yml
done
```

### 6.7 CI Workflow Self-Test

The action ships its own test workflow at `github-action/.github/workflows/test.yml`. Verify it passes on every push and PR:

```bash
# Confirm via GitHub UI:
# Actions tab → Test workflow → all jobs green on latest commit
```

### 6.8 Webhook-Triggered Documentation (GitHub App)

Requires a configured GitHub App (see `GITHUB_APP_SETUP.md`).

```bash
# Forward webhooks to local server
npx smee-client \
  --url https://smee.io/<your-channel> \
  --target http://localhost:8000/api/github/webhook

# Push a commit to a connected repo and verify:
# 1. POST /api/github/webhook 200 in server logs
# 2. Incremental analysis triggers for changed files
# 3. New docs appear in search
```

**Webhook payload unit tests (automated):**
```bash
pytest tests/test_github_serialization.py -v
```

**Manual webhook edge cases:**

| Event | Expected behaviour |
|-------|--------------------|
| `push` to main | Incremental analysis of changed files only |
| `push` to feature branch | Analysis triggered only if configured |
| `pull_request` opened | Optional analysis + comment if configured |
| Malformed payload | 400 response, no crash |
| Invalid HMAC signature | 401 response, payload rejected |
| Duplicate delivery ID | Deduplicated, not re-processed |

---

## 7. Language Processor Tests

### 7.1 Automated

```bash
pytest tests/unit/test_processors.py -v
```

Covers Python, JavaScript, Java. Other languages are validated via the OSS matrix (Section 9).

### 7.2 Manual Spot-Check

| Language | Recommended Repo | Key Things to Verify |
|----------|-----------------|-----------------------|
| Python | `psf/requests` | Decorators, type hints, class methods |
| JavaScript | `expressjs/express` | CommonJS imports, middleware patterns |
| TypeScript | `microsoft/TypeScript` | Interfaces, generics, type aliases |
| Java | `google/guava` | Annotations, generics, checked exceptions |
| Go | `gin-gonic/gin` | Structs, interfaces, goroutines |
| Rust | `tokio-rs/tokio` | Traits, enums, lifetimes |
| PHP | `WordPress/WordPress` | Hooks, global functions, OOP classes |
| Ruby | `rails/rails` | Modules, mixins, DSL methods |
| C# | `dotnet/aspnetcore` | Async methods, interfaces, attributes |
| COBOL | Sample COBOL file | Divisions, sections, paragraphs |
| Fortran | Sample Fortran file | Subroutines, modules |
| R | `tidyverse/ggplot2` | S3/S4 classes, pipe operators |

For each: run `baddocs generate --repo <url>`, then confirm `baddocs status` shows > 0 files and `baddocs search <term>` returns results.

---

## 8. Self-Documentation Test

Use baddocs to document its own codebase — the most important integration smoke test.

```bash
baddocs init
baddocs generate --repo https://github.com/shepherdscientific/baddocs-clean
baddocs status --detailed

# Search for concepts that must appear in any reasonable documentation
baddocs search "language processor"
baddocs search "LLM provider"
baddocs search "storage"
baddocs search "incremental"
baddocs search "MCP server"
baddocs search "FastAPI"
```

**Pass criteria:**
- All `src/baddocs/` files processed without errors
- ≥ 5 distinct search terms return results
- Generated docs reference correct function and class names
- ≥ 80% of source files show as documented in `baddocs status`

---

## 9. OSS Project Test Matrix

| Repo | Language | Size | Priority | Why |
|------|----------|------|----------|-----|
| `pallets/flask` | Python | Small | High | Solid Python baseline |
| `expressjs/express` | JavaScript | Small | High | Node/CommonJS baseline |
| `gin-gonic/gin` | Go | Small | Medium | Go processor |
| `sinatra/sinatra` | Ruby | Small | Medium | Ruby processor |
| `tidyverse/ggplot2` | R | Small | Medium | R processor |
| `laravel/framework` | PHP | Large | Medium | PHP OOP patterns |
| `rails/rails` | Ruby | Large | Medium | Large Ruby codebase |
| `dotnet/aspnetcore` | C# | Large | Medium | C# async patterns |
| `WordPress/WordPress` | PHP | Very large | High | PHP + DB docs + hooks |

For each, after `baddocs generate --repo <url>`:
1. `baddocs status` shows > 0 files processed
2. 3–5 domain-relevant searches return results
3. No unhandled exceptions in logs

---

## 10. LLM Provider Testing

Both local and cloud providers must be tested before sign-off. Test them independently, then test the fallback chain between them.

### 10.1 Automated (Mock — No Key Needed)

```bash
pytest tests/unit/test_llm_providers.py -v
pytest tests/unit/test_llamacpp_provider.py -v
```

### 10.2 Test Each Provider Independently

```bash
uvicorn src.baddocs.web.main:app --port 8000

curl -X POST localhost:8000/test-provider/ollama
curl -X POST localhost:8000/test-provider/llamacpp
curl -X POST localhost:8000/test-provider/deepseek
curl -X POST localhost:8000/test-provider/openai
curl -X POST localhost:8000/test-provider/anthropic
```

Expected for a healthy provider: `{"status": "ok", "provider": "<name>", "latency_ms": <n>}`

### 10.3 Local — Ollama

```bash
curl http://localhost:11434/api/tags   # confirm model available

OLLAMA_URL=http://localhost:11434 \
  baddocs generate --repo https://github.com/shepherdscientific/optimized-sssp

# Verify logs: "Using provider: ollama"
```

### 10.4 Local — llama.cpp

```bash
curl http://localhost:8080/health   # confirm server running

LLAMACPP_URL=http://localhost:8080 \
  baddocs generate --repo https://github.com/shepherdscientific/optimized-sssp

# Verify logs: "Using provider: llamacpp"
```

### 10.5 Cloud Providers

Disable local providers to force a specific cloud path:

```bash
OLLAMA_URL="" LLAMACPP_URL="" DEEPSEEK_API_KEY=sk-... \
  baddocs generate --repo https://github.com/shepherdscientific/optimized-sssp

# Verify logs: "Using provider: deepseek"
# Verify: baddocs status shows cost_usd > 0
```

Repeat for each cloud provider you want to validate.

### 10.6 Fallback Chain Test

```bash
# 1. Ollama running + a cloud key set in .env
# 2. Stop Ollama
ollama stop

# 3. Run — should auto-fall back to cloud
baddocs generate --repo https://github.com/shepherdscientific/optimized-sssp
# Verify logs: "Provider ollama unavailable, falling back to ..."

# 4. Restart Ollama and re-run — should return to Ollama
ollama serve &
baddocs generate --repo https://github.com/shepherdscientific/optimized-sssp
# Verify logs: "Using provider: ollama"
```

### 10.7 Budget Enforcement

```bash
BADDOCS_MONTHLY_BUDGET=0.001 \
  baddocs generate --repo https://github.com/shepherdscientific/optimized-sssp

# Expected: budget warning logged, graceful stop, partial results in DB (no crash)
```

---

## 11. LLM Benchmarking

Run when evaluating models for production use, after hardware changes, or when comparing local vs cloud quality. Record all results in `QA/benchmark-results.md`.

### 11.1 What to Measure

| Metric | How |
|--------|-----|
| **Throughput** | Files documented per minute |
| **Latency** | Seconds per file (average and p95) |
| **Quality score** | Manual 1–5 review across 5 sampled docs |
| **Cost** | USD per 1000 files (cloud only) |
| **Context faithfulness** | Does the doc accurately describe what the code does? |

### 11.2 Benchmark Script

Use a fixed reference repo so results are comparable across runs:

```bash
BENCH_REPO="https://github.com/pallets/flask"   # ~300 Python files, stable

time baddocs generate --repo $BENCH_REPO --full

baddocs status --output-format json | python3 -c "
import sys, json
s = json.load(sys.stdin)
print(f'Files:       {s.get(\"total_files\")}')
print(f'Documented:  {s.get(\"documented_files\")}')
print(f'Coverage:    {s.get(\"coverage_percentage\")}%')
print(f'Cost:        \${s.get(\"cost_usd\", 0):.4f}')
"
```

### 11.3 Model Comparison Matrix

Fill in `QA/benchmark-results.md` after each run:

| Provider | Model | Hardware | Files/min | Avg latency | Quality (1–5) | Cost/1k files |
|----------|-------|----------|-----------|-------------|---------------|---------------|
| Ollama | qwen2.5-coder:7b | MacBook M2 | | | | Free |
| Ollama | qwen2.5-coder:7b | Linux i7 + 32GB | | | | Free |
| Ollama | deepseek-coder-v2:16b | MacBook M3 Max | | | | Free |
| llama.cpp | qwen2.5-coder-7b-q4 | MacBook M2 | | | | Free |
| llama.cpp | qwen2.5-coder-7b-q8 | Linux RTX 4090 | | | | Free |
| DeepSeek | deepseek-chat | API | | | | |
| OpenAI | gpt-4o-mini | API | | | | |
| OpenAI | gpt-4o | API | | | | |
| Anthropic | claude-haiku-4-5 | API | | | | |
| Anthropic | claude-sonnet-4-6 | API | | | | |

### 11.4 Capturing Hardware Context

```bash
# macOS
system_profiler SPHardwareDataType | grep -E "Chip|Memory|Cores"

# Linux
lscpu | grep -E "Model name|CPU\(s\)"
free -h | grep Mem
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "No GPU"
```

Key variables affecting local performance: Apple Silicon unified memory, GPU VRAM (models fitting entirely in VRAM run 5–10× faster), quantisation level (Q4 vs Q8 vs F16 trades quality for speed).

### 11.5 Quality Evaluation Protocol

After each benchmark run, manually review 5 generated docs from the Flask repo (one function, one class, one module, one route handler, one utility). Score each on accuracy, completeness, and readability (1–5). Record in `QA/benchmark-results.md`.

---

## 12. Incremental Analysis Tests

```bash
# Full first run
baddocs generate --repo https://github.com/shepherdscientific/optimized-sssp

# Second run — should skip all unchanged files
baddocs generate --repo https://github.com/shepherdscientific/optimized-sssp
# Expected logs: "0 files need reprocessing"

# Force full re-analysis
baddocs generate --repo https://github.com/shepherdscientific/optimized-sssp --full
```

---

## 13. Database Documentation Tests

```env
DATABASE_TYPE=postgresql
DATABASE_HOST=localhost
DATABASE_NAME=your_db
DATABASE_USER=user
DATABASE_PASSWORD=pass
```

```bash
baddocs generate --include-database
baddocs search "table schema"
baddocs search "foreign key"
```

---

## 14. GitHub App Integration Tests

Full setup in `GITHUB_APP_SETUP.md`. Requires a registered GitHub App.

### Private Repository Analysis

```bash
curl -X POST localhost:8000/api/repositories/analyze \
  -H "Content-Type: application/json" \
  -d '{"repository_url": "https://github.com/your-org/private-repo"}'
# Expected: analysis succeeds using GitHub App installation token
```

### Installation Endpoints

```bash
curl localhost:8000/github/installations
curl localhost:8000/github/debug/installations
```

### Token Rotation

Run a long analysis (100+ files) and verify in logs that the installation token refreshes automatically before its 1-hour expiry.

---

## 15. Performance Benchmarks

| Scenario | Acceptable Time |
|----------|----------------|
| Small repo (< 50 files) — first run | < 5 min |
| Medium repo (50–500 files) — first run | < 30 min |
| Large repo (500–5000 files) — first run | < 2 hrs |
| Incremental run, no changes | < 10 sec |
| FTS5 search query | < 500 ms |
| `/health` endpoint | < 100 ms |
| GitHub Action cold start | < 30 sec |

---

## 16. Common Issues & Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `No LLM provider available` | No key set, no local server running | Configure at least one provider in `.env` |
| `Failed to clone repository` | Git not in PATH, or private repo without App auth | `git --version`, configure GitHub App |
| `Processor not found for language` | Unrecognised file extension | Check `src/baddocs/core/file_discovery.py` |
| `FTS5 search returns nothing` | DB not initialised | Run `baddocs init` first |
| `Budget exceeded` | `BADDOCS_MONTHLY_BUDGET` too low | Raise limit or use a local provider |
| `MCP server not available` | `MCP_ENABLED=true` but no MCP server running | Set `MCP_ENABLED=false` for fallback mode |
| Docker: `port 8000 in use` | Port conflict | `PORT=8001 docker-compose up` |
| Action: `dist/index.js not found` | Build not committed | `npm run build` then commit `dist/` |
| Action: `status=failure` with no message | Uncaught JS exception | Check runner logs for stack trace |
| Webhook: `401 Unauthorized` | `GITHUB_WEBHOOK_SECRET` mismatch | Verify secret matches GitHub App settings |
| Webhook: duplicate processing | No delivery ID deduplication | Known gap — see backlog |

---

## 17. Sign-Off Checklist

**Automated tests**
- [ ] All unit tests pass (`pytest tests/unit/`)
- [ ] Integration tests pass (`pytest tests/integration/`)
- [ ] Coverage ≥ 50%

**CLI**
- [ ] `baddocs --version` returns correct version
- [ ] `baddocs init` creates `.baddocs/` directory
- [ ] `baddocs generate` + `baddocs search` work end to end

**API**
- [ ] `/health` returns `{"status":"healthy"}`
- [ ] Repository analysis → status poll → search flow works
- [ ] Docker `docker-compose up` starts cleanly

**GitHub Action**
- [ ] `npm test` passes in `github-action/`
- [ ] `dist/index.js` is current (no uncommitted build diff)
- [ ] Action runs successfully on a live test repo (at least one provider)
- [ ] `status=success` output confirmed
- [ ] Action fails cleanly on missing API key (no crash)
- [ ] Webhook serialisation test passes (`pytest tests/test_github_serialization.py`)
- [ ] At least one webhook delivery confirmed in logs

**LLM providers**
- [ ] At least one local provider tested end to end (Ollama or llama.cpp)
- [ ] At least one cloud provider tested end to end
- [ ] Fallback chain confirmed working (kill primary, secondary picks up)
- [ ] Budget enforcement triggers gracefully

**Benchmarks**
- [ ] Benchmark run recorded in `QA/benchmark-results.md` for local model
- [ ] Benchmark run recorded for at least one cloud provider
- [ ] Quality score ≥ 3.5/5 for chosen production model

**OSS projects**
- [ ] Self-documentation run completes without errors
- [ ] At least two OSS language tests pass (Flask + one other recommended)
- [ ] WordPress test passes or skip documented with reason

**Hygiene**
- [ ] `README.md` install instructions produce a working install
- [ ] `LICENSE` present and correct
- [ ] `.env.example` / `.env.schema` contain no real secrets

---

*Last updated: March 2026 | BadDocs v0.1.0-alpha*
