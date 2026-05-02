/**
 * detail.js — Metatile detail panel for the Tileset Editor (center panel).
 * Shows the selected metatile preview and mode tabs.
 * Compose mode shows an exploded layer view and renders the tile palette
 * into the context panel on the right.
 */

import { esc } from "../../utils.js";
import {
  state, emit, on,
  METATILE_SELECTED, MODE_CHANGED, DIRTY_CHANGED, DETAIL_NEEDS_UPDATE,
  METATILE_MODIFIED,
  LAYER_NAMES, LAYER_COLORS,
  getEffectiveLayerType, getEffectiveBehavior, getSelectedMetatile,
  defaultToggles, addChange,
} from "./state.js";
import { renderMetatile, renderMetatileTile } from "./renderer.js";
import { updateGridCell } from "./grid.js";
import { renderBehaviorPickerHTML, bindBehaviorPicker } from "./behaviorPicker.js";
import {
  renderComposeHTML, renderComposeCanvases, bindComposeEvents,
  assignTileToSlot, clearSelectedSlot, getSelectedSlotTileIndex, COMPOSE_CSS,
} from "./compose.js";
import {
  renderTilePaletteHTML, renderTilePaletteCanvases, bindTilePaletteEvents,
  selectTileInPalette, cleanupTilePalette, TILE_PALETTE_CSS,
} from "./tilePalette.js";
import {
  renderPixelEditorHTML, renderPixelCanvas, bindPixelEditorEvents,
  getPixelEditState, cleanupPixelEditor, PIXEL_EDITOR_CSS,
} from "./pixelEditor.js";

// ---------------------------------------------------------------------------
// Mode tabs
// ---------------------------------------------------------------------------

const MODES = [
  { id: "layers", label: "Layers" },
  { id: "behavior", label: "Behavior" },
  { id: "compose", label: "Compose" },
  { id: "pixel", label: "Pixel" },
];

// ---------------------------------------------------------------------------
// Exported CSS (collected from sub-modules for tilesets.js to inject)
// ---------------------------------------------------------------------------

export const DETAIL_EXTRA_CSS = COMPOSE_CSS + TILE_PALETTE_CSS + PIXEL_EDITOR_CSS;

// ---------------------------------------------------------------------------
// Render detail panel
// ---------------------------------------------------------------------------

export function renderDetailPanel() {
  if (!state.container) return;
  const panel = state.container.querySelector(".ts-detail");
  if (!panel) return;

  const mt = getSelectedMetatile();
  if (!mt) {
    panel.innerHTML = `<div class="ts-detail-empty">Select a metatile from the grid to edit.</div>`;
    _hideContextPanel();
    return;
  }

  const layerType = getEffectiveLayerType(mt);
  const behaviorVal = getEffectiveBehavior(mt);

  let html = "";

  // Preview canvas (smaller when in compose mode to save space)
  const previewSize = state.activeMode === "compose" ? 64 : 128;
  html += `<div class="ts-detail-preview" style="margin-bottom:0.5rem">`;
  html += `<canvas id="ts-detail-canvas" width="16" height="16" style="width:${previewSize}px;height:${previewSize}px"></canvas>`;
  html += `</div>`;
  html += `<div class="ts-detail-id">Metatile #${mt.id} (0x${mt.id.toString(16).toUpperCase().padStart(3, "0")})`;
  if (state.pendingChanges.has(mt.id)) {
    html += ` <button class="ts-clear-edits" id="ts-clear-edits" title="Discard all edits for this metatile">Clear edits</button>`;
  }
  html += `</div>`;

  // Mode tabs
  html += `<div class="ts-mode-tabs">`;
  for (const mode of MODES) {
    const active = mode.id === state.activeMode ? " active" : "";
    const disabled = "";
    html += `<button class="ts-mode-tab${active}${disabled}" data-mode="${mode.id}"${disabled ? " disabled" : ""}>${mode.label}</button>`;
  }
  html += `</div>`;

  // Mode-specific content
  if (state.activeMode === "layers") {
    html += _renderLayersMode(mt, layerType);
  } else if (state.activeMode === "behavior") {
    html += _renderBehaviorMode(mt, behaviorVal);
  } else if (state.activeMode === "compose") {
    html += renderComposeHTML(mt);
  } else if (state.activeMode === "pixel") {
    html += _renderPixelMode(mt);
  }

  panel.innerHTML = html;

  // Render the detail preview canvas (all layers, using working tiles if modified)
  const previewCanvas = document.getElementById("ts-detail-canvas");
  if (previewCanvas && state.tilesImg) {
    const change = state.pendingChanges.get(mt.id);
    if (change && change.tiles) {
      // Render with modified tiles
      const fakeMt = { ...mt, tiles: change.tiles };
      renderMetatile(previewCanvas, fakeMt, layerType,
        state.activeMode === "compose" ? { bottom: true, middle: true, top: true } : state.layerOverrides);
    } else {
      renderMetatile(previewCanvas, mt, layerType,
        state.activeMode === "compose" ? { bottom: true, middle: true, top: true } : state.layerOverrides);
    }
  }

  // Bind events
  _bindDetailEvents();

  // Compose mode: render canvases and show tile palette
  if (state.activeMode === "compose") {
    renderComposeCanvases(mt);
    _showContextPanel();
  } else if (state.activeMode === "pixel") {
    if (_pixelTileIndex != null) {
      renderPixelCanvas();
    } else {
      // Render tile picker canvases
      _renderPixelPickerCanvases(mt);
    }
    _hideContextPanel();
  } else {
    _hideContextPanel();
  }
}

