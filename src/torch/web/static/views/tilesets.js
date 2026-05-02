/**
 * TORCH Web GUI — Tileset Editor view.
 * Entry point that orchestrates the modular tileset editor.
 * Replaces the monolithic metatiles.js with a component architecture.
 */

import { esc } from "../utils.js";
import { renderStudioNavbar } from "../studioNav.js";
import {
  state, emit, on, off,
  METATILE_SELECTED, METATILE_MODIFIED, DIRTY_CHANGED, SAVE_COMPLETED,
  WIZARD_STARTED, WIZARD_EXITED, MODE_CHANGED,
  LAYER_COLORS, CHANGED_COLOR,
  loadTilesetData, loadTilesImage, doSave, showToast, resetState,
  getSelectedMetatile, setBeforeChangeHook,
} from "./tileset/state.js";
import { renderGrid, applyFilter, updateGridCell } from "./tileset/grid.js";
import { renderDetailPanel, DETAIL_EXTRA_CSS } from "./tileset/detail.js";
import {
  startWizard, exitWizard, wizardEligible, wizardUnconfigured,
} from "./tileset/layers.js";
import { cleanupRenderer } from "./tileset/renderer.js";
import { BEHAVIOR_PICKER_CSS, cleanupBehaviorPicker } from "./tileset/behaviorPicker.js";
import { initHistory, snapshotBeforeChange, undo, redo, canUndo, canRedo, cleanup as cleanupHistory } from "./tileset/history.js";
import { cleanupTilePalette } from "./tileset/tilePalette.js";
import { cleanupPixelEditor as _cleanupPixelEditor } from "./tileset/pixelEditor.js";
import { handleChordKeydown, cleanupClipboard } from "./tileset/clipboard.js";
import { api, postApi } from "../app.js";

// ---------------------------------------------------------------------------
// CSS
// ---------------------------------------------------------------------------

const STYLE_ID = "tilesets-view-css";
let _styleEl = null;

