/**
 * TORCH Web GUI — SCORCH view.
 *
 * Selective (Singe) and total (Phoenix) vanilla content removal.
 * Two tabs: Singe shows category grid with drill-down item lists,
 * Phoenix shows plan preview with padlock-confirmed execution.
 */

import { api, postApi } from "../app.js";
import { esc, createModal } from "../utils.js";

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _container = null;
let activeTab = "singe";           // "singe" | "phoenix"
let preflightStatus = null;        // {ready, issues} or null (loading)
let scanData = null;               // full scan result
let categoryItems = {};            // category_id -> items array (lazy-loaded)
let selectedCategory = null;       // currently drilled-into category id
let selectedItems = new Set();     // names of items selected for removal
let searchQuery = "";
let debounceTimer = null;
let phoenixPlan = null;            // phoenix plan data or null
let snapshotsData = null;          // list of snapshots
let showSnapshots = false;
let _relockHandler = null;
let removing = false;              // removal in progress
let phoenixExecuting = false;      // phoenix in progress

// ---------------------------------------------------------------------------
// CSS
// ---------------------------------------------------------------------------

const STYLE_ID = "scorch-view-css";

function injectCSS() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    /* Tabs */
    .scorch-tabs {
      display: flex;
      gap: 0;
      margin-bottom: 1.5rem;
      border-bottom: 2px solid var(--border-subtle);
    }
    .scorch-tab {
      padding: 0.5rem 1.2rem;
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--text-dim);
      background: none;
      border: none;
      border-bottom: 2px solid transparent;
      margin-bottom: -2px;
      cursor: pointer;
      transition: color 0.15s, border-color 0.15s;
    }
    .scorch-tab:hover { color: #ccc; }
    .scorch-tab.active {
      color: var(--accent);
      border-bottom-color: var(--accent);
    }
    .scorch-tab-phoenix.active {
      color: #e85050;
      border-bottom-color: #e85050;
    }

    /* Preflight banner */
    .scorch-preflight {
      padding: 0.6rem 0.8rem;
      border-radius: 4px;
      margin-bottom: 1rem;
      font-size: 0.8rem;
    }
    .scorch-preflight-ok {
      background: rgba(72,199,142,0.1);
      border: 1px solid rgba(72,199,142,0.3);
      color: var(--status-ok, #48c78e);
    }
    .scorch-preflight-warn {
      background: rgba(232,160,32,0.1);
      border: 1px solid rgba(232,160,32,0.3);
      color: #e8a020;
    }
    .scorch-preflight-err {
      background: rgba(244,67,54,0.1);
      border: 1px solid rgba(244,67,54,0.3);
      color: var(--status-error, #f44);
    }

    /* Category grid */
    .scorch-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
      gap: 0.75rem;
      margin-bottom: 1.5rem;
    }
    .scorch-card {
      background: var(--surface-2);
      border: 1px solid var(--border-subtle);
      border-radius: 6px;
      padding: 1rem;
      cursor: pointer;
      transition: border-color 0.15s, background 0.15s;
    }
    .scorch-card:hover {
      border-color: var(--border-emphasis);
      background: rgba(255,255,255,0.03);
    }
    .scorch-card-header {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      margin-bottom: 0.5rem;
    }
    .scorch-card-icon { font-size: 1.3rem; line-height: 1; }
    .scorch-card-name {
      font-weight: 600;
      font-size: 0.9rem;
      color: #eee;
    }
    .scorch-card-stats {
      font-size: 0.75rem;
      color: var(--text-dim);
      display: flex;
      flex-direction: column;
      gap: 0.15rem;
    }
    .scorch-card-total {
      font-size: 0.8rem;
      color: var(--text-secondary, #ccc);
      font-weight: 600;
      margin-bottom: 0.2rem;
    }
    .scorch-stat-safe { color: var(--status-ok, #48c78e); }
    .scorch-stat-blocked { color: var(--status-error, #f44); }

    /* Category detail view */
    .scorch-detail-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-bottom: 1rem;
    }
    .scorch-detail-title {
      font-size: 1rem;
      font-weight: 600;
      color: #eee;
    }
    .scorch-detail-stats {
      font-size: 0.75rem;
      color: var(--text-dim);
    }
    .scorch-detail-stats span { margin-right: 1rem; }
    .scorch-back-btn {
      padding: 0.3rem 0.7rem;
      font-size: 0.8rem;
      background: none;
      color: var(--text-dim);
      border: 1px solid var(--border-subtle);
      border-radius: 4px;
      cursor: pointer;
    }
    .scorch-back-btn:hover { color: #ccc; border-color: var(--border-emphasis); }

    /* Toolbar */
    .scorch-toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.75rem;
      margin-bottom: 0.75rem;
    }
    .scorch-search {
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
    .scorch-search:focus { border-color: var(--accent); }
    .scorch-search::placeholder { color: var(--text-dim); }
    .scorch-select-btns {
      display: flex;
      gap: 0.3rem;
    }
    .scorch-select-btn {
      padding: 0.3rem 0.6rem;
      font-size: 0.72rem;
      background: var(--surface-2);
      color: var(--text-dim);
      border: 1px solid var(--border-subtle);
      border-radius: 4px;
      cursor: pointer;
    }
    .scorch-select-btn:hover { color: #ccc; }

    /* Item table */
    .scorch-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.8rem;
    }
    .scorch-table th {
      text-align: left;
      padding: 0.4rem 0.6rem;
      color: var(--text-dim);
      font-weight: 500;
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      border-bottom: 1px solid var(--border-subtle);
    }
    .scorch-table td {
      padding: 0.4rem 0.6rem;
      color: var(--text-secondary, #ccc);
      border-bottom: 1px solid var(--border-subtle);
    }
    .scorch-table tr:last-child td { border-bottom: none; }
    .scorch-table tbody tr:hover td { background: rgba(255,255,255,0.02); }
    .scorch-item-name {
      font-family: monospace;
      font-size: 0.8rem;
      max-width: 300px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .scorch-item-checkbox {
      width: 16px;
      height: 16px;
      cursor: pointer;
    }
    .scorch-item-checkbox:disabled { cursor: not-allowed; opacity: 0.3; }

    /* Status badges */
    .scorch-status-badge {
      display: inline-block;
      font-size: 0.65rem;
      padding: 0.1rem 0.4rem;
      border-radius: 3px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .scorch-status-SAFE {
      background: rgba(72,199,142,0.15);
      color: var(--status-ok, #48c78e);
      border: 1px solid rgba(72,199,142,0.3);
    }
    .scorch-status-BLOCKED {
      background: rgba(244,67,54,0.1);
      color: var(--status-error, #f44);
      border: 1px solid rgba(244,67,54,0.3);
    }
    .scorch-status-CAUTION {
      background: rgba(232,160,32,0.1);
      color: #e8a020;
      border: 1px solid rgba(232,160,32,0.3);
    }

    /* Detail/refs tooltip */
    .scorch-item-detail {
      font-size: 0.72rem;
      color: var(--text-dim);
      max-width: 350px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .scorch-refs-tooltip {
      font-size: 0.7rem;
      color: var(--text-dim);
      padding-left: 1rem;
      max-height: 100px;
      overflow-y: auto;
    }
    .scorch-refs-tooltip div {
      padding: 0.1rem 0;
      font-family: monospace;
    }

    /* Remove button */
    .scorch-remove-bar {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin-top: 1rem;
      padding: 0.75rem;
      background: var(--surface-2);
      border: 1px solid var(--border-subtle);
      border-radius: 4px;
    }
    .scorch-remove-count {
      font-size: 0.8rem;
      color: var(--text-secondary, #ccc);
    }
    .scorch-remove-btn {
      padding: 0.4rem 0.8rem;
      font-size: 0.8rem;
      background: rgba(244,67,54,0.15);
      color: #e85050;
      border: 1px solid rgba(244,67,54,0.3);
      border-radius: 4px;
      cursor: pointer;
      font-weight: 600;
      transition: background 0.15s;
    }
    .scorch-remove-btn:disabled { opacity: 0.4; cursor: not-allowed; }
    .scorch-remove-btn:not(:disabled):hover { background: rgba(244,67,54,0.25); }

    /* Confirm modal */
    .scorch-confirm-backdrop {
      position: fixed; inset: 0; background: rgba(0,0,0,0.65);
      display: flex; align-items: center; justify-content: center; z-index: 1000;
    }
    .scorch-confirm {
      background: var(--surface-2, #1e1e2e);
      border: 1px solid var(--border-subtle, #313244);
      border-radius: 8px;
      padding: 1.5rem;
      max-width: 480px;
      width: 90%;
    }
    .scorch-confirm-title {
      font-size: 1rem;
      font-weight: 600;
      color: #e85050;
      margin-bottom: 0.75rem;
    }
    .scorch-confirm-text {
      font-size: 0.85rem;
      color: var(--text-secondary, #ccc);
      margin-bottom: 1rem;
      line-height: 1.4;
    }
    .scorch-confirm-input {
      width: 100%;
      padding: 0.4rem 0.6rem;
      font-size: 0.85rem;
      background: rgba(0,0,0,0.2);
      border: 1px solid var(--border-subtle);
      border-radius: 4px;
      color: #eee;
      outline: none;
      font-family: monospace;
      margin-bottom: 1rem;
      box-sizing: border-box;
    }
    .scorch-confirm-input:focus { border-color: var(--accent); }
    .scorch-confirm-actions {
      display: flex;
      gap: 0.5rem;
      justify-content: flex-end;
    }
    .scorch-confirm-cancel {
      padding: 0.4rem 0.8rem;
      font-size: 0.8rem;
      background: none;
      color: var(--text-dim);
      border: 1px solid var(--border-subtle);
      border-radius: 4px;
      cursor: pointer;
    }
    .scorch-confirm-exec {
      padding: 0.4rem 0.8rem;
      font-size: 0.8rem;
      background: rgba(244,67,54,0.15);
      color: #e85050;
      border: 1px solid rgba(244,67,54,0.3);
      border-radius: 4px;
      cursor: pointer;
      font-weight: 600;
    }
    .scorch-confirm-exec:disabled { opacity: 0.4; cursor: not-allowed; }
    .scorch-confirm-error {
      font-size: 0.75rem;
      color: var(--status-error, #f44);
      margin-top: 0.5rem;
    }

    /* Phoenix panel */
    .scorch-phoenix-card {
      background: var(--surface-2);
      border: 1px solid var(--border-subtle);
      border-radius: 6px;
      padding: 1rem 1.25rem;
      margin-bottom: 1rem;
    }
    .scorch-phoenix-title {
      font-size: 1rem;
      font-weight: 600;
      color: #e85050;
      margin-bottom: 0.75rem;
    }
    .scorch-phoenix-summary {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
      gap: 0.5rem;
      margin-bottom: 1rem;
    }
    .scorch-phoenix-stat {
      font-size: 0.8rem;
      color: var(--text-secondary, #ccc);
    }
    .scorch-phoenix-stat-label {
      font-size: 0.7rem;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .scorch-phoenix-stat-nuke { color: #e85050; font-weight: 600; }
    .scorch-phoenix-stat-keep { color: var(--status-ok, #48c78e); font-weight: 600; }
    .scorch-phoenix-errors {
      font-size: 0.8rem;
      color: var(--status-error, #f44);
      margin-bottom: 0.75rem;
    }
    .scorch-phoenix-maps {
      font-size: 0.72rem;
      color: var(--text-dim);
      max-height: 120px;
      overflow-y: auto;
      font-family: monospace;
      margin-bottom: 1rem;
      padding: 0.5rem;
      background: rgba(0,0,0,0.15);
      border-radius: 4px;
    }

    /* Snapshots section */
    .scorch-snapshots-toggle {
      padding: 0.3rem 0.7rem;
      font-size: 0.8rem;
      background: none;
      color: var(--text-dim);
      border: 1px solid var(--border-subtle);
      border-radius: 4px;
      cursor: pointer;
      margin-bottom: 1rem;
    }
    .scorch-snapshots-toggle:hover { color: #ccc; }
    .scorch-snapshot-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.8rem;
      margin-top: 0.5rem;
    }
    .scorch-snapshot-table th {
      text-align: left;
      padding: 0.4rem 0.6rem;
      color: var(--text-dim);
      font-weight: 500;
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      border-bottom: 1px solid var(--border-subtle);
    }
    .scorch-snapshot-table td {
      padding: 0.4rem 0.6rem;
      color: var(--text-secondary, #ccc);
      border-bottom: 1px solid var(--border-subtle);
    }
    .scorch-snapshot-table tr:last-child td { border-bottom: none; }
    .scorch-snapshot-filename {
      font-family: monospace;
      font-size: 0.75rem;
      max-width: 280px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .scorch-snapshot-type {
      display: inline-block;
      font-size: 0.65rem;
      padding: 0.1rem 0.4rem;
      border-radius: 3px;
      font-weight: 600;
      text-transform: uppercase;
    }
    .scorch-snapshot-singe {
      background: rgba(232,160,32,0.15);
      color: #e8a020;
      border: 1px solid rgba(232,160,32,0.3);
    }
    .scorch-snapshot-phoenix {
      background: rgba(244,67,54,0.1);
      color: #e85050;
      border: 1px solid rgba(244,67,54,0.3);
    }
    .scorch-restore-btn {
      padding: 0.25rem 0.5rem;
      font-size: 0.72rem;
      background: none;
      color: var(--accent);
      border: 1px solid var(--accent);
      border-radius: 3px;
      cursor: pointer;
    }
    .scorch-restore-btn:hover { background: var(--accent); color: #111; }
    .scorch-restore-btn:disabled { opacity: 0.4; cursor: not-allowed; }

    /* Expanded row (refs) */
    .scorch-expanded-row td {
      background: var(--surface-2);
      border-bottom: 1px solid var(--border-subtle);
    }

    /* Loading / empty */
    .scorch-loading {
      text-align: center;
      padding: 2rem;
      color: var(--text-dim);
      font-size: 0.85rem;
    }
    .scorch-empty {
      text-align: center;
      padding: 2rem;
      color: var(--text-dim);
      font-size: 0.85rem;
    }

    /* Result banner */
    .scorch-result {
      padding: 0.75rem 1rem;
      border-radius: 4px;
      margin-bottom: 1rem;
      font-size: 0.85rem;
    }
    .scorch-result-ok {
      background: rgba(72,199,142,0.1);
      border: 1px solid rgba(72,199,142,0.3);
      color: var(--status-ok, #48c78e);
    }
    .scorch-result-err {
      background: rgba(244,67,54,0.1);
      border: 1px solid rgba(244,67,54,0.3);
      color: var(--status-error, #f44);
    }
  `;
  document.body.appendChild(style);
}


// ---------------------------------------------------------------------------
// Category icons
// ---------------------------------------------------------------------------

const CAT_ICONS = {
  maps: "&#x1F5FA;",       // world map
  trainers: "&#x2694;",    // crossed swords
  encounters: "&#x1F43E;", // paw prints
  frontier: "&#x1F3DF;",   // stadium
  scripts: "&#x1F4DC;",    // scroll
  tilesets: "&#x1F3A8;",   // palette
  graphics: "&#x1F5BC;",   // frame
  music: "&#x1F3B5;",      // musical note
};

const CAT_LABELS = {
  maps: "Maps",
  trainers: "Trainers",
  encounters: "Encounters",
  frontier: "Battle Frontier",
  scripts: "Scripts",
  tilesets: "Tilesets",
  graphics: "Graphics",
  music: "Music",
};


// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadPreflight() {
  try {
    const resp = await api("/scorch/status");
    if (resp.ok) {
      preflightStatus = resp.data;
    } else {
      preflightStatus = { ready: false, issues: [resp.error || "Unknown error"] };
    }
  } catch (e) {
    preflightStatus = { ready: false, issues: [e.message] };
  }
}

async function loadFullScan() {
  try {
    const resp = await api("/scorch/scan");
    if (resp.ok) {
      scanData = resp.data;
      // Index items by category for quick access
      categoryItems = {};
      for (const item of (scanData.items || [])) {
        const cat = item.category;
        if (!categoryItems[cat]) categoryItems[cat] = [];
        categoryItems[cat].push(item);
      }
    } else {
      scanData = null;
    }
  } catch (_) {
    scanData = null;
  }
}

async function loadCategoryItems(cat) {
  if (categoryItems[cat]) return; // already loaded from full scan
  try {
    const resp = await api(`/scorch/scan/${cat}`);
    if (resp.ok) {
      categoryItems[cat] = resp.data.items || [];
    }
  } catch (_) {
    // leave empty
  }
}

async function loadPhoenixPlan() {
  try {
    const resp = await api("/scorch/phoenix/plan");
    if (resp.ok) {
      phoenixPlan = resp.data;
    } else {
      phoenixPlan = { errors: [resp.error], summary: {}, ready: false };
    }
  } catch (e) {
    phoenixPlan = { errors: [e.message], summary: {}, ready: false };
  }
}

async function loadSnapshots() {
  try {
    const resp = await api("/scorch/snapshots");
    if (resp.ok) {
      snapshotsData = resp.data.snapshots || [];
    } else {
      snapshotsData = [];
    }
  } catch (_) {
    snapshotsData = [];
  }
}


// ---------------------------------------------------------------------------
// Render — main dispatcher
// ---------------------------------------------------------------------------

function renderAll() {
  if (!_container) return;
  let html = "";

  // Page header
  html += `<h2 style="margin-bottom:0.5rem">SCORCH</h2>`;
  html += `<p style="font-size:0.8rem;color:var(--text-dim);margin-bottom:1rem">Vanilla content removal</p>`;

  // Preflight
  html += renderPreflight();

  // Tabs
  html += `<div class="scorch-tabs">`;
  html += `<button class="scorch-tab${activeTab === "singe" ? " active" : ""}" data-tab="singe">Singe (Selective)</button>`;
  html += `<button class="scorch-tab scorch-tab-phoenix${activeTab === "phoenix" ? " active" : ""}" data-tab="phoenix">Phoenix (Total)</button>`;
  html += `</div>`;

  // Tab content
  if (activeTab === "singe") {
    html += renderSingeTab();
  } else {
    html += renderPhoenixTab();
  }

  // Snapshots section
  html += renderSnapshotsSection();

  _container.innerHTML = html;
  bindEvents();
}


// ---------------------------------------------------------------------------
// Render — preflight
// ---------------------------------------------------------------------------

function renderPreflight() {
  if (!preflightStatus) {
    return `<div class="scorch-loading">Checking project...</div>`;
  }
  const { ready, issues } = preflightStatus;
  if (issues.length === 0) {
    return `<div class="scorch-preflight scorch-preflight-ok">Project ready for SCORCH</div>`;
  }
  const cls = ready ? "scorch-preflight-warn" : "scorch-preflight-err";
  let html = `<div class="scorch-preflight ${cls}">`;
  for (const issue of issues) {
    html += `<div>${esc(issue)}</div>`;
  }
  html += `</div>`;
  return html;
}


// ---------------------------------------------------------------------------
// Render — Singe tab
// ---------------------------------------------------------------------------

function renderSingeTab() {
  if (!scanData) {
    return `<div class="scorch-loading">Scanning vanilla content... this may take a few seconds.</div>`;
  }

  if (selectedCategory) {
    return renderCategoryDetail(selectedCategory);
  }

  return renderCategoryGrid();
}

function renderCategoryGrid() {
  const categories = scanData.categories || [];
  if (categories.length === 0) {
    return `<div class="scorch-empty">No vanilla content detected.</div>`;
  }

  let html = `<div class="scorch-grid">`;
  for (const cat of categories) {
    const icon = CAT_ICONS[cat.id] || "&#x2753;";
    html += `<div class="scorch-card" data-category="${esc(cat.id)}">`;
    html += `<div class="scorch-card-header">`;
    html += `<span class="scorch-card-icon">${icon}</span>`;
    html += `<span class="scorch-card-name">${esc(cat.label)}</span>`;
    html += `</div>`;
    html += `<div class="scorch-card-stats">`;
    html += `<div class="scorch-card-total">${cat.total} item${cat.total !== 1 ? "s" : ""}</div>`;
    html += `<div><span class="scorch-stat-safe">${cat.safe} safe</span></div>`;
    html += `<div><span class="scorch-stat-blocked">${cat.blocked} blocked</span></div>`;
    if (cat.caution > 0) {
      html += `<div><span style="color:#e8a020">${cat.caution} caution</span></div>`;
    }
    html += `</div>`;
    html += `</div>`;
  }
  html += `</div>`;
  return html;
}

function renderCategoryDetail(catId) {
  const items = categoryItems[catId] || [];
  const label = CAT_LABELS[catId] || catId;

  // Filter items by search
  let filtered = items;
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    filtered = items.filter(i =>
      i.name.toLowerCase().includes(q) ||
      (i.detail && i.detail.toLowerCase().includes(q))
    );
  }

  const safeCount = items.filter(i => i.status === "SAFE").length;
  const blockedCount = items.filter(i => i.status === "BLOCKED").length;
  const selectedCount = selectedItems.size;

  let html = "";

  // Header
  html += `<div class="scorch-detail-header">`;
  html += `<div style="display:flex;align-items:center;gap:0.75rem">`;
  html += `<button class="scorch-back-btn" data-action="back">&#8592; Back</button>`;
  html += `<span class="scorch-detail-title">${esc(label)}</span>`;
  html += `</div>`;
  html += `<div class="scorch-detail-stats">`;
  html += `<span>Total: ${items.length}</span>`;
  html += `<span class="scorch-stat-safe">Safe: ${safeCount}</span>`;
  html += `<span class="scorch-stat-blocked">Blocked: ${blockedCount}</span>`;
  html += `</div>`;
  html += `</div>`;

  // Toolbar
  html += `<div class="scorch-toolbar">`;
  html += `<input class="scorch-search" type="text" placeholder="Search items..." value="${esc(searchQuery)}">`;
  html += `<div class="scorch-select-btns">`;
  html += `<button class="scorch-select-btn" data-action="select-all">Select All Safe</button>`;
  html += `<button class="scorch-select-btn" data-action="deselect-all">Deselect All</button>`;
  html += `</div>`;
  html += `</div>`;

  // Table
  if (filtered.length === 0) {
    html += `<div class="scorch-empty">No items match the search.</div>`;
  } else {
    html += `<table class="scorch-table"><thead><tr>`;
    html += `<th style="width:30px"></th><th>Name</th><th>Status</th><th>Detail</th>`;
    html += `</tr></thead><tbody>`;
    for (const item of filtered) {
      const isSafe = item.status === "SAFE";
      const checked = selectedItems.has(item.name) ? " checked" : "";
      const disabled = !isSafe ? " disabled" : "";
      html += `<tr data-item="${esc(item.name)}">`;
      html += `<td><input type="checkbox" class="scorch-item-checkbox" data-name="${esc(item.name)}"${checked}${disabled}></td>`;
      html += `<td class="scorch-item-name">${esc(item.name)}</td>`;
      html += `<td><span class="scorch-status-badge scorch-status-${esc(item.status)}">${esc(item.status)}</span>`;
      if (item.status === "BLOCKED" && item.refs && item.refs.length > 0) {
        const refPreview = item.refs.length <= 2
          ? item.refs.map(r => esc(r)).join(", ")
          : esc(item.refs[0]) + ", " + esc(item.refs[1]) + " +" + (item.refs.length - 2) + " more";
        html += ` <span style="color:var(--text-dim);font-size:0.7rem">(${refPreview})</span>`;
      }
      html += `</td>`;
      html += `<td class="scorch-item-detail" title="${esc(item.detail || "")}">${esc(item.detail || "")}</td>`;
      html += `</tr>`;
      // Refs row for BLOCKED items
      if (!isSafe && item.refs && item.refs.length > 0) {
        html += `<tr class="scorch-expanded-row"><td></td><td colspan="3">`;
        html += `<div class="scorch-refs-tooltip">`;
        for (const ref of item.refs.slice(0, 10)) {
          html += `<div>${esc(ref)}</div>`;
        }
        if (item.refs.length > 10) {
          html += `<div style="color:var(--text-muted)">... and ${item.refs.length - 10} more</div>`;
        }
        html += `</div></td></tr>`;
      }
    }
    html += `</tbody></table>`;
  }

  // Remove bar
  const canRemove = selectedCount > 0 && !removing;
  const removable = ["maps", "trainers", "encounters", "frontier", "scripts", "tilesets"].includes(catId);

  if (removable && safeCount > 0) {
    html += `<div class="scorch-remove-bar">`;
    html += `<span class="scorch-remove-count">${selectedCount} item${selectedCount !== 1 ? "s" : ""} selected</span>`;
    html += `<button class="scorch-remove-btn" data-action="remove"${canRemove ? "" : " disabled"}>`;
    html += removing ? "Removing..." : "Remove Selected";
    html += `</button>`;
    html += `</div>`;
  }

  return html;
}


// ---------------------------------------------------------------------------
// Render — Phoenix tab
// ---------------------------------------------------------------------------

function renderPhoenixTab() {
  if (!phoenixPlan) {
    return `<div class="scorch-loading">Loading Phoenix plan...</div>`;
  }

  let html = "";

  html += `<div class="scorch-phoenix-card">`;
  html += `<div class="scorch-phoenix-title">Scorched Earth</div>`;
  html += `<p style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:1rem">`;
  html += `Phoenix removes <strong>ALL</strong> vanilla content from your project in one operation. `;
  html += `Maps, trainers, encounters, heal locations, layouts, map sections -- everything vanilla gets nuked. `;
  html += `A snapshot is created first. This is designed for projects starting from scratch.`;
  html += `</p>`;

  if (phoenixPlan.errors && phoenixPlan.errors.length > 0) {
    html += `<div class="scorch-phoenix-errors">`;
    for (const err of phoenixPlan.errors) {
      html += `<div>${esc(err)}</div>`;
    }
    html += `</div>`;
  }

  const summary = phoenixPlan.summary || {};
  if (Object.keys(summary).length > 0) {
    html += `<div class="scorch-phoenix-summary">`;
    const labels = {
      maps: "Maps", layouts: "Layouts", trainers: "Trainers",
      encounters: "Encounters", scripts: "Scripts", tilesets: "Tilesets",
      mapsecs: "Map Sections", heal_locs: "Heal Locations", c_patches: "C Patches",
    };
    for (const [catId, data] of Object.entries(summary)) {
      const label = labels[catId] || catId;
      html += `<div class="scorch-phoenix-stat">`;
      html += `<div class="scorch-phoenix-stat-label">${esc(label)}</div>`;
      html += `<span class="scorch-phoenix-stat-nuke">${data.nuke} nuke</span>`;
      html += ` / <span class="scorch-phoenix-stat-keep">${data.keep} keep</span>`;
      html += `</div>`;
    }
    html += `</div>`;

    // Sample of maps being nuked
    if (phoenixPlan.nuke_maps_sample && phoenixPlan.nuke_maps_sample.length > 0) {
      html += `<div style="font-size:0.72rem;color:var(--text-dim);margin-bottom:0.5rem">Maps to remove (sample):</div>`;
      html += `<div class="scorch-phoenix-maps">`;
      for (const m of phoenixPlan.nuke_maps_sample) {
        html += `${esc(m)}\n`;
      }
      if (phoenixPlan.nuke_maps_sample.length >= 20) {
        html += `... and more\n`;
      }
      html += `</div>`;
    }

    // Keep maps
    if (phoenixPlan.keep_maps && phoenixPlan.keep_maps.length > 0) {
      html += `<div style="font-size:0.72rem;color:var(--text-dim);margin-bottom:0.5rem">Maps to keep:</div>`;
      html += `<div class="scorch-phoenix-maps" style="max-height:80px">`;
      for (const m of phoenixPlan.keep_maps) {
        html += `<span class="scorch-stat-safe">${esc(m)}</span>\n`;
      }
      html += `</div>`;
    }
  }

  // Execute button
  if (phoenixPlan.ready) {
    html += `<button class="scorch-remove-btn" data-action="phoenix-execute" style="font-size:0.9rem;padding:0.5rem 1.2rem"${phoenixExecuting ? " disabled" : ""}>`;
    html += phoenixExecuting ? "Executing Phoenix..." : "Execute Phoenix";
    html += `</button>`;
  }

  html += `</div>`;

  return html;
}


// ---------------------------------------------------------------------------
// Render — Snapshots
// ---------------------------------------------------------------------------

function renderSnapshotsSection() {
  let html = "";
  html += `<button class="scorch-snapshots-toggle" data-action="toggle-snapshots">`;
  html += showSnapshots ? "Hide Snapshots" : "Show Snapshots";
  html += `</button>`;

  if (!showSnapshots) return html;

  if (!snapshotsData) {
    html += `<div class="scorch-loading">Loading snapshots...</div>`;
    return html;
  }

  if (snapshotsData.length === 0) {
    html += `<div class="scorch-empty">No SCORCH snapshots found.</div>`;
    return html;
  }

  html += `<table class="scorch-snapshot-table"><thead><tr>`;
  html += `<th>Filename</th><th>Type</th><th>Date</th><th>Category</th><th></th>`;
  html += `</tr></thead><tbody>`;
  for (const snap of snapshotsData) {
    const typeClass = snap.type === "phoenix" ? "scorch-snapshot-phoenix" : "scorch-snapshot-singe";
    html += `<tr>`;
    html += `<td><span class="scorch-snapshot-filename" title="${esc(snap.filename)}">${esc(snap.filename)}</span></td>`;
    html += `<td><span class="scorch-snapshot-type ${typeClass}">${esc(snap.type)}</span></td>`;
    html += `<td>${esc(snap.display_time)}</td>`;
    html += `<td>${esc(snap.category_hint || "--")}</td>`;
    html += `<td><button class="scorch-restore-btn" data-action="restore" data-path="${esc(snap.path)}" data-type="${esc(snap.type)}">Restore</button></td>`;
    html += `</tr>`;
  }
  html += `</tbody></table>`;

  return html;
}


// ---------------------------------------------------------------------------
// Confirmation modals
// ---------------------------------------------------------------------------

function showRemoveConfirmModal(catId, itemNames) {
  const label = CAT_LABELS[catId] || catId;
  const count = itemNames.length;
  const sampleNames = itemNames.slice(0, 8).map(n => esc(n)).join("<br>");
  const moreText = count > 8 ? `<br>... and ${count - 8} more` : "";

  const innerHtml = `
    <div class="scorch-confirm-title">Remove ${count} ${esc(label)} item${count !== 1 ? "s" : ""}?</div>
    <div class="scorch-confirm-text">
      <strong>Items to remove:</strong><br>
      <span style="font-family:monospace;font-size:0.75rem">${sampleNames}${moreText}</span>
      <br><br>
      A backup snapshot will be created automatically before removal.
      <br><br>
      Type <strong>${esc(label.toLowerCase())}</strong> to confirm:
    </div>
    <input type="text" class="scorch-confirm-input" id="scorch-confirm-input" placeholder="${esc(label.toLowerCase())}">
    <div class="scorch-confirm-error" id="scorch-confirm-error"></div>
    <div class="scorch-confirm-actions">
      <button class="scorch-confirm-cancel" id="scorch-confirm-cancel">Cancel</button>
      <button class="scorch-confirm-exec" id="scorch-confirm-exec" disabled>Remove</button>
    </div>
  `;

  const { el, close } = createModal("scorch-confirm", innerHtml);
  const input = el.querySelector("#scorch-confirm-input");
  const execBtn = el.querySelector("#scorch-confirm-exec");
  const cancelBtn = el.querySelector("#scorch-confirm-cancel");
  const errorEl = el.querySelector("#scorch-confirm-error");
  const confirmText = label.toLowerCase();

  input.addEventListener("input", () => {
    execBtn.disabled = input.value.trim().toLowerCase() !== confirmText;
    if (errorEl) errorEl.textContent = "";
  });

  cancelBtn.addEventListener("click", close);

  execBtn.addEventListener("click", async () => {
    if (input.value.trim().toLowerCase() !== confirmText) return;
    execBtn.disabled = true;
    execBtn.textContent = "Removing...";
    removing = true;
    renderAll();

    try {
      const resp = await postApi("/scorch/remove", {
        category: catId,
        items: itemNames,
        confirm: input.value.trim(),
      });
      close();
      removing = false;

      if (resp.ok) {
        selectedItems.clear();
        // Re-scan category
        delete categoryItems[catId];
        scanData = null;
        await loadFullScan();
        await loadCategoryItems(catId);
        renderAll();
        // Show success banner (insert at top)
        const banner = document.createElement("div");
        banner.className = "scorch-result scorch-result-ok";
        banner.textContent = `Removed ${resp.data.removed_count} item(s). Snapshot: ${resp.data.snapshot || "none"}`;
        if (resp.data.errors && resp.data.errors.length > 0) {
          banner.textContent += ` (${resp.data.errors.length} error(s))`;
        }
        _container.insertBefore(banner, _container.firstChild);
        setTimeout(() => banner.remove(), 10000);
      } else {
        if (errorEl) errorEl.textContent = resp.error || "Unknown error";
        renderAll();
        const banner = document.createElement("div");
        banner.className = "scorch-result scorch-result-err";
        banner.textContent = `Removal failed: ${resp.error || "Unknown error"}`;
        _container.insertBefore(banner, _container.firstChild);
        setTimeout(() => banner.remove(), 10000);
      }
    } catch (e) {
      close();
      removing = false;
      renderAll();
      const banner = document.createElement("div");
      banner.className = "scorch-result scorch-result-err";
      banner.textContent = `Error: ${e.message}`;
      _container.insertBefore(banner, _container.firstChild);
      setTimeout(() => banner.remove(), 10000);
    }
  });

  input.focus();
}

function showPhoenixConfirmModal() {
  const innerHtml = `
    <div class="scorch-confirm-title">Execute Scorched Earth?</div>
    <div class="scorch-confirm-text">
      This will <strong>permanently remove ALL vanilla content</strong> from your project.
      A snapshot will be created first, but this operation is designed to be irreversible in practice.
      <br><br>
      Type your <strong>project name</strong> exactly to confirm:
    </div>
    <input type="text" class="scorch-confirm-input" id="scorch-phoenix-input" placeholder="Project name">
    <div class="scorch-confirm-error" id="scorch-phoenix-error"></div>
    <div class="scorch-confirm-actions">
      <button class="scorch-confirm-cancel" id="scorch-phoenix-cancel">Cancel</button>
      <button class="scorch-confirm-exec" id="scorch-phoenix-exec" disabled>Execute Phoenix</button>
    </div>
  `;

  const { el, close } = createModal("scorch-confirm", innerHtml);
  const input = el.querySelector("#scorch-phoenix-input");
  const execBtn = el.querySelector("#scorch-phoenix-exec");
  const cancelBtn = el.querySelector("#scorch-phoenix-cancel");
  const errorEl = el.querySelector("#scorch-phoenix-error");

  // We don't know the project name on the client side, so we just
  // require non-empty input. Server validates the match.
  input.addEventListener("input", () => {
    execBtn.disabled = input.value.trim().length === 0;
    if (errorEl) errorEl.textContent = "";
  });

  cancelBtn.addEventListener("click", close);

  execBtn.addEventListener("click", async () => {
    const confirm = input.value.trim();
    if (!confirm) return;
    execBtn.disabled = true;
    execBtn.textContent = "Executing...";
    phoenixExecuting = true;
    renderAll();

    try {
      const resp = await postApi("/scorch/phoenix/execute", { confirm });
      close();
      phoenixExecuting = false;

      if (resp.ok) {
        // Reload everything
        scanData = null;
        categoryItems = {};
        phoenixPlan = null;
        await Promise.all([loadFullScan(), loadPhoenixPlan(), loadSnapshots()]);
        renderAll();
        const banner = document.createElement("div");
        banner.className = "scorch-result scorch-result-ok";
        let msg = `Phoenix complete. Removed: ${resp.data.maps_removed} maps, `;
        msg += `${resp.data.trainers_removed} trainers, ${resp.data.encounters_removed} encounters. `;
        msg += `${resp.data.patches_applied} C source patches applied.`;
        if (resp.data.errors && resp.data.errors.length > 0) {
          msg += ` (${resp.data.errors.length} error(s) -- check CLI)`;
        }
        banner.textContent = msg;
        _container.insertBefore(banner, _container.firstChild);
      } else {
        if (errorEl) errorEl.textContent = resp.error || "Unknown error";
        renderAll();
        const banner = document.createElement("div");
        banner.className = "scorch-result scorch-result-err";
        banner.textContent = `Phoenix failed: ${resp.error || "Unknown error"}`;
        _container.insertBefore(banner, _container.firstChild);
        setTimeout(() => banner.remove(), 15000);
      }
    } catch (e) {
      close();
      phoenixExecuting = false;
      renderAll();
      const banner = document.createElement("div");
      banner.className = "scorch-result scorch-result-err";
      banner.textContent = `Error: ${e.message}`;
      _container.insertBefore(banner, _container.firstChild);
      setTimeout(() => banner.remove(), 15000);
    }
  });

  input.focus();
}

async function doRestore(path, type) {
  const confirmed = confirm(
    `Restore from this snapshot?\n\nThis will overwrite current game files with the snapshot contents.`
  );
  if (!confirmed) return;

  try {
    const resp = await postApi("/scorch/restore", { path, type });
    if (resp.ok) {
      // Reload everything
      scanData = null;
      categoryItems = {};
      phoenixPlan = null;
      await Promise.all([loadPreflight(), loadFullScan(), loadSnapshots()]);
      if (activeTab === "phoenix") await loadPhoenixPlan();
      renderAll();
      const banner = document.createElement("div");
      banner.className = "scorch-result scorch-result-ok";
      banner.textContent = `Restored ${resp.data.restored_count} file(s) from snapshot.`;
      _container.insertBefore(banner, _container.firstChild);
      setTimeout(() => banner.remove(), 10000);
    } else {
      alert(`Restore failed: ${resp.error || "Unknown error"}`);
    }
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
}


// ---------------------------------------------------------------------------
// Event binding
// ---------------------------------------------------------------------------

function bindEvents() {
  if (!_container) return;

  // Tab clicks
  _container.querySelectorAll(".scorch-tab").forEach(tab => {
    tab.addEventListener("click", async () => {
      activeTab = tab.dataset.tab;
      if (activeTab === "phoenix" && !phoenixPlan) {
        renderAll(); // show loading
        await loadPhoenixPlan();
      }
      renderAll();
    });
  });

  // Category card clicks
  _container.querySelectorAll(".scorch-card").forEach(card => {
    card.addEventListener("click", async () => {
      selectedCategory = card.dataset.category;
      selectedItems.clear();
      searchQuery = "";
      await loadCategoryItems(selectedCategory);
      renderAll();
    });
  });

  // Back button
  _container.querySelectorAll("[data-action='back']").forEach(btn => {
    btn.addEventListener("click", () => {
      selectedCategory = null;
      selectedItems.clear();
      searchQuery = "";
      renderAll();
    });
  });

  // Search input
  const searchInput = _container.querySelector(".scorch-search");
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        searchQuery = e.target.value;
        renderAll();
      }, 300);
    });
  }

  // Select All / Deselect All
  _container.querySelectorAll("[data-action='select-all']").forEach(btn => {
    btn.addEventListener("click", () => {
      const items = categoryItems[selectedCategory] || [];
      for (const item of items) {
        if (item.status === "SAFE") {
          selectedItems.add(item.name);
        }
      }
      renderAll();
    });
  });
  _container.querySelectorAll("[data-action='deselect-all']").forEach(btn => {
    btn.addEventListener("click", () => {
      selectedItems.clear();
      renderAll();
    });
  });

  // Checkboxes
  _container.querySelectorAll(".scorch-item-checkbox").forEach(cb => {
    cb.addEventListener("change", (e) => {
      e.stopPropagation();
      const name = cb.dataset.name;
      if (cb.checked) {
        selectedItems.add(name);
      } else {
        selectedItems.delete(name);
      }
      // Update the remove bar count without full re-render
      const countEl = _container.querySelector(".scorch-remove-count");
      if (countEl) countEl.textContent = `${selectedItems.size} item${selectedItems.size !== 1 ? "s" : ""} selected`;
      const removeBtn = _container.querySelector(".scorch-remove-btn");
      if (removeBtn) removeBtn.disabled = selectedItems.size === 0 || removing;
    });
  });

  // Remove button
  _container.querySelectorAll("[data-action='remove']").forEach(btn => {
    btn.addEventListener("click", () => {
      if (selectedItems.size === 0 || !selectedCategory) return;
      showRemoveConfirmModal(selectedCategory, Array.from(selectedItems));
    });
  });

  // Phoenix execute
  _container.querySelectorAll("[data-action='phoenix-execute']").forEach(btn => {
    btn.addEventListener("click", () => {
      showPhoenixConfirmModal();
    });
  });

  // Snapshots toggle
  _container.querySelectorAll("[data-action='toggle-snapshots']").forEach(btn => {
    btn.addEventListener("click", async () => {
      showSnapshots = !showSnapshots;
      if (showSnapshots && !snapshotsData) {
        renderAll();
        await loadSnapshots();
      }
      renderAll();
    });
  });

  // Restore buttons
  _container.querySelectorAll("[data-action='restore']").forEach(btn => {
    btn.addEventListener("click", () => {
      doRestore(btn.dataset.path, btn.dataset.type);
    });
  });
}


// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function render(container) {
  injectCSS();
  _container = container;
  container.innerHTML = `<div class="scorch-loading">Loading SCORCH...</div>`;

  try {
    // Load preflight + full scan in parallel
    await Promise.all([loadPreflight(), loadFullScan()]);
    renderAll();
  } catch (err) {
    container.innerHTML = `<article><p style="color:var(--status-error)">${esc(err.message)}</p></article>`;
  }
}

export function cleanup() {
  _container = null;
  activeTab = "singe";
  preflightStatus = null;
  scanData = null;
  categoryItems = {};
  selectedCategory = null;
  selectedItems.clear();
  searchQuery = "";
  phoenixPlan = null;
  snapshotsData = null;
  showSnapshots = false;
  removing = false;
  phoenixExecuting = false;
  if (debounceTimer) {
    clearTimeout(debounceTimer);
    debounceTimer = null;
  }
  if (_relockHandler) {
    document.removeEventListener("click", _relockHandler);
    _relockHandler = null;
  }
}
