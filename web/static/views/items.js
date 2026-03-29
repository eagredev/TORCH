/**
 * TORCH Web GUI -- Item Editor view.
 * Browse all game items with search/pocket filter, click to edit fields inline.
 */

import { api, postApi } from "../app.js";
import { esc } from "../utils.js";
import { renderStudioNavbar } from "../studioNav.js";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let allItems = [];
let filteredItems = [];
let pockets = [];
let sortTypes = [];
let holdEffects = null;   // lazy-loaded
let activePocket = "";    // "" = all
let searchQuery = "";
let debounceTimer = null;
let selectedItem = null;  // item constant currently open in detail
let styleEl = null;
let scrollHandler = null;
let renderedCount = 0;
const PAGE_SIZE = 60;

// Saving state per field
const savingState = {};   // { field: "saving"|"ok"|"error" }

// ---------------------------------------------------------------------------
// Pocket colour badges
// ---------------------------------------------------------------------------

const POCKET_COLOURS = {
  POCKET_ITEMS:      { bg: "rgba(160,160,160,0.15)", fg: "#aaa",     label: "Items" },
  POCKET_POKE_BALLS: { bg: "rgba(239,68,68,0.15)",   fg: "#ef4444",  label: "Balls" },
  POCKET_TM_HM:     { bg: "rgba(168,80,248,0.15)",   fg: "#a850f8",  label: "TMs" },
  POCKET_BERRIES:    { bg: "rgba(74,222,128,0.15)",   fg: "#4ade80",  label: "Berries" },
  POCKET_KEY_ITEMS:  { bg: "rgba(250,204,21,0.15)",   fg: "#facc15",  label: "Key Items" },
};

function pocketBadge(pocket) {
  const p = POCKET_COLOURS[pocket] || { bg: "rgba(100,100,100,0.15)", fg: "#888", label: pocket };
  return `<span class="item-pocket-badge" style="background:${p.bg};color:${p.fg}">${esc(p.label)}</span>`;
}

function pocketLabel(pocket) {
  return (POCKET_COLOURS[pocket] || {}).label || pocket;
}

function sortTypeLabel(st) {
  if (!st) return "";
  return st.replace("ITEM_TYPE_", "").replace(/_/g, " ").toLowerCase()
    .replace(/\b\w/g, c => c.toUpperCase());
}

