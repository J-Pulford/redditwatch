"use strict";

// --- Tiny API helper -------------------------------------------------------
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* no body */ }
  if (!res.ok) {
    const msg = (data && data.detail) ? data.detail : `Error ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

const $ = (id) => document.getElementById(id);
let CONFIG = { apify_enabled: false, reddit_configured: false };
let CURRENT_ITEM = null;
let SUB_NOTES = {};
let REPLY_ALLOWED = true;
let REPLY_REASON = null;

// --- Toast -----------------------------------------------------------------
let toastTimer = null;
function toast(msg, kind = "ok") {
  const t = $("toast");
  t.textContent = msg;
  t.className = `toast ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 4200);
}

// --- Time formatting -------------------------------------------------------
function ago(epoch) {
  if (!epoch) return "";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
function fmtNext(iso) {
  if (!iso) return "off";
  const d = new Date(iso);
  if (isNaN(d)) return "off";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// --- Tabs ------------------------------------------------------------------
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    const view = tab.dataset.view;
    $("view-feed").classList.toggle("hidden", view !== "feed");
    $("view-settings").classList.toggle("hidden", view !== "settings");
    if (view === "settings") loadSettings();
    if (view === "feed") loadItems();
  });
});

// --- Stats -----------------------------------------------------------------
async function loadStats() {
  try {
    const s = await api("/api/stats");
    $("stat-matches").textContent = s.matches_total;
    $("stat-new").textContent = s.new_count;
    $("stat-replies").textContent = `${s.replies_today} / ${s.daily_cap}`;
    $("stat-auto").textContent = s.auto_refresh_enabled ? "on" : "off";
    $("stat-next").textContent = s.auto_refresh_enabled ? fmtNext(s.next_run) : "off";
    REPLY_ALLOWED = s.reply_allowed;
    REPLY_REASON = s.reply_block_reason;
  } catch (e) {
    toast(e.message, "err");
  }
}

