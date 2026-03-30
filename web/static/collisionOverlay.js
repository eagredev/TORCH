/**
 * TORCH IDE — Collision Overlay.
 * TORCH_MODULE
 *
 * Semi-transparent canvas overlay that visualizes per-tile walkability on top
 * of the map canvas.  Tiles are color-coded by collision bits and metatile
 * behavior ID (impassable = red, water = blue, grass = green, ledge = yellow).
 *
 * Camera transform is synced with mapCanvas via IDE_CAMERA_CHANGED events.
 * Toggled on/off from the View menu or the keyboard shortcut Shift+C.
 *
 * Exports: initCollisionOverlay, cleanupCollisionOverlay,
 *          setCollisionTransform, setCollisionVisible, isCollisionVisible
 */

import {
  ideOn,
  IDE_MAP_SELECTED, IDE_CAMERA_CHANGED,
} from "./ide.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const METATILE_PX = 16;

// Behavior classification — IDs from pokeemerald metatile_behaviors.h
// Each behavior maps to a category; categories map to overlay colours.

const WATER_BEHAVIORS = new Set([
  16, 17, 18, 19, 20, 21, 22, 23, 25,  // pond, deep, ocean, waterfall, etc.
  34, 42,                                // seaweed variants
  80, 81, 82, 83,                        // water currents
  108, 109,                              // water door/arrow warp
]);

const GRASS_BEHAVIORS = new Set([
  2, 3, 7, 9,    // tall grass, long grass, short grass, long grass edge
  36,             // ash-covered grass
]);

const LEDGE_BEHAVIORS = new Set([
  56, 57, 58, 59,   // cardinal ledges
  60, 61, 62, 63,   // diagonal ledges
]);

const IMPASSABLE_BEHAVIORS = new Set([
  1,                              // MB_IMPASSABLE
  48, 49, 50, 51, 52, 53, 54, 55, // directional blocks
  192, 193,                        // elevated wall variants
]);

// Overlay colours per category
const COLOR_IMPASSABLE = "rgba(255, 0, 0, 0.25)";
const COLOR_WATER      = "rgba(0, 100, 255, 0.2)";
const COLOR_GRASS      = "rgba(0, 200, 0, 0.15)";
const COLOR_LEDGE      = "rgba(255, 200, 0, 0.2)";

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _wrap = null;          // parent #ide-canvas-wrap
let _canvas = null;        // overlay <canvas>
let _ctx = null;

let _panX = 0;
let _panY = 0;
let _zoom = 2;

let _visible = false;
let _mapName = null;

// Cached collision data from the API
let _data = null;          // { width, height, collision[][], behaviors[][] }

// Pre-rendered offscreen canvas (blitted to the visible canvas on each frame)
let _offscreen = null;
let _offCtx = null;

let _cameraUnsub = null;
let _mapUnsub = null;
let _resizeObs = null;

// ---------------------------------------------------------------------------
// Init / Cleanup
// ---------------------------------------------------------------------------

export function initCollisionOverlay(canvasWrapEl) {
  _wrap = canvasWrapEl;

  _canvas = document.createElement("canvas");
  _canvas.className = "ide-collision-overlay-canvas";
  _canvas.style.cssText =
    "position:absolute;inset:0;pointer-events:none;z-index:3;display:none;";
  _wrap.appendChild(_canvas);
  _ctx = _canvas.getContext("2d");

  // Subscribe to IDE bus events
  _cameraUnsub = ideOn(IDE_CAMERA_CHANGED, (d) => {
    setCollisionTransform(d.panX, d.panY, d.zoom);
  });

  _mapUnsub = ideOn(IDE_MAP_SELECTED, (d) => {
    _mapName = d.name || null;
    _data = null;
    _offscreen = null;
    _offCtx = null;
    if (_visible && _mapName) {
      _fetchAndRender();
    }
  });

  _resizeObs = new ResizeObserver(() => { if (_visible) _draw(); });
  _resizeObs.observe(_wrap);
}

