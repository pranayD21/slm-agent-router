/* SLM Mail — Gmail-modeled UI for the inbox agent comparison. */

const el = (id) => document.getElementById(id);

const nodes = {
  menuBtn: el("menu-btn"),
  sidebar: el("sidebar"),
  scrim: el("scrim"),
  navList: el("nav-list"),
  labelList: el("label-list"),
  composeBtn: el("compose-btn"),
  search: el("mail-search"),
  searchClear: el("search-clear"),
  refreshBtn: el("refresh-btn"),
  listTitle: el("list-title"),
  mailCount: el("mail-count"),
  mailList: el("mail-list"),
  readingPane: el("reading-pane"),
  emailDetail: el("email-detail"),
  aiPanel: el("ai-panel"),
  aiToggle: el("ai-toggle"),
  aiClose: el("ai-close"),
  aiBack: el("ai-back"),
  aiSubtitle: el("ai-subtitle"),
  chatScroll: el("chat-scroll"),
  chatThread: el("chat-thread"),
  suggestionRow: el("suggestion-row"),
  promptInput: el("prompt-input"),
  sendBtn: el("send-btn"),
  fab: el("fab"),
  snackbar: el("snackbar"),
  settingsBtn: el("settings-btn"),
  settingsDialog: el("settings-dialog"),
  settingsSave: el("settings-save"),
  keyOpenai: el("key-openai"),
  keyClaude: el("key-claude"),
  providerStatus: el("provider-status"),
};

const AGENT_META = {
  cascade: { name: "SLM Cascade", tagline: "Local-first" },
  openai: { name: "OpenAI", tagline: "Cloud" },
  claude: { name: "Claude", tagline: "Cloud" },
};

const AVATAR_COLORS = ["#1a73e8", "#d93025", "#188038", "#e37400", "#7c3aed", "#007b83", "#b80672", "#5f6368"];

const LABEL_COLORS = [
  ["#e8f0fe", "#1967d2"],
  ["#e6f4ea", "#188038"],
  ["#fef7e0", "#b06000"],
  ["#f3e8fd", "#7627bb"],
  ["#fce8e6", "#c5221f"],
  ["#e4f7fb", "#007b83"],
  ["#fde7f3", "#b80672"],
  ["#f1f3f4", "#3c4043"],
  ["#fef0e3", "#b3540b"],
  ["#e2f6e9", "#0d652d"],
  ["#e8eaf6", "#3949ab"],
  ["#efebe9", "#6d4c41"],
];

const state = {
  emails: [],
  emailById: new Map(),
  categories: [],
  suggestedPrompts: [],
  filter: "inbox",
  search: "",
  selectedEmailId: null,
  detailOpen: false,
  runs: [],
  running: false,
  archivedIds: new Set(),
  starredIds: new Set(),
  readState: new Map(),
  keys: { openai: "", claude: "" },
  config: null,
  lastUndo: null,
};

/* ---------- Data loading ---------- */

async function loadInbox() {
  try {
    const [inboxRes, configRes] = await Promise.all([fetch("/api/inbox"), fetch("/api/config")]);
    const data = await inboxRes.json();
    state.config = configRes.ok ? await configRes.json() : null;
    state.emails = data.emails || [];
    state.emailById = new Map(state.emails.map((email) => [email.id, email]));
    state.categories = data.categories || [];
    state.suggestedPrompts = data.suggested_prompts || [];
    if (!state.selectedEmailId && !isPhone()) {
      state.selectedEmailId = state.emails[0]?.id || null;
    }
    renderAll();
    renderSubtitle();
    renderSuggestions();
    renderThread();
  } catch (error) {
    nodes.mailList.innerHTML = `<div class="list-empty">Could not load the inbox.<br>${escapeHtml(error.message)}</div>`;
  }
}

function renderAll() {
  renderNav();
  renderList();
  renderDetail();
}

/* ---------- Navigation ---------- */

