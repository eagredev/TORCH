/**
 * TORCH IDE — Map Canvas (center panel).
 *
 * Renders server-composed map PNG with zoom/pan.
 * Event overlay layer draws NPC sprites, warp arrows, trigger zones, signs.
 * Click detection dispatches IDE_EVENT_SELECTED / IDE_EVENT_DESELECTED.
 */

import { esc } from "./utils.js";
import {
  ideEmit, ideOn,
  IDE_MAP_SELECTED, IDE_EVENT_SELECTED, IDE_EVENT_DESELECTED,
  IDE_COORDS_UPDATED, IDE_MODE_CHANGED, IDE_OPEN_SCRIPT,
  IDE_CAMERA_CHANGED, IDE_EVENT_UPDATED,
} from "./ide.js";
import { activateTab } from "./contextTabs.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const METATILE_PX = 16;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 8;
const ZOOM_STEP = 1.15;

// Sprite sheet frame layout (from game engine ANIMCMD_FRAME indices):
//   0: South stand, 1: North stand, 2: West stand,
//   3: South walk1, 4: South walk2, 5: North walk1,
//   6: North walk2, 7: West walk1, 8: West walk2
// East = West frame horizontally flipped (matching Porymap exactly).
const FACING_FRAME = { down: 0, up: 1, left: 2, right: 2 };

// Map MOVEMENT_TYPE_FACE_X constants to facing directions
function _movementToFacing(movementType) {
  if (!movementType) return "down";
  const mt = movementType.toUpperCase();
  if (mt.includes("FACE_UP")) return "up";
  if (mt.includes("FACE_LEFT")) return "left";
  if (mt.includes("FACE_RIGHT")) return "right";
  return "down";  // FACE_DOWN, WANDER, NONE, etc. all default to down
}

// Event overlay colors
const EVENT_COLORS = {
  npc:     "rgba(96, 165, 250, 0.8)",   // blue
  trainer: "rgba(239, 68, 68, 0.8)",     // red
  warp:    "rgba(167, 139, 250, 0.8)",   // purple
  trigger: "rgba(251, 146, 60, 0.7)",    // orange
  sign:    "rgba(74, 222, 128, 0.8)",    // green
};

/** Read the current theme accent colour as "r, g, b" for use in rgba(). */
function _getAccentRGB() {
  const hex = getComputedStyle(document.documentElement)
    .getPropertyValue("--accent").trim() || "#d4a017";
  const r = parseInt(hex.slice(1, 3), 16) || 212;
  const g = parseInt(hex.slice(3, 5), 16) || 160;
  const b = parseInt(hex.slice(5, 7), 16) || 23;
  return `${r}, ${g}, ${b}`;
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _container = null;
let _canvasWrap = null;
let _canvas = null;
let _ctx = null;
let _coordTip = null;

// Map state
let _mapName = null;
let _mapImg = null;           // loaded Image element
let _mapW = 0;                // metatile width
let _mapH = 0;                // metatile height
let _events = null;           // event data from API
let _connections = null;      // { connections_out, warps_out } from explorer API

// Border and connection strips
let _borderImg = null;        // border tile pattern Image (map + padding, interior transparent)
let _borderDepth = 4;         // metatiles of border padding
let _connectionStrips = [];   // [{ img, direction, offset, connMap }]
let _showBorders = true;      // toggleable via View menu

// Camera
let _zoom = 2;
let _panX = 0;
let _panY = 0;
let _isPanning = false;
let _didPan = false;          // true if mouse moved during pan (suppress click)
let _panStartX = 0;
let _panStartY = 0;
let _panStartPanX = 0;
let _panStartPanY = 0;

// Selection
let _selectedEvent = null;    // { type, index, data }

// Sprite cache: url -> { sheet: Image, frames: { facing -> Canvas } }
let _spriteCache = {};

// Grid and event visibility
let _showGrid = false;
let _showNpcs = true;
let _showWarps = true;
let _showTriggers = true;
let _showSigns = true;

// Script overlay: NPC object_ids to hide (drawn by overlay instead)
let _hiddenNpcIds = new Set();
let _dimNonScriptEvents = false;

// Mode
let _mode = "view";           // "view", "events", or "scripts"
let _contextMenu = null;      // currently open context menu element

// Stamp placement mode
let _stampPending = null;     // { stamp_id, stamp } or null
let _stampBanner = null;      // overlay element for placement mode indicator
let _stampKeyHandler = null;  // keydown listener for Escape

// Event handlers (for cleanup)
let _mapUnsub = null;
let _modeUnsub = null;
let _eventUpdateUnsub = null;
let _resizeObserver = null;
let _boundWheel = null;
let _boundMouseDown = null;
let _boundMouseMove = null;
let _boundMouseUp = null;
let _boundClick = null;
let _boundMouseLeave = null;
let _stampUnsub = null;
let _mapChangeStampUnsub = null;

// ---------------------------------------------------------------------------
// Init / Cleanup
// ---------------------------------------------------------------------------

export function initMapCanvas(container) {
  _container = container;

  // Canvas wrapper
  _canvasWrap = document.createElement("div");
  _canvasWrap.className = "ide-canvas-wrap";
  _canvasWrap.id = "ide-canvas-wrap";

  _canvas = document.createElement("canvas");
  _canvas.id = "ide-map-canvas";
  _canvasWrap.appendChild(_canvas);
  _ctx = _canvas.getContext("2d");

  // Coordinate tooltip
  _coordTip = document.createElement("div");
  _coordTip.className = "ide-coord-tip";
  _canvasWrap.appendChild(_coordTip);

  container.appendChild(_canvasWrap);

  // Empty state
  _showEmptyState();

  // Event listeners
  _boundWheel = _onWheel.bind(null);
  _boundMouseDown = _onMouseDown.bind(null);
  _boundMouseMove = _onMouseMove.bind(null);
  _boundMouseUp = _onMouseUp.bind(null);
  _boundClick = _onClick.bind(null);
  _boundMouseLeave = _onMouseLeave.bind(null);

  _canvasWrap.addEventListener("wheel", _boundWheel, { passive: false });
  _canvasWrap.addEventListener("mousedown", _boundMouseDown);
  _canvasWrap.addEventListener("mousemove", _boundMouseMove);
  _canvasWrap.addEventListener("mouseup", _boundMouseUp);
  _canvasWrap.addEventListener("click", _boundClick);
  _canvasWrap.addEventListener("mouseleave", _boundMouseLeave);
  _canvasWrap.addEventListener("dblclick", _onDblClick);
  _canvasWrap.addEventListener("contextmenu", _onContextMenu);

  // Resize observer
  _resizeObserver = new ResizeObserver(() => _draw());
  _resizeObserver.observe(_canvasWrap);

  // Listen for map selection and mode changes
  _mapUnsub = ideOn(IDE_MAP_SELECTED, (d) => _loadMap(d.name));
  _modeUnsub = ideOn(IDE_MODE_CHANGED, (d) => {
    _mode = d.mode;
    if (_canvasWrap) {
      _canvasWrap.style.cursor = _mode === "events" ? "crosshair" : "grab";
    }
  });

  // Re-fetch events when properties are saved inline
  _eventUpdateUnsub = ideOn(IDE_EVENT_UPDATED, async (d) => {
    if (d.mapName === _mapName) {
      const result = await _loadMapEvents(_mapName);
      if (result) {
        _events = result;
        _preloadSprites(); // no await — sprites update as they load
        _draw();
      }
    }
  });

  // Stamp placement mode — listen for stamp-pending from stamp library
  _stampUnsub = ideOn("ide:stamp-pending", (d) => {
    _enterStampPlacement(d);
  });

  // Cancel stamp placement when map changes
  _mapChangeStampUnsub = ideOn(IDE_MAP_SELECTED, () => {
    if (_stampPending) _cancelStampPlacement();
  });
}

export function cleanupMapCanvas() {
  if (_mapUnsub) _mapUnsub();
  if (_modeUnsub) _modeUnsub();
  if (_eventUpdateUnsub) _eventUpdateUnsub();
  if (_stampUnsub) _stampUnsub();
  if (_mapChangeStampUnsub) _mapChangeStampUnsub();
  _cancelStampPlacement();
  _mapUnsub = null;
  _modeUnsub = null;
  _stampUnsub = null;
  _mapChangeStampUnsub = null;

  if (_resizeObserver) _resizeObserver.disconnect();
  _resizeObserver = null;

  _dismissContextMenu();

  if (_canvasWrap) {
    _canvasWrap.removeEventListener("wheel", _boundWheel);
    _canvasWrap.removeEventListener("mousedown", _boundMouseDown);
    _canvasWrap.removeEventListener("mousemove", _boundMouseMove);
    _canvasWrap.removeEventListener("mouseup", _boundMouseUp);
    _canvasWrap.removeEventListener("click", _boundClick);
    _canvasWrap.removeEventListener("mouseleave", _boundMouseLeave);
    _canvasWrap.removeEventListener("dblclick", _onDblClick);
    _canvasWrap.removeEventListener("contextmenu", _onContextMenu);
  }

  _container = null;
  _canvasWrap = null;
  _canvas = null;
  _ctx = null;
  _coordTip = null;
  _mapName = null;
  _mapImg = null;
  _events = null;
  _selectedEvent = null;
  _spriteCache = {};
  _borderImg = null;
  _connectionStrips = [];
}

// ---------------------------------------------------------------------------
// Map loading
// ---------------------------------------------------------------------------

async function _loadMap(name) {
  _mapName = name;
  _selectedEvent = null;
  _events = null;
  _connections = null;
  _mapImg = null;
  _borderImg = null;
  _connectionStrips = [];

  // Remove empty state
  if (_container) {
    const existing = _container.querySelector(".ide-empty-state");
    if (existing) existing.remove();
  }

  // Show loading overlay
  _showLoading(name);

  // Load map image, events, and connections in parallel
  const [imgResult, eventsResult, connResult] = await Promise.allSettled([
    _loadMapImage(name),
    _loadMapEvents(name),
    _loadMapConnections(name),
  ]);

  _updateLoadingProgress(50);

  if (imgResult.status === "fulfilled" && imgResult.value) {
    _mapImg = imgResult.value.img;
    _mapW = imgResult.value.w;
    _mapH = imgResult.value.h;
  }

  if (eventsResult.status === "fulfilled" && eventsResult.value) {
    _events = eventsResult.value;
    _mapW = _events.width || _mapW;
    _mapH = _events.height || _mapH;
  }

  if (connResult.status === "fulfilled" && connResult.value) {
    _connections = connResult.value;
  }

  // Pre-load NPC sprites and wait for them
  _updateLoadingProgress(70);
  await _preloadSprites();

  // Load border and connection strips in background (don't block initial render)
  _loadBorderAndStrips(name);

  // Hide loading overlay and render
  _hideLoading();
  requestAnimationFrame(() => {
    _fitMap();
    _draw();
  });
}

// ---------------------------------------------------------------------------
// Loading overlay
// ---------------------------------------------------------------------------

function _showLoading(mapName) {
  if (!_canvasWrap) return;
  _hideLoading(); // remove any previous
  const overlay = document.createElement("div");
  overlay.className = "ide-loading-overlay";
  overlay.innerHTML = `
    <div class="ide-loading-icon">\u{1F525}</div>
    <div class="ide-loading-text">Loading ${mapName}...</div>
    <div class="ide-loading-bar"><div class="ide-loading-fill" style="width:10%"></div></div>
  `;
  _canvasWrap.appendChild(overlay);
}

function _updateLoadingProgress(pct) {
  if (!_canvasWrap) return;
  const fill = _canvasWrap.querySelector(".ide-loading-fill");
  if (fill) fill.style.width = pct + "%";
}

function _hideLoading() {
  if (!_canvasWrap) return;
  const el = _canvasWrap.querySelector(".ide-loading-overlay");
  if (el) el.remove();
}

function _loadMapImage(name) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const w = Math.round(img.naturalWidth / METATILE_PX);
      const h = Math.round(img.naturalHeight / METATILE_PX);
      resolve({ img, w, h });
    };
    img.onerror = () => resolve(null);
    img.src = `/api/map/${encodeURIComponent(name)}/render`;
  });
}