// ---------------------------------------------------------------------------
// Context panel (tile palette) — shown in compose mode
// ---------------------------------------------------------------------------

let _contextVisible = false;

function _showContextPanel() {
  const ctx = state.container?.querySelector(".ts-context");
  if (!ctx) return;

  // Only rebuild the palette if it's not already showing
  if (!_contextVisible) {
    ctx.style.display = "block";
    ctx.innerHTML = renderTilePaletteHTML();
    renderTilePaletteCanvases();
    bindTilePaletteEvents((tileIndex, palette) => {
      const assigned = assignTileToSlot(tileIndex, palette);
      if (assigned) {
        // Re-render compose view and preview only (NOT the palette)
        _rerenderComposeOnly();
        const mt = getSelectedMetatile();
        if (mt) updateGridCell(mt.id);
      }
    });
    _contextVisible = true;
  }
}

function _hideContextPanel() {
  const ctx = state.container?.querySelector(".ts-context");
  if (ctx) {
    ctx.style.display = "none";
    ctx.innerHTML = "";
  }
  _contextVisible = false;
}

/**
 * Re-render only the compose view and preview canvas in the detail panel,
 * without touching the tile palette (preserves scroll position).
 */
function _rerenderComposeOnly() {
  renderDetailPanel();
}

// ---------------------------------------------------------------------------
// Layers mode
// ---------------------------------------------------------------------------

function _renderLayersMode(mt, layerType) {
  const tiles = mt.tiles || [];
  const hasTopContent = tiles.length >= 12 && tiles.slice(8, 12).some(t => t.tile !== 0 || t.palette !== 0);
  const toggles = state.layerOverrides || defaultToggles(layerType);

  let html = "";

  // Player depth
  html += `<div class="ts-section">`;
  html += `<div class="ts-section-label">Player Depth</div>`;
  if (hasTopContent) {
    html += `<div class="ts-depth-status ts-depth-overlap">Part of this tile renders in front of the player</div>`;
    html += `<button class="ts-depth-btn" data-action="top_to_middle">Move behind player</button>`;
  } else {
    html += `<div class="ts-depth-status ts-depth-behind">Player walks on top of this tile</div>`;
    const hasMiddleContent = tiles.length >= 8 && tiles.slice(4, 8).some(t => t.tile !== 0 || t.palette !== 0);
    if (hasMiddleContent) {
      html += `<button class="ts-depth-btn" data-action="middle_to_top">Move in front of player</button>`;
    }
  }
  html += `</div>`;

  // Layer visibility toggles
  html += `<div class="ts-section">`;
  html += `<div class="ts-section-label">Layer Visibility</div>`;
  html += `<div class="ts-toggle-group">`;
  html += `<label class="ts-toggle-label"><input type="checkbox" id="ts-toggle-bottom"${toggles.bottom ? " checked" : ""}> Bottom</label>`;
  html += `<label class="ts-toggle-label"><input type="checkbox" id="ts-toggle-middle"${toggles.middle ? " checked" : ""}> Middle</label>`;
  html += `<label class="ts-toggle-label"><input type="checkbox" id="ts-toggle-top"${toggles.top ? " checked" : ""}> Top</label>`;
  html += `</div></div>`;

  return html;
}

