/**
 * TORCH Web GUI — Flag Browser view.
 *
 * Scrollable flag list with search, filter, detail panel (cross-references),
 * create flow, and delete with padlock safety.
 */

import { api, postApi } from "../app.js";
import { esc } from "../utils.js";
import { renderStudioNavbar } from "../studioNav.js";

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let allFlags = [];
let stats = {};
let filteredFlags = [];
let activeFilter = "all";    // "all" | "custom" | "event" | "free"
let searchQuery = "";
let debounceTimer = null;
let expandedFlag = null;     // flag name currently showing detail panel
let expandedRefs = null;     // cross-ref data for expanded flag (or null = loading)
let _relockHandler = null;
let _container = null;

// ---------------------------------------------------------------------------
// Scoped CSS
// ---------------------------------------------------------------------------

const STYLE_ID = "flags-view-css";

function injectCSS() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    /* Flag browser layout */
    .flags-toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.75rem;
      margin-bottom: 1rem;
    }
    .flags-search {
      flex: 1;
      min-width: 180px;
      padding: 0.4rem 0.6rem;
      font-size: 0.85rem;
      background: var(--surface-2);
      border: 1px solid var(--border-subtle);
      border-radius: 4px;
      color: #eee;
      outline: none;
    }
    .flags-search:focus {
      border-color: var(--accent);
    }
    .flags-search::placeholder {
      color: var(--text-dim);
    }
    .flags-filter-group {
      display: flex;
      gap: 0;
    }
    .flags-filter-btn {
      padding: 0.3rem 0.7rem;
      font-size: 0.75rem;
      background: var(--surface-2);
      color: var(--text-dim);
      border: 1px solid var(--border-subtle);
      cursor: pointer;
      transition: background 0.15s, color 0.15s;
    }
    .flags-filter-btn:first-child { border-radius: 4px 0 0 4px; }
    .flags-filter-btn:last-child { border-radius: 0 4px 4px 0; }
    .flags-filter-btn + .flags-filter-btn { border-left: none; }
    .flags-filter-btn.active {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
    }
    .flags-filter-btn:hover:not(.active) {
      background: rgba(255,255,255,0.05);
      color: #ccc;
    }

    /* Stats bar */
    .flags-stats {
      font-size: 0.75rem;
      color: var(--text-dim);
      margin-bottom: 0.75rem;
    }
    .flags-stats span {
      margin-right: 1rem;
    }

    /* Flag table */
    .flags-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.8rem;
    }
    .flags-table th {
      text-align: left;
      padding: 0.4rem 0.6rem;
      color: var(--text-dim);
      font-weight: 500;
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      border-bottom: 1px solid var(--border-subtle);
    }
    .flags-table td {
      padding: 0.4rem 0.6rem;
      color: var(--text-secondary, #ccc);
      border-bottom: 1px solid var(--border-subtle);
    }
    .flags-table tr:last-child td { border-bottom: none; }
    .flags-table tbody tr { cursor: pointer; }
    .flags-table tbody tr:hover td { background: rgba(255,255,255,0.02); }
    .flags-table tbody tr.flags-row-expanded td {
      background: rgba(255,255,255,0.04);
      border-bottom-color: transparent;
    }
    .flags-name {
      font-family: monospace;
      font-size: 0.8rem;
      max-width: 280px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .flags-value {
      font-family: monospace;
      font-size: 0.75rem;
      color: var(--text-dim);
    }

    /* Type badges */
    .flag-type-badge {
      display: inline-block;
      font-size: 0.65rem;
      padding: 0.1rem 0.4rem;
      border-radius: 3px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .flag-type-custom {
      background: rgba(72,199,142,0.15);
      color: var(--status-ok, #48c78e);
      border: 1px solid rgba(72,199,142,0.3);
    }
    .flag-type-event {
      background: rgba(200,200,200,0.1);
      color: var(--text-dim);
      border: 1px solid rgba(200,200,200,0.2);
    }
    .flag-type-free {
      background: rgba(100,100,100,0.1);
      color: var(--text-muted, #666);
      border: 1px solid rgba(100,100,100,0.2);
    }

    /* Detail panel (inline expansion) */
    .flags-detail {
      padding: 0.75rem 0.6rem;
      background: var(--surface-2);
      border-bottom: 1px solid var(--border-subtle);
    }
    .flags-detail-header {
      display: flex;
      align-items: center;
      gap: 1rem;
      margin-bottom: 0.5rem;
    }
    .flags-detail-name {
      font-family: monospace;
      font-size: 0.9rem;
      color: #eee;
      font-weight: 600;
    }
    .flags-detail-meta {
      font-size: 0.75rem;
      color: var(--text-dim);
    }
    .flags-detail-meta span { margin-right: 1rem; }

    /* Cross-references */
    .flags-refs-loading {
      font-size: 0.75rem;
      color: var(--text-dim);
      font-style: italic;
      padding: 0.5rem 0;
    }
    .flags-ref-group {
      margin-top: 0.5rem;
    }
    .flags-ref-group-label {
      font-size: 0.7rem;
      font-weight: 600;
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 0.3rem;
    }
    .flags-ref-item {
      font-size: 0.75rem;
      padding: 0.15rem 0;
      color: var(--text-dim);
    }
    .flags-ref-file {
      font-family: monospace;
      font-size: 0.7rem;
    }
    .flags-ref-line {
      font-family: monospace;
      font-size: 0.7rem;
      color: var(--text-muted, #666);
      margin-left: 1rem;
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      max-width: 500px;
    }
    .flags-no-refs {
      font-size: 0.75rem;
      color: var(--text-muted, #666);
      font-style: italic;
    }

    /* Delete actions in detail */
    .flags-detail-actions {
      margin-top: 0.75rem;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }
    .flags-padlock {
      background: none;
      border: 1px solid var(--border-subtle);
      border-radius: 4px;
      padding: 0.2rem 0.4rem;
      cursor: pointer;
      font-size: 0.85rem;
      line-height: 1;
    }
    .flags-delete-btn {
      padding: 0.3rem 0.7rem;
      font-size: 0.75rem;
      background: rgba(244,67,54,0.1);
      color: var(--status-error, #f44);
      border: 1px solid rgba(244,67,54,0.3);
      border-radius: 4px;
      cursor: pointer;
      transition: background 0.15s;
    }
    .flags-delete-btn:disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }
    .flags-delete-btn:not(:disabled):hover {
      background: rgba(244,67,54,0.2);
    }
    .flags-ref-warning {
      font-size: 0.75rem;
      color: var(--status-error, #f44);
      margin-top: 0.3rem;
    }

    /* Create form */
    .flags-create-form {
      display: flex;
      flex-wrap: wrap;
      align-items: flex-end;
      gap: 0.75rem;
      margin-bottom: 1rem;
      padding: 0.75rem;
      background: var(--surface-2);
      border: 1px solid var(--border-subtle);
      border-radius: 4px;
    }
    .flags-create-field {
      display: flex;
      flex-direction: column;
      gap: 0.25rem;
    }
    .flags-create-field label {
      font-size: 0.7rem;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .flags-create-field input,
    .flags-create-field select {
      padding: 0.35rem 0.5rem;
      font-size: 0.8rem;
      background: rgba(0,0,0,0.2);
      border: 1px solid var(--border-subtle);
      border-radius: 4px;
      color: #eee;
      outline: none;
      font-family: monospace;
    }
    .flags-create-field input:focus,
    .flags-create-field select:focus {
      border-color: var(--accent);
    }
    .flags-create-btn {
      padding: 0.4rem 0.8rem;
      font-size: 0.8rem;
      background: var(--accent);
      color: #fff;
      border: none;
      border-radius: 4px;
      cursor: pointer;
    }
    .flags-create-btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .flags-create-cancel {
      padding: 0.4rem 0.8rem;
      font-size: 0.8rem;
      background: none;
      color: var(--text-dim);
      border: 1px solid var(--border-subtle);
      border-radius: 4px;
      cursor: pointer;
    }
    .flags-create-error {
      width: 100%;
      font-size: 0.75rem;
      color: var(--status-error, #f44);
    }
    .flags-empty {
      text-align: center;
      padding: 2rem;
      color: var(--text-dim);
      font-size: 0.85rem;
    }

    /* New flag button */
    .flags-new-btn {
      padding: 0.35rem 0.7rem;
      font-size: 0.8rem;
      background: var(--accent);
      color: #fff;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      white-space: nowrap;
    }
    .flags-new-btn:hover { opacity: 0.9; }
  `;
  document.body.appendChild(style);
}


// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadFlags() {
  const resp = await api("/flags");
  if (resp.ok) {
    allFlags = resp.data.flags || [];
    stats = resp.data.stats || {};
  } else {
    allFlags = [];
    stats = {};
  }
  applyFilters();
}

function applyFilters() {
  let list = allFlags;
  if (activeFilter !== "all") {
    list = list.filter(f => f.type === activeFilter);
  }
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    list = list.filter(f =>
      f.name.toLowerCase().includes(q) ||
      (f.comment && f.comment.toLowerCase().includes(q))
    );
  }
  filteredFlags = list;
}


// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function renderAll() {
  if (!_container) return;

  let html = renderStudioNavbar("Flags");

  // Toolbar: search + filters + new button
  html += `<div class="flags-toolbar">`;
  html += `<input class="flags-search" type="text" placeholder="Search flags..." value="${esc(searchQuery)}">`;
  html += `<div class="flags-filter-group">`;
  for (const f of ["all", "custom", "event", "free"]) {
    const active = f === activeFilter ? " active" : "";
    html += `<button class="flags-filter-btn${active}" data-filter="${f}">${esc(f.charAt(0).toUpperCase() + f.slice(1))}</button>`;
  }
  html += `</div>`;
  html += `<button class="flags-new-btn" id="flags-new-btn">+ New Flag</button>`;
  html += `</div>`;

  // Create form (hidden by default)
  html += `<div id="flags-create-form-wrap"></div>`;

  // Stats bar
  html += `<div class="flags-stats">`;
  html += `<span>Total: ${stats.total || 0}</span>`;
  html += `<span>Custom: ${stats.custom || 0}</span>`;
  html += `<span>Event: ${stats.event || 0}</span>`;
  html += `<span>Free: ${stats.free || 0}</span>`;
  html += `</div>`;

  // Flag table
  if (filteredFlags.length === 0) {
    html += `<div class="flags-empty">No flags match the current filter.</div>`;
  } else {
    html += `<table class="flags-table"><thead><tr>`;
    html += `<th>Name</th><th>Value</th><th>Type</th><th>Comment</th>`;
    html += `</tr></thead><tbody>`;
    for (const flag of filteredFlags) {
      const isExpanded = expandedFlag === flag.name;
      const rowClass = isExpanded ? " flags-row-expanded" : "";
      html += `<tr class="flags-row${rowClass}" data-flag="${esc(flag.name)}">`;
      html += `<td class="flags-name">${esc(flag.name)}</td>`;
      html += `<td class="flags-value">${esc(flag.value)}</td>`;
      html += `<td><span class="flag-type-badge flag-type-${esc(flag.type)}">${esc(flag.type)}</span></td>`;
      html += `<td>${esc(flag.comment || "")}</td>`;
      html += `</tr>`;
      if (isExpanded) {
        html += `<tr class="flags-detail-row"><td colspan="4">`;
        html += renderDetailPanel(flag);
        html += `</td></tr>`;
      }
    }
    html += `</tbody></table>`;
  }

  _container.innerHTML = html;
  bindEvents();
}

function renderDetailPanel(flag) {
  let html = `<div class="flags-detail">`;
  html += `<div class="flags-detail-header">`;
  html += `<span class="flags-detail-name">${esc(flag.name)}</span>`;
  html += `<span class="flag-type-badge flag-type-${esc(flag.type)}">${esc(flag.type)}</span>`;
  html += `</div>`;
  html += `<div class="flags-detail-meta">`;
  html += `<span>Value: ${esc(flag.value)}</span>`;
  if (flag.comment) {
    html += `<span>Comment: ${esc(flag.comment)}</span>`;
  }
  html += `</div>`;

  // Cross-references
  html += `<div id="flags-refs-${esc(flag.name)}">`;
  if (expandedRefs === null) {
    html += `<div class="flags-refs-loading">Scanning...</div>`;
  } else if (expandedRefs.count === 0) {
    html += `<div class="flags-no-refs">No references found.</div>`;
  } else {
    html += renderReferences(expandedRefs);
  }
  html += `</div>`;

  // Delete button (custom flags only)
  if (flag.type === "custom") {
    html += `<div class="flags-detail-actions">`;
    html += `<button class="flags-padlock" data-flag="${esc(flag.name)}" title="Unlock to enable delete">\u{1F512}</button>`;
    html += `<button class="flags-delete-btn" data-flag="${esc(flag.name)}" disabled>Delete</button>`;
    html += `</div>`;
    if (expandedRefs && expandedRefs.count > 0) {
      // Count non-header refs
      const nonHeader = (expandedRefs.references || []).filter(
        r => r.category !== "header_define" && r.category !== "header_alias"
      ).length;
      if (nonHeader > 0) {
        html += `<div class="flags-ref-warning">${nonHeader} reference(s) in game files will NOT be removed by deletion.</div>`;
      }
    }
  }

  html += `</div>`;
  return html;
}

const CAT_LABELS = {
  header_define: "Header (define)",
  header_alias: "Header (alias)",
  script_pory: "Poryscript",
  script_inc: "Assembly Script",
  map_json: "Map JSON",
  c_source: "C Source",
  other: "Other",
};

function renderReferences(data) {
  const refs = data.references || [];
  // Group by category
  const groups = {};
  for (const ref of refs) {
    const cat = ref.category || "other";
    if (!groups[cat]) groups[cat] = [];
    groups[cat].push(ref);
  }

  let html = "";
  for (const [cat, catRefs] of Object.entries(groups).sort()) {
    const label = CAT_LABELS[cat] || cat;
    html += `<div class="flags-ref-group">`;
    html += `<div class="flags-ref-group-label">${esc(label)} (${catRefs.length})</div>`;
    const showing = catRefs.slice(0, 20);
    for (const ref of showing) {
      html += `<div class="flags-ref-item">`;
      html += `<span class="flags-ref-file">${esc(ref.file)}:${ref.line_num}</span>`;
      html += `<span class="flags-ref-line">${esc((ref.line_text || "").slice(0, 120))}</span>`;
      html += `</div>`;
    }
    if (catRefs.length > 20) {
      html += `<div class="flags-ref-item" style="color:var(--text-muted)">... and ${catRefs.length - 20} more</div>`;
    }
    html += `</div>`;
  }
  return html;
}


// ---------------------------------------------------------------------------
// Create form
// ---------------------------------------------------------------------------

function showCreateForm() {
  const wrap = document.getElementById("flags-create-form-wrap");
  if (!wrap) return;

  // Build free slot options
  const freeSlots = allFlags.filter(f => f.type === "free");

  let html = `<div class="flags-create-form">`;
  html += `<div class="flags-create-field">`;
  html += `<label>Flag Name</label>`;
  html += `<input type="text" id="flags-create-name" placeholder="FLAG_MY_FLAG" style="width:220px">`;
  html += `</div>`;
  html += `<div class="flags-create-field">`;
  html += `<label>Target Slot (optional)</label>`;
  html += `<select id="flags-create-target" style="width:200px">`;
  html += `<option value="">Auto (first free)</option>`;
  for (const slot of freeSlots) {
    html += `<option value="${esc(slot.name)}">${esc(slot.name)} (${esc(slot.value)})</option>`;
  }
  html += `</select>`;
  html += `</div>`;
  html += `<button class="flags-create-btn" id="flags-create-submit">Create</button>`;
  html += `<button class="flags-create-cancel" id="flags-create-cancel">Cancel</button>`;
  html += `<div class="flags-create-error" id="flags-create-error"></div>`;
  html += `</div>`;

  wrap.innerHTML = html;

  // Bind create form events
  const nameInput = document.getElementById("flags-create-name");
  const submitBtn = document.getElementById("flags-create-submit");
  const cancelBtn = document.getElementById("flags-create-cancel");

  cancelBtn.addEventListener("click", () => { wrap.innerHTML = ""; });

  nameInput.addEventListener("input", () => {
    const errEl = document.getElementById("flags-create-error");
    if (errEl) errEl.textContent = "";
  });

  submitBtn.addEventListener("click", async () => {
    const errEl = document.getElementById("flags-create-error");
    let name = nameInput.value.trim().toUpperCase();
    if (!name) {
      if (errEl) errEl.textContent = "Flag name is required.";
      return;
    }
    if (!name.startsWith("FLAG_")) name = "FLAG_" + name;
    if (!/^FLAG_[A-Z][A-Z0-9_]*$/.test(name)) {
      if (errEl) errEl.textContent = "Name must be FLAG_ followed by uppercase letters, digits, underscores.";
      return;
    }

    const targetSelect = document.getElementById("flags-create-target");
    const target = targetSelect ? targetSelect.value : "";

    submitBtn.disabled = true;
    submitBtn.textContent = "Creating...";

    try {
      const body = { name };
      if (target) body.target = target;
      const resp = await postApi("/flags", body);
      if (resp.ok) {
        wrap.innerHTML = "";
        expandedFlag = resp.data.created || name;
        expandedRefs = null;
        await loadFlags();
        renderAll();
        // Fetch refs for newly created flag
        fetchRefsForExpanded();
        // Scroll to new flag
        scrollToFlag(expandedFlag);
      } else {
        if (errEl) errEl.textContent = resp.error || "Creation failed.";
        submitBtn.disabled = false;
        submitBtn.textContent = "Create";
      }
    } catch (err) {
      if (errEl) errEl.textContent = err.message || "Creation failed.";
      submitBtn.disabled = false;
      submitBtn.textContent = "Create";
    }
  });

  nameInput.focus();
}

function scrollToFlag(flagName) {
  const row = _container.querySelector(`tr[data-flag="${flagName}"]`);
  if (row) row.scrollIntoView({ behavior: "smooth", block: "center" });
}


// ---------------------------------------------------------------------------
// Cross-reference fetch
// ---------------------------------------------------------------------------

async function fetchRefsForExpanded() {
  if (!expandedFlag) return;
  const flagName = expandedFlag;
  try {
    const resp = await api(`/flags/${encodeURIComponent(flagName)}/references`);
    if (expandedFlag !== flagName) return; // user navigated away
    if (resp.ok) {
      expandedRefs = resp.data;
    } else {
      expandedRefs = { flag: flagName, references: [], count: 0 };
    }
  } catch (_) {
    expandedRefs = { flag: flagName, references: [], count: 0 };
  }
  renderAll();
}


// ---------------------------------------------------------------------------
// Event binding
// ---------------------------------------------------------------------------

function bindEvents() {
  if (!_container) return;

  // Search input
  const searchInput = _container.querySelector(".flags-search");
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        searchQuery = e.target.value;
        applyFilters();
        renderAll();
      }, 300);
    });
  }

  // Filter buttons
  _container.querySelectorAll(".flags-filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      activeFilter = btn.dataset.filter;
      applyFilters();
      renderAll();
    });
  });

  // New flag button
  const newBtn = document.getElementById("flags-new-btn");
  if (newBtn) {
    newBtn.addEventListener("click", () => showCreateForm());
  }

  // Row clicks -> expand/collapse detail
  _container.querySelectorAll("tr.flags-row").forEach(row => {
    row.addEventListener("click", () => {
      const flagName = row.dataset.flag;
      if (expandedFlag === flagName) {
        expandedFlag = null;
        expandedRefs = null;
        renderAll();
      } else {
        expandedFlag = flagName;
        expandedRefs = null;
        renderAll();
        fetchRefsForExpanded();
      }
    });
  });

  // Padlock + delete buttons
  _container.querySelectorAll(".flags-padlock").forEach(padlock => {
    padlock.addEventListener("click", (e) => {
      e.stopPropagation();
      const flagName = padlock.dataset.flag;
      const deleteBtn = _container.querySelector(`.flags-delete-btn[data-flag="${flagName}"]`);
      const isLocked = padlock.textContent === "\u{1F512}";
      padlock.textContent = isLocked ? "\u{1F513}" : "\u{1F512}";
      if (deleteBtn) deleteBtn.disabled = !isLocked;
    });
  });

  _container.querySelectorAll(".flags-delete-btn").forEach(deleteBtn => {
    deleteBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const flagName = deleteBtn.dataset.flag;

      const confirmed = confirm(
        `Delete custom flag "${flagName}"?\n\nThis removes the alias from flags.h. ` +
        `Any references in scripts or code will NOT be updated automatically.`
      );
      if (!confirmed) return;

      deleteBtn.disabled = true;
      deleteBtn.textContent = "Deleting...";
      const padlock = _container.querySelector(`.flags-padlock[data-flag="${flagName}"]`);
      if (padlock) padlock.disabled = true;

      try {
        const resp = await postApi("/flags/delete", { name: flagName });
        if (resp.ok) {
          expandedFlag = null;
          expandedRefs = null;
          await loadFlags();
          renderAll();
        } else {
          alert(`Error: ${resp.error || "Unknown error"}`);
          deleteBtn.textContent = "Delete";
          deleteBtn.disabled = false;
          if (padlock) padlock.disabled = false;
        }
      } catch (err) {
        alert(`Error: ${err.message}`);
        deleteBtn.textContent = "Delete";
        deleteBtn.disabled = false;
        if (padlock) padlock.disabled = false;
      }
    });
  });

  // Auto-relock padlocks on outside click
  if (_relockHandler) document.removeEventListener("click", _relockHandler);
  _relockHandler = () => {
    if (!_container) return;
    _container.querySelectorAll(".flags-padlock").forEach(p => {
      if (p.textContent === "\u{1F513}") {
        p.textContent = "\u{1F512}";
        const btn = p.parentElement.querySelector(".flags-delete-btn");
        if (btn) btn.disabled = true;
      }
    });
  };
  document.addEventListener("click", _relockHandler);
}


// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function render(container) {
  injectCSS();
  _container = container;
  container.innerHTML = `<p style="color:var(--text-dim)">Loading flags...</p>`;

  try {
    await loadFlags();
    renderAll();
  } catch (err) {
    container.innerHTML = `<article><p style="color:var(--status-error)">${esc(err.message)}</p></article>`;
  }
}

export function cleanup() {
  allFlags = [];
  stats = {};
  filteredFlags = [];
  activeFilter = "all";
  searchQuery = "";
  expandedFlag = null;
  expandedRefs = null;
  _container = null;
  if (debounceTimer) {
    clearTimeout(debounceTimer);
    debounceTimer = null;
  }
  if (_relockHandler) {
    document.removeEventListener("click", _relockHandler);
    _relockHandler = null;
  }
}