export function cleanupCollisionOverlay() {
  if (_cameraUnsub) { _cameraUnsub(); _cameraUnsub = null; }
  if (_mapUnsub) { _mapUnsub(); _mapUnsub = null; }
  if (_resizeObs) { _resizeObs.disconnect(); _resizeObs = null; }
  if (_canvas && _canvas.parentNode) _canvas.remove();
  _canvas = null;
  _ctx = null;
  _offscreen = null;
  _offCtx = null;
  _data = null;
  _wrap = null;
}

// ---------------------------------------------------------------------------
// Camera sync
// ---------------------------------------------------------------------------

export function setCollisionTransform(panX, panY, zoom) {
  _panX = panX;
  _panY = panY;
  _zoom = zoom;
  if (_visible) _draw();
}

// ---------------------------------------------------------------------------
// Visibility toggle
// ---------------------------------------------------------------------------

export function setCollisionVisible(visible) {
  _visible = !!visible;
  if (_canvas) {
    _canvas.style.display = _visible ? "" : "none";
  }
  if (_visible) {
    if (!_data && _mapName) {
      _fetchAndRender();
    } else {
      _draw();
    }
  }
}

export function isCollisionVisible() {
  return _visible;
}

// ---------------------------------------------------------------------------
// Data fetch
// ---------------------------------------------------------------------------

async function _fetchAndRender() {
  if (!_mapName) return;
  try {
    const resp = await fetch(`/api/maps/${encodeURIComponent(_mapName)}/collision`);
    if (!resp.ok) { _data = null; return; }
    const envelope = await resp.json();
    if (!envelope.ok || !envelope.data) { _data = null; return; }
    _data = envelope.data;
  } catch (_) {
    _data = null;
    return;
  }
  _buildOffscreen();
  _draw();
}

// ---------------------------------------------------------------------------
// Offscreen pre-render
// ---------------------------------------------------------------------------

function _buildOffscreen() {
  if (!_data || !_data.width || !_data.height) { _offscreen = null; return; }

  const w = _data.width;
  const h = _data.height;
  _offscreen = document.createElement("canvas");
  _offscreen.width = w * METATILE_PX;
  _offscreen.height = h * METATILE_PX;
  _offCtx = _offscreen.getContext("2d");

  const collision = _data.collision;
  const behaviors = _data.behaviors;

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const coll = collision[y][x];
      const beh = behaviors[y][x];
      const color = _classifyTile(coll, beh);
      if (!color) continue;
      _offCtx.fillStyle = color;
      _offCtx.fillRect(x * METATILE_PX, y * METATILE_PX, METATILE_PX, METATILE_PX);
    }
  }
}

// ---------------------------------------------------------------------------
// Tile classification
// ---------------------------------------------------------------------------

function _classifyTile(collision, behavior) {
  // Priority order: water > grass > ledge > impassable > collision bits
  if (WATER_BEHAVIORS.has(behavior)) return COLOR_WATER;
  if (GRASS_BEHAVIORS.has(behavior)) return COLOR_GRASS;
  if (LEDGE_BEHAVIORS.has(behavior)) return COLOR_LEDGE;
  if (IMPASSABLE_BEHAVIORS.has(behavior)) return COLOR_IMPASSABLE;
  // Fall back to collision bits from blockdata
  if (collision !== 0) return COLOR_IMPASSABLE;
  return null; // passable, no overlay
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function _draw() {
  if (!_canvas || !_ctx || !_wrap || !_visible) return;

  const rect = _wrap.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;

  // Size canvas to match container
  _canvas.width = rect.width * dpr;
  _canvas.height = rect.height * dpr;
  _canvas.style.width = rect.width + "px";
  _canvas.style.height = rect.height + "px";

  _ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  _ctx.clearRect(0, 0, rect.width, rect.height);

  if (!_offscreen) return;

  // Apply camera transform (same as mapCanvas)
  _ctx.save();
  _ctx.translate(_panX, _panY);
  _ctx.scale(_zoom, _zoom);
  _ctx.imageSmoothingEnabled = false;

  // Blit pre-rendered collision map
  _ctx.drawImage(_offscreen, 0, 0);

  _ctx.restore();
}