// --- Refresh now -----------------------------------------------------------
$("refresh-btn").addEventListener("click", async () => {
  const btn = $("refresh-btn");
  btn.disabled = true;
  btn.textContent = "Refreshing…";
  try {
    const r = await api("/api/refresh", { method: "POST" });
    let msg = `Found ${r.new_items} new match(es) across ` +
      `${r.subreddits_scanned} subreddit(s).`;
    if (r.errors && r.errors.length) msg += ` ${r.errors.length} warning(s).`;
    toast(msg, "ok");
    await Promise.all([loadStats(), loadItems(), loadFilters()]);
  } catch (e) {
    toast(e.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "Refresh now";
  }
});

// --- Filters ---------------------------------------------------------------
async function loadFilters() {
  try {
    const data = await api("/api/settings");
    const subSel = $("f-subreddit");
    const kwSel = $("f-keyword");
    const curSub = subSel.value;
    const curKw = kwSel.value;
    subSel.innerHTML = '<option value="">all subreddits</option>' +
      data.subreddits.map((s) => `<option value="${s.name}">r/${s.name}</option>`).join("");
    kwSel.innerHTML = '<option value="">all keywords</option>' +
      data.keywords.map((k) => `<option value="${escapeAttr(k.phrase)}">${escapeHtml(k.phrase)}</option>`).join("");
    subSel.value = curSub;
    kwSel.value = curKw;
    SUB_NOTES = {};
    data.subreddits.forEach((s) => { SUB_NOTES[s.name] = s.self_promo_notes || ""; });
  } catch (e) { /* non-fatal */ }
}

["f-subreddit", "f-keyword", "f-type", "f-status"].forEach((id) =>
  $(id).addEventListener("change", loadItems)
);

// --- Feed ------------------------------------------------------------------
async function loadItems() {
  const params = new URLSearchParams();
  const sub = $("f-subreddit").value;
  const kw = $("f-keyword").value;
  const type = $("f-type").value;
  const status = $("f-status").value;
  if (sub) params.set("subreddit", sub);
  if (kw) params.set("keyword", kw);
  if (type) params.set("type", type);
  if (status) params.set("status", status);

  try {
    const items = await api("/api/items?" + params.toString());
    const feed = $("feed");
    $("feed-count").textContent = `${items.length} shown`;
    $("feed-empty").classList.toggle("hidden", items.length > 0);
    feed.innerHTML = "";
    items.forEach((it) => feed.appendChild(renderRow(it)));
  } catch (e) {
    toast(e.message, "err");
  }
}

function renderRow(it) {
  const li = document.createElement("li");
  li.className = `row ${it.status}`;
  const titleOrSnip = it.type === "post"
    ? `<div class="title">${escapeHtml(it.title || "(untitled)")}</div>`
    : "";
  li.innerHTML = `
    <div class="row-top">
      <span class="badge ${it.type}">${it.type}</span>
      <span class="sub">r/${escapeHtml(it.subreddit)}</span>
      <span class="kw">“${escapeHtml(it.matched_keyword || "")}”</span>
      <span class="status-pill ${it.status}">${it.status}</span>
    </div>
    ${titleOrSnip}
    <div class="snip">${escapeHtml(it.body_snippet || "")}</div>
    <div class="row-meta">
      <span>u/${escapeHtml(it.author || "?")}</span>
      <span>▲ ${it.score}</span>
      <span>${ago(it.created_utc)}</span>
    </div>`;
  li.addEventListener("click", () => openPanel(it));
  return li;
}

// --- Reply panel -----------------------------------------------------------
function openPanel(it) {
  CURRENT_ITEM = it;
  $("p-type").textContent = it.type;
  $("p-type").className = `badge ${it.type}`;
  $("p-sub").textContent = `r/${it.subreddit}`;
  $("p-sub").className = "sub";
  $("p-kw").textContent = `“${it.matched_keyword || ""}”`;
  $("p-kw").className = "kw";
  $("p-title").textContent = it.type === "post" ? (it.title || "(untitled)") : "Comment";
  $("p-meta").textContent = `u/${it.author || "?"} · ▲ ${it.score} · ${ago(it.created_utc)} · ${it.status}`;
  $("p-body").textContent = it.body_snippet || "(no body)";
  $("p-link").href = it.permalink || "#";
  $("reply-text").value = "";

  // Per-subreddit self-promo rules, shown as a reminder while you write.
  const notes = SUB_NOTES[it.subreddit] || "";
  const nEl = $("p-notes");
  nEl.textContent = notes ? `Self-promo rules: ${notes}` : "";
  nEl.classList.toggle("hidden", !notes);

  updateSendButton();
  $("panel-overlay").classList.remove("hidden");
}

function closePanel() {
  $("panel-overlay").classList.add("hidden");
  CURRENT_ITEM = null;
}
$("panel-close").addEventListener("click", closePanel);
$("panel-overlay").addEventListener("click", (e) => {
  if (e.target === $("panel-overlay")) closePanel();
});

function updateSendButton() {
  const sendBtn = $("send-btn");
  const alreadyReplied = CURRENT_ITEM && CURRENT_ITEM.status === "replied";
  const blocked = !REPLY_ALLOWED || alreadyReplied;
  sendBtn.disabled = blocked;
  if (alreadyReplied) {
    $("block-reason").textContent = "Already replied.";
  } else if (!REPLY_ALLOWED && REPLY_REASON) {
    $("block-reason").textContent = REPLY_REASON;
  } else {
    $("block-reason").textContent = "";
  }
}

// Send reply
$("send-btn").addEventListener("click", async () => {
  if (!CURRENT_ITEM) return;
  const text = $("reply-text").value.trim();
  if (!text) { toast("Reply is empty.", "err"); return; }
  const btn = $("send-btn");
  btn.disabled = true;
  btn.textContent = "Sending…";
  try {
    const r = await api(`/api/items/${CURRENT_ITEM.id}/reply`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    toast("Reply sent ✓", "ok");
    closePanel();
    await Promise.all([loadStats(), loadItems()]);
  } catch (e) {
    toast(e.message, "err");
    await loadStats();
    updateSendButton();
  } finally {
    btn.textContent = "Send reply";
    btn.disabled = false;
    updateSendButton();
  }
});

// Ignore / Save
$("ignore-btn").addEventListener("click", () => setStatus("ignored"));
$("save-btn").addEventListener("click", () => setStatus("saved"));

async function setStatus(status) {
  if (!CURRENT_ITEM) return;
  try {
    await api(`/api/items/${CURRENT_ITEM.id}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    });
    toast(`Marked ${status}.`, "ok");
    closePanel();
    await Promise.all([loadStats(), loadItems()]);
  } catch (e) {
    toast(e.message, "err");
  }
}

// --- Settings --------------------------------------------------------------
async function loadSettings() {
  try {
    const data = await api("/api/settings");
    const s = data.settings;
    $("s-auto").checked = s.auto_refresh_enabled;
    $("s-interval").value = s.refresh_interval_minutes;
    $("s-cooldown").value = s.reply_cooldown_minutes;
    $("s-cap").value = s.daily_reply_cap;
    $("s-posts").value = s.post_scan_limit;
    $("s-comments").value = s.comment_scan_limit;
    renderSubs(data.subreddits);
    renderKws(data.keywords);
  } catch (e) {
    toast(e.message, "err");
  }
}

$("save-settings").addEventListener("click", async () => {
  const payload = {
    auto_refresh_enabled: $("s-auto").checked,
    refresh_interval_minutes: parseInt($("s-interval").value, 10),
    reply_cooldown_minutes: parseInt($("s-cooldown").value, 10),
    daily_reply_cap: parseInt($("s-cap").value, 10),
    post_scan_limit: parseInt($("s-posts").value, 10),
    comment_scan_limit: parseInt($("s-comments").value, 10),
  };
  try {
    await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
    toast("Settings saved.", "ok");
    await loadStats();
  } catch (e) {
    toast(e.message, "err");
  }
});

// Subreddits CRUD
function renderSubs(subs) {
  const tbody = $("sub-rows");
  tbody.innerHTML = "";
  subs.forEach((s) => {
    const tr = document.createElement("tr");
    if (!s.enabled) tr.className = "disabled-item";
    tr.innerHTML = `
      <td class="cell-name">r/${escapeHtml(s.name)}</td>
      <td><input type="text" value="${escapeAttr(s.self_promo_notes || "")}" data-id="${s.id}" class="sub-notes" placeholder="self-promo rules / notes"/></td>
      <td class="cell-actions">
        <button class="btn mini toggle-sub" data-id="${s.id}" data-enabled="${s.enabled}">${s.enabled ? "on" : "off"}</button>
        <button class="btn mini del del-sub" data-id="${s.id}">del</button>
      </td>`;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll(".sub-notes").forEach((inp) => {
    inp.addEventListener("change", () =>
      updateSub(inp.dataset.id, { self_promo_notes: inp.value })
    );
  });
  tbody.querySelectorAll(".toggle-sub").forEach((btn) => {
    btn.addEventListener("click", () =>
      updateSub(btn.dataset.id, { enabled: !(btn.dataset.enabled === "true") })
    );
  });
  tbody.querySelectorAll(".del-sub").forEach((btn) => {
    btn.addEventListener("click", () => delSub(btn.dataset.id));
  });
}

async function updateSub(id, patch) {
  try {
    await api(`/api/subreddits/${id}`, { method: "PUT", body: JSON.stringify(patch) });
    await loadSettings();
    await loadFilters();
  } catch (e) { toast(e.message, "err"); }
}
async function delSub(id) {
  try {
    await api(`/api/subreddits/${id}`, { method: "DELETE" });
    await loadSettings();
    await loadFilters();
  } catch (e) { toast(e.message, "err"); }
}
$("add-sub").addEventListener("click", async () => {
  const name = $("new-sub-name").value.trim();
  if (!name) { toast("Enter a subreddit name.", "err"); return; }
  try {
    await api("/api/subreddits", {
      method: "POST",
      body: JSON.stringify({ name, self_promo_notes: $("new-sub-notes").value.trim() }),
    });
    $("new-sub-name").value = "";
    $("new-sub-notes").value = "";
    await loadSettings();
    await loadFilters();
  } catch (e) { toast(e.message, "err"); }
});

// Keywords CRUD
function renderKws(kws) {
  const tbody = $("kw-rows");
  tbody.innerHTML = "";
  kws.forEach((k) => {
    const tr = document.createElement("tr");
    if (!k.enabled) tr.className = "disabled-item";
    tr.innerHTML = `
      <td><input type="text" value="${escapeAttr(k.phrase)}" data-id="${k.id}" class="kw-phrase"/></td>
      <td class="cell-actions">
        <button class="btn mini toggle-kw" data-id="${k.id}" data-enabled="${k.enabled}">${k.enabled ? "on" : "off"}</button>
        <button class="btn mini del del-kw" data-id="${k.id}">del</button>
      </td>`;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll(".kw-phrase").forEach((inp) => {
    inp.addEventListener("change", () => updateKw(inp.dataset.id, { phrase: inp.value }));
  });
  tbody.querySelectorAll(".toggle-kw").forEach((btn) => {
    btn.addEventListener("click", () =>
      updateKw(btn.dataset.id, { enabled: !(btn.dataset.enabled === "true") })
    );
  });
  tbody.querySelectorAll(".del-kw").forEach((btn) => {
    btn.addEventListener("click", () => delKw(btn.dataset.id));
  });
}
async function updateKw(id, patch) {
  try {
    await api(`/api/keywords/${id}`, { method: "PUT", body: JSON.stringify(patch) });
    await loadSettings();
    await loadFilters();
  } catch (e) { toast(e.message, "err"); }
}
async function delKw(id) {
  try {
    await api(`/api/keywords/${id}`, { method: "DELETE" });
    await loadSettings();
    await loadFilters();
  } catch (e) { toast(e.message, "err"); }
}
$("add-kw").addEventListener("click", async () => {
  const phrase = $("new-kw").value.trim();
  if (!phrase) { toast("Enter a keyword.", "err"); return; }
  try {
    await api("/api/keywords", { method: "POST", body: JSON.stringify({ phrase }) });
    $("new-kw").value = "";
    await loadSettings();
    await loadFilters();
  } catch (e) { toast(e.message, "err"); }
});

// --- Escaping helpers ------------------------------------------------------
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function escapeAttr(s) { return escapeHtml(s); }

// --- Boot ------------------------------------------------------------------
async function boot() {
  try {
    CONFIG = await api("/api/config");
    if (!CONFIG.reddit_configured) {
      toast("Reddit creds not set — fill REDDIT_* in .env, then restart.", "err");
    }
  } catch (e) { /* ignore */ }
  await Promise.all([loadStats(), loadFilters(), loadItems()]);
  // Light polling so the stats strip (cooldown, next-run) stays current.
  setInterval(loadStats, 30000);
}
boot();
