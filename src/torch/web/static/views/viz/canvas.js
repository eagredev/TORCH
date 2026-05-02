/**
 * canvas.js — Canvas renderer for the Script Editor (visualizer).
 * Draws the scene preview: actors on a grid, dialogue boxes, emote bubbles,
 * fade overlays. Subscribes to state changes and re-renders automatically.
 *
 * Exports: init(canvasEl, overlayEl), cleanup()
 */

import {
  state, on, off, setCameraLocked, setNpcPatrolIndex,
  BEAT_CHANGED, FRAMES_UPDATED, CHAIN_CHANGED, PATROL_MODE_CHANGED,
} from "./state.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TILE = 16;
const SCALE = 2;
const TILE_PX = TILE * SCALE;  // 32px per tile on screen

/** Standing frame indices for 9-frame overworld sprite sheets (horizontal strip).
 *  Frames: [up0, up1, up2, down0, down1, down2, left0, left1, left2]
 *  "right" reuses the left standing frame with horizontal flip. */
const FACING_FRAME = { down: 4, up: 1, left: 7, right: 7 };

/** Facing direction labels (clearer than tiny unicode arrows at small sizes). */
const FACING_ARROWS = { up: "\u2191 N", down: "\u2193 S", left: "\u2190 W", right: "\u2192 E" };

/** Emote symbols rendered inside bubbles. */
const EMOTE_SYMBOLS = {
  "!":     { text: "!", color: "#e53935", bold: true },
  "!!":    { text: "!!", color: "#e53935", bold: true },
  "?":     { text: "?", color: "#1e88e5", bold: true },
  "x":     { text: "\u2716", color: "#e53935", bold: true },
  "heart": { text: "\u2665", color: "#e53935", bold: false },
  "love":  { text: "\u2665", color: "#e53935", bold: false },
  "...":   { text: "\u2026", color: "#666", bold: false },
  "happy": { text: "\u266A", color: "#43a047", bold: false },
  "angry": { text: "\uD83D\uDCA2", color: "#e53935", bold: false },
};

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _canvas = null;
let _ctx = null;
let _overlay = null;  // HTML overlay container for dialogue box
let _dialogueEl = null;

// Grid cache
let _gridCanvas = null;
let _gridKey = "";

// Camera (unlocked mode)
let _panX = 0;
let _panY = 0;
let _zoom = 1.0;
let _dragging = false;
let _dragStartX = 0;
let _dragStartY = 0;
let _dragPanX = 0;
let _dragPanY = 0;

// Viewport (locked mode — computed from actor positions)
let _viewport = { ox: 0, oy: 0 };

// Hover animation
let _hoverActor = null;
let _hoverAnimTimer = null;
let _hoverAnimFrame = 0;  // alternates 0/1 for walking frames
let _actorRects = [];  // [{name, x, y, w, h}, ...] for hit-testing

// Event handler references (for cleanup)
let _beatHandler = null;
let _framesHandler = null;
let _chainHandler = null;
let _patrolHandler = null;
let _resizeObserver = null;
let _boundMouseDown = null;
let _boundMouseMove = null;
let _boundMouseUp = null;
let _boundWheel = null;
let _boundClick = null;
let _boundCanvasMouseMove = null;
let _boundCanvasMouseLeave = null;

// ---------------------------------------------------------------------------
// init / cleanup
// ---------------------------------------------------------------------------

