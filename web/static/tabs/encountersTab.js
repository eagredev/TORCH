/**
 * TORCH IDE — Encounters Tab.
 * TORCH_MODULE
 *
 * Compact wild encounter display for the current map.
 * Shows species, level range, and encounter rate grouped by type.
 * "Edit Full Table" opens the full encounters modal.
 *
 * Tab API: init(container, mapName), update(mapName), onSelect(), onDeselect(), cleanup()
 */

import { api } from "../app.js";
import { esc } from "../utils.js";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _container = null;
let _currentMap = null;
let _cache = {};   // mapConst → encounter data

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TYPE_LABELS = {
  land_mons: "Land",
  water_mons: "Water",
  fishing_mons: "Fishing",
  rock_smash_mons: "Rock Smash",
};

function _folderToMapConst(folder) {
  const snake = folder.replace(/([a-z])([A-Z])/g, "$1_$2");
  return "MAP_" + snake.toUpperCase();
}

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
  if (mapName) _load(mapName);
  else _showEmpty();
}

export function onSelect() {}
export function onDeselect() {}

export function cleanup() {
  _container = null;
  _currentMap = null;
  _cache = {};
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function _load(mapName) {
  if (!_container) return;

  const mapConst = _folderToMapConst(mapName);

  // Check cache
  if (_cache[mapConst]) {
    _render(_cache[mapConst]);
    return;
  }

  _container.innerHTML = '<div style="padding:0.5rem;color:var(--text-dim);font-size:0.8rem">Loading encounters...</div>';

  try {
    const res = await api(`/encounters/${encodeURIComponent(mapConst)}`);
    if (res.ok && res.data && res.data.types) {
      _cache[mapConst] = res.data;
      _render(res.data);
    } else {
      _showNoEncounters();
    }
  } catch (_) {
    _showNoEncounters();
  }
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function _render(data) {
  if (!_container) return;

  const types = data.types || {};
  const typeNames = Object.keys(types);

  if (typeNames.length === 0) {
    _showNoEncounters();
    return;
  }

  let html = "";

  for (const tname of typeNames) {
    const group = types[tname];
    const mons = group.mons || [];
    const label = TYPE_LABELS[tname] || tname.replace(/_/g, " ");
    const rate = group.encounter_rate != null ? ` (rate: ${group.encounter_rate})` : "";

    html += `<div class="ide-enc-group">`;
    html += `<div class="ide-enc-group-header">${esc(label)}<span class="ide-enc-rate">${mons.length} slots${esc(rate)}</span></div>`;

    for (const mon of mons) {
      const lvl = mon.min_level === mon.max_level
        ? `Lv ${mon.min_level}`
        : `Lv ${mon.min_level}-${mon.max_level}`;
      const pct = mon.rate_pct != null ? `${mon.rate_pct}%` : "";

      html += `<div class="ide-enc-row">`;
      html += `<span class="ide-enc-lvl">${esc(lvl)}</span>`;
      html += `<span class="ide-enc-species">${esc(mon.species_name || mon.species)}</span>`;
      html += `<span class="ide-enc-pct">${esc(pct)}</span>`;
      html += `</div>`;
    }

    html += `</div>`;
  }

  // Edit Full Table link
  html += `<div class="ide-enc-footer">
    <button class="ide-enc-edit-btn">Edit Full Table...</button>
  </div>`;

  _container.innerHTML = html;

  // Wire edit button
  const editBtn = _container.querySelector(".ide-enc-edit-btn");
  if (editBtn) {
    editBtn.addEventListener("click", async () => {
      const { openToolModal } = await import("../toolbar.js");
      const mapConst = _folderToMapConst(_currentMap);
      openToolModal("Encounters", () => import("../views/encounters.js"), `#/encounters/${mapConst}`);
    });
  }
}

function _showNoEncounters() {
  if (!_container) return;
  _container.innerHTML = `
    <div style="padding:1rem;color:var(--text-dim);text-align:center;font-size:0.8rem">
      No wild encounters for this map
    </div>
  `;
}

function _showEmpty() {
  if (!_container) return;
  _container.innerHTML = `
    <div style="padding:1rem;color:var(--text-dim);text-align:center;font-size:0.8rem">
      Select a map to see encounters
    </div>
  `;
}
