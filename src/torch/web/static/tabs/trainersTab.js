/**
 * TORCH IDE — Trainers Tab.
 * TORCH_MODULE
 *
 * Shows trainers on the current map with party summaries.
 * Identifies trainers from NPC data (trainer_type != NONE).
 * Click to select on canvas.
 *
 * Tab API: init(container, mapName), update(mapName), onSelect(), onDeselect(), cleanup()
 */

import { esc } from "../utils.js";
import { ideEmit, IDE_EVENT_SELECTED } from "../ide.js";

let _container = null;
let _currentMap = null;
let _events = null;

export function init(container, mapName) {
  _container = container;
  _currentMap = mapName;
  if (mapName) _load(mapName);
  else _showEmpty();
}

export function update(mapName) {
  _currentMap = mapName;
  _events = null;
  if (mapName) _load(mapName);
  else _showEmpty();
}

export function onSelect() {}
export function onDeselect() {}
export function cleanup() { _container = null; _currentMap = null; _events = null; }

async function _load(mapName) {
  if (!_container) return;
  _container.innerHTML = '<div style="padding:0.5rem;color:var(--text-dim);font-size:0.78rem">Loading trainers...</div>';

  try {
    const res = await fetch(`/api/map/${encodeURIComponent(mapName)}/events`);
    const data = await res.json();
    if (data.ok) {
      _events = data.data;
      _render();
    } else {
      _showNoTrainers();
    }
  } catch (_) {
    _showNoTrainers();
  }
}

function _render() {
  if (!_container || !_events) return;

  const npcs = _events.object_events || [];
  const trainers = npcs.filter(n =>
    n.trainer_type && n.trainer_type !== "TRAINER_TYPE_NONE"
  );

  if (trainers.length === 0) {
    _showNoTrainers();
    return;
  }

  let html = `<div class="ide-trainers-list">`;
  for (const t of trainers) {
    const script = t.script || "";
    let name = script;
    if (_currentMap && name.startsWith(_currentMap + "_")) {
      name = name.slice(_currentMap.length + 1);
    }
    if (!name) name = `Trainer #${t.object_id}`;

    const type = _humanize(t.trainer_type || "", "TRAINER_TYPE_");
    const sight = t.trainer_sight_or_berry_tree_id || 0;
    const frameUrl = t.graphics_id ? `/api/assets/overworld-frame/${encodeURIComponent(t.graphics_id)}` : "";

    html += `<div class="ide-trainer-row" data-npc-id="${t.object_id}">`;
    if (frameUrl) {
      html += `<img class="ide-trainer-sprite" src="${esc(frameUrl)}" alt="">`;
    }
    html += `<div class="ide-trainer-info">`;
    html += `<div class="ide-trainer-name">${esc(name)}</div>`;
    html += `<div class="ide-trainer-meta">${esc(type)} \u2022 Sight: ${sight} \u2022 (${t.x},${t.y})</div>`;
    html += `</div>`;
    html += `</div>`;
  }
  html += `</div>`;

  html += `<div class="ide-trainers-footer">`;
  html += `<span class="ide-trainers-count">${trainers.length} trainer${trainers.length !== 1 ? "s" : ""}</span>`;
  html += `<button class="ide-trainers-open">Open Trainer Editor</button>`;
  html += `</div>`;

  _container.innerHTML = html;

  // Wire row clicks → select NPC on canvas
  _container.querySelectorAll(".ide-trainer-row").forEach(row => {
    row.addEventListener("click", () => {
      const npcId = parseInt(row.dataset.npcId, 10);
      const npc = (npcs || []).find(n => n.object_id === npcId);
      if (npc) ideEmit(IDE_EVENT_SELECTED, { type: "npc", data: npc });
    });
  });

  const openBtn = _container.querySelector(".ide-trainers-open");
  if (openBtn) {
    openBtn.addEventListener("click", async () => {
      const { openToolModal } = await import("../toolbar.js");
      openToolModal("Trainers", () => import("../views/trainers.js"));
    });
  }
}

function _showNoTrainers() {
  if (_container) _container.innerHTML = '<div style="padding:0.8rem;color:var(--text-dim);text-align:center;font-size:0.78rem">No trainers on this map</div>';
}

function _showEmpty() {
  if (_container) _container.innerHTML = '<div style="padding:1rem;color:var(--text-dim);text-align:center;font-size:0.78rem">Select a map</div>';
}

function _humanize(name, prefix) {
  if (!name) return "?";
  if (prefix && name.startsWith(prefix)) name = name.slice(prefix.length);
  return name.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}
