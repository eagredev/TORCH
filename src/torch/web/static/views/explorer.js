/**
 * TORCH Web GUI -- Map Explorer: interactive connectivity graph.
 *
 * SVG-based force-directed graph of map warps and connections.
 * Path finder, stats panel, detail panel, search, zoom, region filter.
 */

import { api } from "../app.js";
import { esc } from "../utils.js";
import { renderStudioNavbar } from "../studioNav.js";

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _container = null;
let _graphData = null;     // raw API response
let _nodes = [];           // { name, type, region, x, y, vx, vy, ... }
let _edges = [];           // { source, target, type, direction }
let _nodeMap = {};         // name -> node ref
let _svgEl = null;
let _gWorld = null;        // <g> transform group for zoom/pan
let _selectedNode = null;
let _hoveredNode = null;
let _dragNode = null;
let _dragOffset = { x: 0, y: 0 };
let _zoom = 1;
let _panX = 0;
let _panY = 0;
let _isPanning = false;
let _panStart = { x: 0, y: 0 };
let _panStartOffset = { x: 0, y: 0 };
let _searchQuery = "";
let _regionFilter = "";    // "" = all
let _highlightSet = null;  // Set of map names to highlight (path, orphans, etc)
let _highlightLabel = "";
let _pathResult = null;
let _mapDetail = null;     // detail data for selected map
let _allMaps = [];         // sorted list of all map names
let _debounce = null;
let _resizeHandler = null;
let _styleEl = null;
let _expandedParent = null;  // name of spine map whose indoor children are shown
let _spineNames = new Set(); // maps with connections (the geographic backbone)
let _warpChildren = {};      // parentName -> [childName] (direct warp children)
let _grandChildren = {};     // childName -> [grandchildName] (warp grandchildren)

// Layout constants
const NODE_W = 100;
const NODE_H = 28;
const NODE_RX = 6;
const ATTRACTION = 0.08;
const DAMPING = 0.85;
const ITERATIONS = 200;
const CENTER_GRAVITY = 0.002;
const IDEAL_EDGE_LEN = 180;  // desired distance between connected nodes

// Node type colours
const TYPE_COLORS = {
  normal:   "var(--accent, #d4a017)",
  orphan:   "#ef4444",
  dead_end: "#f97316",
  island:   "#eab308",
};

// ---------------------------------------------------------------------------
// Scoped CSS
// ---------------------------------------------------------------------------

const STYLE_ID = "explorer-view-css";

function injectCSS() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  _styleEl = style;
  style.textContent = `
    .explorer-wrap {
      display: flex; height: calc(100vh - 110px); gap: 0;
      position: relative; overflow: hidden;
    }
    .explorer-main {
      flex: 1; display: flex; flex-direction: column; min-width: 0;
    }
    .explorer-toolbar {
      display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem;
      padding: 0.5rem 0.75rem;
      background: var(--surface-1, #111); border-bottom: 1px solid var(--border-subtle, #2a2a2a);
    }
    .explorer-toolbar h2 {
      margin: 0; font-size: 1rem; color: var(--text-primary, #fff); white-space: nowrap;
    }
    .explorer-search {
      flex: 0 1 200px; padding: 0.3rem 0.5rem; font-size: 0.8rem;
      background: var(--surface-2, #1a1a1a); border: 1px solid var(--border-subtle, #2a2a2a);
      border-radius: 4px; color: #eee; outline: none;
    }
    .explorer-search:focus { border-color: var(--accent, #d4a017); }
    .explorer-search::placeholder { color: var(--text-dim, #666); }
    .explorer-region-select {
      padding: 0.3rem 0.5rem; font-size: 0.8rem;
      background: var(--surface-2, #1a1a1a); border: 1px solid var(--border-subtle, #2a2a2a);
      border-radius: 4px; color: #eee; outline: none; max-width: 180px;
    }
    .explorer-toolbar-btn {
      padding: 0.3rem 0.6rem; font-size: 0.75rem;
      background: var(--surface-2, #1a1a1a); color: var(--text-secondary, #ccc);
      border: 1px solid var(--border-subtle, #2a2a2a); border-radius: 4px;
      cursor: pointer; transition: background 0.15s;
    }
    .explorer-toolbar-btn:hover { background: var(--surface-3, #222); }
    .explorer-toolbar-btn.active {
      background: var(--accent, #d4a017); color: #111;
      border-color: var(--accent, #d4a017);
    }

    /* SVG canvas */
    .explorer-svg-wrap {
      flex: 1; position: relative; overflow: hidden;
      background: var(--surface-0, #0a0a0a);
    }
    .explorer-svg {
      width: 100%; height: 100%; display: block; cursor: grab;
    }
    .explorer-svg.panning { cursor: grabbing; }
    .explorer-svg.dragging { cursor: grabbing; }

    /* Stats bar */
    .explorer-stats {
      display: flex; gap: 1rem; padding: 0.4rem 0.75rem;
      background: var(--surface-1, #111); border-top: 1px solid var(--border-subtle, #2a2a2a);
      font-size: 0.75rem; color: var(--text-muted, #888); flex-wrap: wrap;
    }
    .explorer-stat { cursor: pointer; transition: color 0.15s; }
    .explorer-stat:hover { color: var(--text-primary, #fff); }
    .explorer-stat.active { color: var(--accent, #d4a017); font-weight: 600; }
    .explorer-stat-label { color: var(--text-dim, #666); }
    .explorer-stat-value { color: var(--text-secondary, #ccc); font-weight: 600; margin-left: 0.25rem; }

    /* Side panel */
    .explorer-side {
      width: 320px; overflow-y: auto; background: var(--surface-1, #111);
      border-left: 1px solid var(--border-subtle, #2a2a2a);
      padding: 0.75rem; font-size: 0.8rem;
      transition: width 0.2s;
    }
    .explorer-side.collapsed { width: 0; padding: 0; overflow: hidden; }
    .explorer-side h3 {
      margin: 0 0 0.5rem 0; font-size: 0.9rem; color: var(--text-primary, #fff);
      display: flex; align-items: center; gap: 0.5rem;
    }
    .explorer-side-close {
      margin-left: auto; cursor: pointer; color: var(--text-dim, #666);
      font-size: 1.1rem; border: none; background: none; padding: 0 0.2rem;
    }
    .explorer-side-close:hover { color: var(--text-primary, #fff); }
    .explorer-side-section {
      margin-bottom: 0.75rem;
    }
    .explorer-side-section h4 {
      margin: 0 0 0.3rem 0; font-size: 0.75rem; color: var(--accent, #d4a017);
      text-transform: uppercase; letter-spacing: 0.04em;
    }
    .explorer-side-item {
      padding: 0.15rem 0; color: var(--text-secondary, #ccc);
    }
    .explorer-side-link {
      color: var(--accent, #d4a017); cursor: pointer; text-decoration: none;
      border: none; background: none; padding: 0; font-size: inherit;
    }
    .explorer-side-link:hover { text-decoration: underline; }
    .explorer-side-badge {
      display: inline-block; padding: 0.1rem 0.4rem; border-radius: 3px;
      font-size: 0.7rem; font-weight: 600; margin-left: 0.3rem;
    }
    .explorer-badge-orphan { background: rgba(239,68,68,0.15); color: #ef4444; }
    .explorer-badge-dead_end { background: rgba(249,115,22,0.15); color: #f97316; }
    .explorer-badge-island { background: rgba(234,179,8,0.15); color: #eab308; }
    .explorer-badge-normal { background: var(--accent-bg, rgba(212,160,23,0.08)); color: var(--accent, #d4a017); }

    /* Path finder */
    .explorer-pathfinder {
      display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center;
    }
    .explorer-path-select {
      flex: 1; min-width: 100px; padding: 0.3rem 0.5rem; font-size: 0.8rem;
      background: var(--surface-2, #1a1a1a); border: 1px solid var(--border-subtle, #2a2a2a);
      border-radius: 4px; color: #eee; outline: none;
    }
    .explorer-path-result {
      padding: 0.3rem 0; font-size: 0.8rem; color: var(--text-secondary, #ccc);
    }
    .explorer-path-step {
      display: flex; align-items: center; gap: 0.3rem; padding: 0.1rem 0;
    }
    .explorer-path-arrow { color: var(--text-dim, #666); font-size: 0.7rem; }
    .explorer-path-node { color: var(--accent, #d4a017); cursor: pointer; }
    .explorer-path-node:hover { text-decoration: underline; }
    .explorer-path-trans { color: var(--text-dim, #666); font-size: 0.7rem; }

    /* Highlight label bar */
    .explorer-highlight-bar {
      display: flex; align-items: center; gap: 0.5rem;
      padding: 0.3rem 0.75rem;
      background: var(--accent-bg-faint, rgba(212,160,23,0.1));
      border-bottom: 1px solid var(--accent-border-faint, rgba(212,160,23,0.3));
      font-size: 0.75rem; color: var(--accent, #d4a017);
    }
    .explorer-highlight-bar .clear-btn {
      margin-left: auto; cursor: pointer; background: none; border: none;
      color: var(--text-dim, #666); font-size: 0.75rem; padding: 0.1rem 0.3rem;
    }
    .explorer-highlight-bar .clear-btn:hover { color: var(--text-primary, #fff); }

    /* Tooltip */
    .explorer-tooltip {
      position: fixed; pointer-events: none;
      background: var(--surface-3, #222); color: var(--text-primary, #fff);
      padding: 0.3rem 0.5rem; border-radius: 4px; font-size: 0.75rem;
      border: 1px solid var(--border-subtle, #2a2a2a);
      z-index: 1000; white-space: nowrap;
      opacity: 0; transition: opacity 0.1s;
    }
    .explorer-tooltip.visible { opacity: 1; }

    /* Loading spinner */
    .explorer-spinner {
      width: 24px; height: 24px; border: 3px solid var(--border-subtle, #2a2a2a);
      border-top-color: var(--accent, #d4a017); border-radius: 50%;
      animation: explorer-spin 0.8s linear infinite;
    }
    @keyframes explorer-spin { to { transform: rotate(360deg); } }

    /* Responsive */
    @media (max-width: 768px) {
      .explorer-wrap { flex-direction: column; height: auto; }
      .explorer-side { width: 100%; border-left: none; border-top: 1px solid var(--border-subtle, #2a2a2a); max-height: 40vh; }
      .explorer-side.collapsed { max-height: 0; }
      .explorer-svg-wrap { min-height: 50vh; }
    }
  `;
  document.head.appendChild(style);
}