function holdEffectLabel(he) {
  if (!he) return "(none)";
  return he.replace("HOLD_EFFECT_", "").replace(/_/g, " ").toLowerCase()
    .replace(/\b\w/g, c => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function fetchItems() {
  const res = await api("/items/browse");
  if (!res || !res.ok) return;
  allItems = res.data.items || [];
  pockets = res.data.pockets || [];
  sortTypes = res.data.sort_types || [];
}

async function fetchHoldEffects() {
  if (holdEffects) return holdEffects;
  const res = await api("/items/hold-effects");
  if (res && res.ok) holdEffects = res.data.effects || [];
  else holdEffects = [];
  return holdEffects;
}

// ---------------------------------------------------------------------------
// Filtering
// ---------------------------------------------------------------------------

function applyFilters() {
  let result = allItems;
  if (activePocket) {
    result = result.filter(it => it.pocket === activePocket);
  }
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    result = result.filter(it =>
      it.name.toLowerCase().includes(q) || it.constant.toLowerCase().includes(q)
    );
  }
  filteredItems = result;
}

// ---------------------------------------------------------------------------
// List rendering
// ---------------------------------------------------------------------------

function renderItemRow(item) {
  const iconUrl = `/api/items/icons/${item.constant}`;
  return `<tr class="item-row" data-const="${esc(item.constant)}">
    <td class="item-icon-cell"><img class="item-icon" src="${iconUrl}" alt="" width="32" height="32"></td>
    <td class="item-name-cell">${esc(item.name)}</td>
    <td class="item-price-cell">${esc(item.price_display)}</td>
    <td class="item-pocket-cell">${pocketBadge(item.pocket)}</td>
    <td class="item-sort-cell">${esc(sortTypeLabel(item.sort_type))}</td>
  </tr>`;
}

function renderList(container) {
  applyFilters();

  const countLabel = searchQuery || activePocket
    ? `${filteredItems.length} matching`
    : `${filteredItems.length} items`;

  // Pocket filter buttons
  const pocketBtns = pockets.map(p => {
    const active = p === activePocket ? " item-filter-active" : "";
    return `<button class="item-filter-btn${active}" data-pocket="${esc(p)}">${esc(pocketLabel(p))}</button>`;
  }).join("");

  container.innerHTML = `
    <div class="item-toolbar">
      <input type="text" class="item-search" placeholder="Search items..." value="${esc(searchQuery)}">
      <div class="item-filter-group">
        <button class="item-filter-btn${activePocket ? "" : " item-filter-active"}" data-pocket="">All</button>
        ${pocketBtns}
      </div>
      <span class="item-count">${countLabel}</span>
    </div>
    <div class="item-table-wrap">
      <table class="item-table">
        <thead>
          <tr>
            <th class="item-th-icon"></th>
            <th>Name</th>
            <th>Price</th>
            <th>Pocket</th>
            <th>Type</th>
          </tr>
        </thead>
        <tbody class="item-tbody"></tbody>
      </table>
    </div>`;

  const tbody = container.querySelector(".item-tbody");
  renderedCount = 0;
  appendRows(tbody, PAGE_SIZE);
  setupListEvents(container);
}

function appendRows(tbody, count) {
  const end = Math.min(renderedCount + count, filteredItems.length);
  let html = "";
  for (let i = renderedCount; i < end; i++) {
    html += renderItemRow(filteredItems[i]);
  }
  tbody.insertAdjacentHTML("beforeend", html);

  // Attach click handlers to new rows
  const rows = tbody.querySelectorAll(".item-row");
  for (let i = renderedCount; i < end; i++) {
    const row = rows[i];
    if (row) {
      row.addEventListener("click", () => {
        const c = row.dataset.const;
        selectedItem = c;
        renderDetail(tbody.closest(".item-editor-root"), c);
      });
    }
  }
  renderedCount = end;
}

function setupListEvents(container) {
  // Search
  const searchInput = container.querySelector(".item-search");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        searchQuery = searchInput.value.trim();
        renderList(container.querySelector(".item-list-panel") || container);
      }, 300);
    });
    searchInput.focus();
  }

  // Pocket filter
  container.querySelectorAll(".item-filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      activePocket = btn.dataset.pocket || "";
      renderList(container.querySelector(".item-list-panel") || container);
    });
  });

  // Infinite scroll
  if (scrollHandler) {
    window.removeEventListener("scroll", scrollHandler);
    scrollHandler = null;
  }
  const tbody = container.querySelector(".item-tbody");
  if (tbody) {
    scrollHandler = () => {
      if (renderedCount >= filteredItems.length) return;
      const scrollBottom = window.innerHeight + window.scrollY;
      const docHeight = document.documentElement.scrollHeight;
      if (scrollBottom >= docHeight - 400) {
        appendRows(tbody, PAGE_SIZE);
      }
    };
    window.addEventListener("scroll", scrollHandler);
  }
}

// ---------------------------------------------------------------------------
// Detail / edit view
// ---------------------------------------------------------------------------

