/**
 * pixelEditor.js — 8×8 tile pixel editor for the Tileset Editor.
 *
 * Shows a single 8×8 tile at 24× zoom (192×192 canvas) with grid lines.
 * Tools: pencil (click/drag), fill (flood fill), color picker.
 * 16-color palette strip from the tile's assigned palette.
 * Tile usage display and duplicate button.
 */

import {
  state, emit,
  TILE_MODIFIED, DIRTY_CHANGED,
  getSelectedMetatile,
} from "./state.js";
import { snapshotBeforeChange } from "./history.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ZOOM = 24;
const CANVAS_SIZE = 8 * ZOOM; // 192
const TOOLS = ["pencil", "fill", "picker"];

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _activeTool = "pencil";
let _activeColor = 1;
let _tileIndex = null;     // global tile index being edited
let _palIndex = 0;         // palette used by this tile
let _isPrimary = false;    // whether tile belongs to primary tileset
let _localIdx = 0;         // index within the tileset's pixel data
let _painting = false;     // mouse held down for pencil drag

// ---------------------------------------------------------------------------
// Get/set pixel data for the tile being edited
// ---------------------------------------------------------------------------

function _getPixelArray() {
  return _isPrimary ? state.primaryPixels : state.tilePixels;
}

function _getSheetW() {
  return _isPrimary ? state.primarySheetW : state.tileSheetW;
}

function _getPalettes() {
  return _isPrimary ? state.primaryPalettes : state.palettes;
}

function _getPixel(px, py) {
  const pixels = _getPixelArray();
  const sheetW = _getSheetW();
  if (!pixels || !sheetW) return 0;

  const tilesPerRow = sheetW / 8;
  const tileCol = _localIdx % tilesPerRow;
  const tileRow = Math.floor(_localIdx / tilesPerRow);
  const srcX = tileCol * 8 + px;
  const srcY = tileRow * 8 + py;
  return pixels[srcY * sheetW + srcX] || 0;
}

function _setPixel(px, py, colorIdx) {
  const pixels = _getPixelArray();
  const sheetW = _getSheetW();
  if (!pixels || !sheetW) return;

  const tilesPerRow = sheetW / 8;
  const tileCol = _localIdx % tilesPerRow;
  const tileRow = Math.floor(_localIdx / tilesPerRow);
  const srcX = tileCol * 8 + px;
  const srcY = tileRow * 8 + py;
  const idx = srcY * sheetW + srcX;

  if (pixels[idx] !== colorIdx) {
    pixels[idx] = colorIdx;
    // Track that this tile has been modified
    if (!state.tilePixelChanges) state.tilePixelChanges = new Map();
    state.tilePixelChanges.set(_tileIndex, true);
  }
}

// ---------------------------------------------------------------------------
// Tile usage: which metatiles reference this tile?
// ---------------------------------------------------------------------------

function _findTileUsage(globalTileIdx) {
  const usages = [];
  for (const mt of state.metatiles) {
    const tiles = mt.tiles || [];
    for (let i = 0; i < tiles.length; i++) {
      if (tiles[i].tile === globalTileIdx) {
        usages.push(mt.id);
        break;
      }
    }
  }
  return usages;
}

// ---------------------------------------------------------------------------
// Render pixel editor HTML (for the detail panel center area)
// ---------------------------------------------------------------------------

