/**
 * TORCH Web GUI -- Move Editor view.
 * Searchable, filterable move list with per-field inline editing.
 */

import { api, postApi } from "../app.js";
import { esc } from "../utils.js";
import { renderStudioNavbar } from "../studioNav.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TYPE_COLOURS = {
  Normal:   "#A8A878", Fire:     "#F08030", Water:    "#6890F0",
  Electric: "#F8D030", Grass:    "#78C850", Ice:      "#98D8D8",
  Fighting: "#C03028", Poison:   "#A040A0", Ground:   "#E0C068",
  Flying:   "#A890F0", Psychic:  "#F85888", Bug:      "#A8B820",
  Rock:     "#B8A038", Ghost:    "#705898", Dragon:   "#7038F8",
  Dark:     "#705848", Steel:    "#B8B8D0", Fairy:    "#EE99AC",
  Stellar:  "#44AABB",
};

const CAT_COLOURS = {
  Physical: "#C03028",
  Special:  "#6890F0",
  Status:   "#888888",
};

const PAGE_SIZE = 60;

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let debounceTimer = null;
let allMoves = [];
let filteredMoves = [];
let refTypes = [];
let refCategories = [];
let refTargets = [];
let renderedCount = 0;
let scrollHandler = null;
let searchQuery = "";
let categoryFilter = "all";    // "all" | raw constant
let typeFilter = "all";        // "all" | raw constant
let activeView = "list";       // "list" | "detail"
let selectedMove = null;
let writeLock = false;
let styleEl = null;
let currentContainer = null;

// ---------------------------------------------------------------------------
// Type label helpers (mirror backend labels)
// ---------------------------------------------------------------------------

function typeLabel(raw) {
  if (!raw) return "";
  return raw.replace("TYPE_", "").replace(/_/g, " ")
    .split(" ").map(w => w.charAt(0) + w.slice(1).toLowerCase()).join(" ");
}

function catLabel(raw) {
  if (!raw) return "";
  const map = {
    "DAMAGE_CATEGORY_PHYSICAL": "Physical",
    "DAMAGE_CATEGORY_SPECIAL": "Special",
    "DAMAGE_CATEGORY_STATUS": "Status",
  };
  return map[raw] || raw;
}

function targetLabel(raw) {
  if (!raw) return "";
  return raw.replace("MOVE_TARGET_", "").replace(/_/g, " ")
    .split(" ").map(w => w.charAt(0) + w.slice(1).toLowerCase()).join(" ");
}

function typeColour(displayType) {
  return TYPE_COLOURS[displayType] || "#888";
}

// ---------------------------------------------------------------------------
// CSS
// ---------------------------------------------------------------------------

