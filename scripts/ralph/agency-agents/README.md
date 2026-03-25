# agency-agents

A curated subset of [msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents) — AI agent persona files for use with the Ralph autonomous loop.

## What's included

These agents were selected as broadly applicable to software development workflows. Categories not relevant to coding (marketing, sales, paid-media, academic, spatial-computing, strategy, support, game-development, etc.) and niche engineering agents were intentionally omitted.

### Engineering (16 agents)

- `engineering-software-architect` — System design, bounded contexts, ADRs
- `engineering-backend-architect` — Scalable APIs, database architecture, cloud infrastructure
- `engineering-frontend-developer` — React/Vue/Angular, Core Web Vitals, accessibility
- `engineering-senior-developer` — Premium full-stack, Laravel/Livewire, Three.js
- `engineering-ai-engineer` — ML models, RAG systems, production AI deployment
- `engineering-ai-data-remediation-engineer` — Air-gapped SLM data fixing, zero-loss pipelines
- `engineering-data-engineer` — ETL/ELT, lakehouse architecture, Spark, dbt
- `engineering-database-optimizer` — PostgreSQL, EXPLAIN ANALYZE, indexes, N+1 queries
- `engineering-devops-automator` — CI/CD, Infrastructure as Code, Kubernetes, monitoring
- `engineering-security-engineer` — Threat modeling, OWASP, secure code review, SAST/DAST
- `engineering-mobile-app-builder` — Native iOS/Android, React Native, Flutter
- `engineering-code-reviewer` — Correctness, security, maintainability, constructive feedback
- `engineering-rapid-prototyper` — MVP in days, Next.js, Supabase, validation frameworks
- `engineering-autonomous-optimization-architect` — LLM routing, circuit breakers, AI FinOps
- `engineering-sre` — SLOs, error budgets, observability, chaos engineering
- `engineering-technical-writer` — Developer docs, API references, README files, tutorials

**Skipped from engineering/** (niche/irrelevant to most coding workflows):
- `engineering-feishu-integration-developer` (Feishu-specific)
- `engineering-wechat-mini-program-developer` (WeChat-specific)
- `engineering-solidity-smart-contract-engineer` (blockchain)
- `engineering-embedded-firmware-engineer` (embedded hardware)
- `engineering-git-workflow-master` (too narrow)
- `engineering-incident-response-commander` (ops incident response)
- `engineering-threat-detection-engineer` (specialized security ops)

### Testing (8 agents)

- `testing-accessibility-auditor` — WCAG 2.2 AA, screen reader testing, ARIA patterns
- `testing-api-tester` — Functional, performance, security API validation
- `testing-evidence-collector` — Screenshot-based QA, visual proof, fantasy-allergic
- `testing-performance-benchmarker` — Load testing, Core Web Vitals, k6, capacity planning
- `testing-reality-checker` — Integration testing, production readiness, evidence-based certification
- `testing-test-results-analyzer` — Statistical analysis, defect prediction, release readiness
- `testing-tool-evaluator` — Technology assessment, TCO/ROI analysis, vendor selection
- `testing-workflow-optimizer` — Process improvement, Lean/Six Sigma, automation strategy

### Product (1 agent)

- `product-manager` — PRDs, roadmaps, OKRs, GTM planning, stakeholder alignment

### Design (2 agents)

- `design-ui-designer` — Design systems, component libraries, WCAG-compliant visual design
- `design-ux-architect` — CSS architecture, layout frameworks, developer-ready foundations

## Usage

Reference agents by their filename (without `.md`) in `prd.json`:

```json
{
  "agents": ["engineering-backend-architect"],
  "userStories": [
    {
      "id": "US-001",
      "agents": ["engineering-frontend-developer"],
      "title": "..."
    }
  ]
}
```

Resolution order: `story.agents` → `prd.agents` → no persona (zero regression).

Multiple agents can be listed per story — their content is concatenated in order before the base instruction file.

## Attribution

Agent files sourced and curated from [msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents). All credit for the original agent definitions goes to [@msitarzewski](https://github.com/msitarzewski) and contributors.