// ---------------------------------------------------------------------------
// Behavior mode
// ---------------------------------------------------------------------------

function _renderBehaviorMode(mt, behaviorVal) {
  return renderBehaviorPickerHTML(behaviorVal);
}

// ---------------------------------------------------------------------------
// Pixel mode
// ---------------------------------------------------------------------------

/** Track which tile the pixel editor is working on. */
let _pixelTileIndex = null;
let _pixelPalette = 0;
let _pixelIsPrimary = false;
let _pixelLastMetatileId = null;

function _renderPixelMode(mt) {
  const change = state.pendingChanges.get(mt.id);
  const tiles = (change && change.tiles) ? change.tiles : mt.tiles;

  // Reset pixel selection when switching to a different metatile
  if (_pixelLastMetatileId !== mt.id) {
    _pixelTileIndex = null;
    _pixelLastMetatileId = mt.id;
  }

  // If no tile pre-selected, show a slot picker from this metatile
  if (_pixelTileIndex == null) {
    return _renderPixelTilePicker(mt, tiles);
  }

  return renderPixelEditorHTML(_pixelTileIndex, _pixelPalette, _pixelIsPrimary);
}

/** Render a tile-slot picker so the user can click which tile to edit. */
function _renderPixelTilePicker(mt, tiles) {
  if (!tiles || tiles.length === 0) {
    return `<div class="px-empty">This metatile has no tiles.</div>`;
  }

  const LAYER_INFO = [
    { name: "Top", start: 8 },
    { name: "Middle", start: 4 },
    { name: "Bottom", start: 0 },
  ];

  let html = `<div class="px-picker">`;
  html += `<div class="px-picker-label">Click a tile to edit its pixels:</div>`;

  for (const layer of LAYER_INFO) {
    html += `<div class="px-picker-layer">`;
    html += `<span class="px-picker-layer-name">${layer.name}</span>`;
    html += `<div class="px-picker-row">`;
    for (let pos = 0; pos < 4; pos++) {
      const idx = layer.start + pos;
      const ref = tiles[idx];
      if (!ref) continue;
      const isEmpty = ref.tile === 0 && ref.palette === 0;
      const cls = isEmpty ? " empty" : "";
      html += `<div class="px-picker-slot${cls}" data-tile="${ref.tile}" data-pal="${ref.palette}" data-idx="${idx}">`;
      html += `<canvas class="px-picker-canvas" width="8" height="8" data-tile-idx="${idx}"></canvas>`;
      html += `</div>`;
    }
    html += `</div></div>`;
  }

  html += `</div>`;
  return html;
}

/** Set which tile the pixel editor should edit (called from compose slot). */
export function setPixelTile(tileIndex, palette) {
  if (tileIndex == null) {
    _pixelTileIndex = null;
    return;
  }
  _pixelTileIndex = tileIndex;
  _pixelPalette = palette || 0;
  _pixelIsPrimary = state.primaryTileOffset > 0 && tileIndex < state.primaryTileOffset;
}

export function clearPixelTile() {
  _pixelTileIndex = null;
}

// ---------------------------------------------------------------------------
// Event binding
// ---------------------------------------------------------------------------