// ---------------------------------------------------------------------------
// Force-directed layout
// ---------------------------------------------------------------------------

function initLayout(nodes, edges) {
  // ── Hierarchical layout with collapsible indoor maps.
  //
  //    Spine: maps with connections, placed using cardinal directions.
  //    Indoor: warp-only children of spine maps, HIDDEN by default.
  //    Orphans: maps with no edges, placed in a row below.
  //
  //    Clicking a spine node toggles its indoor children visible.
  //    Grandchildren (indoor→indoor warps) show as text links, not nodes.

  const placed = new Set();
  const STEP_X = IDEAL_EDGE_LEN + NODE_W + 20;
  const STEP_Y = IDEAL_EDGE_LEN + NODE_H + 10;

  // Build adjacency lookups from edges
  const connEdges = {};  // map -> [{target, direction}]
  const warpEdges = {};  // map -> [target]
  for (const e of edges) {
    if (e.type === "connection") {
      if (!connEdges[e.source]) connEdges[e.source] = [];
      if (!connEdges[e.target]) connEdges[e.target] = [];
      // direction = "up" means target is above source (game convention)
      connEdges[e.source].push({ target: e.target, direction: e.direction || "" });
      const rev = { up: "down", down: "up", left: "right", right: "left",
                     north: "south", south: "north", east: "west", west: "east" };
      connEdges[e.target].push({ target: e.source, direction: rev[e.direction] || "" });
    } else {
      if (!warpEdges[e.source]) warpEdges[e.source] = [];
      if (!warpEdges[e.target]) warpEdges[e.target] = [];
      warpEdges[e.source].push(e.target);
      warpEdges[e.target].push(e.source);
    }
  }

  // Classify: spine = has connections
  _spineNames = new Set();
  for (const n of nodes) {
    if (connEdges[n.name] && connEdges[n.name].length > 0) {
      _spineNames.add(n.name);
    }
  }

  // Build parent→child warp mapping (spine → non-spine warp targets)
  _warpChildren = {};
  _grandChildren = {};
  const claimed = new Set();  // indoor maps already assigned to a parent
  for (const parentName of _spineNames) {
    const warps = (warpEdges[parentName] || []).filter(
      w => !_spineNames.has(w) && _nodeMap[w] && !claimed.has(w)
    );
    if (warps.length) {
      _warpChildren[parentName] = warps;
      for (const w of warps) claimed.add(w);
    }
  }
  // Grandchildren: indoor maps that warp to other indoor maps
  for (const parentName of Object.keys(_warpChildren)) {
    for (const childName of _warpChildren[parentName]) {
      const gw = (warpEdges[childName] || []).filter(
        w => !_spineNames.has(w) && w !== parentName && _nodeMap[w] && !claimed.has(w)
      );
      if (gw.length) {
        _grandChildren[childName] = gw;
        for (const w of gw) claimed.add(w);
      }
    }
  }

  // Mark indoor nodes (for styling, not hiding)
  for (const n of nodes) {
    n._indoor = claimed.has(n.name);
  }

  // Direction offsets — game uses up/down/left/right (not north/south/east/west)
  // "up" means target is above source (y decreases), "right" means target is to the right
  const DIR_DX = { right: 1, left: -1, up: 0, down: 0, east: 1, west: -1, north: 0, south: 0 };
  const DIR_DY = { up: -1, down: 1, left: 0, right: 0, north: -1, south: 1, east: 0, west: 0 };

  // ── Place spine maps via BFS using connection directions ──
  function placeSpine() {
    if (!_spineNames.size) return;

    // Root: prefer a town (not a Route)
    let root = null;
    for (const name of _spineNames) {
      if (!name.match(/^Route\d/i)) { root = name; break; }
    }
    if (!root) root = _spineNames.values().next().value;

    _nodeMap[root].x = 0;
    _nodeMap[root].y = 0;
    placed.add(root);

    const queue = [root];
    while (queue.length) {
      const current = queue.shift();
      for (const { target, direction } of (connEdges[current] || [])) {
        if (placed.has(target) || !_nodeMap[target]) continue;
        const parent = _nodeMap[current];
        const dx = DIR_DX[direction] ?? 0;
        const dy = DIR_DY[direction] ?? 0;
        // If direction is known, use its offsets exactly; if unknown, default right
        const hasDirInfo = dx !== 0 || dy !== 0;
        let nx = parent.x + (hasDirInfo ? dx : 1) * STEP_X;
        let ny = parent.y + dy * STEP_Y;
        // Nudge to avoid overlaps
        let attempts = 0;
        while (attempts < 10 && isOccupied(nx, ny, NODE_W + 10, NODE_H + 10)) {
          if (dx !== 0) ny += STEP_Y * 0.6;
          else nx += STEP_X * 0.6;
          attempts++;
        }
        _nodeMap[target].x = nx;
        _nodeMap[target].y = ny;
        placed.add(target);
        queue.push(target);
      }
    }

    // Disconnected spine clusters
    for (const name of _spineNames) {
      if (placed.has(name)) continue;
      let maxX = 0;
      for (const n of nodes) { if (placed.has(n.name) && n.x > maxX) maxX = n.x; }
      _nodeMap[name].x = maxX + STEP_X * 2;
      _nodeMap[name].y = 0;
      placed.add(name);
      const q2 = [name];
      while (q2.length) {
        const cur = q2.shift();
        for (const { target, direction } of (connEdges[cur] || [])) {
          if (placed.has(target) || !_nodeMap[target]) continue;
          const p = _nodeMap[cur];
          const ddx = DIR_DX[direction] ?? 0, ddy = DIR_DY[direction] ?? 0;
          const hasDirInfo2 = ddx !== 0 || ddy !== 0;
          _nodeMap[target].x = p.x + (hasDirInfo2 ? ddx : 1) * STEP_X;
          _nodeMap[target].y = p.y + ddy * STEP_Y;
          placed.add(target);
          q2.push(target);
        }
      }
    }
  }

  // ── Place orphans (no connections AND no warp parent) in a row below ──
  function placeOrphans() {
    const unplaced = nodes.filter(n => !placed.has(n.name));
    if (!unplaced.length) return;
    let maxY = 0;
    for (const n of nodes) { if (placed.has(n.name) && n.y > maxY) maxY = n.y; }
    const orphanY = maxY + STEP_Y * 1.2;
    const startX = -(unplaced.length * (NODE_W + 30)) / 2;
    for (let i = 0; i < unplaced.length; i++) {
      unplaced[i].x = startX + i * (NODE_W + 30);
      unplaced[i].y = orphanY;
      placed.add(unplaced[i].name);
    }
  }

  function isOccupied(x, y, w, h) {
    for (const name of placed) {
      const n = _nodeMap[name];
      if (Math.abs(n.x - x) < w && Math.abs(n.y - y) < h) return true;
    }
    return false;
  }

  placeSpine();

  // ── Place indoor maps as vertical stacks, offset left of their spine parent ──
  // Offset left so the stack doesn't overlap the connection line going south
  const CHILD_GAP_Y = NODE_H + 16;  // tight vertical stacking
  const INDOOR_OFFSET_X = -(NODE_W + 30);  // shift entire stack to the left of parent
  for (const [parentName, children] of Object.entries(_warpChildren)) {
    const parent = _nodeMap[parentName];
    if (!parent) continue;
    // Stack all children vertically, offset to the left
    const baseX = parent.x + INDOOR_OFFSET_X;
    let curY = parent.y + CHILD_GAP_Y;
    for (let i = 0; i < children.length; i++) {
      const child = _nodeMap[children[i]];
      if (!child) continue;
      child.x = baseX;
      child.y = curY;
      placed.add(children[i]);
      curY += CHILD_GAP_Y;

      // Grandchildren continue the stack directly below
      const gcs = _grandChildren[children[i]] || [];
      for (let j = 0; j < gcs.length; j++) {
        const gc = _nodeMap[gcs[j]];
        if (!gc) continue;
        gc.x = baseX;
        gc.y = curY;
        placed.add(gcs[j]);
        curY += CHILD_GAP_Y;
      }
    }
  }

  placeOrphans();

  for (const n of nodes) { n.vx = 0; n.vy = 0; }

  // Center on all placed nodes
  if (nodes.length) {
    let cx = 0, cy = 0;
    for (const n of nodes) { cx += n.x; cy += n.y; }
    cx /= nodes.length; cy /= nodes.length;
    for (const n of nodes) { n.x -= cx; n.y -= cy; }
  }
}