export function renderPixelEditorHTML(tileIndex, palette, isPrimary) {
  if (tileIndex == null) {
    return `<div class="px-empty">Select a tile slot in Compose mode, then switch to Pixel to edit it.</div>`;
  }

  _tileIndex = tileIndex;
  _palIndex = palette;
  _isPrimary = isPrimary;
  _localIdx = isPrimary ? tileIndex : (tileIndex - state.primaryTileOffset);

  const usages = _findTileUsage(tileIndex);

  let html = `<div class="px-editor">`;

  // Canvas
  html += `<div class="px-canvas-wrap">`;
  html += `<canvas class="px-canvas" id="px-canvas" width="${CANVAS_SIZE}" height="${CANVAS_SIZE}"></canvas>`;
  html += `</div>`;

  // Tile info
  html += `<div class="px-info">`;
  html += `<span class="px-info-label">Tile #${tileIndex}</span>`;
  html += `<span class="px-info-usage">Used by ${usages.length} metatile${usages.length !== 1 ? "s" : ""}</span>`;
  if (usages.length > 1) {
    html += `<div class="px-usage-warn">Editing this tile affects all metatiles that use it.</div>`;
  }
  html += `</div>`;

  // Palette strip
  const pals = _getPalettes();
  const pal = pals[_palIndex] || [];
  html += `<div class="px-palette">`;
  html += `<div class="px-palette-label">Palette ${_palIndex}</div>`;
  html += `<div class="px-palette-strip">`;
  for (let c = 0; c < 16; c++) {
    const color = pal[c] || [0, 0, 0];
    const rgb = `rgb(${color[0]},${color[1]},${color[2]})`;
    const active = c === _activeColor ? " active" : "";
    const border = c === 0 ? "border:1px dashed rgba(255,255,255,0.3);" : "";
    html += `<button class="px-color${active}" data-color="${c}" style="background:${rgb};${border}" title="${c === 0 ? "Transparent" : `Color ${c}`}"></button>`;
  }
  html += `</div>`;
  html += `<div class="px-color-info">Active: ${_activeColor === 0 ? "Transparent" : `Color ${_activeColor}`}</div>`;
  html += `</div>`;

  // Tools
  html += `<div class="px-tools">`;
  for (const tool of TOOLS) {
    const active = tool === _activeTool ? " active" : "";
    const icons = { pencil: "Pencil", fill: "Fill", picker: "Picker" };
    html += `<button class="px-tool-btn${active}" data-tool="${tool}">${icons[tool]}</button>`;
  }
  html += `</div>`;

  // Duplicate button
  html += `<div class="px-actions">`;
  html += `<button class="px-duplicate-btn" id="px-duplicate">Duplicate Tile (edit copy only)</button>`;
  html += `</div>`;

  html += `</div>`;
  return html;
}

// ---------------------------------------------------------------------------
// Render the pixel canvas
// ---------------------------------------------------------------------------

export function renderPixelCanvas() {
  const canvas = document.getElementById("px-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);

  const pals = _getPalettes();
  const pal = pals[_palIndex] || [];

  // Draw pixels
  for (let py = 0; py < 8; py++) {
    for (let px = 0; px < 8; px++) {
      const palIdx = _getPixel(px, py);
      if (palIdx === 0) {
        // Transparent — checkerboard pattern
        const dx = px * ZOOM, dy = py * ZOOM;
        const half = ZOOM / 2;
        ctx.fillStyle = "#1a1a2e";
        ctx.fillRect(dx, dy, ZOOM, ZOOM);
        ctx.fillStyle = "#2a2a3e";
        ctx.fillRect(dx, dy, half, half);
        ctx.fillRect(dx + half, dy + half, half, half);
      } else {
        const color = pal[palIdx] || [0, 0, 0];
        ctx.fillStyle = `rgb(${color[0]},${color[1]},${color[2]})`;
        ctx.fillRect(px * ZOOM, py * ZOOM, ZOOM, ZOOM);
      }
    }
  }

  // Grid lines
  ctx.strokeStyle = "rgba(255, 255, 255, 0.12)";
  ctx.lineWidth = 1;
  for (let i = 1; i < 8; i++) {
    const p = i * ZOOM + 0.5;
    ctx.beginPath();
    ctx.moveTo(p, 0);
    ctx.lineTo(p, CANVAS_SIZE);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, p);
    ctx.lineTo(CANVAS_SIZE, p);
    ctx.stroke();
  }
}

// ---------------------------------------------------------------------------
// Bind pixel editor events
// ---------------------------------------------------------------------------

