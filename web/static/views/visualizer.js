/**
 * TORCH Web GUI — Script Editor (visualizer) shell.
 *
 * Thin wiring layer (~200 lines). All logic lives in viz/ modules.
 * Stream 236: Complete rewrite from 2844-line monolith.
 */

import * as stateModule from "./viz/state.js";
import {
  loadScene, listMaps, listScripts, saveScript, saveAndBuild,
  closeEditor, copyBeat, pasteBeat, on, off,
  DIRTY_CHANGED, FRAMES_UPDATED,
} from "./viz/state.js";
import * as historyModule from "./viz/history.js";
import { initHistory, undo, redo, markSaved } from "./viz/history.js";
import * as beatList from "./viz/beatList.js";
import * as canvas from "./viz/canvas.js";
import * as transport from "./viz/transport.js";
import * as source from "./viz/source.js";
import * as cast from "./viz/cast.js";
import * as editors from "./viz/editors/index.js";

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _onKeyDown = null;
let _onResizeMove = null;
let _onResizeUp = null;
let _beforeUnloadAttached = false;
let _dirtyHandler = null;
let _shortcutsOverlay = null;

// Handler + element references for cleanup (Fix 2.1 — listener leaks)
let _mapSelectHandler = null;
let _scriptSelectHandler = null;
let _resizeHandleHandler = null;
let _tabBarHandler = null;
let _framesHandler = null;
let _mapSelectEl = null;
let _scriptSelectEl = null;
let _resizeHandleEl = null;
let _tabBarEl = null;
let _controlsBarEl = null;

function _onBeforeUnload(e) {
  e.preventDefault();
  e.returnValue = "";
}

// ---------------------------------------------------------------------------
// Route parsing
// ---------------------------------------------------------------------------

function _parseRoute() {
  const hash = window.location.hash.slice(1) || "/visualizer";
  const parts = hash.split("/").filter(Boolean);
  return { mapName: parts[1] || "", scriptName: parts[2] || "" };
}

// ---------------------------------------------------------------------------
// render
// ---------------------------------------------------------------------------

