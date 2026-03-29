// beatList.js — Beat list panel: render, select, scroll, keyboard navigation
// S231 — Phase 1 (Foundation)

import {
  state, on, off, goToBeat, openEditor, setDirty, resimulate,
  copyBeat, pasteBeat,
  BEAT_TAGS, beatSummary,
  BEAT_CHANGED, FRAMES_UPDATED, EDITOR_OPENED, EDITOR_CLOSED,
} from "./state.js";
import { pushHistory } from "./history.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const VIRTUAL_THRESHOLD = 200;  // Use virtual scrolling above this many beats
const VIRTUAL_BUFFER = 20;      // Extra rows above/below viewport
const ROW_HEIGHT = 29;          // Approx px height of a beat row (for virtual scroll)

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _container = null;
let _handlers = [];         // Event bus subscriptions [{name, handler}]
let _deleteOverlay = null;  // Active delete confirmation element
let _deleteTimer = null;
let _toastTimer = null;     // Status toast auto-dismiss timer
let _searchQuery = "";      // Beat search/filter text

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function init(containerEl) {
  _container = containerEl;
  _container.setAttribute("tabindex", "0");
  _container.classList.add("beat-list-container");

  // Event bus subscriptions
  _handlers = [
    { name: FRAMES_UPDATED, handler: on(FRAMES_UPDATED, _render) },
    { name: BEAT_CHANGED, handler: on(BEAT_CHANGED, _onBeatChanged) },
    { name: EDITOR_OPENED, handler: on(EDITOR_OPENED, _onEditorOpened) },
    { name: EDITOR_CLOSED, handler: on(EDITOR_CLOSED, _onEditorClosed) },
  ];

  // DOM event listeners
  _container.addEventListener("keydown", _onKeyDown);
  _container.addEventListener("click", _onClick);
  _container.addEventListener("dblclick", _onDblClick);

  // Virtual scroll listener
  _container.addEventListener("scroll", _onScroll);

  // Search input + label jump
  _container.addEventListener("input", _onSearchInput);
  _container.addEventListener("change", _onLabelJump);

  _render();
}

export function cleanup() {
  for (const { name, handler } of _handlers) {
    off(name, handler);
  }
  _handlers = [];

  if (_container) {
    _container.removeEventListener("keydown", _onKeyDown);
    _container.removeEventListener("click", _onClick);
    _container.removeEventListener("dblclick", _onDblClick);
    _container.removeEventListener("scroll", _onScroll);
    _container.removeEventListener("input", _onSearchInput);
    _container.removeEventListener("change", _onLabelJump);
  }

  _dismissDelete();
  _searchQuery = "";
  _container = null;
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function _render() {
  if (!_container) return;

  const frames = state.frames;
  if (!frames || frames.length === 0) {
    _container.innerHTML = _searchBarHTML()
      + '<div class="beat-empty">No beats in this script.</div>'
      + _footerHTML();
    return;
  }

  if (frames.length > VIRTUAL_THRESHOLD) {
    _renderVirtual();
  } else {
    _renderAll();
  }
  // Restore search input value after re-render
  const searchInput = _container.querySelector(".beat-search-input");
  if (searchInput && _searchQuery !== "") {
    searchInput.value = _searchQuery;
  }
}

function _renderAll() {
  const frames = state.frames;
  const filtered = _getFilteredIndices();
  let html = _searchBarHTML();
  if (_searchQuery.trim() && filtered.length < frames.length) {
    html += `<div class="beat-search-count">${filtered.length} / ${frames.length} beats</div>`;
  }
  for (const i of filtered) {
    html += _rowHTML(i, frames[i]);
  }
  html += _footerHTML();
  _container.innerHTML = html;
  _scrollIntoView();
}

// ---------------------------------------------------------------------------
// Virtual scrolling (>200 beats)
// ---------------------------------------------------------------------------

function _renderVirtual() {
  const frames = state.frames;
  const totalHeight = frames.length * ROW_HEIGHT;

  const scrollTop = _container.scrollTop;
  const viewHeight = _container.clientHeight;
  const startIdx = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - VIRTUAL_BUFFER);
  const endIdx = Math.min(frames.length, Math.ceil((scrollTop + viewHeight) / ROW_HEIGHT) + VIRTUAL_BUFFER);

  let html = `<div style="height:${totalHeight}px;position:relative;">`;
  for (let i = startIdx; i < endIdx; i++) {
    html += `<div style="position:absolute;top:${i * ROW_HEIGHT}px;left:0;right:0;">`;
    html += _rowHTML(i, frames[i]);
    html += "</div>";
  }
  html += "</div>";
  _container.innerHTML = html;
}

