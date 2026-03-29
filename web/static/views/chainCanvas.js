/**
 * chainCanvas.js — Lightweight canvas for the Chain Builder.
 *
 * Renders NPC positions, sight lines, and approach tiles for a chain segment.
 * Simplified version of the full viz canvas — no animation, no dialogue,
 * no camera controls. Just positions, trigger visualisation, and range tiles.
 *
 * Rendering rules:
 *   Head segment:
 *     - NPC sprite at fixed origin + facing arrow
 *     - Sight/talk trigger tiles (potential player positions)
 *     - No player sprite, no output actor sprites
 *   Subsequent segments:
 *     - Ranged actors → highlighted range tiles + label (no sprite)
 *     - Fixed actors → sprite at position
 *     - Introduced actors → sprite at fixed position
 *     - Anchor actors not in output → sprite at map.json position
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TILE = 16;
const SCALE = 2;
const TILE_PX = TILE * SCALE;

const COLORS = {
  background: "#1a1a2e",
  grid: "rgba(255,255,255,0.05)",
  sightLine: "rgba(0, 188, 212, 0.25)",
  sightBorder: "rgba(0, 188, 212, 0.5)",
  approachEnabled: "rgba(76, 175, 80, 0.3)",
  approachDisabled: "rgba(244, 67, 54, 0.15)",
  approachBorder: "rgba(76, 175, 80, 0.6)",
  approachDisabledBorder: "rgba(244, 67, 54, 0.4)",
  player: "#4caf50",
  npc: "#2196f3",
  fixedActor: "#2196f3",
  actorLabel: "rgba(0,0,0,0.6)",
  labelText: "rgba(255,255,255,0.9)",
  range: "rgba(0, 188, 212, 0.2)",
  rangeBorder: "rgba(0, 188, 212, 0.4)",
  rangeLabel: "rgba(0, 188, 212, 0.8)",
  override: "rgba(212, 160, 23, 0.3)",
  overrideBorder: "rgba(212, 160, 23, 0.6)",
  facingArrow: "rgba(255, 255, 255, 0.85)",
  triggerTile: "rgba(76, 175, 80, 0.25)",
  triggerBorder: "rgba(76, 175, 80, 0.5)",
};

// ---------------------------------------------------------------------------
// Pan / zoom state
// ---------------------------------------------------------------------------

let _panX = 0;
let _panY = 0;
let _dragging = false;
let _dragStartX = 0;
let _dragStartY = 0;
let _dragPanX = 0;
let _dragPanY = 0;
let _didDrag = false;  // true if mouse moved during drag (suppresses click)

// CSS-to-drawing-pixel ratio (set each render)
let _cssToDraw = 1;

// Cached render args for re-render during pan/zoom
let _lastCanvas = null;
let _lastSegmentData = null;
let _lastChainData = null;
let _lastScriptName = "";
let _lastSpriteImages = null;

// ---------------------------------------------------------------------------
// Hit regions (stored after each render for click detection)
// ---------------------------------------------------------------------------

let _lastCardinalRegions = [];  // [{label, x, y, excluded}, ...]
let _lastSightRegions = [];     // [{distance, x, y, excluded}, ...]
let _lastApproachRegions = [];  // [{index, x, y, enabled, facing}, ...]
let _lastViewportOx = 0;
let _lastViewportOy = 0;

/**
 * Return the cardinal tile hit regions from the last render.
 * Each entry: {label: "N"|"E"|"S"|"W", x, y, excluded}
 * x, y are world tile coordinates (integers).
 */
export function getCardinalRegions() {
  return _lastCardinalRegions;
}

/**
 * Return the approach tile hit regions from the last render (talk triggers).
 * Each entry: {index, x, y, enabled, facing}
 */
export function getApproachRegions() {
  return _lastApproachRegions;
}

/**
 * Return the sight corridor tile hit regions from the last render.
 * Each entry: {distance: int, x, y, excluded}
 */
export function getSightRegions() {
  return _lastSightRegions;
}

/** True if the last mousedown→mouseup was a drag, not a click. */
export function wasDrag() {
  return _didDrag;
}