export function render(container) {
  const { mapName: mapFromUrl, scriptName: scriptFromUrl } = _parseRoute();

  // -- DOM --
  container.innerHTML = `
<article class="viz-root">
  <div class="viz-header">
    <a href="#" class="viz-back-link" id="viz-back-link">\u2190</a>
    <span class="viz-title">Script Editor</span>
    <select id="viz-map-select" class="viz-selector">
      <option value="">-- map --</option>
    </select>
    <select id="viz-script-select" class="viz-selector">
      <option value="">-- script --</option>
    </select>
    <span class="viz-header-spacer"></span>
    <div class="viz-tab-bar" id="viz-tab-bar">
      <button class="viz-tab-btn active" data-tab="beats">Beats</button>
      <button class="viz-tab-btn" data-tab="canvas">Canvas</button>
    </div>
  </div>

  <div class="viz-workspace" id="viz-workspace" style="display:none;">
    <div class="viz-split">
      <div class="viz-pane-beats" id="viz-pane-beats">
        <div id="viz-beat-list-container" class="viz-beat-list-wrap"></div>
      </div>
      <div class="viz-resize-handle" id="viz-resize-handle"></div>
      <div class="viz-pane-canvas" id="viz-pane-canvas">
        <div class="viz-canvas-wrap">
          <canvas id="viz-canvas" class="viz-canvas"></canvas>
          <div id="viz-canvas-overlay" class="viz-canvas-overlay"></div>
        </div>
        <div id="viz-editor-container" class="viz-editor-overlay"></div>
      </div>
    </div>
    <div id="viz-side-panels" class="viz-side-panels"></div>
  </div>

  <div class="viz-footer" id="viz-footer" style="display:none;">
    <div class="viz-footer-left">
      <div id="viz-transport-container"></div>
      <div class="viz-beat-controls">
        <button class="viz-ctrl-btn" id="viz-ctrl-add" title="Add beat">+ Add</button>
        <button class="viz-ctrl-btn" id="viz-ctrl-copy" title="Copy beat">Copy</button>
        <button class="viz-ctrl-btn viz-ctrl-paste" id="viz-ctrl-paste" title="Paste beat" disabled>Paste</button>
      </div>
      <span class="viz-key-hints">j/k nav \u00B7 Enter edit \u00B7 a add \u00B7 c copy \u00B7 v paste \u00B7 d del</span>
    </div>
  </div>

  <div class="viz-empty" id="viz-empty">
    <p>Select a map and script above to begin editing.</p>
  </div>
</article>`;

  // -- DOM refs --
  const mapSelect = _mapSelectEl = document.getElementById("viz-map-select");
  const scriptSelect = _scriptSelectEl = document.getElementById("viz-script-select");
  const workspace = document.getElementById("viz-workspace");
  const footer = document.getElementById("viz-footer");
  const emptyState = document.getElementById("viz-empty");
  const beatPane = document.getElementById("viz-pane-beats");
  const canvasPane = document.getElementById("viz-pane-canvas");

  // -- Init modules --
  beatList.init(document.getElementById("viz-beat-list-container"));
  canvas.init(document.getElementById("viz-canvas"), document.getElementById("viz-canvas-overlay"));
  transport.init(document.getElementById("viz-transport-container"));
  editors.init(document.getElementById("viz-editor-container"));
  source.init(document.getElementById("viz-side-panels"));
  cast.init(document.getElementById("viz-side-panels"));

  // -- Beat controls (merged into footer) --
  _controlsBarEl = document.querySelector(".viz-beat-controls");
  const beatListContainer = document.getElementById("viz-beat-list-container");
  _controlsBarEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".viz-ctrl-btn");
    if (!btn) return;
    const id = btn.id;
    if (id === "viz-ctrl-add") {
      beatListContainer.dispatchEvent(new CustomEvent("beat-add-request", {
        bubbles: true,
        detail: { afterIndex: stateModule.state.currentBeat },
      }));
    } else if (id === "viz-ctrl-copy") {
      if (copyBeat(stateModule.state.currentBeat)) {
        _updatePasteBtn();
      }
    } else if (id === "viz-ctrl-paste") {
      if (stateModule.state.clipboard) {
        historyModule.pushHistory(stateModule.state.source);
        pasteBeat();
      }
    }
  });

  // Update paste button when frames change (clipboard may have been set)
  // Also relocate distance controls into canvas pane (transport rebuilds them)
  _framesHandler = on(FRAMES_UPDATED, () => {
    _updatePasteBtn();
    _relocateDistanceControls();
  });

  // -- Set back link to parent map or studio --
  const backLink = document.getElementById("viz-back-link");
  if (mapFromUrl) {
    backLink.textContent = `\u2190 ${mapFromUrl}`;
    backLink.href = `#/scripts/${mapFromUrl}`;
  } else {
    backLink.textContent = "\u2190 Studio";
    backLink.href = "#/studio";
  }
  // Guard: warn if dirty before navigating via back link
  backLink.addEventListener("click", (e) => {
    if (stateModule.state.dirty) {
      if (!confirm("You have unsaved changes. Discard and leave?")) {
        e.preventDefault();
      }
    }
  });

  // -- Populate map selector --
  listMaps().then(maps => {
    for (const map of maps) {
      const opt = document.createElement("option");
      opt.value = map.name;
      opt.textContent = map.name;
      mapSelect.appendChild(opt);
    }
    if (mapFromUrl) {
      mapSelect.value = mapFromUrl;
      mapSelect.dispatchEvent(new Event("change"));
    }
  });

  // -- Map change --
  _mapSelectHandler = async () => {
    const mapName = mapSelect.value;
    // Guard: warn if dirty before switching maps
    if (stateModule.state.dirty) {
      if (!confirm("You have unsaved changes. Discard and continue?")) {
        // Restore selector to current map
        mapSelect.value = stateModule.state.mapName || "";
        return;
      }
    }
    scriptSelect.innerHTML = '<option value="">-- script --</option>';
    if (!mapName) return;
    // Update back link to point to this map
    backLink.textContent = `\u2190 ${mapName}`;
    backLink.href = `#/scripts/${mapName}`;
    const scripts = await listScripts(mapName);
    for (const s of scripts) {
      const opt = document.createElement("option");
      opt.value = s.name || s;
      opt.textContent = s.name || s;
      scriptSelect.appendChild(opt);
    }
    if (scriptFromUrl && mapName === mapFromUrl) {
      scriptSelect.value = scriptFromUrl;
      scriptSelect.dispatchEvent(new Event("change"));
    }
  };
  mapSelect.addEventListener("change", _mapSelectHandler);

  // -- Script change --
  _scriptSelectHandler = async () => {
    const mapName = mapSelect.value;
    const scriptName = scriptSelect.value;
    if (!mapName || !scriptName) {
      workspace.style.display = "none";
      footer.style.display = "none";
      emptyState.style.display = "";
      return;
    }
    // Guard: warn if dirty before switching scripts
    if (stateModule.state.dirty) {
      if (!confirm("You have unsaved changes. Discard and continue?")) {
        // Restore selector to current script
        scriptSelect.value = stateModule.state.scriptName || "";
        return;
      }
    }
    workspace.style.display = "";
    footer.style.display = "";
    emptyState.style.display = "none";

    const result = await loadScene(mapName, scriptName);
    if (!result.ok) return;

    initHistory();
    const newHash = `#/visualizer/${mapName}/${scriptName}`;
    if (window.location.hash !== newHash) {
      history.replaceState(null, "", newHash);
    }
  };
  scriptSelect.addEventListener("change", _scriptSelectHandler);

  // -- Resizable split pane --
  const handle = _resizeHandleEl = document.getElementById("viz-resize-handle");
  let resizing = false, startX = 0, startWidth = 0;

  _resizeHandleHandler = (e) => {
    resizing = true;
    startX = e.clientX;
    startWidth = beatPane.offsetWidth;
    document.body.style.cursor = "col-resize";
    e.preventDefault();
  };
  handle.addEventListener("mousedown", _resizeHandleHandler);

  _onResizeMove = (e) => {
    if (!resizing) return;
    const delta = e.clientX - startX;
    const newWidth = Math.max(200, Math.min(startWidth + delta, window.innerWidth - 300));
    beatPane.style.flex = `0 0 ${newWidth}px`;
    localStorage.setItem("torch-viz-split", newWidth);
  };

  _onResizeUp = () => {
    if (resizing) {
      resizing = false;
      document.body.style.cursor = "";
    }
  };

  document.addEventListener("mousemove", _onResizeMove);
  document.addEventListener("mouseup", _onResizeUp);

  const savedSplit = localStorage.getItem("torch-viz-split");
  if (savedSplit) beatPane.style.flex = `0 0 ${savedSplit}px`;

  // -- Responsive tab bar --
  _tabBarEl = document.getElementById("viz-tab-bar");
  _tabBarHandler = (e) => {
    const btn = e.target.closest(".viz-tab-btn");
    if (!btn) return;
    const tab = btn.dataset.tab;
    document.querySelectorAll(".viz-tab-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    beatPane.classList.toggle("viz-tab-hidden", tab !== "beats");
    canvasPane.classList.toggle("viz-tab-hidden", tab === "beats");
  };
  _tabBarEl.addEventListener("click", _tabBarHandler);

  // -- Dirty state → beforeunload --
  _dirtyHandler = on(DIRTY_CHANGED, (isDirty) => {
    if (isDirty && !_beforeUnloadAttached) {
      window.addEventListener("beforeunload", _onBeforeUnload);
      _beforeUnloadAttached = true;
    } else if (!isDirty && _beforeUnloadAttached) {
      window.removeEventListener("beforeunload", _onBeforeUnload);
      _beforeUnloadAttached = false;
    }
    // Expose dirty state for global navigation guard (app.js)
    window._torchVisualizerDirty = isDirty;
  });

  // -- Global keyboard shortcuts --
  _onKeyDown = (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    const inInput = tag === "input" || tag === "textarea" || tag === "select";

    // Escape — close editor or shortcuts overlay
    if (e.key === "Escape") {
      if (_shortcutsOverlay) {
        _toggleShortcuts();
        return;
      }
      if (stateModule.state.editingBeat >= 0) {
        closeEditor();
        return;
      }
    }

    // Ctrl+S — save
    if (e.ctrlKey && !e.shiftKey && e.key === "s") {
      e.preventDefault();
      saveScript().then(() => markSaved());
      return;
    }
    // Ctrl+Shift+S — save & build
    if (e.ctrlKey && e.shiftKey && e.key === "S") {
      e.preventDefault();
      saveAndBuild().then(() => markSaved());
      return;
    }
    // Ctrl+Z — undo (skip in inputs)
    if (e.ctrlKey && !e.shiftKey && e.key === "z" && !inInput) {
      e.preventDefault();
      undo();
      return;
    }
    // Ctrl+Y or Ctrl+Shift+Z — redo (skip in inputs)
    if ((e.ctrlKey && e.key === "y") || (e.ctrlKey && e.shiftKey && e.key === "Z")) {
      if (!inInput) {
        e.preventDefault();
        redo();
        return;
      }
    }
    // ? — toggle shortcuts overlay
    if (e.key === "?" && !inInput) {
      _toggleShortcuts();
    }
  };

  document.addEventListener("keydown", _onKeyDown);
}