let _scrollRafPending = false;
function _onScroll() {
  if (state.frames.length <= VIRTUAL_THRESHOLD) return;
  if (_scrollRafPending) return;
  _scrollRafPending = true;
  requestAnimationFrame(() => {
    _scrollRafPending = false;
    _renderVirtual();
  });
}

// ---------------------------------------------------------------------------
// Row HTML generation
// ---------------------------------------------------------------------------

function _rowHTML(index, frame) {
  const beat = frame.beat;
  const isSelected = index === state.currentBeat;
  const isEditing = index === state.editingBeat;
  const isLabel = beat && beat.type === "label";

  let cls = "beat-row";
  if (isSelected) cls += " beat-selected";
  if (isEditing) cls += " beat-editing";
  if (isLabel) cls += " beat-row-label";

  const num = index + 1;
  const tag = beat ? (BEAT_TAGS[beat.type] || "???") : "???";
  const tagCls = `beat-tag beat-tag-${tag.toLowerCase()}`;

  if (isLabel) {
    const name = (beat.data || {}).name || (beat.data || {}).label || tag;
    return `<div class="${cls}" data-index="${index}">`
      + `<span class="beat-num">${num}</span>`
      + `<span class="${tagCls}">${_esc(tag)}</span>`
      + `<span class="beat-label-name">${_esc(name)}</span>`
      + `</div>`;
  }

  const summary = beatSummary(beat);
  return `<div class="${cls}" data-index="${index}">`
    + `<span class="beat-num">${num}</span>`
    + `<span class="${tagCls}">${_esc(tag)}</span>`
    + `<span class="beat-summary">${_esc(summary)}</span>`
    + `</div>`;
}

