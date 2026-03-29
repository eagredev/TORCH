/**
 * grid.js — Metatile grid panel for the Tileset Editor (left panel).
 * Renders all metatiles in an 8-wide scrollable grid with color-coded borders.
 */

import {
  state, emit, on, off,
  METATILE_SELECTED, DIRTY_CHANGED, SAVE_COMPLETED, GRID_NEEDS_UPDATE,
  LAYER_COLORS, CHANGED_COLOR,
  getEffectiveLayerType,
} from "./state.js";
import { renderMetatile } from "./renderer.js";

// ---------------------------------------------------------------------------
// Grid rendering
// ---------------------------------------------------------------------------

export function renderGrid(container) {
  const gridEl = container.querySelector(".ts-grid");
  if (!gridEl) return;

  gridEl.innerHTML = "";
  state.gridCanvases.clear();

  for (const mt of state.metatiles) {
    const layerType = getEffectiveLayerType(mt);
    const isChanged = state.pendingChanges.has(mt.id);
    const isDimmed = _isDimmed(mt, layerType);

    const cell = document.createElement("div");
    cell.className = "ts-cell";
    cell.dataset.id = String(mt.id);
    cell.style.borderColor = LAYER_COLORS[layerType];

    if (mt.id === state.selectedId) cell.classList.add("selected");
    if (isDimmed) cell.classList.add("dimmed");
    if (isChanged) cell.classList.add("changed");

    const canvas = document.createElement("canvas");
    canvas.width = 16;
    canvas.height = 16;

    if (state.tilesImgLoaded && state.tilesImg) {
      renderMetatile(canvas, mt, layerType,
                     { bottom: true, middle: true, top: true });
    }

    cell.appendChild(canvas);

    const idLabel = document.createElement("span");
    idLabel.className = "ts-cell-id";
    idLabel.textContent = String(mt.id);
    cell.appendChild(idLabel);

    state.gridCanvases.set(mt.id, canvas);
    gridEl.appendChild(cell);
  }

  gridEl.addEventListener("click", _onGridClick);
}

function _onGridClick(e) {
  const cell = e.target.closest(".ts-cell");
  if (!cell) return;

  const id = parseInt(cell.dataset.id, 10);
  if (isNaN(id)) return;

  state.selectedId = id;
  state.layerOverrides = null;

  // Update selected visual
  if (state.container) {
    state.container.querySelectorAll(".ts-cell.selected").forEach(c => c.classList.remove("selected"));
    cell.classList.add("selected");
  }

  emit(METATILE_SELECTED, { id });
}

export function updateGridCell(id) {
  const mt = state.metatiles.find(m => m.id === id);
  if (!mt) return;

  const canvas = state.gridCanvases.get(id);
  if (!canvas || !state.tilesImg) return;

  const layerType = getEffectiveLayerType(mt);
  // Use pending tile changes if available (composition edits)
  const change = state.pendingChanges.get(id);
  const renderMt = (change && change.tiles) ? { ...mt, tiles: change.tiles } : mt;
  renderMetatile(canvas, renderMt, layerType,
                 { bottom: true, middle: true, top: true });

  const cell = canvas.parentElement;
  if (cell) {
    cell.style.borderColor = LAYER_COLORS[layerType];
    cell.classList.toggle("changed", state.pendingChanges.has(id));
    cell.classList.toggle("dimmed", _isDimmed(mt, layerType));
  }
}

// ---------------------------------------------------------------------------
// Filter logic
// ---------------------------------------------------------------------------

export function applyFilter(newFilter) {
  state.activeFilter = newFilter;
  if (!state.container) return;

  state.container.querySelectorAll(".ts-filter-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.filter === newFilter);
  });

  state.container.querySelectorAll(".ts-cell").forEach(cell => {
    const id = parseInt(cell.dataset.id, 10);
    const mt = state.metatiles.find(m => m.id === id);
    if (!mt || !mt.tiles || newFilter === "all") {
      cell.classList.remove("dimmed");
      return;
    }
    const hasTop = mt.tiles.length >= 12
      && mt.tiles.slice(8, 12).some(t => t.tile !== 0 || t.palette !== 0);
    if (newFilter === "overlaps") {
      cell.classList.toggle("dimmed", !hasTop);
    } else if (newFilter === "behind") {
      cell.classList.toggle("dimmed", hasTop);
    }
  });
}

function _isDimmed(mt, layerType) {
  const f = state.activeFilter;
  if (f === "all") return false;
  if (!mt.tiles || mt.tiles.length < 12) return false;
  const hasTop = mt.tiles.slice(8, 12).some(t => t.tile !== 0 || t.palette !== 0);
  if (f === "overlaps") return !hasTop;
  if (f === "behind") return hasTop;
  return false;
}
