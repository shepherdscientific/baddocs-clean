# Gemini Autonomous Agent Instructions

You are an autonomous agent in a Ralph Loop. Every turn is a fresh start.

## 1. Context Initialization
Read these files immediately to understand your state (total reading budget: ~30k tokens):
- `prd.json`: Your task list and branch name.
- `scripts/ralph/AGENTS.md`: Codebase patterns (The "Brain").
- `scripts/ralph/progress.txt`: Read **only the `## Codebase Patterns` section** — do not read the full file (it grows unboundedly and wastes context).

## 2. Selection & Implementation
1. Identify the highest priority task in `prd.json` where `passes: false`.
2. Implement ONLY that task. Use patterns from `AGENTS.md`.
3. Run tests. If they fail, fix them until they pass.

## 3. The Commit Gate
Run `./scripts/ralph/aider-review.sh`. 
- **IF REVIEW PASSES:** Update `prd.json` using jq (never manually edit — use the safe jq command from `AGENTS.md`), **APPEND** to `progress.txt`, and run:
  `git add -A && git commit -m "feat: [Story ID] - Description"`
- **IF REVIEW FAILS:** You have ONE attempt to fix. If it still fails, document the blocker in `AGENTS.md` and exit.

If all stories are done, reply with <promise>COMPLETE</promise>.

## 4. Critical Constraints
- **Patch, don't rewrite**: Make surgical edits to all files — source code, config, and `AGENTS.md`. Never rewrite a whole file to make a small change. Use diff/patch primitives wherever possible.
- **jq only for `prd.json`**: Never manually edit or use sed/awk on `prd.json`. Always use the safe jq command from `AGENTS.md`.
- **AGENTS.md append-only**: Only ADD new bullet points or EDIT specific existing lines in-place. Never delete content — mark stale entries `[DEPRECATED]` inline instead.