# slm-agent-router

`slm-agent-router` is a small-model-first agent-step router. A local model attempts planning, tool choice, tool arguments, repair, and final formatting first. The router escalates to a fallback model when confidence is low, JSON/schema validation fails, tool arguments are invalid, a verifier disagrees, or local retries are exhausted.

## Quickstart

```bash
python3 -m pip install -e .
slm-router run --suite examples/tasks.json --policy examples/policy.toml --output runs.jsonl
slm-router report runs.jsonl --output report.html
python3 -m unittest discover -s tests
```

## Browser agent benchmark

The project also includes a live side-by-side benchmark for web-navigation tasks. It launches one isolated Playwright browser per agent and streams screenshots, actions, timing, and final answers into a local web UI.

```bash
python3 -m pip install -e ".[web]"
python3 -m playwright install chromium

export OPENAI_API_KEY="..."
export ANTHROPIC_API_KEY="..."

# Optional model overrides. Defaults track the current frontier docs.
export OPENAI_MODEL="gpt-5.6-sol"
export ANTHROPIC_MODEL="claude-sonnet-5"

slm-router serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, enter a web-navigation prompt, choose agents, and run the comparison. The cascade agent always starts with a fast local heuristic policy, optionally adds an Ollama local model when `OLLAMA_MODEL` is set, and escalates to the configured cloud fallback when confidence is low or the local action is invalid.

```bash
# Optional local model stage for the cascade.
export OLLAMA_MODEL="llama3.1"
export OLLAMA_BASE_URL="http://127.0.0.1:11434"
```

The OpenAI and Claude comparison agents use the same browser tool surface as the cascade agent, so the timing comparison measures the end-to-end browser task loop: model decision latency plus browser action latency.

### Cascade reliability tuning

The cascade keeps its speed edge by using local policy for cheap browser moves and escalating only when the local path looks risky:

- Fast local plan is emitted before actions, so the UI shows the intended route.
- Non-final navigation actions use a lower local confidence threshold for speed.
- Final answers use a higher threshold plus checks that reject premature finishes, search-result snippets, empty answers, and blocked pages.
- Failed clicks/fills are recorded as observations so the next step can recover instead of crashing the run.
- Generic search tasks use Brave Search first, then lighter alternate routes, avoiding Google/Bing unless the prompt explicitly names them.
- CAPTCHA, unusual-traffic, and bot-protection pages are detected. The runner switches route when possible and marks the run as `blocked` rather than pretending it succeeded.

## Public deployment

The browser benchmark needs a server that can run Playwright. Deploy it on a Docker-capable host such as Fly.io, Render, Railway, or a VM:

```bash
docker build -t slm-agent-router .
docker run -p 8000:8000 \
  -e OPENAI_API_KEY="..." \
  -e ANTHROPIC_API_KEY="..." \
  slm-agent-router
```

Public-use controls:

```bash
# Keep provider keys server-side. Set false if every visitor must paste their own key.
export SLM_ROUTER_ALLOW_SERVER_KEYS=true

# Cost and abuse controls.
export SLM_ROUTER_MAX_ACTIVE_RUNS=3
export SLM_ROUTER_RUNS_PER_HOUR=20
export SLM_ROUTER_MAX_STEPS=15
```

Visitors can also paste OpenAI or Anthropic API keys in the UI for a single run. Those keys are sent only with that run request and are not written to disk by the app.

## Policy

The TOML policy controls local model name, fallback model name, max local retries, confidence threshold, schema strictness, and enabled escalation reasons.

## Metrics

Reports show percent handled locally, escalation rate, success rate, local retries, estimated cost, and latency. The MVP uses deterministic mock adapters so tests run without network or model downloads.

## Caveat

This project measures cost and latency tradeoffs. Do not claim quality preservation without running representative task suites on real local and cloud models.
