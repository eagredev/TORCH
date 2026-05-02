/**
 * state.js — Central state module for the Tileset Editor.
 * Architectural keystone: every other tileset module imports from here.
 * No tileset module imports from any other tileset module — only from state.
 *
 * Follows the viz/state.js pattern: event bus + state singleton.
 */

import { api, postApi } from "../../app.js";

// ---------------------------------------------------------------------------
// Event bus (lightweight, built on browser EventTarget)
// ---------------------------------------------------------------------------

const _bus = new EventTarget();

export function emit(name, detail) {
  _bus.dispatchEvent(new CustomEvent(name, { detail }));
}

export function on(name, fn) {
  const handler = e => fn(e.detail);
  _bus.addEventListener(name, handler);
  return handler;
}

export function off(name, handler) {
  _bus.removeEventListener(name, handler);
}

// ---------------------------------------------------------------------------
// Event name constants
// ---------------------------------------------------------------------------

export const METATILE_SELECTED = "metatile-selected";
export const TILE_SELECTED = "tile-selected";
export const MODE_CHANGED = "mode-changed";
export const METATILE_MODIFIED = "metatile-modified";
export const TILE_MODIFIED = "tile-modified";
export const DIRTY_CHANGED = "dirty-changed";
export const SAVE_COMPLETED = "save-completed";
export const GRID_NEEDS_UPDATE = "grid-needs-update";
export const DETAIL_NEEDS_UPDATE = "detail-needs-update";
export const WIZARD_STARTED = "wizard-started";
export const WIZARD_EXITED = "wizard-exited";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const LAYER_NAMES = ["Normal", "Covered", "Split"];

export const LAYER_COLORS = [
  "rgba(150, 150, 150, 0.6)",  // Normal — subtle gray
  "rgba(91, 160, 208, 0.7)",   // Covered — blue
  "rgba(74, 222, 128, 0.7)",   // Split — green
];

export const CHANGED_COLOR = "rgba(248, 208, 48, 0.8)";

export const TILE_POSITIONS = [
  { x: 0, y: 0 },  // top-left
  { x: 8, y: 0 },  // top-right
  { x: 0, y: 8 },  // bottom-left
  { x: 8, y: 8 },  // bottom-right
];

// ---------------------------------------------------------------------------
// State singleton
// ---------------------------------------------------------------------------

export const state = {
  // Tileset identity
  primaryName: "",
  secondaryName: "",
  activeTier: "secondary",       // which tileset the user is editing

  // Loaded data — secondary tileset
  metatiles: [],                  // full metatile data from API
  behaviors: [],                  // [{value, name}]
  tilesImg: null,                 // loaded Image for secondary tiles.png (fallback)
  tilesImgLoaded: false,
  tilePixels: null,               // Uint8Array of palette indices
  tileSheetW: 0,
  tileSheetH: 0,
  palettes: [],                   // [[r,g,b] x16] x16

  // Loaded data — primary tileset
  primaryImg: null,
  primaryPixels: null,
  primarySheetW: 0,
  primarySheetH: 0,
  primaryPalettes: [],
  primaryTileOffset: 0,           // NUM_TILES_IN_PRIMARY (512)
  primaryTilesetName: "",         // resolved from layouts.json

  // Import detection
  frImportPattern: false,

  // Selection
  selectedId: null,               // currently selected metatile id
  activeFilter: "all",            // "all" | "overlaps" | "behind"
  layerOverrides: null,           // null or {bottom, middle, top} booleans
  activeMode: "layers",           // "compose" | "behavior" | "layers" | "pixel"

  // Edit tracking
  pendingChanges: new Map(),      // id -> {layer_type?, behavior?, layer_action?, tiles?}
  tilePixelChanges: new Map(),    // global tile index -> true (tiles with modified pixels)

  // Wizard state
  wizardMode: false,
  wizardQueue: [],
  wizardIndex: 0,

  // DOM references
  container: null,
  gridCanvases: new Map(),
};

// ---------------------------------------------------------------------------
// Data helpers
// ---------------------------------------------------------------------------

export function getEffectiveLayerType(mt) {
  const change = state.pendingChanges.get(mt.id);
  if (change && change.layer_type != null) return change.layer_type;
  return mt.layer_type;
}

