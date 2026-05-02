/**
 * compose.js — Metatile composition editor for the Tileset Editor.
 * Shows an exploded 3-layer view of the selected metatile.
 * Each layer is a 2×2 grid of 48px tiles (8×8 at 6× zoom).
 * Click a slot to select it, then assign a tile from the tile palette.
 */

import { esc } from "../../utils.js";
import {
  state, emit,
  METATILE_MODIFIED, DIRTY_CHANGED, TILE_POSITIONS,
  getSelectedMetatile, getEffectiveLayerType, addChange, showToast,
} from "./state.js";
import { renderMetatileTile, renderMetatile } from "./renderer.js";
import {
  copyLayer, copyMetatile, pasteLayer, pasteMetatile,
  hasTileClip, getTileClipType,
} from "./clipboard.js";
import { snapshotBeforeChange } from "./history.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LAYER_LABELS = [
  { name: "Top Layer", sublabel: "BG1 — in front of player", idx: 2 },
  { name: "Middle Layer", sublabel: "BG2 — behind player", idx: 1 },
  { name: "Bottom Layer", sublabel: "BG3 — behind player", idx: 0 },
];

const SLOT_SIZE = 48;   // display size per tile slot
const TILE_SIZE = 8;    // native tile size
const ZOOM = SLOT_SIZE / TILE_SIZE;  // 6×

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

// Selected slot: { layer: 0-2 (bottom/middle/top), pos: 0-3 (tl/tr/bl/br) }
let _selectedSlot = null;

export function getSelectedSlot() { return _selectedSlot; }

export function clearSelectedSlot() { _selectedSlot = null; }

/** Return the global tile index of the currently selected slot, or null. */
export function getSelectedSlotTileIndex(mt) {
  if (!_selectedSlot || !mt) return null;
  const change = state.pendingChanges.get(mt.id);
  const tiles = (change && change.tiles) ? change.tiles : mt.tiles;
  if (!tiles) return null;
  const idx = _selectedSlot.layer * 4 + _selectedSlot.pos;
  const ref = tiles[idx];
  return ref ? ref.tile : null;
}

// ---------------------------------------------------------------------------
// Get working copy of metatile tiles (with pending changes applied)
// ---------------------------------------------------------------------------

function _getWorkingTiles(mt) {
  const change = state.pendingChanges.get(mt.id);
  if (change && change.tiles) {
    return change.tiles;
  }
  return mt.tiles ? [...mt.tiles] : [];
}

// ---------------------------------------------------------------------------
// Render the composition editor HTML
// ---------------------------------------------------------------------------

