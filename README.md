# BadDocs

> AI-powered documentation generator for legacy and undocumented codebases.

BadDocs clones a GitHub repository, detects the language of every source file, runs a language-specific processor to extract structure, calls an LLM to generate documentation, and persists everything to a searchable SQLite database. It runs as a web service with a dashboard or as a CLI tool.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## ☁️ BadDocs Cloud

The fastest way to get started is **[BadDocs Cloud](https://baddocs.io)** — no setup, no API keys, no infrastructure.

- **Free tier**: 3 analyses/month, up to 30 files each
- **Pro ($29/mo)**: 500 files, private repos, API access, clean exports
- **Team ($79/mo)**: 2,000 files, unlimited analyses, 5 seats

[**→ Try BadDocs Cloud free**](https://baddocs.io/signup) · [See a live demo on WordPress](https://baddocs.io/demo)

Self-hosting? Keep reading.

---

## Features

- **13 language processors** — Python, JavaScript/TypeScript, Java, C#, Go, Ruby, Rust, PHP, COBOL, Fortran, VB6, PowerBuilder, R
- **Local-first LLM support** — llama.cpp (`llama-server`) and Ollama work out of the box with no API keys required
- **Cloud LLM fallback** — DeepSeek, Qwen, OpenAI, Anthropic with automatic cost-tier routing
- **Incremental analysis** — only re-processes files that changed since the last run
- **Full-text search** — FTS5 SQLite index over all generated documentation
- **CLI + web service** — use `baddocs generate` locally or deploy via Docker
- **GitHub App auth** — analyse private repositories without storing personal tokens

---

## Quick Start

### Local (CLI)

```bash
git clone https://github.com/shepherdscientific/baddocs
cd baddocs
pip install -e .

# Analyse a repo using local llama.cpp server (no API key needed)
export LLAMACPP_URL=http://localhost:8080
baddocs init
baddocs generate --repo https://github.com/shepherdscientific/optimized-sssp
baddocs search "graph algorithm"
```

### Docker (web service)

```bash
cp .env.example .env   # add at least one LLM provider key
docker-compose up -d
open http://localhost:8000
```

POST a repository URL to start analysis:

```bash
curl -X POST http://localhost:8000/api/repositories/analyze \
  -H "Content-Type: application/json" \
  -d '{"repository_url": "https://github.com/WordPress/WordPress"}'
```

---

## LLM Provider Priority

BadDocs picks providers in this order — the first healthy one wins:

| Priority | Provider | Cost | Notes |
|----------|----------|------|-------|
| 1st | **llama.cpp** | free | Fastest local option — set `LLAMACPP_URL` |
| 2nd | **Ollama** | free | Set `OLLAMA_URL` |
| 3rd | **DeepSeek / Qwen** | ~$0.14/1M tokens | Cheap API fallback |
| 4th | **OpenAI / Anthropic** | $0.30–$15/1M tokens | Premium fallback |

For fully local, private analysis: run `llama-server` or Ollama and set no API keys.

---

## CLI Reference

```bash
baddocs init              # create .baddocs/ config in current directory
baddocs generate          # analyse current repo (uses local LLM by default)
baddocs generate --repo <url>   # clone and analyse a remote repo
baddocs generate --full         # force re-analysis of all files
baddocs search <term>     # full-text search generated docs
baddocs status            # show analysis progress
baddocs export --format markdown --output docs/
```

---

## Configuration

```env
# LLM providers (any combination works — BadDocs routes automatically)
LLAMACPP_URL=http://localhost:8080      # llama.cpp llama-server
OLLAMA_URL=http://localhost:11434       # Ollama
DEEPSEEK_API_KEY=sk-...
QWEN_API_KEY=sk-...
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Budget control
BADDOCS_MVP_TIER=budget          # free | ultra_budget | budget | standard | full
BADDOCS_MONTHLY_BUDGET=20        # USD

# GitHub App (for private repos)
GITHUB_APP_ID=your-app-id
GITHUB_APP_PRIVATE_KEY=path/to/key.pem
```

See `.env.example` for the full reference.

---

## Deployment

```bash
# Railway
railway up

# Fly.io
fly deploy

# Docker
docker-compose up -d
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for platform-specific instructions.

---

## Architecture

```
GitHub repo
    │
    ▼
language detection
    │
    ▼
processors/          ← 13 language-specific extractors
    │
    ▼
mcp_servers/llm/     ← ModelRouter: llamacpp → ollama → deepseek → openai
    │
    ▼
storage/             ← SQLite + FTS5 (files, documents, relationships)
    │
    ▼
cli/ or web/main.py  ← baddocs CLI or FastAPI dashboard
```

---

## Development

```bash
pip install -e ".[dev]"
pytest tests/
mypy src/
ruff check src/
```

This project was built using the [Ralph autonomous agent loop](scripts/ralph/) with Qwen3-Coder running locally via llama.cpp.

---

## Supported Languages

Python · JavaScript · TypeScript · Java · C# · Go · Ruby · Rust · PHP · COBOL · Fortran · VB6 · PowerBuilder · R

---

## Enterprise & Consulting

Need to document a legacy COBOL, PowerBuilder, or VB6 system before a migration? [Hyphen Partners](https://hyphenpartners.io) offers documentation audits, migration planning, and fractional CTO services for African and international enterprises.

[**→ Book a consultation**](https://baddocs.io/services)

---

## License

MIT — see [LICENSE](LICENSE).
