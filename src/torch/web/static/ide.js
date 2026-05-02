/**
 * TORCH IDE — Unified Map-Centric Workspace.
 *
 * Main module: builds the three-panel layout, wires panel communication
 * via a shared event bus, and manages lifecycle.
 */

import { api, getExpansionVersion } from "./app.js";
import { esc } from "./utils.js";
import { initMapTree, cleanupMapTree } from "./mapTree.js";
import { initMapCanvas, cleanupMapCanvas } from "./mapCanvas.js";
import { initContextPanel, cleanupContextPanel } from "./contextPanel.js";
import { initToolbar, cleanupToolbar } from "./toolbar.js";
import { initScriptDrawer, cleanupScriptDrawer } from "./scriptDrawer.js";
import { initScriptsMode, cleanupScriptsMode } from "./scriptsMode.js";
import { initDexWidget, cleanupDexWidget } from "./dexStatusWidget.js";
import { initMusicWidget, cleanupMusicWidget } from "./musicStatusWidget.js";
import { initCollisionOverlay, cleanupCollisionOverlay } from "./collisionOverlay.js";
import { initWorldstatePanel, cleanupWorldstatePanel, injectWorldstateCSS } from "./worldstatePanel.js";

// ---------------------------------------------------------------------------
// IDE Event Bus (shared across panels)
// ---------------------------------------------------------------------------

export const ideBus = new EventTarget();

/** Dispatch a typed IDE event. */
export function ideEmit(type, detail) {
  ideBus.dispatchEvent(new CustomEvent(type, { detail }));
}

/** Listen for a typed IDE event. Returns a removal function. */
export function ideOn(type, fn) {
  const handler = (e) => fn(e.detail);
  ideBus.addEventListener(type, handler);
  return () => ideBus.removeEventListener(type, handler);
}

// Event types
export const IDE_MAP_SELECTED = "ide:map-selected";
export const IDE_EVENT_SELECTED = "ide:event-selected";
export const IDE_EVENT_DESELECTED = "ide:event-deselected";
export const IDE_COORDS_UPDATED = "ide:coords-updated";
export const IDE_MODE_CHANGED = "ide:mode-changed";
export const IDE_OPEN_SCRIPT = "ide:open-script";     // { mapName, scriptName }
export const IDE_CLOSE_SCRIPT = "ide:close-script";
export const IDE_CAMERA_CHANGED = "ide:camera-changed"; // { panX, panY, zoom }
export const IDE_SCRIPT_LOADED = "ide:script-loaded";   // { mapName, scriptName }
export const IDE_SCRIPT_UNLOADED = "ide:script-unloaded";
export const IDE_EVENT_UPDATED = "ide:event-updated";    // { mapName }

// Track selected map globally so toolbar can provide context to modals
let _currentMapName = null;

/** Get the currently selected map name (or null). */
export function getSelectedMap() { return _currentMapName; }

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _container = null;
let _statusMapEl = null;
let _statusCoordsEl = null;
let _statusBuildEl = null;
let _statusVersionEl = null;
let _coordsUnsub = null;
let _mapUnsub = null;
let _styleEl = null;
let _resizeCleanups = [];

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

