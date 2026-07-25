const metricsNode = document.querySelector("#inbox-metrics");
const listNode = document.querySelector("#mail-list");
const detailNode = document.querySelector("#email-detail");
const filterNode = document.querySelector("#mail-filters");
const searchInput = document.querySelector("#mail-search");
const resetButton = document.querySelector("#reset-view");
const promptInput = document.querySelector("#inbox-prompt");
const promptChips = document.querySelector("#prompt-chips");
const runButton = document.querySelector("#run-inbox");
const composerStatus = document.querySelector("#composer-status");
const resultsNode = document.querySelector("#agent-results");
const summaryNode = document.querySelector("#run-summary");
const historyNode = document.querySelector("#run-history");
const total = document.querySelector("#run-total");
const mailCountNode = document.querySelector("#mail-count");

const agentLabels = {
  cascade: "SLM Cascade",
  openai: "OpenAI Agent",
  claude: "Claude Agent",
};

const state = {
  emails: [],
  stats: {},
  categories: [],
  suggestedPrompts: [],
  filter: "all",
  search: "",
  selectedEmailId: "",
  runs: [],
};

async function loadInbox() {
  const response = await fetch("/api/inbox");
  const data = await response.json();
  state.emails = data.emails || [];
  state.stats = data.stats || {};
  state.categories = data.categories || [];
  state.suggestedPrompts = data.suggested_prompts || [];
  state.selectedEmailId = state.emails[0]?.id || "";
  renderInbox();
  renderPromptChips();
  renderInitialResults();
}

function renderInbox() {
  renderMetrics();
  renderFilters();
  renderEmailList();
  renderEmailDetail();
  if (mailCountNode) mailCountNode.textContent = `${filteredEmails().length} of ${state.emails.length} messages`;
}

function renderMetrics() {
  if (!metricsNode) return;
  metricsNode.innerHTML = [
    metricTile("Total", state.stats.total || 0),
    metricTile("Unread", state.stats.unread || 0),
    metricTile("Needs Reply", state.stats.needs_response || 0),
    metricTile("Critical", state.stats.critical || 0),
    metricTile("Due Today", state.stats.today || 0),
  ].join("");
}

function metricTile(label, value) {
  return `<article><span>${escapeHtml(label)}</span><strong>${formatNumber(value)}</strong></article>`;
}

function renderFilters() {
  if (!filterNode) return;
  const filters = [
    ["all", "All"],
    ["needs-response", "Needs reply"],
    ["critical", "Critical"],
    ["today", "Due today"],
    ["customer", "Customer"],
    ["finance", "Finance"],
    ["legal", "Legal"],
  ];
  filterNode.innerHTML = filters
    .map(([id, label]) => `<button class="mail-filter${state.filter === id ? " active" : ""}" type="button" data-filter="${id}">${escapeHtml(label)}</button>`)
    .join("");
  filterNode.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      state.filter = button.dataset.filter;
      renderInbox();
    });
  });
}

function renderEmailList() {
  if (!listNode) return;
  const emails = filteredEmails();
  if (!emails.some((email) => email.id === state.selectedEmailId)) {
    state.selectedEmailId = emails[0]?.id || state.emails[0]?.id || "";
  }
  listNode.innerHTML = emails
    .map((email) => {
      return `<button class="mail-item${email.id === state.selectedEmailId ? " active" : ""}" type="button" data-email="${escapeHtml(email.id)}">
        <div class="mail-item-top">
          <b>${escapeHtml(email.from_name)}</b>
          <span>${escapeHtml(shortTime(email.received))}</span>
        </div>
        <strong>${escapeHtml(email.subject)}</strong>
        <p>${escapeHtml(shorten(email.body, 128))}</p>
        <div class="mail-badges">
          <span class="${priorityClass(email)}">${escapeHtml(email.urgency)}</span>
          ${email.needs_response ? "<span>reply</span>" : "<span>read</span>"}
          ${email.deadline ? `<span>${escapeHtml(email.deadline)}</span>` : ""}
        </div>
      </button>`;
    })
    .join("");
  listNode.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedEmailId = button.dataset.email;
      renderInbox();
    });
  });
}

