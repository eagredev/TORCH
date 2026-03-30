/**
 * TORCH IDE — View Context Protocol.
 * TORCH_MODULE
 *
 * Clean replacement for the hash-manipulation hack used by openToolModal().
 * Stores the currently selected map name so views can read it without
 * parsing window.location.hash.
 *
 * Exports: setViewContext, getViewContext, getMapFromHashOrContext
 */

let _mapName = null;

/** Set the current view context (called on IDE_MAP_SELECTED). */
export function setViewContext(mapName) { _mapName = mapName; }

/** Get the current view context. */
export function getViewContext() { return { mapName: _mapName }; }

/**
 * Get the map name from either the URL hash (standalone route) or the
 * IDE view context (panel/modal). Views can use this as a drop-in
 * replacement for hash parsing.
 */
export function getMapFromHashOrContext() {
  const hash = window.location.hash || "";
  const parts = hash.slice(1).split("/").filter(Boolean);
  if (parts.length >= 2) return decodeURIComponent(parts[1]);
  return _mapName;
}