function renderNav() {
  const active = state.emails.filter((email) => !isArchived(email));
  const folders = [
    { id: "inbox", label: "Inbox", icon: "i-inbox", count: active.filter(isUnread).length },
    { id: "starred", label: "Starred", icon: "i-star", count: active.filter(isStarred).length },
    { id: "important", label: "Important", icon: "i-important", count: active.filter((email) => email.needs_response).length },
    { id: "archived", label: "Archived", icon: "i-archive", count: state.archivedIds.size },
  ];
  nodes.navList.innerHTML = folders
    .map(
      (folder) => `<button class="nav-item${state.filter === folder.id ? " active" : ""}" type="button" data-filter="${folder.id}" title="${folder.label}">
        <svg class="icon"><use href="#${folder.icon}"/></svg>
        <span class="nav-label">${folder.label}</span>
        ${folder.count ? `<span class="nav-count">${folder.count}</span>` : ""}
      </button>`
    )
    .join("");
  nodes.labelList.innerHTML = state.categories
    .map((category) => {
      const [, color] = labelColor(category);
      const count = active.filter((email) => email.category === category).length;
      return `<button class="nav-item${state.filter === `label:${category}` ? " active" : ""}" type="button" data-filter="label:${escapeHtml(category)}" title="${escapeHtml(category)}">
        <span class="label-dot" style="background:${color}"></span>
        <span class="nav-label">${escapeHtml(category)}</span>
        ${count ? `<span class="nav-count">${count}</span>` : ""}
      </button>`;
    })
    .join("");
}

function filterTitle() {
  if (state.filter === "inbox") return "Inbox";
  if (state.filter === "starred") return "Starred";
  if (state.filter === "important") return "Important";
  if (state.filter === "archived") return "Archived";
  if (state.filter.startsWith("label:")) return state.filter.slice(6);
  return "Inbox";
}

/* ---------- Email list ---------- */

function filteredEmails() {
  const query = state.search.trim().toLowerCase();
  return state.emails.filter((email) => {
    const archived = isArchived(email);
    let matches;
    if (state.filter === "archived") matches = archived;
    else if (state.filter === "starred") matches = isStarred(email) && !archived;
    else if (state.filter === "important") matches = email.needs_response && !archived;
    else if (state.filter.startsWith("label:")) matches = email.category === state.filter.slice(6) && !archived;
    else matches = !archived;
    if (!matches) return false;
    if (!query) return true;
    const haystack = `${email.from_name} ${email.from_email} ${email.subject} ${email.body} ${email.category} ${(email.tags || []).join(" ")}`.toLowerCase();
    return haystack.includes(query);
  });
}

function renderList() {
  const emails = filteredEmails();
  nodes.listTitle.textContent = state.search.trim() ? "Search results" : filterTitle();
  nodes.mailCount.textContent = emails.length ? `1–${emails.length} of ${emails.length}` : "";
  if (!emails.length) {
    nodes.mailList.innerHTML = `<div class="list-empty">No conversations here.</div>`;
    return;
  }
  if (!isPhone() && !emails.some((email) => email.id === state.selectedEmailId)) {
    state.selectedEmailId = emails[0].id;
    renderDetail();
  }
  nodes.mailList.innerHTML = emails
    .map((email) => {
      const unread = isUnread(email);
      const classes = [
        "mail-row",
        email.id === state.selectedEmailId && !isPhone() ? "active" : "",
        unread ? "unread" : "",
        isStarred(email) ? "starred" : "",
      ]
        .filter(Boolean)
        .join(" ");
      const [chipBg, chipColor] = labelColor(email.category);
      return `<div class="${classes}" role="listitem" data-open-email="${email.id}" tabindex="0">
        <button class="row-star" type="button" data-star="${email.id}" aria-label="Star">
          <svg class="icon"><use href="#${isStarred(email) ? "i-star-fill" : "i-star"}"/></svg>
        </button>
        <span class="row-avatar" style="background:${avatarColor(email.from_name)}">${escapeHtml(initial(email.from_name))}</span>
        <div class="row-main">
          <div class="row-top">
            <span class="row-sender">${escapeHtml(email.from_name)}</span>
            <span class="row-time">${shortTime(email.received)}</span>
          </div>
          <div class="row-subject">${escapeHtml(email.subject)}</div>
          <div class="row-snippet">
            <span>${escapeHtml(snippet(email.body))}</span>
            <span class="label-chip" style="background:${chipBg};color:${chipColor}">${escapeHtml(email.category)}</span>
          </div>
        </div>
        <div class="row-hover-actions">
          <button class="icon-btn" type="button" data-archive="${email.id}" aria-label="${isArchived(email) ? "Move to inbox" : "Archive"}" title="${isArchived(email) ? "Move to inbox" : "Archive"}">
            <svg class="icon"><use href="#${isArchived(email) ? "i-unarchive" : "i-archive"}"/></svg>
          </button>
          <button class="icon-btn" type="button" data-toggle-read="${email.id}" aria-label="${unread ? "Mark as read" : "Mark as unread"}" title="${unread ? "Mark as read" : "Mark as unread"}">
            <svg class="icon"><use href="#${unread ? "i-mail-open" : "i-mail"}"/></svg>
          </button>
        </div>
      </div>`;
    })
    .join("");
}