function renderEmailDetail() {
  if (!detailNode) return;
  const email = state.emails.find((item) => item.id === state.selectedEmailId) || state.emails[0];
  if (!email) {
    detailNode.innerHTML = "";
    return;
  }
  detailNode.innerHTML = `<div class="email-detail-head">
    <div>
      <p class="eyebrow">${escapeHtml(email.category)} · ${escapeHtml(email.role)}</p>
      <h2>${escapeHtml(email.subject)}</h2>
      <p>${escapeHtml(email.from_name)} &lt;${escapeHtml(email.from_email)}&gt;</p>
    </div>
    <div class="email-priority ${priorityClass(email)}">${escapeHtml(email.urgency)} · ${formatNumber(email.priority)}</div>
  </div>
  <p class="email-body">${escapeHtml(email.body)}</p>
  <div class="email-meta-grid">
    <span><b>Deadline</b>${escapeHtml(email.deadline || "None")}</span>
    <span><b>Needs reply</b>${email.needs_response ? "Yes" : "No"}</span>
    <span><b>Expected action</b>${escapeHtml(email.expected_action)}</span>
  </div>
  <div class="email-tags">${email.tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div>`;
}

function renderPromptChips() {
  if (!promptChips) return;
  promptChips.innerHTML = state.suggestedPrompts
    .map((prompt) => `<button class="prompt-chip" type="button" data-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`)
    .join("");
  promptChips.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      promptInput.value = button.dataset.prompt;
      promptInput.focus();
    });
  });
}

function renderInitialResults() {
  if (summaryNode) {
    summaryNode.innerHTML = `<span class="pill"><strong>Ready</strong> Send a prompt to compare the three agents.</span>`;
  }
  if (resultsNode) {
    resultsNode.innerHTML = ["cascade", "openai", "claude"].map((id) => loadingCard(id, "Idle")).join("");
  }
  renderHistory();
}

async function runInboxAgents() {
  const prompt = promptInput.value.trim();
  if (!prompt) {
    composerStatus.textContent = "Prompt required";
    return;
  }
  runButton.disabled = true;
  runButton.textContent = "Running";
  composerStatus.textContent = "Agents reading inbox";
  total.textContent = "Running";
  summaryNode.innerHTML = `<span class="pill"><strong>Running</strong> ${escapeHtml(prompt)}</span>`;
  resultsNode.innerHTML = ["cascade", "openai", "claude"].map((id) => loadingCard(id, "Running")).join("");
  const startedAt = performance.now();
  try {
    const response = await fetch("/api/inbox/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || response.statusText);
    }
    const run = await response.json();
    run.client_elapsed_ms = Math.round(performance.now() - startedAt);
    state.runs.unshift(run);
    state.runs = state.runs.slice(0, 8);
    renderRun(run);
  } catch (error) {
    composerStatus.textContent = "Run failed";
    summaryNode.innerHTML = `<span class="pill"><strong>Error</strong> ${escapeHtml(error.message)}</span>`;
  } finally {
    runButton.disabled = false;
    runButton.textContent = "Run inbox agents";
  }
}

function renderRun(run) {
  composerStatus.textContent = "Complete";
  total.textContent = `${(run.elapsed_ms / 1000).toFixed(2)}s`;
  const results = run.results || [];
  const fastest = results.find((result) => result.agent_id === run.winner?.fastest);
  const cheapest = results.find((result) => result.agent_id === run.winner?.lowest_cost);
  const best = results.find((result) => result.agent_id === run.winner?.highest_effectiveness);
  summaryNode.innerHTML = [
    summaryPill("Fastest", fastest),
    summaryPill("Lowest cost", cheapest),
    summaryPill("Highest effectiveness", best, "effectiveness"),
    `<span class="pill"><strong>Evaluator target</strong> ${(run.truth || []).length} key emails</span>`,
  ].join("");
  resultsNode.innerHTML = results.map((result) => resultCard(result)).join("");
  renderHistory();
}

function summaryPill(label, result, mode = "time") {
  if (!result) return "";
  const value = mode === "effectiveness" ? `${result.effectiveness}%` : `${(result.runtime_ms / 1000).toFixed(2)}s`;
  return `<span class="pill"><strong>${escapeHtml(label)}</strong> ${escapeHtml(result.label)} · ${escapeHtml(value)}</span>`;
}