async function _loadMapConnections(name) {
  try {
    const res = await fetch(`/api/explorer/map/${encodeURIComponent(name)}`);
    const data = await res.json();
    if (data.ok) return data.data;
  } catch (_) {}
  return null;
}

async function _loadMapEvents(name) {
  try {
    const res = await fetch(`/api/map/${encodeURIComponent(name)}/events`);
    const data = await res.json();
    if (data.ok) return data.data;
  } catch (_) {}
  return null;
}

function _preloadSprites() {
  if (!_events) return Promise.resolve();
  const promises = [];
  for (const npc of _events.object_events || []) {
    const url = npc.sprite_sheet_url;
    const fw = npc.frame_width || 16;
    const fh = npc.frame_height || 32;
    if (url && _spriteCache[url] === undefined) {
      _spriteCache[url] = null; // mark as loading
      promises.push(new Promise((resolve) => {
        const img = new Image();
        img.onload = () => {
          _spriteCache[url] = _processSheet(img, fw, fh);
          resolve();
        };
        img.onerror = () => { _spriteCache[url] = null; resolve(); };
        img.src = url;
      }));
    }
  }
  if (promises.length === 0) return Promise.resolve();
  return Promise.all(promises);
}

/**
 * Process a sprite sheet into per-facing transparent frame canvases.
 * Returns { down, up, left, right } where each is an offscreen canvas.
 */
function _processSheet(img, fw, fh) {
  const frames = {};
  for (const [facing, frameIdx] of Object.entries(FACING_FRAME)) {
    const c = document.createElement("canvas");
    c.width = fw;
    c.height = fh;
    const ctx = c.getContext("2d");

    const sx = frameIdx * fw;
    const flipH = facing === "right";

    if (flipH) {
      ctx.translate(fw, 0);
      ctx.scale(-1, 1);
    }
    ctx.drawImage(img, sx, 0, fw, fh, 0, 0, fw, fh);

    // Remove background color (sample pixel 0,0)
    try {
      const imageData = ctx.getImageData(0, 0, fw, fh);
      const d = imageData.data;
      const bgR = d[0], bgG = d[1], bgB = d[2];
      for (let i = 0; i < d.length; i += 4) {
        if (Math.abs(d[i] - bgR) <= 2 &&
            Math.abs(d[i+1] - bgG) <= 2 &&
            Math.abs(d[i+2] - bgB) <= 2) {
          d[i+3] = 0;
        }
      }
      ctx.putImageData(imageData, 0, 0);
    } catch (_) {}

    frames[facing] = c;
  }
  return frames;
}