export function getEffectiveBehavior(mt) {
  const change = state.pendingChanges.get(mt.id);
  if (change && change.behavior != null) return change.behavior;
  return mt.behavior;
}

export function getSelectedMetatile() {
  if (state.selectedId == null) return null;
  return state.metatiles.find(m => m.id === state.selectedId) || null;
}

export function defaultToggles(layerType) {
  switch (layerType) {
    case 0: return { bottom: false, middle: true, top: true };   // Normal
    case 1: return { bottom: true, middle: true, top: false };   // Covered
    case 2: return { bottom: true, middle: false, top: true };   // Split
    default: return { bottom: true, middle: true, top: true };
  }
}

// ---------------------------------------------------------------------------
// Change tracking
// ---------------------------------------------------------------------------

/** Hook for undo system — set by tilesets.js to avoid circular import. */
let _beforeChangeHook = null;
export function setBeforeChangeHook(fn) { _beforeChangeHook = fn; }

export function addChange(id, field, value) {
  const mt = state.metatiles.find(m => m.id === id);
  if (!mt) return;

  // Snapshot for undo before the change
  if (_beforeChangeHook) _beforeChangeHook("attribute", id);

  let entry = state.pendingChanges.get(id);
  if (!entry) {
    entry = {};
    state.pendingChanges.set(id, entry);
  }
  entry[field] = value;

  // If value matches original, remove the field
  if (field === "layer_type" && value === mt.layer_type) {
    delete entry.layer_type;
  }
  if (field === "behavior" && value === mt.behavior) {
    delete entry.behavior;
  }

  // If entry is empty, remove from map
  if (Object.keys(entry).length === 0) {
    state.pendingChanges.delete(id);
  }

  emit(DIRTY_CHANGED);
}

// ---------------------------------------------------------------------------
// Save
// ---------------------------------------------------------------------------

export async function doSave() {
  if (state.pendingChanges.size === 0) return;

  const changes = [];
  for (const [id, entry] of state.pendingChanges) {
    const obj = { id };
    if (entry.layer_type != null) obj.layer_type = entry.layer_type;
    if (entry.layer_action) obj.layer_action = entry.layer_action;
    if (entry.behavior != null) obj.behavior = entry.behavior;
    if (!obj.layer_type && !obj.layer_action && !obj.behavior && obj.behavior !== 0) continue;
    changes.push(obj);
  }

  const payload = { changes };
  if (state.frImportPattern) payload.fr_import_fix = true;

  const name = state.secondaryName || state.primaryName;
  const res = await postApi(`/metatiles/${encodeURIComponent(name)}/save`, payload);

  if (res && (res.ok !== false) && !res.error) {
    // Apply changes to local data
    for (const [id, entry] of state.pendingChanges) {
      const mt = state.metatiles.find(m => m.id === id);
      if (mt) {
        if (entry.layer_type != null) mt.layer_type = entry.layer_type;
        if (entry.behavior != null) mt.behavior = entry.behavior;
      }
    }
    state.pendingChanges.clear();
    emit(SAVE_COMPLETED, { count: changes.length });
    emit(DIRTY_CHANGED);
    return { ok: true, count: changes.length };
  } else {
    const error = (res && res.error) || "Unknown error";
    return { ok: false, error };
  }
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

export async function loadTilesetData(name) {
  const enc = encodeURIComponent(name);
  const [mtRes, bhRes, palRes] = await Promise.all([
    api(`/metatiles/${enc}`),
    api(`/metatiles/${enc}/behaviors`),
    api(`/metatiles/${enc}/palettes`),
  ]);

  if (mtRes && mtRes.ok !== false && !mtRes.error) {
    const data = mtRes.data || mtRes;
    state.metatiles = data.metatiles || [];
    state.secondaryName = data.name || name;
    state.activeTier = data.tier || "secondary";
    state.primaryTileOffset = data.primary_tile_offset || 0;
    state.frImportPattern = data.fr_import_pattern || false;
    state.primaryTilesetName = data.primary_tileset || "";
  } else {
    const msg = (mtRes && (mtRes.error || mtRes.message)) || "Failed to load metatile data";
    throw new Error(msg);
  }

  if (palRes && palRes.ok !== false && !palRes.error) {
    const pd = palRes.data || palRes;
    state.palettes = pd.palettes || [];
  }

  // Load raw pixel indices
  try {
    const pixRes = await fetch(`/api/metatiles/${enc}/pixels`);
    if (pixRes.ok) {
      state.tileSheetW = parseInt(pixRes.headers.get("X-Tile-Width") || "0", 10);
      state.tileSheetH = parseInt(pixRes.headers.get("X-Tile-Height") || "0", 10);
      const buf = await pixRes.arrayBuffer();
      state.tilePixels = new Uint8Array(buf);
    }
  } catch (_) {
    state.tilePixels = null;
  }

  // Load primary tileset data
  if (state.primaryTilesetName && state.primaryTileOffset > 0) {
    const priEnc = encodeURIComponent(state.primaryTilesetName);
    try {
      const [priPixRes, priPalRes] = await Promise.all([
        fetch(`/api/metatiles/${priEnc}/pixels`),
        api(`/metatiles/${priEnc}/palettes`),
      ]);
      if (priPixRes.ok) {
        state.primarySheetW = parseInt(priPixRes.headers.get("X-Tile-Width") || "0", 10);
        state.primarySheetH = parseInt(priPixRes.headers.get("X-Tile-Height") || "0", 10);
        const buf = await priPixRes.arrayBuffer();
        state.primaryPixels = new Uint8Array(buf);
      }
      if (priPalRes && priPalRes.ok !== false && !priPalRes.error) {
        const ppd = priPalRes.data || priPalRes;
        state.primaryPalettes = ppd.palettes || [];
      }
    } catch (_) {
      state.primaryPixels = null;
    }
    // Primary tiles.png as fallback Image
    try {
      state.primaryImg = await new Promise((resolve) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => resolve(null);
        img.src = `/api/assets/tilesets/${priEnc}/image`;
      });
    } catch (_) {
      state.primaryImg = null;
    }
  }

  if (bhRes && bhRes.ok !== false && !bhRes.error) {
    const data = bhRes.data || bhRes;
    state.behaviors = data.behaviors || [];
  } else {
    state.behaviors = [];
  }
}