const STYLES = `
/* Header bar */
.ts-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1rem;
  flex-wrap: wrap;
}
.ts-header h2 {
  margin: 0;
  font-size: 1.1rem;
  color: var(--text-primary, #cdd6f4);
}
.ts-back {
  color: var(--text-secondary, #bac2de);
  text-decoration: none;
  font-size: 0.85rem;
}
.ts-back:hover { color: var(--accent, #cba6f7); }
.ts-save-btn {
  margin-left: auto;
  padding: 0.4rem 1rem;
  font-size: 0.85rem;
  font-weight: 600;
  background: var(--accent, #cba6f7);
  color: #fff;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: opacity 0.15s;
}
.ts-save-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.ts-save-btn:not(:disabled):hover { opacity: 0.85; }
.ts-save-count {
  font-size: 0.75rem;
  color: var(--text-secondary, #bac2de);
}

/* Main layout — two panels by default, three when context panel visible */
.ts-layout {
  display: flex;
  gap: 1.5rem;
}
.ts-left {
  flex: 0 0 30%;
  min-width: 0;
}
.ts-right {
  flex: 1 1 auto;
  min-width: 0;
}
/* Context panel (tile palette in Compose mode) — hidden by default */
.ts-context {
  flex: 0 0 35%;
  min-width: 0;
  display: none;
}
/* When context is hidden, detail takes more space */
.ts-layout:not(.has-context) .ts-left {
  flex: 0 0 60%;
}
.ts-layout:not(.has-context) .ts-right {
  flex: 0 0 38%;
}

/* Filter bar */
.ts-filter-bar {
  display: flex;
  gap: 0;
  margin-bottom: 0.75rem;
}
.ts-filter-btn {
  padding: 0.3rem 0.7rem;
  font-size: 0.75rem;
  background: var(--surface-2, #313244);
  color: var(--text-dim, #6c7086);
  border: 1px solid var(--border-subtle, #45475a);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.ts-filter-btn:first-child { border-radius: 4px 0 0 4px; }
.ts-filter-btn:last-child { border-radius: 0 4px 4px 0; }
.ts-filter-btn + .ts-filter-btn { border-left: none; }
.ts-filter-btn.active {
  background: var(--accent, #cba6f7);
  color: #fff;
  border-color: var(--accent, #cba6f7);
}
.ts-filter-btn:hover:not(.active) {
  background: rgba(255,255,255,0.05);
  color: #ccc;
}

/* Grid */
.ts-grid {
  display: grid;
  grid-template-columns: repeat(8, 48px);
  gap: 3px;
  max-height: 70vh;
  overflow-y: auto;
  padding: 4px;
  background: var(--surface-1, #1e1e2e);
  border: 1px solid var(--border-subtle, #45475a);
  border-radius: 6px;
  align-content: start;
}
.ts-cell {
  position: relative;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  cursor: pointer;
  border: 2px solid transparent;
  transition: border-color 0.15s, opacity 0.15s;
}
.ts-cell canvas {
  width: 48px;
  height: 48px;
  image-rendering: pixelated;
  display: block;
}
.ts-cell.selected {
  outline: 2px solid var(--accent, #cba6f7);
  outline-offset: 1px;
}
.ts-cell.dimmed { opacity: 0.2; }
.ts-cell.changed::after {
  content: "";
  position: absolute;
  top: -1px;
  right: -1px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: ${CHANGED_COLOR};
}
.ts-cell-id {
  position: absolute;
  bottom: -1px;
  right: 1px;
  font-size: 7px;
  color: rgba(255,255,255,0.4);
  pointer-events: none;
}

/* Detail panel */
.ts-detail {
  background: var(--surface-2, #313244);
  border: 1px solid var(--border-subtle, #45475a);
  border-radius: 8px;
  padding: 1rem;
  position: sticky;
  top: 1rem;
}
.ts-detail-empty {
  color: var(--text-dim, #6c7086);
  font-size: 0.85rem;
  text-align: center;
  padding: 2rem 0;
}
.ts-detail-preview {
  display: flex;
  justify-content: center;
  margin-bottom: 1rem;
}
.ts-detail-preview canvas {
  width: 128px;
  height: 128px;
  image-rendering: pixelated;
  border: 1px solid var(--border-subtle, #45475a);
  border-radius: 4px;
  background: #000;
}
.ts-detail-id {
  text-align: center;
  font-family: monospace;
  font-size: 0.8rem;
  color: var(--text-dim, #6c7086);
  margin-bottom: 0.75rem;
}
.ts-clear-edits {
  margin-left: 0.4rem;
  padding: 0.1rem 0.5rem;
  font-size: 0.68rem;
  background: transparent;
  color: var(--status-error, #f38ba8);
  border: 1px solid var(--status-error, #f38ba8);
  border-radius: 3px;
  cursor: pointer;
  opacity: 0.7;
  transition: opacity 0.15s;
}
.ts-clear-edits:hover { opacity: 1; }

/* Mode tabs */
.ts-mode-tabs {
  display: flex;
  gap: 0;
  margin-bottom: 1rem;
  border-bottom: 1px solid var(--border-subtle, #45475a);
}
.ts-mode-tab {
  padding: 0.4rem 0.8rem;
  font-size: 0.78rem;
  background: transparent;
  color: var(--text-dim, #6c7086);
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}
.ts-mode-tab.active {
  color: var(--accent, #cba6f7);
  border-bottom-color: var(--accent, #cba6f7);
}
.ts-mode-tab:hover:not(.active):not(:disabled) {
  color: var(--text-secondary, #bac2de);
}
.ts-mode-tab:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.ts-mode-placeholder {
  color: var(--text-dim, #6c7086);
  font-size: 0.85rem;
  text-align: center;
  padding: 2rem 0;
  font-style: italic;
}

/* Sections */
.ts-section {
  margin-bottom: 1rem;
}
.ts-section-label {
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--text-dim, #6c7086);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.4rem;
}
.ts-depth-status {
  font-size: 0.82rem;
  padding: 0.4rem 0.6rem;
  border-radius: 4px;
  margin-bottom: 0.4rem;
}
.ts-depth-overlap {
  color: #f8d030;
  background: rgba(248, 208, 48, 0.08);
  border: 1px solid rgba(248, 208, 48, 0.2);
}
.ts-depth-behind {
  color: #a6e3a1;
  background: rgba(166, 227, 161, 0.08);
  border: 1px solid rgba(166, 227, 161, 0.2);
}
.ts-depth-btn {
  padding: 0.3rem 0.8rem;
  border-radius: 4px;
  border: 1px solid var(--border-subtle, #45475a);
  background: var(--surface-2, #313244);
  color: var(--text-primary, #cdd6f4);
  cursor: pointer;
  font-size: 0.8rem;
}
.ts-depth-btn:hover { background: var(--surface-3, #45475a); }

/* Layer toggles */
.ts-toggle-group {
  display: flex;
  gap: 0.75rem;
}
.ts-toggle-label {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.8rem;
  color: var(--text-secondary, #bac2de);
  cursor: pointer;
}
.ts-toggle-label input[type="checkbox"] {
  accent-color: var(--accent, #cba6f7);
}

/* Toast */
.ts-toast {
  position: fixed;
  bottom: 4rem;
  left: 50%;
  transform: translateX(-50%);
  background: var(--surface-3, #585b70);
  color: #fff;
  padding: 0.5rem 1.25rem;
  border-radius: 6px;
  font-size: 0.85rem;
  z-index: 9999;
  opacity: 0;
  transition: opacity 0.3s;
  pointer-events: none;
}
.ts-toast.visible { opacity: 1; }

/* Loading */
.ts-loading {
  text-align: center;
  padding: 3rem;
  color: var(--text-dim, #6c7086);
  font-size: 0.9rem;
}

/* Responsive */
@media (max-width: 900px) {
  .ts-layout { flex-direction: column; }
  .ts-left, .ts-right { flex: 1 1 auto; }
  .ts-detail { position: static; }
}

/* Wizard button */
/* Restore button */
.ts-restore-wrap {
  position: relative;
  display: inline-block;
}
.ts-restore-btn {
  padding: 0.35rem 1rem;
  background: var(--surface-2, #313244);
  color: var(--text-secondary, #bac2de);
  border: 1px solid var(--border-subtle, #45475a);
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.85rem;
}
.ts-restore-btn:hover { background: var(--surface-3, #45475a); }
.ts-restore-menu {
  display: none;
  position: absolute;
  top: 100%;
  right: 0;
  z-index: 20;
  background: var(--surface-1, #1e1e2e);
  border: 1px solid var(--border-subtle, #313244);
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
  min-width: 280px;
  padding: 0.5rem;
  margin-top: 0.2rem;
}
.ts-restore-menu.open { display: block; }
.ts-restore-menu-title {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--text-dim, #585b70);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.4rem;
}
.ts-snap-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.4rem 0.5rem;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.1s;
  margin-bottom: 0.2rem;
}
.ts-snap-item:hover { background: var(--surface-2, #313244); }
.ts-snap-label {
  font-size: 0.8rem;
  color: var(--text-primary, #cdd6f4);
}
.ts-snap-time {
  font-size: 0.7rem;
  color: var(--text-dim, #585b70);
}
.ts-snap-original { color: var(--accent, #f8d030); }
.ts-restore-empty {
  font-size: 0.78rem;
  color: var(--text-dim, #585b70);
  text-align: center;
  padding: 1rem;
  font-style: italic;
}

.ts-wizard-btn {
  padding: 0.35rem 1rem;
  background: var(--surface-2, #313244);
  color: var(--accent, #f8d030);
  border: 1px solid var(--accent, #f8d030);
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 600;
}
.ts-wizard-btn:hover { background: var(--surface-3, #45475a); }
.ts-wizard-wrap {
  position: relative;
  display: inline-block;
}
.ts-wizard-menu {
  display: none;
  position: absolute;
  top: 100%;
  left: 0;
  z-index: 20;
  background: var(--surface-1, #1e1e2e);
  border: 1px solid var(--border-subtle, #313244);
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
  min-width: 220px;
  padding: 0.3rem 0;
  margin-top: 0.2rem;
}
.ts-wizard-menu.open { display: block; }
.ts-wiz-opt {
  display: block;
  width: 100%;
  text-align: left;
  padding: 0.45rem 0.9rem;
  border: none;
  background: transparent;
  color: var(--text-primary, #cdd6f4);
  cursor: pointer;
  font-size: 0.82rem;
}
.ts-wiz-opt:hover { background: var(--surface-2, #313244); }

/* ---- Wizard mode (reuse same class names as metatiles.js) ---- */
.wiz-container { max-width: 700px; margin: 0 auto; padding: 1rem; }
.wiz-header { text-align: center; margin-bottom: 1.5rem; }
.wiz-header h2 { color: var(--text-primary, #cdd6f4); margin: 0 0 0.25rem 0; font-size: 1.3rem; }
.wiz-subtitle { color: var(--text-secondary, #a6adc8); font-size: 0.85rem; }
.wiz-progress { margin-top: 0.5rem; height: 6px; background: var(--surface-2, #313244); border-radius: 3px; overflow: hidden; }
.wiz-progress-bar { height: 100%; background: var(--accent, #f8d030); transition: width 0.2s ease; }
.wiz-body { background: var(--surface-1, #1e1e2e); border-radius: 8px; padding: 1.5rem; border: 1px solid var(--border-subtle, #313244); }
.wiz-prompt { font-size: 1.1rem; color: var(--text-primary, #cdd6f4); margin: 0 0 1rem 0; font-weight: 600; text-align: center; }
.wiz-compare-row { display: flex; justify-content: center; gap: 1.5rem; margin-bottom: 0.5rem; }
.wiz-compare-btn {
  display: flex; flex-direction: column; align-items: center; gap: 0.4rem;
  padding: 1rem; border-radius: 8px; cursor: pointer;
  border: 2px solid var(--border-subtle, #313244); background: var(--surface-0, #11111b);
  transition: border-color 0.15s, background 0.15s, transform 0.1s; width: 190px; text-align: center;
}
.wiz-compare-btn:hover { border-color: var(--accent, #f8d030); background: rgba(248, 208, 48, 0.06); transform: translateY(-2px); }
.wiz-compare-btn strong { color: var(--text-primary, #cdd6f4); font-size: 0.9rem; }
.wiz-compare-btn span { color: var(--text-secondary, #a6adc8); font-size: 0.75rem; }
.wiz-compare-canvas { width: 128px; height: 128px; image-rendering: pixelated; background: #181825; border-radius: 4px; }
.wiz-extra-row { display: flex; justify-content: center; align-items: center; gap: 1rem; margin-top: 0.8rem; }
.wiz-extra-btn {
  padding: 0.4rem 1rem; border: 1px solid var(--border-subtle, #313244);
  background: transparent; color: var(--text-secondary, #a6adc8); border-radius: 4px; cursor: pointer; font-size: 0.8rem;
}
.wiz-extra-btn:hover { background: var(--surface-2, #313244); color: var(--text-primary, #cdd6f4); }
.wiz-skip-btn {
  padding: 0.3rem 1rem; border: 1px solid var(--border-subtle, #313244);
  background: transparent; color: var(--text-secondary, #a6adc8); border-radius: 4px; cursor: pointer; font-size: 0.8rem;
}
.wiz-skip-btn:hover { background: var(--surface-2, #313244); }
.wiz-meta { margin-top: 1rem; font-size: 0.7rem; color: var(--text-dim, #585b70); text-align: center; }
.wiz-footer { display: flex; align-items: center; gap: 1rem; margin-top: 1.5rem; justify-content: center; }
.wiz-nav-btn {
  padding: 0.4rem 1rem; border-radius: 4px; border: 1px solid var(--border-subtle, #313244);
  background: var(--surface-2, #313244); color: var(--text-primary, #cdd6f4); cursor: pointer; font-size: 0.85rem;
}
.wiz-nav-btn:disabled { opacity: 0.4; cursor: default; }
.wiz-nav-btn:not(:disabled):hover { background: var(--surface-3, #45475a); }
.wiz-exit-btn { color: var(--text-secondary, #a6adc8); }
.wiz-changes { font-size: 0.8rem; color: var(--accent, #f8d030); }
`;