export function init(canvasEl, overlayEl) {
  _canvas = canvasEl;
  _ctx = canvasEl.getContext("2d");
  _overlay = overlayEl;

  // Create dialogue box element
  _dialogueEl = document.createElement("div");
  _dialogueEl.className = "viz-dialogue-box";
  _dialogueEl.innerHTML = '<div class="viz-dialogue-text"></div>';
  _dialogueEl.style.display = "none";
  _overlay.appendChild(_dialogueEl);

  // Subscribe to state events
  _beatHandler = on(BEAT_CHANGED, () => _renderFrame());
  _framesHandler = on(FRAMES_UPDATED, () => {
    _viewport = _computeViewport(state.frames);
    _invalidateGrid();
    _renderFrame();
  });
  _chainHandler = on(CHAIN_CHANGED, () => _renderFrame());
  _patrolHandler = on(PATROL_MODE_CHANGED, () => _renderFrame());

  // Mouse handlers
  _boundClick = e => _onCanvasClick(e);
  _boundMouseDown = e => _onMouseDown(e);
  _boundMouseMove = e => _onMouseMove(e);
  _boundMouseUp = () => _onMouseUp();
  _boundWheel = e => _onWheel(e);
  _boundCanvasMouseMove = e => _onCanvasHoverMove(e);
  _boundCanvasMouseLeave = () => _onCanvasHoverLeave();

  _canvas.addEventListener("click", _boundClick);
  _canvas.addEventListener("mousedown", _boundMouseDown);
  document.addEventListener("mousemove", _boundMouseMove);
  document.addEventListener("mouseup", _boundMouseUp);
  _canvas.addEventListener("wheel", _boundWheel, { passive: false });
  _canvas.addEventListener("mousemove", _boundCanvasMouseMove);
  _canvas.addEventListener("mouseleave", _boundCanvasMouseLeave);

  // Resize observer
  _resizeObserver = new ResizeObserver(() => {
    _invalidateGrid();
    _renderFrame();
  });
  const parent = _canvas.parentElement;
  if (parent) _resizeObserver.observe(parent);

  // Compute viewport and render
  _viewport = _computeViewport(state.frames);
  _renderFrame();
}

export function cleanup() {
  if (_beatHandler) { off(BEAT_CHANGED, _beatHandler); _beatHandler = null; }
  if (_framesHandler) { off(FRAMES_UPDATED, _framesHandler); _framesHandler = null; }
  if (_chainHandler) { off(CHAIN_CHANGED, _chainHandler); _chainHandler = null; }
  if (_patrolHandler) { off(PATROL_MODE_CHANGED, _patrolHandler); _patrolHandler = null; }

  if (_canvas) {
    _canvas.removeEventListener("click", _boundClick);
    _canvas.removeEventListener("mousedown", _boundMouseDown);
    _canvas.removeEventListener("wheel", _boundWheel);
    _canvas.removeEventListener("mousemove", _boundCanvasMouseMove);
    _canvas.removeEventListener("mouseleave", _boundCanvasMouseLeave);
  }
  document.removeEventListener("mousemove", _boundMouseMove);
  document.removeEventListener("mouseup", _boundMouseUp);

  if (_resizeObserver) { _resizeObserver.disconnect(); _resizeObserver = null; }
  if (_hoverAnimTimer) { clearInterval(_hoverAnimTimer); _hoverAnimTimer = null; }

  if (_dialogueEl && _dialogueEl.parentElement) {
    _dialogueEl.parentElement.removeChild(_dialogueEl);
  }

  _canvas = null;
  _ctx = null;
  _overlay = null;
  _dialogueEl = null;
  _gridCanvas = null;
  _gridKey = "";
  _hoverActor = null;
  _actorRects = [];
}

// ---------------------------------------------------------------------------
// Viewport computation
// ---------------------------------------------------------------------------

function _computeViewport(frames) {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const f of frames) {
    for (const a of Object.values(f.actors || {})) {
      if (a.x < minX) minX = a.x;
      if (a.x > maxX) maxX = a.x;
      if (a.y < minY) minY = a.y;
      if (a.y > maxY) maxY = a.y;
    }
  }
  if (!isFinite(minX)) return { ox: 0, oy: 0, zoom: 1.0 };

  const pad = 3; // tiles of padding around actors
  const cw = _canvas ? _canvas.width : 600;
  const ch = _canvas ? _canvas.height : 400;

  // World-space bounding box in pixels (with padding)
  const worldW = (maxX - minX + 1 + pad * 2) * TILE_PX;
  const worldH = (maxY - minY + 1 + pad * 2) * TILE_PX;

  // Auto-zoom to fit all actors, capped at 1.0 (never zoom in past native)
  const zoom = Math.min(1.0, cw / worldW, ch / worldH);

  // Centre of actor bounding box in world pixels
  const midWorldX = ((minX + maxX) / 2 + 0.5) * TILE_PX;
  const midWorldY = ((minY + maxY) / 2 + 0.5) * TILE_PX;

  // Render contract: screen_pos = zoom * actorWorld - ox
  // To centre: zoom * midWorld - ox = cw/2  =>  ox = zoom * midWorld - cw/2
  const ox = zoom * midWorldX - cw / 2;
  const oy = zoom * midWorldY - ch / 2;

  return { ox, oy, zoom };
}

