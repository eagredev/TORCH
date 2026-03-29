/**
 * tilePalette.js — 8×8 tile selector panel for the Tileset Editor.
 * Shows all tiles in the tileset as a scrollable grid (16 per row, 2× zoom).
 * Click a tile to assign it to the selected metatile slot.
 * Palette strip at bottom to preview tiles with different palettes.
 */

import {
  state, emit, TILE_POSITIONS,
} from "./state.js";
import { renderMetatileTile } from "./renderer.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TILES_PER_ROW = 16;
const TILE_DISPLAY_SIZE = 20; // 8px at 2.5× zoom
const TILE_NATIVE = 8;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _previewPalette = 0; // which palette to render the tile palette with
let _canvasMap = new Map(); // tileIdx -> canvas element

// ---------------------------------------------------------------------------
// Calculate tile counts from pixel data
// ---------------------------------------------------------------------------

function _getTileCount(pixels, sheetW, sheetH) {
  if (!pixels || !sheetW || !sheetH) return 0;
  return (sheetW / 8) * (sheetH / 8);
}

// ---------------------------------------------------------------------------
// Render tile palette HTML
// ---------------------------------------------------------------------------

export function renderTilePaletteHTML() {
  const secCount = _getTileCount(state.tilePixels, state.tileSheetW, state.tileSheetH);
  const priCount = _getTileCount(state.primaryPixels, state.primarySheetW, state.primarySheetH);

  let html = `<div class="tp-container">`;

  // Palette preview strip
  html += `<div class="tp-pal-strip">`;
  html += `<span class="tp-pal-label">Preview palette:</span>`;
  for (let p = 0; p < 13; p++) {
    const active = p === _previewPalette ? " active" : "";
    const divider = p === 6 ? ` style="margin-left:0.3rem"` : "";
    html += `<button class="tp-pal-btn${active}" data-pal="${p}"${divider}>${p}</button>`;
  }
  html += `</div>`;

  // Primary tiles section
  if (priCount > 0) {
    html += `<div class="tp-section">`;
    html += `<div class="tp-section-label">Primary Tiles (${priCount})</div>`;
    html += `<div class="tp-grid" id="tp-grid-primary" data-tier="primary"></div>`;
    html += `</div>`;
  }

  // Secondary tiles section
  if (secCount > 0) {
    html += `<div class="tp-section">`;
    html += `<div class="tp-section-label">Secondary Tiles (${secCount})</div>`;
    html += `<div class="tp-grid" id="tp-grid-secondary" data-tier="secondary"></div>`;
    html += `</div>`;
  }

  if (priCount === 0 && secCount === 0) {
    html += `<div class="tp-empty">No tile data available.</div>`;
  }

  html += `</div>`;
  return html;
}

// ---------------------------------------------------------------------------
// Render tile canvases into the grids
// ---------------------------------------------------------------------------

export function renderTilePaletteCanvases() {
  _canvasMap.clear();

  // Primary tiles
  const priGrid = document.getElementById("tp-grid-primary");
  if (priGrid && state.primaryPixels) {
    const count = _getTileCount(state.primaryPixels, state.primarySheetW, state.primarySheetH);
    _renderTileGrid(priGrid, count, true);
  }

  // Secondary tiles
  const secGrid = document.getElementById("tp-grid-secondary");
  if (secGrid && state.tilePixels) {
    const count = _getTileCount(state.tilePixels, state.tileSheetW, state.tileSheetH);
    _renderTileGrid(secGrid, count, false);
  }
}

function _renderTileGrid(container, count, isPrimary) {
  container.innerHTML = "";

  for (let i = 0; i < count; i++) {
    const cell = document.createElement("div");
    cell.className = "tp-tile";
    // For primary tiles, the global tile index is just i
    // For secondary tiles, the global index is primaryTileOffset + i
    const globalIdx = isPrimary ? i : (state.primaryTileOffset + i);
    cell.dataset.tile = String(globalIdx);
    cell.dataset.localIdx = String(i);
    cell.dataset.primary = isPrimary ? "1" : "0";

    const canvas = document.createElement("canvas");
    canvas.width = TILE_NATIVE;
    canvas.height = TILE_NATIVE;
    canvas.className = "tp-tile-canvas";

    // Render the tile with the preview palette
    const ctx = canvas.getContext("2d");
    const tileRef = {
      tile: globalIdx,
      palette: _previewPalette,
      hflip: false,
      vflip: false,
    };
    renderMetatileTile(ctx, tileRef, 0, 0);

    cell.appendChild(canvas);
    _canvasMap.set(globalIdx, canvas);
    container.appendChild(cell);
  }
}

// ---------------------------------------------------------------------------
// Re-render all tiles with a new palette
// ---------------------------------------------------------------------------