/**
 * Convert a CSS click position (relative to canvas element) to a
 * world tile coordinate, inverting pan/zoom and viewport transforms.
 *
 * @param {HTMLCanvasElement} canvas
 * @param {number} cssX - click X relative to canvas element
 * @param {number} cssY - click Y relative to canvas element
 * @returns {{tx: number, ty: number}} world tile coordinates (integers)
 */
export function cssToTile(canvas, cssX, cssY) {
  const rect = canvas.getBoundingClientRect();
  const c2c = rect.width > 0 ? canvas.width / rect.width : 1;
  // CSS → canvas pixels (= drawing pixels, no canvas transform)
  const drawX = cssX * c2c;
  const drawY = cssY * c2c;
  // Drawing coords → world tile: drawCoord = tileCoord * TILE_PX - viewport.ox
  const tx = Math.floor((drawX + _lastViewportOx) / TILE_PX);
  const ty = Math.floor((drawY + _lastViewportOy) / TILE_PX);
  return { tx, ty };
}

/**
 * Wire pan/zoom mouse handlers onto a canvas. Call once per canvas element.
 * Resets pan/zoom to default on each call.
 */
export function initInteraction(canvas) {
  _panX = 0;
  _panY = 0;
  _dragging = false;
  _didDrag = false;

  canvas.addEventListener("mousedown", _onMouseDown);
  canvas.addEventListener("mousemove", _onMouseMove);
  canvas.addEventListener("mouseup", _onMouseUp);
  canvas.addEventListener("mouseleave", _onMouseUp);
  canvas.style.cursor = "grab";
}

function _onMouseDown(e) {
  _dragging = true;
  _didDrag = false;
  _dragStartX = e.clientX;
  _dragStartY = e.clientY;
  _dragPanX = _panX;
  _dragPanY = _panY;
  e.currentTarget.style.cursor = "grabbing";
}

function _onMouseMove(e) {
  if (_dragging) {
    const dx = e.clientX - _dragStartX;
    const dy = e.clientY - _dragStartY;
    if (!_didDrag && Math.abs(dx) <= 4 && Math.abs(dy) <= 4) return;
    _didDrag = true;
    _panX = _dragPanX + dx;
    _panY = _dragPanY + dy;
    _rerender();
    return;
  }
  // Hover: change cursor to pointer over clickable trigger tiles
  const canvas = e.currentTarget;
  const rect = canvas.getBoundingClientRect();
  const tile = cssToTile(canvas, e.clientX - rect.left, e.clientY - rect.top);
  const onSight = _lastSightRegions.some(r => r.x === tile.tx && r.y === tile.ty);
  const onCardinal = _lastCardinalRegions.some(r => r.x === tile.tx && r.y === tile.ty);
  const onApproach = _lastApproachRegions.some(r => r.x === tile.tx && r.y === tile.ty);
  canvas.style.cursor = (onSight || onCardinal || onApproach) ? "pointer" : "grab";
}

function _onMouseUp(e) {
  if (_dragging) {
    _dragging = false;
    if (e.currentTarget) e.currentTarget.style.cursor = "grab";
  }
}

