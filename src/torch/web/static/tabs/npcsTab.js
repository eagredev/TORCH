/**
 * TORCH IDE — NPCs Tab.
 * TORCH_MODULE
 *
 * Lists all NPCs on the current map with spatial linking:
 * click NPC in list → selects on canvas; click NPC on canvas → highlights in list.
 *
 * Tab API: init(container, mapName), update(mapName), onSelect(), onDeselect(), cleanup()
 */

import { api } from "../app.js";
import { esc } from "../utils.js";
import {
  ideOn, ideEmit,
  IDE_EVENT_SELECTED, IDE_OPEN_SCRIPT,
} from "../ide.js";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _container = null;
let _currentMap = null;
let _active = false;
let _unsubs = [];
let _events = null;   // cached events data

// ---------------------------------------------------------------------------
// Tab API
// ---------------------------------------------------------------------------

export function init(container, mapName) {
  _container = container;
  _currentMap = mapName;
  _active = true;

  _unsubs.push(ideOn(IDE_EVENT_SELECTED, _onCanvasSelect));

  if (mapName) _load(mapName);
  else _showEmpty();
}

export function update(mapName) {
  _currentMap = mapName;
  _events = null;
  if (mapName) _load(mapName);
  else _showEmpty();
}

export function onSelect() { _active = true; }
export function onDeselect() { _active = false; }

export function cleanup() {
  for (const unsub of _unsubs) unsub();
  _unsubs = [];
  _container = null;
  _currentMap = null;
  _events = null;
  _active = false;
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function _load(mapName) {
  if (!_container) return;
  _container.innerHTML = '<div style="padding:0.5rem;color:var(--text-dim);font-size:0.78rem">Loading NPCs...</div>';

  try {
    const res = await fetch(`/api/map/${encodeURIComponent(mapName)}/events`);
    const data = await res.json();
    if (data.ok) {
      _events = data.data;
      _render();
    } else {
      _showEmpty();
    }
  } catch (_) {
    _showEmpty();
  }
}

// ---------------------------------------------------------------------------
// Canvas → list sync
// ---------------------------------------------------------------------------

function _onCanvasSelect(detail) {
  if (!_active || !_container || !detail || detail.type !== "npc") return;
  const npcId = detail.data?.object_id;
  if (npcId == null) return;

  // Highlight matching row
  _container.querySelectorAll(".ide-npc-row").forEach(row => {
    row.classList.toggle("highlighted", row.dataset.npcId === String(npcId));
  });

  // Scroll into view
  const target = _container.querySelector(`.ide-npc-row[data-npc-id="${npcId}"]`);
  if (target) target.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function _render() {
  if (!_container || !_events) return;

  const npcs = _events.object_events || [];
  if (npcs.length === 0) {
    _container.innerHTML = '<div style="padding:0.8rem;color:var(--text-dim);text-align:center;font-size:0.78rem">No NPCs on this map</div>';
    return;
  }

  let html = `<input type="text" class="ide-npc-search" placeholder="Filter NPCs..." autocomplete="off" spellcheck="false">`;
  html += `<div class="ide-npc-list">`;

  for (const npc of npcs) {
    const id = npc.object_id;
    const script = npc.script || "";
    // Strip map prefix for display name
    let name = script;
    if (_currentMap && name.startsWith(_currentMap + "_")) {
      name = name.slice(_currentMap.length + 1);
    }
    if (!name) name = `NPC #${id}`;

    const gfx = _humanize(npc.graphics_id || "", "OBJ_EVENT_GFX_");
    const trainer = npc.is_trainer ? " [T]" : "";
    const frameUrl = npc.graphics_id ? `/api/assets/overworld-frame/${encodeURIComponent(npc.graphics_id)}` : "";

    html += `<div class="ide-npc-row" data-npc-id="${id}" data-search="${esc((name + " " + gfx).toLowerCase())}">`;
    if (frameUrl) {
      html += `<img class="ide-npc-sprite" src="${esc(frameUrl)}" alt="">`;
    } else {
      html += `<div class="ide-npc-sprite-ph">?</div>`;
    }
    html += `<div class="ide-npc-info">`;
    html += `<div class="ide-npc-name">${esc(name)}${esc(trainer)}</div>`;
    html += `<div class="ide-npc-meta">${esc(gfx)} (${npc.x}, ${npc.y})</div>`;
    html += `</div>`;
    html += `</div>`;
  }

  html += `</div>`;

  // Footer actions
  html += `<div class="ide-npc-footer">`;
  html += `<span class="ide-npc-count">${npcs.length} NPC${npcs.length !== 1 ? "s" : ""}</span>`;
  html += `</div>`;

  _container.innerHTML = html;

  // Wire search
  const searchInput = _container.querySelector(".ide-npc-search");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      const q = searchInput.value.toLowerCase();
      _container.querySelectorAll(".ide-npc-row").forEach(row => {
        row.style.display = !q || row.dataset.search.includes(q) ? "" : "none";
      });
    });
  }

  // Wire row clicks → select on canvas
  _container.querySelectorAll(".ide-npc-row").forEach(row => {
    row.addEventListener("click", () => {
      const npcId = parseInt(row.dataset.npcId, 10);
      const npc = npcs.find(n => n.object_id === npcId);
      if (npc) {
        ideEmit(IDE_EVENT_SELECTED, { type: "npc", data: npc });
        // Highlight this row
        _container.querySelectorAll(".ide-npc-row").forEach(r => r.classList.remove("highlighted"));
        row.classList.add("highlighted");
      }
    });
  });
}

function _showEmpty() {
  if (!_container) return;
  _container.innerHTML = '<div style="padding:1rem;color:var(--text-dim);text-align:center;font-size:0.78rem">Select a map to see NPCs</div>';
}

function _humanize(name, prefix) {
  if (!name) return "?";
  if (prefix && name.startsWith(prefix)) name = name.slice(prefix.length);
  return name.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}