export function renderComposeHTML(mt) {
  if (!mt || !mt.tiles) return `<div class="ts-mode-placeholder">No metatile selected.</div>`;

  const tiles = _getWorkingTiles(mt);

  // Copy/paste metatile row
  let html = `<div class="cp-mt-actions">`;
  html += `<button class="cp-copy-mt-btn" id="cp-copy-mt" title="Copy full metatile (c+\\)">Copy Metatile</button>`;
  const canPasteMt = hasTileClip() && getTileClipType() === "metatile";
  if (canPasteMt) {
    html += `<button class="cp-paste-mt-btn" id="cp-paste-mt" title="Paste full metatile (v+\\)">Paste Metatile</button>`;
  }
  html += `</div>`;

  html += `<div class="cp-layers">`;

  for (const layer of LAYER_LABELS) {
    const startIdx = layer.idx * 4; // 0=bottom(0-3), 1=middle(4-7), 2=top(8-11)
    html += `<div class="cp-layer">`;
    html += `<div class="cp-layer-header">`;
    html += `<span class="cp-layer-name">${layer.name}</span>`;
    html += `<span class="cp-layer-sub">${layer.sublabel}</span>`;
    html += `<span class="cp-layer-actions">`;
    html += `<button class="cp-copy-layer-btn" data-layer="${layer.idx}" title="Copy this layer">Copy</button>`;
    const canPaste = hasTileClip() && getTileClipType() === "layer";
    if (canPaste) {
      html += `<button class="cp-paste-layer-btn" data-layer="${layer.idx}" title="Paste layer here">Paste</button>`;
    }
    html += `</span>`;
    html += `</div>`;
    html += `<div class="cp-layer-grid">`;

    for (let pos = 0; pos < 4; pos++) {
      const tileIdx = startIdx + pos;
      const tileRef = tiles[tileIdx];
      const isSelected = _selectedSlot
        && _selectedSlot.layer === layer.idx
        && _selectedSlot.pos === pos;
      const cls = isSelected ? " selected" : "";

      html += `<div class="cp-slot${cls}" data-layer="${layer.idx}" data-pos="${pos}">`;
      html += `<canvas class="cp-slot-canvas" width="8" height="8" data-tile-idx="${tileIdx}"></canvas>`;
      if (tileRef) {
        html += `<span class="cp-slot-info">#${tileRef.tile}</span>`;
      }
      html += `</div>`;
    }

    html += `</div>`; // cp-layer-grid
    html += `</div>`; // cp-layer
  }

  html += `</div>`; // cp-layers

  // Slot detail (shows when a slot is selected)
  if (_selectedSlot) {
    const slotTileIdx = _selectedSlot.layer * 4 + _selectedSlot.pos;
    const tileRef = tiles[slotTileIdx];
    if (tileRef) {
      const posNames = ["Top-Left", "Top-Right", "Bottom-Left", "Bottom-Right"];
      const layerName = LAYER_LABELS.find(l => l.idx === _selectedSlot.layer)?.name || "";
      html += `<div class="cp-slot-detail">`;
      html += `<div class="cp-slot-detail-label">${posNames[_selectedSlot.pos]} of ${layerName}</div>`;
      html += `<div class="cp-slot-controls">`;
      // Tile index display
      html += `<span class="cp-ctrl-label">Tile:</span>`;
      html += `<span class="cp-ctrl-value">#${tileRef.tile}</span>`;
      // Palette selector — label which belong to primary vs secondary
      html += `<span class="cp-ctrl-label">Pal:</span>`;
      html += `<select class="cp-pal-select" id="cp-pal-select">`;
      for (let p = 0; p < 13; p++) {
        const sel = p === tileRef.palette ? " selected" : "";
        const label = p < 6 ? `${p} (primary)` : `${p} (secondary)`;
        html += `<option value="${p}"${sel}>${label}</option>`;
      }
      html += `</select>`;
      // Flip toggles
      html += `<button class="cp-flip-btn${tileRef.hflip ? " active" : ""}" id="cp-hflip" title="Horizontal flip">H</button>`;
      html += `<button class="cp-flip-btn${tileRef.vflip ? " active" : ""}" id="cp-vflip" title="Vertical flip">V</button>`;
      // Clear button
      html += `<button class="cp-clear-btn" id="cp-clear" title="Clear this slot">×</button>`;
      html += `</div>`;
      html += `</div>`;
    }
  } else {
    html += `<div class="cp-slot-hint">Click a tile slot above to select it, then pick a tile from the palette.</div>`;
  }

  return html;
}

// ---------------------------------------------------------------------------
// Render tile canvases after HTML is in DOM
// ---------------------------------------------------------------------------

export function renderComposeCanvases(mt) {
  if (!mt) return;
  const tiles = _getWorkingTiles(mt);

  const canvases = document.querySelectorAll(".cp-slot-canvas");
  canvases.forEach(canvas => {
    const idx = parseInt(canvas.dataset.tileIdx, 10);
    if (isNaN(idx) || !tiles[idx]) return;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, 8, 8);
    renderMetatileTile(ctx, tiles[idx], 0, 0);
  });
}

// ---------------------------------------------------------------------------
// Bind compose events
// ---------------------------------------------------------------------------