// ---------------------------------------------------------------------------
// Border and connection strip loading
// ---------------------------------------------------------------------------

/** Map connection direction to the opposite edge strip we need from the connected map. */
const _OPPOSITE_EDGE = { up: "south", down: "north", left: "east", right: "west" };

function _loadBorderAndStrips(name) {
  // Load border tile pattern
  const borderImg = new Image();
  borderImg.onload = () => { _borderImg = borderImg; _draw(); };
  borderImg.onerror = () => { _borderImg = null; };
  borderImg.src = `/api/map/${encodeURIComponent(name)}/border?depth=${_borderDepth}`;

  // Load connection strips
  if (!_connections) return;
  const conns = _connections.connections_out || [];
  for (const conn of conns) {
    const dir = (conn.direction || "").toLowerCase();
    const connMap = conn.map || "";
    const offset = conn.offset || 0;
    if (!connMap || !_OPPOSITE_EDGE[dir]) continue;

    const edge = _OPPOSITE_EDGE[dir];
    const img = new Image();
    img.onload = () => {
      _connectionStrips.push({ img, direction: dir, offset, connMap });
      _draw();
    };
    img.onerror = () => {};
    img.src = `/api/map/${encodeURIComponent(connMap)}/strip?edge=${edge}&depth=${_borderDepth}`;
  }
}

// ---------------------------------------------------------------------------
// Camera controls
// ---------------------------------------------------------------------------

function _fitMap() {
  if (!_canvasWrap || !_mapImg) return;
  const rect = _canvasWrap.getBoundingClientRect();
  const vw = rect.width;
  const vh = rect.height;
  const iw = _mapImg.naturalWidth;
  const ih = _mapImg.naturalHeight;

  if (iw === 0 || ih === 0) return;

  // If viewport is too small (DOM hasn't laid out yet), retry next frame
  if (vw < 50 || vh < 50) {
    requestAnimationFrame(() => { _fitMap(); _draw(); });
    return;
  }

  // Fit map into viewport with padding, centered
  const padding = 20;
  _zoom = Math.min(
    (vw - padding * 2) / iw,
    (vh - padding * 2) / ih,
    MAX_ZOOM,
  );
  _zoom = Math.max(_zoom, MIN_ZOOM);

  // Center the map in the viewport
  _panX = (vw - iw * _zoom) / 2;
  _panY = (vh - ih * _zoom) / 2;
}

function _screenToMap(sx, sy) {
  const mx = (sx - _panX) / _zoom;
  const my = (sy - _panY) / _zoom;
  return {
    px: mx,
    py: my,
    tileX: Math.floor(mx / METATILE_PX),
    tileY: Math.floor(my / METATILE_PX),
  };
}

// ---------------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------------

function _draw() {
  if (!_canvas || !_ctx || !_canvasWrap) return;

  const rect = _canvasWrap.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;

  // Size canvas to container
  _canvas.width = rect.width * dpr;
  _canvas.height = rect.height * dpr;
  _canvas.style.width = rect.width + "px";
  _canvas.style.height = rect.height + "px";

  _ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  _ctx.clearRect(0, 0, rect.width, rect.height);

  if (!_mapImg) {
    _showEmptyState();
    return;
  }

  // Remove empty state if present
  const es = _container?.querySelector(".ide-empty-state");
  if (es) es.remove();

  // Apply camera transform
  _ctx.save();
  _ctx.translate(_panX, _panY);
  _ctx.scale(_zoom, _zoom);

  // Draw map image (pixelated)
  _ctx.imageSmoothingEnabled = false;

  // Border tiles and connection strips (behind the map)
  if (_showBorders) {
    _drawBorderAndStrips();
  }

  // Main map image
  _ctx.drawImage(_mapImg, 0, 0);

  // Grid
  if (_showGrid && _zoom >= 1) {
    _drawGrid();
  }

  // Event overlays
  _drawEvents();

  // Drag preview — ghost of the event at the drag position
  if (_dragging) {
    const dx = _dragging.currentX * METATILE_PX;
    const dy = _dragging.currentY * METATILE_PX;
    const lw = Math.max(1, 2 / _zoom);
    const fs = Math.max(6, 8 / _zoom);
    _ctx.globalAlpha = 0.65;

    if (_dragging.hitType === "npc" && _dragging.data.sprite_sheet_url) {
      // Draw the NPC sprite ghost
      const frames = _spriteCache[_dragging.data.sprite_sheet_url];
      if (frames) {
        _drawNpcSprite(frames, dx, dy, _dragging.data);
      } else {
        _ctx.fillStyle = EVENT_COLORS.npc;
        _ctx.beginPath();
        _ctx.arc(dx + METATILE_PX / 2, dy + METATILE_PX / 2, 5, 0, Math.PI * 2);
        _ctx.fill();
      }
    } else if (_dragging.hitType === "warp") {
      _ctx.fillStyle = "rgba(167, 139, 250, 0.25)";
      _ctx.fillRect(dx, dy, METATILE_PX, METATILE_PX);
      _ctx.fillStyle = EVENT_COLORS.warp;
      _ctx.font = `bold ${fs}px monospace`;
      _ctx.textAlign = "center";
      _ctx.textBaseline = "middle";
      _ctx.fillText("\u2195", dx + METATILE_PX / 2, dy + METATILE_PX / 2);
    } else if (_dragging.hitType === "trigger") {
      _ctx.fillStyle = "rgba(251, 146, 60, 0.2)";
      _ctx.fillRect(dx, dy, METATILE_PX, METATILE_PX);
      _ctx.strokeStyle = EVENT_COLORS.trigger;
      _ctx.lineWidth = lw;
      _ctx.setLineDash([2 / _zoom, 2 / _zoom]);
      _ctx.strokeRect(dx, dy, METATILE_PX, METATILE_PX);
      _ctx.setLineDash([]);
    } else if (_dragging.hitType === "sign") {
      _ctx.fillStyle = "rgba(74, 222, 128, 0.25)";
      _ctx.fillRect(dx + 2, dy + 2, METATILE_PX - 4, METATILE_PX - 4);
      _ctx.fillStyle = EVENT_COLORS.sign;
      _ctx.font = `bold ${fs}px monospace`;
      _ctx.textAlign = "center";
      _ctx.textBaseline = "middle";
      _ctx.fillText("S", dx + METATILE_PX / 2, dy + METATILE_PX / 2);
    }

    // Selection ring around the ghost
    _ctx.strokeStyle = "#fff";
    _ctx.lineWidth = lw;
    _ctx.strokeRect(dx - 1, dy - 1, METATILE_PX + 2, METATILE_PX + 2);
    _ctx.globalAlpha = 1.0;
  }

  _ctx.restore();

  // Notify script overlay of current camera transform
  ideEmit(IDE_CAMERA_CHANGED, { panX: _panX, panY: _panY, zoom: _zoom });
}