// ---------------------------------------------------------------------------
// Controls bar helpers
// ---------------------------------------------------------------------------

function _relocateDistanceControls() {
  const canvasPane = document.getElementById("viz-pane-canvas");
  if (!canvasPane) return;
  // Move any distance controls from the transport into the canvas pane
  document.querySelectorAll(".viz-distance-wrap").forEach(el => {
    if (el.parentElement !== canvasPane) {
      canvasPane.appendChild(el);
    }
  });
}

function _updatePasteBtn() {
  const btn = document.getElementById("viz-ctrl-paste");
  if (!btn) return;
  const hasClip = !!stateModule.state.clipboard;
  btn.disabled = !hasClip;
}

// ---------------------------------------------------------------------------
// Shortcuts overlay
// ---------------------------------------------------------------------------

function _toggleShortcuts() {
  if (_shortcutsOverlay) {
    _shortcutsOverlay.remove();
    _shortcutsOverlay = null;
    return;
  }
  _shortcutsOverlay = document.createElement("div");
  _shortcutsOverlay.className = "viz-shortcuts-overlay";
  _shortcutsOverlay.innerHTML = `
    <h3>Keyboard Shortcuts</h3>
    <table>
      <tr><td>j / \u2193</td><td>Next beat</td></tr>
      <tr><td>k / \u2191</td><td>Previous beat</td></tr>
      <tr><td>Enter</td><td>Edit beat</td></tr>
      <tr><td>Escape</td><td>Close editor</td></tr>
      <tr><td>a</td><td>Add beat</td></tr>
      <tr><td>d / Delete</td><td>Delete beat</td></tr>
      <tr><td>Ctrl+\u2191/\u2193</td><td>Move beat</td></tr>
      <tr><td>Space</td><td>Play / Pause</td></tr>
      <tr><td>Ctrl+S</td><td>Save</td></tr>
      <tr><td>Ctrl+Shift+S</td><td>Save &amp; Build</td></tr>
      <tr><td>Ctrl+Z</td><td>Undo</td></tr>
      <tr><td>Ctrl+Y</td><td>Redo</td></tr>
      <tr><td>?</td><td>This help</td></tr>
    </table>
    <p>Press ? or Escape to close</p>`;
  _shortcutsOverlay.addEventListener("click", () => _toggleShortcuts());
  document.body.appendChild(_shortcutsOverlay);
}