function renderDetail(root, constant) {
  const item = allItems.find(it => it.constant === constant);
  if (!item) return;

  const iconUrl = `/api/items/icons/${constant}`;

  root.innerHTML = `
    <div class="item-detail">
      <button class="item-back-btn">&larr; Back to list</button>
      <div class="item-detail-header">
        <img class="item-detail-icon" src="${iconUrl}" alt="" width="48" height="48">
        <div>
          <h2 class="item-detail-name">${esc(item.name)}</h2>
          <span class="item-detail-const">${esc(item.constant)}</span>
          <span class="item-detail-id">#${item.id}</span>
        </div>
      </div>
      <div class="item-detail-fields">
        ${renderField(item, "name", "Name", "text")}
        ${renderField(item, "price", "Price", "text")}
        ${renderField(item, "description", "Description", "textarea")}
        ${renderField(item, "pocket", "Pocket", "select")}
        ${renderField(item, "sort_type", "Sort Type", "select")}
        ${renderField(item, "hold_effect", "Hold Effect", "searchselect")}
        ${renderField(item, "hold_effect_param", "Hold Effect Param", "number")}
        ${renderField(item, "fling_power", "Fling Power", "number")}
      </div>
    </div>`;

  // Back button
  root.querySelector(".item-back-btn").addEventListener("click", () => {
    selectedItem = null;
    renderListPanel(root);
  });

  // Attach edit events
  setupFieldEditors(root, item);
}

function renderField(item, field, label, type) {
  const value = item[field] ?? "";
  let displayValue = esc(String(value));

  if (field === "pocket") displayValue = esc(pocketLabel(value));
  else if (field === "sort_type") displayValue = esc(sortTypeLabel(value));
  else if (field === "hold_effect") displayValue = esc(holdEffectLabel(value));
  else if (field === "price") displayValue = esc(item.price_display || value);

  return `<div class="item-field" data-field="${field}" data-type="${type}">
    <label class="item-field-label">${esc(label)}</label>
    <div class="item-field-display">
      <span class="item-field-value">${displayValue || '<span class="item-empty">(none)</span>'}</span>
      <button class="item-field-edit-btn" title="Edit ${esc(label)}">Edit</button>
      <span class="item-field-status"></span>
    </div>
    <div class="item-field-editor" style="display:none"></div>
  </div>`;
}

function setupFieldEditors(root, item) {
  root.querySelectorAll(".item-field").forEach(fieldEl => {
    const field = fieldEl.dataset.field;
    const type = fieldEl.dataset.type;
    const editBtn = fieldEl.querySelector(".item-field-edit-btn");
    const editorWrap = fieldEl.querySelector(".item-field-editor");
    const displayWrap = fieldEl.querySelector(".item-field-display");

    editBtn.addEventListener("click", () => {
      openFieldEditor(fieldEl, field, type, item, editorWrap, displayWrap);
    });
  });
}

function openFieldEditor(fieldEl, field, type, item, editorWrap, displayWrap) {
  displayWrap.style.display = "none";
  editorWrap.style.display = "flex";

  const currentValue = item[field] ?? "";

  if (type === "text") {
    const maxLen = field === "name" ? 19 : 999;
    editorWrap.innerHTML = `
      <input type="text" class="item-edit-input" value="${esc(String(currentValue))}" maxlength="${maxLen}">
      <button class="item-save-btn">Save</button>
      <button class="item-cancel-btn">Cancel</button>`;

  } else if (type === "textarea") {
    editorWrap.innerHTML = `
      <textarea class="item-edit-textarea" rows="3">${esc(String(currentValue))}</textarea>
      <button class="item-save-btn">Save</button>
      <button class="item-cancel-btn">Cancel</button>`;

  } else if (type === "number") {
    const min = 0;
    const max = field === "hold_effect_param" ? 255 : 150;
    editorWrap.innerHTML = `
      <input type="number" class="item-edit-input" value="${Number(currentValue)}" min="${min}" max="${max}">
      <button class="item-save-btn">Save</button>
      <button class="item-cancel-btn">Cancel</button>`;

  } else if (type === "select") {
    const options = field === "pocket" ? pockets : sortTypes;
    const optHtml = options.map(o => {
      const label = field === "pocket" ? pocketLabel(o) : sortTypeLabel(o);
      const sel = o === currentValue ? " selected" : "";
      return `<option value="${esc(o)}"${sel}>${esc(label)}</option>`;
    }).join("");
    editorWrap.innerHTML = `
      <select class="item-edit-select">${optHtml}</select>
      <button class="item-save-btn">Save</button>
      <button class="item-cancel-btn">Cancel</button>`;

  } else if (type === "searchselect") {
    // Hold effect — load effects list, then render searchable dropdown
    editorWrap.innerHTML = `<span class="item-loading">Loading...</span>`;
    fetchHoldEffects().then(effects => {
      renderHoldEffectEditor(editorWrap, effects, currentValue, field, item, fieldEl, displayWrap);
    });
    return; // events set up after async
  }

  // Wire save/cancel
  wireEditorEvents(editorWrap, displayWrap, fieldEl, field, item);
}