// ---------------------------------------------------------------------------
// SVG rendering
// ---------------------------------------------------------------------------

function svgNS() { return "http://www.w3.org/2000/svg"; }

function createSVG(container) {
  const wrap = container.querySelector(".explorer-svg-wrap");
  if (!wrap) return;

  const svg = document.createElementNS(svgNS(), "svg");
  svg.classList.add("explorer-svg");
  svg.setAttribute("xmlns", svgNS());
  _svgEl = svg;

  const gWorld = document.createElementNS(svgNS(), "g");
  gWorld.setAttribute("class", "world");
  _gWorld = gWorld;
  svg.appendChild(gWorld);

  wrap.appendChild(svg);

  // Event handlers
  svg.addEventListener("wheel", onWheel, { passive: false });
  svg.addEventListener("mousedown", onMouseDown);
  svg.addEventListener("mousemove", onMouseMove);
  svg.addEventListener("mouseup", onMouseUp);
  svg.addEventListener("mouseleave", onMouseUp);

  updateTransform();
  drawGraph();
}

function updateTransform() {
  if (!_gWorld) return;
  _gWorld.setAttribute("transform", `translate(${_panX},${_panY}) scale(${_zoom})`);
}

function drawGraph() {
  if (!_gWorld || !_nodes.length) return;
  _gWorld.innerHTML = "";

  // Region background rectangles (subtle)
  const regionBounds = {};
  for (const n of _nodes) {
    if (!n.region || !isVisible(n)) continue;
    if (!regionBounds[n.region]) {
      regionBounds[n.region] = { minX: n.x, maxX: n.x, minY: n.y, maxY: n.y };
    } else {
      const b = regionBounds[n.region];
      b.minX = Math.min(b.minX, n.x);
      b.maxX = Math.max(b.maxX, n.x);
      b.minY = Math.min(b.minY, n.y);
      b.maxY = Math.max(b.maxY, n.y);
    }
  }

  const pad = 40;
  for (const [region, b] of Object.entries(regionBounds)) {
    const rect = document.createElementNS(svgNS(), "rect");
    rect.setAttribute("x", b.minX - pad);
    rect.setAttribute("y", b.minY - pad);
    rect.setAttribute("width", b.maxX - b.minX + NODE_W + pad * 2);
    rect.setAttribute("height", b.maxY - b.minY + NODE_H + pad * 2);
    rect.setAttribute("rx", "8");
    rect.setAttribute("fill", "rgba(255,255,255,0.02)");
    rect.setAttribute("stroke", "rgba(255,255,255,0.04)");
    rect.setAttribute("stroke-width", "1");
    _gWorld.appendChild(rect);

    // Region label
    const text = document.createElementNS(svgNS(), "text");
    text.setAttribute("x", b.minX - pad + 6);
    text.setAttribute("y", b.minY - pad + 14);
    text.setAttribute("fill", "rgba(255,255,255,0.12)");
    text.setAttribute("font-size", "10");
    text.setAttribute("font-family", "sans-serif");
    text.textContent = region;
    _gWorld.appendChild(text);
  }

  // Draw edges
  for (const e of _edges) {
    const src = _nodeMap[e.source];
    const tgt = _nodeMap[e.target];
    if (!src || !tgt) continue;
    if (!isVisible(src) || !isVisible(tgt)) continue;

    const line = document.createElementNS(svgNS(), "line");
    line.setAttribute("x1", src.x + NODE_W / 2);
    line.setAttribute("y1", src.y + NODE_H / 2);
    line.setAttribute("x2", tgt.x + NODE_W / 2);
    line.setAttribute("y2", tgt.y + NODE_H / 2);

    const isHighlighted = isEdgeHighlighted(e);
    if (isHighlighted) {
      line.setAttribute("stroke", "#4ade80");
      line.setAttribute("stroke-width", "3");
      line.setAttribute("stroke-opacity", "1");
    } else if (_highlightSet) {
      line.setAttribute("stroke", "rgba(255,255,255,0.06)");
      line.setAttribute("stroke-width", "0.5");
    } else if (e.type === "connection") {
      // Geographic spine — solid, prominent
      line.setAttribute("stroke", "rgba(100,180,255,0.5)");
      line.setAttribute("stroke-width", "2");
    } else {
      // Warp — thinner, dashed, warm color (parent → indoor child)
      line.setAttribute("stroke", "rgba(212,160,23,0.35)");
      line.setAttribute("stroke-width", "1.5");
      line.setAttribute("stroke-dasharray", "6,4");
    }

    _gWorld.appendChild(line);
  }

  // Zoom-dependent label visibility
  const showLabels = _zoom > 0.4;
  const showFullLabels = _zoom > 0.8;
  const dotMode = !showLabels;
  const dotR = dotMode ? 5 : 0;

  // Draw nodes
  for (const n of _nodes) {
    if (!isVisible(n)) continue;

    const g = document.createElementNS(svgNS(), "g");
    g.setAttribute("transform", `translate(${n.x},${n.y})`);
    g.setAttribute("data-map", n.name);
    g.style.cursor = "pointer";

    const isSelected = _selectedNode === n.name;
    const isInHighlight = _highlightSet && _highlightSet.has(n.name);
    const isSearchMatch = _searchQuery && n.name.toLowerCase().includes(_searchQuery.toLowerCase());

    let fillColor = "var(--surface-2, #1a1a1a)";
    let strokeColor = TYPE_COLORS[n.type] || TYPE_COLORS.normal;
    let strokeWidth = "1.5";
    let textFill = "var(--text-secondary, #ccc)";

    if (isSelected) {
      fillColor = "var(--accent-bg-strong, rgba(212,160,23,0.2))";
      strokeColor = "var(--accent, #d4a017)";
      strokeWidth = "2.5";
      textFill = "var(--text-primary, #fff)";
    } else if (isInHighlight) {
      fillColor = "rgba(74,222,128,0.12)";
      strokeColor = "#4ade80";
      strokeWidth = "2";
      textFill = "#fff";
    } else if (isSearchMatch) {
      fillColor = "var(--accent-bg-faint, rgba(212,160,23,0.1))";
      strokeWidth = "2";
      textFill = "#fff";
    } else if (_highlightSet) {
      // Dim non-highlighted nodes
      fillColor = "var(--surface-2, #1a1a1a)";
      strokeColor = "rgba(255,255,255,0.08)";
      strokeWidth = "0.5";
      textFill = "rgba(255,255,255,0.2)";
    }

    if (dotMode) {
      // At low zoom, render compact circles instead of full rectangles
      const circle = document.createElementNS(svgNS(), "circle");
      circle.setAttribute("cx", NODE_W / 2);
      circle.setAttribute("cy", NODE_H / 2);
      circle.setAttribute("r", dotR);
      circle.setAttribute("fill", strokeColor);
      circle.setAttribute("stroke", strokeColor);
      circle.setAttribute("stroke-width", strokeWidth);
      circle.setAttribute("fill-opacity", "0.6");
      g.appendChild(circle);
    } else {
      const rect = document.createElementNS(svgNS(), "rect");
      rect.setAttribute("width", NODE_W);
      rect.setAttribute("height", NODE_H);
      rect.setAttribute("rx", NODE_RX);
      rect.setAttribute("fill", fillColor);
      rect.setAttribute("stroke", strokeColor);
      rect.setAttribute("stroke-width", strokeWidth);
      g.appendChild(rect);

      const text = document.createElementNS(svgNS(), "text");
      text.setAttribute("x", NODE_W / 2);
      text.setAttribute("y", NODE_H / 2 + 4);
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("fill", textFill);
      text.setAttribute("font-size", "9");
      text.setAttribute("font-family", "sans-serif");

      // Truncate based on zoom level
      let displayName;
      if (showFullLabels) {
        displayName = n.name.length > 14 ? n.name.slice(0, 13) + "..." : n.name;
      } else {
        displayName = n.name.length > 8 ? n.name.slice(0, 8) + "..." : n.name;
      }
      text.textContent = displayName;
      g.appendChild(text);

      // Indoor child count badge on spine maps
      const childCount = (_warpChildren[n.name] || []).length;
      if (childCount > 0 && showLabels) {
        const badge = document.createElementNS(svgNS(), "text");
        badge.setAttribute("x", NODE_W - 4);
        badge.setAttribute("y", 9);
        badge.setAttribute("text-anchor", "end");
        badge.setAttribute("fill", _expandedParent === n.name ? "#4ade80" : "var(--text-dim, #666)");
        badge.setAttribute("font-size", "7");
        badge.setAttribute("font-family", "sans-serif");
        badge.textContent = _expandedParent === n.name ? `\u25B2${childCount}` : `\u25BC${childCount}`;
        g.appendChild(badge);
      }
    }

    // Events
    g.addEventListener("mousedown", (e) => { e.stopPropagation(); startDrag(n, e); });
    g.addEventListener("click", (e) => {
      e.stopPropagation();
      if (!n._dragged) selectNode(n.name);
    });
    g.addEventListener("mouseenter", (e) => showTooltip(n, e));
    g.addEventListener("mouseleave", hideTooltip);

    _gWorld.appendChild(g);
  }
}