function resultCard(result) {
  return `<article class="inbox-agent-card" data-model="${escapeHtml(result.agent_id)}">
    <div class="agent-card-head">
      <div>
        <h2>${escapeHtml(result.label)}</h2>
        <p>${escapeHtml(result.model)}</p>
      </div>
      <span>${formatNumber(result.effectiveness)}%</span>
    </div>
    <div class="result-metrics">
      <span><b>${(result.runtime_ms / 1000).toFixed(2)}s</b> Runtime</span>
      <span><b>${formatNumber(result.tokens)}</b> Tokens</span>
      <span><b>$${formatMoney(result.cost_usd)}</b> Cost</span>
    </div>
    <div class="effectiveness-meter" aria-label="Effectiveness"><i style="width:${Math.max(3, result.effectiveness).toFixed(1)}%"></i></div>
    <pre class="agent-answer">${escapeHtml(result.answer)}</pre>
    <div class="selected-mail">
      <h3>Emails selected</h3>
      ${result.selected_emails.map(selectedEmailRow).join("")}
    </div>
    ${renderDrafts(result.drafts)}
    <ol class="agent-trace">
      ${result.actions.map((action) => `<li><span class="route-chip ${escapeHtml(action.route)}">${escapeHtml(action.label)}</span><small>${escapeHtml(action.detail)}</small></li>`).join("")}
    </ol>
  </article>`;
}

function selectedEmailRow(email) {
  return `<button type="button" class="selected-email-row" data-select-email="${escapeHtml(email.id)}">
    <b>${escapeHtml(email.from_name)}</b>
    <span>${escapeHtml(email.subject)}</span>
  </button>`;
}

function renderDrafts(drafts) {
  if (!drafts || !drafts.length) {
    return `<div class="drafts"><h3>Drafts</h3><p>No drafts requested for this prompt.</p></div>`;
  }
  return `<div class="drafts">
    <h3>Drafts</h3>
    ${drafts
      .map(
        (draft) => `<details>
          <summary>${escapeHtml(draft.subject)}</summary>
          <p><b>To:</b> ${escapeHtml(draft.to)}</p>
          <p>${escapeHtml(draft.body)}</p>
        </details>`
      )
      .join("")}
  </div>`;
}

function loadingCard(agentId, status) {
  return `<article class="inbox-agent-card loading" data-model="${escapeHtml(agentId)}">
    <div class="agent-card-head">
      <div>
        <h2>${escapeHtml(agentLabels[agentId])}</h2>
        <p>${escapeHtml(status)}</p>
      </div>
      <span>--</span>
    </div>
    <div class="agent-placeholder"></div>
    <div class="agent-placeholder short"></div>
    <div class="agent-placeholder"></div>
  </article>`;
}

function renderHistory() {
  if (!historyNode) return;
  if (!state.runs.length) {
    historyNode.innerHTML = `<p class="history-empty">No prompts run yet.</p>`;
    return;
  }
  historyNode.innerHTML = state.runs
    .map((run) => {
      const best = run.results.find((result) => result.agent_id === run.winner?.highest_effectiveness);
      return `<button class="history-item" type="button" data-history="${escapeHtml(run.prompt)}">
        <span>${escapeHtml(shorten(run.prompt, 92))}</span>
        <b>${escapeHtml(best?.label || "n/a")} · ${formatNumber(best?.effectiveness || 0)}%</b>
      </button>`;
    })
    .join("");
  historyNode.querySelectorAll("button").forEach((button, index) => {
    button.addEventListener("click", () => renderRun(state.runs[index]));
  });
}

function filteredEmails() {
  const query = state.search.toLowerCase();
  return state.emails.filter((email) => {
    const matchesFilter =
      state.filter === "all" ||
      (state.filter === "needs-response" && email.needs_response) ||
      (state.filter === "critical" && email.urgency === "critical") ||
      (state.filter === "today" && String(email.deadline || "").includes("Today")) ||
      email.category.toLowerCase() === state.filter;
    const haystack = `${email.from_name} ${email.from_email} ${email.subject} ${email.body} ${email.category} ${email.tags.join(" ")}`.toLowerCase();
    return matchesFilter && (!query || haystack.includes(query));
  });
}

function priorityClass(email) {
  if (email.urgency === "critical") return "critical";
  if (email.urgency === "high") return "high";
  if (email.urgency === "medium") return "medium";
  return "low";
}

function shortTime(value) {
  return String(value || "").split(" ")[1] || "";
}

function formatMoney(value) {
  const number = Number(value || 0);
  return number < 1 ? number.toFixed(4) : number.toFixed(2);
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 1 });
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

searchInput.addEventListener("input", () => {
  state.search = searchInput.value;
  renderInbox();
});

resetButton.addEventListener("click", () => {
  state.filter = "all";
  state.search = "";
  searchInput.value = "";
  state.selectedEmailId = state.emails[0]?.id || "";
  renderInbox();
});

runButton.addEventListener("click", runInboxAgents);
promptInput.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    runInboxAgents();
  }
});

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-select-email]");
  if (!button) return;
  state.selectedEmailId = button.dataset.selectEmail;
  renderInbox();
  detailNode.scrollIntoView({ behavior: "smooth", block: "start" });
});

loadInbox();