function _drawGrid() {
  if (!_mapW || !_mapH) return;

  _ctx.strokeStyle = "rgba(255,255,255,0.08)";
  _ctx.lineWidth = 1 / _zoom;

  for (let x = 0; x <= _mapW; x++) {
    _ctx.beginPath();
    _ctx.moveTo(x * METATILE_PX, 0);
    _ctx.lineTo(x * METATILE_PX, _mapH * METATILE_PX);
    _ctx.stroke();
  }
  for (let y = 0; y <= _mapH; y++) {
    _ctx.beginPath();
    _ctx.moveTo(0, y * METATILE_PX);
    _ctx.lineTo(_mapW * METATILE_PX, y * METATILE_PX);
    _ctx.stroke();
  }
}

function _drawBorderAndStrips() {
  const d = _borderDepth;
  const mapPxW = _mapW * METATILE_PX;
  const mapPxH = _mapH * METATILE_PX;

  // 1. Draw the border tile pattern (dimmed — auto-generated border)
  if (_borderImg && _borderImg.complete && _borderImg.naturalWidth > 0) {
    _ctx.globalAlpha = 0.35;
    _ctx.drawImage(_borderImg, -d * METATILE_PX, -d * METATILE_PX);
    _ctx.globalAlpha = 1.0;
  }

  // 2. Draw connection strips — clipped to only the border region
  const borderPx = d * METATILE_PX;
  const lw = Math.max(1, 2 / _zoom);

  for (const strip of _connectionStrips) {
    if (!strip.img || !strip.img.complete || strip.img.naturalWidth <= 0) continue;

    let sx = 0, sy = 0;
    if (strip.direction === "up") {
      sx = strip.offset * METATILE_PX;
      sy = -strip.img.naturalHeight;
    } else if (strip.direction === "down") {
      sx = strip.offset * METATILE_PX;
      sy = mapPxH;
    } else if (strip.direction === "left") {
      sx = -strip.img.naturalWidth;
      sy = strip.offset * METATILE_PX;
    } else if (strip.direction === "right") {
      sx = mapPxW;
      sy = strip.offset * METATILE_PX;
    }

    // Clip the strip to the border region (don't extend past the border depth)
    _ctx.save();
    _ctx.beginPath();
    _ctx.rect(-borderPx, -borderPx,
              mapPxW + borderPx * 2, mapPxH + borderPx * 2);
    // Cut out the map interior so strips only show in the border area
    _ctx.rect(0, mapPxH, mapPxW, -mapPxH);  // winding-rule hole
    _ctx.clip("evenodd");

    // Draw the strip at full brightness
    _ctx.drawImage(strip.img, sx, sy);

    // Themed neon outline around the strip
    const accent = _getAccentRGB();
    _ctx.strokeStyle = `rgba(${accent}, 0.5)`;
    _ctx.lineWidth = 0.5;
    _ctx.strokeRect(sx, sy, strip.img.naturalWidth, strip.img.naturalHeight);

    _ctx.restore();

    // Tight connection label — pixel font, corner tag
    const labelH = 3.5;
    _ctx.font = `bold ${labelH}px monospace`;
    _ctx.textAlign = "left";
    _ctx.textBaseline = "top";
    _ctx.imageSmoothingEnabled = false;

    const label = strip.connMap;
    const measured = _ctx.measureText(label);
    const padX = 1;
    const padY = 0.5;
    const tagW = measured.width + padX * 2;
    const tagH = labelH + padY * 2;
    const tagX = sx;
    const tagY = sy;

    _ctx.fillStyle = `rgba(${accent}, 0.8)`;
    _ctx.fillRect(tagX, tagY, tagW, tagH);

    _ctx.lineWidth = 0.6;
    _ctx.lineJoin = "round";
    _ctx.strokeStyle = "rgba(0, 0, 0, 0.9)";
    _ctx.strokeText(label, tagX + padX, tagY + padY);
    _ctx.fillStyle = "#fff";
    _ctx.fillText(label, tagX + padX, tagY + padY);
  }
}

function _drawEvents() {
  if (!_events) return;

  const lw = Math.max(1, 1 / _zoom);
  const fontSize = Math.max(6, 8 / _zoom);

  // Dim non-script events when in scripts mode with dimming active
  if (_dimNonScriptEvents) _ctx.globalAlpha = 0.15;

  // Triggers (draw first, behind everything)
  if (_showTriggers) for (const ev of _events.coord_events || []) {
    const x = ev.x * METATILE_PX;
    const y = ev.y * METATILE_PX;
    _ctx.fillStyle = "rgba(251, 146, 60, 0.2)";
    _ctx.fillRect(x, y, METATILE_PX, METATILE_PX);
    _ctx.strokeStyle = EVENT_COLORS.trigger;
    _ctx.lineWidth = lw;
    _ctx.setLineDash([2 / _zoom, 2 / _zoom]);
    _ctx.strokeRect(x, y, METATILE_PX, METATILE_PX);
    _ctx.setLineDash([]);
  }

  // Signs
  if (_showSigns) for (const ev of _events.bg_events || []) {
    const x = ev.x * METATILE_PX;
    const y = ev.y * METATILE_PX;
    _ctx.fillStyle = "rgba(74, 222, 128, 0.25)";
    _ctx.fillRect(x + 2, y + 2, METATILE_PX - 4, METATILE_PX - 4);
    _ctx.strokeStyle = EVENT_COLORS.sign;
    _ctx.lineWidth = lw;
    _ctx.strokeRect(x + 2, y + 2, METATILE_PX - 4, METATILE_PX - 4);
    // Sign icon (S)
    _ctx.fillStyle = EVENT_COLORS.sign;
    _ctx.font = `bold ${fontSize}px monospace`;
    _ctx.textAlign = "center";
    _ctx.textBaseline = "middle";
    _ctx.fillText("S", x + METATILE_PX / 2, y + METATILE_PX / 2);
  }

  // Warps
  if (_showWarps) for (const ev of _events.warp_events || []) {
    const x = ev.x * METATILE_PX;
    const y = ev.y * METATILE_PX;
    _ctx.fillStyle = "rgba(167, 139, 250, 0.25)";
    _ctx.fillRect(x, y, METATILE_PX, METATILE_PX);
    _ctx.strokeStyle = EVENT_COLORS.warp;
    _ctx.lineWidth = lw;
    _ctx.strokeRect(x, y, METATILE_PX, METATILE_PX);
    // Arrow icon
    _ctx.fillStyle = EVENT_COLORS.warp;
    _ctx.font = `bold ${fontSize}px monospace`;
    _ctx.textAlign = "center";
    _ctx.textBaseline = "middle";
    _ctx.fillText("\u2195", x + METATILE_PX / 2, y + METATILE_PX / 2);
  }

  // NPCs (draw last, on top) — skip cast members handled by script overlay
  // Restore alpha for NPCs (non-cast NPCs still show, dimmed separately if needed)
  if (_dimNonScriptEvents) _ctx.globalAlpha = 0.25;
  if (_showNpcs) for (const npc of _events.object_events || []) {
    if (_hiddenNpcIds.size > 0 && _hiddenNpcIds.has(npc.object_id)) continue;
    const x = npc.x * METATILE_PX;
    const y = npc.y * METATILE_PX;

    // Try to draw sprite from pre-processed facing frame
    const spriteFrames = npc.sprite_sheet_url ? _spriteCache[npc.sprite_sheet_url] : null;
    if (spriteFrames) {
      _drawNpcSprite(spriteFrames, x, y, npc);
    } else {
      // Fallback: colored dot
      const color = npc.is_trainer ? EVENT_COLORS.trainer : EVENT_COLORS.npc;
      _ctx.fillStyle = color;
      _ctx.beginPath();
      _ctx.arc(x + METATILE_PX / 2, y + METATILE_PX / 2, 5, 0, Math.PI * 2);
      _ctx.fill();
    }

    // Selection highlight
    if (_selectedEvent &&
        _selectedEvent.type === "npc" &&
        _selectedEvent.data.object_id === npc.object_id) {
      _ctx.strokeStyle = "#fff";
      _ctx.lineWidth = 2 / _zoom;
      _ctx.strokeRect(x - 1, y - 1, METATILE_PX + 2, METATILE_PX + 2);
    }
  }

  // Selection highlight for non-NPC events
  if (_selectedEvent && _selectedEvent.type !== "npc") {
    const ev = _selectedEvent.data;
    const x = ev.x * METATILE_PX;
    const y = ev.y * METATILE_PX;
    _ctx.strokeStyle = "#fff";
    _ctx.lineWidth = 2 / _zoom;
    _ctx.strokeRect(x - 1, y - 1, METATILE_PX + 2, METATILE_PX + 2);
  }

  // Restore alpha after dimming
  if (_dimNonScriptEvents) _ctx.globalAlpha = 1.0;

  // Connection labels (only when border tiles are hidden — strips handle it otherwise)
  if (!_showBorders) {
    _drawConnections(lw, fontSize);
  }
}

