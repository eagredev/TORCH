/**
 * TORCH IDE — Worldstate Simulator Panel.
 * TORCH_MODULE
 *
 * Toggleable right-edge panel that lets the user set flags and variables,
 * then see which NPCs change state on the current map.
 *
 * Features:
 *   - Flag checkboxes + variable inputs (auto-populated from map data)
 *   - Affected NPCs list (real-time updates)
 *   - Analysis Mode: show ALL NPCs with ALL pages and met/unmet conditions
 *   - Preset save/load for state snapshots
 */

import { api } from "./app.js";
import { esc } from "./utils.js";
import { worldState, parseRawCondition } from "./worldstate.js";
import { ideOn, ideEmit, IDE_MAP_SELECTED } from "./ide.js";
import { getSelectedMap } from "./ide.js";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _panelEl = null;
let _visible = false;
let _analysisMode = false;
let _presetsOpen = false;
let _mapName = null;
let _mapData = null;
let _unsubs = [];
let _wsUnsub = null;

// ---------------------------------------------------------------------------
// Preset storage (localStorage)
// ---------------------------------------------------------------------------

const _PRESET_KEY = "torch_worldstate_presets";

function _loadPresets() {
  try { return JSON.parse(localStorage.getItem(_PRESET_KEY) || "{}"); } catch { return {}; }
}

function _savePresets(presets) {
  try { localStorage.setItem(_PRESET_KEY, JSON.stringify(presets)); } catch { /* ignore */ }
}

function _saveCurrentAsPreset(name) {
  if (!name) return;
  const presets = _loadPresets();
  presets[name] = worldState.toPreset();
  _savePresets(presets);
}

function _deletePreset(name) {
  const presets = _loadPresets();
  delete presets[name];
  _savePresets(presets);
}