function renderHoldEffectEditor(editorWrap, effects, currentValue, field, item, fieldEl, displayWrap) {
  const optHtml = effects.map(e => {
    const sel = e === currentValue ? " selected" : "";
    return `<option value="${esc(e)}"${sel}>${esc(holdEffectLabel(e))}</option>`;
  }).join("");

  editorWrap.innerHTML = `
    <input type="text" class="item-hold-search" placeholder="Filter effects...">
    <select class="item-edit-select item-hold-select" size="8">${optHtml}</select>
    <button class="item-save-btn">Save</button>
    <button class="item-cancel-btn">Cancel</button>`;

  // Filter
  const searchInput = editorWrap.querySelector(".item-hold-search");
  const select = editorWrap.querySelector(".item-hold-select");

  searchInput.addEventListener("input", () => {
    const q = searchInput.value.toLowerCase();
    const filtered = effects.filter(e =>
      e.toLowerCase().includes(q) || holdEffectLabel(e).toLowerCase().includes(q)
    );
    select.innerHTML = filtered.map(e => {
      const sel = e === currentValue ? " selected" : "";
      return `<option value="${esc(e)}"${sel}>${esc(holdEffectLabel(e))}</option>`;
    }).join("");
  });

  searchInput.focus();
  wireEditorEvents(editorWrap, displayWrap, fieldEl, field, item);
}

function wireEditorEvents(editorWrap, displayWrap, fieldEl, field, item) {
  const saveBtn = editorWrap.querySelector(".item-save-btn");
  const cancelBtn = editorWrap.querySelector(".item-cancel-btn");

  cancelBtn.addEventListener("click", () => {
    editorWrap.style.display = "none";
    displayWrap.style.display = "";
  });

  saveBtn.addEventListener("click", async () => {
    const input = editorWrap.querySelector("input, textarea, select");
    if (!input) return;

    let newValue = input.value;
    // For searchable select, get the actual select value
    const select = editorWrap.querySelector(".item-hold-select, .item-edit-select");
    if (select) newValue = select.value;
    // For textarea
    const textarea = editorWrap.querySelector("textarea");
    if (textarea) newValue = textarea.value;
    // For regular input
    const textInput = editorWrap.querySelector("input.item-edit-input");
    if (textInput) newValue = textInput.value;

    // Show saving state
    const statusEl = fieldEl.querySelector(".item-field-status");
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";

    const res = await postApi(`/items/browse/${item.constant}`, {
      field: field,
      value: newValue,
    });

    if (res && res.ok) {
      // Update local item data
      const updated = res.data.item;
      Object.assign(item, updated);
      // Also update allItems
      const idx = allItems.findIndex(it => it.constant === item.constant);
      if (idx >= 0) Object.assign(allItems[idx], updated);

      // Update display
      editorWrap.style.display = "none";
      displayWrap.style.display = "";
      updateFieldDisplay(fieldEl, field, item);
      showFieldStatus(statusEl, "ok");
    } else {
      showFieldStatus(statusEl, "error", (res && res.error) || "Save failed");
      saveBtn.disabled = false;
      saveBtn.textContent = "Save";
    }
  });
}