/* ---------- Reading pane ---------- */

function renderDetail() {
  const email = state.emailById.get(state.selectedEmailId);
  if (!email) {
    nodes.emailDetail.innerHTML = `<div class="detail-empty">
      <svg class="icon"><use href="#i-mail-open"/></svg>
      <p>Select a conversation to read it here.</p>
    </div>`;
    return;
  }
  const [chipBg, chipColor] = labelColor(email.category);
  const unread = isUnread(email);
  nodes.emailDetail.innerHTML = `
    <div class="detail-toolbar">
      <button class="icon-btn detail-back" type="button" data-close-detail aria-label="Back"><svg class="icon"><use href="#i-back"/></svg></button>
      <button class="icon-btn" type="button" data-archive="${email.id}" aria-label="${isArchived(email) ? "Move to inbox" : "Archive"}" title="${isArchived(email) ? "Move to inbox" : "Archive"}">
        <svg class="icon"><use href="#${isArchived(email) ? "i-unarchive" : "i-archive"}"/></svg>
      </button>
      <button class="icon-btn" type="button" data-toggle-read="${email.id}" aria-label="${unread ? "Mark as read" : "Mark as unread"}" title="${unread ? "Mark as read" : "Mark as unread"}">
        <svg class="icon"><use href="#${unread ? "i-mail-open" : "i-mail"}"/></svg>
      </button>
      <button class="icon-btn" type="button" data-star="${email.id}" aria-label="Star" title="${isStarred(email) ? "Unstar" : "Star"}">
        <svg class="icon" style="${isStarred(email) ? "fill:#f4b400" : ""}"><use href="#${isStarred(email) ? "i-star-fill" : "i-star"}"/></svg>
      </button>
      <span class="spacer"></span>
    </div>
    <div class="detail-subjectline">
      <h2>${escapeHtml(email.subject)}</h2>
      <span class="label-chip" style="background:${chipBg};color:${chipColor}">${escapeHtml(email.category)}</span>
    </div>
    <div class="detail-head">
      <span class="sender-avatar" style="background:${avatarColor(email.from_name)}">${escapeHtml(initial(email.from_name))}</span>
      <div class="detail-frombox">
        <div class="detail-fromline">
          <b>${escapeHtml(email.from_name)}</b>
          <span class="from-email">&lt;${escapeHtml(email.from_email)}&gt;</span>
        </div>
        <div class="detail-tome">to me</div>
      </div>
      <span class="detail-date">${longTime(email.received)}</span>
    </div>
    <div class="detail-body">${escapeHtml(email.body)}</div>
    <div class="detail-replybar">
      <button class="pill-btn" type="button" data-reply="${email.id}"><svg class="icon"><use href="#i-reply"/></svg>Reply</button>
      <button class="pill-btn ai" type="button" data-summarize="${email.id}"><svg class="icon"><use href="#i-sparkle"/></svg>Summarize with agents</button>
    </div>`;
}

function openEmail(emailId, { markRead = true } = {}) {
  state.selectedEmailId = emailId;
  if (markRead) state.readState.set(emailId, false);
  state.detailOpen = true;
  renderAll();
  if (isPhone()) nodes.readingPane.classList.add("open");
  nodes.emailDetail.scrollTop = 0;
}

function closeDetail() {
  state.detailOpen = false;
  nodes.readingPane.classList.remove("open");
}

/* ---------- Mail state helpers ---------- */

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

function toggleStar(emailId) {
  if (state.starredIds.has(emailId)) state.starredIds.delete(emailId);
  else state.starredIds.add(emailId);
  renderAll();
}

function toggleRead(emailId) {
  const email = state.emailById.get(emailId);
  if (!email) return;
  state.readState.set(emailId, !isUnread(email));
  renderAll();
}