export function render(container) {
  _container = container;
  container.innerHTML = "";

  // Inject IDE CSS (alongside torch.css)
  _injectCSS();

  // Build DOM structure
  const root = document.createElement("div");
  root.className = "ide-root";

  // 1. Toolbar
  const toolbar = document.createElement("div");
  toolbar.className = "ide-toolbar";
  toolbar.id = "ide-toolbar";
  root.appendChild(toolbar);

  // 2. Main content (three panels)
  const main = document.createElement("div");
  main.className = "ide-main";
  main.id = "ide-main";

  const left = document.createElement("div");
  left.className = "ide-left";
  left.id = "ide-left";

  // Resize handle between left and center
  const resizeLeft = document.createElement("div");
  resizeLeft.className = "ide-resize-handle";
  resizeLeft.id = "ide-resize-left";

  const center = document.createElement("div");
  center.className = "ide-center";
  center.id = "ide-center";

  // Resize handle between center and right
  const resizeRight = document.createElement("div");
  resizeRight.className = "ide-resize-handle";
  resizeRight.id = "ide-resize-right";

  const right = document.createElement("div");
  right.className = "ide-right";
  right.id = "ide-right";

  // Script editor drawer (bottom dock, spans all columns)
  const drawer = document.createElement("div");
  drawer.className = "ide-drawer";
  drawer.id = "ide-drawer";

  main.appendChild(left);
  main.appendChild(resizeLeft);
  main.appendChild(center);
  main.appendChild(resizeRight);
  main.appendChild(right);
  main.appendChild(drawer);
  root.appendChild(main);

  // 3. Status bar
  const status = document.createElement("div");
  status.className = "ide-status";
  status.id = "ide-status";
  status.innerHTML = `
    <span class="ide-status-item map-name" id="ide-status-map">No map selected</span>
    <span class="ide-status-item coords" id="ide-status-coords"></span>
    <span class="ide-status-item" id="ide-status-build">
      <span class="dot" style="background: var(--status-ok)"></span> Ready
    </span>
    <span class="ide-status-item" id="ide-status-version"></span>
  `;
  root.appendChild(status);

  container.appendChild(root);

  // Cache status bar elements
  _statusMapEl = document.getElementById("ide-status-map");
  _statusCoordsEl = document.getElementById("ide-status-coords");
  _statusBuildEl = document.getElementById("ide-status-build");
  _statusVersionEl = document.getElementById("ide-status-version");

  // Initialize panels
  initToolbar(document.getElementById("ide-toolbar"));
  initMapTree(document.getElementById("ide-left"));
  initMapCanvas(document.getElementById("ide-center"));
  initCollisionOverlay(document.getElementById("ide-canvas-wrap"));
  initContextPanel(document.getElementById("ide-right"));
  initScriptDrawer(document.getElementById("ide-drawer"));
  initScriptsMode();
  initMusicWidget(container);
  initDexWidget(container);
  injectWorldstateCSS();
  initWorldstatePanel(document.getElementById("ide-center"));

  // Wire resize handles
  _resizeCleanups.push(
    _initResize("ide-resize-left", "ide-left", "width", "torch-ide-left-w", 160, 400),
    _initResize("ide-resize-right", "ide-right", "width", "torch-ide-right-w", 180, 450, true),
  );

  // Restore saved panel widths
  _restorePanelWidth("ide-left", "torch-ide-left-w");
  _restorePanelWidth("ide-right", "torch-ide-right-w");

  // Wire status bar updates
  _coordsUnsub = ideOn(IDE_COORDS_UPDATED, (detail) => {
    if (_statusCoordsEl) {
      if (detail) {
        _statusCoordsEl.textContent = `(${detail.x}, ${detail.y})`;
      } else {
        _statusCoordsEl.textContent = "";
      }
    }
  });

  _mapUnsub = ideOn(IDE_MAP_SELECTED, (detail) => {
    _currentMapName = detail.name || null;
    if (_statusMapEl) {
      _statusMapEl.textContent = detail.name || "No map selected";
    }
    // Update window title for standalone mode
    document.title = detail.name
      ? `TORCH Studio \u2014 ${detail.name}`
      : "TORCH Studio";
  });

  // Load version info
  _loadVersion();
}

async function _loadVersion() {
  const ver = await getExpansionVersion();
  if (_statusVersionEl) {
    _statusVersionEl.textContent = ver ? `Expansion v${ver}` : "Vanilla";
  }
}

function _injectCSS() {
  const id = "ide-view-css";
  if (document.getElementById(id)) return;
  const link = document.createElement("link");
  link.id = id;
  link.rel = "stylesheet";
  link.href = "ide.css";
  document.head.appendChild(link);
  _styleEl = link;
}

// ---------------------------------------------------------------------------
// Panel resize
// ---------------------------------------------------------------------------

function _initResize(handleId, panelId, prop, storageKey, min, max, fromRight) {
  const handle = document.getElementById(handleId);
  const panel = document.getElementById(panelId);
  if (!handle || !panel) return () => {};

  let startX, startW;

  const onDown = (e) => {
    e.preventDefault();
    startX = e.clientX;
    startW = panel.getBoundingClientRect().width;
    document.body.style.cursor = "col-resize";
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  const onMove = (e) => {
    const delta = fromRight ? (startX - e.clientX) : (e.clientX - startX);
    const newW = Math.max(min, Math.min(startW + delta, max));
    panel.style.width = newW + "px";
    panel.style.flex = `0 0 ${newW}px`;
  };

  const onUp = () => {
    document.body.style.cursor = "";
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
    try { localStorage.setItem(storageKey, panel.getBoundingClientRect().width); } catch (_) {}
  };

  handle.addEventListener("mousedown", onDown);
  return () => handle.removeEventListener("mousedown", onDown);
}

function _restorePanelWidth(panelId, storageKey) {
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved) {
      const panel = document.getElementById(panelId);
      if (panel) {
        panel.style.width = saved + "px";
        panel.style.flex = `0 0 ${saved}px`;
      }
    }
  } catch (_) {}
}

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------

export function cleanup() {
  if (_coordsUnsub) _coordsUnsub();
  if (_mapUnsub) _mapUnsub();
  for (const fn of _resizeCleanups) fn();
  _coordsUnsub = null;
  _mapUnsub = null;
  _resizeCleanups = [];

  cleanupToolbar();
  cleanupMapTree();
  cleanupMapCanvas();
  cleanupCollisionOverlay();
  cleanupContextPanel();
  cleanupScriptDrawer();
  cleanupScriptsMode();
  cleanupMusicWidget();
  cleanupDexWidget();
  cleanupWorldstatePanel();

  if (_styleEl) {
    _styleEl.remove();
    _styleEl = null;
  }

  if (_container) {
    _container.innerHTML = "";
    _container = null;
  }

  _statusMapEl = null;
  _statusCoordsEl = null;
  _statusBuildEl = null;
  _statusVersionEl = null;
}