function _rerender() {
  if (_lastCanvas && _lastSegmentData) {
    renderSegment(_lastCanvas, _lastSegmentData, _lastChainData, _lastScriptName, _lastSpriteImages);
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Render a chain segment preview on a canvas element.
 *
 * @param {HTMLCanvasElement} canvas - target canvas
 * @param {Object} segmentData - segment from chain_data.segments[scriptName]
 * @param {Object} chainData - full chain data (for cast, anchor, overrides)
 * @param {string} scriptName - which segment to render
 * @param {Object} [spriteImages] - optional gfx_id -> Image map
 */
export function renderSegment(canvas, segmentData, chainData, scriptName, spriteImages) {
  if (!canvas || !segmentData) return;

  // Cache for re-render during pan/zoom
  _lastCanvas = canvas;
  _lastSegmentData = segmentData;
  _lastChainData = chainData;
  _lastScriptName = scriptName;
  _lastSpriteImages = spriteImages;
  _lastCardinalRegions = [];
  _lastSightRegions = [];
  _lastApproachRegions = [];

  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;

  // Clear
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, w, h);

  // CSS-to-canvas pixel ratio
  const rect = canvas.getBoundingClientRect();
  _cssToDraw = rect.width > 0 ? canvas.width / rect.width : 1;

  // Determine segment position in sequence (0 = head)
  const sequence = chainData?.sequence || [];
  const segIndex = sequence.findIndex(e => e.script === scriptName);
  const isHead = segIndex === 0;

  // Renderers compute viewport with pan/zoom folded in.
  // Pass canvas pixel dimensions — viewport handles all offsets.
  if (isHead) {
    _renderHeadSegment(ctx, w, h, segmentData, chainData, scriptName, spriteImages);
  } else {
    _renderSubsequentSegment(ctx, w, h, segmentData, chainData, scriptName, segIndex, spriteImages);
  }
}

/**
 * Render the approach tile selector for a talk-to trigger.
 * Returns clickable regions for toggle interaction.
 */
export function renderApproachTiles(canvas, trigger, viewport) {
  if (!canvas || !trigger || trigger.type !== "talk") return [];

  const ctx = canvas.getContext("2d");
  const tiles = trigger.approach_tiles || [];
  const regions = [];

  for (const tile of tiles) {
    const px = tile.x * TILE_PX - viewport.ox;
    const py = tile.y * TILE_PX - viewport.oy;

    const enabled = tile.enabled !== false;
    ctx.fillStyle = enabled ? COLORS.approachEnabled : COLORS.approachDisabled;
    ctx.strokeStyle = enabled ? COLORS.approachBorder : COLORS.approachDisabledBorder;
    ctx.lineWidth = 2;
    ctx.fillRect(px, py, TILE_PX, TILE_PX);
    ctx.strokeRect(px, py, TILE_PX, TILE_PX);

    ctx.fillStyle = COLORS.labelText;
    ctx.font = "bold 10px monospace";
    ctx.textAlign = "center";
    ctx.fillText(tile.player_facing || "?", px + TILE_PX / 2, py + TILE_PX / 2 + 3);

    regions.push({
      x: tile.x, y: tile.y,
      tileX: px, tileY: py,
      enabled,
      canvasRect: { x: px, y: py, w: TILE_PX, h: TILE_PX },
    });
  }

  return regions;
}

// ---------------------------------------------------------------------------
// Head segment rendering
// ---------------------------------------------------------------------------

function _renderHeadSegment(ctx, w, h, segmentData, chainData, scriptName, spriteImages) {
  const trigger = segmentData.trigger;

  // No trigger (auto) — use the subsequent-segment renderer which handles
  // fixed vs range actors properly. Head auto scripts are just like any
  // segment where all positions come from the simulation output.
  if (!trigger || trigger.type === "auto") {
    _renderSubsequentSegment(ctx, w, h, segmentData, chainData, scriptName, 0, spriteImages);
    return;
  }

  const anchor = chainData?.anchor?.actors || {};

  // Triggered head: show NPC sprite + trigger tiles, no player sprite
  const points = [];

  const origin = trigger.npc_origin || {};
  const npcX = origin.x || 0;
  const npcY = origin.y || 0;
  const npcFacing = origin.facing || trigger.facing || "down";
  const npcName = trigger.actor || "";
  points.push({ x: npcX, y: npcY });

  // Add trigger range tiles to viewport
  if (trigger.type === "sight") {
    const range = trigger.range || [1, 1];
    const maxDist = Array.isArray(range) ? range[1] : range;

    // Sight corridor extends in NPC's facing direction
    switch (npcFacing) {
      case "left":  points.push({ x: npcX - maxDist, y: npcY }); break;
      case "right": points.push({ x: npcX + maxDist, y: npcY }); break;
      case "up":    points.push({ x: npcX, y: npcY - maxDist }); break;
      case "down":  points.push({ x: npcX, y: npcY + maxDist }); break;
    }
    // Also include N/E/S/W cardinal tiles around NPC
    points.push({ x: npcX - 1, y: npcY });
    points.push({ x: npcX + 1, y: npcY });
    points.push({ x: npcX, y: npcY - 1 });
    points.push({ x: npcX, y: npcY + 1 });
  } else if (trigger.type === "talk") {
    for (const t of (trigger.approach_tiles || [])) {
      points.push({ x: t.x, y: t.y });
    }
  } else if (trigger.type === "walk_over" || trigger.type === "coord_event") {
    for (const t of (trigger.coord_tiles || [])) {
      points.push({ x: t.x, y: t.y });
    }
  }

  // Add anchor actors for context (e.g., other NPCs on the map)
  for (const [name, data] of Object.entries(anchor)) {
    if (name !== npcName) {
      points.push({ x: data.x || 0, y: data.y || 0 });
    }
  }

  if (points.length === 0) {
    _drawEmpty(ctx, w, h);
    return;
  }

  const viewport = _computeViewport(points, w, h);
  _drawGrid(ctx, w, h, viewport);

  // Draw trigger tiles
  if (trigger.type === "sight") {
    _drawSightCorridor(ctx, trigger, viewport);
  } else if (trigger.type === "talk") {
    _drawTalkApproachTiles(ctx, trigger, viewport);
  } else if (trigger.type === "walk_over" || trigger.type === "coord_event") {
    _drawCoordTriggerTiles(ctx, trigger, viewport);
  }

  // Draw anchor actors (NPCs on the map that aren't the trigger NPC)
  for (const [name, data] of Object.entries(anchor)) {
    if (name === npcName) continue;
    const px = (data.x || 0) * TILE_PX - viewport.ox;
    const py = (data.y || 0) * TILE_PX - viewport.oy;
    _drawActorSprite(ctx, name, px, py, false, spriteImages, data.graphics_id);
  }

  // Draw the trigger NPC sprite with facing arrow
  if (npcName) {
    const px = npcX * TILE_PX - viewport.ox;
    const py = npcY * TILE_PX - viewport.oy;
    _drawActorSprite(ctx, npcName, px, py, false, spriteImages, null);
    _drawFacingArrow(ctx, px, py, npcFacing);
  }
}

// ---------------------------------------------------------------------------
// Subsequent segment rendering
// ---------------------------------------------------------------------------

function _renderSubsequentSegment(ctx, w, h, segmentData, chainData, scriptName, segIndex, spriteImages) {
  const output = segmentData.output || {};
  const actors = output.actors || {};
  const introduces = segmentData.introduces || {};
  const anchor = chainData?.anchor?.actors || {};
  const overrides = (chainData?.manual_overrides || {})[scriptName] || {};
  const actorOverrides = overrides.actors || {};

  // Classify actors into ranged and fixed
  const rangedActors = [];  // {name, xRange, yRange, hasOverride}
  const fixedActors = [];   // {name, x, y, isPlayer, graphics_id}

  for (const [name, data] of Object.entries(actors)) {
    const xIsRange = Array.isArray(data.x) && data.x.length === 2 && data.x[0] !== data.x[1];
    const yIsRange = Array.isArray(data.y) && data.y.length === 2 && data.y[0] !== data.y[1];

    if (xIsRange || yIsRange) {
      rangedActors.push({
        name,
        xRange: xIsRange ? data.x : null,
        yRange: yIsRange ? data.y : null,
        fixedX: _resolveFixed(data.x),
        fixedY: _resolveFixed(data.y),
        hasOverride: name in actorOverrides,
        isPlayer: name === "player",
      });
    } else {
      fixedActors.push({
        name,
        x: _resolveFixed(data.x),
        y: _resolveFixed(data.y),
        isPlayer: name === "player",
        graphics_id: data.graphics_id || "",
      });
    }
  }

  // Add introduced actors that aren't already in output
  const outputNames = new Set(Object.keys(actors));
  for (const [name, data] of Object.entries(introduces)) {
    if (!outputNames.has(name)) {
      fixedActors.push({
        name,
        x: data.x || 0,
        y: data.y || 0,
        isPlayer: name === "player",
        graphics_id: data.graphics_id || "",
      });
    }
  }

  // Add anchor actors not in output and not introduced (like Clyde in ClydeArrives)
  // These are NPCs on the map whose positions haven't changed because they weren't
  // mentioned in any previous script
  for (const [name, data] of Object.entries(anchor)) {
    if (!outputNames.has(name) && !(name in introduces)) {
      fixedActors.push({
        name,
        x: data.x || 0,
        y: data.y || 0,
        isPlayer: false,
        graphics_id: data.graphics_id || "",
      });
    }
  }

  // Build viewport from all positions (including range extents)
  const points = [];
  for (const a of fixedActors) {
    points.push({ x: a.x, y: a.y });
  }
  for (const a of rangedActors) {
    if (a.xRange) {
      points.push({ x: a.xRange[0], y: a.fixedY });
      points.push({ x: a.xRange[1], y: a.fixedY });
    }
    if (a.yRange) {
      points.push({ x: a.fixedX, y: a.yRange[0] });
      points.push({ x: a.fixedX, y: a.yRange[1] });
    }
    if (!a.xRange && !a.yRange) {
      points.push({ x: a.fixedX, y: a.fixedY });
    }
  }

  if (points.length === 0) {
    _drawEmpty(ctx, w, h);
    return;
  }

  const viewport = _computeViewport(points, w, h);
  _drawGrid(ctx, w, h, viewport);

  // Build a map of tile coord -> list of actor names that can occupy it
  const tileOccupants = {};  // "x,y" -> [name, ...]
  for (const a of rangedActors) {
    if (a.xRange) {
      for (let x = a.xRange[0]; x <= a.xRange[1]; x++) {
        const key = `${x},${a.fixedY}`;
        (tileOccupants[key] = tileOccupants[key] || []).push(a.name);
      }
    }
    if (a.yRange) {
      for (let y = a.yRange[0]; y <= a.yRange[1]; y++) {
        const key = `${a.fixedX},${y}`;
        (tileOccupants[key] = tileOccupants[key] || []).push(a.name);
      }
    }
  }

  // Draw range tiles first (underneath sprites), with occupant labels
  for (const a of rangedActors) {
    const color = a.hasOverride ? COLORS.override : COLORS.range;
    const border = a.hasOverride ? COLORS.overrideBorder : COLORS.rangeBorder;
    _drawRangeTiles(ctx, a, viewport, color, border);
  }
  // Draw occupant labels on each tile
  _drawTileOccupantLabels(ctx, tileOccupants, viewport);

  // Draw fixed-position actors as sprites
  for (const a of fixedActors) {
    const px = a.x * TILE_PX - viewport.ox;
    const py = a.y * TILE_PX - viewport.oy;
    _drawActorSprite(ctx, a.name, px, py, a.isPlayer, spriteImages, a.graphics_id);
  }
}

// ---------------------------------------------------------------------------
// Viewport
// ---------------------------------------------------------------------------

function _computeViewport(positions, canvasW, canvasH) {
  if (positions.length === 0) {
    _lastViewportOx = 0;
    _lastViewportOy = 0;
    return { ox: 0, oy: 0 };
  }

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of positions) {
    minX = Math.min(minX, p.x);
    minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x);
    maxY = Math.max(maxY, p.y);
  }

  const pad = 3;
  minX -= pad; minY -= pad; maxX += pad; maxY += pad;

  const worldW = (maxX - minX + 1) * TILE_PX;
  const worldH = (maxY - minY + 1) * TILE_PX;

  // Center content in the canvas: place minX at left edge + margin
  // No zoom scaling — tiles always draw at TILE_PX. Content is centered
  // by shifting the viewport origin so the world center maps to canvas center.
  const worldCX = (minX + maxX + 1) / 2 * TILE_PX;
  const worldCY = (minY + maxY + 1) / 2 * TILE_PX;
  const baseOx = worldCX - canvasW / 2;
  const baseOy = worldCY - canvasH / 2;

  // Apply user pan (CSS pixels → canvas pixels)
  const ox = Math.round(baseOx - _panX * _cssToDraw);
  const oy = Math.round(baseOy - _panY * _cssToDraw);

  // Store for hit testing
  _lastViewportOx = ox;
  _lastViewportOy = oy;

  return { ox, oy };
}