function updateFieldDisplay(fieldEl, field, item) {
  const valueEl = fieldEl.querySelector(".item-field-value");
  if (!valueEl) return;

  const value = item[field] ?? "";
  let display = esc(String(value));

  if (field === "pocket") display = esc(pocketLabel(value));
  else if (field === "sort_type") display = esc(sortTypeLabel(value));
  else if (field === "hold_effect") display = esc(holdEffectLabel(value));
  else if (field === "price") display = esc(item.price_display || value);

  valueEl.innerHTML = display || '<span class="item-empty">(none)</span>';
}

function showFieldStatus(el, state, msg) {
  if (!el) return;
  if (state === "ok") {
    el.textContent = "Saved";
    el.className = "item-field-status item-status-ok";
    setTimeout(() => { el.textContent = ""; el.className = "item-field-status"; }, 2000);
  } else if (state === "error") {
    el.textContent = msg || "Error";
    el.className = "item-field-status item-status-error";
    setTimeout(() => { el.textContent = ""; el.className = "item-field-status"; }, 4000);
  }
}

// ---------------------------------------------------------------------------
// Main render
// ---------------------------------------------------------------------------

function renderListPanel(root) {
  root.innerHTML = `<div class="item-list-panel"></div>`;
  renderList(root.querySelector(".item-list-panel"));
}

export async function render(container) {
  injectStyles();

  container.innerHTML = renderStudioNavbar("Items") + `<div class="item-editor-root"><p class="item-loading">Loading items...</p></div>`;
  const root = container.querySelector(".item-editor-root");

  await fetchItems();

  if (!allItems.length) {
    root.innerHTML = `<p class="item-empty-msg">No items found. Ensure this is a pokeemerald-expansion project.</p>`;
    return;
  }

  if (selectedItem) {
    renderDetail(root, selectedItem);
  } else {
    renderListPanel(root);
  }
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
  selectedItem = null;
}

// ---------------------------------------------------------------------------
// Scoped CSS
// ---------------------------------------------------------------------------

