const board = document.querySelector("#board");
const summary = document.querySelector("#summary");
const runButton = document.querySelector("#run");
const total = document.querySelector("#run-total");
const template = document.querySelector("#agent-template");
const modeTabs = Array.from(document.querySelectorAll(".mode-tab"));
const views = Array.from(document.querySelectorAll(".view"));
const gameworldCards = document.querySelector("#gameworld-cards");
const gameworldSource = document.querySelector("#gameworld-source");
const gameGrid = document.querySelector("#game-grid");
const traceLanes = document.querySelector("#trace-lanes");
const playbackTabs = document.querySelector("#playback-tabs");
const playbackStage = document.querySelector("#playback-stage");
const panels = new Map();
let eventSource = null;
let timers = new Map();
let runStartedAt = 0;
let totalTimer = null;
let serverConfig = {};
let playbackTimer = null;
let activePlayback = null;
let activePlaybackStep = 0;

const labels = {
  cascade: "SLM Cascade",
  openai: "OpenAI",
  claude: "Claude",
};

async function loadConfig() {
  const response = await fetch("/api/config");
  const config = await response.json();
  serverConfig = config;
  for (const [id, data] of Object.entries(config)) {
    if (id === "limits") continue;
    const model = document.querySelector(`#model-${id}`);
    if (model) model.textContent = data.model ? `(${data.model})` : "";
    const input = document.querySelector(`input[name="agent"][value="${id}"]`);
    if (input && id !== "cascade") {
      input.disabled = !data.enabled;
      input.checked = data.enabled;
      input.closest("label").title = data.enabled ? data.model : data.hint;
    }
  }
}

async function loadGameWorld() {
  const response = await fetch("/api/gameworld");
  const report = await response.json();
  renderGameWorld(report);
}

function initializeTabs() {
  modeTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.view;
      modeTabs.forEach((item) => item.classList.toggle("active", item === tab));
      views.forEach((view) => view.classList.toggle("active", view.id === target));
      total.textContent = target === "gameworld-view" ? "GameWorld" : "Idle";
    });
  });
}

function selectedAgents() {
  return Array.from(document.querySelectorAll('input[name="agent"]:checked'))
    .filter((input) => !input.disabled)
    .map((input) => input.value);
}

function createPanel(agentId) {
  const node = template.content.firstElementChild.cloneNode(true);
  node.dataset.agent = agentId;
  node.querySelector("h2").textContent = labels[agentId] || agentId;
  node.querySelector(".badge").textContent = "";
  node.querySelector(".model").textContent = "";
  board.appendChild(node);
  const panel = {
    node,
    status: node.querySelector(".status"),
    model: node.querySelector(".model"),
    timer: node.querySelector(".timer"),
    steps: node.querySelector(".steps"),
    badge: node.querySelector(".badge"),
    routing: node.querySelector(".routing-summary"),
    routeCounts: { slm: 0, llm: 0, safety: 0, unavailable: 0, unknown: 0 },
    viewport: node.querySelector(".viewport"),
    image: node.querySelector("img"),
    title: node.querySelector(".page-title"),
    url: node.querySelector(".url"),
    log: node.querySelector(".log"),
    answer: node.querySelector(".answer"),
    startedAt: Date.now(),
    finished: false,
  };
  panels.set(agentId, panel);
  timers.set(agentId, window.setInterval(() => tickPanel(agentId), 100));
  return panel;
}

function resetBoard(agents) {
  if (eventSource) eventSource.close();
  for (const timer of timers.values()) window.clearInterval(timer);
  timers = new Map();
  panels.clear();
  board.innerHTML = "";
  summary.innerHTML = "";
  agents.forEach(createPanel);
  runStartedAt = Date.now();
  if (totalTimer) window.clearInterval(totalTimer);
  totalTimer = window.setInterval(() => {
    total.textContent = `${((Date.now() - runStartedAt) / 1000).toFixed(1)}s`;
  }, 100);
}

function tickPanel(agentId) {
  const panel = panels.get(agentId);
  if (!panel || panel.finished) return;
  panel.timer.textContent = `${((Date.now() - panel.startedAt) / 1000).toFixed(1)}s`;
}

