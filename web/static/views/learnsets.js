/**
 * TORCH Web GUI -- Learnset Editor view.
 * Species picker, tabbed editor for level-up / egg / teachable learnsets.
 */

import { api, postApi } from "../app.js";
import { esc } from "../utils.js";
import { renderStudioNavbar } from "../studioNav.js";

// ---------------------------------------------------------------------------
// Type colour palette (matches moves.js)
// ---------------------------------------------------------------------------

const TYPE_COLOURS = {
  Normal:   "#A8A878", Fire:     "#F08030", Water:    "#6890F0",
  Electric: "#F8D030", Grass:    "#78C850", Ice:      "#98D8D8",
  Fighting: "#C03028", Poison:   "#A040A0", Ground:   "#E0C068",
  Flying:   "#A890F0", Psychic:  "#F85888", Bug:      "#A8B820",
  Rock:     "#B8A038", Ghost:    "#705898", Dragon:   "#7038F8",
  Dark:     "#705848", Steel:    "#B8B8D0", Fairy:    "#EE99AC",
};

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let styleEl = null;
let currentContainer = null;
let debounceTimer = null;
let writeLock = false;

// Species picker
let speciesResults = [];

// Editor
let selectedSpecies = null;  // { const, name }
let activeTab = "level_up";  // "level_up" | "egg" | "teachable"
let learnsetData = null;     // server response .data

// Working copies for editable tabs
let levelUpWorking = [];     // [{level, move, name}, ...]
let eggWorking = [];         // [{move, name}, ...]
let dirty = false;

// Move cache for the picker
let moveCache = null;        // [{const, name, type, category}, ...]

// ---------------------------------------------------------------------------
// CSS
// ---------------------------------------------------------------------------

