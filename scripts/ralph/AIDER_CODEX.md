# Aider Codex Instructions

You are the implementation engine.
1. Read `prd.json` to find the current `passes: false` story.
2. Implement the story using your file-editing tools.
3. Once implemented, run your internal tests.
4. Update `prd.json` and `progress.txt` within this same chat session.
5. **Crucial:** Because Aider handles file writes differently, do NOT use `--auto-commit`. You must manually execute:
   `/run git add -A`
   `/run git commit -m "feat: Completed story [ID]"`
6. If all PRD items are done, output <promise>COMPLETE</promise>.