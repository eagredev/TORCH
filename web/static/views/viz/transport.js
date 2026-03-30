// transport.js — Transport bar: play/nav/save controls, beat counter, dirty indicator
// S231 — Phase 1 (Foundation)

import {
  state, on, off, goToBeat, setPlaying, saveScript, saveAndBuild,
  setPlayerDistance, activateChain, deactivateChain,
  BEAT_CHANGED, FRAMES_UPDATED, DIRTY_CHANGED, TRIGGER_DISTANCE_CHANGED,
  CHAIN_CHANGED,
} from "./state.js";

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _container = null;
let _handlers = [];       // Event bus subscriptions
let _playInterval = null;
let _statusTimeout = null;

// DOM references (populated in init)
let _counterEl = null;
let _playBtn = null;
let _saveBtn = null;
let _saveBuildBtn = null;
let _statusEl = null;

// Slider + chain control handler refs (for cleanup on _rebuild)
let _sliderInputHandler = null;
let _sliderChangeHandler = null;
let _sliderEl = null;
let _dirBtnHandler = null;
let _chainToggleHandler = null;
let _chainToggleEl = null;
let _chainSelectHandler = null;
let _chainSelectEl = null;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function init(containerEl) {
  _container = containerEl;
  _container.innerHTML = _buildHTML();

  // Cache DOM references
  _counterEl = _container.querySelector(".viz-beat-info");
  _playBtn = _container.querySelector('[data-action="play"]');
  _saveBtn = _container.querySelector(".viz-save-btn");
  _saveBuildBtn = _container.querySelector(".viz-save-build-btn");
  _statusEl = _container.querySelector(".viz-save-status");

  // Button click handlers
  _container.addEventListener("click", _onClick);

  // Event bus subscriptions
  _handlers = [
    { name: BEAT_CHANGED, handler: on(BEAT_CHANGED, _updateCounter) },
    { name: FRAMES_UPDATED, handler: on(FRAMES_UPDATED, _onFramesUpdated) },
    { name: DIRTY_CHANGED, handler: on(DIRTY_CHANGED, _updateDirtyState) },
    { name: CHAIN_CHANGED, handler: on(CHAIN_CHANGED, _onChainChanged) },
  ];

  // Listen for play-toggle-request from beat list (Space key)
  document.addEventListener("play-toggle-request", _togglePlay);

  // Distance slider (trainer sight range)
  _wireSlider();

  _wireChainControls();
  _updateCounter();
  _updateDirtyState();
}

export function cleanup() {
  for (const { name, handler } of _handlers) {
    off(name, handler);
  }
  _handlers = [];

  _stopPlaying();

  document.removeEventListener("play-toggle-request", _togglePlay);

  if (_container) {
    _container.removeEventListener("click", _onClick);
  }

  // Remove slider + chain control listeners
  _unwireSlider();
  _unwireChainControls();

  if (_statusTimeout) {
    clearTimeout(_statusTimeout);
    _statusTimeout = null;
  }

  _container = null;
  _counterEl = null;
  _playBtn = null;
  _saveBtn = null;
  _saveBuildBtn = null;
  _statusEl = null;
  _hasSlider = false;
  _hasChainUI = false;
}

// ---------------------------------------------------------------------------
// HTML
// ---------------------------------------------------------------------------

