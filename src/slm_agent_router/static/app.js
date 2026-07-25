const board = document.querySelector("#board");
const summary = document.querySelector("#summary");
const runButton = document.querySelector("#run");
const total = document.querySelector("#run-total");
const template = document.querySelector("#agent-template");
const panels = new Map();
let eventSource = null;
let timers = new Map();
let runStartedAt = 0;
let totalTimer = null;
let serverConfig = {};

const labels = {
  cascade: "SLM Cascade",
  openai: "OpenAI",
  claude: "Claude",
};

async function loadConfig() {
  const response = await fetch("/api/config");
  const config = await response.json();
  serverConfig = config;
  if (config.limits && config.limits.max_steps) {
    const maxSteps = document.querySelector("#max-steps");
    maxSteps.max = config.limits.max_steps;
    maxSteps.value = Math.min(Number(maxSteps.value), config.limits.max_steps);
  }
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
    max_steps: Number(document.querySelector("#max-steps").value || 12),
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
  item.innerHTML = `<b>plan</b> ${items}<small>${escapeHtml(event.strategy || "")}</small>`;
  panel.log.appendChild(item);
  panel.log.scrollTop = panel.log.scrollHeight;
}

function addAction(event) {
  const panel = panels.get(event.agent_id);
  if (!panel) return;
  panel.steps.textContent = `${event.step} step${event.step === 1 ? "" : "s"}`;
  const action = event.action || {};
  const item = document.createElement("li");
  const target = action.target || action.selector || action.text || "";
  item.innerHTML = `<b>${escapeHtml(action.action || "action")}</b> ${escapeHtml(shorten(target, 80))}
    <small>${escapeHtml(event.reason || "")}${event.routed_from ? ` · ${escapeHtml(event.routed_from)}` : ""} · ${event.llm_latency_ms}ms</small>`;
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

function shorten(value, limit) {
  const text = String(value || "");
  return text.length > limit ? `${text.slice(0, limit - 1)}...` : text;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

runButton.addEventListener("click", startRun);
loadConfig();