function isVisible(node) {
  if (_regionFilter && node.region !== _regionFilter) return false;
  // Indoor maps hidden unless their parent is expanded
  if (node._indoor) {
    if (!_expandedParent) return false;
    const children = _warpChildren[_expandedParent] || [];
    if (children.includes(node.name)) return true;
    // Check grandchildren
    for (const ch of children) {
      if ((_grandChildren[ch] || []).includes(node.name)) return true;
    }
    return false;
  }
  return true;
}

function isEdgeHighlighted(edge) {
  if (!_highlightSet || !_pathResult) return false;
  const path = _pathResult;
  for (let i = 0; i < path.length - 1; i++) {
    const a = path[i].map, b = path[i + 1].map;
    if ((edge.source === a && edge.target === b) ||
        (edge.source === b && edge.target === a)) {
      return true;
    }
  }
  return false;
}


// ---------------------------------------------------------------------------
// Interaction: zoom, pan, drag
// ---------------------------------------------------------------------------

function onWheel(e) {
  e.preventDefault();
  const delta = e.deltaY > 0 ? 0.9 : 1.1;
  const newZoom = Math.max(0.01, Math.min(10, _zoom * delta));

  // Zoom toward cursor
  const rect = _svgEl.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  _panX = mx - (mx - _panX) * (newZoom / _zoom);
  _panY = my - (my - _panY) * (newZoom / _zoom);

  // Redraw when crossing label visibility thresholds
  const oldZoom = _zoom;
  _zoom = newZoom;
  const crossedThreshold =
    (oldZoom <= 0.4 && newZoom > 0.4) || (oldZoom > 0.4 && newZoom <= 0.4) ||
    (oldZoom <= 0.8 && newZoom > 0.8) || (oldZoom > 0.8 && newZoom <= 0.8);

  if (crossedThreshold) {
    drawGraph();
  }
  updateTransform();
}