function _roundRect(x, y, w, h, r) {
  _ctx.beginPath();
  _ctx.moveTo(x + r, y);
  _ctx.lineTo(x + w - r, y);
  _ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  _ctx.lineTo(x + w, y + h - r);
  _ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  _ctx.lineTo(x + r, y + h);
  _ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  _ctx.lineTo(x, y + r);
  _ctx.quadraticCurveTo(x, y, x + r, y);
  _ctx.closePath();
}

function _drawConnections(lw, fontSize) {
  if (!_connections || !_mapW || !_mapH) return;

  const conns = _connections.connections_out || [];
  if (conns.length === 0) return;

  const mapPxW = _mapW * METATILE_PX;
  const mapPxH = _mapH * METATILE_PX;
  const accent = _getAccentRGB();
  const labelH = 3.5;
  const padX = 1;
  const padY = 0.5;

  _ctx.font = `bold ${labelH}px monospace`;
  _ctx.textAlign = "left";
  _ctx.textBaseline = "top";
  _ctx.imageSmoothingEnabled = false;

  for (const conn of conns) {
    const dir = (conn.direction || "").toLowerCase();
    const name = conn.map || "";
    if (!name) continue;

    _ctx.strokeStyle = `rgba(${accent}, 0.5)`;
    _ctx.lineWidth = 0.5;

    let tagX, tagY;
    if (dir === "up" || dir === "north") {
      _ctx.beginPath(); _ctx.moveTo(0, 0); _ctx.lineTo(mapPxW, 0); _ctx.stroke();
      tagX = 0; tagY = -(labelH + padY * 2);
    } else if (dir === "down" || dir === "south") {
      _ctx.beginPath(); _ctx.moveTo(0, mapPxH); _ctx.lineTo(mapPxW, mapPxH); _ctx.stroke();
      tagX = 0; tagY = mapPxH;
    } else if (dir === "left" || dir === "west") {
      _ctx.beginPath(); _ctx.moveTo(0, 0); _ctx.lineTo(0, mapPxH); _ctx.stroke();
      const m = _ctx.measureText(name);
      tagX = -(m.width + padX * 2); tagY = 0;
    } else if (dir === "right" || dir === "east") {
      _ctx.beginPath(); _ctx.moveTo(mapPxW, 0); _ctx.lineTo(mapPxW, mapPxH); _ctx.stroke();
      tagX = mapPxW; tagY = 0;
    } else {
      continue;
    }

    const m = _ctx.measureText(name);
    const tagW = m.width + padX * 2;
    const tagH = labelH + padY * 2;

    _ctx.fillStyle = `rgba(${accent}, 0.8)`;
    _ctx.fillRect(tagX, tagY, tagW, tagH);

    _ctx.lineWidth = 0.6;
    _ctx.lineJoin = "round";
    _ctx.strokeStyle = "rgba(0, 0, 0, 0.9)";
    _ctx.strokeText(name, tagX + padX, tagY + padY);
    _ctx.fillStyle = "#fff";
    _ctx.fillText(name, tagX + padX, tagY + padY);
  }
}

function _drawNpcSprite(frames, x, y, npc) {
  // frames is { down, up, left, right } — pre-processed transparent canvases.
  const facing = _movementToFacing(npc.movement_type);
  const frameCanvas = frames[facing] || frames["down"];
  if (!frameCanvas) return;

  const fw = frameCanvas.width;
  const fh = frameCanvas.height;

  // Center horizontally in the metatile, anchor bottom of tile
  const dx = x + (METATILE_PX - fw) / 2;
  const dy = y + METATILE_PX - fh;

  _ctx.drawImage(frameCanvas, dx, dy, fw, fh);
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function _showEmptyState() {
  if (!_container) return;
  let es = _container.querySelector(".ide-empty-state");
  if (es) return;
  es = document.createElement("div");
  es.className = "ide-empty-state";
  es.innerHTML = `
    <div class="logo">\u{1F525}</div>
    <div>Select a map from the tree</div>
  `;
  _container.appendChild(es);
}

// ---------------------------------------------------------------------------
// Input handlers
// ---------------------------------------------------------------------------

function _onWheel(e) {
  e.preventDefault();
  const rect = _canvasWrap.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;

  // Zoom toward cursor
  const oldZoom = _zoom;
  if (e.deltaY < 0) {
    _zoom = Math.min(_zoom * ZOOM_STEP, MAX_ZOOM);
  } else {
    _zoom = Math.max(_zoom / ZOOM_STEP, MIN_ZOOM);
  }

  // Adjust pan to keep point under cursor
  _panX = mx - (mx - _panX) * (_zoom / oldZoom);
  _panY = my - (my - _panY) * (_zoom / oldZoom);

  _draw();
}

function _onMouseDown(e) {
  if (e.button === 1) {
    // Middle-click to pan
    e.preventDefault();
    _isPanning = true;
    _didPan = false;
    _panStartX = e.clientX;
    _panStartY = e.clientY;
    _panStartPanX = _panX;
    _panStartPanY = _panY;
    _canvasWrap.classList.add("panning");
  }
}

function _onMouseMove(e) {
  // Drag-to-move an event
  if (_dragging) {
    const rect = _canvasWrap.getBoundingClientRect();
    const pos = _screenToMap(e.clientX - rect.left, e.clientY - rect.top);
    const nx = Math.max(0, Math.min(pos.tileX, _mapW - 1));
    const ny = Math.max(0, Math.min(pos.tileY, _mapH - 1));
    if (nx !== _dragging.currentX || ny !== _dragging.currentY) {
      _dragging.currentX = nx;
      _dragging.currentY = ny;
      _draw();
    }
    return;
  }

  if (_isPanning) {
    const dx = e.clientX - _panStartX;
    const dy = e.clientY - _panStartY;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) _didPan = true;
    _panX = _panStartPanX + dx;
    _panY = _panStartPanY + dy;
    _draw();
    return;
  }

  // Update coordinates in status bar + hover tooltip
  if (_mapImg) {
    const rect = _canvasWrap.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const pos = _screenToMap(mx, my);

    if (pos.tileX >= 0 && pos.tileX < _mapW &&
        pos.tileY >= 0 && pos.tileY < _mapH) {
      ideEmit(IDE_COORDS_UPDATED, { x: pos.tileX, y: pos.tileY });

      // Hover tooltip for events
      const hit = _hitTest(pos.tileX, pos.tileY);
      if (hit && _coordTip) {
        _coordTip.style.display = "";
        _coordTip.style.left = (mx + 12) + "px";
        _coordTip.style.top = (my - 8) + "px";
        _coordTip.textContent = _tooltipText(hit);
      } else if (_coordTip) {
        _coordTip.style.display = "none";
      }
    } else {
      // Outside map bounds — check for connection strip hover
      const connHit = _hitTestConnectionStrip(pos.px, pos.py);
      if (connHit && _coordTip) {
        _coordTip.style.display = "";
        _coordTip.style.left = (mx + 12) + "px";
        _coordTip.style.top = (my - 8) + "px";
        _coordTip.textContent = `${connHit} — dbl-click to navigate`;
      } else if (_coordTip) {
        _coordTip.style.display = "none";
      }
      ideEmit(IDE_COORDS_UPDATED, null);
    }
  }
}