function _getEffectiveOffset() {
  if (state.cameraLocked) {
    return { ox: _viewport.ox, oy: _viewport.oy, zoom: _viewport.zoom || 1.0 };
  }
  return { ox: -_panX, oy: -_panY, zoom: _zoom };
}

// ---------------------------------------------------------------------------
// Grid cache
// ---------------------------------------------------------------------------

function _invalidateGrid() {
  _gridCanvas = null;
  _gridKey = "";
}

function _ensureGrid(w, h, ox, oy) {
  const key = `${w},${h},${ox},${oy}`;
  if (key === _gridKey && _gridCanvas) return _gridCanvas;

  _gridCanvas = document.createElement("canvas");
  _gridCanvas.width = w;
  _gridCanvas.height = h;
  const gc = _gridCanvas.getContext("2d");

  gc.fillStyle = "#1a1a2e";
  gc.fillRect(0, 0, w, h);

  gc.strokeStyle = "rgba(255,255,255,0.05)";
  gc.lineWidth = 1;
  const startX = -(ox % TILE_PX);
  const startY = -(oy % TILE_PX);
  for (let x = startX; x < w; x += TILE_PX) {
    gc.beginPath(); gc.moveTo(x, 0); gc.lineTo(x, h); gc.stroke();
  }
  for (let y = startY; y < h; y += TILE_PX) {
    gc.beginPath(); gc.moveTo(0, y); gc.lineTo(w, y); gc.stroke();
  }

  _gridKey = key;
  return _gridCanvas;
}

// ---------------------------------------------------------------------------
// Main render
// ---------------------------------------------------------------------------