function onMouseDown(e) {
  if (e.button !== 0) return;
  // Start panning (only if not on a node)
  _isPanning = true;
  _panStart = { x: e.clientX, y: e.clientY };
  _panStartOffset = { x: _panX, y: _panY };
  _svgEl.classList.add("panning");
}

function onMouseMove(e) {
  if (_dragNode) {
    // Don't start dragging until mouse moves beyond dead zone
    const dxPx = e.clientX - (_dragNode._dragStartX || 0);
    const dyPx = e.clientY - (_dragNode._dragStartY || 0);
    if (!_dragNode._dragged && Math.abs(dxPx) < DRAG_DEAD_ZONE && Math.abs(dyPx) < DRAG_DEAD_ZONE) {
      return;  // still in dead zone — treat as potential click
    }
    e.preventDefault();
    _dragNode._dragged = true;
    _svgEl.classList.add("dragging");
    const rect = _svgEl.getBoundingClientRect();
    const mx = (e.clientX - rect.left - _panX) / _zoom;
    const my = (e.clientY - rect.top - _panY) / _zoom;
    _dragNode.x = mx - _dragOffset.x;
    _dragNode.y = my - _dragOffset.y;
    drawGraph();
    return;
  }
  if (_isPanning) {
    const dx = e.clientX - _panStart.x;
    const dy = e.clientY - _panStart.y;
    _panX = _panStartOffset.x + dx;
    _panY = _panStartOffset.y + dy;
    updateTransform();
  }
}

function onMouseUp() {
  if (_dragNode) {
    // Reset drag flag after a short delay so click handler can check it
    const node = _dragNode;
    setTimeout(() => { node._dragged = false; }, 50);
    _dragNode = null;
    _svgEl.classList.remove("dragging");
  }
  _isPanning = false;
  _svgEl.classList.remove("panning");
}

const DRAG_DEAD_ZONE = 5;  // px — must move this far before drag starts

function startDrag(node, e) {
  _dragNode = node;
  node._dragged = false;
  node._dragStartX = e.clientX;
  node._dragStartY = e.clientY;
  const rect = _svgEl.getBoundingClientRect();
  const mx = (e.clientX - rect.left - _panX) / _zoom;
  const my = (e.clientY - rect.top - _panY) / _zoom;
  _dragOffset = { x: mx - node.x, y: my - node.y };
}


// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------

function showTooltip(node, e) {
  _hoveredNode = node.name;
  let tip = document.querySelector(".explorer-tooltip");
  if (!tip) {
    tip = document.createElement("div");
    tip.className = "explorer-tooltip";
    document.body.appendChild(tip);
  }
  const warpCount = node.warp_count || 0;
  const connCount = node.conn_count || 0;
  tip.innerHTML = `<strong>${esc(node.name)}</strong><br>${node.region || "No region"}<br>${warpCount} warps, ${connCount} connections`;
  tip.style.left = (e.clientX + 12) + "px";
  tip.style.top = (e.clientY + 12) + "px";
  tip.classList.add("visible");
}

function hideTooltip() {
  _hoveredNode = null;
  const tip = document.querySelector(".explorer-tooltip");
  if (tip) tip.classList.remove("visible");
}


// ---------------------------------------------------------------------------
// Node selection and detail panel
// ---------------------------------------------------------------------------

