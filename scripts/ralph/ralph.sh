#!/bin/bash
# Ralph Wiggum - Autonomous AI agent loop
# Usage: ./ralph.sh [--tool amp|claude|opencode|gemini|codex] [max_iterations]
#
# Agent persona support:
#   Add "agents" to prd.json at the PRD level (default for all stories) and/or
#   at the story level (overrides the default for that iteration).
#   Agent files are loaded from an agency-agents/ directory — checked first as
#   a sibling of this script's directory, then as a subdirectory within it.
#   Agent names must match filenames in agency-agents/ (without the .md extension).
#   Example: "agents": ["engineering-software-architect"]
#            → loads agency-agents/engineering/engineering-software-architect.md

set -e

TOOL="amp"        # Default tool
MAX_ITERATIONS=10
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRD_FILE="$SCRIPT_DIR/prd.json"
PROGRESS_FILE="$SCRIPT_DIR/progress.txt"
ARCHIVE_DIR="$SCRIPT_DIR/archive"
LAST_BRANCH_FILE="$SCRIPT_DIR/.last-branch"

# ---------------------------------------------------------------------------
# Locate agency-agents directory
# Priority: sibling directory first, then subdirectory of SCRIPT_DIR
# ---------------------------------------------------------------------------
AGENT_DIR=""
for _candidate in "$SCRIPT_DIR/../agency-agents" "$SCRIPT_DIR/agency-agents"; do
  if [ -d "$_candidate" ]; then
    AGENT_DIR="$(cd "$_candidate" && pwd)"
    break
  fi
done

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case $1 in
    --tool)
      TOOL="$2"
      shift 2
      ;;
    --tool=*)
      TOOL="${1#*=}"
      shift
      ;;
    *)
      if [[ "$1" =~ ^[0-9]+$ ]]; then
        MAX_ITERATIONS="$1"
      fi
      shift
      ;;
  esac
done

# Validate tool
VALID_TOOLS="amp claude opencode gemini codex"
if ! echo "$VALID_TOOLS" | grep -qw "$TOOL"; then
  echo "Error: Invalid tool '$TOOL'. Must be one of: $VALID_TOOLS"
  exit 1
fi

# ---------------------------------------------------------------------------
# Archive previous run if branch changed
# ---------------------------------------------------------------------------
if [ -f "$PRD_FILE" ] && [ -f "$LAST_BRANCH_FILE" ]; then
  CURRENT_BRANCH=$(jq -r '.branchName // empty' "$PRD_FILE" 2>/dev/null || echo "")
  LAST_BRANCH=$(cat "$LAST_BRANCH_FILE" 2>/dev/null || echo "")

  if [ -n "$CURRENT_BRANCH" ] && [ -n "$LAST_BRANCH" ] && [ "$CURRENT_BRANCH" != "$LAST_BRANCH" ]; then
    DATE=$(date +%Y-%m-%d)
    FOLDER_NAME=$(echo "$LAST_BRANCH" | sed 's|^ralph/||')
    ARCHIVE_FOLDER="$ARCHIVE_DIR/$DATE-$FOLDER_NAME"
    echo "Archiving previous run: $LAST_BRANCH"
    mkdir -p "$ARCHIVE_FOLDER"
    [ -f "$PRD_FILE" ] && cp "$PRD_FILE" "$ARCHIVE_FOLDER/"
    [ -f "$PROGRESS_FILE" ] && cp "$PROGRESS_FILE" "$ARCHIVE_FOLDER/"
    echo "   Archived to: $ARCHIVE_FOLDER"

    echo "# Ralph Progress Log" > "$PROGRESS_FILE"
    echo "Started: $(date)" >> "$PROGRESS_FILE"
    echo "---" >> "$PROGRESS_FILE"
  fi
fi

# Track current branch
if [ -f "$PRD_FILE" ]; then
  CURRENT_BRANCH=$(jq -r '.branchName // empty' "$PRD_FILE" 2>/dev/null || echo "")
  [ -n "$CURRENT_BRANCH" ] && echo "$CURRENT_BRANCH" > "$LAST_BRANCH_FILE"
fi