const STYLES = `
.ls-layout { max-width: 900px; margin: 0 auto; }

/* --- Species Picker --- */
.ls-picker { padding: 1rem 0; }
.ls-picker-title {
  color: var(--text-primary, #cdd6f4); font-size: 1.1rem; font-weight: 600;
  margin-bottom: 0.75rem;
}
.ls-search {
  width: 100%; max-width: 400px; padding: 0.6rem 0.8rem;
  background: var(--bg-secondary, #1e1e2e); color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border, #313244); border-radius: 6px;
  font-size: 0.9rem; margin-bottom: 1rem;
}
.ls-search:focus { border-color: var(--accent, #cba6f7); outline: none; }
.ls-species-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0.5rem;
}
.ls-species-card {
  background: var(--bg-secondary, #1e1e2e); border: 1px solid var(--border, #313244);
  border-radius: 6px; padding: 0.6rem 0.8rem; cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.ls-species-card:hover {
  border-color: var(--accent, #cba6f7); background: var(--bg-hover, #313244);
}
.ls-species-name {
  color: var(--text-primary, #cdd6f4); font-weight: 500; font-size: 0.85rem;
}
.ls-species-const {
  color: var(--text-muted, #6c7086); font-size: 0.7rem; margin-top: 2px;
}

/* --- Editor Layout --- */
.ls-editor { padding: 0.5rem 0; }
.ls-back-btn {
  background: none; border: none; color: var(--accent, #cba6f7);
  cursor: pointer; font-size: 0.85rem; padding: 0.3rem 0; margin-bottom: 0.5rem;
}
.ls-back-btn:hover { text-decoration: underline; }
.ls-editor-title {
  color: var(--text-primary, #cdd6f4); font-size: 1.2rem; font-weight: 600;
  margin-bottom: 0.75rem;
}

/* --- Tabs --- */
.ls-tabs {
  display: flex; gap: 0; border-bottom: 2px solid var(--border, #313244);
  margin-bottom: 1rem;
}
.ls-tab {
  padding: 0.5rem 1.2rem; cursor: pointer; font-size: 0.85rem; font-weight: 500;
  color: var(--text-muted, #6c7086); border-bottom: 2px solid transparent;
  margin-bottom: -2px; transition: color 0.15s, border-color 0.15s;
  background: none; border-top: none; border-left: none; border-right: none;
}
.ls-tab:hover { color: var(--text-primary, #cdd6f4); }
.ls-tab.active {
  color: var(--accent, #cba6f7); border-bottom-color: var(--accent, #cba6f7);
}

/* --- Move Table --- */
.ls-table-wrap {
  background: var(--bg-secondary, #1e1e2e); border: 1px solid var(--border, #313244);
  border-radius: 8px; overflow: hidden;
}
.ls-table {
  width: 100%; border-collapse: collapse; font-size: 0.85rem;
}
.ls-table th {
  text-align: left; padding: 0.6rem 0.8rem;
  color: var(--text-muted, #6c7086); font-weight: 600; font-size: 0.75rem;
  text-transform: uppercase; letter-spacing: 0.05em;
  border-bottom: 1px solid var(--border, #313244);
  background: var(--bg-tertiary, #181825);
}
.ls-table td {
  padding: 0.45rem 0.8rem; border-bottom: 1px solid var(--border-subtle, #313244);
  color: var(--text-primary, #cdd6f4);
}
.ls-table tr:last-child td { border-bottom: none; }
.ls-table tr:hover td { background: var(--bg-hover, #313244); }
.ls-table.readonly tr:hover td { background: transparent; }
.ls-table.readonly td { color: var(--text-muted, #6c7086); }

.ls-level-input {
  width: 50px; padding: 0.2rem 0.4rem; text-align: center;
  background: var(--bg-tertiary, #181825); color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border, #313244); border-radius: 4px;
  font-size: 0.85rem;
}
.ls-level-input:focus { border-color: var(--accent, #cba6f7); outline: none; }

/* --- Type Badge --- */
.ls-type-badge {
  display: inline-block; padding: 1px 7px; border-radius: 3px;
  font-size: 0.7rem; font-weight: 600; color: #fff;
  vertical-align: middle;
}

/* --- Move Picker --- */
.ls-move-picker-wrap { position: relative; display: inline-block; width: 100%; }
.ls-move-input {
  width: 100%; padding: 0.3rem 0.5rem;
  background: var(--bg-tertiary, #181825); color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border, #313244); border-radius: 4px;
  font-size: 0.85rem;
}
.ls-move-input:focus { border-color: var(--accent, #cba6f7); outline: none; }
.ls-move-dropdown {
  position: absolute; top: 100%; left: 0; right: 0; z-index: 100;
  max-height: 200px; overflow-y: auto;
  background: var(--bg-secondary, #1e1e2e); border: 1px solid var(--border, #313244);
  border-radius: 0 0 6px 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}
.ls-move-option {
  padding: 0.35rem 0.6rem; cursor: pointer; display: flex;
  align-items: center; gap: 0.5rem; font-size: 0.82rem;
  color: var(--text-primary, #cdd6f4);
}
.ls-move-option:hover { background: var(--bg-hover, #313244); }
.ls-move-option.highlighted { background: var(--bg-active, #45475a); }

/* --- Buttons --- */
.ls-btn-row {
  display: flex; gap: 0.5rem; align-items: center;
  margin-top: 0.75rem; padding: 0 0.8rem 0.8rem;
}
.ls-btn {
  padding: 0.4rem 1rem; border-radius: 6px; font-size: 0.82rem;
  font-weight: 500; cursor: pointer; border: none; transition: opacity 0.15s;
}
.ls-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ls-btn-save {
  background: var(--accent, #cba6f7); color: var(--bg-primary, #1e1e2e);
}
.ls-btn-cancel {
  background: var(--bg-tertiary, #45475a); color: var(--text-primary, #cdd6f4);
}
.ls-btn-add {
  background: var(--bg-tertiary, #45475a); color: var(--text-primary, #cdd6f4);
}
.ls-btn-delete {
  background: none; border: none; color: var(--red, #f38ba8);
  cursor: pointer; font-size: 0.9rem; padding: 0.1rem 0.4rem; opacity: 0.6;
}
.ls-btn-delete:hover { opacity: 1; }

.ls-status {
  font-size: 0.8rem; margin-left: 0.5rem;
}
.ls-status.ok { color: var(--green, #a6e3a1); }
.ls-status.err { color: var(--red, #f38ba8); }

.ls-readonly-note {
  color: var(--text-muted, #6c7086); font-size: 0.8rem; font-style: italic;
  padding: 0.6rem 0.8rem; border-bottom: 1px solid var(--border, #313244);
  background: var(--bg-tertiary, #181825);
}

.ls-empty {
  color: var(--text-muted, #6c7086); font-size: 0.85rem; padding: 1.5rem;
  text-align: center;
}
`;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function typeBadge(typeName) {
  if (!typeName) return "";
  const bg = TYPE_COLOURS[typeName] || "#888";
  return `<span class="ls-type-badge" style="background:${bg}">${esc(typeName)}</span>`;
}