function _renderFrame() {
  if (!_canvas || !_ctx) return;

  const ctx = _ctx;

  if (state.frames.length === 0) {
    _fitCanvasToParent();
    ctx.clearRect(0, 0, _canvas.width, _canvas.height);
    ctx.fillStyle = "#1a1a2e";
    ctx.fillRect(0, 0, _canvas.width, _canvas.height);
    ctx.fillStyle = "rgba(255,255,255,0.3)";
    ctx.font = "14px monospace";
    ctx.textAlign = "center";
    ctx.fillText("No beats", _canvas.width / 2, _canvas.height / 2);
    _drawLockIcon(ctx, _canvas.width);
    _updateDialogue(null);
    return;
  }

  const frame = state.frames[state.currentBeat];
  if (!frame) return;

  _fitCanvasToParent();

  const actors = frame.actors || {};
  const dialogue = frame.dialogue;
  const effects = frame.effects || [];

  const cam = _getEffectiveOffset();
  const ox = cam.ox;
  const oy = cam.oy;
  const z = cam.zoom;

  // Draw grid background
  if (z === 1.0) {
    const grid = _ensureGrid(_canvas.width, _canvas.height, ox, oy);
    ctx.drawImage(grid, 0, 0);
  } else {
    ctx.fillStyle = "#1a1a2e";
    ctx.fillRect(0, 0, _canvas.width, _canvas.height);
    ctx.save();
    ctx.scale(z, z);
    const effOx = ox / z;
    const effOy = oy / z;
    ctx.strokeStyle = "rgba(255,255,255,0.05)";
    const startX = -(effOx % TILE_PX);
    const startY = -(effOy % TILE_PX);
    const vw = _canvas.width / z;
    const vh = _canvas.height / z;
    for (let x = startX; x < vw; x += TILE_PX) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, vh); ctx.stroke();
    }
    for (let y = startY; y < vh; y += TILE_PX) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(vw, y); ctx.stroke();
    }
    ctx.restore();
  }

  // Fade effects (drawn over grid, under actors for "to" fades)
  const hasFadeToBlack = effects.some(e => e === "fade_black" || e === "fade_to_black");
  const hasFadeToWhite = effects.some(e => e === "fade_white" || e === "fade_to_white");
  const hasFadeFromBlack = effects.some(e => e === "from_black" || e === "fade_from_black");
  const hasFadeFromWhite = effects.some(e => e === "from_white" || e === "fade_from_white");

  if (hasFadeToBlack) {
    ctx.fillStyle = "rgba(0,0,0,0.85)";
    ctx.fillRect(0, 0, _canvas.width, _canvas.height);
  } else if (hasFadeToWhite) {
    ctx.fillStyle = "rgba(255,255,255,0.85)";
    ctx.fillRect(0, 0, _canvas.width, _canvas.height);
  } else if (hasFadeFromBlack) {
    ctx.fillStyle = "rgba(0,0,0,0.3)";
    ctx.fillRect(0, 0, _canvas.width, _canvas.height);
  } else if (hasFadeFromWhite) {
    ctx.fillStyle = "rgba(255,255,255,0.3)";
    ctx.fillRect(0, 0, _canvas.width, _canvas.height);
  }

  // Draw chain position ranges (before actors, so actors render on top)
  _drawChainRanges(ctx, ox, oy, z);

  // Draw patrol position tiles when patrol mode is active
  if (state.patrolMode) {
    _drawPatrolTiles(ctx, ox, oy, z);
  }

  // Draw actors
  _actorRects = [];
  ctx.save();
  if (z !== 1.0) ctx.scale(z, z);
  const azOx = z === 1.0 ? ox : ox / z;
  const azOy = z === 1.0 ? oy : oy / z;

  for (const [name, actorState] of Object.entries(actors)) {
    if (!actorState.visible) continue;
    const px = actorState.x * TILE_PX - azOx;
    const py = actorState.y * TILE_PX - azOy;

    // Draw manual override pin icon
    if (state.chainName && _hasManualOverride(name)) {
      _drawOverridePin(ctx, px, py);
    }

    _drawActor(ctx, name, actorState, px, py, z, effects);
  }
  ctx.restore();

  // Lock icon (always on top, unscaled)
  _drawLockIcon(ctx, _canvas.width);

  // Dialogue box (HTML overlay)
  _updateDialogue(dialogue);
}

// ---------------------------------------------------------------------------
// Canvas sizing
// ---------------------------------------------------------------------------

function _fitCanvasToParent() {
  const parent = _canvas.parentElement;
  if (!parent) return;
  const newW = parent.clientWidth;
  const newH = parent.clientHeight - 50;  // leave room for transport bar
  if (_canvas.width !== newW || _canvas.height !== newH) {
    _canvas.width = newW;
    _canvas.height = newH;
    _invalidateGrid();
  }
}

// ---------------------------------------------------------------------------
// Actor rendering
// ---------------------------------------------------------------------------

