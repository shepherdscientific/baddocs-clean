# Python Agent Logic (Lean Mode)

## 1. Python Environment
- VirtualEnv: `.venv/bin/activate`
- Type Checking: `mypy .`
- Testing: `pytest`

## 2. Iteration Rules
1. Read `prd.json` & `AGENTS.md`.
2. Check `git log -n 10`.
3. Execute ONE task from `prd.json` (Priority-based).
4. Update `progress.txt` (Human Audit) & `prd.json` (State).
5. If tests fail: Fix or document blocker in `AGENTS.md` and EXIT.

## 3. Discovered Patterns (The "Brain")
- Alembic migrations require `alembic.ini` configuration file with `script_location = db/migrations` and `prepend_path = .`
- When running Alembic from `orchestrator/`, the env.py must add the repo root (parent of orchestrator/) to sys.path for imports
- Use `sa.Enum("value1", "value2", ..., name="typename")` in migration files instead of `sa.Enum("typename", name="typename")` to avoid duplicate enum creation
- PostgreSQL JSONB type must be imported from `sqlalchemy.dialects.postgresql` (not `sqlalchemy`) - use `from sqlalchemy.dialects.postgresql import JSONB`
- Alembic async migrations require `greenlet` library - install with `pip install greenlet`
- Alembic async migrations with asyncpg require `psycopg2-binary` - install with `pip install psycopg2-binary`

## 4. ⚠️ CRITICAL: Updating prd.json Safely

**NEVER manually edit prd.json or use sed/awk!** This creates duplicate keys.

**ALWAYS use jq to update prd.json:**

```bash
# Mark a story as complete (US-015)
jq '(.userStories[] | select(.id == "US-015") | .passes) = true' prd.json > /tmp/prd.json && mv /tmp/prd.json prd.json

# Mark a story as incomplete
jq '(.userStories[] | select(.id == "US-015") | .passes) = false' prd.json > /tmp/prd.json && mv /tmp/prd.json prd.json

# Update notes for a story
jq '(.userStories[] | select(.id == "US-015") | .notes) = "Implementation complete"' prd.json > /tmp/prd.json && mv /tmp/prd.json prd.json
```

**Validation: Check for duplicate keys before committing:**

```bash
# Run validation script
./validate-prd.sh

# Or manual check (should return empty)
python3 -c "import json; d=json.load(open('prd.json')); print('Duplicates found!' if any('passes' in str(s) and str(s).count('\"passes\"') > 1 for s in d['userStories']) else '')"
```

**If you find duplicate keys, run:**
```bash
./fix-prd-duplicates.sh
```

## 5. Aider Review (Mandatory Post-Implementation Gate)
- Run `./scripts/ralph/aider_review.sh` **after** implementation, **before** updating prd.json.
- Apply *all* critical fixes Aider suggests.
- If Aider reports a reusable pattern (e.g., anti-pattern), add it here.
- If Aider finds a blocker you cannot fix: document in this file and EXIT (no commit).