function _injectCSS() {
  if (document.getElementById(STYLE_ID)) return;
  _styleEl = document.createElement("style");
  _styleEl.id = STYLE_ID;
  _styleEl.textContent = STYLES + BEHAVIOR_PICKER_CSS + DETAIL_EXTRA_CSS;
  document.head.appendChild(_styleEl);
}

// ---------------------------------------------------------------------------
// Event handlers (module-level, cleaned up on cleanup())
// ---------------------------------------------------------------------------

let _handlers = [];

function _listen(event, fn) {
  const h = on(event, fn);
  _handlers.push({ event, handler: h });
}

// ---------------------------------------------------------------------------
// Main render
// ---------------------------------------------------------------------------

function _renderAll() {
  if (!state.container) return;

  const displayName = (state.secondaryName || state.primaryName)
    .replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());

  let html = renderStudioNavbar("Assets");

  // Header
  html += `<div class="ts-header">`;
  html += `<a href="#/assets" class="ts-back">&larr; Assets</a>`;
  html += `<h2>${esc(displayName)} &mdash; Tileset Editor</h2>`;
  html += `<div class="ts-wizard-wrap">`;
  html += `<button class="ts-wizard-btn">Wizard &#9662;</button>`;
  html += `<div class="ts-wizard-menu">`;
  const unconfigCount = wizardUnconfigured().length;
  const allCount = wizardEligible().length;
  html += `<button class="ts-wiz-opt" data-wiz="new">Unconfigured tiles (${unconfigCount})</button>`;
  html += `<button class="ts-wiz-opt" data-wiz="all">All tiles (${allCount})</button>`;
  if (state.selectedId != null) {
    html += `<button class="ts-wiz-opt" data-wiz="from-selected">From selected (#${state.selectedId})</button>`;
  }
  html += `</div></div>`;
  html += `<div class="ts-restore-wrap">`;
  html += `<button class="ts-restore-btn">Restore</button>`;
  html += `<div class="ts-restore-menu" id="ts-restore-menu"></div>`;
  html += `</div>`;
  html += `<span class="ts-save-count"></span>`;
  html += `<button class="ts-save-btn" disabled>Save</button>`;
  html += `</div>`;

  // Layout
  html += `<div class="ts-layout">`;

  // Left panel
  html += `<div class="ts-left">`;
  html += `<div class="ts-filter-bar">`;
  for (const [f, label] of [["all", "All"], ["overlaps", "Overlaps Player"], ["behind", "Behind Player"]]) {
    const active = f === state.activeFilter ? " active" : "";
    html += `<button class="ts-filter-btn${active}" data-filter="${esc(f)}">${esc(label)}</button>`;
  }
  html += `</div>`;

  if (!state.tilesImgLoaded) {
    html += `<div class="ts-loading">Loading tile graphics...</div>`;
  } else if (!state.tilesImg) {
    html += `<div class="ts-loading">Could not load tiles.png for this tileset.</div>`;
  }

  html += `<div class="ts-grid"></div>`;
  html += `</div>`;

  // Center panel (detail)
  html += `<div class="ts-right">`;
  html += `<div class="ts-detail">`;
  html += `<div class="ts-detail-empty">Select a metatile from the grid to edit.</div>`;
  html += `</div>`;
  html += `</div>`;

  // Right context panel (tile palette in Compose mode — hidden by default)
  html += `<div class="ts-context"></div>`;

  html += `</div>`;

  state.container.innerHTML = html;

  // Render grid
  if (state.tilesImgLoaded) {
    renderGrid(state.container);
  }

  // Render detail if something was selected
  if (state.selectedId != null) {
    renderDetailPanel();
  }

  // Bind top-level events
  _bindTopEvents();
  _updateSaveButton();
}