function _drawActor(ctx, name, actorState, px, py, zoom, effects) {
  const gfxId = actorState.graphics_id || "";
  const spriteImg = state.spriteImages[gfxId];
  const spriteInfo = state.spriteIndex[gfxId];

  if (spriteImg && spriteImg.complete && spriteImg.naturalWidth > 0 && spriteInfo) {
    const sw = spriteInfo.width;
    const sh = spriteInfo.height;
    let frameIdx = FACING_FRAME[actorState.facing] || 1;

    // Hover animation: alternate walking frames (frames are in groups of 3: walk1, stand, walk2)
    if (_hoverActor === name) {
      const group = Math.floor(frameIdx / 3) * 3;
      frameIdx = group + (_hoverAnimFrame === 0 ? 0 : 2);
    }

    // Source rect from sprite sheet (horizontal strip: N frames × 1 row)
    const sx = frameIdx * sw;
    const sy = 0;
    const flipH = actorState.facing === "right";

    // Destination Y offset: align sprite bottom with tile bottom
    const dy = py - (sh * SCALE - TILE_PX);

    ctx.save();
    if (flipH) {
      ctx.translate(px + sw * SCALE, dy);
      ctx.scale(-1, 1);
      ctx.drawImage(spriteImg, sx, sy, sw, sh, 0, 0, sw * SCALE, sh * SCALE);
    } else {
      ctx.drawImage(spriteImg, sx, sy, sw, sh, px, dy, sw * SCALE, sh * SCALE);
    }
    ctx.restore();

    // Track actor rect for hover hit-testing (in canvas coordinates, pre-zoom)
    _actorRects.push({
      name,
      x: px * zoom,
      y: dy * zoom,
      w: sw * SCALE * zoom,
      h: sh * SCALE * zoom,
    });
  } else {
    // Placeholder rectangle
    const isPlayer = name === "player";
    ctx.fillStyle = isPlayer ? "#4caf50" : "#2196f3";
    ctx.fillRect(px + 4, py + 4, TILE_PX - 8, TILE_PX - 8);

    _actorRects.push({
      name,
      x: (px + 4) * zoom,
      y: (py + 4) * zoom,
      w: (TILE_PX - 8) * zoom,
      h: (TILE_PX - 8) * zoom,
    });
  }

  // Actor label (above sprite)
  ctx.save();
  ctx.fillStyle = "rgba(0,0,0,0.5)";
  ctx.font = "bold 11px monospace";
  ctx.textAlign = "center";
  const labelX = px + TILE_PX / 2;
  const labelY = py - 6;
  const labelW = ctx.measureText(name).width + 6;
  ctx.fillRect(labelX - labelW / 2, labelY - 9, labelW, 12);
  ctx.fillStyle = "rgba(255,255,255,0.9)";
  ctx.fillText(name, labelX, labelY);
  ctx.restore();

  // Coordinate label below feet
  ctx.save();
  ctx.fillStyle = "rgba(255,255,255,0.4)";
  ctx.font = "9px monospace";
  ctx.textAlign = "center";
  ctx.fillText(`(${actorState.x}, ${actorState.y})`, px + TILE_PX / 2, py + TILE_PX + 10);
  ctx.restore();

  // Emote bubble (from emote beats)
  const emoteEffect = effects.find(e => e.startsWith(`emote:${name}:`));
  if (emoteEffect) {
    const emoteName = emoteEffect.split(":")[2];
    _drawEmoteBubble(ctx, emoteName, px + TILE_PX / 2, py - 24);
  }

  // Battle emote — show ! over the NPC triggering the battle
  const battleEmote = effects.find(e => e === `battle_emote:${name}`);
  if (battleEmote) {
    _drawEmoteBubble(ctx, "!", px + TILE_PX / 2, py - 24);
  }
}

// ---------------------------------------------------------------------------
// Emote bubbles
// ---------------------------------------------------------------------------

function _drawEmoteBubble(ctx, emoteName, cx, cy) {
  const sym = EMOTE_SYMBOLS[emoteName];
  const text = sym ? sym.text : emoteName;
  const color = sym ? sym.color : "#ffc107";
  const isBold = sym ? sym.bold : false;

  // Measure text for bubble sizing
  ctx.font = `${isBold ? "bold " : ""}13px monospace`;
  const textW = ctx.measureText(text).width;
  const bubbleW = Math.max(textW + 12, 24);
  const bubbleH = 20;
  const bx = cx - bubbleW / 2;
  const by = cy - bubbleH;

  ctx.save();

  // Bubble shadow
  ctx.fillStyle = "rgba(0,0,0,0.2)";
  _roundRect(ctx, bx + 2, by + 2, bubbleW, bubbleH, 6);
  ctx.fill();

  // Bubble background
  ctx.fillStyle = "#fff";
  _roundRect(ctx, bx, by, bubbleW, bubbleH, 6);
  ctx.fill();

  // Bubble border
  ctx.strokeStyle = "rgba(0,0,0,0.15)";
  ctx.lineWidth = 1;
  _roundRect(ctx, bx, by, bubbleW, bubbleH, 6);
  ctx.stroke();

  // Pointer triangle
  ctx.fillStyle = "#fff";
  ctx.beginPath();
  ctx.moveTo(cx - 4, by + bubbleH);
  ctx.lineTo(cx, by + bubbleH + 5);
  ctx.lineTo(cx + 4, by + bubbleH);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = "rgba(0,0,0,0.15)";
  ctx.stroke();

  // Cover the pointer's top edge where it meets the bubble
  ctx.fillStyle = "#fff";
  ctx.fillRect(cx - 3, by + bubbleH - 1, 6, 2);

  // Emote text
  ctx.fillStyle = color;
  ctx.font = `${isBold ? "bold " : ""}13px monospace`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, cx, by + bubbleH / 2);

  ctx.restore();
}