function injectStyles() {
  if (styleEl) return;
  styleEl = document.createElement("style");
  styleEl.textContent = `
/* Move Editor styles */
.mv-toolbar {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  margin-bottom: 16px;
}
.mv-search {
  flex: 1; min-width: 200px; padding: 8px 12px;
  background: var(--surface-2, #1a1a1a); color: var(--text, #e0e0e0);
  border: 1px solid var(--border, #333); border-radius: 6px;
  font-size: 14px; outline: none;
}
.mv-search:focus { border-color: var(--accent, #6890F0); }
.mv-filter-group { display: flex; gap: 4px; }
.mv-filter-btn {
  padding: 4px 10px; border-radius: 4px; border: 1px solid var(--border, #333);
  background: var(--surface-2, #1a1a1a); color: var(--text-dim, #888);
  cursor: pointer; font-size: 12px;
}
.mv-filter-btn.active {
  background: var(--accent, #6890F0); color: #fff; border-color: var(--accent, #6890F0);
}
.mv-type-select {
  padding: 4px 8px; border-radius: 4px; border: 1px solid var(--border, #333);
  background: var(--surface-2, #1a1a1a); color: var(--text, #e0e0e0);
  font-size: 12px; cursor: pointer;
}
.mv-count {
  font-size: 12px; color: var(--text-dim, #888); margin-left: auto;
}

/* Table */
.mv-table {
  width: 100%; border-collapse: collapse; font-size: 13px;
}
.mv-table thead th {
  text-align: left; padding: 8px 10px; font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.5px; color: var(--text-dim, #888);
  border-bottom: 1px solid var(--border, #333);
}
.mv-table tbody tr {
  cursor: pointer; transition: background 0.1s;
}
.mv-table tbody tr:hover { background: var(--surface-hover, #222); }
.mv-table td { padding: 6px 10px; }
.mv-type-badge {
  display: inline-block; padding: 2px 8px; border-radius: 3px;
  font-size: 11px; font-weight: 600; color: #fff;
}
.mv-cat-badge {
  display: inline-block; padding: 2px 6px; border-radius: 3px;
  font-size: 11px; font-weight: 600; color: #fff;
}
.mv-power-dash { color: var(--text-dim, #555); }

/* Detail / Edit view */
.mv-detail { max-width: 600px; }
.mv-back-btn {
  display: inline-flex; align-items: center; gap: 4px; padding: 6px 12px;
  background: var(--surface-2, #1a1a1a); color: var(--text, #e0e0e0);
  border: 1px solid var(--border, #333); border-radius: 6px;
  cursor: pointer; font-size: 13px; margin-bottom: 16px;
}
.mv-back-btn:hover { background: var(--surface-hover, #222); }
.mv-detail-header {
  display: flex; align-items: baseline; gap: 12px; margin-bottom: 20px;
}
.mv-detail-name { font-size: 22px; font-weight: 700; color: var(--text, #e0e0e0); }
.mv-detail-const { font-size: 13px; color: var(--text-dim, #888); }
.mv-detail-id { font-size: 13px; color: var(--text-dim, #666); }

.mv-field-row {
  display: flex; align-items: center; gap: 12px; padding: 10px 0;
  border-bottom: 1px solid var(--border-dim, #222);
}
.mv-field-label {
  width: 100px; font-size: 12px; text-transform: uppercase;
  letter-spacing: 0.5px; color: var(--text-dim, #888); flex-shrink: 0;
}
.mv-field-value {
  flex: 1; font-size: 14px; color: var(--text, #e0e0e0);
  display: flex; align-items: center; gap: 8px;
}
.mv-field-edit-btn {
  padding: 2px 8px; border-radius: 3px; border: 1px solid var(--border, #333);
  background: transparent; color: var(--text-dim, #888); cursor: pointer;
  font-size: 11px; opacity: 0; transition: opacity 0.15s;
}
.mv-field-row:hover .mv-field-edit-btn { opacity: 1; }
.mv-field-readonly {
  font-size: 12px; color: var(--text-dim, #666); font-style: italic;
}

/* Inline edit controls */
.mv-inline-edit {
  display: flex; align-items: center; gap: 6px; flex: 1;
}
.mv-inline-input {
  padding: 4px 8px; border-radius: 4px; border: 1px solid var(--accent, #6890F0);
  background: var(--surface-2, #1a1a1a); color: var(--text, #e0e0e0);
  font-size: 14px; flex: 1; min-width: 0;
}
.mv-inline-select {
  padding: 4px 8px; border-radius: 4px; border: 1px solid var(--accent, #6890F0);
  background: var(--surface-2, #1a1a1a); color: var(--text, #e0e0e0);
  font-size: 14px;
}
.mv-inline-save, .mv-inline-cancel {
  padding: 4px 8px; border-radius: 3px; border: none;
  font-size: 12px; cursor: pointer;
}
.mv-inline-save {
  background: var(--accent, #6890F0); color: #fff;
}
.mv-inline-save:disabled { opacity: 0.5; cursor: not-allowed; }
.mv-inline-cancel {
  background: var(--surface-2, #333); color: var(--text-dim, #aaa);
}

.mv-field-feedback {
  font-size: 11px; margin-left: 4px;
}
.mv-field-feedback.success { color: #4ade80; }
.mv-field-feedback.error { color: #ef4444; }

.mv-conditional-warn {
  font-size: 11px; color: #f59e0b; display: flex; align-items: center; gap: 4px;
}

/* Flag chips */
.mv-flags { display: flex; flex-wrap: wrap; gap: 4px; }
.mv-flag-chip {
  display: inline-block; padding: 2px 6px; border-radius: 3px;
  background: var(--surface-2, #1a1a1a); border: 1px solid var(--border, #333);
  font-size: 11px; color: var(--text-dim, #aaa);
}
`;
  document.head.appendChild(styleEl);
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function fetchMoves() {
  const res = await api("/moves/browse");
  if (!res.ok) return;
  allMoves = res.data.moves || [];
  refTypes = res.data.types || [];
  refCategories = res.data.categories || [];
  refTargets = res.data.targets || [];
  applyFilters();
}

function applyFilters() {
  let result = allMoves;
  if (categoryFilter !== "all") {
    result = result.filter(mv => mv.category_raw === categoryFilter);
  }
  if (typeFilter !== "all") {
    const label = typeLabel(typeFilter);
    result = result.filter(mv => mv.type === label);
  }
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    result = result.filter(mv =>
      mv.name.toLowerCase().includes(q) ||
      mv.constant.toLowerCase().includes(q) ||
      mv.type.toLowerCase().includes(q)
    );
  }
  filteredMoves = result;
}