function _buildHTML() {
  const ti = state.triggerInfo;
  const currentDist = state.playerDistance || ti?.default_distance || 0;
  let distSlider = "";
  if (ti) {
    if (ti.type === "talk") {
      // Talk-to NPC: compass d-pad, arrows point inward toward NPC
      // Layout position = where player stands, arrow points at NPC
      const dirs = ti.directions || ["north", "south", "west", "east"];
      if (dirs.length > 1) {
        // Multiple directions: show d-pad
        const labels = { north: "\u2193", south: "\u2191", west: "\u2192", east: "\u2190" };
        const titles = { north: "Stand north", south: "Stand south", west: "Stand west", east: "Stand east" };
        const btn = (d) => {
          const i = dirs.indexOf(d);
          if (i < 0) return "";
          return `<button class="viz-dir-btn${i === currentDist ? " viz-dir-active" : ""}" data-dir-idx="${i}" title="${titles[d]}">${labels[d]}</button>`;
        };
        distSlider = `
          <span class="viz-distance-wrap viz-dir-wrap" title="Player approach direction">
            <div class="viz-dir-pad">
              <div class="viz-dir-row">${btn("north")}</div>
              <div class="viz-dir-row">${btn("west")}<span class="viz-dir-center"></span>${btn("east")}</div>
              <div class="viz-dir-row">${btn("south")}</div>
            </div>
          </span>`;
      }
      // Single direction: no d-pad needed, player position is fixed
    } else if (ti.type === "coord_event") {
      // Coord event: only show picker if multiple tiles
      const tiles = ti.tiles || [];
      if (tiles.length > 1) {
        distSlider = `
          <span class="viz-distance-wrap" title="Player trigger tile">
            <label class="viz-distance-label">Trigger tile:</label>
            <input type="range" class="viz-distance-slider" min="0" max="${tiles.length - 1}" value="${currentDist}" step="1">
            <span class="viz-distance-val">${currentDist + 1}/${tiles.length}</span>
          </span>`;
      }
      // Single tile: no slider, player is just placed there
    }
    // Trainer sight range is controlled via Starting Position in the context panel, not here
  }

  const chainUI = _buildChainUI();

  return `<div class="viz-transport">
  <div class="viz-transport-left">
    <button data-action="first" title="First beat">\u258C\u25C0</button>
    <button data-action="prev" title="Previous beat">\u25C0</button>
    <button data-action="next" title="Next beat">\u25B6</button>
    <button data-action="last" title="Last beat">\u25B6\u2590</button>
    <button class="viz-play-btn" data-action="play" title="Play/Pause (Space)">\u23F5</button>
    <span class="viz-beat-info">Beat 1 / 0</span>
    ${distSlider}
    ${chainUI}
  </div>
  <div class="viz-transport-right">
    <span class="viz-save-status"></span>
    <button class="viz-save-btn" title="Save (Ctrl+S)">Save</button>
    <button class="viz-save-build-btn" title="Save + Build (Ctrl+Shift+S)">S+B</button>
  </div>
</div>`;
}

function _buildChainUI() {
  const chains = state.availableChains || [];
  if (chains.length === 0) return "";

  if (chains.length === 1) {
    // Single chain: toggle ON/OFF
    const name = chains[0].name;
    const isOn = state.chainName === name;
    return `
      <span class="viz-chain-wrap" title="Chain context: ${name}">
        <button class="viz-chain-toggle ${isOn ? "viz-chain-active" : ""}"
                data-chain-name="${name}">
          Chain: ${name} ${isOn ? "ON" : "OFF"}
        </button>
      </span>`;
  }

  // Multiple chains: dropdown picker
  let options = `<option value="">None</option>`;
  for (const c of chains) {
    const sel = c.name === state.chainName ? "selected" : "";
    options += `<option value="${c.name}" ${sel}>${c.name}</option>`;
  }
  return `
    <span class="viz-chain-wrap" title="Select chain context">
      <label class="viz-chain-label">Chain:</label>
      <select class="viz-chain-select">${options}</select>
    </span>`;
}

// ---------------------------------------------------------------------------
// Button handler
// ---------------------------------------------------------------------------

function _onClick(e) {
  const btn = e.target.closest("button");
  if (!btn) return;

  const action = btn.dataset.action;
  if (action) {
    switch (action) {
      case "first":
        goToBeat(0);
        break;
      case "prev":
        goToBeat(state.currentBeat - 1);
        break;
      case "next":
        goToBeat(state.currentBeat + 1);
        break;
      case "last":
        goToBeat(state.frames.length - 1);
        break;
      case "play":
        _togglePlay();
        break;
    }
    return;
  }

  if (btn.classList.contains("viz-save-btn")) {
    _doSave();
  } else if (btn.classList.contains("viz-save-build-btn")) {
    _doSaveAndBuild();
  }
}

// ---------------------------------------------------------------------------
// Frames updated — rebuild if trigger info changed
// ---------------------------------------------------------------------------

let _hasSlider = false;

function _onFramesUpdated() {
  // Stop playback whenever frames change (reload, resimulate, edit).
  // The user must press Play manually to start advancing.
  _stopPlaying();

  // Always rebuild — script may have changed (different NPC, different trigger).
  _rebuild();
}

function _rebuild() {
  if (!_container) return;

  // Unwire old slider/chain listeners before innerHTML replacement
  _unwireSlider();
  _unwireChainControls();

  _container.innerHTML = _buildHTML();
  _counterEl = _container.querySelector(".viz-beat-info");
  _playBtn = _container.querySelector('[data-action="play"]');
  _saveBtn = _container.querySelector(".viz-save-btn");
  _saveBuildBtn = _container.querySelector(".viz-save-build-btn");
  _statusEl = _container.querySelector(".viz-save-status");

  _wireSlider();

  _wireChainControls();
  _updateCounter();
  _updateDirtyState();
}

// ---------------------------------------------------------------------------
// Slider wiring/unwiring
// ---------------------------------------------------------------------------