/** Draw a rounded rectangle path (compatible with browsers lacking ctx.roundRect). */
function _roundRect(ctx, x, y, w, h, r) {
  if (ctx.roundRect) {
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, r);
  } else {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.arcTo(x + w, y, x + w, y + r, r);
    ctx.lineTo(x + w, y + h - r);
    ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
    ctx.lineTo(x + r, y + h);
    ctx.arcTo(x, y + h, x, y + h - r, r);
    ctx.lineTo(x, y + r);
    ctx.arcTo(x, y, x + r, y, r);
    ctx.closePath();
  }
}

// ---------------------------------------------------------------------------
// Patrol tile rendering (NPC starting position picker)
// ---------------------------------------------------------------------------

function _drawPatrolTiles(ctx, ox, oy, zoom) {
  const ti = state.triggerInfo;
  if (!ti || !ti.npc_positions || ti.npc_positions.length <= 1) return;

  const positions = ti.npc_positions;
  const selectedIdx = state.npcPatrolIndex || 0;

  ctx.save();
  if (zoom !== 1.0) ctx.scale(zoom, zoom);
  const azOx = zoom === 1.0 ? ox : ox / zoom;
  const azOy = zoom === 1.0 ? oy : oy / zoom;

  for (let i = 0; i < positions.length; i++) {
    const pos = positions[i];
    const sx = pos.x * TILE_PX - azOx;
    const sy = pos.y * TILE_PX - azOy;

    if (i === selectedIdx) {
      ctx.fillStyle = "rgba(212, 160, 23, 0.45)";
      ctx.strokeStyle = "rgba(212, 160, 23, 0.9)";
      ctx.lineWidth = 2;
    } else {
      ctx.fillStyle = "rgba(137, 180, 250, 0.25)";
      ctx.strokeStyle = "rgba(137, 180, 250, 0.6)";
      ctx.lineWidth = 1;
    }
    ctx.fillRect(sx, sy, TILE_PX, TILE_PX);
    ctx.strokeRect(sx, sy, TILE_PX, TILE_PX);
  }
  ctx.restore();
}


// ---------------------------------------------------------------------------
// Chain position range rendering
// ---------------------------------------------------------------------------

/**
 * Draw translucent tile strips showing chain-calculated position ranges.
 * Teal for auto-calculated, gold for manual overrides.
 * Only renders when chain mode is active.
 */
