/**
 * renderer.js — Canvas rendering for the Tileset Editor.
 * Extracted from metatiles.js. All rendering functions read pixel/palette
 * data from state.js rather than module globals.
 */

import { state, TILE_POSITIONS } from "./state.js";

// ---------------------------------------------------------------------------
// Offscreen tile canvas (for alpha-correct compositing)
// ---------------------------------------------------------------------------

let _tileCanvas = null;
let _tileCtx = null;

function _ensureTileCanvas() {
  if (!_tileCanvas) {
    _tileCanvas = document.createElement("canvas");
    _tileCanvas.width = 8;
    _tileCanvas.height = 8;
    _tileCtx = _tileCanvas.getContext("2d");
  }
}

// ---------------------------------------------------------------------------
// Single 8x8 tile rendering
// ---------------------------------------------------------------------------

/**
 * Render an 8x8 tile with per-tile palette using raw pixel indices.
 * Uses offscreen canvas + drawImage for alpha-correct compositing.
 */
function _renderTileWithPaletteData(ctx, tileRef, tileIdx, dx, dy,
                                     pixels, sheetW, sheetH, pals) {
  const tilesPerRow = sheetW / 8;
  const totalTiles = tilesPerRow * (sheetH / 8);
  if (tileIdx < 0 || tileIdx >= totalTiles) return;

  const pal = pals[tileRef.palette] || pals[0] || [];
  if (pal.length === 0) return;

  const tileCol = tileIdx % tilesPerRow;
  const tileRow = Math.floor(tileIdx / tilesPerRow);
  const srcX = tileCol * 8;
  const srcY = tileRow * 8;

  const imgData = ctx.createImageData(8, 8);
  const data = imgData.data;

  for (let py = 0; py < 8; py++) {
    for (let px = 0; px < 8; px++) {
      let readX = tileRef.hflip ? (7 - px) : px;
      let readY = tileRef.vflip ? (7 - py) : py;

      const srcIdx = (srcY + readY) * sheetW + (srcX + readX);
      const palIdx = pixels[srcIdx] || 0;

      const dstIdx = (py * 8 + px) * 4;
      if (palIdx === 0) {
        data[dstIdx] = 0;
        data[dstIdx + 1] = 0;
        data[dstIdx + 2] = 0;
        data[dstIdx + 3] = 0;
      } else {
        const color = pal[palIdx] || [0, 0, 0];
        data[dstIdx] = color[0];
        data[dstIdx + 1] = color[1];
        data[dstIdx + 2] = color[2];
        data[dstIdx + 3] = 255;
      }
    }
  }

  _ensureTileCanvas();
  _tileCtx.putImageData(imgData, 0, 0);
  ctx.drawImage(_tileCanvas, dx, dy);
}

/**
 * Render a single 8x8 tile from a metatile reference.
 * Automatically routes to primary or secondary tileset data.
 */
export function renderMetatileTile(ctx, tileRef, dx, dy) {
  if (tileRef.tile === 0 && tileRef.palette === 0) return;

  let tileIdx = tileRef.tile;
  let usePrimary = false;
  if (state.primaryTileOffset > 0 && tileIdx < state.primaryTileOffset) {
    usePrimary = true;
  } else if (state.primaryTileOffset > 0) {
    tileIdx -= state.primaryTileOffset;
  }

  const usePixels = usePrimary ? state.primaryPixels : state.tilePixels;
  const useSheetW = usePrimary ? state.primarySheetW : state.tileSheetW;
  const useSheetH = usePrimary ? state.primarySheetH : state.tileSheetH;
  const usePals = usePrimary ? state.primaryPalettes : state.palettes;

  if (usePixels && useSheetW > 0 && usePals.length > 0) {
    _renderTileWithPaletteData(ctx, tileRef, tileIdx, dx, dy,
                                usePixels, useSheetW, useSheetH, usePals);
    return;
  }

  // Fallback: draw from tiles.png Image
  const img = usePrimary ? state.primaryImg : state.tilesImg;
  if (!img) return;
  const tilesPerRow = img.naturalWidth / 8;
  const totalTiles = (img.naturalWidth / 8) * (img.naturalHeight / 8);
  if (tileIdx < 0 || tileIdx >= totalTiles) return;
  const sx = (tileIdx % tilesPerRow) * 8;
  const sy = Math.floor(tileIdx / tilesPerRow) * 8;

  ctx.save();
  if (tileRef.hflip && tileRef.vflip) {
    ctx.translate(dx + 8, dy + 8);
    ctx.scale(-1, -1);
    ctx.drawImage(img, sx, sy, 8, 8, 0, 0, 8, 8);
  } else if (tileRef.hflip) {
    ctx.translate(dx + 8, dy);
    ctx.scale(-1, 1);
    ctx.drawImage(img, sx, sy, 8, 8, 0, 0, 8, 8);
  } else if (tileRef.vflip) {
    ctx.translate(dx, dy + 8);
    ctx.scale(1, -1);
    ctx.drawImage(img, sx, sy, 8, 8, 0, 0, 8, 8);
  } else {
    ctx.drawImage(img, sx, sy, 8, 8, dx, dy, 8, 8);
  }
  ctx.restore();
}