function _esc(s) {
  if (!s) return "";
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function _searchBarHTML() {
  // Build label jump options
  const frames = state.frames || [];
  let labelOptions = '<option value="">Go to label...</option>';
  for (let i = 0; i < frames.length; i++) {
    const beat = frames[i].beat;
    if (beat && beat.type === "label") {
      const name = (beat.data || {}).name || (beat.data || {}).label || "";
      if (name) {
        labelOptions += `<option value="${i}">${_esc(name)}</option>`;
      }
    }
  }
  const hasLabels = frames.some(f => f.beat && f.beat.type === "label");
  return `<div class="beat-search-bar">`
    + `<input type="text" class="beat-search-input" placeholder="Filter beats..." />`
    + (hasLabels ? `<select class="beat-label-jump" title="Jump to label">${labelOptions}</select>` : "")
    + `</div>`;
}

function _getFilteredIndices() {
  const frames = state.frames;
  const q = _searchQuery.trim().toLowerCase();
  if (!q) {
    return frames.map((_, i) => i);
  }
  const result = [];
  for (let i = 0; i < frames.length; i++) {
    const beat = frames[i].beat;
    if (!beat) continue;
    // Match against type, tag, label name, summary text, actor
    const tag = (BEAT_TAGS[beat.type] || "").toLowerCase();
    const type = (beat.type || "").toLowerCase();
    const summary = beatSummary(beat).toLowerCase();
    const data = beat.data || {};
    const actor = (data.actor || "").toLowerCase();
    const label = (data.name || data.label || "").toLowerCase();
    const text = (data.text || "").toLowerCase();
    if (type.includes(q) || tag.includes(q) || summary.includes(q)
        || actor.includes(q) || label.includes(q) || text.includes(q)) {
      result.push(i);
    }
  }
  return result;
}

function _onSearchInput(e) {
  if (!e.target.classList.contains("beat-search-input")) return;
  _searchQuery = e.target.value;
  _render();
  // Re-focus the search input after re-render
  const newInput = _container.querySelector(".beat-search-input");
  if (newInput) {
    newInput.focus();
    newInput.selectionStart = newInput.selectionEnd = newInput.value.length;
  }
}

function _onLabelJump(e) {
  if (!e.target.classList.contains("beat-label-jump")) return;
  const idx = parseInt(e.target.value, 10);
  if (!isNaN(idx)) {
    _searchQuery = "";  // Clear filter when jumping
    goToBeat(idx);
    _render();
  }
}

function _footerHTML() {
  return "";  // Buttons moved to docked controls bar in visualizer.js
}

// ---------------------------------------------------------------------------
// Selection + scroll into view
// ---------------------------------------------------------------------------

function _onBeatChanged() {
  _updateSelection();
  _scrollIntoView();
}

function _updateSelection() {
  if (!_container) return;
  const rows = _container.querySelectorAll(".beat-row");
  for (const row of rows) {
    const idx = parseInt(row.dataset.index, 10);
    row.classList.toggle("beat-selected", idx === state.currentBeat);
  }
}

function _scrollIntoView() {
  if (!_container) return;

  // For virtual scrolling, handle manually
  if (state.frames.length > VIRTUAL_THRESHOLD) {
    const targetTop = state.currentBeat * ROW_HEIGHT;
    const viewTop = _container.scrollTop;
    const viewBottom = viewTop + _container.clientHeight;
    if (targetTop < viewTop || targetTop + ROW_HEIGHT > viewBottom) {
      _container.scrollTop = targetTop - _container.clientHeight / 2;
    }
    return;
  }

  const row = _container.querySelector(`.beat-row[data-index="${state.currentBeat}"]`);
  if (row) {
    row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

// ---------------------------------------------------------------------------
// Editor opened/closed
// ---------------------------------------------------------------------------

function _onEditorOpened(idx) {
  if (!_container) return;
  const row = _container.querySelector(`.beat-row[data-index="${idx}"]`);
  if (row) row.classList.add("beat-editing");
}

function _onEditorClosed() {
  if (!_container) return;
  const editing = _container.querySelector(".beat-editing");
  if (editing) editing.classList.remove("beat-editing");
  // Return focus to beat list for keyboard navigation
  _container.focus();
}

// ---------------------------------------------------------------------------
// Keyboard navigation
// ---------------------------------------------------------------------------

function _onKeyDown(e) {
  // Escape in search input: clear search and return focus to list
  if (e.key === "Escape" && e.target.classList.contains("beat-search-input")) {
    _searchQuery = "";
    _render();
    _container.focus();
    return;
  }

  // Don't handle navigation keys when typing in search
  if (e.target.classList.contains("beat-search-input")) return;

  // Don't handle keys when a delete overlay is active (handled separately)
  if (_deleteOverlay) return;

  const frames = state.frames;
  if (!frames || frames.length === 0) return;

  switch (e.key) {
    case "j":
    case "ArrowDown":
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        _moveBeat(1);  // move down
      } else {
        e.preventDefault();
        goToBeat(state.currentBeat + 1);  // j = next/down
      }
      break;

    case "k":
    case "ArrowUp":
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        _moveBeat(-1);  // move up
      } else {
        e.preventDefault();
        goToBeat(state.currentBeat - 1);  // k = previous/up
      }
      break;

    case "Home":
      e.preventDefault();
      goToBeat(0);
      break;

    case "End":
      e.preventDefault();
      goToBeat(frames.length - 1);
      break;

    case "Enter":
      e.preventDefault();
      openEditor(state.currentBeat);
      break;

    case "d":
    case "Delete":
      e.preventDefault();
      _deleteBeat(state.currentBeat);
      break;

    case " ":  // Space — toggle play/pause
      e.preventDefault();
      _container.dispatchEvent(new CustomEvent("play-toggle-request", { bubbles: true }));
      break;

    case "a":
      e.preventDefault();
      // Emit custom event for editor index.js to handle
      _container.dispatchEvent(new CustomEvent("beat-add-request", {
        bubbles: true,
        detail: { afterIndex: state.currentBeat },
      }));
      break;

    case "c":
      if (e.ctrlKey || e.metaKey) break;  // Don't intercept Ctrl+C
      e.preventDefault();
      if (copyBeat(state.currentBeat)) {
        _showToast("Beat copied");
        _render();  // Re-render to update paste button state
      }
      break;

    case "v":
      if (e.ctrlKey || e.metaKey) break;  // Don't intercept Ctrl+V
      e.preventDefault();
      if (state.clipboard) {
        pushHistory(state.source);
        pasteBeat().then(ok => {
          if (ok) _showToast("Beat pasted");
        });
      }
      break;

    case "/": {
      // Focus search bar
      const search = _container.querySelector(".beat-search-input");
      if (search) {
        e.preventDefault();
        search.focus();
      }
      break;
    }
  }
}

// ---------------------------------------------------------------------------
// Click handlers
// ---------------------------------------------------------------------------

function _onClick(e) {
  const row = e.target.closest(".beat-row");
  if (!row) return;
  const idx = parseInt(row.dataset.index, 10);
  if (isNaN(idx)) return;
  goToBeat(idx);
  _container.focus();
}

function _onDblClick(e) {
  const row = e.target.closest(".beat-row");
  if (!row) return;
  const idx = parseInt(row.dataset.index, 10);
  if (isNaN(idx)) return;
  goToBeat(idx);
  openEditor(idx);
}

// ---------------------------------------------------------------------------
// Status toast
// ---------------------------------------------------------------------------

function _showToast(message) {
  if (!_container) return;
  // Remove any existing toast
  const old = _container.querySelector(".beat-toast");
  if (old) old.remove();
  if (_toastTimer) clearTimeout(_toastTimer);

  const toast = document.createElement("div");
  toast.className = "beat-toast";
  toast.textContent = message;
  _container.appendChild(toast);
  _toastTimer = setTimeout(() => {
    if (toast.parentNode) toast.remove();
    _toastTimer = null;
  }, 1500);
}

// ---------------------------------------------------------------------------
// Delete beat
// ---------------------------------------------------------------------------

function _deleteBeat(beatIdx) {
  const frames = state.frames;
  if (beatIdx < 0 || beatIdx >= frames.length) return;
  const frame = frames[beatIdx];
  const beat = frame.beat;
  if (!beat || beat.source_line == null) return;

  // Find the row element
  const row = _container.querySelector(`.beat-row[data-index="${beatIdx}"]`);
  if (!row) return;

  // Dismiss any existing delete overlay
  _dismissDelete();

  // Show inline confirmation
  row.classList.add("beat-delete-confirm");
  const overlay = document.createElement("div");
  overlay.className = "beat-delete-overlay";
  overlay.innerHTML = `<span>Delete?</span> <button class="beat-del-yes">Y</button> <button class="beat-del-no">N</button>`;
  row.appendChild(overlay);
  _deleteOverlay = overlay;

  let resolved = false;

  function dismiss() {
    if (resolved) return;
    resolved = true;
    row.classList.remove("beat-delete-confirm");
    if (overlay.parentNode) overlay.remove();
    clearTimeout(_deleteTimer);
    _deleteOverlay = null;
  }

  // Auto-dismiss after 3 seconds
  _deleteTimer = setTimeout(dismiss, 3000);

  overlay.querySelector(".beat-del-yes").addEventListener("click", async (e) => {
    e.stopPropagation();
    dismiss();
    await _executeDelete(beatIdx);
  });

  overlay.querySelector(".beat-del-no").addEventListener("click", (e) => {
    e.stopPropagation();
    dismiss();
  });
}

function _dismissDelete() {
  if (_deleteOverlay && _deleteOverlay.parentNode) {
    _deleteOverlay.parentNode.classList.remove("beat-delete-confirm");
    _deleteOverlay.remove();
  }
  _deleteOverlay = null;
  if (_deleteTimer) {
    clearTimeout(_deleteTimer);
    _deleteTimer = null;
  }
}

async function _executeDelete(beatIdx) {
  const frames = state.frames;
  if (beatIdx < 0 || beatIdx >= frames.length) return;

  const beat = frames[beatIdx].beat;
  if (!beat || beat.source_line == null) return;

  pushHistory(state.source);

  const lines = state.source.split("\n");
  const sl = beat.source_line;
  const el = beat.source_end_line != null ? beat.source_end_line : sl;

  if (sl >= 0 && sl < lines.length) {
    lines.splice(sl, el - sl + 1);
  }
  const newSource = lines.join("\n");

  try {
    await resimulate(newSource);
    setDirty(true);

    // Adjust selection
    if (state.currentBeat >= state.frames.length) {
      goToBeat(Math.max(0, state.frames.length - 1));
    }
  } catch (err) {
    // resimulate handles error display
  }
}

// ---------------------------------------------------------------------------
// Move beat (reorder)
// ---------------------------------------------------------------------------

async function _moveBeat(direction) {
  const beatIdx = state.currentBeat;
  const frames = state.frames;
  if (beatIdx < 0 || beatIdx >= frames.length) return;

  const targetIdx = beatIdx + direction;
  if (targetIdx < 0 || targetIdx >= frames.length) return;

  const frame = frames[beatIdx];
  const targetFrame = frames[targetIdx];
  if (!frame.beat || frame.beat.source_line == null) return;
  if (!targetFrame.beat || targetFrame.beat.source_line == null) return;

  // Don't move past labels (section boundaries)
  if (frame.beat.type === "label" || targetFrame.beat.type === "label") return;

  const sl1 = frame.beat.source_line;
  const el1 = frame.beat.source_end_line != null ? frame.beat.source_end_line : sl1;
  const sl2 = targetFrame.beat.source_line;
  const el2 = targetFrame.beat.source_end_line != null ? targetFrame.beat.source_end_line : sl2;

  pushHistory(state.source);

  const lines = state.source.split("\n");
  if (sl1 < 0 || sl1 >= lines.length || sl2 < 0 || sl2 >= lines.length) return;

  // Ensure blockA is the earlier range (lower line numbers)
  const [startA, endA, startB, endB] = sl1 < sl2
    ? [sl1, el1, sl2, el2]
    : [sl2, el2, sl1, el1];

  const blockA = lines.slice(startA, endA + 1);
  const blockB = lines.slice(startB, endB + 1);

  // Replace later block first (so indices stay valid), then earlier block
  lines.splice(startB, endB - startB + 1, ...blockA);
  lines.splice(startA, endA - startA + 1, ...blockB);

  const newSource = lines.join("\n");

  try {
    await resimulate(newSource);
    setDirty(true);
    goToBeat(targetIdx);

    // Pulse animation on the moved beat
    requestAnimationFrame(() => {
      const movedRow = _container.querySelector(`.beat-row[data-index="${targetIdx}"]`);
      if (movedRow) {
        movedRow.classList.add("beat-move-pulse");
        setTimeout(() => movedRow.classList.remove("beat-move-pulse"), 400);
      }
    });
  } catch (err) {
    // resimulate handles error display
  }
}
