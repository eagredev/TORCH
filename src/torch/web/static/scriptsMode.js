/**
 * TORCH IDE — Scripts Mode Controller.
 * TORCH_MODULE
 *
 * Master controller for the third IDE mode. Manages:
 * - Mode enter/exit lifecycle
 * - Script loading via viz/state.js
 * - Bus bridge between IDE events and viz events
 * - Transport bar placement in IDE status area
 * - Overlay creation/cleanup
 *
 * Exports: initScriptsMode(), cleanupScriptsMode()
 */

import { api } from "./app.js";
import {
  ideOn, ideEmit,
  IDE_MODE_CHANGED, IDE_MAP_SELECTED, IDE_OPEN_SCRIPT,
  IDE_CAMERA_CHANGED, IDE_SCRIPT_LOADED, IDE_SCRIPT_UNLOADED,
} from "./ide.js";
import { getCamera, getMapName, setHiddenNpcIds, clearHiddenNpcIds, setDimNonScriptEvents } from "./mapCanvas.js";
import {
  initScriptOverlay, cleanupScriptOverlay, setTransform,
} from "./scriptOverlay.js";
import {
  state, loadScene, goToBeat, cleanup as vizCleanup,
  on as vizOn, off as vizOff,
  FRAMES_UPDATED, BEAT_CHANGED, BEAT_BOUNDARY,
} from "./views/viz/state.js";
import * as transport from "./views/viz/transport.js";
import { initHistory, cleanup as historyCleanup } from "./views/viz/history.js";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _active = false;          // true when in scripts mode
let _scriptLoaded = false;    // true when a script is loaded in viz state
let _transportEl = null;      // transport bar container element
let _unsubs = [];             // IDE event bus unsubscribe functions
let _vizUnsubs = [];          // viz bus handler refs for cleanup

// Chain navigation state
let _chainSequence = null;    // [{ script, map }, ...] from chain data
let _chainPosition = -1;      // current index in _chainSequence

// ---------------------------------------------------------------------------
// Init / Cleanup
// ---------------------------------------------------------------------------

export function initScriptsMode() {
  _unsubs.push(ideOn(IDE_MODE_CHANGED, _onModeChanged));
  _unsubs.push(ideOn(IDE_CAMERA_CHANGED, _onCameraChanged));
  _unsubs.push(ideOn(IDE_OPEN_SCRIPT, _onOpenScript));
  _unsubs.push(ideOn(IDE_MAP_SELECTED, _onMapSelected));
}

export function cleanupScriptsMode() {
  if (_active) _exitScriptsMode();
  for (const unsub of _unsubs) unsub();
  _unsubs = [];
}

// ---------------------------------------------------------------------------
// Mode enter / exit
// ---------------------------------------------------------------------------

function _onModeChanged(detail) {
  if (detail.mode === "scripts" && !_active) {
    _enterScriptsMode();
  } else if (detail.mode !== "scripts" && _active) {
    _exitScriptsMode();
  }
}

function _enterScriptsMode() {
  _active = true;

  // Create the script overlay on top of the map canvas
  const canvasWrap = document.getElementById("ide-canvas-wrap");
  if (canvasWrap) {
    initScriptOverlay(canvasWrap);
  }

  // Sync initial camera
  const cam = getCamera();
  if (cam) setTransform(cam.panX, cam.panY, cam.zoom);

  // Create and show transport bar
  _createTransportBar();

  // Wire viz bus → IDE bus bridge
  const framesH = vizOn(FRAMES_UPDATED, () => {
    ideEmit(IDE_SCRIPT_LOADED, {
      mapName: state.mapName,
      scriptName: state.scriptName,
    });
  });
  _vizUnsubs.push({ event: FRAMES_UPDATED, handler: framesH });

  // Chain boundary navigation — seamless transition between scripts
  const boundaryH = vizOn(BEAT_BOUNDARY, (detail) => {
    _onBeatBoundary(detail.direction);
  });
  _vizUnsubs.push({ event: BEAT_BOUNDARY, handler: boundaryH });

  // Initialize history module
  initHistory();
}

function _exitScriptsMode() {
  // Unload script if loaded
  if (_scriptLoaded) {
    _unloadScript();
  }

  // Tear down transport bar
  _destroyTransportBar();

  // Cleanup overlay
  cleanupScriptOverlay();

  // Unwire viz bus handlers
  for (const { event, handler } of _vizUnsubs) {
    vizOff(event, handler);
  }
  _vizUnsubs = [];

  // Cleanup history
  historyCleanup();

  _active = false;
}

// ---------------------------------------------------------------------------
// Script loading
// ---------------------------------------------------------------------------

async function _onOpenScript(detail) {
  if (!_active) return; // let scriptDrawer handle it in other modes

  const mapName = detail.mapName || getMapName();
  const scriptName = detail.scriptName;
  if (!mapName || !scriptName) return;

  // If already loaded, do nothing
  if (_scriptLoaded && state.mapName === mapName && state.scriptName === scriptName) return;

  // Unload any current script first
  if (_scriptLoaded) _unloadScript();

  // Load the scene via viz state
  const result = await loadScene(mapName, scriptName);
  if (!result.ok) {
    console.warn("[ScriptsMode] Failed to load script:", result.error);
    return;
  }

  _scriptLoaded = true;

  // Hide map canvas NPC sprites for cast members (overlay draws them instead)
  const castIds = Object.values(state.cast).filter(v => typeof v === "number");
  if (castIds.length > 0) setHiddenNpcIds(castIds);
  setDimNonScriptEvents(true);

  // Sync camera transform now that frames are ready
  const cam = getCamera();
  if (cam) setTransform(cam.panX, cam.panY, cam.zoom);

  // Discover chain context for seamless navigation
  await _discoverChain(mapName, scriptName);

  // Notify IDE that script is loaded
  ideEmit(IDE_SCRIPT_LOADED, { mapName, scriptName });
}

