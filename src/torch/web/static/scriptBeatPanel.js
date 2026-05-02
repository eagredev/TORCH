/**
 * TORCH IDE — Script Beat Panel.
 * TORCH_MODULE
 *
 * Adapter that wraps viz/beatList.js for embedding in the IDE left panel's
 * "Beats" tab. Creates a container with the beat list and a compact control
 * bar pinned below it.  Beat editing and Add Beat menu are handled by the
 * right-side context panel (contextPanel.js).
 *
 * Exports: initBeatPanel(parentEl), cleanupBeatPanel()
 */

import * as beatList from "./views/viz/beatList.js";
import {
  state, copyBeat, pasteBeat,
  on, off, FRAMES_UPDATED, BEAT_CHANGED,
} from "./views/viz/state.js";
import { pushHistory } from "./views/viz/history.js";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _parentEl = null;
let _containerEl = null;      // flex column: beat list + control bar
let _beatListEl = null;       // beat list host
let _controlBarEl = null;     // bottom control bar
let _active = false;
let _framesHandler = null;
let _beatHandler = null;

// ---------------------------------------------------------------------------
// Init / Cleanup
// ---------------------------------------------------------------------------

export function initBeatPanel(parentEl) {
  if (_active) return;
  _parentEl = parentEl;

  // Outer flex column: beat list fills, control bar sticks to bottom
  _containerEl = document.createElement("div");
  _containerEl.className = "ide-beat-panel";
  _containerEl.style.cssText = "flex:1;overflow:hidden;display:flex;flex-direction:column;";
  _parentEl.appendChild(_containerEl);

  // Beat list host (fills available space)
  _beatListEl = document.createElement("div");
  _beatListEl.className = "ide-beat-list-host";
  _beatListEl.style.cssText = "flex:1;overflow:hidden;display:flex;flex-direction:column;min-height:0;";
  _beatListEl.tabIndex = 0;
  _containerEl.appendChild(_beatListEl);

  // Control bar (pinned to bottom)
  _controlBarEl = document.createElement("div");
  _controlBarEl.className = "ide-beat-controls";
  _controlBarEl.innerHTML = `
    <div class="ide-beat-controls-row">
      <button class="ide-beat-btn" data-action="add" title="Add after (a)">+ Add</button>
      <button class="ide-beat-btn" data-action="insert" title="Insert before (i)">Ins</button>
      <button class="ide-beat-btn" data-action="up" title="Move up (Ctrl+Up)">&#9650;</button>
      <button class="ide-beat-btn" data-action="down" title="Move down (Ctrl+Down)">&#9660;</button>
      <button class="ide-beat-btn" data-action="copy" title="Copy (c)">Copy</button>
      <button class="ide-beat-btn ide-beat-btn-paste" data-action="paste" title="Paste (v)" disabled>Paste</button>
      <button class="ide-beat-btn ide-beat-btn-del" data-action="delete" title="Delete (d)">Del</button>
    </div>
    <div class="ide-beat-hints">j/k nav &middot; Enter edit &middot; a add &middot; i insert &middot; d del</div>
  `;
  _containerEl.appendChild(_controlBarEl);

  // Init beat list
  beatList.init(_beatListEl);

  // Wire button clicks
  _controlBarEl.addEventListener("click", _onControlClick);

  // Update paste button state when frames change
  _framesHandler = on(FRAMES_UPDATED, _updatePasteBtn);
  _beatHandler = on(BEAT_CHANGED, _updatePasteBtn);

  _active = true;

  // Auto-focus for keyboard nav
  requestAnimationFrame(() => {
    if (_beatListEl) _beatListEl.focus();
  });
}

export function cleanupBeatPanel() {
  if (!_active) return;

  if (_framesHandler) { off(FRAMES_UPDATED, _framesHandler); _framesHandler = null; }
  if (_beatHandler) { off(BEAT_CHANGED, _beatHandler); _beatHandler = null; }

  beatList.cleanup();

  if (_controlBarEl) _controlBarEl.removeEventListener("click", _onControlClick);

  if (_containerEl && _containerEl.parentNode) {
    _containerEl.remove();
  }
  _containerEl = null;
  _beatListEl = null;
  _controlBarEl = null;
  _parentEl = null;
  _active = false;
}

export function isActive() { return _active; }

// ---------------------------------------------------------------------------
// Control bar actions
// ---------------------------------------------------------------------------

function _onControlClick(e) {
  const btn = e.target.closest(".ide-beat-btn");
  if (!btn) return;

  const action = btn.dataset.action;
  if (!state.frames || state.frames.length === 0) return;

  switch (action) {
    case "add":
      if (_beatListEl) {
        _beatListEl.dispatchEvent(new CustomEvent("beat-add-request", {
          bubbles: true,
          detail: { afterIndex: state.currentBeat, position: "after" },
        }));
      }
      break;

    case "insert":
      if (_beatListEl) {
        _beatListEl.dispatchEvent(new CustomEvent("beat-add-request", {
          bubbles: true,
          detail: { afterIndex: state.currentBeat, position: "before" },
        }));
      }
      break;

    case "up":
      _simulateKey("ArrowUp", true);
      break;

    case "down":
      _simulateKey("ArrowDown", true);
      break;

    case "copy":
      if (copyBeat(state.currentBeat)) {
        _updatePasteBtn();
      }
      break;

    case "paste":
      if (state.clipboard) {
        pushHistory(state.source);
        pasteBeat();
        _updatePasteBtn();
      }
      break;

    case "delete":
      _simulateKey("d", false);
      break;
  }

  // Return focus to beat list
  if (_beatListEl) _beatListEl.focus();
}

/**
 * Simulate a keydown on the beat list container so beatList.js
 * handles move/delete through its existing key handler.
 */
function _simulateKey(key, ctrl) {
  if (!_beatListEl) return;
  _beatListEl.dispatchEvent(new KeyboardEvent("keydown", {
    key,
    ctrlKey: !!ctrl,
    bubbles: true,
    cancelable: true,
  }));
}

function _updatePasteBtn() {
  if (!_controlBarEl) return;
  const btn = _controlBarEl.querySelector('[data-action="paste"]');
  if (btn) btn.disabled = !state.clipboard;
}