function speciesDisplay(speciesConst) {
  if (!speciesConst || !speciesConst.startsWith("SPECIES_")) return speciesConst || "";
  return speciesConst.slice(8).replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// Move cache (fetch once, used by pickers)
// ---------------------------------------------------------------------------

async function ensureMoveCache() {
  if (moveCache) return moveCache;
  try {
    const res = await api("/moves");
    if (res.ok && res.data) {
      moveCache = res.data.map(m => ({
        const: m.const,
        name: m.name,
        type: m.type || "Normal",
        category: m.category || "Physical",
      }));
    }
  } catch { /* ignore */ }
  if (!moveCache) moveCache = [];
  return moveCache;
}

function filterMoves(query) {
  if (!moveCache) return [];
  const q = query.toLowerCase();
  return moveCache.filter(m =>
    m.name.toLowerCase().includes(q) || m.const.toLowerCase().includes(q)
  ).slice(0, 30);
}

// ---------------------------------------------------------------------------
// Species Picker
// ---------------------------------------------------------------------------

async function searchSpecies(query) {
  const q = encodeURIComponent(query);
  try {
    const res = await api(`/species?q=${q}`);
    if (res.ok && res.data) return res.data;
  } catch { /* ignore */ }
  return [];
}

function renderPicker() {
  const wrap = currentContainer.querySelector(".ls-layout");
  if (!wrap) return;

  let html = `<div class="ls-picker">
    <div class="ls-picker-title">Learnset Editor</div>
    <input class="ls-search" placeholder="Search species..." autofocus>
    <div class="ls-species-grid" id="ls-species-grid"></div>
  </div>`;
  wrap.innerHTML = html;

  const input = wrap.querySelector(".ls-search");
  const grid = wrap.querySelector("#ls-species-grid");

  function renderGrid(items) {
    if (!items.length) {
      grid.innerHTML = `<div class="ls-empty">Type a species name to search</div>`;
      return;
    }
    grid.innerHTML = items.map(sp => {
      const name = sp.name || sp.display || speciesDisplay(sp.const || sp.species || "");
      const cst = sp.const || sp.species || "";
      return `<div class="ls-species-card" data-species="${esc(cst)}">
        <div class="ls-species-name">${esc(name)}</div>
        <div class="ls-species-const">${esc(cst)}</div>
      </div>`;
    }).join("");
  }

  renderGrid([]);

  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
      const val = input.value.trim();
      if (val.length < 2) { renderGrid([]); return; }
      speciesResults = await searchSpecies(val);
      renderGrid(speciesResults);
    }, 300);
  });

  grid.addEventListener("click", (e) => {
    const card = e.target.closest(".ls-species-card");
    if (!card) return;
    const sp = card.dataset.species;
    if (sp) openEditor(sp);
  });
}

// ---------------------------------------------------------------------------
// Editor — load & render
// ---------------------------------------------------------------------------

async function openEditor(speciesConst) {
  selectedSpecies = speciesConst;
  activeTab = "level_up";
  dirty = false;

  try {
    const res = await api(`/learnsets/${speciesConst}`);
    if (!res.ok) {
      learnsetData = null;
      renderEditorError(res.error || "Failed to load learnsets");
      return;
    }
    learnsetData = res.data;
  } catch (err) {
    learnsetData = null;
    renderEditorError("Network error");
    return;
  }

  await ensureMoveCache();
  copyWorkingData();
  renderEditor();
}

function copyWorkingData() {
  if (!learnsetData) return;
  levelUpWorking = learnsetData.level_up.map(m => ({ ...m }));
  eggWorking = learnsetData.egg.map(m => ({ ...m }));
  dirty = false;
}

function renderEditorError(msg) {
  const wrap = currentContainer.querySelector(".ls-layout");
  if (!wrap) return;
  wrap.innerHTML = `<div class="ls-editor">
    <button class="ls-back-btn">&larr; Back to species</button>
    <div class="ls-empty">${esc(msg)}</div>
  </div>`;
  wrap.querySelector(".ls-back-btn").addEventListener("click", goBack);
}

function goBack() {
  selectedSpecies = null;
  learnsetData = null;
  dirty = false;
  renderPicker();
}