function _bindTopEvents() {
  if (!state.container) return;

  // Save button
  const saveBtn = state.container.querySelector(".ts-save-btn");
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      saveBtn.disabled = true;
      saveBtn.textContent = "Saving...";
      try {
        await _saveAll();
      } catch (err) {
        showToast("Save failed: " + err.message);
      }
      saveBtn.disabled = state.pendingChanges.size === 0;
      saveBtn.textContent = "Save";
    });
  }

  // Wizard dropdown
  const wizBtn = state.container.querySelector(".ts-wizard-btn");
  const wizMenu = state.container.querySelector(".ts-wizard-menu");
  if (wizBtn && wizMenu) {
    wizBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      wizMenu.classList.toggle("open");
    });
    document.addEventListener("click", () => wizMenu.classList.remove("open"), { once: false });
    wizMenu.querySelectorAll(".ts-wiz-opt").forEach(opt => {
      opt.addEventListener("click", (e) => {
        e.stopPropagation();
        wizMenu.classList.remove("open");
        const mode = opt.dataset.wiz;
        if (mode === "new") startWizard("unconfigured");
        else if (mode === "all") startWizard("all");
        else if (mode === "from-selected") startWizard("from-selected");
      });
    });
  }

  // Filter buttons
  state.container.querySelectorAll(".ts-filter-btn").forEach(btn => {
    btn.addEventListener("click", () => applyFilter(btn.dataset.filter));
  });

  // Restore button
  const restoreBtn = state.container.querySelector(".ts-restore-btn");
  const restoreMenu = document.getElementById("ts-restore-menu");
  if (restoreBtn && restoreMenu) {
    restoreBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (restoreMenu.classList.contains("open")) {
        restoreMenu.classList.remove("open");
        return;
      }
      // Load snapshots
      const name = state.secondaryName || state.primaryName;
      const res = await api(`/tilesets/${encodeURIComponent(name)}/snapshots`);
      const snapshots = (res && (res.data || res).snapshots) || [];

      if (snapshots.length === 0) {
        restoreMenu.innerHTML = `<div class="ts-restore-empty">No snapshots yet. Snapshots are created automatically when you save.</div>`;
      } else {
        let mhtml = `<div class="ts-restore-menu-title">Restore tileset</div>`;
        for (const snap of snapshots) {
          const cls = snap.is_original ? " ts-snap-original" : "";
          mhtml += `<div class="ts-snap-item" data-snap="${esc(snap.id)}">`;
          mhtml += `<span class="ts-snap-label${cls}">${esc(snap.label)}</span>`;
          if (!snap.is_original && snap.timestamp) {
            mhtml += `<span class="ts-snap-time">${esc(snap.timestamp)}</span>`;
          }
          mhtml += `</div>`;
        }
        restoreMenu.innerHTML = mhtml;

        // Bind restore clicks
        restoreMenu.querySelectorAll(".ts-snap-item").forEach(item => {
          item.addEventListener("click", async () => {
            const snapId = item.dataset.snap;
            restoreMenu.classList.remove("open");
            restoreBtn.textContent = "Restoring...";
            restoreBtn.disabled = true;
            const rRes = await postApi(`/tilesets/${encodeURIComponent(name)}/restore`, { snapshot_id: snapId });
            if (rRes && rRes.ok !== false && !rRes.error) {
              showToast(`Restored from ${snapId}`);
              // Reload all data
              state.pendingChanges.clear();
              if (state.tilePixelChanges) state.tilePixelChanges.clear();
              await Promise.all([
                loadTilesetData(name),
                loadTilesImage(name),
              ]);
              _renderAll();
            } else {
              showToast("Restore failed: " + ((rRes && rRes.error) || "Unknown error"));
            }
            restoreBtn.textContent = "Restore";
            restoreBtn.disabled = false;
          });
        });
      }

      restoreMenu.classList.add("open");
    });
    document.addEventListener("click", () => restoreMenu.classList.remove("open"));
  }
}