// ---------------------------------------------------------------------------
// List view
// ---------------------------------------------------------------------------

function renderListView(container) {
  renderedCount = 0;

  // Toolbar
  const toolbar = document.createElement("div");
  toolbar.className = "mv-toolbar";

  // Search
  const search = document.createElement("input");
  search.className = "mv-search";
  search.type = "text";
  search.placeholder = "Search moves...";
  search.value = searchQuery;
  search.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      searchQuery = search.value.trim();
      applyFilters();
      renderBody();
    }, 300);
  });
  toolbar.appendChild(search);

  // Category filter
  const catGroup = document.createElement("div");
  catGroup.className = "mv-filter-group";
  const cats = [
    { label: "All", value: "all" },
    { label: "Physical", value: "DAMAGE_CATEGORY_PHYSICAL" },
    { label: "Special", value: "DAMAGE_CATEGORY_SPECIAL" },
    { label: "Status", value: "DAMAGE_CATEGORY_STATUS" },
  ];
  for (const c of cats) {
    const btn = document.createElement("button");
    btn.className = "mv-filter-btn" + (categoryFilter === c.value ? " active" : "");
    btn.textContent = c.label;
    btn.addEventListener("click", () => {
      categoryFilter = c.value;
      applyFilters();
      renderBody();
    });
    catGroup.appendChild(btn);
  }
  toolbar.appendChild(catGroup);

  // Type filter dropdown
  const typeSelect = document.createElement("select");
  typeSelect.className = "mv-type-select";
  const allOpt = document.createElement("option");
  allOpt.value = "all";
  allOpt.textContent = "All Types";
  typeSelect.appendChild(allOpt);
  for (const t of refTypes) {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = typeLabel(t);
    if (typeFilter === t) opt.selected = true;
    typeSelect.appendChild(opt);
  }
  typeSelect.addEventListener("change", () => {
    typeFilter = typeSelect.value;
    applyFilters();
    renderBody();
  });
  toolbar.appendChild(typeSelect);

  // Count
  const countEl = document.createElement("span");
  countEl.className = "mv-count";
  countEl.id = "mv-count";
  toolbar.appendChild(countEl);

  container.appendChild(toolbar);

  // Table
  const table = document.createElement("table");
  table.className = "mv-table";
  table.innerHTML = `<thead><tr>
    <th>Name</th><th>Type</th><th>Category</th>
    <th>Power</th><th>Accuracy</th><th>PP</th>
  </tr></thead>`;
  const tbody = document.createElement("tbody");
  tbody.id = "mv-tbody";
  table.appendChild(tbody);
  container.appendChild(table);

  renderBody();
  installScroll();
}

function renderBody() {
  const tbody = document.getElementById("mv-tbody");
  const countEl = document.getElementById("mv-count");
  if (!tbody) return;

  tbody.innerHTML = "";
  renderedCount = 0;

  if (countEl) {
    const total = allMoves.length;
    const shown = filteredMoves.length;
    countEl.textContent = shown === total
      ? `${total} moves`
      : `${shown} matching`;
  }

  appendRows(Math.min(PAGE_SIZE, filteredMoves.length));
}