export function bindComposeEvents(onSlotChange) {
  // Slot click
  document.querySelectorAll(".cp-slot").forEach(slot => {
    slot.addEventListener("click", () => {
      const layer = parseInt(slot.dataset.layer, 10);
      const pos = parseInt(slot.dataset.pos, 10);

      // Toggle selection
      if (_selectedSlot && _selectedSlot.layer === layer && _selectedSlot.pos === pos) {
        _selectedSlot = null;
      } else {
        _selectedSlot = { layer, pos };
      }

      if (onSlotChange) onSlotChange(_selectedSlot);
    });
  });

  // Palette selector
  const palSelect = document.getElementById("cp-pal-select");
  if (palSelect) {
    palSelect.addEventListener("change", () => {
      if (!_selectedSlot) return;
      const mt = getSelectedMetatile();
      if (!mt) return;
      const newPal = parseInt(palSelect.value, 10);
      _applySlotChange(mt, _selectedSlot, { palette: newPal });
      _refreshAfterChange(mt);
    });
  }

  // H-flip
  const hflipBtn = document.getElementById("cp-hflip");
  if (hflipBtn) {
    hflipBtn.addEventListener("click", () => {
      if (!_selectedSlot) return;
      const mt = getSelectedMetatile();
      if (!mt) return;
      const tiles = _getWorkingTiles(mt);
      const idx = _selectedSlot.layer * 4 + _selectedSlot.pos;
      _applySlotChange(mt, _selectedSlot, { hflip: !tiles[idx].hflip });
      hflipBtn.classList.toggle("active");
      _refreshAfterChange(mt);
    });
  }

  // V-flip
  const vflipBtn = document.getElementById("cp-vflip");
  if (vflipBtn) {
    vflipBtn.addEventListener("click", () => {
      if (!_selectedSlot) return;
      const mt = getSelectedMetatile();
      if (!mt) return;
      const tiles = _getWorkingTiles(mt);
      const idx = _selectedSlot.layer * 4 + _selectedSlot.pos;
      _applySlotChange(mt, _selectedSlot, { vflip: !tiles[idx].vflip });
      vflipBtn.classList.toggle("active");
      _refreshAfterChange(mt);
    });
  }

  // Clear slot
  const clearBtn = document.getElementById("cp-clear");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      if (!_selectedSlot) return;
      const mt = getSelectedMetatile();
      if (!mt) return;
      _applySlotChange(mt, _selectedSlot, { tile: 0, palette: 0, hflip: false, vflip: false });
      _refreshAfterChange(mt);
    });
  }

  // Copy/paste metatile buttons
  const copyMtBtn = document.getElementById("cp-copy-mt");
  if (copyMtBtn) {
    copyMtBtn.addEventListener("click", () => copyMetatile());
  }
  const pasteMtBtn = document.getElementById("cp-paste-mt");
  if (pasteMtBtn) {
    pasteMtBtn.addEventListener("click", () => {
      if (pasteMetatile()) {
        const mt = getSelectedMetatile();
        if (mt) _refreshAfterChange(mt);
      }
    });
  }

  // Copy/paste layer buttons
  document.querySelectorAll(".cp-copy-layer-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const layerIdx = parseInt(btn.dataset.layer, 10);
      copyLayer(layerIdx);
    });
  });
  document.querySelectorAll(".cp-paste-layer-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const layerIdx = parseInt(btn.dataset.layer, 10);
      if (pasteLayer(layerIdx)) {
        const mt = getSelectedMetatile();
        if (mt) _refreshAfterChange(mt);
      }
    });
  });
}

// ---------------------------------------------------------------------------
// In-place refresh after palette/flip/clear (no DOM rebuild)
// ---------------------------------------------------------------------------