function renderEditor() {
  const wrap = currentContainer.querySelector(".ls-layout");
  if (!wrap || !learnsetData) return;

  const display = speciesDisplay(selectedSpecies);
  const tabs = [
    { key: "level_up", label: `Level Up (${levelUpWorking.length})` },
    { key: "egg", label: `Egg Moves (${eggWorking.length})` },
  ];
  if (learnsetData.teachable_available) {
    tabs.push({ key: "teachable", label: `TM/Tutor (${learnsetData.teachable.length})` });
  }

  let html = `<div class="ls-editor">
    <button class="ls-back-btn">&larr; Back to species</button>
    <div class="ls-editor-title">${esc(display)}</div>
    <div class="ls-tabs">
      ${tabs.map(t => `<button class="ls-tab${t.key === activeTab ? " active" : ""}" data-tab="${t.key}">${t.label}</button>`).join("")}
    </div>
    <div id="ls-tab-content"></div>
  </div>`;
  wrap.innerHTML = html;

  wrap.querySelector(".ls-back-btn").addEventListener("click", () => {
    if (dirty && !confirm("Discard unsaved changes?")) return;
    goBack();
  });

  wrap.querySelectorAll(".ls-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      activeTab = btn.dataset.tab;
      renderEditor();
    });
  });

  const content = wrap.querySelector("#ls-tab-content");
  if (activeTab === "level_up") renderLevelUpTab(content);
  else if (activeTab === "egg") renderEggTab(content);
  else if (activeTab === "teachable") renderTeachableTab(content);
}

// ---------------------------------------------------------------------------
// Level-Up Tab
// ---------------------------------------------------------------------------

function renderLevelUpTab(container) {
  let html = `<div class="ls-table-wrap"><table class="ls-table">
    <thead><tr><th style="width:70px">Level</th><th>Move</th><th style="width:40px"></th></tr></thead>
    <tbody id="ls-lu-body">`;

  if (levelUpWorking.length === 0) {
    html += `<tr><td colspan="3" class="ls-empty">No level-up moves</td></tr>`;
  } else {
    levelUpWorking.forEach((m, i) => {
      const moveInfo = moveCache ? moveCache.find(mc => mc.const === m.move) : null;
      const moveType = moveInfo ? moveInfo.type : "";
      html += `<tr data-idx="${i}">
        <td><input class="ls-level-input" type="number" min="1" max="100" value="${m.level}" data-idx="${i}"></td>
        <td>${typeBadge(moveType)} ${esc(m.name || m.move)}</td>
        <td><button class="ls-btn-delete" data-idx="${i}" title="Remove">&times;</button></td>
      </tr>`;
    });
  }

  html += `</tbody></table></div>
  <div class="ls-btn-row">
    <button class="ls-btn ls-btn-add" id="ls-lu-add">+ Add Move</button>
    <button class="ls-btn ls-btn-save" id="ls-lu-save">Save</button>
    <button class="ls-btn ls-btn-cancel" id="ls-lu-cancel">Cancel</button>
    <span class="ls-status" id="ls-lu-status"></span>
  </div>`;

  container.innerHTML = html;
  bindLevelUpEvents(container);
}

function bindLevelUpEvents(container) {
  // Level input changes
  container.querySelectorAll(".ls-level-input").forEach(inp => {
    inp.addEventListener("change", () => {
      const idx = parseInt(inp.dataset.idx, 10);
      const val = parseInt(inp.value, 10);
      if (val >= 1 && val <= 100 && idx < levelUpWorking.length) {
        levelUpWorking[idx].level = val;
        dirty = true;
      } else {
        inp.value = levelUpWorking[idx].level;
      }
    });
  });

  // Delete buttons
  container.querySelectorAll(".ls-btn-delete").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.dataset.idx, 10);
      levelUpWorking.splice(idx, 1);
      dirty = true;
      renderEditor();
    });
  });

  // Add move
  container.querySelector("#ls-lu-add").addEventListener("click", () => {
    showMovePickerModal((moveConst, moveName, moveType) => {
      levelUpWorking.push({ level: 1, move: moveConst, name: moveName });
      dirty = true;
      renderEditor();
    });
  });

  // Save
  container.querySelector("#ls-lu-save").addEventListener("click", () => saveLevelUp(container));

  // Cancel
  container.querySelector("#ls-lu-cancel").addEventListener("click", () => {
    copyWorkingData();
    dirty = false;
    renderEditor();
  });
}