async function startRun() {
  const agents = selectedAgents();
  if (!agents.length) {
    summary.innerHTML = `<span class="pill"><strong>Select an agent</strong></span>`;
    return;
  }
  resetBoard(agents);
  runButton.disabled = true;
  runButton.textContent = "Running";
  const payload = {
    task: document.querySelector("#task").value,
    start_url: document.querySelector("#start-url").value,
    agents,
    provider_keys: {
      openai: document.querySelector("#openai-key").value,
      claude: document.querySelector("#anthropic-key").value,
    },
  };
  const response = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json();
    summary.innerHTML = `<span class="pill"><strong>Error</strong> ${escapeHtml(error.detail || response.statusText)}</span>`;
    finishRunButton();
    return;
  }
  const { run_id } = await response.json();
  eventSource = new EventSource(`/api/runs/${run_id}/events`);
  eventSource.onmessage = (message) => handleEvent(JSON.parse(message.data));
  eventSource.onerror = () => {
    summary.innerHTML = `<span class="pill"><strong>Stream interrupted</strong></span>`;
    finishRunButton();
  };
}

function handleEvent(event) {
  if (event.type === "agent_started") {
    const panel = panels.get(event.agent_id) || createPanel(event.agent_id);
    panel.status.textContent = "Running";
    panel.status.classList.add("running");
    panel.status.classList.remove("done", "blocked", "error");
    panel.model.textContent = event.model || "";
    panel.badge.textContent = event.badge || "";
    panel.startedAt = Date.now();
  }
  if (event.type === "screenshot") updateScreenshot(event);
  if (event.type === "plan") addPlan(event);
  if (event.type === "action") addAction(event);
  if (event.type === "observation") addObservation(event);
  if (event.type === "error") addError(event);
  if (event.type === "agent_finished") finishAgent(event);
  if (event.type === "run_finished") finishRun(event.results || []);
  if (event.type === "run_error") {
    summary.innerHTML = `<span class="pill"><strong>Error</strong> ${escapeHtml(event.message)}</span>`;
    finishRunButton();
  }
  if (event.type === "stream_closed" && eventSource) {
    eventSource.close();
  }
}

function updateScreenshot(event) {
  const panel = panels.get(event.agent_id);
  if (!panel) return;
  panel.image.src = event.image;
  panel.viewport.classList.add("has-image");
  panel.title.textContent = event.title || "Untitled";
  panel.url.textContent = event.url || "";
  if (event.url && event.url.startsWith("http")) panel.url.href = event.url;
}

function addPlan(event) {
  const panel = panels.get(event.agent_id);
  if (!panel) return;
  const item = document.createElement("li");
  const items = (event.items || []).map((part) => escapeHtml(part)).join(" ");
  const subtasks = (event.subtasks || []).map((part) => escapeHtml(part)).join(" → ");
  item.innerHTML = `<b>plan</b> ${items}<small>${escapeHtml(event.strategy || "")}${subtasks ? ` · ${subtasks}` : ""}</small>`;
  panel.log.appendChild(item);
  panel.log.scrollTop = panel.log.scrollHeight;
}

function addAction(event) {
  const panel = panels.get(event.agent_id);
  if (!panel) return;
  panel.steps.textContent = `${event.step} step${event.step === 1 ? "" : "s"}`;
  const action = event.action || {};
  const route = routeDetails(event);
  updateRouteCounters(panel, route.kind);
  const item = document.createElement("li");
  const target = action.target || action.selector || action.text || "";
  const latency = event.decision_latency_ms ?? event.llm_latency_ms;
  const detail = [event.reason, route.detail, latency === undefined ? "" : `${latency}ms`]
    .filter(Boolean)
    .join(" · ");
  item.classList.add(`route-${route.kind}`);
  item.innerHTML = `<span class="step-line"><span class="route-chip ${route.kind}">${escapeHtml(route.label)}</span><b>${escapeHtml(action.action || "action")}</b><span class="step-target">${escapeHtml(shorten(target, 80))}</span></span>
    <small>${escapeHtml(detail)}</small>`;
  panel.log.appendChild(item);
  panel.log.scrollTop = panel.log.scrollHeight;
}

function addObservation(event) {
  const panel = panels.get(event.agent_id);
  if (!panel) return;
  const item = document.createElement("li");
  item.innerHTML = `<b>observed</b> <small>${escapeHtml(event.message || "")}</small>`;
  panel.log.appendChild(item);
  panel.log.scrollTop = panel.log.scrollHeight;
}