function _bindDetailEvents() {
  if (!state.container) return;

  // Clear edits button
  const clearEditsBtn = document.getElementById("ts-clear-edits");
  if (clearEditsBtn) {
    clearEditsBtn.addEventListener("click", () => {
      const mt = getSelectedMetatile();
      if (!mt) return;
      state.pendingChanges.delete(mt.id);
      emit(DIRTY_CHANGED);
      updateGridCell(mt.id);
      renderDetailPanel();
    });
  }

  // Mode tabs
  state.container.querySelectorAll(".ts-mode-tab:not([disabled])").forEach(tab => {
    tab.addEventListener("click", () => {
      const newMode = tab.dataset.mode;
      if (newMode !== state.activeMode) {
        // Clear compose slot selection when leaving compose mode
        if (state.activeMode === "compose") clearSelectedSlot();
        state.activeMode = newMode;
        emit(MODE_CHANGED, { mode: newMode });
        renderDetailPanel();
      }
    });
  });

  // Depth action buttons
  state.container.querySelectorAll(".ts-depth-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const mt = getSelectedMetatile();
      if (!mt) return;
      addChange(mt.id, "layer_action", btn.dataset.action);
      updateGridCell(mt.id);
      renderDetailPanel();
    });
  });

  // Layer visibility toggles
  const toggleIds = ["ts-toggle-bottom", "ts-toggle-middle", "ts-toggle-top"];
  toggleIds.forEach(id => {
    const cb = document.getElementById(id);
    if (!cb) return;
    cb.addEventListener("change", () => {
      const mt = getSelectedMetatile();
      if (!mt) return;

      const overrides = {
        bottom: document.getElementById("ts-toggle-bottom")?.checked ?? false,
        middle: document.getElementById("ts-toggle-middle")?.checked ?? false,
        top: document.getElementById("ts-toggle-top")?.checked ?? false,
      };
      state.layerOverrides = overrides;

      const layerType = getEffectiveLayerType(mt);
      const previewCanvas = document.getElementById("ts-detail-canvas");
      if (previewCanvas && state.tilesImg) {
        renderMetatile(previewCanvas, mt, layerType, overrides);
      }
    });
  });

  // Behavior picker
  bindBehaviorPicker((value) => {
    const mt = getSelectedMetatile();
    if (mt) {
      addChange(mt.id, "behavior", value);
      updateGridCell(mt.id);
    }
  });

  // Compose mode events
  if (state.activeMode === "compose") {
    bindComposeEvents((slot) => {
      // Slot selection changed — re-render to show slot detail controls
      renderDetailPanel();
      // Sync tile palette: highlight + scroll to the tile in the selected slot
      const mt = getSelectedMetatile();
      const tileIdx = getSelectedSlotTileIndex(mt);
      if (tileIdx != null) {
        setTimeout(() => selectTileInPalette(tileIdx), 0);
        // Also set the pixel editor target for when user switches to Pixel tab
        const change = state.pendingChanges.get(mt.id);
        const tiles = (change && change.tiles) ? change.tiles : mt.tiles;
        if (slot && tiles) {
          const ref = tiles[slot.layer * 4 + slot.pos];
          if (ref) setPixelTile(ref.tile, ref.palette);
        }
      }
    });
  }

  // Pixel mode events
  if (state.activeMode === "pixel") {
    if (_pixelTileIndex != null) {
      bindPixelEditorEvents(
        // onTileModified
        (tileIndex) => {
          emit(TILE_MODIFIED, { tileIndex });
          emit(DIRTY_CHANGED);
          // Update grid cells that reference this tile
          for (const mt of state.metatiles) {
            if (mt.tiles && mt.tiles.some(t => t.tile === tileIndex)) {
              updateGridCell(mt.id);
            }
          }
          // Update the metatile preview canvas
          _updatePreviewFromPixelEdit();
        },
        // onDuplicate — TODO: implement via API
        null,
      );
    } else {
      // Bind pixel picker slot clicks
      _bindPixelPickerEvents();
    }
  }
}

// ---------------------------------------------------------------------------
// Pixel picker helpers (tile-slot grid when no tile pre-selected)
// ---------------------------------------------------------------------------

function _renderPixelPickerCanvases(mt) {
  if (!mt) return;
  const change = state.pendingChanges.get(mt.id);
  const tiles = (change && change.tiles) ? change.tiles : mt.tiles;
  if (!tiles) return;

  document.querySelectorAll(".px-picker-canvas").forEach(canvas => {
    const idx = parseInt(canvas.dataset.tileIdx, 10);
    if (isNaN(idx) || !tiles[idx]) return;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, 8, 8);
    renderMetatileTile(ctx, tiles[idx], 0, 0);
  });
}

function _bindPixelPickerEvents() {
  document.querySelectorAll(".px-picker-slot:not(.empty)").forEach(slot => {
    slot.addEventListener("click", () => {
      const tileIdx = parseInt(slot.dataset.tile, 10);
      const palIdx = parseInt(slot.dataset.pal, 10);
      if (isNaN(tileIdx)) return;
      setPixelTile(tileIdx, palIdx);
      renderDetailPanel();
    });
  });
}

/** Update the metatile preview canvas after pixel editing. */
function _updatePreviewFromPixelEdit() {
  const mt = getSelectedMetatile();
  if (!mt) return;
  const previewCanvas = document.getElementById("ts-detail-canvas");
  if (!previewCanvas) return;
  const layerType = getEffectiveLayerType(mt);
  const change = state.pendingChanges.get(mt.id);
  const renderMt = (change && change.tiles) ? { ...mt, tiles: change.tiles } : mt;
  renderMetatile(previewCanvas, renderMt, layerType, { bottom: true, middle: true, top: true });
}
