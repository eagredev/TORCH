/**
 * history.js — Undo/redo stack for the Tileset Editor.
 *
 * Supports three change types:
 *   - "composition" — tile ref changes (which tiles go where)
 *   - "attribute" — behavior and layer_type changes
 *   - "pixel" — tile pixel data changes
 *
 * Each entry stores a full snapshot of the relevant data before the change,
 * so undo restores exactly what was there before.
 */

import {
  state, emit,
  METATILE_MODIFIED, TILE_MODIFIED, DIRTY_CHANGED,
  getEffectiveBehavior, getEffectiveLayerType,
} from "./state.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_HISTORY = 100;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _undoStack = [];
let _redoStack = [];

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function initHistory() {
  _undoStack = [];
  _redoStack = [];
}

/**
 * Snapshot the current state of a metatile BEFORE making a change.
 * Call this, then make your change, and the undo will restore this snapshot.
 *
 * @param {"composition"|"attribute"|"pixel"} type
 * @param {number} id - metatile ID (for composition/attribute) or tile index (for pixel)
 */
export function snapshotBeforeChange(type, id) {
  const entry = { type, id, before: _captureState(type, id) };
  _undoStack.push(entry);
  if (_undoStack.length > MAX_HISTORY) _undoStack.shift();
  _redoStack = [];
}

export function undo() {
  if (_undoStack.length === 0) return null;
  const entry = _undoStack.pop();

  // Capture current state for redo
  _redoStack.push({ type: entry.type, id: entry.id, before: _captureState(entry.type, entry.id) });

  // Restore
  _applyState(entry.type, entry.id, entry.before);

  if (entry.type === "pixel") {
    emit(TILE_MODIFIED, { tileIndex: entry.id });
  } else {
    emit(METATILE_MODIFIED, { id: entry.id });
  }
  emit(DIRTY_CHANGED);
  return entry;
}

export function redo() {
  if (_redoStack.length === 0) return null;
  const entry = _redoStack.pop();

  // Capture current state for undo
  _undoStack.push({ type: entry.type, id: entry.id, before: _captureState(entry.type, entry.id) });

  // Restore
  _applyState(entry.type, entry.id, entry.before);

  if (entry.type === "pixel") {
    emit(TILE_MODIFIED, { tileIndex: entry.id });
  } else {
    emit(METATILE_MODIFIED, { id: entry.id });
  }
  emit(DIRTY_CHANGED);
  return entry;
}

export function canUndo() { return _undoStack.length > 0; }
export function canRedo() { return _redoStack.length > 0; }

export function cleanup() {
  _undoStack = [];
  _redoStack = [];
}

// ---------------------------------------------------------------------------
// State capture
// ---------------------------------------------------------------------------

function _captureState(type, id) {
  if (type === "composition") {
    const mt = state.metatiles.find(m => m.id === id);
    const change = state.pendingChanges.get(id);
    const tiles = (change && change.tiles)
      ? change.tiles.map(t => ({ ...t }))
      : mt ? mt.tiles.map(t => ({ ...t })) : [];
    return { tiles };
  }

  if (type === "attribute") {
    const mt = state.metatiles.find(m => m.id === id);
    const change = state.pendingChanges.get(id);
    return {
      behavior: change && change.behavior != null ? change.behavior : (mt ? mt.behavior : 0),
      layer_type: change && change.layer_type != null ? change.layer_type : (mt ? mt.layer_type : 0),
      layer_action: change ? change.layer_action : undefined,
    };
  }

  if (type === "pixel") {
    // Capture the 64 pixels of the tile
    const pixels = _getTilePixels(id);
    return { pixels };
  }

  return {};
}

// ---------------------------------------------------------------------------
// State restoration
// ---------------------------------------------------------------------------