function _applyPreset(name) {
  const presets = _loadPresets();
  if (presets[name]) {
    worldState.loadPreset(presets[name]);
    _renderPanel();
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function initWorldstatePanel(container) {
  _panelEl = document.createElement("div");
  _panelEl.className = "ws-panel";
  _panelEl.style.display = "none";
  container.appendChild(_panelEl);

  _unsubs.push(ideOn(IDE_MAP_SELECTED, (d) => {
    _mapName = d.name;
    if (_visible) _loadMapData();
  }));

  _mapName = getSelectedMap();
}

export function cleanupWorldstatePanel() {
  for (const u of _unsubs) u();
  _unsubs = [];
  if (_wsUnsub) { _wsUnsub(); _wsUnsub = null; }
  if (_panelEl && _panelEl.parentNode) _panelEl.remove();
  _panelEl = null;
  _visible = false;
}

export function toggleWorldstate() {
  _visible = !_visible;
  if (!_panelEl) return;
  _panelEl.style.display = _visible ? "flex" : "none";
  if (_visible) {
    _mapName = _mapName || getSelectedMap();
    _loadMapData();
    _wsUnsub = worldState.onChange(() => _renderResults());
  } else {
    if (_wsUnsub) { _wsUnsub(); _wsUnsub = null; }
    // Clear canvas worldstate overlay
    ideEmit("ide:worldstate-changed", { npcs: [], active: false });
  }
}

export function isWorldstateVisible() { return _visible; }

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function _loadMapData() {
  if (!_mapName) {
    _renderEmpty("Select a map to simulate worldstate");
    return;
  }
  _renderEmpty("Loading...");
  try {
    const res = await api(`/map/${encodeURIComponent(_mapName)}/worldstate-data`);
    if (!res.ok) {
      _renderEmpty(res.error || "Failed to load worldstate data");
      return;
    }
    _mapData = res.data;

    // Apply global conditions to the worldstate engine
    const globals = _mapData.global_conditions || [];
    worldState.applyGlobalConditions(globals);

    _renderPanel();
  } catch (e) {
    _renderEmpty(`Error: ${e.message}`);
  }
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function _renderEmpty(msg) {
  if (!_panelEl) return;
  _panelEl.innerHTML = `
    <div class="ws-header">
      <span class="ws-title">Worldstate</span>
      <button class="ws-close" title="Close">&times;</button>
    </div>
    <div class="ws-empty">${esc(msg)}</div>
  `;
  _panelEl.querySelector(".ws-close").addEventListener("click", toggleWorldstate);
}

function _renderPanel() {
  if (!_panelEl || !_mapData) return;

  const flags = _mapData.referenced_flags || [];
  const vars = _mapData.referenced_vars || [];

  let html = `
    <div class="ws-header">
      <span class="ws-title">Worldstate</span>
      <button class="ws-btn" data-action="reset" title="Reset all flags and vars">Reset</button>
      <button class="ws-btn ws-btn-analysis ${_analysisMode ? "ws-btn-active" : ""}"
              data-action="analysis" title="Show all NPC states">All</button>
      <button class="ws-btn ws-btn-presets ${_presetsOpen ? "ws-btn-active" : ""}"
              data-action="presets" title="Save/load worldstate presets">Presets</button>
      <button class="ws-close" title="Close">&times;</button>
    </div>
    <div class="ws-body">
  `;

  // Presets panel
  if (_presetsOpen) {
    const presets = _loadPresets();
    const names = Object.keys(presets);
    html += `<div class="ws-section ws-presets-section">
      <div class="ws-section-title">Presets</div>
      <div class="ws-presets-save">
        <input type="text" id="ws-preset-name" class="ws-preset-input" placeholder="Preset name...">
        <button class="ws-btn ws-btn-save-preset" data-action="save-preset">Save</button>
      </div>
      ${names.length === 0 ? `<div class="ws-presets-empty">No saved presets</div>` : ""}
      ${names.map(n => `
        <div class="ws-preset-row">
          <span class="ws-preset-name">${esc(n)}</span>
          <button class="ws-btn ws-btn-xs" data-action="load-preset" data-preset="${esc(n)}">Load</button>
          <button class="ws-btn ws-btn-xs ws-btn-del" data-action="del-preset" data-preset="${esc(n)}">✕</button>
        </div>`).join("")}
    </div>`;
  }

  // Global conditions section
  const globals = _mapData.global_conditions || [];
  if (globals.length > 0) {
    html += `<div class="ws-section ws-global-section">
      <div class="ws-section-title">Global</div>`;
    for (const gc of globals) {
      if (gc.type === "choice" && gc.options) {
        const current = gc.current || gc.default || "";
        const opts = gc.options.map(o =>
          `<option value="${esc(o.value)}" ${o.value === current || o.label === current ? "selected" : ""}>${esc(o.label)}</option>`
        ).join("");
        html += `<div class="ws-global-row">
          <span class="ws-global-label">${esc(gc.name)}</span>
          <select class="ws-global-select" data-global-id="${esc(gc.id)}">${opts}</select>
        </div>`;
      } else if (gc.type === "number") {
        const val = gc.current || gc.default || 0;
        html += `<div class="ws-global-row">
          <span class="ws-global-label">${esc(gc.name)}</span>
          <input type="number" class="ws-var-input" data-global-id="${esc(gc.id)}" value="${val}" min="0">
        </div>`;
      }
    }
    html += `</div>`;
  }

  // Flags section
  if (flags.length > 0) {
    html += `<div class="ws-section">
      <div class="ws-section-title">Flags (${flags.length})</div>`;
    for (const flag of flags) {
      const checked = worldState.getFlag(flag) ? "checked" : "";
      const short = flag.replace("FLAG_", "").replace("HIDE_", "H:").replace("DEFEATED_", "D:");
      html += `<label class="ws-flag-row">
        <input type="checkbox" data-flag="${esc(flag)}" ${checked}>
        <span class="ws-flag-name" title="${esc(flag)}">${esc(short)}</span>
      </label>`;
    }
    html += `</div>`;
  }

  // Vars section
  if (vars.length > 0) {
    html += `<div class="ws-section">
      <div class="ws-section-title">Variables (${vars.length})</div>`;
    for (const v of vars) {
      const val = worldState.getVar(v);
      const short = v.replace("VAR_", "");
      html += `<div class="ws-var-row">
        <span class="ws-var-name" title="${esc(v)}">${esc(short)}</span>
        <input type="number" class="ws-var-input" data-var="${esc(v)}" value="${val}" min="0">
      </div>`;
    }
    html += `</div>`;
  }

  // No flags/vars — helpful message
  if (flags.length === 0 && vars.length === 0) {
    html += `<div class="ws-section">
      <div class="ws-empty-hint">This map has no flag or variable references in its scripts.
        Add conditional logic to NPC scripts (if/switch/page) to see them here.</div>
    </div>`;
  }

  // Results section
  html += `<div class="ws-section">
    <div class="ws-section-title" id="ws-results-title">NPCs</div>
    <div class="ws-results" id="ws-results"></div>
  </div>`;

  html += `</div>`; // close ws-body

  _panelEl.innerHTML = html;

  // Wire header buttons
  _panelEl.querySelector(".ws-close").addEventListener("click", toggleWorldstate);
  _panelEl.querySelector('[data-action="reset"]').addEventListener("click", () => {
    worldState.reset();
    _renderPanel();
  });
  _panelEl.querySelector('[data-action="analysis"]').addEventListener("click", () => {
    _analysisMode = !_analysisMode;
    _renderPanel();
  });
  _panelEl.querySelector('[data-action="presets"]').addEventListener("click", () => {
    _presetsOpen = !_presetsOpen;
    _renderPanel();
  });

  // Wire preset actions
  const savePresetBtn = _panelEl.querySelector('[data-action="save-preset"]');
  if (savePresetBtn) {
    savePresetBtn.addEventListener("click", () => {
      const nameEl = _panelEl.querySelector("#ws-preset-name");
      const name = nameEl ? nameEl.value.trim() : "";
      if (name) { _saveCurrentAsPreset(name); _renderPanel(); }
    });
  }
  _panelEl.querySelectorAll('[data-action="load-preset"]').forEach(btn => {
    btn.addEventListener("click", () => _applyPreset(btn.dataset.preset));
  });
  _panelEl.querySelectorAll('[data-action="del-preset"]').forEach(btn => {
    btn.addEventListener("click", () => { _deletePreset(btn.dataset.preset); _renderPanel(); });
  });

  // Wire global condition selects
  _panelEl.querySelectorAll("[data-global-id]").forEach(el => {
    const handler = () => {
      const id = el.dataset.globalId;
      const value = el.value;
      // Update the condition in the local data
      const gc = (globals || []).find(c => c.id === id);
      if (gc) gc.current = value;
      // Re-apply global conditions to the engine
      worldState.applyGlobalConditions(globals);
      // Persist to server (fire-and-forget)
      fetch("/api/worldstate/global-conditions/set-value", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, value }),
      }).catch(() => {});
    };
    el.addEventListener("change", handler);
    el.addEventListener("input", handler);
  });

  // Wire flag checkboxes
  _panelEl.querySelectorAll("[data-flag]").forEach(cb => {
    cb.addEventListener("change", () => {
      worldState.setFlag(cb.dataset.flag, cb.checked);
    });
  });

  // Wire var inputs
  _panelEl.querySelectorAll("[data-var]").forEach(input => {
    input.addEventListener("input", () => {
      worldState.setVar(input.dataset.var, input.value);
    });
  });

  _renderResults();
}

