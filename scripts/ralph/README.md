# Mr. Wiggum

![Ralph](ralph.webp)

Mr. Wiggum is a fork of [Ralph](https://github.com/snarktank/ralph) — an autonomous AI agent loop that runs AI coding tools ([Amp](https://ampcode.com) or [Claude Code](https://docs.anthropic.com/en/docs/claude-code)) repeatedly until all PRD items are complete. Each iteration is a fresh instance with clean context. Memory persists via git history, `progress.txt`, and `prd.json`.

**What this fork adds on top of Ralph:**
- **Aider code review gate** — after each implementation, [aider](https://aider.chat) reviews the diff using a local or remote LLM before committing. Critical issues must be fixed; the loop never commits code that fails review.
- **Local LLM support** — the review step works against any OpenAI-compatible server (llama.cpp, Ollama, LiteLLM, etc.) via `LLM_API_BASE`. No cloud dependency required for the review pass.
- **`SKIP_AIDER_REVIEW` env var** — opt out of the review step per-run without editing any files. Useful when iterating fast or when the local model server is offline.
- **Graceful server detection** — if the LLM server is unreachable (5s timeout), the review step skips automatically instead of blocking the loop indefinitely.

Based on [Geoffrey Huntley's Ralph pattern](https://ghuntley.com/ralph/).

---

## Prerequisites

- One of the following AI coding tools installed and authenticated:
  - [Amp CLI](https://ampcode.com) (default)
  - [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`npm install -g @anthropic-ai/claude-code`)
- [aider](https://aider.chat) installed (`pip install aider-chat`) — required for the review gate
- `jq` installed (`brew install jq` on macOS)
- A git repository for your project
- **For local LLM review:** a running OpenAI-compatible server (llama.cpp `llama-server`, Ollama, LiteLLM proxy, etc.)

---

## Setup

### Option 1: Copy to your project

```bash
mkdir -p scripts/ralph
cp /path/to/mr-wiggum/ralph.sh scripts/ralph/
cp /path/to/mr-wiggum/aider-review.sh scripts/ralph/
cp /path/to/mr-wiggum/AGENTS.md scripts/ralph/

# Copy the prompt template for your AI tool of choice:
cp /path/to/mr-wiggum/CLAUDE.md scripts/ralph/CLAUDE.md    # For Claude Code
# OR
cp /path/to/mr-wiggum/prompt.md scripts/ralph/prompt.md    # For Amp

chmod +x scripts/ralph/ralph.sh scripts/ralph/aider-review.sh
```

### Option 2: Install skills globally

```bash
# For Amp
cp -r skills/prd ~/.config/amp/skills/
cp -r skills/ralph ~/.config/amp/skills/

# For Claude Code
cp -r skills/prd ~/.claude/skills/
cp -r skills/ralph ~/.claude/skills/
```

---

## Aider Review Gate

After each story implementation, `aider-review.sh` runs aider against the current diff before committing. Controlled by environment variables:

| Variable | Default | Description |
|---|---|---|
| `SKIP_AIDER_REVIEW` | `0` | Set to `1` to skip entirely |
| `LLM_API_BASE` | `http://localhost:8080/v1` | OpenAI-compatible API base URL |
| `LLM_API_KEY` | `dummy` | API key (`dummy` works for local servers) |

```bash
# Run with local LLM review (default)
./scripts/ralph/ralph.sh --tool claude 10

# Skip review
SKIP_AIDER_REVIEW=1 ./scripts/ralph/ralph.sh --tool claude 10

# Point at a different server
LLM_API_BASE=http://192.168.8.100:8080/v1 ./scripts/ralph/ralph.sh --tool claude 10
```

If the server is unreachable, the review step skips with a warning rather than blocking the loop.

---

## Key Files

| File | Purpose |
|------|---------|---|
| `ralph.sh` | The bash loop that spawns fresh AI instances |
| `CLAUDE.md` | Prompt template for Claude Code |
| `prompt.md` | Prompt template for Amp |
| `aider-review.sh` | Aider-powered code review gate |
| `AGENTS.md` | Seed pattern library — copy to your project and customise |
| `prd.json.example` | Example PRD format |

---

## References

- [Original Ralph by Geoffrey Huntley](https://ghuntley.com/ralph/)
- [snarktank/ralph](https://github.com/snarktank/ralph) — upstream repo
- [aider](https://aider.chat)
- [Amp documentation](https://ampcode.com/manual)
- [Claude Code documentation](https://docs.anthropic.com/en/docs/claude-code)