function _refreshAfterChange(mt) {
  // Re-render compose slot canvases
  renderComposeCanvases(mt);
  // Re-render the preview canvas
  const previewCanvas = document.getElementById("ts-detail-canvas");
  if (previewCanvas) {
    const change = state.pendingChanges.get(mt.id);
    const renderMt = (change && change.tiles) ? { ...mt, tiles: change.tiles } : mt;
    const layerType = getEffectiveLayerType(mt);
    renderMetatile(previewCanvas, renderMt, layerType,
      { bottom: true, middle: true, top: true });
  }
  emit(METATILE_MODIFIED, { id: mt.id });
}

// ---------------------------------------------------------------------------
// Tile assignment (called from tilePalette when user clicks a tile)
// ---------------------------------------------------------------------------

export function assignTileToSlot(tileIndex, palette) {
  if (!_selectedSlot) return false;
  const mt = getSelectedMetatile();
  if (!mt) return false;

  _applySlotChange(mt, _selectedSlot, { tile: tileIndex, palette: palette ?? 0 });
  emit(METATILE_MODIFIED, { id: mt.id });
  return true;
}

// ---------------------------------------------------------------------------
// Internal: apply a change to a specific slot
// ---------------------------------------------------------------------------

function _applySlotChange(mt, slot, changes) {
  // Snapshot for undo before modification
  snapshotBeforeChange("composition", mt.id);

  let entry = state.pendingChanges.get(mt.id);
  if (!entry) {
    entry = {};
    state.pendingChanges.set(mt.id, entry);
  }

  // Ensure we have a working copy of tiles
  if (!entry.tiles) {
    entry.tiles = mt.tiles.map(t => ({ ...t }));
  }

  const idx = slot.layer * 4 + slot.pos;
  const ref = entry.tiles[idx];
  if (changes.tile !== undefined) ref.tile = changes.tile;
  if (changes.palette !== undefined) ref.palette = changes.palette;
  if (changes.hflip !== undefined) ref.hflip = changes.hflip;
  if (changes.vflip !== undefined) ref.vflip = changes.vflip;
}

// ---------------------------------------------------------------------------
// CSS for the composition editor
// ---------------------------------------------------------------------------