function _unloadScript() {
  if (!_scriptLoaded) return;
  clearHiddenNpcIds();
  setDimNonScriptEvents(false);

  // Cleanup viz state
  vizCleanup();
  _scriptLoaded = false;
  _chainSequence = null;
  _chainPosition = -1;

  ideEmit(IDE_SCRIPT_UNLOADED, {});
}

// ---------------------------------------------------------------------------
// Chain navigation — seamless script transitions
// ---------------------------------------------------------------------------

async function _discoverChain(mapName, scriptName) {
  _chainSequence = null;
  _chainPosition = -1;

  try {
    const res = await api(`/chains/by-script/${encodeURIComponent(mapName)}/${encodeURIComponent(scriptName)}`);
    if (!res.ok || !res.data?.chains?.length) return;

    // Use the first (or only) chain
    const chainInfo = res.data.chains[0];
    const chainRes = await api(`/chains/${encodeURIComponent(chainInfo.name)}`);
    if (!chainRes.ok || !chainRes.data?.sequence) return;

    _chainSequence = chainRes.data.sequence;
    _chainPosition = _chainSequence.findIndex(
      s => s.script === scriptName && s.map === mapName
    );
  } catch (_) {
    // Chain discovery is optional — don't break script loading
  }
}

async function _onBeatBoundary(direction) {
  if (!_chainSequence || _chainPosition < 0) return;

  const nextPos = direction === "next" ? _chainPosition + 1 : _chainPosition - 1;
  if (nextPos < 0 || nextPos >= _chainSequence.length) return;

  const next = _chainSequence[nextPos];

  // Load the adjacent script
  const result = await loadScene(next.map, next.script);
  if (!result.ok) return;

  _scriptLoaded = true;
  _chainPosition = nextPos;

  // Update hidden NPCs for new cast
  const castIds = Object.values(state.cast).filter(v => typeof v === "number");
  if (castIds.length > 0) setHiddenNpcIds(castIds);
  else clearHiddenNpcIds();

  // Re-discover chain (updates _chainSequence if needed)
  await _discoverChain(next.map, next.script);

  // Sync camera
  const cam = getCamera();
  if (cam) setTransform(cam.panX, cam.panY, cam.zoom);

  // Jump to first or last beat depending on direction
  if (direction === "prev") {
    goToBeat(state.frames.length - 1);
  } else {
    goToBeat(0);
  }

  ideEmit(IDE_SCRIPT_LOADED, { mapName: next.map, scriptName: next.script });
}

// ---------------------------------------------------------------------------
// Camera sync
// ---------------------------------------------------------------------------

function _onCameraChanged(detail) {
  if (!_active) return;
  setTransform(detail.panX, detail.panY, detail.zoom);
}

// ---------------------------------------------------------------------------
// Map selection during scripts mode
// ---------------------------------------------------------------------------

function _onMapSelected(detail) {
  if (!_active) return;
  // If map changes while script is loaded, unload the script
  if (_scriptLoaded && detail.name !== state.mapName) {
    _unloadScript();
  }
}

// ---------------------------------------------------------------------------
// Transport bar
// ---------------------------------------------------------------------------

function _createTransportBar() {
  if (_transportEl) return;

  const statusBar = document.getElementById("ide-status");
  if (!statusBar) return;

  // Save status bar content, then replace it with transport
  _savedStatusHTML = statusBar.innerHTML;
  statusBar.innerHTML = "";
  statusBar.classList.add("ide-script-transport");

  _transportEl = statusBar; // reuse the status bar element
  transport.init(_transportEl);
}

let _savedStatusHTML = "";

function _destroyTransportBar() {
  transport.cleanup();

  const statusBar = document.getElementById("ide-status");
  if (statusBar) {
    statusBar.classList.remove("ide-script-transport");
    statusBar.innerHTML = _savedStatusHTML;
    _savedStatusHTML = "";
  }
  _transportEl = null;
}

// ---------------------------------------------------------------------------
// Public query
// ---------------------------------------------------------------------------

/** True if scripts mode is currently active. */
export function isScriptsModeActive() { return _active; }

/** True if a script is currently loaded in scripts mode. */
export function isScriptLoaded() { return _scriptLoaded; }

/**
 * Handle Escape key cascade: close editor → unload script → exit mode.
 * @param {function} setMode — toolbar's mode setter to exit scripts mode
 */
export function handleEscape(setMode) {
  if (!_active) return;

  // 1. If editing a beat, close the editor
  if (state.editingBeat >= 0) {
    import("./views/viz/state.js").then(({ closeEditor }) => closeEditor());
    return;
  }

  // 2. If a script is loaded, unload it
  if (_scriptLoaded) {
    _unloadScript();
    return;
  }

  // 3. Exit scripts mode entirely
  if (setMode) setMode("view");
}
