/**
 * clipboard.js — Copy/paste system for the Tileset Editor.
 *
 * Two separate clipboards:
 *   1. Tile clipboard — holds metatile tile refs (full metatile, or a single layer)
 *   2. Behavior clipboard — holds a behavior value
 *
 * Keyboard shortcuts (two-key chords starting with 'c' for copy, 'v' for paste):
 *   c + \ = copy full metatile (all 12 tile refs)
 *   c + a = copy top layer (tiles 8-11)
 *   c + s = copy middle layer (tiles 4-7)
 *   c + d = copy bottom layer (tiles 0-3)
 *   c + b = copy behavior
 *
 *   v + \ = paste full metatile
 *   v + a = paste to top layer
 *   v + s = paste to middle layer
 *   v + d = paste to bottom layer
 *   v + b = paste behavior
 */

import {
  state, emit,
  METATILE_MODIFIED, DIRTY_CHANGED,
  getSelectedMetatile, getEffectiveBehavior,
  addChange, showToast,
} from "./state.js";
import { snapshotBeforeChange } from "./history.js";

// ---------------------------------------------------------------------------
// Clipboard state
// ---------------------------------------------------------------------------

/** Tile clipboard: { type: "metatile"|"layer", tiles: [...] } */
let _tileClip = null;

/** Behavior clipboard: number or null */
let _behaviorClip = null;

// ---------------------------------------------------------------------------
// Copy operations
// ---------------------------------------------------------------------------

export function copyMetatile() {
  const mt = getSelectedMetatile();
  if (!mt || !mt.tiles) return false;
  const tiles = _getWorkingTiles(mt);
  _tileClip = { type: "metatile", tiles: tiles.map(t => ({ ...t })) };
  showToast("Copied metatile");
  return true;
}

export function copyLayer(layerIdx) {
  const mt = getSelectedMetatile();
  if (!mt || !mt.tiles) return false;
  const tiles = _getWorkingTiles(mt);
  const start = layerIdx * 4;
  const layerTiles = tiles.slice(start, start + 4).map(t => ({ ...t }));
  const names = ["bottom", "middle", "top"];
  _tileClip = { type: "layer", tiles: layerTiles };
  showToast(`Copied ${names[layerIdx]} layer`);
  return true;
}

export function copyBehavior() {
  const mt = getSelectedMetatile();
  if (!mt) return false;
  _behaviorClip = getEffectiveBehavior(mt);
  const beh = state.behaviors.find(b => b.value === _behaviorClip);
  showToast(`Copied behavior: ${beh ? beh.name : _behaviorClip}`);
  return true;
}

// ---------------------------------------------------------------------------
// Paste operations
// ---------------------------------------------------------------------------

export function pasteMetatile() {
  if (!_tileClip || _tileClip.type !== "metatile") {
    showToast("Nothing to paste (copy a metatile first)");
    return false;
  }
  const mt = getSelectedMetatile();
  if (!mt) return false;

  snapshotBeforeChange("composition", mt.id);
  _ensureTilesCopy(mt);
  const entry = state.pendingChanges.get(mt.id);
  for (let i = 0; i < 12 && i < _tileClip.tiles.length; i++) {
    entry.tiles[i] = { ..._tileClip.tiles[i] };
  }
  emit(METATILE_MODIFIED, { id: mt.id });
  emit(DIRTY_CHANGED);
  showToast("Pasted metatile");
  return true;
}

export function pasteLayer(layerIdx) {
  if (!_tileClip || _tileClip.type !== "layer") {
    showToast("Nothing to paste (copy a layer first)");
    return false;
  }
  const mt = getSelectedMetatile();
  if (!mt) return false;

  snapshotBeforeChange("composition", mt.id);
  _ensureTilesCopy(mt);
  const entry = state.pendingChanges.get(mt.id);
  const start = layerIdx * 4;
  for (let i = 0; i < 4 && i < _tileClip.tiles.length; i++) {
    entry.tiles[start + i] = { ..._tileClip.tiles[i] };
  }
  const names = ["bottom", "middle", "top"];
  emit(METATILE_MODIFIED, { id: mt.id });
  emit(DIRTY_CHANGED);
  showToast(`Pasted to ${names[layerIdx]} layer`);
  return true;
}

export function pasteBehavior() {
  if (_behaviorClip == null) {
    showToast("Nothing to paste (copy a behavior first)");
    return false;
  }
  const mt = getSelectedMetatile();
  if (!mt) return false;
  addChange(mt.id, "behavior", _behaviorClip);
  const beh = state.behaviors.find(b => b.value === _behaviorClip);
  showToast(`Pasted behavior: ${beh ? beh.name : _behaviorClip}`);
  return true;
}

// ---------------------------------------------------------------------------
// Clipboard state queries
// ---------------------------------------------------------------------------

export function hasTileClip() { return _tileClip != null; }
export function getTileClipType() { return _tileClip ? _tileClip.type : null; }
export function hasBehaviorClip() { return _behaviorClip != null; }

// ---------------------------------------------------------------------------
// Keyboard chord handler
// ---------------------------------------------------------------------------

let _chordKey = null;   // 'c' or 'v' (first key of chord)
let _chordTimer = null; // timeout to cancel chord

export function handleChordKeydown(e) {
  // Don't trigger when typing in inputs
  const tag = e.target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return false;

  const key = e.key.toLowerCase();

  // First key of chord
  if (!_chordKey && (key === "c" || key === "v")) {
    _chordKey = key;
    _chordTimer = setTimeout(() => { _chordKey = null; }, 500);
    return false; // don't consume yet — might not be a chord
  }

  // Second key of chord
  if (_chordKey) {
    clearTimeout(_chordTimer);
    const first = _chordKey;
    _chordKey = null;

    if (first === "c") {
      // Copy
      if (key === "\\") { e.preventDefault(); return copyMetatile(); }
      if (key === "a") { e.preventDefault(); return copyLayer(2); }  // top
      if (key === "s") { e.preventDefault(); return copyLayer(1); }  // middle
      if (key === "d") { e.preventDefault(); return copyLayer(0); }  // bottom
      if (key === "b") { e.preventDefault(); return copyBehavior(); }
    } else if (first === "v") {
      // Paste
      if (key === "\\") { e.preventDefault(); return pasteMetatile(); }
      if (key === "a") { e.preventDefault(); return pasteLayer(2); }  // top
      if (key === "s") { e.preventDefault(); return pasteLayer(1); }  // middle
      if (key === "d") { e.preventDefault(); return pasteLayer(0); }  // bottom
      if (key === "b") { e.preventDefault(); return pasteBehavior(); }
    }
  }

  return false;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _getWorkingTiles(mt) {
  const change = state.pendingChanges.get(mt.id);
  if (change && change.tiles) return change.tiles;
  return mt.tiles ? [...mt.tiles] : [];
}

function _ensureTilesCopy(mt) {
  let entry = state.pendingChanges.get(mt.id);
  if (!entry) {
    entry = {};
    state.pendingChanges.set(mt.id, entry);
  }
  if (!entry.tiles) {
    entry.tiles = mt.tiles.map(t => ({ ...t }));
  }
}

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------

export function cleanupClipboard() {
  _chordKey = null;
  if (_chordTimer) clearTimeout(_chordTimer);
  _chordTimer = null;
  // Don't clear clipboards — they persist across metatile selections
}