// ---------------------------------------------------------------------------
// Drawing: trigger visualisation
// ---------------------------------------------------------------------------

function _drawSightCorridor(ctx, trigger, viewport) {
  const origin = trigger.npc_origin || {};
  const range = trigger.range || [1, 1];
  const minDist = Array.isArray(range) ? range[0] : 1;
  const maxDist = Array.isArray(range) ? range[1] : range;
  const facing = origin.facing || trigger.facing || "down";
  const nx = origin.x || 0;
  const ny = origin.y || 0;
  const excludedDists = trigger.excluded_distances || [];

  ctx.lineWidth = 1;
  _lastSightRegions = [];

  // Draw sight corridor only in the NPC's facing direction
  for (let d = minDist; d <= maxDist; d++) {
    let tx, ty;
    switch (facing) {
      case "left":  tx = nx - d; ty = ny; break;
      case "right": tx = nx + d; ty = ny; break;
      case "up":    tx = nx; ty = ny - d; break;
      case "down":  tx = nx; ty = ny + d; break;
      default:      tx = nx; ty = ny + d; break;
    }

    const px = tx * TILE_PX - viewport.ox;
    const py = ty * TILE_PX - viewport.oy;
    const isExcluded = excludedDists.includes(d);

    // Sight corridor fill — red for excluded, teal for valid
    ctx.fillStyle = isExcluded ? COLORS.approachDisabled : COLORS.sightLine;
    ctx.fillRect(px, py, TILE_PX, TILE_PX);
    ctx.strokeStyle = isExcluded ? COLORS.approachDisabledBorder : COLORS.sightBorder;
    ctx.lineWidth = isExcluded ? 2 : 1;
    ctx.strokeRect(px, py, TILE_PX, TILE_PX);

    // Distance label
    ctx.fillStyle = isExcluded ? COLORS.approachDisabledBorder : COLORS.triggerBorder;
    ctx.font = "bold 9px monospace";
    ctx.textAlign = "center";
    ctx.fillText(String(d), px + TILE_PX / 2, py + TILE_PX / 2 + 3);

    // Draw X over excluded tiles
    if (isExcluded) {
      ctx.strokeStyle = COLORS.approachDisabledBorder;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(px + 4, py + 4);
      ctx.lineTo(px + TILE_PX - 4, py + TILE_PX - 4);
      ctx.moveTo(px + TILE_PX - 4, py + 4);
      ctx.lineTo(px + 4, py + TILE_PX - 4);
      ctx.stroke();
    }

    _lastSightRegions.push({ distance: d, x: tx, y: ty, excluded: isExcluded });
  }

  // Draw N/E/S/W approach tiles around the NPC (cardinal trigger positions)
  const excluded = trigger.excluded_cardinals || [];
  const cardinals = [
    { x: nx, y: ny - 1, label: "N" },
    { x: nx + 1, y: ny, label: "E" },
    { x: nx, y: ny + 1, label: "S" },
    { x: nx - 1, y: ny, label: "W" },
  ];

  _lastCardinalRegions = [];

  for (const c of cardinals) {
    const px = c.x * TILE_PX - viewport.ox;
    const py = c.y * TILE_PX - viewport.oy;
    const isExcluded = excluded.includes(c.label);

    ctx.fillStyle = isExcluded ? COLORS.approachDisabled : COLORS.triggerTile;
    ctx.fillRect(px, py, TILE_PX, TILE_PX);
    ctx.strokeStyle = isExcluded ? COLORS.approachDisabledBorder : COLORS.triggerBorder;
    ctx.lineWidth = isExcluded ? 2 : 1;
    ctx.strokeRect(px, py, TILE_PX, TILE_PX);

    ctx.fillStyle = isExcluded ? COLORS.approachDisabledBorder : COLORS.triggerBorder;
    ctx.font = "bold 8px monospace";
    ctx.textAlign = "center";
    ctx.fillText(c.label, px + TILE_PX / 2, py + TILE_PX / 2 + 3);

    // Draw X over excluded tiles
    if (isExcluded) {
      ctx.strokeStyle = COLORS.approachDisabledBorder;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(px + 4, py + 4);
      ctx.lineTo(px + TILE_PX - 4, py + TILE_PX - 4);
      ctx.moveTo(px + TILE_PX - 4, py + 4);
      ctx.lineTo(px + 4, py + TILE_PX - 4);
      ctx.stroke();
    }

    _lastCardinalRegions.push({
      label: c.label,
      x: c.x,
      y: c.y,
      excluded: isExcluded,
    });
  }
}