function _renderResults() {
  const el = _panelEl ? _panelEl.querySelector("#ws-results") : null;
  const titleEl = _panelEl ? _panelEl.querySelector("#ws-results-title") : null;
  if (!el || !_mapData) return;

  const result = worldState.resolveMap(_mapData);

  if (_analysisMode) {
    _renderAnalysis(el, titleEl);
  } else {
    _renderAffected(el, titleEl, result);
  }

  // Emit event for canvas integration
  ideEmit("ide:worldstate-changed", {
    npcs: result.npcs,
    active: true,
    spriteUrlMap: _mapData.sprite_url_map || {},
  });
}

function _renderAffected(el, titleEl, result) {
  const changed = result.npcs.filter(n => n.changed || !n.visible);
  if (titleEl) titleEl.textContent = `Affected NPCs (${changed.length})`;

  if (changed.length === 0) {
    el.innerHTML = `<div class="ws-no-changes">No NPCs affected by current state</div>`;
    return;
  }

  el.innerHTML = changed.map(npc => {
    const vis = npc.visible
      ? `<span class="ws-vis ws-vis-show">visible</span>`
      : `<span class="ws-vis ws-vis-hide">hidden</span>`;
    const page = npc.activePage
      ? `<span class="ws-page-badge">P${npc.activePage}</span>`
      : "";
    const preview = npc.dialoguePreview
      ? `<div class="ws-npc-preview">${esc(npc.dialoguePreview)}</div>`
      : "";
    return `<div class="ws-npc-item">
      <div class="ws-npc-top">
        <span class="ws-npc-name">${esc(npc.name)}</span>
        ${vis} ${page}
      </div>
      ${preview}
    </div>`;
  }).join("");
}

