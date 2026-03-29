/**
 * TORCH IDE — Script Overlay.
 * TORCH_MODULE
 *
 * Transparent canvas + HTML overlay that renders script actors on top of the
 * map canvas. Actors draw at real map coordinates (metatile space). Camera
 * transform is synced with mapCanvas via IDE_CAMERA_CHANGED events.
 *
 * Exports: initScriptOverlay(canvasWrapEl), cleanupScriptOverlay(),
 *          renderOverlay(), setTransform(panX, panY, zoom)
 */

import {
  state, on, off,
  BEAT_CHANGED, FRAMES_UPDATED,
} from "./views/viz/state.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const METATILE_PX = 16; // map canvas tile size — actors at (x*16, y*16)

/** Standing frame indices for 9-frame overworld sprite sheets.
 *  Frames: [up0, up1, up2, down0, down1, down2, left0, left1, left2]
 *  "right" reuses left standing frame with horizontal flip. */
const FACING_FRAME = { down: 4, up: 1, left: 7, right: 7 };

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

let _wrap = null;         // parent #ide-canvas-wrap
let _canvas = null;       // overlay <canvas>
let _ctx = null;
let _dlgEl = null;        // HTML dialogue overlay
let _overlayDiv = null;   // container div for HTML overlays

let _panX = 0;
let _panY = 0;
let _zoom = 2;

let _beatHandler = null;
let _framesHandler = null;
let _resizeObs = null;

// ---------------------------------------------------------------------------
// Init / Cleanup
// ---------------------------------------------------------------------------

export function initScriptOverlay(canvasWrapEl) {
  _wrap = canvasWrapEl;

  // Overlay canvas (transparent, above map canvas)
  _canvas = document.createElement("canvas");
  _canvas.className = "ide-script-overlay-canvas";
  _canvas.style.cssText = "position:absolute;inset:0;pointer-events:none;z-index:5;";
  _wrap.appendChild(_canvas);
  _ctx = _canvas.getContext("2d");

  // HTML overlay container (for dialogue box)
  _overlayDiv = document.createElement("div");
  _overlayDiv.className = "ide-script-overlay-html";
  _overlayDiv.style.cssText = "position:absolute;inset:0;pointer-events:none;z-index:6;overflow:hidden;";
  _wrap.appendChild(_overlayDiv);

  // Dialogue box element
  _dlgEl = document.createElement("div");
  _dlgEl.className = "ide-script-dlg-box";
  _dlgEl.style.display = "none";
  _overlayDiv.appendChild(_dlgEl);

  // Subscribe to viz state changes
  _beatHandler = on(BEAT_CHANGED, () => renderOverlay());
  _framesHandler = on(FRAMES_UPDATED, () => renderOverlay());

  // Resize observer to keep overlay canvas sized correctly
  _resizeObs = new ResizeObserver(() => renderOverlay());
  _resizeObs.observe(_wrap);
}

export function cleanupScriptOverlay() {
  if (_beatHandler) { off(BEAT_CHANGED, _beatHandler); _beatHandler = null; }
  if (_framesHandler) { off(FRAMES_UPDATED, _framesHandler); _framesHandler = null; }
  if (_resizeObs) { _resizeObs.disconnect(); _resizeObs = null; }
  if (_canvas && _canvas.parentNode) _canvas.remove();
  if (_overlayDiv && _overlayDiv.parentNode) _overlayDiv.remove();
  _canvas = null;
  _ctx = null;
  _dlgEl = null;
  _overlayDiv = null;
  _wrap = null;
}

// ---------------------------------------------------------------------------
// Camera sync
// ---------------------------------------------------------------------------