function toggleArchive(emailId) {
  const email = state.emailById.get(emailId);
  if (!email) return;
  const wasArchived = isArchived(email);
  if (wasArchived) state.archivedIds.delete(emailId);
  else state.archivedIds.add(emailId);
  if (state.selectedEmailId === emailId && !wasArchived && state.filter !== "archived") {
    const remaining = filteredEmails();
    state.selectedEmailId = remaining[0]?.id || null;
    if (isPhone()) closeDetail();
  }
  renderAll();
  showSnackbar(wasArchived ? "Conversation moved to inbox" : "Conversation archived", () => {
    if (wasArchived) state.archivedIds.add(emailId);
    else state.archivedIds.delete(emailId);
    state.selectedEmailId = emailId;
    renderAll();
  });
}

/* ---------- AI panel ---------- */

function isPhone() {
  return window.matchMedia("(max-width: 768px)").matches;
}

function aiIsDrawer() {
  return window.matchMedia("(max-width: 1120px)").matches;
}

function openAiPanel(focus = false) {
  nodes.aiPanel.classList.remove("collapsed");
  if (aiIsDrawer()) nodes.aiPanel.classList.add("open");
  nodes.aiToggle.classList.add("active");
  if (focus) setTimeout(() => nodes.promptInput.focus(), 120);
}

function closeAiPanel() {
  if (aiIsDrawer()) nodes.aiPanel.classList.remove("open");
  else nodes.aiPanel.classList.add("collapsed");
  nodes.aiToggle.classList.remove("active");
}

function aiPanelVisible() {
  return aiIsDrawer() ? nodes.aiPanel.classList.contains("open") : !nodes.aiPanel.classList.contains("collapsed");
}

function renderSubtitle() {
  const config = state.config || {};
  const parts = [];
  parts.push("Cascade");
  parts.push(config.openai?.enabled || state.keys.openai ? "OpenAI" : "OpenAI (off)");
  parts.push(config.claude?.enabled || state.keys.claude ? "Claude" : "Claude (off)");
  nodes.aiSubtitle.textContent = parts.join(" · ");
}

function renderSuggestions() {
  const prompts = state.suggestedPrompts.slice(0, 6);
  nodes.suggestionRow.innerHTML = prompts
    .map((prompt) => `<button class="suggestion-chip" type="button" data-suggestion="${escapeHtml(prompt)}">${escapeHtml(shorten(prompt, 44))}</button>`)
    .join("");
}

function renderThread() {
  if (!state.runs.length && !state.running) {
    nodes.chatThread.innerHTML = `<div class="chat-welcome">
      <svg class="sparkle-lg"><use href="#i-sparkle"/></svg>
      <h3>Ask your inbox agents</h3>
      <p>One prompt runs three agents side by side — a local small-model cascade, OpenAI, and Claude — so you can compare answers, speed, and cost.</p>
    </div>`;
    return;
  }
  nodes.chatThread.innerHTML = state.runs.map(renderRunBlock).join("");
  scrollChatToBottom();
}

function renderRunBlock(run) {
  const bubble = `<div class="user-bubble">${escapeHtml(run.prompt)}</div>`;
  if (run.pending) {
    return `${bubble}<div class="run-block">
      <div class="thinking-note"><svg class="sparkle"><use href="#i-sparkle"/></svg>Agents are reading the inbox…</div>
      ${["cascade", "openai", "claude"].map(loadingCard).join("")}
    </div>`;
  }
  if (run.error) {
    return `${bubble}<div class="error-bubble">${escapeHtml(run.error)}</div>`;
  }
  const summary = run.summary || {};
  const live = (run.results || []).filter((result) => result.status !== "provider_unavailable");
  const tokens = live.reduce((total, result) => total + Number(result.tokens || 0), 0);
  const cost = live.reduce((total, result) => total + Number(result.cost_usd || 0), 0);
  const matched = Number(summary.matched_emails || 0);
  const meta = [
    `<b>${formatDuration(run.elapsed_ms)}</b>`,
    `${formatNumber(tokens)} tokens`,
    `$${formatMoney(cost)}`,
    `${formatNumber(matched)} email${matched === 1 ? "" : "s"} matched`,
  ].join(" · ");
  const cards = (run.results || []).map(renderAgentCard).join("");
  return `${bubble}<div class="run-block"><div class="run-meta">${meta}</div>${cards}</div>`;
}

function loadingCard(agentId) {
  return `<article class="agent-card loading" data-agent="${agentId}">
    <div class="agent-card-head">
      <span class="agent-dot"><svg class="icon"><use href="#i-sparkle"/></svg></span>
      <div class="agent-name-box">
        <span class="agent-name">${AGENT_META[agentId].name}</span>
        <span class="agent-model">working…</span>
      </div>
    </div>
    <div class="agent-answer">
      <div class="shimmer"></div>
      <div class="shimmer w85"></div>
      <div class="shimmer w60"></div>
    </div>
  </article>`;
}

