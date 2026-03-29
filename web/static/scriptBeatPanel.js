/**
 * TORCH IDE — Script Beat Panel.
 * TORCH_MODULE
 *
 * Adapter that wraps viz/beatList.js for embedding in the IDE left panel's
 * "Beats" tab. Creates a container, calls beatList.init/cleanup, and handles
 * CSS adjustments for the narrower panel width.
 *
 * Exports: initBeatPanel(parentEl), cleanupBeatPanel()
 */

import * as beatList from "./views/viz/beatList.js";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _parentEl = null;
let _containerEl = null;
let _active = false;

// ---------------------------------------------------------------------------
// Init / Cleanup
// ---------------------------------------------------------------------------

export function initBeatPanel(parentEl) {
  if (_active) return;
  _parentEl = parentEl;

  _containerEl = document.createElement("div");
  _containerEl.className = "ide-beat-panel";
  _containerEl.style.cssText = "flex:1;overflow:hidden;display:flex;flex-direction:column;";
  _parentEl.appendChild(_containerEl);

  beatList.init(_containerEl);
  _active = true;

  // Auto-focus for keyboard nav
  requestAnimationFrame(() => {
    if (_containerEl) _containerEl.focus();
  });
}

export function cleanupBeatPanel() {
  if (!_active) return;

  beatList.cleanup();
  if (_containerEl && _containerEl.parentNode) {
    _containerEl.remove();
  }
  _containerEl = null;
  _parentEl = null;
  _active = false;
}

export function isActive() { return _active; }