function _updateSaveButton() {
  if (!state.container) return;
  const btn = state.container.querySelector(".ts-save-btn");
  const countEl = state.container.querySelector(".ts-save-count");
  const mtCount = state.pendingChanges.size;
  const pxCount = state.tilePixelChanges ? state.tilePixelChanges.size : 0;
  const total = mtCount + pxCount;
  if (btn) btn.disabled = total === 0;
  if (countEl) {
    if (total === 0) {
      countEl.textContent = "";
    } else {
      const parts = [];
      if (mtCount > 0) parts.push(`${mtCount} metatile${mtCount !== 1 ? "s" : ""}`);
      if (pxCount > 0) parts.push(`${pxCount} tile${pxCount !== 1 ? "s" : ""}`);
      countEl.textContent = parts.join(" + ");
    }
  }
}

// ---------------------------------------------------------------------------
// Save all (attributes + composition)
// ---------------------------------------------------------------------------

async function _saveAll() {
  const name = state.secondaryName || state.primaryName;
  const enc = encodeURIComponent(name);

  // Separate composition changes (tiles) from attribute changes (behavior/layer)
  const attrChanges = [];
  const compChanges = [];

  for (const [id, entry] of state.pendingChanges) {
    // Composition change (tile refs modified)
    if (entry.tiles) {
      compChanges.push({ id, tiles: entry.tiles });
    }
    // Attribute changes (behavior, layer_type, layer_action)
    const attrObj = { id };
    let hasAttr = false;
    if (entry.layer_type != null) { attrObj.layer_type = entry.layer_type; hasAttr = true; }
    if (entry.layer_action) { attrObj.layer_action = entry.layer_action; hasAttr = true; }
    if (entry.behavior != null) { attrObj.behavior = entry.behavior; hasAttr = true; }
    if (hasAttr) attrChanges.push(attrObj);
  }

  let savedCount = 0;

  // Save pixel changes first (tiles.png)
  if (state.tilePixelChanges && state.tilePixelChanges.size > 0) {
    const pixelData = {};
    const pixels = state.tilePixels;
    const sheetW = state.tileSheetW;
    const sheetH = state.tileSheetH;

    if (pixels && sheetW) {
      const tilesPerRow = sheetW / 8;
      for (const [globalIdx] of state.tilePixelChanges) {
        // Extract the 64 pixels for this tile
        let localIdx = globalIdx;
        let usePixels = pixels;
        let useW = sheetW;
        if (state.primaryTileOffset > 0 && globalIdx < state.primaryTileOffset) {
          // Primary tile — use primary pixel data
          usePixels = state.primaryPixels;
          useW = state.primarySheetW;
          localIdx = globalIdx;
        } else if (state.primaryTileOffset > 0) {
          localIdx = globalIdx - state.primaryTileOffset;
        }
        if (!usePixels) continue;
        const tpr = useW / 8;
        const tileCol = localIdx % tpr;
        const tileRow = Math.floor(localIdx / tpr);
        const baseX = tileCol * 8;
        const baseY = tileRow * 8;
        const tile64 = [];
        for (let py = 0; py < 8; py++) {
          for (let px = 0; px < 8; px++) {
            tile64.push(usePixels[(baseY + py) * useW + (baseX + px)] || 0);
          }
        }
        pixelData[String(localIdx)] = tile64;
      }
    }

    if (Object.keys(pixelData).length > 0) {
      const res = await postApi(`/tilesets/${enc}/tiles/save`, { tiles: pixelData });
      if (res && res.ok !== false && !res.error) {
        savedCount += (res.data || res).saved || Object.keys(pixelData).length;
        state.tilePixelChanges.clear();
      } else {
        showToast("Save failed (pixels): " + ((res && (res.data?.error || res.error)) || "Unknown error"));
        return;
      }
    }
  }

  // Save composition changes
  if (compChanges.length > 0) {
    const res = await postApi(`/tilesets/${enc}/composition/save`, { changes: compChanges });
    if (res && res.ok !== false && !res.error) {
      // Apply to local data
      for (const change of compChanges) {
        const mt = state.metatiles.find(m => m.id === change.id);
        if (mt) mt.tiles = change.tiles.map(t => ({ ...t }));
      }
      savedCount += (res.data || res).saved || compChanges.length;
    } else {
      showToast("Save failed (composition): " + ((res && res.error) || "Unknown error"));
      return;
    }
  }

  // Save attribute changes
  if (attrChanges.length > 0) {
    const result = await doSave();
    if (result.ok) {
      savedCount += result.count;
    } else {
      showToast("Save failed (attributes): " + result.error);
      return;
    }
  }

  // Clear any remaining composition-only entries
  if (compChanges.length > 0 && attrChanges.length === 0) {
    // doSave wasn't called, so clear pendingChanges manually
    for (const change of compChanges) {
      const entry = state.pendingChanges.get(change.id);
      if (entry) {
        delete entry.tiles;
        if (Object.keys(entry).length === 0) {
          state.pendingChanges.delete(change.id);
        }
      }
    }
    emit(DIRTY_CHANGED);
  }

  // Update UI
  state.container?.querySelectorAll(".ts-cell.changed").forEach(c => c.classList.remove("changed"));
  _updateSaveButton();

  if (savedCount > 0) {
    showToast(`Saved ${savedCount} change${savedCount !== 1 ? "s" : ""}`);
  } else {
    showToast("Nothing to save");
  }

  // Re-render grid cells that changed
  for (const [id] of state.pendingChanges) {
    updateGridCell(id);
  }
}