// ---------------------------------------------------------------------------
// Metatile rendering (16x16 composite)
// ---------------------------------------------------------------------------

/**
 * Render a metatile to a 16x16 canvas.
 * layerType: 0=Normal, 1=Covered, 2=Split
 * overrides: null (use layerType) or {bottom: bool, middle: bool, top: bool}
 */
export function renderMetatile(canvas, metatile, layerType, overrides) {
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, 16, 16);

  if (!metatile || !metatile.tiles) return;

  const tiles = metatile.tiles;

  if (overrides) {
    const layers = [];
    if (overrides.bottom) layers.push(tiles.slice(0, 4));
    if (overrides.middle) layers.push(tiles.slice(4, 8));
    if (overrides.top) layers.push(tiles.slice(8, 12));
    for (const layer of layers) {
      for (let i = 0; i < 4; i++) {
        renderMetatileTile(ctx, layer[i], TILE_POSITIONS[i].x, TILE_POSITIONS[i].y);
      }
    }
  } else {
    let lowerLayer = null;
    let upperLayer = null;

    switch (layerType) {
      case 0: // Normal: middle + top
        lowerLayer = tiles.slice(4, 8);
        upperLayer = tiles.slice(8, 12);
        break;
      case 1: // Covered: bottom + middle
        lowerLayer = tiles.slice(0, 4);
        upperLayer = tiles.slice(4, 8);
        break;
      case 2: // Split: bottom + top
        lowerLayer = tiles.slice(0, 4);
        upperLayer = tiles.slice(8, 12);
        break;
    }

    if (lowerLayer) {
      for (let i = 0; i < 4; i++) {
        renderMetatileTile(ctx, lowerLayer[i], TILE_POSITIONS[i].x, TILE_POSITIONS[i].y);
      }
    }
    if (upperLayer) {
      for (let i = 0; i < 4; i++) {
        renderMetatileTile(ctx, upperLayer[i], TILE_POSITIONS[i].x, TILE_POSITIONS[i].y);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Player silhouette
// ---------------------------------------------------------------------------

export function drawPlayerSilhouette(ctx) {
  const px = 4, py = 1;
  ctx.fillStyle = "rgba(60, 180, 255, 0.85)";
  // Head
  ctx.fillRect(px + 2, py, 4, 1);
  ctx.fillRect(px + 1, py + 1, 6, 3);
  ctx.fillRect(px + 2, py + 4, 4, 1);
  // Body
  ctx.fillRect(px + 1, py + 5, 6, 5);
  ctx.fillRect(px + 2, py + 10, 2, 3);
  ctx.fillRect(px + 4, py + 10, 2, 3);
}

/**
 * Render a metatile with player sprite overlaid to show layer depth effect.
 */
export function renderMetatileWithPlayer(canvas, mt, layerType) {
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, 16, 16);
  if (!mt || !mt.tiles) return;

  const tiles = mt.tiles;
  let lowerTiles, upperTiles;

  switch (layerType) {
    case 0: // Normal: middle behind, top in front
      lowerTiles = tiles.slice(4, 8);
      upperTiles = tiles.slice(8, 12);
      break;
    case 1: // Covered: both behind player
      for (let i = 0; i < 4; i++)
        renderMetatileTile(ctx, tiles[i], TILE_POSITIONS[i].x, TILE_POSITIONS[i].y);
      for (let i = 0; i < 4; i++)
        renderMetatileTile(ctx, tiles[4 + i], TILE_POSITIONS[i].x, TILE_POSITIONS[i].y);
      drawPlayerSilhouette(ctx);
      return;
    case 2: // Split: bottom behind, top in front
      lowerTiles = tiles.slice(0, 4);
      upperTiles = tiles.slice(8, 12);
      break;
    default:
      return;
  }

  if (lowerTiles) {
    for (let i = 0; i < 4; i++)
      renderMetatileTile(ctx, lowerTiles[i], TILE_POSITIONS[i].x, TILE_POSITIONS[i].y);
  }

  drawPlayerSilhouette(ctx);

  if (upperTiles) {
    for (let i = 0; i < 4; i++)
      renderMetatileTile(ctx, upperTiles[i], TILE_POSITIONS[i].x, TILE_POSITIONS[i].y);
  }
}

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------

export function cleanupRenderer() {
  _tileCanvas = null;
  _tileCtx = null;
}