function _wireSlider() {
  if (!_container) return;
  const slider = _container.querySelector(".viz-distance-slider");
  _hasSlider = !!slider;
  if (slider) {
    const valEl = _container.querySelector(".viz-distance-val");
    _sliderEl = slider;

    const excluded = (state.triggerInfo && state.triggerInfo.excluded_distances) || [];

    // Snap a raw slider value to the nearest non-excluded distance
    const snap = (raw) => {
      if (!excluded.length) return raw;
      if (!excluded.includes(raw)) return raw;
      // Search outward for nearest valid value
      const ti = state.triggerInfo;
      const lo = ti ? ti.min_distance : 1;
      const hi = ti ? ti.max_distance : raw;
      for (let delta = 1; delta <= hi - lo; delta++) {
        if (raw - delta >= lo && !excluded.includes(raw - delta)) return raw - delta;
        if (raw + delta <= hi && !excluded.includes(raw + delta)) return raw + delta;
      }
      return raw;  // all excluded — fall through
    };

    const isCoord = state.triggerInfo && state.triggerInfo.type === "coord_event";
    const tiles = isCoord ? (state.triggerInfo.tiles || []) : [];

    const formatVal = (v) => {
      if (isCoord && tiles.length > 1) return `${v + 1}/${tiles.length}`;
      return String(v);
    };

    _sliderInputHandler = () => {
      const v = snap(parseInt(slider.value, 10));
      if (v !== parseInt(slider.value, 10)) slider.value = v;
      if (valEl) valEl.textContent = formatVal(v);
    };
    _sliderChangeHandler = () => {
      const v = snap(parseInt(slider.value, 10));
      slider.value = v;
      if (valEl) valEl.textContent = formatVal(v);
      setPlayerDistance(v);
    };
    slider.addEventListener("input", _sliderInputHandler);
    slider.addEventListener("change", _sliderChangeHandler);
  }

  // Direction buttons (talk trigger type)
  const dirWrap = _container.querySelector(".viz-dir-wrap");
  if (dirWrap) {
    _hasSlider = true;  // treat as "has controls" for rebuild logic
    _dirBtnHandler = (e) => {
      const btn = e.target.closest(".viz-dir-btn");
      if (!btn) return;
      const idx = parseInt(btn.dataset.dirIdx, 10);
      if (isNaN(idx)) return;
      // Update active state on all buttons
      dirWrap.querySelectorAll(".viz-dir-btn").forEach(b => b.classList.remove("viz-dir-active"));
      btn.classList.add("viz-dir-active");
      setPlayerDistance(idx);
    };
    dirWrap.addEventListener("click", _dirBtnHandler);
  }

}

function _unwireSlider() {
  if (_sliderEl) {
    if (_sliderInputHandler) _sliderEl.removeEventListener("input", _sliderInputHandler);
    if (_sliderChangeHandler) _sliderEl.removeEventListener("change", _sliderChangeHandler);
  }
  if (_dirBtnHandler) {
    const dirWrap = _container && _container.querySelector(".viz-dir-wrap");
    if (dirWrap) dirWrap.removeEventListener("click", _dirBtnHandler);
  }
  _sliderEl = null;
  _sliderInputHandler = null;
  _sliderChangeHandler = null;
  _dirBtnHandler = null;
}

// ---------------------------------------------------------------------------
// Chain controls
// ---------------------------------------------------------------------------

function _wireChainControls() {
  if (!_container) return;

  // Single-chain toggle button
  const toggleBtn = _container.querySelector(".viz-chain-toggle");
  if (toggleBtn) {
    _chainToggleEl = toggleBtn;
    _chainToggleHandler = () => {
      const name = toggleBtn.dataset.chainName;
      if (state.chainName === name) {
        deactivateChain();
      } else {
        activateChain(name);
      }
    };
    toggleBtn.addEventListener("click", _chainToggleHandler);
  }

  // Multi-chain dropdown
  const chainSelect = _container.querySelector(".viz-chain-select");
  if (chainSelect) {
    _chainSelectEl = chainSelect;
    _chainSelectHandler = () => {
      const val = chainSelect.value;
      if (val) {
        activateChain(val);
      } else {
        deactivateChain();
      }
    };
    chainSelect.addEventListener("change", _chainSelectHandler);
  }
}

function _unwireChainControls() {
  if (_chainToggleEl && _chainToggleHandler) {
    _chainToggleEl.removeEventListener("click", _chainToggleHandler);
  }
  _chainToggleEl = null;
  _chainToggleHandler = null;

  if (_chainSelectEl && _chainSelectHandler) {
    _chainSelectEl.removeEventListener("change", _chainSelectHandler);
  }
  _chainSelectEl = null;
  _chainSelectHandler = null;
}

let _hasChainUI = false;

function _onChainChanged() {
  // Rebuild transport to update chain toggle/picker state
  const shouldHaveChainUI = (state.availableChains || []).length > 0;
  if (shouldHaveChainUI !== _hasChainUI || shouldHaveChainUI) {
    _rebuild();
    _hasChainUI = shouldHaveChainUI;
  }
}