function renderAgentCard(result) {
  const agentId = result.agent_id;
  const meta = AGENT_META[agentId] || { name: result.label };
  const completion = result.completion || { checks: [], state: result.status || "complete" };
  const status = completion.state || result.status || "complete";
  const unavailable = status === "provider_unavailable";
  const answerHtml = unavailable
    ? `<p class="unavailable-note">${escapeHtml(unavailableNote(result))}</p>`
    : formatAnswer(result.answer);
  const stats = unavailable
    ? ""
    : `<div class="agent-stats">
        <span><b>${formatDuration(result.runtime_ms)}</b></span>
        <span><b>${formatNumber(result.tokens || 0)}</b> tokens</span>
        <span><b>$${formatMoney(result.cost_usd || 0)}</b></span>
        <span><b>${formatPercent(result.confidence || 0)}</b> confident</span>
      </div>`;
  return `<article class="agent-card" data-agent="${escapeHtml(agentId)}">
    <div class="agent-card-head">
      <span class="agent-dot"><svg class="icon"><use href="#i-sparkle"/></svg></span>
      <div class="agent-name-box">
        <span class="agent-name">${escapeHtml(result.label || meta.name)}</span>
        <span class="agent-model" title="${escapeHtml(result.model || "")}">${escapeHtml(result.model || "")}</span>
      </div>
      <span class="status-pill ${escapeHtml(status)}">
        <svg class="icon"><use href="#${status === "complete" ? "i-check" : "i-alert"}"/></svg>${unavailable && agentId === "cascade" ? "No fallback" : statusLabel(status)}
      </span>
    </div>
    <div class="agent-answer">${answerHtml}</div>
    ${stats}
    ${renderAgentDetails(result, completion, unavailable)}
  </article>`;
}

function unavailableNote(result) {
  const message = String(result.answer || "");
  if (/OPENAI_API_KEY/i.test(message)) {
    return "Not connected — add an OpenAI API key in Settings to include this agent.";
  }
  if (/ANTHROPIC_API_KEY/i.test(message)) {
    return "Not connected — add an Anthropic API key in Settings to include this agent.";
  }
  if (result.agent_id === "cascade") {
    return "The local model wanted a cloud fallback for this prompt, but no cloud agent is connected. Add an API key in Settings, or try a direct question like “What did Nora say?”";
  }
  return message || "This agent didn't return a response.";
}

function renderAgentDetails(result, completion, unavailable) {
  const sections = [];
  if (unavailable && result.answer) {
    sections.push(`<div class="details-section"><h4>Why</h4><div class="trace-detail">${escapeHtml(result.answer)}</div></div>`);
  }
  if (!unavailable && completion.checks?.length) {
    sections.push(`<div class="details-section"><h4>Checks</h4><div class="check-list">${completion.checks
      .map(
        (check) => `<div class="check-item ${check.passed ? "pass" : "fail"}" title="${escapeHtml(check.detail || "")}">
          <svg class="icon"><use href="#${check.passed ? "i-check" : "i-alert"}"/></svg>${escapeHtml(check.label)}
        </div>`
      )
      .join("")}</div></div>`);
  }
  if (result.selected_emails?.length) {
    sections.push(`<div class="details-section"><h4>Emails used</h4><div class="source-list">${result.selected_emails
      .map(
        (email) => `<button class="source-row" type="button" data-open-email="${escapeHtml(email.id)}">
          <b>${escapeHtml(email.from_name)}</b>
          <span>${escapeHtml(email.subject)}</span>
        </button>`
      )
      .join("")}</div></div>`);
  }
  if (result.drafts?.length) {
    sections.push(`<div class="details-section"><h4>Drafts</h4>${result.drafts
      .map(
        (draft) => `<div class="draft-card">
          <div class="draft-to">To: ${escapeHtml(draft.to)}</div>
          <div class="draft-subject">${escapeHtml(draft.subject)}</div>
          <div class="draft-body">${escapeHtml(draft.body)}</div>
        </div>`
      )
      .join("")}</div>`);
  }
  if (result.operations?.length) {
    sections.push(`<div class="details-section"><h4>Suggested actions</h4><div class="op-list">${result.operations
      .map(
        (operation) => `<button class="op-chip" type="button" data-open-email="${escapeHtml(operation.email_id)}" title="${escapeHtml(operation.reason || "")}">
          <span>${escapeHtml(operation.label)}</span>
        </button>`
      )
      .join("")}</div></div>`);
  }
  if (result.actions?.length) {
    sections.push(`<div class="details-section"><h4>How it worked</h4><ol class="trace-list">${result.actions
      .map(
        (action) => `<li class="trace-item" data-route="${escapeHtml(action.route || "unknown")}">
          <span class="trace-marker"></span>
          <div class="trace-content">
            <div class="trace-label">${escapeHtml(action.label)}</div>
            <div class="trace-detail">${escapeHtml(action.detail || "")}</div>
            ${traceMeta(action)}
          </div>
        </li>`
      )
      .join("")}</ol></div>`);
  }
  if (!sections.length) return "";
  return `<details class="agent-details">
    <summary><svg class="icon"><use href="#i-chevron"/></svg>Details</summary>
    <div class="details-body">${sections.join("")}</div>
  </details>`;
}