export function setTransform(panX, panY, zoom) {
  _panX = panX;
  _panY = panY;
  _zoom = zoom;
  renderOverlay();
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

export function renderOverlay() {
  if (!_canvas || !_ctx || !_wrap) return;

  const rect = _wrap.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;

  // Size canvas to match container (same as mapCanvas._draw)
  _canvas.width = rect.width * dpr;
  _canvas.height = rect.height * dpr;
  _canvas.style.width = rect.width + "px";
  _canvas.style.height = rect.height + "px";

  _ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  _ctx.clearRect(0, 0, rect.width, rect.height);

  // Get current frame
  const frame = state.frames[state.currentBeat];
  if (!frame || !frame.actors) {
    _dlgEl.style.display = "none";
    return;
  }

  // Apply camera transform (identical to mapCanvas)
  _ctx.save();
  _ctx.translate(_panX, _panY);
  _ctx.scale(_zoom, _zoom);
  _ctx.imageSmoothingEnabled = false;

  const effects = frame.effects || [];

  // Draw fade effect (behind actors)
  _drawFade(effects, rect.width, rect.height);

  // Identify the active actor for this beat (for highlight ring)
  const beat = frame.beat || {};
  const activeActor = beat.data?.actor || null;

  // Draw all actors
  for (const [name, actor] of Object.entries(frame.actors)) {
    if (!actor.visible && actor.visible !== undefined) continue;
    _drawActor(name, actor, effects, name === activeActor);
  }

  _ctx.restore();

  // Update dialogue box (HTML overlay)
  _updateDialogue(frame, rect);
}

// ---------------------------------------------------------------------------
// Actor rendering
// ---------------------------------------------------------------------------

function _drawActor(name, actor, effects, isActive) {
  const px = actor.x * METATILE_PX;
  const py = actor.y * METATILE_PX;

  // Active actor highlight ring
  if (isActive) {
    const r = METATILE_PX * 0.6;
    const cx = px + METATILE_PX / 2;
    const cy = py + METATILE_PX / 2;
    _ctx.save();
    _ctx.strokeStyle = "rgba(212, 160, 23, 0.7)";
    _ctx.lineWidth = 2 / _zoom;
    _ctx.beginPath();
    _ctx.arc(cx, cy, r, 0, Math.PI * 2);
    _ctx.stroke();
    // Soft glow
    _ctx.strokeStyle = "rgba(212, 160, 23, 0.25)";
    _ctx.lineWidth = 4 / _zoom;
    _ctx.beginPath();
    _ctx.arc(cx, cy, r + 1 / _zoom, 0, Math.PI * 2);
    _ctx.stroke();
    _ctx.restore();
  }

  const gfxId = actor.graphics_id || "";
  const spriteImg = state.spriteImages[gfxId];
  const spriteInfo = state.spriteIndex[gfxId];

  if (spriteImg && spriteImg.complete && spriteImg.naturalWidth > 0 && spriteInfo) {
    const sw = spriteInfo.width;
    const sh = spriteInfo.height;
    const frameIdx = FACING_FRAME[actor.facing] || 1;

    // Source rect from sprite sheet
    const sx = frameIdx * sw;
    const sy = 0;
    const flipH = actor.facing === "right";

    // Align sprite bottom with tile bottom (no SCALE — drawing at native metatile size)
    const dy = py - (sh - METATILE_PX);

    _ctx.save();
    if (flipH) {
      _ctx.translate(px + sw, dy);
      _ctx.scale(-1, 1);
      _ctx.drawImage(spriteImg, sx, sy, sw, sh, 0, 0, sw, sh);
    } else {
      _ctx.drawImage(spriteImg, sx, sy, sw, sh, px, dy, sw, sh);
    }
    _ctx.restore();
  } else {
    // Placeholder dot
    const isPlayer = name === "player";
    _ctx.fillStyle = isPlayer ? "#4caf50" : "#2196f3";
    _ctx.beginPath();
    _ctx.arc(px + METATILE_PX / 2, py + METATILE_PX / 2, 4, 0, Math.PI * 2);
    _ctx.fill();
  }

  // Actor name label (scaled to stay readable at any zoom)
  const labelSize = Math.max(6, 8 / _zoom);
  _ctx.save();
  _ctx.fillStyle = "rgba(0,0,0,0.6)";
  _ctx.font = `bold ${labelSize}px monospace`;
  _ctx.textAlign = "center";
  const lx = px + METATILE_PX / 2;
  const ly = py - 3 / _zoom;
  const lw = _ctx.measureText(name).width + 4 / _zoom;
  _ctx.fillRect(lx - lw / 2, ly - labelSize + 1, lw, labelSize + 1);
  _ctx.fillStyle = "rgba(255,255,255,0.9)";
  _ctx.fillText(name, lx, ly);
  _ctx.restore();

  // Emote bubbles
  const emoteEffect = effects.find(e => e.startsWith(`emote:${name}:`));
  if (emoteEffect) {
    _drawEmoteBubble(emoteEffect.split(":")[2], px + METATILE_PX / 2, py - 12 / _zoom);
  }
  const battleEmote = effects.find(e => e === `battle_emote:${name}`);
  if (battleEmote) {
    _drawEmoteBubble("!", px + METATILE_PX / 2, py - 12 / _zoom);
  }
}

// ---------------------------------------------------------------------------
// Emote bubbles
// ---------------------------------------------------------------------------

function _drawEmoteBubble(emoteName, cx, cy) {
  const sym = EMOTE_SYMBOLS[emoteName];
  const text = sym ? sym.text : emoteName;
  const color = sym ? sym.color : "#ffc107";
  const isBold = sym ? sym.bold : false;

  const fontSize = Math.max(6, 9 / _zoom);
  _ctx.font = `${isBold ? "bold " : ""}${fontSize}px monospace`;
  const textW = _ctx.measureText(text).width;
  const bw = Math.max(textW + 6 / _zoom, 14 / _zoom);
  const bh = fontSize + 6 / _zoom;
  const bx = cx - bw / 2;
  const by = cy - bh;
  const r = 3 / _zoom;

  _ctx.save();

  // Background
  _ctx.fillStyle = "#fff";
  _roundRect(_ctx, bx, by, bw, bh, r);
  _ctx.fill();

  // Border
  _ctx.strokeStyle = "rgba(0,0,0,0.15)";
  _ctx.lineWidth = 1 / _zoom;
  _roundRect(_ctx, bx, by, bw, bh, r);
  _ctx.stroke();

  // Pointer
  const pw = 3 / _zoom;
  _ctx.fillStyle = "#fff";
  _ctx.beginPath();
  _ctx.moveTo(cx - pw, by + bh);
  _ctx.lineTo(cx, by + bh + 3 / _zoom);
  _ctx.lineTo(cx + pw, by + bh);
  _ctx.closePath();
  _ctx.fill();

  // Text
  _ctx.fillStyle = color;
  _ctx.textAlign = "center";
  _ctx.textBaseline = "middle";
  _ctx.fillText(text, cx, by + bh / 2);

  _ctx.restore();
}

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
// Fade effects
// ---------------------------------------------------------------------------

function _drawFade(effects, viewW, viewH) {
  const fadeBlack = effects.includes("fade_black");
  const fadeWhite = effects.includes("fade_white");
  const fadeFromBlack = effects.includes("fade_from_black");
  const fadeFromWhite = effects.includes("fade_from_white");

  if (!fadeBlack && !fadeWhite && !fadeFromBlack && !fadeFromWhite) return;

  // Draw fade in screen space (before camera transform is applied — but we're
  // already inside ctx.save/translate/scale, so draw a large rect in world space)
  _ctx.save();
  // Reset transform to draw in screen space
  const dpr = window.devicePixelRatio || 1;
  _ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  if (fadeBlack) {
    _ctx.fillStyle = "rgba(0,0,0,0.7)";
    _ctx.fillRect(0, 0, viewW, viewH);
  } else if (fadeWhite) {
    _ctx.fillStyle = "rgba(255,255,255,0.7)";
    _ctx.fillRect(0, 0, viewW, viewH);
  } else if (fadeFromBlack) {
    _ctx.fillStyle = "rgba(0,0,0,0.3)";
    _ctx.fillRect(0, 0, viewW, viewH);
  } else if (fadeFromWhite) {
    _ctx.fillStyle = "rgba(255,255,255,0.3)";
    _ctx.fillRect(0, 0, viewW, viewH);
  }

  _ctx.restore();
}

// ---------------------------------------------------------------------------
// Dialogue box (HTML overlay)
// ---------------------------------------------------------------------------

function _updateDialogue(frame, viewRect) {
  if (!_dlgEl) return;

  if (!frame.dialogue) {
    _dlgEl.style.display = "none";
    return;
  }

  // Format dialogue text (replace TorScript escapes with real whitespace)
  const cleanText = frame.dialogue
    .replace(/\\p/g, "\n\n")
    .replace(/\\n/g, "\n");
  _dlgEl.textContent = cleanText;
  _dlgEl.style.whiteSpace = "pre-wrap";

  // Position: fixed at bottom center of the canvas area (like the GBA)
  _dlgEl.style.display = "block";
  _dlgEl.style.left = "50%";
  _dlgEl.style.bottom = "12px";
  _dlgEl.style.top = "auto";
  _dlgEl.style.transform = "translate(-50%, 0)";
}