function appendRows(count) {
  const tbody = document.getElementById("mv-tbody");
  if (!tbody) return;
  const end = Math.min(renderedCount + count, filteredMoves.length);

  for (let i = renderedCount; i < end; i++) {
    const mv = filteredMoves[i];
    const tr = document.createElement("tr");
    tr.dataset.constant = mv.constant;
    tr.addEventListener("click", () => openDetail(mv.constant));

    const bg = typeColour(mv.type);
    const catBg = CAT_COLOURS[mv.category] || "#888";

    tr.innerHTML = `
      <td>${esc(mv.name)}</td>
      <td><span class="mv-type-badge" style="background:${bg}">${esc(mv.type)}</span></td>
      <td><span class="mv-cat-badge" style="background:${catBg}">${esc(mv.category)}</span></td>
      <td>${mv.power > 0 ? mv.power : '<span class="mv-power-dash">---</span>'}</td>
      <td>${mv.accuracy > 0 ? mv.accuracy : '<span class="mv-power-dash">---</span>'}</td>
      <td>${mv.pp}</td>
    `;
    tbody.appendChild(tr);
  }

  renderedCount = end;
}

function installScroll() {
  if (scrollHandler) return;
  scrollHandler = () => {
    if (renderedCount >= filteredMoves.length) return;
    const scrollBottom = window.innerHeight + window.scrollY;
    const docHeight = document.documentElement.scrollHeight;
    if (scrollBottom >= docHeight - 300) {
      appendRows(PAGE_SIZE);
    }
  };
  window.addEventListener("scroll", scrollHandler);
}

// ---------------------------------------------------------------------------
// Detail / Edit view
// ---------------------------------------------------------------------------

async function openDetail(constant) {
  activeView = "detail";
  const res = await api(`/moves/browse/${constant}`);
  if (!res.ok) {
    activeView = "list";
    return;
  }
  selectedMove = res.data;
  renderDetail();
}

function renderDetail() {
  if (!currentContainer || !selectedMove) return;
  const mv = selectedMove;
  currentContainer.innerHTML = renderStudioNavbar("Moves");

  const wrapper = document.createElement("div");
  wrapper.className = "mv-detail";

  // Back button
  const backBtn = document.createElement("button");
  backBtn.className = "mv-back-btn";
  backBtn.innerHTML = "&larr; Back";
  backBtn.addEventListener("click", () => {
    activeView = "list";
    selectedMove = null;
    renderInto(currentContainer);
  });
  wrapper.appendChild(backBtn);

  // Header
  const header = document.createElement("div");
  header.className = "mv-detail-header";
  header.innerHTML = `
    <span class="mv-detail-name">${esc(mv.name)}</span>
    <span class="mv-detail-const">${esc(mv.constant)}</span>
    <span class="mv-detail-id">#${mv.id}</span>
  `;
  wrapper.appendChild(header);

  // Editable fields
  const editableFields = [
    { key: "name", label: "Name", type: "text", maxlength: 16 },
    { key: "type", label: "Type", type: "select", raw_key: "type_raw", options: refTypes, displayFn: typeLabel },
    { key: "category", label: "Category", type: "select", raw_key: "category_raw", options: refCategories, displayFn: catLabel },
    { key: "power", label: "Power", type: "number", min: 0, max: 250, raw_key: "power_raw" },
    { key: "accuracy", label: "Accuracy", type: "number", min: 0, max: 100, raw_key: "accuracy_raw" },
    { key: "pp", label: "PP", type: "number", min: 1, max: 40, raw_key: "pp_raw" },
    { key: "priority", label: "Priority", type: "number", min: -7, max: 5 },
    { key: "target", label: "Target", type: "select", raw_key: "target_raw", options: refTargets, displayFn: targetLabel },
    { key: "description", label: "Description", type: "text", maxlength: 200 },
  ];

  for (const field of editableFields) {
    wrapper.appendChild(buildFieldRow(mv, field));
  }

  // Read-only fields
  // Effect
  if (mv.effect) {
    wrapper.appendChild(buildReadonlyRow("Effect", mv.effect));
  }

  // Flags
  if (mv.flags && mv.flags.length > 0) {
    const row = document.createElement("div");
    row.className = "mv-field-row";
    row.innerHTML = `<div class="mv-field-label">Flags</div>`;
    const val = document.createElement("div");
    val.className = "mv-field-value mv-flags";
    for (const f of mv.flags) {
      const chip = document.createElement("span");
      chip.className = "mv-flag-chip";
      chip.textContent = formatFlagName(f);
      val.appendChild(chip);
    }
    row.appendChild(val);
    wrapper.appendChild(row);
  }

  // Additional effects
  if (mv.has_additional_effects) {
    wrapper.appendChild(buildReadonlyRow("Additional Effects", "Yes (see source)"));
  }

  currentContainer.appendChild(wrapper);
}