function traceMeta(action) {
  const parts = [];
  if (Number(action.confidence) > 0) parts.push(`${formatPercent(action.confidence)} conf`);
  if (Number(action.tokens) > 0) parts.push(`${formatNumber(action.tokens)} tok`);
  if (Number(action.latency_ms) > 0) parts.push(formatDuration(action.latency_ms));
  if (Number(action.messages) > 0) parts.push(`${formatNumber(action.messages)} msgs`);
  return parts.length ? `<div class="trace-meta">${parts.join(" · ")}</div>` : "";
}

/* ---------- Running the agents ---------- */

async function runAgents(promptText) {
  const prompt = String(promptText || nodes.promptInput.value || "").trim();
  if (!prompt || state.running) return;
  state.running = true;
  nodes.promptInput.value = "";
  autosizeInput();
  nodes.sendBtn.disabled = true;
  const run = { prompt, pending: true };
  state.runs.push(run);
  renderThread();
  try {
    const payload = { prompt };
    const providerKeys = {};
    if (state.keys.openai) providerKeys.openai = state.keys.openai;
    if (state.keys.claude) providerKeys.claude = state.keys.claude;
    if (Object.keys(providerKeys).length) payload.provider_keys = providerKeys;
    const response = await fetch("/api/inbox/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        detail = (await response.json()).detail || detail;
      } catch (ignore) {}
      throw new Error(detail);
    }
    const data = await response.json();
    Object.assign(run, data, { pending: false });
  } catch (error) {
    run.pending = false;
    run.error = error.message || "The run failed. Try again in a moment.";
  } finally {
    state.running = false;
    nodes.sendBtn.disabled = false;
    renderThread();
  }
}

function scrollChatToBottom() {
  requestAnimationFrame(() => {
    nodes.chatScroll.scrollTop = nodes.chatScroll.scrollHeight;
  });
}

/* ---------- Answer formatting ---------- */

function formatAnswer(raw) {
  const text = String(raw || "").replace(/\r/g, "").trim();
  if (!text) return `<p class="unavailable-note">No answer returned.</p>`;
  const lines = text.split("\n");
  const blocks = [];
  let list = null;
  const flushList = () => {
    if (list) {
      blocks.push(`<${list.tag}>${list.items.join("")}</${list.tag}>`);
      list = null;
    }
  };
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flushList();
      continue;
    }
    const bullet = line.match(/^[-*•]\s+(.*)$/);
    const numbered = line.match(/^(\d{1,2})[.)]\s+(.*)$/);
    if (bullet) {
      if (!list || list.tag !== "ul") {
        flushList();
        list = { tag: "ul", items: [] };
      }
      list.items.push(`<li>${inlineFormat(bullet[1])}</li>`);
    } else if (numbered) {
      if (!list || list.tag !== "ol") {
        flushList();
        list = { tag: "ol", items: [] };
      }
      list.items.push(`<li>${inlineFormat(numbered[2])}</li>`);
    } else {
      flushList();
      const heading = /^.{3,60}:$/.test(line) && !line.includes(". ");
      blocks.push(`<p${heading ? ' class="answer-heading"' : ""}>${inlineFormat(line)}</p>`);
    }
  }
  flushList();
  return blocks.join("");
}

function inlineFormat(text) {
  let html = escapeHtml(text);
  html = html.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\(?\b(E-\d{3,5})\b\)?/g, (match, id) => {
    const email = state.emailById.get(id);
    if (!email) return match;
    return ` <button class="email-ref" type="button" data-open-email="${id}" title="${escapeHtml(email.subject)}">${escapeHtml(email.from_name)}</button>`;
  });
  return html;
}

