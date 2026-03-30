/**
 * TORCH IDE — Script Editor Drawer (bottom dock).
 *
 * Embeds the existing viz/ script editor modules in a bottom-docking drawer.
 * Opens contextually from NPC "Edit Script" or Ctrl+E.
 * Listens for IDE_OPEN_SCRIPT / IDE_CLOSE_SCRIPT events.
 *
 * The drawer reuses the FULL visualizer module (views/visualizer.js) by
 * rendering it into the drawer body. This avoids duplicating any viz/ logic.
 */

import { esc } from "./utils.js";
import {
  ideOn, ideEmit,
  IDE_OPEN_SCRIPT, IDE_CLOSE_SCRIPT, IDE_EVENT_SELECTED,
} from "./ide.js";
import { isScriptsModeActive } from "./scriptsMode.js";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _container = null;      // .ide-drawer element
let _headerEl = null;
let _bodyEl = null;
let _vizCleanup = null;     // cleanup function from loaded visualizer
let _currentMap = null;
let _currentScript = null;
let _unsubs = [];
let _keyHandler = null;

// ---------------------------------------------------------------------------
// Init / Cleanup
// ---------------------------------------------------------------------------

export function initScriptDrawer(container) {
  _container = container;

  // Build drawer chrome (header is always present, body loads on demand)
  _headerEl = document.createElement("div");
  _headerEl.className = "ide-drawer-header";
  _headerEl.innerHTML = `
    <span class="ide-drawer-title">Script Editor</span>
    <span class="ide-drawer-script" id="ide-drawer-script-label" style="color:var(--text-muted);font-size:0.75rem"></span>
    <button class="ide-drawer-close" id="ide-drawer-close" title="Close (Escape)">&times;</button>
  `;
  container.appendChild(_headerEl);

  _bodyEl = document.createElement("div");
  _bodyEl.className = "ide-drawer-body";
  container.appendChild(_bodyEl);

  // Close button
  document.getElementById("ide-drawer-close").addEventListener("click", _close);

  // Listen for script open/close events
  _unsubs.push(ideOn(IDE_OPEN_SCRIPT, _onOpenScript));
  _unsubs.push(ideOn(IDE_CLOSE_SCRIPT, _close));

  // Ctrl+E toggles the drawer
  _keyHandler = (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" ||
        e.target.isContentEditable) return;
    if (e.ctrlKey && e.key === "e") {
      e.preventDefault();
      if (_isOpen()) {
        _close();
      }
      // Ctrl+E without a script selected does nothing (need context)
    }
  };
  document.addEventListener("keydown", _keyHandler);
}

export function cleanupScriptDrawer() {
  for (const unsub of _unsubs) unsub();
  _unsubs = [];

  if (_keyHandler) {
    document.removeEventListener("keydown", _keyHandler);
    _keyHandler = null;
  }

  _cleanupViz();
  _container = null;
  _headerEl = null;
  _bodyEl = null;
}

// ---------------------------------------------------------------------------
// Open / Close
// ---------------------------------------------------------------------------

async function _onOpenScript(detail) {
  if (!detail || !detail.mapName || !detail.scriptName) return;

  // In Scripts Mode, the scriptsMode controller handles script loading
  if (isScriptsModeActive()) return;

  // Already showing this script?
  if (_isOpen() && _currentMap === detail.mapName &&
      _currentScript === detail.scriptName) {
    return;
  }

  _currentMap = detail.mapName;
  _currentScript = detail.scriptName;

  // Update label
  const label = document.getElementById("ide-drawer-script-label");
  if (label) {
    label.textContent = `${detail.mapName} / ${detail.scriptName}`;
  }

  // Show drawer
  const main = document.getElementById("ide-main");
  if (main) main.classList.add("drawer-open");

  // Clean up previous viz instance
  _cleanupViz();

  // Load the visualizer into the drawer body
  // We set the hash temporarily so the visualizer picks up the map/script
  const prevHash = window.location.hash;
  const vizHash = `#/visualizer/${encodeURIComponent(detail.mapName)}/${encodeURIComponent(detail.scriptName)}`;

  try {
    // Temporarily set hash so the visualizer's _parseRoute() picks up
    // the map/script context.  replaceState changes the hash synchronously
    // without firing hashchange, so the SPA router won't navigate away.
    history.replaceState(null, "", vizHash);

    const viz = await import("./views/visualizer.js");
    _bodyEl.innerHTML = "";
    await viz.render(_bodyEl);
    _vizCleanup = viz.cleanup;
  } catch (err) {
    _bodyEl.innerHTML = `<div style="padding:1rem;color:var(--status-error)">${esc(err.message)}</div>`;
  }

  // Always restore hash to IDE route
  history.replaceState(null, "", prevHash || "#/studio");
}

function _close() {
  _cleanupViz();
  _currentMap = null;
  _currentScript = null;

  const main = document.getElementById("ide-main");
  if (main) main.classList.remove("drawer-open");

  if (_bodyEl) _bodyEl.innerHTML = "";

  const label = document.getElementById("ide-drawer-script-label");
  if (label) label.textContent = "";
}

function _isOpen() {
  const main = document.getElementById("ide-main");
  return main && main.classList.contains("drawer-open");
}

function _cleanupViz() {
  if (_vizCleanup) {
    _vizCleanup();
    _vizCleanup = null;
  }
}

// ---------------------------------------------------------------------------
// Public: open script drawer programmatically
// ---------------------------------------------------------------------------

export function openScript(mapName, scriptName) {
  ideEmit(IDE_OPEN_SCRIPT, { mapName, scriptName });
}

export function closeScript() {
  _close();
}