export function loadTilesImage(name) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      state.tilesImg = img;
      state.tilesImgLoaded = true;
      resolve(true);
    };
    img.onerror = () => {
      state.tilesImg = null;
      state.tilesImgLoaded = true;
      resolve(false);
    };
    img.src = `/api/assets/tilesets/${encodeURIComponent(name)}/image`;
  });
}

// ---------------------------------------------------------------------------
// Toast utility
// ---------------------------------------------------------------------------

export function showToast(message) {
  const existing = document.querySelector(".ts-toast");
  if (existing) existing.remove();

  const toast = document.createElement("div");
  toast.className = "ts-toast";
  toast.textContent = message;
  document.body.appendChild(toast);

  requestAnimationFrame(() => toast.classList.add("visible"));

  setTimeout(() => {
    toast.classList.remove("visible");
    setTimeout(() => toast.remove(), 300);
  }, 2500);
}

// ---------------------------------------------------------------------------
// Reset
// ---------------------------------------------------------------------------

export function resetState() {
  state.primaryName = "";
  state.secondaryName = "";
  state.activeTier = "secondary";
  state.metatiles = [];
  state.behaviors = [];
  state.tilesImg = null;
  state.tilesImgLoaded = false;
  state.tilePixels = null;
  state.tileSheetW = 0;
  state.tileSheetH = 0;
  state.palettes = [];
  state.primaryImg = null;
  state.primaryPixels = null;
  state.primarySheetW = 0;
  state.primarySheetH = 0;
  state.primaryPalettes = [];
  state.primaryTilesetName = "";
  state.primaryTileOffset = 0;
  state.frImportPattern = false;
  state.selectedId = null;
  state.activeFilter = "all";
  state.layerOverrides = null;
  state.activeMode = "layers";
  state.pendingChanges.clear();
  state.tilePixelChanges.clear();
  state.wizardMode = false;
  state.wizardQueue = [];
  state.wizardIndex = 0;
  state.container = null;
  state.gridCanvases.clear();
}