function _applyState(type, id, snapshot) {
  if (!snapshot) return;

  if (type === "composition") {
    const mt = state.metatiles.find(m => m.id === id);
    if (!mt) return;
    // Check if snapshot matches original
    const isOriginal = mt.tiles.every((t, i) =>
      snapshot.tiles[i] &&
      t.tile === snapshot.tiles[i].tile &&
      t.palette === snapshot.tiles[i].palette &&
      t.hflip === snapshot.tiles[i].hflip &&
      t.vflip === snapshot.tiles[i].vflip
    );
    if (isOriginal) {
      // Remove tiles from pending changes
      const change = state.pendingChanges.get(id);
      if (change) {
        delete change.tiles;
        if (Object.keys(change).length === 0) state.pendingChanges.delete(id);
      }
    } else {
      let change = state.pendingChanges.get(id);
      if (!change) { change = {}; state.pendingChanges.set(id, change); }
      change.tiles = snapshot.tiles.map(t => ({ ...t }));
    }
    return;
  }

  if (type === "attribute") {
    const mt = state.metatiles.find(m => m.id === id);
    if (!mt) return;
    let change = state.pendingChanges.get(id);

    // Restore behavior
    if (snapshot.behavior === mt.behavior) {
      if (change) delete change.behavior;
    } else {
      if (!change) { change = {}; state.pendingChanges.set(id, change); }
      change.behavior = snapshot.behavior;
    }

    // Restore layer_type
    if (snapshot.layer_type === mt.layer_type) {
      if (change) delete change.layer_type;
    } else {
      if (!change) { change = {}; state.pendingChanges.set(id, change); }
      change.layer_type = snapshot.layer_type;
    }

    // Restore layer_action
    if (snapshot.layer_action) {
      if (!change) { change = {}; state.pendingChanges.set(id, change); }
      change.layer_action = snapshot.layer_action;
    } else if (change) {
      delete change.layer_action;
    }

    // Clean up empty change entry
    if (change && Object.keys(change).length === 0) {
      state.pendingChanges.delete(id);
    }
    return;
  }

  if (type === "pixel") {
    _setTilePixels(id, snapshot.pixels);
    return;
  }
}

// ---------------------------------------------------------------------------
// Pixel helpers
// ---------------------------------------------------------------------------

function _getTilePixels(globalTileIdx) {
  const isPrimary = state.primaryTileOffset > 0 && globalTileIdx < state.primaryTileOffset;
  const localIdx = isPrimary ? globalTileIdx : (globalTileIdx - state.primaryTileOffset);
  const pixels = isPrimary ? state.primaryPixels : state.tilePixels;
  const sheetW = isPrimary ? state.primarySheetW : state.tileSheetW;

  if (!pixels || !sheetW) return new Array(64).fill(0);

  const tilesPerRow = sheetW / 8;
  const tileCol = localIdx % tilesPerRow;
  const tileRow = Math.floor(localIdx / tilesPerRow);
  const baseX = tileCol * 8;
  const baseY = tileRow * 8;

  const result = [];
  for (let py = 0; py < 8; py++) {
    for (let px = 0; px < 8; px++) {
      result.push(pixels[(baseY + py) * sheetW + (baseX + px)] || 0);
    }
  }
  return result;
}

function _setTilePixels(globalTileIdx, pixelData) {
  if (!pixelData || pixelData.length !== 64) return;

  const isPrimary = state.primaryTileOffset > 0 && globalTileIdx < state.primaryTileOffset;
  const localIdx = isPrimary ? globalTileIdx : (globalTileIdx - state.primaryTileOffset);
  const pixels = isPrimary ? state.primaryPixels : state.tilePixels;
  const sheetW = isPrimary ? state.primarySheetW : state.tileSheetW;

  if (!pixels || !sheetW) return;

  const tilesPerRow = sheetW / 8;
  const tileCol = localIdx % tilesPerRow;
  const tileRow = Math.floor(localIdx / tilesPerRow);
  const baseX = tileCol * 8;
  const baseY = tileRow * 8;

  let changed = false;
  for (let py = 0; py < 8; py++) {
    for (let px = 0; px < 8; px++) {
      const idx = (baseY + py) * sheetW + (baseX + px);
      const newVal = pixelData[py * 8 + px];
      if (pixels[idx] !== newVal) {
        pixels[idx] = newVal;
        changed = true;
      }
    }
  }

  // Update pixel change tracking
  if (changed) {
    state.tilePixelChanges.set(globalTileIdx, true);
  } else {
    state.tilePixelChanges.delete(globalTileIdx);
  }
}