function _renderAnalysis(el, titleEl) {
  // Show EVERY NPC with ALL their pages and condition status
  const npcs = _mapData.npcs || [];
  if (titleEl) titleEl.textContent = `All NPCs (${npcs.length})`;

  if (npcs.length === 0) {
    el.innerHTML = `<div class="ws-no-changes">No NPCs on this map</div>`;
    return;
  }

  el.innerHTML = npcs.map(npc => {
    const pages = npc.pages || [];
    const visFlag = npc.visibility_flag;
    const isHidden = visFlag ? worldState.getFlag(visFlag) : false;

    let pagesHtml = "";
    if (pages.length > 0) {
      const activePage = worldState.resolveActivePage
        ? null  // we'll compute inline
        : null;

      // Find active page (highest-numbered matching)
      let activeNum = 1;
      const sorted = [...pages].sort((a, b) => b.page_num - a.page_num);
      for (const p of sorted) {
        if (!p.condition || worldState.evaluateRawCondition(p.condition)) {
          activeNum = p.page_num;
          break;
        }
      }

      pagesHtml = pages.map(p => {
        const isActive = p.page_num === activeNum;
        const condMet = !p.condition || worldState.evaluateRawCondition(p.condition);
        const icon = isActive ? "\u2605" : condMet ? "\u25CB" : "\u2717";
        const cls = isActive ? "ws-page-active" : condMet ? "ws-page-met" : "ws-page-unmet";
        const condText = p.condition
          ? _formatConditionStatus(p.condition)
          : "(default)";
        const dlg = p.dialogue_preview ? ` — ${esc(p.dialogue_preview)}` : "";
        return `<div class="ws-page-row ${cls}">
          <span class="ws-page-icon">${icon}</span>
          <span class="ws-page-label">Page ${p.page_num}</span>
          <span class="ws-page-cond">${condText}</span>
          ${dlg ? `<div class="ws-page-dlg">${dlg}</div>` : ""}
        </div>`;
      }).join("");
    }

    const visHtml = visFlag
      ? `<span class="ws-vis ${isHidden ? "ws-vis-hide" : "ws-vis-show"}">${isHidden ? "hidden" : "visible"}</span>`
      : "";

    return `<div class="ws-npc-item ws-npc-analysis">
      <div class="ws-npc-top">
        <span class="ws-npc-name">${esc(npc.name)}</span>
        <span class="ws-npc-id">#${npc.npc_id}</span>
        ${visHtml}
      </div>
      ${pagesHtml}
    </div>`;
  }).join("");
}