function selectNode(name) {
  // Toggle indoor expansion for spine maps that have children
  if (_spineNames.has(name) && _warpChildren[name] && _warpChildren[name].length) {
    _expandedParent = (_expandedParent === name) ? null : name;
  }

  if (_selectedNode === name) {
    _selectedNode = null;
    _mapDetail = null;
    updateSidePanel();
    drawGraph();
    return;
  }
  _selectedNode = name;
  drawGraph();
  loadMapDetail(name);
}

async function loadMapDetail(name) {
  try {
    const resp = await api(`/explorer/map/${name}`);
    if (resp.ok) {
      _mapDetail = resp.data;
    } else {
      _mapDetail = { name, error: resp.error || "Failed to load" };
    }
  } catch (err) {
    _mapDetail = { name, error: err.message };
  }
  updateSidePanel();
}

function updateSidePanel() {
  if (!_container) return;
  const side = _container.querySelector(".explorer-side");
  if (!side) return;

  if (!_selectedNode || !_mapDetail) {
    side.classList.add("collapsed");
    return;
  }

  side.classList.remove("collapsed");
  const d = _mapDetail;

  if (d.error) {
    side.innerHTML = `<h3>${esc(d.name)} <button class="explorer-side-close">&times;</button></h3>
      <p style="color:#f44">${esc(d.error)}</p>`;
    wireCloseBtn(side);
    return;
  }

  const badgeClass = `explorer-badge-${d.type || "normal"}`;
  const badgeLabel = (d.type || "normal").replace("_", " ");

  let layoutHtml = "";
  if (d.layout) {
    const l = d.layout;
    if (l.width && l.height) layoutHtml += `<div class="explorer-side-item">${l.width} x ${l.height} tiles</div>`;
    if (l.primary_tileset) layoutHtml += `<div class="explorer-side-item" style="color:var(--text-dim)">${esc(l.primary_tileset)}</div>`;
    if (l.secondary_tileset) layoutHtml += `<div class="explorer-side-item" style="color:var(--text-dim)">${esc(l.secondary_tileset)}</div>`;
    const counts = [];
    if (l.npc_count) counts.push(`${l.npc_count} NPCs`);
    if (l.warp_event_count) counts.push(`${l.warp_event_count} warps`);
    if (l.trigger_count) counts.push(`${l.trigger_count} triggers`);
    if (l.sign_count) counts.push(`${l.sign_count} signs`);
    if (counts.length) layoutHtml += `<div class="explorer-side-item" style="color:var(--text-dim)">${counts.join(" / ")}</div>`;
  }

  let warpsOutHtml = "";
  if (d.warps_out && d.warps_out.length) {
    warpsOutHtml = d.warps_out.map(w =>
      `<div class="explorer-side-item"><button class="explorer-side-link" data-nav="${esc(w.dest_map)}">${esc(w.dest_map)}</button> <span style="color:var(--text-dim)">warp ${w.dest_warp_id} (${w.x},${w.y})</span></div>`
    ).join("");
  } else {
    warpsOutHtml = `<div class="explorer-side-item" style="color:var(--text-dim)">None</div>`;
  }

  let warpsInHtml = "";
  if (d.warps_in && d.warps_in.length) {
    warpsInHtml = d.warps_in.map(m =>
      `<div class="explorer-side-item"><button class="explorer-side-link" data-nav="${esc(m)}">${esc(m)}</button></div>`
    ).join("");
  } else {
    warpsInHtml = `<div class="explorer-side-item" style="color:var(--text-dim)">None</div>`;
  }

  let connsOutHtml = "";
  if (d.connections_out && d.connections_out.length) {
    connsOutHtml = d.connections_out.map(c =>
      `<div class="explorer-side-item"><button class="explorer-side-link" data-nav="${esc(c.map)}">${esc(c.map)}</button> <span style="color:var(--text-dim)">${esc(c.direction)}</span></div>`
    ).join("");
  } else {
    connsOutHtml = `<div class="explorer-side-item" style="color:var(--text-dim)">None</div>`;
  }

  let connsInHtml = "";
  if (d.connections_in && d.connections_in.length) {
    connsInHtml = d.connections_in.map(c =>
      `<div class="explorer-side-item"><button class="explorer-side-link" data-nav="${esc(c.map)}">${esc(c.map)}</button> <span style="color:var(--text-dim)">${esc(c.direction)}</span></div>`
    ).join("");
  } else {
    connsInHtml = `<div class="explorer-side-item" style="color:var(--text-dim)">None</div>`;
  }

  side.innerHTML = `
    <h3>${esc(d.name)} <span class="explorer-side-badge ${badgeClass}">${badgeLabel}</span>
      <button class="explorer-side-close">&times;</button></h3>
    ${d.region ? `<div class="explorer-side-item" style="color:var(--text-muted);margin-bottom:0.5rem">${esc(d.region)}</div>` : ""}
    <div class="explorer-side-section">
      <h4>Layout</h4>
      ${layoutHtml || `<div class="explorer-side-item" style="color:var(--text-dim)">No layout info</div>`}
    </div>
    <div class="explorer-side-section">
      <h4>Warps Out (${(d.warps_out || []).length})</h4>
      ${warpsOutHtml}
    </div>
    <div class="explorer-side-section">
      <h4>Warps In (${(d.warps_in || []).length})</h4>
      ${warpsInHtml}
    </div>
    <div class="explorer-side-section">
      <h4>Connections Out (${(d.connections_out || []).length})</h4>
      ${connsOutHtml}
    </div>
    <div class="explorer-side-section">
      <h4>Connections In (${(d.connections_in || []).length})</h4>
      ${connsInHtml}
    </div>
    ${buildIndoorSection(d.name)}
  `;

  wireCloseBtn(side);
  wireSideNav(side);
}

function buildIndoorSection(mapName) {
  const children = _warpChildren[mapName];
  if (!children || !children.length) return "";
  let html = `<div class="explorer-side-section">
    <h4>Indoor Maps (${children.length})</h4>`;
  for (const childName of children) {
    html += `<div class="explorer-side-item"><button class="explorer-side-link" data-nav="${esc(childName)}">${esc(childName)}</button>`;
    // Show grandchildren as sub-links
    const gcs = _grandChildren[childName];
    if (gcs && gcs.length) {
      html += `<div style="margin-left:1rem;margin-top:0.1rem">`;
      for (const gc of gcs) {
        html += `<div><button class="explorer-side-link" data-nav="${esc(gc)}" style="font-size:0.7rem;color:var(--text-dim)">\u2514 ${esc(gc)}</button></div>`;
      }
      html += `</div>`;
    }
    html += `</div>`;
  }
  html += `</div>`;
  return html;
}