export const COMPOSE_CSS = `
/* Copy/paste metatile row */
.cp-mt-actions {
  display: flex;
  gap: 0.4rem;
  justify-content: center;
  margin-bottom: 0.5rem;
}
.cp-copy-mt-btn, .cp-paste-mt-btn {
  padding: 0.25rem 0.7rem;
  font-size: 0.72rem;
  background: var(--surface-2, #313244);
  color: var(--text-secondary, #bac2de);
  border: 1px solid var(--border-subtle, #45475a);
  border-radius: 3px;
  cursor: pointer;
  transition: background 0.1s;
}
.cp-copy-mt-btn:hover, .cp-paste-mt-btn:hover {
  background: var(--surface-3, #45475a);
}
.cp-paste-mt-btn {
  color: var(--accent, #f8d030);
  border-color: var(--accent, #f8d030);
}

/* Composition editor layers */
.cp-layers {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.cp-layer {
  background: var(--surface-1, #1e1e2e);
  border: 1px solid var(--border-subtle, #45475a);
  border-radius: 6px;
  padding: 0.5rem;
}
.cp-layer-header {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  margin-bottom: 0.4rem;
}
.cp-layer-name {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--text-primary, #cdd6f4);
}
.cp-layer-sub {
  font-size: 0.65rem;
  color: var(--text-dim, #585b70);
}
.cp-layer-actions {
  margin-left: auto;
  display: flex;
  gap: 0.25rem;
}
.cp-copy-layer-btn, .cp-paste-layer-btn {
  padding: 0.1rem 0.4rem;
  font-size: 0.62rem;
  background: transparent;
  color: var(--text-dim, #585b70);
  border: 1px solid var(--border-subtle, #45475a);
  border-radius: 2px;
  cursor: pointer;
  transition: color 0.1s, border-color 0.1s;
}
.cp-copy-layer-btn:hover { color: var(--text-secondary, #bac2de); border-color: var(--text-secondary, #bac2de); }
.cp-paste-layer-btn { color: var(--accent, #f8d030); border-color: var(--accent, #f8d030); opacity: 0.7; }
.cp-paste-layer-btn:hover { opacity: 1; }
.cp-layer-grid {
  display: grid;
  grid-template-columns: repeat(2, ${SLOT_SIZE}px);
  gap: 2px;
  justify-content: center;
}
.cp-slot {
  position: relative;
  width: ${SLOT_SIZE}px;
  height: ${SLOT_SIZE}px;
  background: #000;
  border: 2px solid var(--border-subtle, #45475a);
  border-radius: 3px;
  cursor: pointer;
  transition: border-color 0.15s;
  display: flex;
  align-items: center;
  justify-content: center;
}
.cp-slot:hover {
  border-color: var(--text-secondary, #bac2de);
}
.cp-slot.selected {
  border-color: var(--accent, #f8d030);
  box-shadow: 0 0 0 2px var(--accent, #f8d030), 0 0 8px rgba(248, 208, 48, 0.4);
  z-index: 1;
}
.cp-slot-canvas {
  width: ${SLOT_SIZE}px;
  height: ${SLOT_SIZE}px;
  image-rendering: pixelated;
  display: block;
}
.cp-slot-info {
  position: absolute;
  bottom: 1px;
  right: 2px;
  font-size: 7px;
  color: rgba(255,255,255,0.35);
  pointer-events: none;
  font-family: monospace;
}

/* Slot detail controls */
.cp-slot-detail {
  margin-top: 0.75rem;
  padding: 0.6rem;
  background: var(--surface-1, #1e1e2e);
  border: 1px solid var(--border-subtle, #45475a);
  border-radius: 6px;
}
.cp-slot-detail-label {
  font-size: 0.72rem;
  color: var(--text-dim, #585b70);
  margin-bottom: 0.4rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-weight: 600;
}
.cp-slot-controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.cp-ctrl-label {
  font-size: 0.75rem;
  color: var(--text-dim, #585b70);
}
.cp-ctrl-value {
  font-size: 0.8rem;
  font-family: monospace;
  color: var(--text-primary, #cdd6f4);
}
.cp-pal-select {
  padding: 0.2rem 0.3rem;
  font-size: 0.75rem;
  background: var(--surface-0, #11111b);
  color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border-subtle, #45475a);
  border-radius: 3px;
  width: 3rem;
}
.cp-flip-btn {
  padding: 0.2rem 0.5rem;
  font-size: 0.72rem;
  font-weight: 700;
  font-family: monospace;
  background: var(--surface-2, #313244);
  color: var(--text-dim, #585b70);
  border: 1px solid var(--border-subtle, #45475a);
  border-radius: 3px;
  cursor: pointer;
  transition: background 0.1s, color 0.1s;
}
.cp-flip-btn:hover {
  background: var(--surface-3, #45475a);
  color: var(--text-primary, #cdd6f4);
}
.cp-flip-btn.active {
  background: var(--accent, #f8d030);
  color: #000;
  border-color: var(--accent, #f8d030);
}
.cp-clear-btn {
  padding: 0.2rem 0.5rem;
  font-size: 0.8rem;
  background: transparent;
  color: var(--text-dim, #585b70);
  border: 1px solid var(--border-subtle, #45475a);
  border-radius: 3px;
  cursor: pointer;
  margin-left: auto;
}
.cp-clear-btn:hover {
  color: var(--status-error, #f38ba8);
  border-color: var(--status-error, #f38ba8);
}

/* Hint text */
.cp-slot-hint {
  margin-top: 0.75rem;
  font-size: 0.78rem;
  color: var(--text-dim, #585b70);
  text-align: center;
  font-style: italic;
}
`;