function addError(event) {
  const panel = panels.get(event.agent_id);
  if (!panel) return;
  panel.status.textContent = "Error";
  panel.status.classList.add("error");
  panel.answer.textContent = event.message || "";
}

function finishAgent(event) {
  const panel = panels.get(event.agent_id);
  if (!panel) return;
  panel.finished = true;
  panel.timer.textContent = `${(event.elapsed_ms / 1000).toFixed(2)}s`;
  panel.steps.textContent = `${event.steps} step${event.steps === 1 ? "" : "s"}`;
  panel.status.textContent = event.status;
  panel.status.classList.remove("running");
  panel.status.classList.toggle("done", event.status === "completed");
  panel.status.classList.toggle("blocked", event.status === "blocked");
  panel.status.classList.toggle("error", event.status === "error");
  panel.answer.textContent = event.answer || "";
  const timer = timers.get(event.agent_id);
  if (timer) window.clearInterval(timer);
}

function finishRun(results) {
  const sorted = [...results].sort((a, b) => a.elapsed_ms - b.elapsed_ms);
  summary.innerHTML = sorted
    .map((result, index) => {
      const place = index === 0 ? "Fastest" : "Result";
      return `<span class="pill"><strong>${place}</strong> ${escapeHtml(result.label)} · ${(result.elapsed_ms / 1000).toFixed(2)}s · ${escapeHtml(result.status)}</span>`;
    })
    .join("");
  finishRunButton();
}

function finishRunButton() {
  runButton.disabled = false;
  runButton.textContent = "Run comparison";
  if (totalTimer) window.clearInterval(totalTimer);
}

function renderGameWorld(report) {
  const models = report.models || [];
  const games = report.games || [];
  const winner = models.find((model) => model.id === report.summary?.winner) || bestBy(models, "pass_rate");
  gameworldSource.textContent = `${report.mode === "demo" ? "Demo report" : "Imported report"} · ${report.summary?.games || games.length} games · ${report.summary?.tasks || 0} tasks`;
  gameworldCards.innerHTML = [
    metricCard("Leader", winner?.label || "n/a", `${formatPercent(winner?.pass_rate || 0)} pass rate`),
    metricCard("Best cost per win", cheapestModel(models)?.label || "n/a", `$${formatMoney(cheapestModel(models)?.cost_per_success_usd || 0)}`),
    metricCard("Fastest median", fastestModel(models)?.label || "n/a", `${formatNumber(fastestModel(models)?.median_time_s || 0)}s`),
    metricCard("Most local actions", "SLM Cascade", `${formatNumber(models.find((model) => model.id === "cascade")?.slm_actions || 0)} SLM actions`),
  ].join("");

  renderBarChart("#pass-chart", models, "pass_rate", { suffix: "%", scale: 100, higherIsBetter: true });
  renderBarChart("#time-chart", models, "median_time_s", { suffix: "s", higherIsBetter: false });
  renderBarChart("#cost-chart", models, "estimated_cost_usd", { prefix: "$", higherIsBetter: false });
  renderBarChart("#cost-success-chart", models, "cost_per_success_usd", { prefix: "$", higherIsBetter: false });
  renderPlaybackSelector(report.playbacks || [], models);
  renderGameGrid(games, models);
  renderTraceLanes(report.traces || [], models);
}

function metricCard(label, value, subtext) {
  return `<article class="scorecard"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(subtext)}</small></article>`;
}

function renderBarChart(selector, models, key, options = {}) {
  const node = document.querySelector(selector);
  if (!node) return;
  const values = models.map((model) => Number(model[key] || 0));
  const max = Math.max(...values, 0.001);
  node.innerHTML = models
    .map((model) => {
      const raw = Number(model[key] || 0);
      const width = Math.max(4, (raw / max) * 100);
      const display = formatChartValue(raw, options);
      return `<div class="bar-row" data-model="${escapeHtml(model.id)}">
        <div class="bar-label"><span>${escapeHtml(model.label)}</span><b>${escapeHtml(display)}</b></div>
        <div class="bar-track"><span style="width:${width.toFixed(2)}%"></span></div>
      </div>`;
    })
    .join("");
}