function _drawChainRanges(ctx, ox, oy, zoom) {
  if (!state.chainName || !state.chainData) return;

  const seg = state.chainSegment;
  if (!seg) return;

  const output = seg.output || {};
  const actors = output.actors || {};
  const overrides = (state.chainData.manual_overrides || {})[state.scriptName] || {};
  const actorOverrides = overrides.actors || {};

  ctx.save();
  if (zoom !== 1.0) ctx.scale(zoom, zoom);
  const azOx = zoom === 1.0 ? ox : ox / zoom;
  const azOy = zoom === 1.0 ? oy : oy / zoom;

  for (const [name, data] of Object.entries(actors)) {
    const xVal = data.x;
    const yVal = data.y;
    const hasOverride = name in actorOverrides;

    // Only render if there's actually a range
    const xIsRange = Array.isArray(xVal) && xVal.length === 2 && xVal[0] !== xVal[1];
    const yIsRange = Array.isArray(yVal) && yVal.length === 2 && yVal[0] !== yVal[1];

    if (!xIsRange && !yIsRange) continue;

    // Choose color based on override status
    const color = hasOverride ? "rgba(212, 160, 23, 0.2)" : "rgba(0, 188, 212, 0.2)";
    const borderColor = hasOverride ? "rgba(212, 160, 23, 0.5)" : "rgba(0, 188, 212, 0.4)";

    ctx.fillStyle = color;
    ctx.strokeStyle = borderColor;
    ctx.lineWidth = 1;

    if (xIsRange) {
      // Horizontal range strip
      const x1 = xVal[0] * TILE_PX - azOx;
      const x2 = (xVal[1] + 1) * TILE_PX - azOx;
      const fixedY = Array.isArray(yVal) ? yVal[0] : (yVal || 0);
      const y = fixedY * TILE_PX - azOy;
      ctx.fillRect(x1, y, x2 - x1, TILE_PX);
      ctx.strokeRect(x1, y, x2 - x1, TILE_PX);
    }

    if (yIsRange) {
      // Vertical range strip
      const fixedX = Array.isArray(xVal) ? xVal[0] : (xVal || 0);
      const x = fixedX * TILE_PX - azOx;
      const y1 = yVal[0] * TILE_PX - azOy;
      const y2 = (yVal[1] + 1) * TILE_PX - azOy;
      ctx.fillRect(x, y1, TILE_PX, y2 - y1);
      ctx.strokeRect(x, y1, TILE_PX, y2 - y1);
    }
  }

  ctx.restore();
}

/**
 * Check if an actor has a manual override in the current chain.
 */
function _hasManualOverride(actorName) {
  if (!state.chainData) return false;
  const overrides = (state.chainData.manual_overrides || {})[state.scriptName] || {};
  return actorName in (overrides.actors || {});
}

/**
 * Draw a small pin icon above an actor with manual overrides.
 */
function _drawOverridePin(ctx, px, py) {
  ctx.save();
  ctx.fillStyle = "rgba(212, 160, 23, 0.9)";
  ctx.font = "bold 10px monospace";
  ctx.textAlign = "center";
  // Pin icon above the actor label area
  ctx.fillText("\u{1F4CC}", px + TILE_PX / 2, py - 20);
  ctx.restore();
}

// ---------------------------------------------------------------------------
// Dialogue box (HTML overlay)
// ---------------------------------------------------------------------------

function _updateDialogue(dialogue) {
  if (!_dialogueEl) return;
  const textEl = _dialogueEl.querySelector(".viz-dialogue-text");

  const rawText = typeof dialogue === "string" ? dialogue : (dialogue && dialogue.text);
  if (rawText) {
    let text = rawText;
    // Strip trailing $
    if (text.endsWith("$")) text = text.slice(0, -1);
    // Escape HTML
    text = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    // Convert Pokeemerald text control codes
    text = text.replace(/\\p/g, "<br><br>");
    text = text.replace(/\\n/g, "<br>");
    textEl.innerHTML = text;
    _dialogueEl.style.display = "block";
  } else {
    textEl.innerHTML = "";
    _dialogueEl.style.display = "none";
  }
}

// ---------------------------------------------------------------------------
// Lock icon
// ---------------------------------------------------------------------------

function _drawLockIcon(ctx, canvasWidth) {
  const size = 20;
  const x = canvasWidth - size - 8;
  const y = 8;

  ctx.save();
  ctx.fillStyle = "rgba(0,0,0,0.5)";
  ctx.fillRect(x, y, size, size);
  ctx.fillStyle = state.cameraLocked ? "rgba(255,200,0,0.9)" : "rgba(150,150,150,0.7)";
  ctx.font = "14px monospace";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(state.cameraLocked ? "L" : "U", x + size / 2, y + size / 2);
  ctx.restore();
}

// ---------------------------------------------------------------------------
// Camera: click, pan, zoom
// ---------------------------------------------------------------------------

