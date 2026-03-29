/**
 * history.js — Undo/redo stack for the Script Editor.
 * Each entry is a source string snapshot.
 */

import { state, resimulate, setDirty } from "./state.js";

const MAX_HISTORY = 50;
let _undoStack = [];
let _redoStack = [];
let _lastSaved = "";

export function initHistory() {
  _undoStack = [];
  _redoStack = [];
  _lastSaved = state.source;
}

export function pushHistory(oldSource) {
  _undoStack.push(oldSource);
  if (_undoStack.length > MAX_HISTORY) _undoStack.shift();
  _redoStack = [];
}

export async function undo() {
  if (_undoStack.length === 0) return;
  _redoStack.push(state.source);
  const prev = _undoStack.pop();
  const result = await resimulate(prev);
  setDirty(prev !== _lastSaved);
  return result;
}

export async function redo() {
  if (_redoStack.length === 0) return;
  _undoStack.push(state.source);
  const next = _redoStack.pop();
  const result = await resimulate(next);
  setDirty(next !== _lastSaved);
  return result;
}

export function markSaved() {
  _lastSaved = state.source;
}

export function canUndo() { return _undoStack.length > 0; }
export function canRedo() { return _redoStack.length > 0; }

export function cleanup() {
  _undoStack = [];
  _redoStack = [];
  _lastSaved = "";
}
