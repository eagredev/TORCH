/**
 * TORCH IDE — Flags Tab.
 * TORCH_MODULE
 *
 * Shows flags likely related to the current map (matched by name).
 * Click to see details. "Open Flag Browser" for the full list.
 *
 * Tab API: init(container, mapName), update(mapName), onSelect(), onDeselect(), cleanup()
 */

import { api } from "../app.js";
import { esc } from "../utils.js";

let _container = null;
let _currentMap = null;
let _allFlags = null;   // cached global flags list

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
export function cleanup() { _container = null; _currentMap = null; _allFlags = null; }

async function _load(mapName) {
  if (!_container) return;
  _container.innerHTML = '<div style="padding:0.5rem;color:var(--text-dim);font-size:0.78rem">Loading flags...</div>';

  // Load flags once, cache globally
  if (!_allFlags) {
    try {
      const res = await api("/flags");
      _allFlags = res.ok ? (res.data?.flags || []) : [];
    } catch (_) {
      _allFlags = [];
    }
  }

  // Filter: match map name in flag name (case-insensitive)
  // Convert PascalCase map name to parts for matching
  // "ShirubeTown" → ["shirube", "town"], "LakeElixSouth" → ["lake", "elix", "south"]
  const parts = mapName.replace(/([a-z])([A-Z])/g, "$1_$2").toLowerCase().split("_");
  const mapLower = mapName.toLowerCase().replace(/_/g, "");

  const matched = _allFlags.filter(f => {
    const name = (f.name || "").toLowerCase();
    // Direct map name match (e.g., FLAG_VISITED_SHIRUBE_TOWN)
    if (name.includes(mapLower)) return true;
    // Match all parts (e.g., "shirube" AND "town" in flag name)
    const nameParts = name.replace(/^flag_/, "");
    return parts.length >= 2 && parts.every(p => nameParts.includes(p));
  });

  if (matched.length === 0) {
    let html = `<div style="padding:0.8rem;color:var(--text-dim);text-align:center;font-size:0.78rem">
      No flags matching "${esc(mapName)}"
    </div>`;
    html += _footer();
    _container.innerHTML = html;
    _wireFooter();
    return;
  }

  let html = `<div class="ide-flags-list">`;
  for (const f of matched) {
    const type = f.type || "event";
    const badge = type === "trainer" ? "T" : type === "temp" ? "~" : "";
    html += `<div class="ide-flag-row">`;
    if (badge) html += `<span class="ide-flag-badge">${esc(badge)}</span>`;
    html += `<span class="ide-flag-name">${esc(f.name)}</span>`;
    html += `</div>`;
  }
  html += `</div>`;
  html += `<div class="ide-flags-count">${matched.length} flag${matched.length !== 1 ? "s" : ""} found</div>`;
  html += _footer();

  _container.innerHTML = html;
  _wireFooter();
}

function _footer() {
  return `<div class="ide-flags-footer">
    <button class="ide-flags-open">Open Flag Browser</button>
  </div>`;
}

function _wireFooter() {
  if (!_container) return;
  const btn = _container.querySelector(".ide-flags-open");
  if (btn) {
    btn.addEventListener("click", async () => {
      const { openToolModal } = await import("../toolbar.js");
      openToolModal("Flags", () => import("../views/flags.js"));
    });
  }
}

function _showEmpty() {
  if (_container) _container.innerHTML = '<div style="padding:1rem;color:var(--text-dim);text-align:center;font-size:0.78rem">Select a map</div>';
}
