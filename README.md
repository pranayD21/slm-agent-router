# slm-agent-router

`slm-agent-router` is a small-model-first agent-step router. A local model attempts planning, tool choice, tool arguments, repair, and final formatting first. The router escalates to a fallback model when confidence is low, JSON/schema validation fails, tool arguments are invalid, a verifier disagrees, or local retries are exhausted.

It ships with **SLM Mail**, a Gmail-modeled web UI: a synthetic executive inbox on the left, a reading pane in the middle, and an agent side panel (in the style of Gmail's Gemini panel) where one prompt runs the SLM cascade, OpenAI, and Claude side by side so you can compare answers, speed, and cost. The UI is fully responsive and works on phones.

## Quickstart (web UI)

Requires Python 3.10+.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[web]"
slm-router serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The inbox, search, labels, star/archive/read actions, and the agent panel all work immediately. For live agent answers, connect at least one model:

- **Local cascade (free):** `brew install ollama && brew services start ollama && ollama pull llama3.2:1b`
- **OpenAI / Claude:** export `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` before `slm-router serve`, or paste keys in the UI under Settings (held in memory, sent only with each run).

## Quickstart (CLI benchmark)

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
export OLLAMA_MODEL="llama3.2:1b"
export OLLAMA_BASE_URL="http://127.0.0.1:11434"
```

The OpenAI and Claude comparison agents use the same browser tool surface as the cascade agent, so the timing comparison measures the end-to-end browser task loop: model decision latency plus browser action latency.

## Inbox agent comparison

The inbox manager uses real model calls when the app runs:

- SLM Cascade first scores the local synthetic inbox, asks Ollama at `OLLAMA_BASE_URL` with `OLLAMA_MODEL` (default `llama3.2:1b`) for a compact plan and selected email ids, validates that plan, then either composes simple direct answers locally or sends only the selected emails to OpenAI/Claude for final synthesis. It retries the planning step with broader context only when the selected ids or confidence fail validation.
- OpenAI Agent calls the OpenAI Responses API with `OPENAI_API_KEY` and `OPENAI_MODEL` (default `gpt-5.6-sol`).
- Claude Agent calls the Anthropic Messages API with `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` (default `claude-sonnet-5`).

For a fully live local run:

```bash
brew install ollama
brew services start ollama
ollama pull llama3.2:1b

export OPENAI_API_KEY="..."
export ANTHROPIC_API_KEY="..."
export OLLAMA_MODEL="llama3.2:1b"

slm-router serve --host 127.0.0.1 --port 8000
```

If a provider is missing or offline, its card is marked unavailable instead of showing simulated output. The cascade trace shows the real route events, including local retrieval, Ollama planning, validator decisions, local compose, selected-context LLM synthesis, confidence, latency, message counts, and token counts.

## GameWorld benchmark dashboard

The web UI includes a GameWorld benchmark tab that graphically compares the SLM Cascade, OpenAI, and Claude agents across game-agent metrics:

- pass rate and average score
- median completion time
- total token cost and cost per successful task
- per-game score/cost tiles
- representative SLM-vs-LLM route timelines

By default, the dashboard ships with a normalized demo report so the visualization is usable immediately. To show real GameWorld results, write a report to `benchmark_runs/gameworld_results.json` or point the app at one:

```bash
export SLM_ROUTER_GAMEWORLD_RESULTS="/path/to/gameworld_results.json"
slm-router serve --host 127.0.0.1 --port 8000
```

The importer accepts either the dashboard-native shape with `models` and `games`, or flat run logs with fields such as `model`, `game`, `passed`, `score`, `elapsed_s`, `total_tokens`, and `estimated_cost_usd`.

### Cascade reliability tuning

The cascade keeps its speed edge by using local policy for cheap browser moves and escalating only when the local path looks risky:

- Fast local plan is emitted before actions, so the UI shows the intended route.
- Non-final navigation actions use a lower local confidence threshold for speed.
- Final answers use a higher threshold plus checks that reject premature finishes, search-result snippets, empty answers, and blocked pages.
- Search-result links are opened by direct URL when possible, avoiding slower and more fragile browser clicks.
- Source pages that already contain enough evidence are marked ready for synthesis, so the fallback LLM answers instead of browsing deeper.
- Failed clicks/fills are recorded as observations so the next step can recover instead of crashing the run.
- Generic search tasks use Brave Search first, then lighter alternate routes, avoiding Google/Bing unless the prompt explicitly names them.
- CAPTCHA, unusual-traffic, and bot-protection pages are detected. The runner switches route when possible and marks the run as `blocked` rather than pretending it succeeded.

The default cascade profile was selected from a 20-epoch tuning run across direct navigation, search, and synthesis tasks:

- `SLM_ROUTER_CONFIDENCE_THRESHOLD=0.52`
- `SLM_ROUTER_FINISH_CONFIDENCE_THRESHOLD=0.84`
- Winning profile: `100%` judged pass rate, `0.99` average judge score, `3.43s` median elapsed time, and `2,645` average action LLM tokens.

You can rerun the tuning suite locally:

```bash
python3 scripts/tune_cascade.py --epochs 20 --timeout 60 --output benchmark_runs/cascade_tuning_latest.json
```

## Public deployment

**Instant public URL (from your machine):** serve locally, then tunnel. Anyone — including phones — can use the app at the printed `https://….trycloudflare.com` URL with zero accounts:

```bash
slm-router serve --host 127.0.0.1 --port 8000
cloudflared tunnel --url http://127.0.0.1:8000
```

**Permanent hosting:** the browser benchmark needs a server that can run Playwright, so deploy the Docker image on a Docker-capable host. The repo includes ready configs for Fly.io (`fly.toml` — run `flyctl launch --copy-config --now`) and Render (`render.yaml`), or run it anywhere with Docker:

```bash
docker build -t slm-agent-router .
docker run -p 8000:8000 \
  -e OPENAI_API_KEY="..." \
  -e ANTHROPIC_API_KEY="..." \
  slm-agent-router
```

Hosted deployments have no local Ollama, so either set `OLLAMA_BASE_URL` to a reachable Ollama server or provide cloud keys (server-side, or let visitors paste their own in Settings). Without any model connected the mailbox UI still works fully; agent cards are marked "Not connected" instead of showing simulated output.

Public-use controls:

```bash
# Keep provider keys server-side. Set false if every visitor must paste their own key.
export SLM_ROUTER_ALLOW_SERVER_KEYS=true

# Cost and abuse controls.
export SLM_ROUTER_MAX_ACTIVE_RUNS=3
export SLM_ROUTER_RUNS_PER_HOUR=20
export SLM_ROUTER_AGENT_TIMEOUT_SECONDS=75
export SLM_ROUTER_CONFIDENCE_THRESHOLD=0.52
export SLM_ROUTER_FINISH_CONFIDENCE_THRESHOLD=0.84
```

Visitors can also paste OpenAI or Anthropic API keys in the UI for a single run. Those keys are sent only with that run request and are not written to disk by the app.

## Policy

The TOML policy controls local model name, fallback model name, max local retries, confidence threshold, schema strictness, and enabled escalation reasons.

## Metrics

Reports show percent handled locally, escalation rate, success rate, local retries, estimated cost, and latency. The MVP uses deterministic mock adapters so tests run without network or model downloads.

## Caveat

This project measures cost and latency tradeoffs. Do not claim quality preservation without running representative task suites on real local and cloud models.