async function saveLevelUp(container) {
  if (writeLock) return;
  writeLock = true;
  const status = container.querySelector("#ls-lu-status");
  const saveBtn = container.querySelector("#ls-lu-save");
  if (saveBtn) saveBtn.disabled = true;
  if (status) { status.textContent = "Saving..."; status.className = "ls-status"; }

  const moves = levelUpWorking.map(m => ({ level: m.level, move: m.move }));

  try {
    const res = await postApi(`/learnsets/${selectedSpecies}/level_up`, { moves });
    if (res.ok) {
      if (status) { status.textContent = `Saved ${res.data.count} moves`; status.className = "ls-status ok"; }
      dirty = false;
      // Refresh from server
      const fresh = await api(`/learnsets/${selectedSpecies}`);
      if (fresh.ok) {
        learnsetData = fresh.data;
        copyWorkingData();
      }
      setTimeout(() => renderEditor(), 800);
    } else {
      if (status) { status.textContent = res.error || "Save failed"; status.className = "ls-status err"; }
    }
  } catch {
    if (status) { status.textContent = "Network error"; status.className = "ls-status err"; }
  } finally {
    writeLock = false;
    if (saveBtn) saveBtn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Egg Moves Tab
// ---------------------------------------------------------------------------

function renderEggTab(container) {
  let html = `<div class="ls-table-wrap"><table class="ls-table">
    <thead><tr><th>Move</th><th style="width:40px"></th></tr></thead>
    <tbody>`;

  if (eggWorking.length === 0) {
    html += `<tr><td colspan="2" class="ls-empty">No egg moves</td></tr>`;
  } else {
    eggWorking.forEach((m, i) => {
      const moveInfo = moveCache ? moveCache.find(mc => mc.const === m.move) : null;
      const moveType = moveInfo ? moveInfo.type : "";
      html += `<tr data-idx="${i}">
        <td>${typeBadge(moveType)} ${esc(m.name || m.move)}</td>
        <td><button class="ls-btn-delete" data-idx="${i}" title="Remove">&times;</button></td>
      </tr>`;
    });
  }

  html += `</tbody></table></div>
  <div class="ls-btn-row">
    <button class="ls-btn ls-btn-add" id="ls-egg-add">+ Add Move</button>
    <button class="ls-btn ls-btn-save" id="ls-egg-save">Save</button>
    <button class="ls-btn ls-btn-cancel" id="ls-egg-cancel">Cancel</button>
    <span class="ls-status" id="ls-egg-status"></span>
  </div>`;

  container.innerHTML = html;
  bindEggEvents(container);
}

function bindEggEvents(container) {
  // Delete
  container.querySelectorAll(".ls-btn-delete").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.dataset.idx, 10);
      eggWorking.splice(idx, 1);
      dirty = true;
      renderEditor();
    });
  });

  // Add
  container.querySelector("#ls-egg-add").addEventListener("click", () => {
    showMovePickerModal((moveConst, moveName) => {
      if (eggWorking.some(m => m.move === moveConst)) return; // no dupes
      eggWorking.push({ move: moveConst, name: moveName });
      dirty = true;
      renderEditor();
    });
  });

  // Save
  container.querySelector("#ls-egg-save").addEventListener("click", () => saveEgg(container));

  // Cancel
  container.querySelector("#ls-egg-cancel").addEventListener("click", () => {
    copyWorkingData();
    dirty = false;
    renderEditor();
  });
}