function _drawTalkApproachTiles(ctx, trigger, viewport) {
  const tiles = trigger.approach_tiles || [];
  _lastApproachRegions = [];

  for (let i = 0; i < tiles.length; i++) {
    const tile = tiles[i];
    const px = tile.x * TILE_PX - viewport.ox;
    const py = tile.y * TILE_PX - viewport.oy;

    const enabled = tile.enabled !== false;
    ctx.fillStyle = enabled ? COLORS.approachEnabled : COLORS.approachDisabled;
    ctx.strokeStyle = enabled ? COLORS.approachBorder : COLORS.approachDisabledBorder;
    ctx.lineWidth = 2;
    ctx.fillRect(px, py, TILE_PX, TILE_PX);
    ctx.strokeRect(px, py, TILE_PX, TILE_PX);

    ctx.fillStyle = COLORS.labelText;
    ctx.font = "bold 10px monospace";
    ctx.textAlign = "center";
    ctx.fillText(tile.player_facing || "?", px + TILE_PX / 2, py + TILE_PX / 2 + 3);

    // Draw X over disabled tiles
    if (!enabled) {
      ctx.strokeStyle = COLORS.approachDisabledBorder;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(px + 4, py + 4);
      ctx.lineTo(px + TILE_PX - 4, py + TILE_PX - 4);
      ctx.moveTo(px + TILE_PX - 4, py + 4);
      ctx.lineTo(px + 4, py + TILE_PX - 4);
      ctx.stroke();
    }

    _lastApproachRegions.push({
      index: i,
      x: tile.x,
      y: tile.y,
      enabled: enabled,
      facing: tile.player_facing || "?",
    });
  }
}