function _reRenderWithPalette(palette) {
  _previewPalette = palette;

  // Update palette strip active state
  document.querySelectorAll(".tp-pal-btn").forEach(btn => {
    btn.classList.toggle("active", parseInt(btn.dataset.pal, 10) === palette);
  });

  // Re-render all tile canvases
  for (const [globalIdx, canvas] of _canvasMap) {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, TILE_NATIVE, TILE_NATIVE);
    const tileRef = {
      tile: globalIdx,
      palette: palette,
      hflip: false,
      vflip: false,
    };
    renderMetatileTile(ctx, tileRef, 0, 0);
  }
}

// ---------------------------------------------------------------------------
// Bind events
// ---------------------------------------------------------------------------

export function bindTilePaletteEvents(onTileSelect) {
  // Tile clicks
  document.querySelectorAll(".tp-tile").forEach(cell => {
    cell.addEventListener("click", () => {
      const globalIdx = parseInt(cell.dataset.tile, 10);
      if (isNaN(globalIdx)) return;

      // Highlight selected tile
      document.querySelectorAll(".tp-tile.selected").forEach(c => c.classList.remove("selected"));
      cell.classList.add("selected");

      if (onTileSelect) onTileSelect(globalIdx, _previewPalette);
    });
  });

  // Palette strip clicks
  document.querySelectorAll(".tp-pal-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const pal = parseInt(btn.dataset.pal, 10);
      if (!isNaN(pal)) _reRenderWithPalette(pal);
    });
  });
}

// ---------------------------------------------------------------------------
// Programmatic tile selection (sync from compose slot click)
// ---------------------------------------------------------------------------

export function selectTileInPalette(globalTileIdx) {
  if (globalTileIdx == null || globalTileIdx === 0) return;

  // Clear previous selection
  document.querySelectorAll(".tp-tile.selected").forEach(c => c.classList.remove("selected"));

  // Find the tile cell
  const cell = document.querySelector(`.tp-tile[data-tile="${globalTileIdx}"]`);
  if (cell) {
    cell.classList.add("selected");
    cell.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------

export function cleanupTilePalette() {
  _canvasMap.clear();
  _previewPalette = 0;
}

// ---------------------------------------------------------------------------
// CSS for tile palette
// ---------------------------------------------------------------------------

export const TILE_PALETTE_CSS = `
/* Tile palette container */
.tp-container {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  max-height: 70vh;
  overflow-y: auto;
}

/* Palette preview strip */
.tp-pal-strip {
  display: flex;
  align-items: center;
  gap: 0.2rem;
  padding: 0.4rem;
  background: var(--surface-2, #313244);
  border-radius: 4px;
  flex-wrap: wrap;
  position: sticky;
  top: 0;
  z-index: 2;
}
.tp-pal-label {
  font-size: 0.65rem;
  color: var(--text-dim, #585b70);
  margin-right: 0.3rem;
  white-space: nowrap;
}
.tp-pal-btn {
  width: 1.4rem;
  height: 1.4rem;
  font-size: 0.6rem;
  font-family: monospace;
  background: var(--surface-1, #1e1e2e);
  color: var(--text-dim, #585b70);
  border: 1px solid var(--border-subtle, #45475a);
  border-radius: 2px;
  cursor: pointer;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.1s, color 0.1s;
}
.tp-pal-btn:hover {
  color: var(--text-primary, #cdd6f4);
  background: var(--surface-3, #45475a);
}
.tp-pal-btn.active {
  background: var(--accent, #f8d030);
  color: #000;
  border-color: var(--accent, #f8d030);
  font-weight: 700;
}

/* Section headers */
.tp-section {
  margin-bottom: 0.25rem;
}
.tp-section-label {
  font-size: 0.65rem;
  font-weight: 600;
  color: var(--text-dim, #585b70);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.3rem;
  padding: 0 0.2rem;
}

/* Tile grid */
.tp-grid {
  display: grid;
  grid-template-columns: repeat(${TILES_PER_ROW}, ${TILE_DISPLAY_SIZE}px);
  gap: 1px;
  background: var(--surface-1, #1e1e2e);
  border: 1px solid var(--border-subtle, #45475a);
  border-radius: 4px;
  padding: 2px;
}
.tp-tile {
  width: ${TILE_DISPLAY_SIZE}px;
  height: ${TILE_DISPLAY_SIZE}px;
  cursor: pointer;
  border: 1px solid transparent;
  border-radius: 1px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.1s;
}
.tp-tile:hover {
  border-color: var(--text-secondary, #bac2de);
}
.tp-tile.selected {
  border-color: var(--accent, #f8d030);
  box-shadow: 0 0 0 1px var(--accent, #f8d030);
}
.tp-tile-canvas {
  width: ${TILE_DISPLAY_SIZE}px;
  height: ${TILE_DISPLAY_SIZE}px;
  image-rendering: pixelated;
  display: block;
}

/* Empty state */
.tp-empty {
  color: var(--text-dim, #585b70);
  font-size: 0.8rem;
  text-align: center;
  padding: 2rem;
}
`;