/* ---------- Settings ---------- */

function openSettings() {
  nodes.keyOpenai.value = state.keys.openai;
  nodes.keyClaude.value = state.keys.claude;
  renderProviderStatus();
  nodes.settingsDialog.showModal();
}

function renderProviderStatus() {
  const config = state.config || {};
  const rows = [
    { label: "SLM Cascade (local)", on: true, model: config.cascade?.model || "ollama" },
    { label: "OpenAI", on: Boolean(config.openai?.enabled || state.keys.openai), model: config.openai?.model || "" },
    { label: "Claude", on: Boolean(config.claude?.enabled || state.keys.claude), model: config.claude?.model || "" },
  ];
  nodes.providerStatus.innerHTML = rows
    .map(
      (row) => `<div class="row">
        <span class="dot ${row.on ? "on" : "off"}"></span>${escapeHtml(row.label)}
        <span title="${escapeHtml(row.model)}">${escapeHtml(row.model)}</span>
      </div>`
    )
    .join("");
}

/* ---------- Snackbar ---------- */

let snackbarTimer = null;

function showSnackbar(message, undoFn) {
  clearTimeout(snackbarTimer);
  nodes.snackbar.innerHTML = `<span>${escapeHtml(message)}</span>${undoFn ? '<button type="button" id="snackbar-undo">Undo</button>' : ""}`;
  nodes.snackbar.classList.remove("hidden");
  if (undoFn) {
    el("snackbar-undo").addEventListener("click", () => {
      undoFn();
      hideSnackbar();
    });
  }
  snackbarTimer = setTimeout(hideSnackbar, 5000);
}

function hideSnackbar() {
  nodes.snackbar.classList.add("hidden");
}

/* ---------- Formatting helpers ---------- */

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function initial(name) {
  return String(name || "?").trim().charAt(0).toUpperCase();
}

function avatarColor(name) {
  let hash = 0;
  for (const char of String(name || "")) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}

function labelColor(category) {
  const index = Math.max(0, state.categories.indexOf(category));
  return LABEL_COLORS[index % LABEL_COLORS.length];
}

function snippet(body) {
  return shorten(String(body || "").replace(/\s+/g, " "), 110);
}

