---
name: ralph
description: "Convert PRDs to prd.json format for the Ralph autonomous agent system. Use when you have an existing PRD and need to convert it to Ralph's JSON format. Triggers on: convert this prd, turn this into ralph format, create prd.json from this, ralph json."
user-invocable: true
---

# Ralph PRD Converter

Converts existing PRDs to the prd.json format that Ralph uses for autonomous execution.

---

## The Job

Take a PRD (markdown file or text) and convert it to `prd.json` in your ralph directory.

---

## Output Format

```json
{
  "project": "[Project Name]",
  "branchName": "ralph/[feature-name-kebab-case]",
  "description": "[Feature description from PRD title/intro]",
  "agents": ["engineering-backend-architect"],
  "userStories": [
    {
      "id": "US-001",
      "title": "[Story title]",
      "description": "As a [user], I want [feature] so that [benefit]",
      "agents": ["engineering-frontend-developer"],
      "acceptanceCriteria": [
        "Criterion 1",
        "Criterion 2",
        "Typecheck passes"
      ],
      "priority": 1,
      "passes": false,
      "notes": ""
    }
  ]
}
```

---

## Agent Personas

Ralph can inject an agent persona into the AI's context at the start of each iteration. This shapes how the model approaches each story — a backend architect will make different trade-offs than a frontend developer.

### How it works

Before each iteration, ralph resolves the agents for the next incomplete story and prepends their content to the instruction file. The CLAUDE.md / prompt.md stays unchanged; the persona is prepended, not mixed in.

### Resolution order

`story.agents` → `prd.agents` → no persona (current behaviour, no regression)

Story-level agents override the PRD-level default. If neither is set, the iteration runs without a persona — identical to the previous behaviour.

### Agent names

Agent names must exactly match the filename of an agent in the `agency-agents/` directory (without the `.md` extension). The lookup searches recursively across all subdirectories.

```
agency-agents/
  engineering/
    engineering-backend-architect.md    ← name: "engineering-backend-architect"
    engineering-frontend-developer.md   ← name: "engineering-frontend-developer"
    engineering-software-architect.md   ← name: "engineering-software-architect"
  design/
    design-ux-researcher.md             ← name: "design-ux-researcher"
  ...
```

### Multiple agents on one story

You can list more than one agent. Their content is concatenated (in order) and then the instruction file follows — so the instruction file overrides any conflicting behavioural instructions in the agents.

```json
"agents": ["engineering-ai-engineer", "engineering-ai-data-remediation-engineer"]
```

### Setting up agency-agents

The `agency-agents/` directory is included in this repo under `agency-agents/`. No extra setup required — ralph auto-detects it on startup.

Alternatively, clone the full agency-agents repo as a sibling of your mr-wiggum directory:

```
your-project/
  mr-wiggum/          ← ralph.sh lives here
  agency-agents/      ← cloned from github.com/msitarzewski/agency-agents
```

Ralph checks the sibling location first, then the subdirectory.

---

## Conversion Rules

1. **Each user story becomes one JSON entry**
2. **IDs**: Sequential (US-001, US-002, etc.)
3. **Priority**: Based on dependency order, then document order
4. **All stories**: `passes: false` and empty `notes`
5. **branchName**: Derive from feature name, kebab-case, prefixed with `ralph/`
6. **Always add**: "Typecheck passes" to every story's acceptance criteria
7. **agents (optional)**:
   - Set `"agents"` at the PRD level for a default persona that applies to all stories
   - Override on individual stories with a story-level `"agents"` array
   - Omit entirely if you don't need persona injection (no regression)
   - Names must match filenames in `agency-agents/` exactly (without `.md`)

---

## Story Size: The Number One Rule

**Each story must be completable in ONE Ralph iteration (one context window).**

Ralph spawns a fresh AI instance per iteration with no memory of previous work. If a story is too big, the LLM runs out of context before finishing and produces broken code.

### Right-sized stories:
- Add a database column and migration
- Add a UI component to an existing page
- Update a server action with new logic
- Add a filter dropdown to a list

### Too big (split these):
- "Build the entire dashboard" - Split into: schema, queries, UI components, filters
- "Add authentication" - Split into: schema, middleware, login UI, session handling
- "Refactor the API" - Split into one story per endpoint or pattern

**Rule of thumb:** If you cannot describe the change in 2-3 sentences, it is too big.