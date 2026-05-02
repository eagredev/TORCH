/**
 * TORCH IDE — Warps Tab.
 * TORCH_MODULE
 *
 * Lists all warps and map connections for the current map.
 * Click warp → highlights on canvas. Double-click → navigates to destination.
 *
 * Tab API: init(container, mapName), update(mapName), onSelect(), onDeselect(), cleanup()
 */

import { api } from "../app.js";
import { esc } from "../utils.js";
import { ideEmit, IDE_MAP_SELECTED, IDE_EVENT_SELECTED } from "../ide.js";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _container = null;
let _currentMap = null;
let _events = null;
let _connections = null;

// ---------------------------------------------------------------------------
// Tab API
// ---------------------------------------------------------------------------

export function init(container, mapName) {
  _container = container;
  _currentMap = mapName;
  if (mapName) _load(mapName);
  else _showEmpty();
}

export function update(mapName) {
  _currentMap = mapName;
  _events = null;
  _connections = null;
  if (mapName) _load(mapName);
  else _showEmpty();
}

export function onSelect() {}
export function onDeselect() {}

export function cleanup() {
  _container = null;
  _currentMap = null;
  _events = null;
  _connections = null;
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function _load(mapName) {
  if (!_container) return;
  _container.innerHTML = '<div style="padding:0.5rem;color:var(--text-dim);font-size:0.78rem">Loading...</div>';

  // Load events and connections in parallel
  const [eventsRes, connRes] = await Promise.allSettled([
    fetch(`/api/map/${encodeURIComponent(mapName)}/events`).then(r => r.json()),
    api(`/explorer/map/${encodeURIComponent(mapName)}`),
  ]);

  if (eventsRes.status === "fulfilled" && eventsRes.value?.ok) {
    _events = eventsRes.value.data;
  }
  if (connRes.status === "fulfilled" && connRes.value?.ok) {
    _connections = connRes.value.data;
  }

  _render();
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function _render() {
  if (!_container) return;

  const warps = _events?.warp_events || [];
  const connsOut = _connections?.connections_out || [];
  const hasData = warps.length > 0 || connsOut.length > 0;

  if (!hasData) {
    _container.innerHTML = '<div style="padding:1rem;color:var(--text-dim);text-align:center;font-size:0.78rem">No warps or connections</div>';
    return;
  }

  let html = "";

  // Warp events
  if (warps.length > 0) {
    html += `<div class="ide-warp-section-header">Warps (${warps.length})</div>`;
    for (const w of warps) {
      const dest = w.dest_map || "?";
      const destWarp = w.dest_warp_id || 0;
      html += `<div class="ide-warp-row" data-warp-id="${w.id}" data-dest="${esc(dest)}">`;
      html += `<span class="ide-warp-arrow">\u2192</span>`;
      html += `<span class="ide-warp-dest">${esc(dest)}</span>`;
      html += `<span class="ide-warp-meta">#${destWarp} (${w.x},${w.y})</span>`;
      html += `</div>`;
    }
  }

  // Map connections
  if (connsOut.length > 0) {
    html += `<div class="ide-warp-section-header" style="margin-top:0.5rem">Connections (${connsOut.length})</div>`;
    for (const c of connsOut) {
      const dir = (c.direction || "?").charAt(0).toUpperCase() + (c.direction || "").slice(1);
      html += `<div class="ide-warp-row ide-conn-row" data-dest="${esc(c.map)}">`;
      html += `<span class="ide-warp-dir">${esc(dir)}</span>`;
      html += `<span class="ide-warp-dest">${esc(c.map)}</span>`;
      html += `</div>`;
    }
  }

  _container.innerHTML = html;

  // Wire warp row clicks → select on canvas
  _container.querySelectorAll(".ide-warp-row[data-warp-id]").forEach(row => {
    row.addEventListener("click", () => {
      const warpId = parseInt(row.dataset.warpId, 10);
      const warp = warps.find(w => w.id === warpId);
      if (warp) {
        ideEmit(IDE_EVENT_SELECTED, { type: "warp", data: warp });
      }
    });
    row.addEventListener("dblclick", () => {
      const dest = row.dataset.dest;
      if (dest && dest !== "?") {
        ideEmit(IDE_MAP_SELECTED, { name: dest, source: "warps-tab" });
      }
    });
  });

  // Wire connection row clicks → navigate
  _container.querySelectorAll(".ide-conn-row").forEach(row => {
    row.addEventListener("click", () => {
      const dest = row.dataset.dest;
      if (dest) {
        ideEmit(IDE_MAP_SELECTED, { name: dest, source: "warps-tab" });
      }
    });
  });
}

function _showEmpty() {
  if (!_container) return;
  _container.innerHTML = '<div style="padding:1rem;color:var(--text-dim);text-align:center;font-size:0.78rem">Select a map to see warps</div>';
}