function shorten(value, limit) {
  const text = String(value || "");
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function shortTime(received) {
  const time = String(received || "").split(" ")[1] || "";
  const [hourText, minute] = time.split(":");
  const hour = Number(hourText);
  if (!Number.isFinite(hour)) return time;
  const period = hour >= 12 ? "PM" : "AM";
  const display = hour % 12 === 0 ? 12 : hour % 12;
  return `${display}:${minute} ${period}`;
}

function longTime(received) {
  const [date, time] = String(received || "").split(" ");
  if (!date) return "";
  const [year, month, day] = date.split("-").map(Number);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const monthName = months[(month || 1) - 1] || "";
  return `${monthName} ${day}, ${year}, ${shortTime(received)}`;
}

function formatDuration(value) {
  const ms = Number(value || 0);
  if (ms < 1000) return `${ms.toFixed(0)} ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatMoney(value) {
  const number = Number(value || 0);
  if (number === 0) return "0.00";
  return number < 0.01 ? number.toFixed(4) : number.toFixed(2);
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function formatPercent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function statusLabel(value) {
  if (value === "complete") return "Complete";
  if (value === "needs_review") return "Needs review";
  if (value === "provider_unavailable") return "Not connected";
  return String(value || "").replaceAll("_", " ");
}

/* ---------- Sidebar drawer ---------- */

function sidebarIsDrawer() {
  return window.matchMedia("(max-width: 1024px)").matches;
}

function toggleSidebar() {
  if (!sidebarIsDrawer()) return;
  const open = nodes.sidebar.classList.toggle("open");
  nodes.scrim.classList.toggle("hidden", !open);
}

function closeSidebar() {
  nodes.sidebar.classList.remove("open");
  nodes.scrim.classList.add("hidden");
}

/* ---------- Prompt helpers ---------- */

function promptForReply(email) {
  return `Draft a reply to ${email.from_name} about "${email.subject}"`;
}

function promptForSummary(email) {
  return `What did ${email.from_name.split(" ")[0]} say about "${email.subject}"?`;
}

function askAgents(prompt) {
  openAiPanel(true);
  nodes.promptInput.value = prompt;
  autosizeInput();
}

function autosizeInput() {
  nodes.promptInput.style.height = "auto";
  if (nodes.promptInput.value.trim()) {
    nodes.promptInput.style.height = `${Math.min(nodes.promptInput.scrollHeight, 120)}px`;
  }
}

/* ---------- Events ---------- */

document.addEventListener("click", (event) => {
  const star = event.target.closest("[data-star]");
  if (star) {
    event.stopPropagation();
    toggleStar(star.dataset.star);
    return;
  }
  const archive = event.target.closest("[data-archive]");
  if (archive) {
    event.stopPropagation();
    toggleArchive(archive.dataset.archive);
    return;
  }
  const read = event.target.closest("[data-toggle-read]");
  if (read) {
    event.stopPropagation();
    toggleRead(read.dataset.toggleRead);
    return;
  }
  const reply = event.target.closest("[data-reply]");
  if (reply) {
    const email = state.emailById.get(reply.dataset.reply);
    if (email) askAgents(promptForReply(email));
    return;
  }
  const summarize = event.target.closest("[data-summarize]");
  if (summarize) {
    const email = state.emailById.get(summarize.dataset.summarize);
    if (email) {
      askAgents(promptForSummary(email));
      runAgents(promptForSummary(email));
    }
    return;
  }
  const suggestion = event.target.closest("[data-suggestion]");
  if (suggestion) {
    nodes.promptInput.value = suggestion.dataset.suggestion;
    autosizeInput();
    nodes.promptInput.focus();
    return;
  }
  const closeDetailBtn = event.target.closest("[data-close-detail]");
  if (closeDetailBtn) {
    closeDetail();
    return;
  }
  const filter = event.target.closest("[data-filter]");
  if (filter) {
    state.filter = filter.dataset.filter;
    if (state.filter === "inbox") {
      state.search = "";
      nodes.search.value = "";
      nodes.searchClear.classList.add("hidden");
    }
    closeSidebar();
    renderAll();
    return;
  }
  const open = event.target.closest("[data-open-email]");
  if (open) {
    openEmail(open.dataset.openEmail);
    if (isPhone() && open.closest(".ai-panel")) closeAiPanel();
    return;
  }
});

nodes.menuBtn.addEventListener("click", toggleSidebar);
nodes.scrim.addEventListener("click", closeSidebar);

nodes.search.addEventListener("input", () => {
  state.search = nodes.search.value;
  nodes.searchClear.classList.toggle("hidden", !state.search);
  renderList();
});

nodes.searchClear.addEventListener("click", () => {
  state.search = "";
  nodes.search.value = "";
  nodes.searchClear.classList.add("hidden");
  renderList();
  nodes.search.focus();
});

nodes.refreshBtn.addEventListener("click", loadInbox);

nodes.composeBtn.addEventListener("click", () => {
  closeSidebar();
  const email = state.emailById.get(state.selectedEmailId);
  askAgents(email ? promptForReply(email) : "Draft replies to the highest priority emails.");
});

nodes.aiToggle.addEventListener("click", () => {
  if (aiPanelVisible()) closeAiPanel();
  else openAiPanel(true);
});

nodes.aiClose.addEventListener("click", closeAiPanel);
nodes.aiBack.addEventListener("click", closeAiPanel);
nodes.fab.addEventListener("click", () => openAiPanel(true));

nodes.sendBtn.addEventListener("click", () => runAgents());

nodes.promptInput.addEventListener("input", autosizeInput);
nodes.promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    runAgents();
  }
});

nodes.settingsBtn.addEventListener("click", openSettings);

nodes.settingsDialog.addEventListener("close", () => {
  if (nodes.settingsDialog.returnValue === "save") {
    state.keys.openai = nodes.keyOpenai.value.trim();
    state.keys.claude = nodes.keyClaude.value.trim();
    renderSubtitle();
    showSnackbar("Settings saved for this session");
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeSidebar();
    if (isPhone() && nodes.readingPane.classList.contains("open")) closeDetail();
  }
});

window.addEventListener("resize", () => {
  if (!sidebarIsDrawer()) closeSidebar();
  if (!aiIsDrawer()) nodes.aiPanel.classList.remove("open");
  if (!isPhone() && !state.selectedEmailId && state.emails.length) {
    renderAll();
  }
});

/* ---------- Boot ---------- */

loadInbox();