// ---------------------------------------------------------------------------
// Beat counter
// ---------------------------------------------------------------------------

function _updateCounter() {
  if (!_counterEl) return;
  const total = state.frames ? state.frames.length : 0;
  const current = total > 0 ? state.currentBeat + 1 : 0;
  _counterEl.textContent = `Beat ${current} / ${total}`;
}

// ---------------------------------------------------------------------------
// Play / Pause
// ---------------------------------------------------------------------------

function _togglePlay() {
  if (state.playing) {
    _stopPlaying();
  } else {
    _startPlaying();
  }
}

function _startPlaying() {
  if (!state.frames || state.frames.length === 0) return;

  setPlaying(true);
  if (_playBtn) _playBtn.textContent = "\u23F8";  // pause symbol

  _playInterval = setInterval(() => {
    const next = state.currentBeat + 1;
    if (next >= state.frames.length) {
      _stopPlaying();
      return;
    }
    goToBeat(next);
  }, 2000);
}

function _stopPlaying() {
  if (_playInterval) {
    clearInterval(_playInterval);
    _playInterval = null;
  }
  setPlaying(false);
  if (_playBtn) _playBtn.textContent = "\u23F5";  // play symbol
}

// ---------------------------------------------------------------------------
// Dirty state
// ---------------------------------------------------------------------------

function _updateDirtyState() {
  if (!_saveBtn) return;
  if (state.dirty) {
    _saveBtn.classList.add("viz-save-dirty");
    _saveBtn.textContent = "Save *";
  } else {
    _saveBtn.classList.remove("viz-save-dirty");
    _saveBtn.textContent = "Save";
  }
}

// ---------------------------------------------------------------------------
// Save
// ---------------------------------------------------------------------------

async function _doSave() {
  if (!_saveBtn) return;
  _saveBtn.disabled = true;
  _showStatus("Saving...");

  try {
    const res = await saveScript();
    if (!res.ok) {
      _showStatus(`Save failed: ${res.error || "unknown error"}`, 5000, "error");
    } else if (res.validation) {
      const v = res.validation;
      const errs = (v.errors || []).length;
      const warns = (v.warnings || []).length;
      if (errs > 0) {
        const msg = v.errors.map(e => e.message).join("; ");
        _showStatus(`Saved with errors: ${msg}`, 5000, "error");
      } else if (warns > 0) {
        const msg = v.warnings.map(w => w.message).join("; ");
        _showStatus(`Saved (${warns} warning${warns > 1 ? "s" : ""}): ${msg}`, 5000, "warn");
      } else {
        _showStatus("Saved");
      }
    } else {
      _showStatus("Saved");
    }
  } catch (err) {
    _showStatus(`Save failed: ${err.message || "network error"}`, 5000, "error");
  } finally {
    _saveBtn.disabled = false;
  }
}

async function _doSaveAndBuild() {
  if (!_saveBuildBtn) return;
  _saveBuildBtn.disabled = true;
  _showStatus("Saving...");

  try {
    const res = await saveAndBuild();
    if (!res.ok) {
      const step = res.step ? ` (${res.step})` : "";
      _showStatus(`Save+Build failed${step}: ${res.error || "unknown error"}`, 5000, "error");
    } else if (res.validation) {
      const v = res.validation;
      const errs = (v.errors || []).length;
      const warns = (v.warnings || []).length;
      if (errs > 0) {
        const msg = v.errors.map(e => e.message).join("; ");
        _showStatus(`Build started (errors: ${msg})`, 5000, "error");
      } else if (warns > 0) {
        _showStatus(`Build started (${warns} warning${warns > 1 ? "s" : ""})`, 5000, "warn");
      } else {
        _showStatus("Build started");
      }
    } else {
      _showStatus("Build started");
    }
  } catch (err) {
    _showStatus(`Save+Build failed: ${err.message || "network error"}`, 5000, "error");
  } finally {
    _saveBuildBtn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Status text
// ---------------------------------------------------------------------------

function _showStatus(text, duration, severity) {
  if (!_statusEl) return;
  _statusEl.textContent = text;
  _statusEl.style.opacity = "1";

  // Apply severity class for visual distinction
  _statusEl.classList.remove("viz-status-error", "viz-status-warn");
  if (severity === "error") {
    _statusEl.classList.add("viz-status-error");
  } else if (severity === "warn") {
    _statusEl.classList.add("viz-status-warn");
  }

  if (_statusTimeout) clearTimeout(_statusTimeout);
  _statusTimeout = setTimeout(() => {
    if (_statusEl) {
      _statusEl.style.opacity = "0";
      _statusEl.classList.remove("viz-status-error", "viz-status-warn");
    }
  }, duration || 1500);
}