export function bindPixelEditorEvents(onTileModified, onDuplicate) {
  const canvas = document.getElementById("px-canvas");
  if (!canvas) return;

  function _canvasToPixel(e) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = CANVAS_SIZE / rect.width;
    const scaleY = CANVAS_SIZE / rect.height;
    const cx = (e.clientX - rect.left) * scaleX;
    const cy = (e.clientY - rect.top) * scaleY;
    const px = Math.floor(cx / ZOOM);
    const py = Math.floor(cy / ZOOM);
    if (px < 0 || px >= 8 || py < 0 || py >= 8) return null;
    return { px, py };
  }

  function _applyTool(px, py) {
    if (_activeTool === "pencil") {
      _setPixel(px, py, _activeColor);
      renderPixelCanvas();
      if (onTileModified) onTileModified(_tileIndex);
    } else if (_activeTool === "fill") {
      _floodFill(px, py, _activeColor);
      renderPixelCanvas();
      if (onTileModified) onTileModified(_tileIndex);
    } else if (_activeTool === "picker") {
      _activeColor = _getPixel(px, py);
      // Update palette strip active state
      document.querySelectorAll(".px-color").forEach(btn => {
        btn.classList.toggle("active", parseInt(btn.dataset.color, 10) === _activeColor);
      });
      const info = document.querySelector(".px-color-info");
      if (info) info.textContent = `Active: ${_activeColor === 0 ? "Transparent" : `Color ${_activeColor}`}`;
    }
  }

  canvas.addEventListener("mousedown", (e) => {
    const p = _canvasToPixel(e);
    if (!p) return;
    // Snapshot once at start of stroke for undo
    if (_tileIndex != null && (_activeTool === "pencil" || _activeTool === "fill")) {
      snapshotBeforeChange("pixel", _tileIndex);
    }
    _painting = true;
    _applyTool(p.px, p.py);
  });

  canvas.addEventListener("mousemove", (e) => {
    if (!_painting || _activeTool !== "pencil") return;
    const p = _canvasToPixel(e);
    if (!p) return;
    _applyTool(p.px, p.py);
  });

  canvas.addEventListener("mouseup", () => { _painting = false; });
  canvas.addEventListener("mouseleave", () => { _painting = false; });

  // Prevent context menu on right-click
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());

  // Palette color clicks
  document.querySelectorAll(".px-color").forEach(btn => {
    btn.addEventListener("click", () => {
      _activeColor = parseInt(btn.dataset.color, 10);
      document.querySelectorAll(".px-color").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const info = document.querySelector(".px-color-info");
      if (info) info.textContent = `Active: ${_activeColor === 0 ? "Transparent" : `Color ${_activeColor}`}`;
    });
  });

  // Tool buttons
  document.querySelectorAll(".px-tool-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      _activeTool = btn.dataset.tool;
      document.querySelectorAll(".px-tool-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      // Change cursor
      canvas.style.cursor = _activeTool === "picker" ? "crosshair" : "default";
    });
  });

  // Duplicate button
  const dupBtn = document.getElementById("px-duplicate");
  if (dupBtn) {
    dupBtn.addEventListener("click", () => {
      if (onDuplicate) onDuplicate(_tileIndex);
    });
  }
}

// ---------------------------------------------------------------------------
// Flood fill
// ---------------------------------------------------------------------------

function _floodFill(startX, startY, newColor) {
  const targetColor = _getPixel(startX, startY);
  if (targetColor === newColor) return;

  const stack = [[startX, startY]];
  const visited = new Set();

  while (stack.length > 0) {
    const [x, y] = stack.pop();
    const key = y * 8 + x;
    if (visited.has(key)) continue;
    if (x < 0 || x >= 8 || y < 0 || y >= 8) continue;
    if (_getPixel(x, y) !== targetColor) continue;

    visited.add(key);
    _setPixel(x, y, newColor);

    stack.push([x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]);
  }
}

// ---------------------------------------------------------------------------
// Get current editing state (for external access)
// ---------------------------------------------------------------------------

export function getPixelEditState() {
  return {
    tileIndex: _tileIndex,
    palIndex: _palIndex,
    isPrimary: _isPrimary,
    localIdx: _localIdx,
  };
}

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------

export function cleanupPixelEditor() {
  _tileIndex = null;
  _painting = false;
  _activeColor = 1;
  _activeTool = "pencil";
}

// ---------------------------------------------------------------------------
// CSS
// ---------------------------------------------------------------------------