function _onCanvasClick(e) {
  const rect = _canvas.getBoundingClientRect();
  const cx = e.clientX - rect.left;
  const cy = e.clientY - rect.top;

  // Lock icon hit test
  const size = 20;
  const ix = _canvas.width - size - 8;
  const iy = 8;
  if (cx >= ix && cx <= ix + size && cy >= iy && cy <= iy + size) {
    if (state.cameraLocked) {
      setCameraLocked(false);
      _panX = -_viewport.ox;
      _panY = -_viewport.oy;
      _zoom = 1.0;
    } else {
      setCameraLocked(true);
      _panX = 0;
      _panY = 0;
      _zoom = 1.0;
      _invalidateGrid();
    }
    _renderFrame();
    return;
  }

  // Patrol tile click detection
  if (state.patrolMode && state.triggerInfo && state.triggerInfo.npc_positions) {
    const positions = state.triggerInfo.npc_positions;
    const z = _zoom;
    const rawOx = state.cameraLocked ? _viewport.ox : -_panX;
    const rawOy = state.cameraLocked ? _viewport.oy : -_panY;
    // Convert click position to world tile coordinates
    const worldX = cx / z + rawOx;
    const worldY = cy / z + rawOy;
    const tileX = Math.floor(worldX / TILE_PX);
    const tileY = Math.floor(worldY / TILE_PX);
    for (let i = 0; i < positions.length; i++) {
      if (positions[i].x === tileX && positions[i].y === tileY) {
        setNpcPatrolIndex(i);
        return;
      }
    }
  }
}

function _onMouseDown(e) {
  if (state.cameraLocked) return;
  const rect = _canvas.getBoundingClientRect();
  const cx = e.clientX - rect.left;
  const cy = e.clientY - rect.top;

  // Skip if clicking lock icon
  const size = 20;
  const ix = _canvas.width - size - 8;
  if (cx >= ix && cx <= ix + size && cy >= 8 && cy <= 8 + size) return;

  _dragging = true;
  _dragStartX = e.clientX;
  _dragStartY = e.clientY;
  _dragPanX = _panX;
  _dragPanY = _panY;
  _canvas.style.cursor = "grabbing";
}

function _onMouseMove(e) {
  if (!_dragging) return;
  _panX = _dragPanX + (e.clientX - _dragStartX);
  _panY = _dragPanY + (e.clientY - _dragStartY);
  _invalidateGrid();
  _renderFrame();
}

function _onMouseUp() {
  if (_dragging) {
    _dragging = false;
    if (_canvas) _canvas.style.cursor = "";
  }
}

function _onWheel(e) {
  if (state.cameraLocked) return;
  e.preventDefault();

  const rect = _canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;

  const oldZoom = _zoom;
  const delta = e.deltaY > 0 ? 0.9 : 1.1;
  _zoom = Math.max(0.5, Math.min(3.0, _zoom * delta));

  // Zoom toward mouse position
  _panX = mx - (_zoom / oldZoom) * (mx - _panX);
  _panY = my - (_zoom / oldZoom) * (my - _panY);

  _invalidateGrid();
  _renderFrame();
}

// ---------------------------------------------------------------------------
// Hover animation
// ---------------------------------------------------------------------------

function _onCanvasHoverMove(e) {
  const rect = _canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;

  // Hit test against actor rects
  let found = null;
  for (const ar of _actorRects) {
    if (mx >= ar.x && mx <= ar.x + ar.w && my >= ar.y && my <= ar.y + ar.h) {
      found = ar.name;
      break;
    }
  }

  if (found === _hoverActor) return;

  if (_hoverAnimTimer) {
    clearInterval(_hoverAnimTimer);
    _hoverAnimTimer = null;
  }

  _hoverActor = found;
  _hoverAnimFrame = 0;

  if (found) {
    _hoverAnimTimer = setInterval(() => {
      _hoverAnimFrame = _hoverAnimFrame === 0 ? 1 : 0;
      _renderFrame();
    }, 300);
  } else {
    _renderFrame();  // re-render to clear animation frame
  }
}

function _onCanvasHoverLeave() {
  if (_hoverAnimTimer) {
    clearInterval(_hoverAnimTimer);
    _hoverAnimTimer = null;
  }
  if (_hoverActor) {
    _hoverActor = null;
    _hoverAnimFrame = 0;
    _renderFrame();
  }
}