function renderGameGrid(games, models) {
  gameGrid.innerHTML = games
    .map((game) => {
      const rows = models
        .map((model) => {
          const score = Number(game.scores?.[model.id] || 0);
          const cost = Number(game.cost_usd?.[model.id] || 0);
          return `<div class="game-score" data-model="${escapeHtml(model.id)}">
            <span>${escapeHtml(model.label)}</span>
            <div class="mini-track"><i style="width:${Math.max(3, score * 100).toFixed(2)}%"></i></div>
            <b>${formatPercent(score)}</b>
            <small>$${formatMoney(cost)}</small>
          </div>`;
        })
        .join("");
      return `<article class="game-card">
        <div class="game-card-head">
          <div><h2>${escapeHtml(game.name)}</h2><p>${escapeHtml(game.task || "")}</p></div>
          <span>${escapeHtml(game.genre || "Game")}</span>
        </div>
        ${rows}
      </article>`;
    })
    .join("");
}

function renderTraceLanes(traces, models) {
  const maxEnd = Math.max(...traces.map((trace) => Number(trace.start || 0) + Number(trace.duration || 0)), 1);
  traceLanes.innerHTML = models
    .map((model) => {
      const items = traces
        .filter((trace) => trace.model === model.id)
        .map((trace) => {
          const left = (Number(trace.start || 0) / maxEnd) * 100;
          const width = Math.max(2, (Number(trace.duration || 0) / maxEnd) * 100);
          const kind = normalizeRouteKind(trace.kind || "llm");
          return `<span class="trace-segment ${kind}" style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%" title="${escapeHtml(trace.label || "")}">${escapeHtml(trace.label || "")}</span>`;
        })
        .join("");
      return `<div class="trace-lane">
        <div class="trace-label">${escapeHtml(model.label)}</div>
        <div class="trace-track">${items}</div>
      </div>`;
    })
    .join("");
}

function renderPlaybackSelector(playbacks, models) {
  if (!playbackTabs || !playbackStage) return;
  if (!playbacks.length) {
    if (playbackTimer) window.clearInterval(playbackTimer);
    playbackTabs.innerHTML = "";
    playbackStage.innerHTML = `<div class="playback-empty">No task playback traces loaded.</div>`;
    return;
  }
  if (!activePlayback || !playbacks.some((playback) => playback.id === activePlayback.id)) {
    activePlayback = playbacks[0];
  }
  playbackTabs.innerHTML = playbacks
    .map(
      (playback) => `<button class="playback-tab${playback.id === activePlayback.id ? " active" : ""}" type="button" role="tab" aria-selected="${playback.id === activePlayback.id ? "true" : "false"}" data-playback="${escapeHtml(playback.id)}">
        ${escapeHtml(playback.name || playback.id)}
      </button>`
    )
    .join("");
  playbackTabs.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      const playback = playbacks.find((item) => item.id === button.dataset.playback);
      if (playback) selectPlayback(playback, models);
    });
  });
  selectPlayback(activePlayback, models);
}

function selectPlayback(playback, models) {
  activePlayback = playback;
  activePlaybackStep = 0;
  playbackTabs?.querySelectorAll("button").forEach((button) => {
    const selected = button.dataset.playback === playback.id;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", selected ? "true" : "false");
  });
  renderPlaybackFrame(playback, models);
  startPlayback(models);
}

function startPlayback(models) {
  if (playbackTimer) window.clearInterval(playbackTimer);
  const frameCount = maxPlaybackFrames(activePlayback);
  if (frameCount <= 1) return;
  playbackTimer = window.setInterval(() => {
    activePlaybackStep = (activePlaybackStep + 1) % frameCount;
    renderPlaybackFrame(activePlayback, models);
  }, 1350);
}

function maxPlaybackFrames(playback) {
  return Math.max(
    ...Object.values(playback?.models || {}).map((model) => (Array.isArray(model.frames) ? model.frames.length : 0)),
    0
  );
}

function renderPlaybackFrame(playback, models) {
  if (!playbackStage || !playback) return;
  const modelRows = models.length
    ? models
    : Object.keys(playback.models || {}).map((id) => ({ id, label: labels[id] || id }));
  const frameCount = Math.max(maxPlaybackFrames(playback), 1);
  playbackStage.innerHTML = `
    <div class="playback-task">
      <div>
        <span>${escapeHtml(playback.genre || "Game")}</span>
        <h3>${escapeHtml(playback.name || "GameWorld task")}</h3>
        <p>${escapeHtml(playback.task || "")}</p>
      </div>
      <div class="playback-clock">Frame ${Math.min(activePlaybackStep + 1, frameCount)} / ${frameCount}</div>
    </div>
    <div class="playback-grid">
      ${modelRows
        .map((model) => renderPlaybackCard(playback, model, activePlaybackStep))
        .join("")}
    </div>
  `;
}