// ---------------------------------------------------------------------------
// cleanup
// ---------------------------------------------------------------------------

export function cleanup() {
  if (_onKeyDown) document.removeEventListener("keydown", _onKeyDown);
  if (_onResizeMove) document.removeEventListener("mousemove", _onResizeMove);
  if (_onResizeUp) document.removeEventListener("mouseup", _onResizeUp);
  if (_beforeUnloadAttached) window.removeEventListener("beforeunload", _onBeforeUnload);
  if (_dirtyHandler) off(DIRTY_CHANGED, _dirtyHandler);
  if (_framesHandler) off(FRAMES_UPDATED, _framesHandler);
  if (_shortcutsOverlay) { _shortcutsOverlay.remove(); _shortcutsOverlay = null; }

  // Remove selector / resize / tab bar listeners (Fix 2.1)
  if (_mapSelectEl && _mapSelectHandler) _mapSelectEl.removeEventListener("change", _mapSelectHandler);
  if (_scriptSelectEl && _scriptSelectHandler) _scriptSelectEl.removeEventListener("change", _scriptSelectHandler);
  if (_resizeHandleEl && _resizeHandleHandler) _resizeHandleEl.removeEventListener("mousedown", _resizeHandleHandler);
  if (_tabBarEl && _tabBarHandler) _tabBarEl.removeEventListener("click", _tabBarHandler);

  window._torchVisualizerDirty = false;

  beatList.cleanup();
  canvas.cleanup();
  transport.cleanup();
  editors.cleanup();
  source.cleanup();
  cast.cleanup();
  stateModule.cleanup();
  historyModule.cleanup();

  _onKeyDown = null;
  _onResizeMove = null;
  _onResizeUp = null;
  _beforeUnloadAttached = false;
  _dirtyHandler = null;
  _mapSelectHandler = null;
  _scriptSelectHandler = null;
  _resizeHandleHandler = null;
  _tabBarHandler = null;
  _framesHandler = null;
  _mapSelectEl = null;
  _scriptSelectEl = null;
  _resizeHandleEl = null;
  _tabBarEl = null;
  _controlsBarEl = null;
}
