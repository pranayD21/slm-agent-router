const metricsNode = document.querySelector("#inbox-metrics");
const listNode = document.querySelector("#mail-list");
const detailNode = document.querySelector("#email-detail");
const filterNode = document.querySelector("#mail-filters");
const searchInput = document.querySelector("#mail-search");
const resetButton = document.querySelector("#reset-view");
const promptInput = document.querySelector("#inbox-prompt");
const promptChips = document.querySelector("#prompt-chips");
const runButton = document.querySelector("#run-inbox");
const composeButton = document.querySelector(".compose-button");
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
  archivedIds: new Set(),
  starredIds: new Set(),
  readState: new Map(),
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
  const active = state.emails.filter((email) => !isArchived(email));
  metricsNode.innerHTML = [
    metricTile("Inbox", active.length),
    metricTile("Unread", active.filter(isUnread).length),
    metricTile("Starred", state.starredIds.size),
    metricTile("Archived", state.archivedIds.size),
    metricTile("Due Today", active.filter((email) => String(email.deadline || "").includes("Today")).length),
  ].join("");
}

function metricTile(label, value) {
  return `<article><span>${escapeHtml(label)}</span><strong>${formatNumber(value)}</strong></article>`;
}

function renderFilters() {
  if (!filterNode) return;
  const filters = [
    ["all", "All"],
    ["starred", "Starred"],
    ["needs-response", "Needs reply"],
    ["critical", "Critical"],
    ["today", "Due today"],
    ["archived", "Archived"],
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
      const classes = [
        "mail-item",
        email.id === state.selectedEmailId ? "active" : "",
        isUnread(email) ? "unread" : "",
        isStarred(email) ? "starred" : "",
      ].filter(Boolean).join(" ");
      return `<button class="${classes}" type="button" data-email="${escapeHtml(email.id)}">
        <div class="mail-item-top">
          <b>${isStarred(email) ? "* " : ""}${escapeHtml(email.from_name)}</b>
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
  <div class="email-actions">
    <button type="button" data-mail-action="archive" data-email-id="${escapeHtml(email.id)}">${isArchived(email) ? "Move to inbox" : "Archive"}</button>
    <button type="button" data-mail-action="read" data-email-id="${escapeHtml(email.id)}">${isUnread(email) ? "Mark read" : "Mark unread"}</button>
    <button type="button" data-mail-action="star" data-email-id="${escapeHtml(email.id)}">${isStarred(email) ? "Unstar" : "Star"}</button>
    <button type="button" data-mail-action="reply" data-email-id="${escapeHtml(email.id)}">Reply with agents</button>
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
    summaryNode.innerHTML = `<span class="pill"><strong>Ready</strong> Ask the agents to search, summarize, draft, or triage this inbox.</span>`;
  }
  if (resultsNode) {
    resultsNode.innerHTML = `<div class="chat-empty">Ask something like "what did Nora say" or "draft replies to the 3 highest priority customer emails."</div>`;
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
  resultsNode.innerHTML = userPromptBubble(prompt) + ["cascade", "openai", "claude"].map((id) => loadingCard(id, "Working")).join("");
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
  total.textContent = `${formatDuration(run.elapsed_ms)} run`;
  const results = run.results || [];
  const summary = run.summary || {};
  summaryNode.innerHTML = [
    summaryPill("State", summary.state || "complete"),
    summaryPill("Matched", `${summary.matched_emails || 0} emails`),
    summaryPill("Tokens", formatNumber(summary.total_tokens || 0)),
    summaryPill("Cost", `$${formatMoney(summary.total_cost_usd || 0)}`),
    summary.providers_unavailable ? summaryPill("Offline", `${summary.providers_unavailable} provider${summary.providers_unavailable === 1 ? "" : "s"}`) : "",
  ].join("");
  resultsNode.innerHTML = userPromptBubble(run.prompt) + results.map((result) => resultCard(result)).join("");
  renderHistory();
}

function summaryPill(label, value) {
  return `<span class="pill"><strong>${escapeHtml(label)}</strong> ${escapeHtml(value)}</span>`;
}

function resultCard(result) {
  const completion = result.completion || { checks: [], state: result.status || "complete" };
  const work = result.work || {};
  return `<article class="inbox-agent-card" data-model="${escapeHtml(result.agent_id)}">
    <div class="agent-card-head">
      <div>
        <h2>${escapeHtml(result.label)}</h2>
        <p>${escapeHtml(result.provider || result.agent_id)} · ${escapeHtml(result.model)}</p>
      </div>
      <span class="status-chip ${escapeHtml(completion.state)}">${escapeHtml(statusLabel(completion.state))}</span>
    </div>
    <div class="result-metrics">
      <span><b>${escapeHtml(formatDuration(result.runtime_ms))}</b> Measured</span>
      <span><b>${formatNumber(result.tokens || 0)}</b> Tokens</span>
      <span><b>$${formatMoney(result.cost_usd || 0)}</b> Cost</span>
      <span><b>${formatPercent(result.confidence || 0)}</b> Confidence</span>
      <span><b>${formatNumber(work.messages_matched || 0)}</b> Emails</span>
      <span><b>${formatNumber(work.drafts_created || 0)}</b> Drafts</span>
    </div>
    <div class="completion-checks">
      ${completion.checks.map((check) => `<span class="${check.passed ? "passed" : "failed"}">${check.passed ? "OK" : "Review"} ${escapeHtml(check.label)}</span>`).join("")}
    </div>
    <div class="agent-answer">${formatAnswer(result.answer)}</div>
    <div class="selected-mail">
      <h3>Mail used</h3>
      ${result.selected_emails.map(selectedEmailRow).join("")}
    </div>
    ${renderOperations(result.operations)}
    ${renderDrafts(result.drafts)}
    <ol class="agent-trace">
      ${result.actions.map((action) => `<li><span class="route-chip ${escapeHtml(action.route)}">${escapeHtml(action.label)}</span><small>${escapeHtml(action.detail)}${routeEventMeta(action)}</small></li>`).join("")}
    </ol>
  </article>`;
}

function routeEventMeta(action) {
  const parts = [];
  if (Number.isFinite(Number(action.confidence)) && Number(action.confidence) > 0) {
    parts.push(`${formatPercent(action.confidence)} conf`);
  }
  if (Number(action.tokens) > 0) {
    parts.push(`${formatNumber(action.tokens)} tokens`);
  }
  if (Number(action.latency_ms) > 0) {
    parts.push(formatDuration(action.latency_ms));
  }
  if (Number(action.messages) > 0) {
    parts.push(`${formatNumber(action.messages)} msgs`);
  }
  return parts.length ? ` · ${parts.join(" · ")}` : "";
}

function selectedEmailRow(email) {
  return `<button type="button" class="selected-email-row" data-select-email="${escapeHtml(email.id)}">
    <b>${escapeHtml(email.from_name)}</b>
    <span>${escapeHtml(email.subject)}</span>
    <small>${escapeHtml(shorten(email.body || "", 120))}</small>
  </button>`;
}

function renderOperations(operations) {
  if (!operations || !operations.length) return "";
  return `<div class="agent-operations">
    <h3>Actions</h3>
    ${operations.map((operation) => `<button type="button" data-select-email="${escapeHtml(operation.email_id)}">
      <b>${escapeHtml(operation.label)}</b>
      <span>${escapeHtml(operation.reason)}</span>
    </button>`).join("")}
  </div>`;
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
      const summary = run.summary || {};
      return `<button class="history-item" type="button" data-history="${escapeHtml(run.prompt)}">
        <span>${escapeHtml(shorten(run.prompt, 92))}</span>
        <b>${escapeHtml(statusLabel(summary.state || "complete"))} · ${formatNumber(summary.matched_emails || 0)} emails</b>
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
      (state.filter === "starred" && isStarred(email)) ||
      (state.filter === "archived" && isArchived(email)) ||
      (state.filter === "needs-response" && email.needs_response) ||
      (state.filter === "critical" && email.urgency === "critical") ||
      (state.filter === "today" && String(email.deadline || "").includes("Today")) ||
      email.category.toLowerCase() === state.filter;
    const matchesArchiveState = state.filter === "archived" ? isArchived(email) : !isArchived(email);
    const haystack = `${email.from_name} ${email.from_email} ${email.subject} ${email.body} ${email.category} ${email.tags.join(" ")}`.toLowerCase();
    return matchesFilter && matchesArchiveState && (!query || haystack.includes(query));
  });
}