/**
 * Format a condition string with met/unmet highlighting.
 * Shows which parts of compound conditions pass or fail.
 */
function _formatConditionStatus(condStr) {
  if (!condStr) return "";
  // For compound conditions, evaluate each part
  const parts = condStr.split(/\s+(and|or)\s+/);
  if (parts.length <= 1) {
    const met = worldState.evaluateRawCondition(condStr);
    const cls = met ? "ws-cond-met" : "ws-cond-fail";
    return `<span class="${cls}">${esc(condStr)}</span>`;
  }

  return parts.map(part => {
    if (part === "and" || part === "or") return ` <span class="ws-cond-op">${part}</span> `;
    const met = worldState.evaluateRawCondition(part);
    const cls = met ? "ws-cond-met" : "ws-cond-fail";
    return `<span class="${cls}">${esc(part)}</span>`;
  }).join("");
}

// ---------------------------------------------------------------------------
// Inject CSS (once)
// ---------------------------------------------------------------------------

let _cssInjected = false;

export function injectWorldstateCSS() {
  if (_cssInjected) return;
  _cssInjected = true;
  const style = document.createElement("style");
  style.textContent = `
.ws-panel {
  position: absolute;
  top: 0; right: 0; bottom: 0;
  width: 280px;
  background: var(--bg-primary, #1a1a2e);
  border-left: 1px solid rgba(255,255,255,0.08);
  display: flex;
  flex-direction: column;
  z-index: 50;
  overflow: hidden;
  font-size: 0.78rem;
}
.ws-header {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.4rem 0.5rem;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  flex-shrink: 0;
}
.ws-title {
  font-weight: 700;
  font-size: 0.82rem;
  flex: 1;
}
.ws-close, .ws-btn {
  background: none;
  border: 1px solid rgba(255,255,255,0.1);
  color: var(--text-secondary, #aaa);
  cursor: pointer;
  border-radius: 3px;
  padding: 1px 6px;
  font-size: 0.68rem;
}
.ws-close:hover, .ws-btn:hover {
  background: rgba(255,255,255,0.08);
}
.ws-btn-active {
  background: var(--accent, #4a9eff) !important;
  color: #111 !important;
  border-color: var(--accent, #4a9eff) !important;
  font-weight: 700;
}
.ws-body {
  flex: 1;
  overflow-y: auto;
  padding: 0.3rem 0;
}
.ws-empty {
  padding: 1rem;
  color: var(--text-dim, #666);
  text-align: center;
  font-size: 0.75rem;
}
.ws-empty-hint {
  color: var(--text-dim, #666);
  font-size: 0.72rem;
  line-height: 1.4;
  font-style: italic;
}
.ws-section {
  padding: 0.3rem 0.5rem;
}
.ws-section-title {
  font-weight: 700;
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-dim, #666);
  margin-bottom: 0.2rem;
}
.ws-global-section {
  border-bottom: 1px solid rgba(255,255,255,0.08);
  padding-bottom: 0.4rem;
  margin-bottom: 0.2rem;
}
.ws-global-row {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 2px 0;
}
.ws-global-label {
  font-size: 0.72rem;
  color: var(--text-primary, #ddd);
  flex: 1;
  font-weight: 600;
}
.ws-global-select {
  padding: 2px 4px;
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 3px;
  background: rgba(255,255,255,0.08);
  color: var(--text-primary, #ddd);
  font-size: 0.72rem;
  cursor: pointer;
}
.ws-flag-row {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 2px 0;
  cursor: pointer;
}
.ws-flag-row:hover { background: rgba(255,255,255,0.03); }
.ws-flag-name {
  font-size: 0.7rem;
  color: var(--text-primary, #ddd);
  word-break: break-all;
}
.ws-var-row {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 2px 0;
}
.ws-var-name {
  font-size: 0.7rem;
  color: var(--text-primary, #ddd);
  flex: 1;
}
.ws-var-input {
  width: 3.5rem;
  padding: 2px 4px;
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 3px;
  background: rgba(255,255,255,0.06);
  color: var(--text-primary, #ddd);
  font-size: 0.7rem;
}
.ws-no-changes {
  color: var(--text-dim, #666);
  font-style: italic;
  padding: 0.3rem 0;
  font-size: 0.72rem;
}
.ws-npc-item {
  padding: 0.3rem 0;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
.ws-npc-analysis {
  padding: 0.4rem 0;
}
.ws-npc-top {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  flex-wrap: wrap;
}
.ws-npc-name { font-weight: 600; font-size: 0.75rem; }
.ws-npc-id { color: var(--text-dim, #666); font-size: 0.6rem; }
.ws-vis { font-size: 0.6rem; font-weight: 600; padding: 0 3px; border-radius: 2px; }
.ws-vis-show { color: var(--status-ok, #2ecc71); }
.ws-vis-hide { color: var(--status-error, #e74c3c); background: rgba(231,76,60,0.1); }
.ws-page-badge {
  background: var(--accent, #4a9eff);
  color: #111;
  font-size: 0.58rem;
  font-weight: 700;
  padding: 0 4px;
  border-radius: 3px;
}
.ws-npc-preview {
  color: var(--text-muted, #888);
  font-size: 0.68rem;
  font-style: italic;
  margin-top: 2px;
}
/* Analysis mode — page rows */
.ws-page-row {
  display: flex;
  align-items: baseline;
  gap: 0.25rem;
  padding: 1px 0 1px 0.6rem;
  font-size: 0.68rem;
  flex-wrap: wrap;
}
.ws-page-icon { width: 1em; text-align: center; flex-shrink: 0; }
.ws-page-label { font-weight: 600; flex-shrink: 0; }
.ws-page-cond { font-size: 0.65rem; }
.ws-page-dlg {
  width: 100%;
  padding-left: 1.25em;
  color: var(--text-muted, #888);
  font-style: italic;
  font-size: 0.62rem;
}
.ws-page-active { color: var(--status-ok, #2ecc71); }
.ws-page-active .ws-page-icon { color: #facc15; }
.ws-page-met { color: var(--text-secondary, #aaa); }
.ws-page-unmet { color: var(--text-dim, #555); }
.ws-cond-met { color: var(--status-ok, #2ecc71); }
.ws-cond-fail { color: var(--status-error, #e74c3c); text-decoration: line-through; }
.ws-cond-op { color: var(--text-dim, #666); }
/* Presets section */
.ws-presets-section {
  border-bottom: 1px solid rgba(255,255,255,0.08);
  padding-bottom: 0.5rem;
  margin-bottom: 0.2rem;
}
.ws-presets-save {
  display: flex;
  gap: 0.3rem;
  margin-bottom: 0.3rem;
}
.ws-preset-input {
  flex: 1;
  padding: 2px 5px;
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 3px;
  background: var(--bg-secondary, #111);
  color: var(--text-primary, #eee);
  font-size: 0.72rem;
}
.ws-presets-empty {
  color: var(--text-dim, #555);
  font-size: 0.7rem;
  font-style: italic;
  padding: 2px 0;
}
.ws-preset-row {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 2px 0;
}
.ws-preset-name {
  flex: 1;
  font-size: 0.72rem;
  color: var(--text-primary, #ddd);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ws-btn-xs {
  padding: 1px 5px;
  font-size: 0.65rem;
}
.ws-btn-save-preset {
  white-space: nowrap;
}
.ws-btn-del {
  color: var(--status-error, #e74c3c);
  border-color: rgba(231,76,60,0.3);
}
.ws-btn-del:hover {
  background: rgba(231,76,60,0.15) !important;
}
  `;
  document.head.appendChild(style);
}