function buildReadonlyRow(label, value) {
  const row = document.createElement("div");
  row.className = "mv-field-row";
  row.innerHTML = `
    <div class="mv-field-label">${esc(label)}</div>
    <div class="mv-field-value">
      <span class="mv-field-readonly">${esc(value)}</span>
    </div>
  `;
  return row;
}

function buildFieldRow(mv, field) {
  const row = document.createElement("div");
  row.className = "mv-field-row";
  row.dataset.field = field.key;

  const label = document.createElement("div");
  label.className = "mv-field-label";
  label.textContent = field.label;
  row.appendChild(label);

  const valueWrap = document.createElement("div");
  valueWrap.className = "mv-field-value";

  // Determine display value and raw value
  let displayVal = "";
  let rawVal = "";

  if (field.key === "type") {
    displayVal = mv.type;
    rawVal = mv.type_raw;
  } else if (field.key === "category") {
    displayVal = mv.category;
    rawVal = mv.category_raw;
  } else if (field.key === "target") {
    displayVal = mv.target;
    rawVal = mv.target_raw;
  } else if (field.key === "power") {
    displayVal = mv.power > 0 ? String(mv.power) : "---";
    rawVal = mv.power_raw;
  } else if (field.key === "accuracy") {
    displayVal = mv.accuracy > 0 ? String(mv.accuracy) : "---";
    rawVal = mv.accuracy_raw;
  } else if (field.key === "pp") {
    displayVal = String(mv.pp);
    rawVal = mv.pp_raw;
  } else if (field.key === "priority") {
    displayVal = String(mv.priority);
    rawVal = String(mv.priority);
  } else {
    displayVal = mv[field.key] || "";
    rawVal = displayVal;
  }

  // Detect conditional value
  const isConditional = rawVal && rawVal.includes("?");

  // Type badge for the type field
  if (field.key === "type") {
    const bg = typeColour(displayVal);
    valueWrap.innerHTML = `<span class="mv-type-badge" style="background:${bg}">${esc(displayVal)}</span>`;
  } else if (field.key === "category") {
    const catBg = CAT_COLOURS[displayVal] || "#888";
    valueWrap.innerHTML = `<span class="mv-cat-badge" style="background:${catBg}">${esc(displayVal)}</span>`;
  } else {
    const span = document.createElement("span");
    span.textContent = displayVal;
    valueWrap.appendChild(span);
  }

  // Conditional warning
  if (isConditional) {
    const warn = document.createElement("span");
    warn.className = "mv-conditional-warn";
    warn.textContent = "Conditional value — editing replaces it";
    valueWrap.appendChild(warn);
  }

  // Edit button
  const editBtn = document.createElement("button");
  editBtn.className = "mv-field-edit-btn";
  editBtn.textContent = "Edit";
  editBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    startInlineEdit(row, mv, field);
  });
  valueWrap.appendChild(editBtn);

  row.appendChild(valueWrap);
  return row;
}