function wireCloseBtn(side) {
  const btn = side.querySelector(".explorer-side-close");
  if (btn) {
    btn.addEventListener("click", () => {
      _selectedNode = null;
      _mapDetail = null;
      updateSidePanel();
      drawGraph();
    });
  }
}

function wireSideNav(side) {
  side.querySelectorAll("[data-nav]").forEach(btn => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.nav;
      navigateToNode(target);
    });
  });
}

function navigateToNode(name) {
  const node = _nodeMap[name];
  if (!node) return;

  // Center the view on this node
  if (_svgEl) {
    const rect = _svgEl.getBoundingClientRect();
    _panX = rect.width / 2 - node.x * _zoom;
    _panY = rect.height / 2 - node.y * _zoom;
    updateTransform();
  }

  selectNode(name);
}


// ---------------------------------------------------------------------------
// Path finder
// ---------------------------------------------------------------------------

async function findPath(fromMap, toMap) {
  if (!fromMap || !toMap) return;
  try {
    const resp = await api(`/explorer/path?from=${encodeURIComponent(fromMap)}&to=${encodeURIComponent(toMap)}`);
    if (resp.ok) {
      _pathResult = resp.data.found ? resp.data.path : null;
      if (resp.data.found) {
        _highlightSet = new Set(resp.data.path.map(s => s.map));
        _highlightLabel = `Path: ${fromMap} \u2192 ${toMap} (${resp.data.hops} hop${resp.data.hops !== 1 ? "s" : ""})`;
      } else {
        _highlightSet = null;
        _highlightLabel = `No path found from ${fromMap} to ${toMap}`;
        _pathResult = null;
      }
      drawGraph();
      updateHighlightBar();
      updatePathResult();
    }
  } catch (err) {
    _highlightLabel = `Error: ${err.message}`;
    updateHighlightBar();
  }
}

function updatePathResult() {
  if (!_container) return;
  const el = _container.querySelector(".explorer-path-result");
  if (!el) return;

  if (!_pathResult) {
    el.innerHTML = _highlightLabel ? `<span style="color:var(--text-dim)">${esc(_highlightLabel)}</span>` : "";
    return;
  }

  let html = "";
  for (let i = 0; i < _pathResult.length; i++) {
    const step = _pathResult[i];
    if (i > 0) {
      html += `<div class="explorer-path-step">
        <span class="explorer-path-arrow">\u2192</span>
        <span class="explorer-path-trans">${esc(step.transition)}</span>
      </div>`;
    }
    html += `<div class="explorer-path-step">
      <span class="explorer-path-node" data-nav="${esc(step.map)}">${esc(step.map)}</span>
    </div>`;
  }

  el.innerHTML = html;
  el.querySelectorAll("[data-nav]").forEach(span => {
    span.style.cursor = "pointer";
    span.addEventListener("click", () => navigateToNode(span.dataset.nav));
  });
}


// ---------------------------------------------------------------------------
// Stat highlight toggles
// ---------------------------------------------------------------------------

function highlightCategory(category) {
  if (!_graphData) return;

  // Toggle off if already active
  if (_highlightLabel === category) {
    clearHighlight();
    return;
  }

  const stats = _graphData.stats;
  let maps;
  if (category === "orphans") {
    maps = _nodes.filter(n => n.type === "orphan").map(n => n.name);
  } else if (category === "dead_ends") {
    maps = _nodes.filter(n => n.type === "dead_end").map(n => n.name);
  } else if (category === "islands") {
    maps = _nodes.filter(n => n.type === "island").map(n => n.name);
  } else {
    clearHighlight();
    return;
  }

  _highlightSet = new Set(maps);
  _highlightLabel = category;
  _pathResult = null;
  drawGraph();
  updateHighlightBar();
  updateStatsBar();
}

function clearHighlight() {
  _highlightSet = null;
  _highlightLabel = "";
  _pathResult = null;
  drawGraph();
  updateHighlightBar();
  updateStatsBar();
  const pathRes = _container ? _container.querySelector(".explorer-path-result") : null;
  if (pathRes) pathRes.innerHTML = "";
}

function updateHighlightBar() {
  if (!_container) return;
  const bar = _container.querySelector(".explorer-highlight-bar");
  if (!bar) return;

  if (!_highlightLabel) {
    bar.style.display = "none";
    return;
  }
  bar.style.display = "flex";
  bar.innerHTML = `<span>${esc(_highlightLabel)}${_highlightSet ? ` (${_highlightSet.size} maps)` : ""}</span>
    <button class="clear-btn">Clear</button>`;
  bar.querySelector(".clear-btn").addEventListener("click", clearHighlight);
}

function updateStatsBar() {
  if (!_container) return;
  _container.querySelectorAll(".explorer-stat").forEach(el => {
    el.classList.toggle("active", el.dataset.category === _highlightLabel);
  });
}


// ---------------------------------------------------------------------------
// Fit view
// ---------------------------------------------------------------------------

function fitView() {
  if (!_svgEl || !_nodes.length) return;
  const rect = _svgEl.getBoundingClientRect();
  const visibleNodes = _nodes.filter(isVisible);
  if (!visibleNodes.length) return;

  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const n of visibleNodes) {
    if (n.x < minX) minX = n.x;
    if (n.x + NODE_W > maxX) maxX = n.x + NODE_W;
    if (n.y < minY) minY = n.y;
    if (n.y + NODE_H > maxY) maxY = n.y + NODE_H;
  }

  const graphW = Math.max(maxX - minX, 1);
  const graphH = Math.max(maxY - minY, 1);
  const padFrac = 0.08;
  const availW = rect.width * (1 - padFrac * 2);
  const availH = rect.height * (1 - padFrac * 2);

  const oldZoom = _zoom;
  _zoom = Math.min(availW / graphW, availH / graphH, 3);
  _panX = rect.width / 2 - (minX + graphW / 2) * _zoom;
  _panY = rect.height / 2 - (minY + graphH / 2) * _zoom;

  // Redraw if we crossed a label visibility threshold
  const crossedThreshold =
    (oldZoom <= 0.4 && _zoom > 0.4) || (oldZoom > 0.4 && _zoom <= 0.4) ||
    (oldZoom <= 0.8 && _zoom > 0.8) || (oldZoom > 0.8 && _zoom <= 0.8);
  if (crossedThreshold) drawGraph();
  updateTransform();
}


// ---------------------------------------------------------------------------
// Main render
// ---------------------------------------------------------------------------