function userPromptBubble(prompt) {
  return `<article class="chat-prompt"><p>${escapeHtml(prompt)}</p></article>`;
}

function statusLabel(value) {
  return String(value || "complete").replaceAll("_", " ");
}

function formatAnswer(value) {
  return String(value || "")
    .split("\n")
    .filter(Boolean)
    .map((line) => `<p>${escapeHtml(line)}</p>`)
    .join("");
}

function formatDuration(value) {
  const ms = Number(value || 0);
  if (ms < 1) return `${ms.toFixed(2)}ms`;
  if (ms < 1000) return `${ms.toFixed(ms < 10 ? 1 : 0)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function isArchived(email) {
  return state.archivedIds.has(email.id);
}

function isStarred(email) {
  return state.starredIds.has(email.id);
}

function isUnread(email) {
  if (state.readState.has(email.id)) return state.readState.get(email.id);
  return Boolean(email.unread);
}

function handleMailAction(action, emailId) {
  const email = state.emails.find((item) => item.id === emailId);
  if (!email) return;
  if (action === "archive") {
    if (isArchived(email)) state.archivedIds.delete(email.id);
    else state.archivedIds.add(email.id);
    const emails = filteredEmails();
    if (!emails.some((item) => item.id === state.selectedEmailId)) {
      state.selectedEmailId = emails[0]?.id || state.emails.find((item) => !isArchived(item))?.id || email.id;
    }
  }
  if (action === "read") {
    state.readState.set(email.id, !isUnread(email));
  }
  if (action === "star") {
    if (isStarred(email)) state.starredIds.delete(email.id);
    else state.starredIds.add(email.id);
  }
  if (action === "reply") {
    promptInput.value = `Draft a reply to ${email.from_name} about "${email.subject}"`;
    promptInput.focus();
  }
  renderInbox();
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

function formatPercent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
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
composeButton.addEventListener("click", () => {
  const email = state.emails.find((item) => item.id === state.selectedEmailId);
  promptInput.value = email ? `Draft a reply to ${email.from_name} about "${email.subject}"` : "Draft a new email";
  promptInput.focus();
});
promptInput.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    runInboxAgents();
  }
});

document.addEventListener("click", (event) => {
  const actionButton = event.target.closest("[data-mail-action]");
  if (actionButton) {
    handleMailAction(actionButton.dataset.mailAction, actionButton.dataset.emailId);
    return;
  }
  const button = event.target.closest("[data-select-email]");
  if (!button) return;
  state.selectedEmailId = button.dataset.selectEmail;
  renderInbox();
  detailNode.scrollIntoView({ behavior: "smooth", block: "start" });
});

loadInbox();
