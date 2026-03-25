#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Aider Review — provider-agnostic
#
# Environment variables (all optional):
#
#   SKIP_AIDER_REVIEW=1          Skip this step entirely (no warning)
#
#   AIDER_REVIEW_MODEL           Model for review, e.g.:
#                                  openai/qwen3-coder-next   (local, default)
#                                  gemini/gemini-2.5-pro
#                                  deepseek/deepseek-chat
#
#   AIDER_REVIEW_API_BASE        Override API base URL (OpenAI-compatible providers)
#                                  Defaults to LLM_API_BASE for local/deepseek
#   AIDER_REVIEW_API_KEY         Override API key
#                                  Defaults to LLM_API_KEY or provider env vars
#
# Provider auto-detection (when AIDER_REVIEW_MODEL is set):
#   gemini/*   → uses GEMINI_API_KEY (no base URL needed)
#   *          → uses AIDER_REVIEW_API_BASE + AIDER_REVIEW_API_KEY
#
# ---------------------------------------------------------------------------

# Skip entirely if requested
if [ "${SKIP_AIDER_REVIEW:-0}" = "1" ]; then
  echo "⏭️  SKIP_AIDER_REVIEW=1 — skipping aider review step"
  exit 0
fi

# Verify aider is installed
if ! command -v aider &> /dev/null; then
  echo "⚠️  Aider not found — skipping review."
  exit 0
fi

# --- Resolve model -------------------------------------------------------
REVIEW_MODEL="${AIDER_REVIEW_MODEL:-}"

if [ -z "$REVIEW_MODEL" ]; then
  # No explicit review model — fall back to local server (legacy behaviour)
  REVIEW_MODEL="openai/qwen3-coder-next"
  USE_LOCAL=1
else
  USE_LOCAL=0
fi

# --- Detect provider from model prefix -----------------------------------
PROVIDER="${REVIEW_MODEL%%/*}"   # e.g. "gemini", "deepseek", "openai"

# --- Build aider args based on provider ----------------------------------
AIDER_EXTRA_ARGS=()

if [ "${USE_LOCAL:-0}" = "1" ]; then
  # ── Local server (original behaviour) ──────────────────────────────────
  API_BASE="${AIDER_REVIEW_API_BASE:-${LLM_API_BASE:-http://localhost:8080/v1}}"
  API_KEY="${AIDER_REVIEW_API_KEY:-${LLM_API_KEY:-dummy}}"

  if ! curl -sf --max-time 5 "$API_BASE/models" > /dev/null; then
    echo -e "\033[33m⚠️  LLM server not responding at $API_BASE — skipping aider review\033[0m"
    echo "   Set AIDER_REVIEW_MODEL=gemini/gemini-2.5-pro (or deepseek/deepseek-chat) to use an API instead"
    echo "   Set SKIP_AIDER_REVIEW=1 to suppress this warning"
    exit 0
  fi

  AIDER_EXTRA_ARGS+=(--openai-api-base "$API_BASE" --openai-api-key "$API_KEY")

elif [ "$PROVIDER" = "gemini" ]; then
  # ── Gemini (native litellm support, no base URL needed) ─────────────────
  KEY="${AIDER_REVIEW_API_KEY:-${GEMINI_API_KEY:-}}"
  if [ -z "$KEY" ]; then
    echo "⚠️  AIDER_REVIEW_MODEL=gemini/* but GEMINI_API_KEY is not set — skipping review."
    exit 0
  fi
  # aider/litellm picks up GEMINI_API_KEY automatically; passing explicitly for clarity
  export GEMINI_API_KEY="$KEY"

else
  # ── OpenAI-compatible (DeepSeek, any other API) ──────────────────────────
  API_BASE="${AIDER_REVIEW_API_BASE:-${OPENAI_BASE_URL:-${LLM_API_BASE:-}}}"
  API_KEY="${AIDER_REVIEW_API_KEY:-${OPENAI_API_KEY:-${LLM_API_KEY:-dummy}}}"

  if [ -z "$API_BASE" ]; then
    echo "⚠️  AIDER_REVIEW_MODEL=$REVIEW_MODEL requires AIDER_REVIEW_API_BASE (or OPENAI_BASE_URL) — skipping review."
    exit 0
  fi

  AIDER_EXTRA_ARGS+=(--openai-api-base "$API_BASE" --openai-api-key "$API_KEY")
fi

# -------------------------------------------------------------------------
echo "🔍 Running Aider review  model=$REVIEW_MODEL"

REVIEW_OUTPUT=$(mktemp)
trap "rm -f $REVIEW_OUTPUT" EXIT

aider \
  --model "$REVIEW_MODEL" \
  "${AIDER_EXTRA_ARGS[@]}" \
  --yes \
  --no-auto-commit \
  --message "Analyze the current uncommitted changes.
1. If there are critical logic errors or PRD mismatches, output 'RESULT: FAIL' and list them.
2. If the code is sound, output 'RESULT: PASS'.
3. Always suggest one new pattern for AGENTS.md." | tee "$REVIEW_OUTPUT"

if grep -q "RESULT: FAIL" "$REVIEW_OUTPUT"; then
  echo "❌ Aider review failed — fix critical issues before committing."
  exit 1
fi

echo "✅ Aider review passed."
exit 0