function _tooltipText(hit) {
  if (hit.type === "npc") {
    const gfx = (hit.data.graphics_id || "").replace("OBJ_EVENT_GFX_", "");
    const script = hit.data.script ? ` — ${hit.data.script}` : "";
    return `NPC #${hit.data.object_id}: ${gfx}${script}`;
  }
  if (hit.type === "warp") {
    return `Warp → ${hit.data.dest_map || "?"} (dbl-click to go)`;
  }
  if (hit.type === "trigger") {
    return `Trigger #${hit.data.id}: ${hit.data.script || "no script"}`;
  }
  if (hit.type === "sign") {
    return `Sign #${hit.data.id}: ${hit.data.script || hit.data.type || ""}`;
  }
  return "";
}

let _didDrag = false;  // suppress click after drag

function _onMouseUp(e) {
  if (_dragging) {
    const d = _dragging;
    _dragging = null;
    _didDrag = true;  // suppress the click that follows mouseup
    // Commit the move if position actually changed
    if (d.currentX !== d.startX || d.currentY !== d.startY) {
      _moveEvent(d.type, d.index, d.currentX, d.currentY);
    }
    _draw();
    return;
  }
  if (_isPanning) {
    _isPanning = false;
    _canvasWrap.classList.remove("panning");
  }
}

function _onMouseLeave() {
  if (_dragging) {
    _dragging = null;
    _draw();
  }
  if (_isPanning) {
    _isPanning = false;
    _canvasWrap.classList.remove("panning");
  }
  ideEmit(IDE_COORDS_UPDATED, null);
}

function _onClick(e) {
  if (e.button !== 0) return;
  // Suppress click if we just finished panning or dragging
  if (_didPan) { _didPan = false; return; }
  if (_didDrag) { _didDrag = false; return; }

  const rect = _canvasWrap.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const pos = _screenToMap(mx, my);

  // Stamp placement mode — intercept click
  if (_stampPending) {
    if (pos.tileX >= 0 && pos.tileX < _mapW &&
        pos.tileY >= 0 && pos.tileY < _mapH && _mapName) {
      _executeStampPlacement(pos.tileX, pos.tileY);
    }
    return;
  }

  if (!_events) return;

  // Hit-test events (NPCs first, then warps, triggers, signs)
  const hit = _hitTest(pos.tileX, pos.tileY);

  if (hit) {
    _selectedEvent = hit;
    ideEmit(IDE_EVENT_SELECTED, hit);
  } else {
    _selectedEvent = null;
    ideEmit(IDE_EVENT_DESELECTED, {});
  }

  _draw();
}