async function saveEgg(container) {
  if (writeLock) return;
  writeLock = true;
  const status = container.querySelector("#ls-egg-status");
  const saveBtn = container.querySelector("#ls-egg-save");
  if (saveBtn) saveBtn.disabled = true;
  if (status) { status.textContent = "Saving..."; status.className = "ls-status"; }

  const moves = eggWorking.map(m => m.move);

  try {
    const res = await postApi(`/learnsets/${selectedSpecies}/egg`, { moves });
    if (res.ok) {
      if (status) { status.textContent = `Saved ${res.data.count} moves`; status.className = "ls-status ok"; }
      dirty = false;
      const fresh = await api(`/learnsets/${selectedSpecies}`);
      if (fresh.ok) {
        learnsetData = fresh.data;
        copyWorkingData();
      }
      setTimeout(() => renderEditor(), 800);
    } else {
      if (status) { status.textContent = res.error || "Save failed"; status.className = "ls-status err"; }
    }
  } catch {
    if (status) { status.textContent = "Network error"; status.className = "ls-status err"; }
  } finally {
    writeLock = false;
    if (saveBtn) saveBtn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Teachable Tab (read-only)
// ---------------------------------------------------------------------------

function renderTeachableTab(container) {
  const moves = learnsetData.teachable || [];
  let html = `<div class="ls-table-wrap">
    <div class="ls-readonly-note">TM/Tutor learnsets are auto-generated by the expansion build system.</div>
    <table class="ls-table readonly">
    <thead><tr><th>Move</th></tr></thead>
    <tbody>`;

  if (moves.length === 0) {
    html += `<tr><td class="ls-empty">No teachable moves</td></tr>`;
  } else {
    moves.forEach(m => {
      const moveInfo = moveCache ? moveCache.find(mc => mc.const === m.move) : null;
      const moveType = moveInfo ? moveInfo.type : "";
      html += `<tr><td>${typeBadge(moveType)} ${esc(m.name || m.move)}</td></tr>`;
    });
  }

  html += `</tbody></table></div>`;
  container.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Move Picker Modal
// ---------------------------------------------------------------------------

function showMovePickerModal(onSelect) {
  // Remove any existing modal
  const existing = document.querySelector(".ls-modal-overlay");
  if (existing) existing.remove();

  const overlay = document.createElement("div");
  overlay.className = "ls-modal-overlay";
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:500;display:flex;align-items:center;justify-content:center;";

  const modal = document.createElement("div");
  modal.style.cssText = "background:var(--bg-secondary,#1e1e2e);border:1px solid var(--border,#313244);border-radius:10px;padding:1rem;width:380px;max-height:450px;display:flex;flex-direction:column;";

  const title = document.createElement("div");
  title.textContent = "Select Move";
  title.style.cssText = "color:var(--text-primary,#cdd6f4);font-weight:600;margin-bottom:0.5rem;font-size:0.95rem;";

  const input = document.createElement("input");
  input.className = "ls-move-input";
  input.placeholder = "Search moves...";
  input.style.marginBottom = "0.5rem";

  const list = document.createElement("div");
  list.style.cssText = "overflow-y:auto;flex:1;max-height:320px;";

  let highlighted = -1;
  let currentResults = [];

  function renderResults(items) {
    currentResults = items;
    highlighted = items.length > 0 ? 0 : -1;
    list.innerHTML = items.map((m, i) => {
      const bg = TYPE_COLOURS[m.type] || "#888";
      return `<div class="ls-move-option${i === 0 ? " highlighted" : ""}" data-idx="${i}">
        <span class="ls-type-badge" style="background:${bg}">${esc(m.type)}</span>
        <span>${esc(m.name)}</span>
      </div>`;
    }).join("");
  }

  function selectItem(idx) {
    const m = currentResults[idx];
    if (m) {
      onSelect(m.const, m.name, m.type);
      overlay.remove();
    }
  }

  input.addEventListener("input", () => {
    const q = input.value.trim();
    if (q.length < 1) { list.innerHTML = ""; currentResults = []; return; }
    renderResults(filterMoves(q));
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (highlighted < currentResults.length - 1) {
        highlighted++;
        updateHighlight();
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (highlighted > 0) {
        highlighted--;
        updateHighlight();
      }
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (highlighted >= 0) selectItem(highlighted);
    } else if (e.key === "Escape") {
      overlay.remove();
    }
  });

  function updateHighlight() {
    list.querySelectorAll(".ls-move-option").forEach((el, i) => {
      el.classList.toggle("highlighted", i === highlighted);
      if (i === highlighted) el.scrollIntoView({ block: "nearest" });
    });
  }

  list.addEventListener("click", (e) => {
    const opt = e.target.closest(".ls-move-option");
    if (opt) selectItem(parseInt(opt.dataset.idx, 10));
  });

  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.remove();
  });

  modal.appendChild(title);
  modal.appendChild(input);
  modal.appendChild(list);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);
  input.focus();
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export async function render(container) {
  currentContainer = container;

  if (!styleEl) {
    styleEl = document.createElement("style");
    styleEl.textContent = STYLES;
    document.head.appendChild(styleEl);
  }

  container.innerHTML = renderStudioNavbar("Learnsets") + `<div class="ls-layout"></div>`;

  if (selectedSpecies && learnsetData) {
    renderEditor();
  } else {
    renderPicker();
  }
}

export function cleanup() {
  clearTimeout(debounceTimer);
  debounceTimer = null;
  if (styleEl) { styleEl.remove(); styleEl = null; }
  const modal = document.querySelector(".ls-modal-overlay");
  if (modal) modal.remove();
  currentContainer = null;
  selectedSpecies = null;
  learnsetData = null;
  levelUpWorking = [];
  eggWorking = [];
  dirty = false;
  writeLock = false;
}