function renderPlaybackCard(playback, model, stepIndex) {
  const data = playback.models?.[model.id] || {};
  const frames = Array.isArray(data.frames) ? data.frames : [];
  const frame = frames[Math.min(stepIndex, Math.max(frames.length - 1, 0))] || {};
  const routeKind = playbackRouteKind(frame.route || (model.id === "cascade" ? "SLM" : "LLM"));
  const step = Number(frame.step || Math.min(stepIndex + 1, frames.length || 1));
  const progress = frames.length ? ((Math.min(stepIndex, frames.length - 1) + 1) / frames.length) * 100 : 0;
  const detail =
    playback.kind === "2048"
      ? `Score ${formatNumber(frame.score || 0)}`
      : `Inventory ${formatInventory(frame.inventory)}`;
  return `<article class="playback-card" data-model="${escapeHtml(model.id)}">
    <div class="playback-card-head">
      <div>
        <h3>${escapeHtml(model.label || labels[model.id] || model.id)}</h3>
        <p>${escapeHtml(data.outcome || "Task in progress")}</p>
      </div>
      <span>${formatNumber(data.time_s || 0)}s</span>
    </div>
    <div class="playback-visual">${renderPlaybackVisual(playback, frame)}</div>
    <div class="playback-action">
      <span class="route-chip ${routeKind}">${routeKind === "slm" ? "SLM" : "LLM"}</span>
      <b>Step ${step}</b>
      <span>${escapeHtml(frame.action || "observe")}</span>
    </div>
    <div class="playback-progress" aria-label="Playback progress"><i style="width:${progress.toFixed(2)}%"></i></div>
    <div class="playback-stats">
      <span>${escapeHtml(detail)}</span>
      <span>${formatNumber(data.tokens || 0)} tokens</span>
      <span>$${formatMoney(data.cost_usd || 0)}</span>
    </div>
  </article>`;
}

function renderPlaybackVisual(playback, frame) {
  if (playback.kind === "2048") return render2048Board(frame.grid || []);
  if (playback.kind === "minecraft") return renderMinecraftMap(playback, frame);
  return `<div class="playback-empty">No visual renderer for this task.</div>`;
}

function render2048Board(grid) {
  const cells = Array.isArray(grid) ? grid.flat().slice(0, 16) : [];
  while (cells.length < 16) cells.push(0);
  return `<div class="game-2048" aria-label="2048 board">
    ${cells
      .map((value) => {
        const number = Number(value || 0);
        return `<span class="tile ${tileClass(number)}">${number ? escapeHtml(number) : ""}</span>`;
      })
      .join("")}
  </div>`;
}

function renderMinecraftMap(playback, frame) {
  const rows = Array.isArray(frame.map) ? frame.map : [];
  const [agentX, agentY] = Array.isArray(frame.agent) ? frame.agent : [-1, -1];
  const width = Math.max(...rows.map((row) => String(row).length), 1);
  const legend = playback.legend || {};
  return `<div class="minecraft-map" style="--cols:${width}" aria-label="Minecraft sandbox map">
    ${rows
      .map((row, y) =>
        Array.from(String(row).padEnd(width, "."))
          .map((tile, x) => {
            const hasAgent = x === agentX && y === agentY;
            const label = hasAgent ? "agent" : legend[tile] || "tile";
            const text = hasAgent ? "A" : tile === "." ? "" : tile;
            return `<span class="mc-cell ${minecraftTileClass(tile)}${hasAgent ? " agent" : ""}" title="${escapeHtml(label)}">${escapeHtml(text)}</span>`;
          })
          .join("")
      )
      .join("")}
  </div>`;
}

function tileClass(value) {
  if (!value) return "tile-empty";
  if (value >= 512) return "tile-v512";
  if (value >= 256) return "tile-v256";
  if (value >= 128) return "tile-v128";
  return `tile-v${value}`;
}

function minecraftTileClass(value) {
  const classes = {
    ".": "grass",
    T: "tree",
    L: "log",
    C: "crafting",
    W: "water",
    P: "planks",
  };
  return classes[value] || "grass";
}