function _hitTest(tx, ty) {
  if (!_events) return null;

  // Check NPCs
  for (const npc of _events.object_events || []) {
    if (npc.x === tx && npc.y === ty) {
      return { type: "npc", data: npc };
    }
  }
  // Check warps
  for (const warp of _events.warp_events || []) {
    if (warp.x === tx && warp.y === ty) {
      return { type: "warp", data: warp };
    }
  }
  // Check triggers
  for (const trig of _events.coord_events || []) {
    if (trig.x === tx && trig.y === ty) {
      return { type: "trigger", data: trig };
    }
  }
  // Check signs
  for (const bg of _events.bg_events || []) {
    if (bg.x === tx && bg.y === ty) {
      return { type: "sign", data: bg };
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Double-click: open script editor for NPC
// ---------------------------------------------------------------------------

function _onDblClick(e) {
  if (!_mapName) return;

  // In Event Mode, double-click is handled by drag/select — don't open scripts
  if (_mode === "events") return;

  // In Scripts Mode, double-click NPC → open their script
  if (_mode === "scripts") {
    const rect = _canvasWrap.getBoundingClientRect();
    const pos = _screenToMap(e.clientX - rect.left, e.clientY - rect.top);
    if (!_events) return;
    const hit = _hitTest(pos.tileX, pos.tileY);
    if (hit && hit.type === "npc" && hit.data.script) {
      // map.json uses full labels (e.g. "ShirubeTown_Buster");
      // workspace scripts use short names (e.g. "Buster").
      // Try stripping the MapName_ prefix as a best-effort match.
      let scriptName = hit.data.script;
      const prefix = _mapName + "_";
      if (scriptName.startsWith(prefix)) {
        scriptName = scriptName.slice(prefix.length);
      }
      ideEmit(IDE_OPEN_SCRIPT, {
        mapName: _mapName,
        scriptName,
      });
    }
    return;
  }

  const rect = _canvasWrap.getBoundingClientRect();
  const pos = _screenToMap(e.clientX - rect.left, e.clientY - rect.top);

  // Check connection strips first (click may be outside map bounds)
  const connHit = _hitTestConnectionStrip(pos.px, pos.py);
  if (connHit) {
    ideEmit(IDE_MAP_SELECTED, { name: connHit, source: "connection-navigate" });
    return;
  }

  if (!_events) return;
  const hit = _hitTest(pos.tileX, pos.tileY);

  if (!hit) return;

  if (hit.type === "npc") {
    _openNpcDetail(hit.data.object_id);
  } else if (hit.type === "warp" && hit.data.dest_map) {
    ideEmit(IDE_MAP_SELECTED, {
      name: hit.data.dest_map,
      source: "warp-navigate",
    });
  }
}

/** Hit-test connection strips (within the border region only). */
function _hitTestConnectionStrip(px, py) {
  const mapPxW = _mapW * METATILE_PX;
  const mapPxH = _mapH * METATILE_PX;
  const borderPx = _borderDepth * METATILE_PX;

  // Must be in the border area (outside map, within border depth)
  if (px >= 0 && px < mapPxW && py >= 0 && py < mapPxH) return null;
  if (px < -borderPx || px >= mapPxW + borderPx) return null;
  if (py < -borderPx || py >= mapPxH + borderPx) return null;

  for (const strip of _connectionStrips) {
    if (!strip.img || !strip.img.complete) continue;

    let sx = 0, sy = 0;
    if (strip.direction === "up") {
      sx = strip.offset * METATILE_PX;
      sy = -strip.img.naturalHeight;
    } else if (strip.direction === "down") {
      sx = strip.offset * METATILE_PX;
      sy = mapPxH;
    } else if (strip.direction === "left") {
      sx = -strip.img.naturalWidth;
      sy = strip.offset * METATILE_PX;
    } else if (strip.direction === "right") {
      sx = mapPxW;
      sy = strip.offset * METATILE_PX;
    }

    if (px >= sx && px < sx + strip.img.naturalWidth &&
        py >= sy && py < sy + strip.img.naturalHeight) {
      return strip.connMap;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Right-click context menu (Event Mode)
// ---------------------------------------------------------------------------

function _onContextMenu(e) {
  e.preventDefault();
  _dismissContextMenu();

  if (!_events || !_mapName) return;

  const rect = _canvasWrap.getBoundingClientRect();
  const pos = _screenToMap(e.clientX - rect.left, e.clientY - rect.top);
  const hit = _hitTest(pos.tileX, pos.tileY);

  const items = [];
  const tx = pos.tileX, ty = pos.tileY;

  if (hit) {
    // --- Context menu for an existing event ---
    if (hit.type === "npc") {
      items.push({ label: `NPC #${hit.data.object_id}`, disabled: true });
      if (_mode === "scripts" && hit.data.script) {
        let scriptName = hit.data.script;
        const prefix = _mapName + "_";
        if (scriptName.startsWith(prefix)) scriptName = scriptName.slice(prefix.length);
        items.push({
          label: "Edit Script",
          action: () => ideEmit(IDE_OPEN_SCRIPT, { mapName: _mapName, scriptName }),
        });
        items.push({ sep: true });
      }
      items.push({
        label: "Edit NPC",
        action: () => _openNpcDetail(hit.data.object_id),
      });
      if (_mode !== "scripts") {
        items.push({
          label: "Select",
          action: () => {
            _selectedEvent = hit;
            ideEmit(IDE_EVENT_SELECTED, hit);
            _draw();
          },
        });
      }
      items.push({ sep: true });
      items.push({
        label: "Show in NPC List",
        action: () => { activateTab("npcs"); ideEmit(IDE_EVENT_SELECTED, hit); },
      });
      items.push({
        label: "Encounters Here",
        action: () => activateTab("encounters"),
      });
      items.push({ sep: true });
      items.push({
        label: "Delete NPC",
        danger: true,
        action: () => _deleteEvent("object", _findEventIndex("object_events", hit.data)),
      });
    } else if (hit.type === "warp") {
      items.push({ label: `Warp #${hit.data.id}`, disabled: true });
      if (hit.data.dest_map) {
        items.push({
          label: `Go to ${hit.data.dest_map}`,
          action: () => ideEmit(IDE_MAP_SELECTED, {
            name: hit.data.dest_map, source: "context",
          }),
        });
      }
      items.push({ sep: true });
      items.push({
        label: "Show in Warps",
        action: () => { activateTab("warps"); ideEmit(IDE_EVENT_SELECTED, hit); },
      });
      items.push({ sep: true });
      items.push({
        label: "Delete Warp",
        danger: true,
        action: () => _deleteEvent("warp", hit.data.id),
      });
    } else if (hit.type === "trigger") {
      items.push({ label: `Trigger #${hit.data.id}`, disabled: true });
      items.push({ sep: true });
      items.push({
        label: "Delete Trigger",
        danger: true,
        action: () => _deleteEvent("coord", hit.data.id),
      });
    } else if (hit.type === "sign") {
      items.push({ label: `Sign #${hit.data.id}`, disabled: true });
      items.push({ sep: true });
      items.push({
        label: "Delete Sign",
        danger: true,
        action: () => _deleteEvent("bg", hit.data.id),
      });
    }
  } else if (_mode === "events") {
    // --- Context menu on empty tile in Event Mode ---
    items.push({ label: `Tile (${tx}, ${ty})`, disabled: true });
    items.push({
      label: "New NPC here...",
      action: () => _openNpcWizardAt(tx, ty),
    });
    items.push({
      label: "New Warp here",
      action: () => _createEvent("warp", tx, ty),
    });
    items.push({
      label: "New Trigger here",
      action: () => _createEvent("coord", tx, ty),
    });
    items.push({
      label: "New Sign here",
      action: () => _createEvent("bg", tx, ty),
    });
    items.push({ sep: true });
    items.push({
      label: "Encounters Here",
      action: () => activateTab("encounters"),
    });
    items.push({
      label: "Place Stamp Here...",
      action: () => _openStampLibraryAt(tx, ty),
    });
  }

  if (items.length === 0) return;

  // Build menu DOM
  const menu = document.createElement("div");
  menu.className = "ide-context-menu";
  menu.style.left = e.clientX + "px";
  menu.style.top = e.clientY + "px";

  for (const item of items) {
    if (item.sep) {
      const sep = document.createElement("div");
      sep.className = "ide-context-sep";
      menu.appendChild(sep);
      continue;
    }
    const el = document.createElement("div");
    el.className = "ide-context-item"
      + (item.disabled ? " disabled" : "")
      + (item.danger ? " danger" : "");
    el.textContent = item.label;
    if (item.action) {
      el.addEventListener("click", () => {
        _dismissContextMenu();
        item.action();
      });
    }
    menu.appendChild(el);
  }

  document.body.appendChild(menu);
  _contextMenu = menu;

  // Dismiss on next click anywhere
  const dismiss = (ev) => {
    if (!menu.contains(ev.target)) {
      _dismissContextMenu();
    }
    document.removeEventListener("click", dismiss);
  };
  setTimeout(() => document.addEventListener("click", dismiss), 0);
}

function _dismissContextMenu() {
  if (_contextMenu) {
    _contextMenu.remove();
    _contextMenu = null;
  }
}

// ---------------------------------------------------------------------------
// Event CRUD helpers (canvas-level create / delete / move)
// ---------------------------------------------------------------------------

async function _openNpcDetail(npcId) {
  if (!_mapName) return;
  try {
    const { openToolModal } = await import("./toolbar.js");
    openToolModal(
      `NPC #${npcId}`,
      async () => {
        const mod = await import("./views/npcDetail.js");
        return {
          render: (container) => mod.renderNpcDetailModal(container, _mapName, npcId),
          cleanup: () => mod.cleanupNpcDetail(),
        };
      },
    );
  } catch (_) {}
}

async function _openStampLibraryAt(x, y) {
  if (!_mapName) return;
  try {
    const { openToolModal } = await import("./toolbar.js");
    openToolModal(
      "Stamp Library",
      async () => {
        const mod = await import("./views/stampLibrary.js");
        return {
          render: (container) => mod.render(container),
          cleanup: () => mod.cleanup(),
        };
      },
      { presetCoords: { x, y }, mapName: _mapName },
    );
  } catch (_) {}
}

async function _openNpcWizardAt(x, y) {
  if (!_mapName) return;
  try {
    const { openNpcWizard } = await import("./views/npcWizard.js");
    openNpcWizard(_mapName, () => _reloadEvents(), { x, y });
  } catch (_) {}
}

async function _createEvent(type, x, y) {
  if (!_mapName) return;
  try {
    const res = await fetch(`/api/map/${encodeURIComponent(_mapName)}/events/${type}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ x, y }),
    });
    const data = await res.json();
    if (data.ok) {
      await _reloadEvents();
    }
  } catch (_) {}
}

async function _deleteEvent(type, index) {
  if (!_mapName || index < 0) return;
  try {
    const res = await fetch(
      `/api/map/${encodeURIComponent(_mapName)}/events/${type}/${index}`,
      { method: "DELETE" },
    );
    const data = await res.json();
    if (data.ok) {
      _selectedEvent = null;
      ideEmit(IDE_EVENT_DESELECTED, {});
      await _reloadEvents();
    }
  } catch (_) {}
}

async function _moveEvent(type, index, x, y) {
  if (!_mapName || index < 0) return;
  try {
    const res = await fetch(
      `/api/map/${encodeURIComponent(_mapName)}/events/${type}/${index}/position`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x, y }),
      },
    );
    const data = await res.json();
    if (data.ok) {
      await _reloadEvents();
    }
  } catch (_) {}
}

/** Reload events from the API and redraw. */
async function _reloadEvents() {
  if (!_mapName) return;
  const result = await _loadMapEvents(_mapName);
  if (result) {
    _events = result;
    _preloadSprites();
  }
  _draw();
}

/** Find the 0-based index of an event in its array by matching x, y, and object_id or id. */
function _findEventIndex(arrayKey, eventData) {
  if (!_events) return -1;
  const arr = _events[arrayKey] || [];
  for (let i = 0; i < arr.length; i++) {
    const ev = arr[i];
    if (ev.object_id !== undefined && ev.object_id === eventData.object_id) return i;
    if (ev.id !== undefined && ev.id === eventData.id) return i;
    if (ev.x === eventData.x && ev.y === eventData.y) return i;
  }
  return -1;
}

// ---------------------------------------------------------------------------
// Drag-to-move (Event Mode)
// ---------------------------------------------------------------------------

let _dragging = null;  // { type, index, startX, startY, currentX, currentY }

function _startDrag(hit, tileX, tileY) {
  // Map hit type to API event type and find index
  const typeMap = { npc: "object", warp: "warp", trigger: "coord", sign: "bg" };
  const arrayMap = { npc: "object_events", warp: "warp_events", trigger: "coord_events", sign: "bg_events" };
  const apiType = typeMap[hit.type];
  const index = _findEventIndex(arrayMap[hit.type], hit.data);
  if (!apiType || index < 0) return;

  _dragging = {
    type: apiType,
    hitType: hit.type,
    index,
    data: hit.data,
    startX: hit.data.x,
    startY: hit.data.y,
    currentX: hit.data.x,
    currentY: hit.data.y,
  };
}

// ---------------------------------------------------------------------------
// Stamp placement mode
// ---------------------------------------------------------------------------

function _enterStampPlacement(detail) {
  _stampPending = detail;

  // Change cursor to crosshair
  if (_canvasWrap) _canvasWrap.style.cursor = "crosshair";

  // Show placement banner
  _showStampBanner(detail.stamp?.name || detail.stamp_id || "stamp");

  // Listen for Escape to cancel
  _stampKeyHandler = (e) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      _cancelStampPlacement();
    }
  };
  document.addEventListener("keydown", _stampKeyHandler, true);
}

function _cancelStampPlacement() {
  _stampPending = null;
  _removeStampBanner();

  // Restore cursor based on current mode
  if (_canvasWrap) {
    _canvasWrap.style.cursor = _mode === "events" ? "crosshair" : "grab";
  }

  // Remove key listener
  if (_stampKeyHandler) {
    document.removeEventListener("keydown", _stampKeyHandler, true);
    _stampKeyHandler = null;
  }
}

function _showStampBanner(name) {
  _removeStampBanner();
  if (!_canvasWrap) return;

  const banner = document.createElement("div");
  banner.className = "ide-stamp-banner";

  const text = document.createElement("span");
  text.textContent = "Placing: " + name + " \u2014 click a door tile";
  banner.appendChild(text);

  const hint = document.createElement("span");
  hint.className = "ide-stamp-hint";
  hint.textContent = "Esc to cancel";
  banner.appendChild(hint);

  _canvasWrap.appendChild(banner);
  _stampBanner = banner;
}

function _removeStampBanner() {
  if (_stampBanner) {
    _stampBanner.remove();
    _stampBanner = null;
  }
}

async function _executeStampPlacement(tileX, tileY) {
  if (!_stampPending || !_mapName) return;

  const { stamp_id } = _stampPending;
  const stampName = _stampPending.stamp?.name || stamp_id;

  // Show placing indicator on banner
  if (_stampBanner) {
    const text = _stampBanner.querySelector("span");
    if (text) text.textContent = "Placing " + stampName + " at (" + tileX + ", " + tileY + ")...";
  }

  try {
    const res = await fetch("/api/stamps/place", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        stamp_id: stamp_id,
        parent_map: _mapName,
        door_x: tileX,
        door_y: tileY,
      }),
    });
    const data = await res.json();

    if (data.ok) {
      const createdMap = data.data?.map_name || data.data?.created_map || stampName;
      _cancelStampPlacement();
      _showStampResult(true, "Placed " + createdMap + " at (" + tileX + ", " + tileY + ")");
      // Refresh canvas to show new warp
      await _reloadEvents();
    } else {
      const msg = data.error || data.message || "Placement failed";
      _showStampResult(false, msg);
      // Keep placement mode active so user can try another tile
    }
  } catch (err) {
    _showStampResult(false, "Network error: " + (err.message || "unknown"));
  }
}

function _showStampResult(success, message) {
  if (!_canvasWrap) return;

  // Remove any previous result
  const prev = _canvasWrap.querySelector(".ide-stamp-result");
  if (prev) prev.remove();

  const el = document.createElement("div");
  el.className = "ide-stamp-result" + (success ? " success" : " failure");
  el.textContent = message;
  _canvasWrap.appendChild(el);

  // Auto-dismiss after a few seconds
  setTimeout(() => {
    if (el.parentNode) el.remove();
  }, success ? 4000 : 6000);
}

// ---------------------------------------------------------------------------
// Public: toggle grid (called from toolbar)
// ---------------------------------------------------------------------------

export function toggleGrid() {
  _showGrid = !_showGrid;
  _draw();
  return _showGrid;
}

export function toggleNpcs() { _showNpcs = !_showNpcs; _draw(); return _showNpcs; }
export function toggleWarps() { _showWarps = !_showWarps; _draw(); return _showWarps; }
export function toggleTriggers() { _showTriggers = !_showTriggers; _draw(); return _showTriggers; }
export function toggleSigns() { _showSigns = !_showSigns; _draw(); return _showSigns; }
export function toggleBorders() { _showBorders = !_showBorders; _draw(); return _showBorders; }

/** Toggle dimming of non-script events (warps, triggers, signs, uninvolved NPCs). */
export function setDimNonScriptEvents(dim) { _dimNonScriptEvents = dim; _draw(); }

/** Hide NPC sprites by object_id (script overlay draws them instead). */
export function setHiddenNpcIds(ids) { _hiddenNpcIds = new Set(ids); _draw(); }

/** Clear hidden NPC list. */
export function clearHiddenNpcIds() { _hiddenNpcIds.clear(); _draw(); }

/** Get current camera state for overlay synchronization. */
export function getCamera() { return { panX: _panX, panY: _panY, zoom: _zoom }; }

/** Get the currently loaded map name. */
export function getMapName() { return _mapName; }

/** Get the current event data. */
export function getEvents() { return _events; }