function _drawCoordTriggerTiles(ctx, trigger, viewport) {
  const tiles = trigger.coord_tiles || [];

  for (const tile of tiles) {
    const px = tile.x * TILE_PX - viewport.ox;
    const py = tile.y * TILE_PX - viewport.oy;

    ctx.fillStyle = COLORS.triggerTile;
    ctx.strokeStyle = COLORS.triggerBorder;
    ctx.lineWidth = 2;
    ctx.fillRect(px, py, TILE_PX, TILE_PX);
    ctx.strokeRect(px, py, TILE_PX, TILE_PX);

    // Label: player icon
    ctx.fillStyle = COLORS.triggerBorder;
    ctx.font = "bold 9px monospace";
    ctx.textAlign = "center";
    ctx.fillText("\u25CB", px + TILE_PX / 2, py + TILE_PX / 2 + 3);
  }
}

// ---------------------------------------------------------------------------
// Drawing: range tiles
// ---------------------------------------------------------------------------

function _drawRangeTiles(ctx, actor, viewport, fillColor, borderColor) {
  ctx.fillStyle = fillColor;
  ctx.strokeStyle = borderColor;
  ctx.lineWidth = 1;

  if (actor.xRange) {
    const fixedY = actor.fixedY;
    for (let x = actor.xRange[0]; x <= actor.xRange[1]; x++) {
      const px = x * TILE_PX - viewport.ox;
      const py = fixedY * TILE_PX - viewport.oy;
      ctx.fillRect(px, py, TILE_PX, TILE_PX);
      ctx.strokeRect(px, py, TILE_PX, TILE_PX);
    }
  }

  if (actor.yRange) {
    const fixedX = actor.fixedX;
    for (let y = actor.yRange[0]; y <= actor.yRange[1]; y++) {
      const px = fixedX * TILE_PX - viewport.ox;
      const py = y * TILE_PX - viewport.oy;
      ctx.fillRect(px, py, TILE_PX, TILE_PX);
      ctx.strokeRect(px, py, TILE_PX, TILE_PX);
    }
  }
}

