/**
 * TORCH IDE — Shops Tab.
 * TORCH_MODULE
 *
 * Compact shop display for the current map.
 * Shows items with names. "Edit in Shop Editor" opens the full modal.
 *
 * Tab API: init(container, mapName), update(mapName), onSelect(), onDeselect(), cleanup()
 */

import { api } from "../app.js";
import { esc } from "../utils.js";

let _container = null;
let _currentMap = null;
let _shopCache = {};  // mapName → shop data

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
export function cleanup() { _container = null; _currentMap = null; _shopCache = {}; }

async function _load(mapName) {
  if (!_container) return;

  // Check cache
  if (_shopCache[mapName]) {
    _render(_shopCache[mapName]);
    return;
  }

  _container.innerHTML = '<div style="padding:0.5rem;color:var(--text-dim);font-size:0.78rem">Loading shops...</div>';

  // The shops API uses map folder names — try direct match
  try {
    const res = await api(`/shops/${encodeURIComponent(mapName)}`);
    if (res.ok && res.data) {
      _shopCache[mapName] = res.data;
      _render(res.data);
      return;
    }
  } catch (_) {}

  // Try searching in the full shops list for maps containing this name
  try {
    const res = await api("/shops");
    if (res.ok && res.data?.maps) {
      const mapLower = mapName.toLowerCase().replace(/_/g, "");
      const match = res.data.maps.find(m => {
        const n = (m.name || "").toLowerCase().replace(/_/g, "");
        return n === mapLower || n.includes(mapLower) || mapLower.includes(n);
      });
      if (match && match.shops && match.shops.length > 0) {
        _shopCache[mapName] = match;
        _render(match);
        return;
      }
    }
  } catch (_) {}

  _container.innerHTML = `<div style="padding:0.8rem;color:var(--text-dim);text-align:center;font-size:0.78rem">
    No shops on this map
  </div>`;
}

function _render(data) {
  if (!_container) return;

  const shops = data.shops || [];
  if (shops.length === 0) {
    _container.innerHTML = '<div style="padding:0.8rem;color:var(--text-dim);text-align:center;font-size:0.78rem">No shops</div>';
    return;
  }

  let html = "";
  for (const shop of shops) {
    const label = _humanizeLabel(shop.label || "Shop");
    const items = shop.items || [];
    html += `<div class="ide-shop-group">`;
    html += `<div class="ide-shop-header">${esc(label)} <span class="ide-shop-count">${items.length} items</span></div>`;
    for (const item of items) {
      const name = _humanizeItem(item);
      html += `<div class="ide-shop-item">${esc(name)}</div>`;
    }
    html += `</div>`;
  }

  html += `<div class="ide-shop-footer">
    <button class="ide-shop-edit">Edit in Shop Editor</button>
  </div>`;

  _container.innerHTML = html;

  const editBtn = _container.querySelector(".ide-shop-edit");
  if (editBtn) {
    editBtn.addEventListener("click", async () => {
      const { openToolModal } = await import("../toolbar.js");
      openToolModal("Shops", () => import("../views/shops.js"), `#/shops/${_currentMap}`);
    });
  }
}

function _showEmpty() {
  if (_container) _container.innerHTML = '<div style="padding:1rem;color:var(--text-dim);text-align:center;font-size:0.78rem">Select a map</div>';
}

function _humanizeLabel(label) {
  // "ShirubeTown_Mart_Pokemart" → "Pokemart"
  const parts = label.split("_");
  return parts[parts.length - 1] || label;
}

function _humanizeItem(item) {
  // "ITEM_POTION" → "Potion"
  if (item.startsWith("ITEM_")) item = item.slice(5);
  return item.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}