function startInlineEdit(row, mv, field) {
  if (writeLock) return;

  const valueWrap = row.querySelector(".mv-field-value");
  if (!valueWrap) return;

  // Determine current raw value for pre-fill
  let currentVal = "";
  if (field.key === "type") currentVal = mv.type_raw;
  else if (field.key === "category") currentVal = mv.category_raw;
  else if (field.key === "target") currentVal = mv.target_raw;
  else if (field.key === "power") currentVal = String(mv.power);
  else if (field.key === "accuracy") currentVal = String(mv.accuracy);
  else if (field.key === "pp") currentVal = String(mv.pp);
  else if (field.key === "priority") currentVal = String(mv.priority);
  else currentVal = mv[field.key] || "";

  valueWrap.innerHTML = "";
  const editWrap = document.createElement("div");
  editWrap.className = "mv-inline-edit";

  let inputEl;

  if (field.type === "select") {
    inputEl = document.createElement("select");
    inputEl.className = "mv-inline-select";
    for (const opt of field.options) {
      const o = document.createElement("option");
      o.value = opt;
      o.textContent = field.displayFn ? field.displayFn(opt) : opt;
      if (opt === currentVal) o.selected = true;
      inputEl.appendChild(o);
    }
  } else if (field.type === "number") {
    inputEl = document.createElement("input");
    inputEl.className = "mv-inline-input";
    inputEl.type = "number";
    inputEl.value = currentVal;
    if (field.min !== undefined) inputEl.min = field.min;
    if (field.max !== undefined) inputEl.max = field.max;
  } else {
    inputEl = document.createElement("input");
    inputEl.className = "mv-inline-input";
    inputEl.type = "text";
    inputEl.value = currentVal;
    if (field.maxlength) inputEl.maxLength = field.maxlength;
  }
  editWrap.appendChild(inputEl);

  const saveBtn = document.createElement("button");
  saveBtn.className = "mv-inline-save";
  saveBtn.textContent = "Save";
  saveBtn.addEventListener("click", () => saveField(row, mv, field, inputEl));
  editWrap.appendChild(saveBtn);

  const cancelBtn = document.createElement("button");
  cancelBtn.className = "mv-inline-cancel";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", () => renderDetail());
  editWrap.appendChild(cancelBtn);

  valueWrap.appendChild(editWrap);

  inputEl.focus();
  if (inputEl.select) inputEl.select();

  // Enter to save, Escape to cancel
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); saveField(row, mv, field, inputEl); }
    if (e.key === "Escape") { e.preventDefault(); renderDetail(); }
  });
}

async function saveField(row, mv, field, inputEl) {
  if (writeLock) return;
  writeLock = true;

  const saveBtn = row.querySelector(".mv-inline-save");
  if (saveBtn) saveBtn.disabled = true;

  const value = inputEl.value.trim();

  try {
    const res = await postApi(`/moves/browse/${mv.constant}`, {
      field: field.key,
      value: value,
    });

    if (res.ok) {
      // Update selectedMove with new data
      selectedMove = res.data;
      // Also update in allMoves cache
      const idx = allMoves.findIndex(m => m.constant === mv.constant);
      if (idx !== -1) allMoves[idx] = res.data;
      applyFilters();
      renderDetail();
      // Brief success flash
      showFieldFeedback(field.key, "Saved", "success");
    } else {
      showFieldFeedback(field.key, res.error || "Save failed", "error");
    }
  } catch (err) {
    showFieldFeedback(field.key, "Network error", "error");
  } finally {
    writeLock = false;
  }
}

function showFieldFeedback(fieldKey, message, type) {
  const row = currentContainer
    ? currentContainer.querySelector(`[data-field="${fieldKey}"]`)
    : null;
  if (!row) return;
  const valueWrap = row.querySelector(".mv-field-value");
  if (!valueWrap) return;

  // Remove existing feedback
  const old = valueWrap.querySelector(".mv-field-feedback");
  if (old) old.remove();

  const fb = document.createElement("span");
  fb.className = `mv-field-feedback ${type}`;
  fb.textContent = message;
  valueWrap.appendChild(fb);

  setTimeout(() => fb.remove(), 3000);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatFlagName(flag) {
  return flag.replace(/([a-z])([A-Z])/g, "$1 $2");
}

// ---------------------------------------------------------------------------
// Main render / cleanup
// ---------------------------------------------------------------------------

async function renderInto(container) {
  container.innerHTML = renderStudioNavbar("Moves");

  if (activeView === "detail" && selectedMove) {
    renderDetail();
    return;
  }

  if (allMoves.length === 0) {
    container.innerHTML = renderStudioNavbar("Moves") + '<div style="text-align:center;color:var(--text-dim,#888);padding:32px">Loading moves...</div>';
    await fetchMoves();
    container.innerHTML = renderStudioNavbar("Moves");
  }

  renderListView(container);
}

export async function render(container) {
  currentContainer = container;
  injectStyles();
  await renderInto(container);
}

export function cleanup() {
  clearTimeout(debounceTimer);
  debounceTimer = null;
  if (scrollHandler) {
    window.removeEventListener("scroll", scrollHandler);
    scrollHandler = null;
  }
  if (styleEl) {
    styleEl.remove();
    styleEl = null;
  }
  allMoves = [];
  filteredMoves = [];
  renderedCount = 0;
  searchQuery = "";
  categoryFilter = "all";
  typeFilter = "all";
  activeView = "list";
  selectedMove = null;
  writeLock = false;
  currentContainer = null;
}