function _drawTileOccupantLabels(ctx, tileOccupants, viewport) {
  ctx.save();
  ctx.font = "bold 7px monospace";
  ctx.textAlign = "center";

  for (const [key, names] of Object.entries(tileOccupants)) {
    const [tx, ty] = key.split(",").map(Number);
    const px = tx * TILE_PX - viewport.ox;
    const py = ty * TILE_PX - viewport.oy;

    // Abbreviate names: first 3 chars, lowercase
    const labels = names.map(n => n.length <= 3 ? n : n.slice(0, 3));
    const lineH = 8;
    const startY = py + (TILE_PX - labels.length * lineH) / 2 + 6;

    for (let i = 0; i < labels.length; i++) {
      const ly = startY + i * lineH;
      ctx.fillStyle = "rgba(0, 188, 212, 0.7)";
      const w = ctx.measureText(labels[i]).width + 3;
      ctx.fillRect(px + TILE_PX / 2 - w / 2, ly - 6, w, 8);
      ctx.fillStyle = COLORS.labelText;
      ctx.fillText(labels[i], px + TILE_PX / 2, ly);
    }
  }

  ctx.restore();
}

// ---------------------------------------------------------------------------
// Drawing: actors
// ---------------------------------------------------------------------------

function _drawActorSprite(ctx, name, px, py, isPlayer, spriteImages, gfxId) {
  if (spriteImages && gfxId && spriteImages[gfxId]) {
    const img = spriteImages[gfxId];
    if (img.complete && img.naturalWidth > 0) {
      const sw = img.naturalWidth / 9;
      const sh = img.naturalHeight;
      const dy = py - (sh * SCALE - TILE_PX);
      ctx.drawImage(img, 0, 0, sw, sh, px, dy, sw * SCALE, sh * SCALE);
    } else {
      _drawPlaceholder(ctx, px, py, isPlayer);
    }
  } else {
    _drawPlaceholder(ctx, px, py, isPlayer);
  }

  // Name label
  ctx.save();
  ctx.fillStyle = COLORS.actorLabel;
  ctx.font = "bold 9px monospace";
  ctx.textAlign = "center";
  const labelX = px + TILE_PX / 2;
  const labelY = py - 4;
  const labelW = ctx.measureText(name).width + 4;
  ctx.fillRect(labelX - labelW / 2, labelY - 8, labelW, 10);
  ctx.fillStyle = COLORS.labelText;
  ctx.fillText(name, labelX, labelY);
  ctx.restore();
}