export async function render(container) {
  _container = container;
  injectCSS();

  container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:60vh;gap:1rem">
    <div class="explorer-spinner"></div>
    <span style="color:var(--text-muted)">Loading map graph...</span>
  </div>`;

  try {
    const resp = await api("/explorer/graph");
    if (!resp.ok) {
      container.innerHTML = `<p style="color:#f44;padding:1rem;">${esc(resp.error)}</p>`;
      return;
    }
    _graphData = resp.data;
  } catch (err) {
    container.innerHTML = `<p style="color:#f44;padding:1rem;">${esc(err.message)}</p>`;
    return;
  }

  _nodes = _graphData.nodes.map(n => ({ ...n, vx: 0, vy: 0 }));
  _edges = _graphData.edges;
  _nodeMap = {};
  for (const n of _nodes) _nodeMap[n.name] = n;
  _allMaps = _graphData.nodes.map(n => n.name).sort();

  // Build region options
  const regionSet = new Set();
  for (const n of _nodes) {
    if (n.region) regionSet.add(n.region);
  }
  const regionOptions = Array.from(regionSet).sort().map(r =>
    `<option value="${esc(r)}">${esc(r)}</option>`
  ).join("");

  // Build map options for path finder
  const mapOptions = _allMaps.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join("");

  const stats = _graphData.stats;

  container.innerHTML = renderStudioNavbar("Map Explorer") + `
    <div class="explorer-wrap">
      <div class="explorer-main">
        <div class="explorer-toolbar">
          <h2>Map Explorer</h2>
          <input type="text" class="explorer-search" placeholder="Search maps...">
          <select class="explorer-region-select">
            <option value="">All Regions</option>
            ${regionOptions}
          </select>
          <button class="explorer-toolbar-btn" data-action="fit">Fit</button>
          <button class="explorer-toolbar-btn" data-action="path">Path Finder</button>
        </div>
        <div class="explorer-highlight-bar" style="display:none"></div>
        <div class="explorer-pathfinder-wrap" style="display:none">
          <div style="padding:0.5rem 0.75rem;background:var(--surface-1);border-bottom:1px solid var(--border-subtle)">
            <div class="explorer-pathfinder">
              <select class="explorer-path-select" data-role="from">
                <option value="">-- From --</option>
                ${mapOptions}
              </select>
              <span style="color:var(--text-dim)">\u2192</span>
              <select class="explorer-path-select" data-role="to">
                <option value="">-- To --</option>
                ${mapOptions}
              </select>
              <button class="explorer-toolbar-btn" data-action="find-path">Find</button>
              <button class="explorer-toolbar-btn" data-action="close-path">&times;</button>
            </div>
            <div class="explorer-path-result"></div>
          </div>
        </div>
        <div class="explorer-svg-wrap"></div>
        <div class="explorer-stats">
          <span class="explorer-stat" data-category="total"><span class="explorer-stat-label">Total</span><span class="explorer-stat-value">${stats.total}</span></span>
          <span class="explorer-stat" data-category="connected"><span class="explorer-stat-label">Connected</span><span class="explorer-stat-value">${stats.connected}</span></span>
          <span class="explorer-stat" data-category="orphans"><span class="explorer-stat-label">Orphans</span><span class="explorer-stat-value">${stats.orphans}</span></span>
          <span class="explorer-stat" data-category="dead_ends"><span class="explorer-stat-label">Dead Ends</span><span class="explorer-stat-value">${stats.dead_ends}</span></span>
          <span class="explorer-stat" data-category="islands"><span class="explorer-stat-label">Islands</span><span class="explorer-stat-value">${stats.islands}</span></span>
          <span class="explorer-stat" data-category="edges"><span class="explorer-stat-label">Edges</span><span class="explorer-stat-value">${stats.edges}</span></span>
        </div>
      </div>
      <div class="explorer-side collapsed"></div>
    </div>
  `;

  // Run layout
  initLayout(_nodes, _edges);

  // Create SVG
  createSVG(container);

  // Fit view after a frame
  requestAnimationFrame(() => fitView());

  // Wire toolbar
  wireToolbar(container);

  // Resize handler
  _resizeHandler = () => fitView();
  window.addEventListener("resize", _resizeHandler);
}

function wireToolbar(container) {
  // Search
  const searchInput = container.querySelector(".explorer-search");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      clearTimeout(_debounce);
      _debounce = setTimeout(() => {
        _searchQuery = searchInput.value.trim();
        drawGraph();
      }, 200);
    });
  }

  // Region filter
  const regionSelect = container.querySelector(".explorer-region-select");
  if (regionSelect) {
    regionSelect.addEventListener("change", () => {
      _regionFilter = regionSelect.value;
      drawGraph();
      requestAnimationFrame(() => fitView());
    });
  }

  // Fit button
  container.querySelector("[data-action='fit']")?.addEventListener("click", fitView);

  // Path finder toggle
  const pathBtn = container.querySelector("[data-action='path']");
  const pathWrap = container.querySelector(".explorer-pathfinder-wrap");
  if (pathBtn && pathWrap) {
    pathBtn.addEventListener("click", () => {
      const visible = pathWrap.style.display !== "none";
      pathWrap.style.display = visible ? "none" : "block";
      pathBtn.classList.toggle("active", !visible);
    });
  }

  // Find path
  container.querySelector("[data-action='find-path']")?.addEventListener("click", () => {
    const from = container.querySelector("[data-role='from']")?.value;
    const to = container.querySelector("[data-role='to']")?.value;
    findPath(from, to);
  });

  // Close path finder
  container.querySelector("[data-action='close-path']")?.addEventListener("click", () => {
    if (pathWrap) pathWrap.style.display = "none";
    if (pathBtn) pathBtn.classList.remove("active");
    clearHighlight();
  });

  // Stats clicks
  container.querySelectorAll(".explorer-stat").forEach(el => {
    el.addEventListener("click", () => {
      const cat = el.dataset.category;
      if (cat === "orphans" || cat === "dead_ends" || cat === "islands") {
        highlightCategory(cat);
      }
    });
  });
}


// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------

export function cleanup() {
  if (_resizeHandler) {
    window.removeEventListener("resize", _resizeHandler);
    _resizeHandler = null;
  }
  clearTimeout(_debounce);
  _debounce = null;
  hideTooltip();

  // Remove tooltip element
  const tip = document.querySelector(".explorer-tooltip");
  if (tip) tip.remove();

  _container = null;
  _graphData = null;
  _nodes = [];
  _edges = [];
  _nodeMap = {};
  _svgEl = null;
  _gWorld = null;
  _selectedNode = null;
  _hoveredNode = null;
  _dragNode = null;
  _zoom = 1;
  _panX = 0;
  _panY = 0;
  _isPanning = false;
  _searchQuery = "";
  _regionFilter = "";
  _highlightSet = null;
  _highlightLabel = "";
  _pathResult = null;
  _mapDetail = null;
  _allMaps = [];
  _expandedParent = null;
  _spineNames = new Set();
  _warpChildren = {};
  _grandChildren = {};
}