// ---------------------------------------------------------------------------
// Keyboard shortcuts
// ---------------------------------------------------------------------------

let _keyHandler = null;

function _bindKeyboard() {
  _keyHandler = (e) => {
    // Ctrl+S = save
    if ((e.ctrlKey || e.metaKey) && e.key === "s") {
      e.preventDefault();
      if (state.pendingChanges.size > 0) _saveAll();
    }
    // Ctrl+Z = undo
    if ((e.ctrlKey || e.metaKey) && e.key === "z" && !e.shiftKey) {
      e.preventDefault();
      if (canUndo()) {
        const entry = undo();
        renderDetailPanel();
        if (entry && entry.type !== "pixel") updateGridCell(entry.id);
        _updateSaveButton();
      }
    }
    // Ctrl+Y or Ctrl+Shift+Z = redo
    if ((e.ctrlKey || e.metaKey) && (e.key === "y" || (e.key === "z" && e.shiftKey))) {
      e.preventDefault();
      if (canRedo()) {
        const entry = redo();
        renderDetailPanel();
        if (entry && entry.type !== "pixel") updateGridCell(entry.id);
        _updateSaveButton();
      }
    }

    // Copy/paste chord shortcuts (c+\, c+a/s/d/b, v+\, v+a/s/d/b)
    if (!e.ctrlKey && !e.metaKey && !e.altKey) {
      if (handleChordKeydown(e)) {
        renderDetailPanel();
        // Update all grid cells that might have changed
        const mt = getSelectedMetatile();
        if (mt) updateGridCell(mt.id);
      }
    }
  };
  document.addEventListener("keydown", _keyHandler);
}