export const PIXEL_EDITOR_CSS = `
/* Pixel editor container */
.px-editor {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  align-items: center;
}
.px-empty {
  color: var(--text-dim, #585b70);
  font-size: 0.82rem;
  text-align: center;
  padding: 2rem 0;
  font-style: italic;
}

/* Pixel tile picker (shown when no tile pre-selected) */
.px-picker {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.px-picker-label {
  font-size: 0.78rem;
  color: var(--text-secondary, #bac2de);
  text-align: center;
  margin-bottom: 0.25rem;
}
.px-picker-layer {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.px-picker-layer-name {
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--text-dim, #585b70);
  width: 3.5rem;
  text-align: right;
  flex-shrink: 0;
}
.px-picker-row {
  display: flex;
  gap: 3px;
}
.px-picker-slot {
  width: 48px;
  height: 48px;
  background: #000;
  border: 2px solid var(--border-subtle, #45475a);
  border-radius: 3px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.15s;
}
.px-picker-slot:hover:not(.empty) {
  border-color: var(--accent, #f8d030);
  box-shadow: 0 0 0 1px var(--accent, #f8d030);
}
.px-picker-slot.empty {
  opacity: 0.25;
  cursor: not-allowed;
}
.px-picker-canvas {
  width: 48px;
  height: 48px;
  image-rendering: pixelated;
  display: block;
}

/* Canvas */
.px-canvas-wrap {
  display: flex;
  justify-content: center;
}
.px-canvas {
  width: 192px;
  height: 192px;
  image-rendering: pixelated;
  border: 2px solid var(--border-subtle, #45475a);
  border-radius: 4px;
  cursor: default;
}

/* Tile info */
.px-info {
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.px-info-label {
  font-size: 0.8rem;
  font-family: monospace;
  color: var(--text-primary, #cdd6f4);
}
.px-info-usage {
  font-size: 0.72rem;
  color: var(--text-dim, #585b70);
}
.px-usage-warn {
  font-size: 0.72rem;
  color: #f8d030;
  background: rgba(248, 208, 48, 0.08);
  border: 1px solid rgba(248, 208, 48, 0.2);
  border-radius: 4px;
  padding: 0.25rem 0.5rem;
  margin-top: 0.2rem;
}

/* Palette strip */
.px-palette {
  width: 100%;
}
.px-palette-label {
  font-size: 0.65rem;
  font-weight: 600;
  color: var(--text-dim, #585b70);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.3rem;
}
.px-palette-strip {
  display: flex;
  gap: 2px;
  flex-wrap: wrap;
  justify-content: center;
}
.px-color {
  width: 20px;
  height: 20px;
  border: 2px solid transparent;
  border-radius: 2px;
  cursor: pointer;
  padding: 0;
  transition: border-color 0.1s, transform 0.1s;
}
.px-color:hover {
  border-color: var(--text-secondary, #bac2de);
  transform: scale(1.15);
}
.px-color.active {
  border-color: var(--accent, #f8d030);
  box-shadow: 0 0 0 1px var(--accent, #f8d030), 0 0 6px rgba(248, 208, 48, 0.4);
  transform: scale(1.15);
}
.px-color-info {
  font-size: 0.7rem;
  color: var(--text-dim, #585b70);
  text-align: center;
  margin-top: 0.2rem;
}

/* Tools */
.px-tools {
  display: flex;
  gap: 0.3rem;
  justify-content: center;
}
.px-tool-btn {
  padding: 0.3rem 0.8rem;
  font-size: 0.75rem;
  background: var(--surface-2, #313244);
  color: var(--text-dim, #585b70);
  border: 1px solid var(--border-subtle, #45475a);
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.1s, color 0.1s;
}
.px-tool-btn:hover {
  background: var(--surface-3, #45475a);
  color: var(--text-primary, #cdd6f4);
}
.px-tool-btn.active {
  background: var(--accent, #f8d030);
  color: #000;
  border-color: var(--accent, #f8d030);
  font-weight: 600;
}

/* Actions */
.px-actions {
  width: 100%;
  text-align: center;
}
.px-duplicate-btn {
  padding: 0.35rem 0.8rem;
  font-size: 0.75rem;
  background: var(--surface-2, #313244);
  color: var(--text-secondary, #bac2de);
  border: 1px solid var(--border-subtle, #45475a);
  border-radius: 4px;
  cursor: pointer;
}
.px-duplicate-btn:hover {
  background: var(--surface-3, #45475a);
  color: var(--text-primary, #cdd6f4);
}
`;
