# slm-agent-router

`slm-agent-router` is a small-model-first agent-step router. A local model attempts planning, tool choice, tool arguments, repair, and final formatting first. The router escalates to a fallback model when confidence is low, JSON/schema validation fails, tool arguments are invalid, a verifier disagrees, or local retries are exhausted.

## Quickstart

```bash
python -m pip install -e .
slm-router run --suite examples/tasks.json --policy examples/policy.toml --output runs.jsonl
slm-router report runs.jsonl --output report.html
python -m unittest discover -s tests
```

## Policy

The TOML policy controls local model name, fallback model name, max local retries, confidence threshold, schema strictness, and enabled escalation reasons.

## Metrics

Reports show percent handled locally, escalation rate, success rate, local retries, estimated cost, and latency. The MVP uses deterministic mock adapters so tests run without network or model downloads.

## Caveat

This project measures cost and latency tradeoffs. Do not claim quality preservation without running representative task suites on real local and cloud models.
