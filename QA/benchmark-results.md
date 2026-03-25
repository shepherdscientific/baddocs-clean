# BadDocs Benchmark Results

> **Instructions**: Copy this template for each benchmark run. Fill in all fields. Commit completed results to `QA/benchmark-results/YYYY-MM-DD-<tester>.md`.

---

## Run Metadata

| Field | Value |
|-------|-------|
| Date | |
| Tester | |
| BadDocs version / commit | |
| Target repository | |
| Target repo size (files / LOC) | |
| Target repo primary language | |

---

## Hardware Profile

| Field | Value |
|-------|-------|
| Machine | (e.g. MacBook Pro M3 Max, AWS c5.4xlarge) |
| CPU | |
| RAM | |
| GPU / NPU | (if applicable) |
| OS | |
| Python version | |
| Ollama version | (if local) |

---

## Provider Matrix

Run the same target repo through each provider you have access to. Record `N/A` for providers not tested.

### 1. Local Providers

#### Ollama

| Model | Params | Quantisation | Time (s) | Tokens/s | Cost ($) | Doc quality (1–5) | Notes |
|-------|--------|-------------|----------|----------|----------|-------------------|-------|
| | | | | | 0.00 | | |
| | | | | | 0.00 | | |

#### llama.cpp

| Model | Params | Quantisation | Time (s) | Tokens/s | Cost ($) | Doc quality (1–5) | Notes |
|-------|--------|-------------|----------|----------|----------|-------------------|-------|
| | | | | | 0.00 | | |

### 2. Cloud Providers

#### DeepSeek

| Model | Time (s) | Input tokens | Output tokens | Cost ($) | Doc quality (1–5) | Notes |
|-------|----------|-------------|--------------|----------|-------------------|-------|
| deepseek-chat | | | | | | |
| deepseek-reasoner | | | | | | |

#### Qwen

| Model | Time (s) | Input tokens | Output tokens | Cost ($) | Doc quality (1–5) | Notes |
|-------|----------|-------------|--------------|----------|-------------------|-------|
| | | | | | | |

#### OpenAI

| Model | Time (s) | Input tokens | Output tokens | Cost ($) | Doc quality (1–5) | Notes |
|-------|----------|-------------|--------------|----------|-------------------|-------|
| gpt-4o | | | | | | |
| gpt-4o-mini | | | | | | |

#### Anthropic

| Model | Time (s) | Input tokens | Output tokens | Cost ($) | Doc quality (1–5) | Notes |
|-------|----------|-------------|--------------|----------|-------------------|-------|
| claude-opus-4-6 | | | | | | |
| claude-sonnet-4-6 | | | | | | |
| claude-haiku-4-5-20251001 | | | | | | |

---

## Quality Evaluation

For each tested model, rate the generated documentation on the following rubric (1 = poor, 5 = excellent):

| Criterion | Weight | Description |
|-----------|--------|-------------|
| Accuracy | 30% | Descriptions match what the code actually does |
| Completeness | 25% | All public APIs / modules covered |
| Clarity | 20% | Readable by a developer unfamiliar with the codebase |
| Structure | 15% | Logical organisation, consistent formatting |
| Examples | 10% | Useful code examples included where relevant |

### Quality Scores

| Model | Accuracy | Completeness | Clarity | Structure | Examples | Weighted total |
|-------|----------|-------------|---------|-----------|----------|----------------|
| | /5 | /5 | /5 | /5 | /5 | /5 |
| | /5 | /5 | /5 | /5 | /5 | /5 |
| | /5 | /5 | /5 | /5 | /5 | /5 |

**Weighted total formula**: `(Accuracy×0.30) + (Completeness×0.25) + (Clarity×0.20) + (Structure×0.15) + (Examples×0.10)`

---

## Performance Summary

### Speed (tokens/second — local models only)

| Model | Hardware | Tokens/s | Relative to baseline |
|-------|----------|----------|----------------------|
| | | | 1.00× (baseline) |
| | | | |

### Cost Efficiency (cloud models only)

| Model | $/1k output tokens | Quality score | Quality-per-dollar index |
|-------|--------------------|---------------|--------------------------|
| | | | |

---

## Incremental Analysis Check

> Re-run against the same repo after making a minor code change (add/modify one function).

| Field | Value |
|-------|-------|
| Change description | |
| Files changed | |
| Provider used | |
| Full re-analysis time (s) | |
| Incremental analysis time (s) | |
| Speedup | |
| Quality delta | |

---

## Failure / Edge Cases Observed

| Issue | Provider / model | Severity (low/med/high) | Reproducible? | Notes |
|-------|-----------------|------------------------|---------------|-------|
| | | | | |

---

## Environment Snapshot

```
# Paste output of: baddocs --version && python --version && uname -a
```

```
# Paste active .env.schema tier / budget settings (no secrets):
BADDOCS_MVP_TIER=
BADDOCS_MONTHLY_BUDGET=
OLLAMA_URL=
```

---

## Sign-off

| Field | Value |
|-------|-------|
| Tester sign-off | |
| Date | |
| Recommendation | ☐ Pass  ☐ Pass with notes  ☐ Fail |
| Summary notes | |