function _unbindKeyboard() {
  if (_keyHandler) {
    document.removeEventListener("keydown", _keyHandler);
    _keyHandler = null;
  }
}

// ---------------------------------------------------------------------------
// Layout class management (toggle three-panel when context visible)
// ---------------------------------------------------------------------------

function _updateLayoutClass() {
  const layout = state.container?.querySelector(".ts-layout");
  const ctx = state.container?.querySelector(".ts-context");
  if (layout && ctx) {
    layout.classList.toggle("has-context", ctx.style.display !== "none");
  }
}

// ---------------------------------------------------------------------------
// Parse tileset name from hash
// ---------------------------------------------------------------------------

function _parseTilesetName() {
  const hash = window.location.hash || "";
  // Support both /tilesets/name and /tilesets?secondary=name
  let match = hash.match(/^#\/tilesets\/(.+)$/);
  if (match) return decodeURIComponent(match[1]);

  // Also support query param style
  match = hash.match(/^#\/tilesets\?secondary=(.+)$/);
  if (match) return decodeURIComponent(match[1]);

  // Legacy metatiles redirect
  match = hash.match(/^#\/metatiles\/(.+)$/);
  if (match) return decodeURIComponent(match[1]);

  return null;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function render(container) {
  _injectCSS();
  resetState();
  state.container = container;

  const tilesetName = _parseTilesetName();
  if (!tilesetName) {
    container.innerHTML = `<article>
      ${renderStudioNavbar("Assets")}
      <p style="color:var(--text-dim)">No tileset specified. <a href="#/assets">Back to Assets</a></p>
    </article>`;
    return;
  }

  container.innerHTML = `<div class="ts-loading">Loading tileset data...</div>`;

  // Set up event listeners
  _listen(METATILE_SELECTED, () => renderDetailPanel());
  _listen(DIRTY_CHANGED, () => _updateSaveButton());
  _listen(WIZARD_EXITED, () => _renderAll());
  _listen(MODE_CHANGED, () => setTimeout(_updateLayoutClass, 0));
  _listen(METATILE_MODIFIED, (detail) => {
    if (detail && detail.id != null) {
      updateGridCell(detail.id);
      _updateSaveButton();
    }
  });

  // Keyboard shortcuts and undo
  _bindKeyboard();
  initHistory();
  setBeforeChangeHook((type, id) => snapshotBeforeChange(type, id));

  try {
    await Promise.all([
      loadTilesetData(tilesetName),
      loadTilesImage(tilesetName),
    ]);

    _renderAll();
  } catch (err) {
    container.innerHTML = `<article>
      ${renderStudioNavbar("Assets")}
      <a href="#/assets" class="ts-back">&larr; Assets</a>
      <p style="color:var(--status-error, #f38ba8); margin-top: 1rem;">${esc(err.message)}</p>
    </article>`;
  }
}

export function cleanup() {
  // Remove event listeners
  for (const { event, handler } of _handlers) {
    off(event, handler);
  }
  _handlers = [];

  _unbindKeyboard();
  resetState();
  cleanupRenderer();
  cleanupBehaviorPicker();
  cleanupTilePalette();
  cleanupHistory();
  _cleanupPixelEditor();
  cleanupClipboard();

  if (_styleEl) {
    _styleEl.remove();
    _styleEl = null;
  }

  const toast = document.querySelector(".ts-toast");
  if (toast) toast.remove();
}