function injectStyles() {
  if (styleEl) return;
  styleEl = document.createElement("style");
  styleEl.textContent = `
/* Item Editor */
.item-editor-root {
  max-width: 1100px;
  margin: 0 auto;
  padding: 1rem;
}
.item-loading { color: var(--text-muted); }
.item-empty-msg { color: var(--text-muted); text-align: center; padding: 3rem 1rem; }

/* Toolbar */
.item-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
}
.item-search {
  flex: 1 1 200px;
  min-width: 180px;
  padding: 0.5rem 0.75rem;
  background: var(--surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 0.9rem;
}
.item-search:focus {
  border-color: var(--accent);
  outline: none;
  box-shadow: 0 0 0 2px var(--accent-bg-focus);
}
.item-filter-group {
  display: flex;
  gap: 0.25rem;
  flex-wrap: wrap;
}
.item-filter-btn {
  padding: 0.35rem 0.65rem;
  font-size: 0.8rem;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  background: var(--surface-2);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}
.item-filter-btn:hover { border-color: var(--border-emphasis); color: var(--text-secondary); }
.item-filter-btn.item-filter-active {
  background: var(--accent-bg-faint);
  border-color: var(--accent-border-faint);
  color: var(--accent);
}
.item-count {
  color: var(--text-dim);
  font-size: 0.85rem;
  white-space: nowrap;
}

/* Table */
.item-table-wrap { overflow-x: auto; }
.item-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}
.item-table th {
  text-align: left;
  padding: 0.5rem 0.75rem;
  color: var(--text-dim);
  font-weight: 500;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-bottom: 1px solid var(--border-subtle);
}
.item-th-icon { width: 40px; }
.item-row {
  cursor: pointer;
  transition: background 0.1s;
}
.item-row:hover { background: var(--accent-bg-subtle); }
.item-row td {
  padding: 0.45rem 0.75rem;
  border-bottom: 1px solid var(--surface-3);
  vertical-align: middle;
}
.item-icon-cell { width: 40px; text-align: center; }
.item-icon {
  width: 32px; height: 32px;
  image-rendering: pixelated;
  background: var(--surface-3);
  border-radius: 4px;
  vertical-align: middle;
}
.item-name-cell { color: var(--text-primary); font-weight: 500; }
.item-price-cell { color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.item-sort-cell { color: var(--text-dim); font-size: 0.85rem; }
.item-pocket-badge {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
  white-space: nowrap;
}

/* Detail view */
.item-detail { max-width: 700px; }
.item-back-btn {
  background: none;
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
  padding: 0.35rem 0.75rem;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.85rem;
  margin-bottom: 1.25rem;
}
.item-back-btn:hover { border-color: var(--accent); color: var(--accent); }
.item-detail-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.5rem;
}
.item-detail-icon {
  width: 48px; height: 48px;
  image-rendering: pixelated;
  background: var(--surface-3);
  border-radius: 6px;
  padding: 4px;
}
.item-detail-name {
  margin: 0;
  font-size: 1.4rem;
  color: var(--text-primary);
}
.item-detail-const {
  color: var(--text-dim);
  font-size: 0.85rem;
  font-family: monospace;
}
.item-detail-id {
  color: var(--text-dim);
  font-size: 0.85rem;
  margin-left: 0.5rem;
}

/* Fields */
.item-detail-fields {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.item-field {
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--surface-3);
}
.item-field-label {
  display: block;
  color: var(--text-dim);
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  margin-bottom: 0.35rem;
}
.item-field-display {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.item-field-value {
  flex: 1;
  color: var(--text-secondary);
  font-size: 0.95rem;
  word-break: break-word;
}
.item-empty { color: var(--text-dim); font-style: italic; }
.item-field-edit-btn {
  padding: 0.25rem 0.6rem;
  font-size: 0.78rem;
  background: var(--surface-3);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  color: var(--text-muted);
  cursor: pointer;
  flex-shrink: 0;
}
.item-field-edit-btn:hover { border-color: var(--accent); color: var(--accent); }
.item-field-status {
  font-size: 0.8rem;
  flex-shrink: 0;
  min-width: 50px;
}
.item-status-ok { color: var(--status-ok); }
.item-status-error { color: var(--status-error); }

/* Editor inline */
.item-field-editor {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-top: 0.5rem;
}
.item-edit-input, .item-edit-textarea, .item-edit-select {
  flex: 1 1 200px;
  padding: 0.4rem 0.6rem;
  background: var(--surface-1);
  border: 1px solid var(--border-emphasis);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.9rem;
  font-family: inherit;
}
.item-edit-input:focus, .item-edit-textarea:focus, .item-edit-select:focus {
  border-color: var(--accent);
  outline: none;
}
.item-edit-textarea {
  min-height: 60px;
  resize: vertical;
  width: 100%;
  flex-basis: 100%;
}
.item-hold-search {
  flex: 1 1 100%;
  padding: 0.4rem 0.6rem;
  background: var(--surface-1);
  border: 1px solid var(--border-emphasis);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.9rem;
  margin-bottom: 0.25rem;
}
.item-hold-search:focus { border-color: var(--accent); outline: none; }
.item-hold-select {
  flex: 1 1 100%;
  min-height: 160px;
}
.item-edit-select option {
  padding: 0.25rem 0.4rem;
}
.item-save-btn, .item-cancel-btn {
  padding: 0.4rem 0.75rem;
  font-size: 0.85rem;
  border-radius: 4px;
  cursor: pointer;
  border: 1px solid var(--border-subtle);
  flex-shrink: 0;
}
.item-save-btn {
  background: var(--accent);
  color: #000;
  border-color: var(--accent);
  font-weight: 500;
}
.item-save-btn:hover { background: var(--accent-hover); }
.item-save-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.item-cancel-btn {
  background: var(--surface-3);
  color: var(--text-muted);
}
.item-cancel-btn:hover { border-color: var(--border-emphasis); color: var(--text-secondary); }
`;
  document.head.appendChild(styleEl);
}