function _drawPlaceholder(ctx, px, py, isPlayer) {
  ctx.fillStyle = isPlayer ? COLORS.player : COLORS.npc;
  ctx.fillRect(px + 4, py + 4, TILE_PX - 8, TILE_PX - 8);
}

function _drawFacingArrow(ctx, px, py, facing) {
  const cx = px + TILE_PX / 2;
  const cy = py + TILE_PX / 2;
  const r = TILE_PX / 3;

  ctx.save();
  ctx.fillStyle = COLORS.facingArrow;
  ctx.beginPath();

  switch (facing) {
    case "up":
      ctx.moveTo(cx, cy - r);
      ctx.lineTo(cx - r * 0.6, cy + r * 0.3);
      ctx.lineTo(cx + r * 0.6, cy + r * 0.3);
      break;
    case "down":
      ctx.moveTo(cx, cy + r);
      ctx.lineTo(cx - r * 0.6, cy - r * 0.3);
      ctx.lineTo(cx + r * 0.6, cy - r * 0.3);
      break;
    case "left":
      ctx.moveTo(cx - r, cy);
      ctx.lineTo(cx + r * 0.3, cy - r * 0.6);
      ctx.lineTo(cx + r * 0.3, cy + r * 0.6);
      break;
    case "right":
      ctx.moveTo(cx + r, cy);
      ctx.lineTo(cx - r * 0.3, cy - r * 0.6);
      ctx.lineTo(cx - r * 0.3, cy + r * 0.6);
      break;
  }

  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

// ---------------------------------------------------------------------------
// Drawing: grid & empty state
// ---------------------------------------------------------------------------

function _drawEmpty(ctx, w, h) {
  ctx.fillStyle = COLORS.background;
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = "rgba(255,255,255,0.3)";
  ctx.font = "12px monospace";
  ctx.textAlign = "center";
  ctx.fillText("No position data - sync chain first", w / 2, h / 2);
}

function _drawGrid(ctx, w, h, viewport) {
  ctx.fillStyle = COLORS.background;
  ctx.fillRect(0, 0, w, h);

  ctx.strokeStyle = COLORS.grid;
  ctx.lineWidth = 1;
  // Grid lines align to tile boundaries: offset by -(viewport.ox mod TILE_PX)
  const offX = (((-viewport.ox) % TILE_PX) + TILE_PX) % TILE_PX;
  const offY = (((-viewport.oy) % TILE_PX) + TILE_PX) % TILE_PX;
  for (let x = offX; x < w; x += TILE_PX) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  }
  for (let y = offY; y < h; y += TILE_PX) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function _resolveFixed(val) {
  if (Array.isArray(val) && val.length === 2) {
    return Math.round((val[0] + val[1]) / 2);
  }
  return val || 0;
}