function playbackRouteKind(value) {
  const route = String(value || "").toLowerCase();
  if (route.includes("slm")) return "slm";
  if (route.includes("llm")) return "llm";
  return normalizeRouteKind(route);
}

function formatInventory(items) {
  return Array.isArray(items) && items.length ? items.join(", ") : "empty";
}

function bestBy(rows, key) {
  return [...rows].sort((a, b) => Number(b[key] || 0) - Number(a[key] || 0))[0];
}

function cheapestModel(rows) {
  return [...rows].sort((a, b) => Number(a.cost_per_success_usd || Infinity) - Number(b.cost_per_success_usd || Infinity))[0];
}

function fastestModel(rows) {
  return [...rows].sort((a, b) => Number(a.median_time_s || Infinity) - Number(b.median_time_s || Infinity))[0];
}

function formatChartValue(value, options) {
  if (options.prefix === "$") return `$${formatMoney(value)}`;
  if (options.suffix === "%") return formatPercent(value);
  if (options.suffix) return `${formatNumber(value)}${options.suffix}`;
  return formatNumber(value);
}

function formatPercent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function formatMoney(value) {
  const number = Number(value || 0);
  return number < 1 ? number.toFixed(3) : number.toFixed(2);
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function shorten(value, limit) {
  const text = String(value || "");
  return text.length > limit ? `${text.slice(0, limit - 1)}...` : text;
}

function routeDetails(event) {
  const rawKind = String(event.route_kind || "").toLowerCase();
  const rawRoute = String(event.routed_from || "");
  const kind = normalizeRouteKind(rawKind || inferRouteKind(event.agent_id, rawRoute));
  const label = event.route_label || defaultRouteLabel(kind, rawRoute);
  const reasons = Array.isArray(event.routing_reasons) ? event.routing_reasons : [];
  const detail = reasons.length
    ? `SLM declined: ${reasons.map(humanizeRouteReason).join(", ")}`
    : humanizeRouteSource(rawRoute);
  return { kind, label, detail };
}

function inferRouteKind(agentId, routedFrom) {
  const route = String(routedFrom || "").toLowerCase();
  if (route.startsWith("fallback")) return "llm";
  if (route === "browser-safety") return "safety";
  if (agentId === "openai" || agentId === "claude") return "llm";
  return route ? "slm" : "unknown";
}

function normalizeRouteKind(kind) {
  return ["slm", "llm", "safety", "unavailable"].includes(kind) ? kind : "unknown";
}

function defaultRouteLabel(kind, routedFrom) {
  if (kind === "slm") return routedFrom ? `SLM: ${routedFrom}` : "SLM";
  if (kind === "llm") return routedFrom && routedFrom.startsWith("fallback") ? "LLM fallback" : "LLM";
  if (kind === "safety") return "Safety rule";
  if (kind === "unavailable") return "Fallback unavailable";
  return "Unknown route";
}

function humanizeRouteSource(value) {
  const source = String(value || "");
  if (!source) return "";
  if (source === "browser-safety") return "local safety rule";
  if (source.startsWith("fallback after ")) {
    return `SLM declined: ${source.replace("fallback after ", "").split(", ").map(humanizeRouteReason).join(", ")}`;
  }
  return `selected by ${source}`;
}

function humanizeRouteReason(value) {
  const [source, reason] = String(value || "").split(":");
  const cleanReason = (reason || source || "fallback").replaceAll("_", " ");
  return reason ? `${source} ${cleanReason}` : cleanReason;
}

function updateRouteCounters(panel, kind) {
  const bucket = normalizeRouteKind(kind);
  panel.routeCounts[bucket] += 1;
  renderRouteSummary(panel);
}

function renderRouteSummary(panel) {
  const counts = panel.routeCounts;
  panel.routing.innerHTML = `
    <span class="route-count slm"><b>${counts.slm}</b> SLM</span>
    <span class="route-count llm"><b>${counts.llm}</b> LLM</span>
    ${counts.safety ? `<span class="route-count safety"><b>${counts.safety}</b> Safety</span>` : ""}
    ${counts.unavailable ? `<span class="route-count unavailable"><b>${counts.unavailable}</b> Unavailable</span>` : ""}
    ${counts.unknown ? `<span class="route-count unknown"><b>${counts.unknown}</b> Unknown</span>` : ""}
  `;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

initializeTabs();
runButton.addEventListener("click", startRun);
loadConfig();
loadGameWorld();