# Initialize progress file
if [ ! -f "$PROGRESS_FILE" ]; then
  echo "# Ralph Progress Log" > "$PROGRESS_FILE"
  echo "Started: $(date)" >> "$PROGRESS_FILE"
  echo "---" >> "$PROGRESS_FILE"
fi

echo "🚀 Starting Ralph — Tool: $TOOL — Max iterations: $MAX_ITERATIONS"
if [ -n "$AGENT_DIR" ]; then
  echo "   Agent directory: $AGENT_DIR"
else
  echo "   No agency-agents/ directory found — persona injection disabled"
fi

# ---------------------------------------------------------------------------
# Helper: check prd.json for incomplete stories
# ---------------------------------------------------------------------------
prd_all_complete() {
  if [ ! -f "$PRD_FILE" ]; then return 1; fi
  local incomplete
  incomplete=$(jq '[.userStories[] | select(.passes != true)] | length' "$PRD_FILE" 2>/dev/null) || return 1
  [ "$incomplete" = "0" ]
}

# ---------------------------------------------------------------------------
# Helper: write agent persona prefix for the next incomplete story to a file.
#
# Resolution order: story.agents → prd.agents → empty (no persona, no change)
#
# $1 — output file path to write combined agent content into
# Logs loaded/missing agents to stderr so they surface in the terminal.
# Returns 0 if at least one agent was loaded, 1 if none.
# ---------------------------------------------------------------------------
write_agent_prefix() {
  local out_file="$1"
  : > "$out_file"   # truncate / create

  if [ ! -f "$PRD_FILE" ] || [ -z "$AGENT_DIR" ]; then
    return 1
  fi

  # Resolve agents: story-level overrides PRD-level
  local agents
  agents=$(jq -r '(
    ([ .userStories[] | select(.passes != true) ][0].agents // .agents // []) | .[]\n  ' "$PRD_FILE" 2>/dev/null) || agents=""

  if [ -z "$agents" ]; then
    return 1
  fi

  local loaded=0
  while IFS= read -r agent_name; do
    [ -z "$agent_name" ] && continue
    local agent_file
    agent_file=$(find "$AGENT_DIR" -name "${agent_name}.md" 2>/dev/null | head -1)
    if [ -f "$agent_file" ]; then
      cat "$agent_file" >> "$out_file"
      printf '\n\n---\n\n' >> "$out_file"
      echo "  🎭 Agent loaded: $agent_name" >&2
      loaded=$((loaded + 1))
    else
      echo "  ⚠️  Warning: agent '${agent_name}' not found in $AGENT_DIR" >&2
    fi
  done <<< "$agents"

  [ "$loaded" -gt 0 ] && return 0 || return 1
}

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
for i in $(seq 1 $MAX_ITERATIONS); do
  echo ""
  echo "==============================================================="
  echo "  Ralph Iteration $i of $MAX_ITERATIONS ($TOOL)"
  echo "==============================================================="

  # Early exit: all stories already marked complete before this iteration
  if prd_all_complete; then
    echo ""
    echo "✅ All PRD stories already complete — skipping iteration $i"
    exit 0
  fi

  # -------------------------------------------------------------------------
  # Resolve agent personas for this iteration's story
  # -------------------------------------------------------------------------
  AGENT_PREFIX_FILE=$(mktemp)
  write_agent_prefix "$AGENT_PREFIX_FILE" || true   # failure = no agents, that's fine

  # -------------------------------------------------------------------------
  # Build the combined prompt (agent prefix + base instruction file)
  # -------------------------------------------------------------------------
  TMPPROMPT=$(mktemp)
  TMPOUT=$(mktemp)

  # -------------------------------------------------------------------------
  # Determine whether we can stream output live via /dev/tty.
  # /dev/tty is the controlling terminal — works on Linux and macOS.
  # Falls back to captured-then-printed output (e.g. CI with no tty).
  # This fixes the "STDOUT stuck on iteration 1" problem: previously, all
  # output was buffered silently inside $(...) until the command finished.
  # -------------------------------------------------------------------------
  STREAM_LIVE=false
  [ -w /dev/tty ] && STREAM_LIVE=true

  # -------------------------------------------------------------------------
  # Run the AI tool
  # -------------------------------------------------------------------------
  case "$TOOL" in

    "amp")
      cat "$AGENT_PREFIX_FILE" "$SCRIPT_DIR/prompt.md" > "$TMPPROMPT"
      if $STREAM_LIVE; then
        cat "$TMPPROMPT" | amp --dangerously-allow-all 2>&1 | tee /dev/tty > "$TMPOUT" || true
      else
        cat "$TMPPROMPT" | amp --dangerously-allow-all > "$TMPOUT" 2>&1 || true
      fi
      ;;

    "claude")
      # NOTE: Claude Code requires the prompt as a string argument, NOT via
      # stdin. Newer versions misparse stdin as structured tool input (ZodError).
      cat "$AGENT_PREFIX_FILE" "$SCRIPT_DIR/CLAUDE.md" > "$TMPPROMPT"
      if $STREAM_LIVE; then
        claude --dangerously-skip-permissions --print "$(cat "$TMPPROMPT")" 2>&1 | tee /dev/tty > "$TMPOUT" || true
      else
        claude --dangerously-skip-permissions --print "$(cat "$TMPPROMPT")" > "$TMPOUT" 2>&1 || true
      fi
      ;;

    "opencode")
      cat "$AGENT_PREFIX_FILE" "$SCRIPT_DIR/OPENCODE.md" > "$TMPPROMPT"
      if $STREAM_LIVE; then
        opencode run "$(cat "$TMPPROMPT")" 2>&1 | tee /dev/tty > "$TMPOUT" || true
      else
        opencode run "$(cat "$TMPPROMPT")" > "$TMPOUT" 2>&1 || true
      fi
      ;;

    "gemini")
      cat "$AGENT_PREFIX_FILE" "$SCRIPT_DIR/GEMINI.md" > "$TMPPROMPT"
      if $STREAM_LIVE; then
        gemini -p "$(cat "$TMPPROMPT")" 2>&1 | tee /dev/tty > "$TMPOUT" || true
      else
        gemini -p "$(cat "$TMPPROMPT")" > "$TMPOUT" 2>&1 || true
      fi
      ;;

    "codex")
      # aider reads instructions from a file; prepend agent content inline
      cat "$AGENT_PREFIX_FILE" "$SCRIPT_DIR/AIDER_CODEX.md" > "$TMPPROMPT"
      if $STREAM_LIVE; then
        aider --model gpt-4o --message-file "$TMPPROMPT" --yes --no-auto-commit 2>&1 | tee /dev/tty > "$TMPOUT" || true
      else
        aider --model gpt-4o --message-file "$TMPPROMPT" --yes --no-auto-commit > "$TMPOUT" 2>&1 || true
      fi
      ;;

  esac

  # Capture output for completion detection
  OUTPUT=$(cat "$TMPOUT")

  # Clean up temp files
  rm -f "$AGENT_PREFIX_FILE" "$TMPPROMPT" "$TMPOUT"

  # If not streamed live, print now
  if ! $STREAM_LIVE; then
    printf '%s\n' "$OUTPUT"
  fi

  # -------------------------------------------------------------------------
  # Completion detection
  # -------------------------------------------------------------------------

  # Primary: model emits <promise>COMPLETE</promise>
  if printf '%s\n' "$OUTPUT" | grep -q "<promise>COMPLETE</promise>"; then
    echo ""
    echo "✅ Ralph completed all tasks at iteration $i of $MAX_ITERATIONS"
    exit 0
  fi

  # Fallback: inspect prd.json directly.
  # Handles cases where the model finishes but doesn't emit the signal
  # (e.g. truncated output, JSON-wrapped response, or crash after writing).
  if prd_all_complete; then
    echo ""
    echo "✅ All PRD stories complete (verified via prd.json) at iteration $i"
    exit 0
  fi

  echo "Iteration $i complete. Continuing..."
  sleep 2
done

echo ""
echo "Ralph reached max iterations ($MAX_ITERATIONS) without completing all tasks."
echo "Check $PROGRESS_FILE for status. Remaining stories:"
jq '[.userStories[] | select(.passes != true) | {id, title}]' "$PRD_FILE" 2>/dev/null || true
exit 1