// beatList.js — Beat list panel: render, select, scroll, keyboard navigation
// S231 — Phase 1 (Foundation)

import {
  state, on, off, goToBeat, openEditor, closeEditor, setDirty, resimulate,
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

/**
 * Render data-only beats (text blocks, movement blocks) into an external container.
 * Used by the Data tab in the IDE left panel.
 */
export function renderDataBeats(targetEl) {
  const frames = state.frames;
  if (!frames || frames.length === 0) {
    targetEl.innerHTML = '<div style="color:var(--text-dim);font-size:0.75rem;padding:0.5rem;">No data declarations in this script.</div>';
    return;
  }

  let html = "";
  for (let i = 0; i < frames.length; i++) {
    const beat = frames[i].beat;
    if (!beat) continue;
    if (beat.type === "movement" || beat.type === "text") {
      html += _rowHTML(i, frames[i]);
    }
  }

  if (!html) {
    targetEl.innerHTML = '<div style="color:var(--text-dim);font-size:0.75rem;padding:0.5rem;">No data declarations in this script.</div>';
    return;
  }

  targetEl.innerHTML = html;

  // Add click handler for selecting data beats
  targetEl.addEventListener("click", (e) => {
    const row = e.target.closest(".beat-row");
    if (!row) return;
    const idx = parseInt(row.dataset.index, 10);
    if (!isNaN(idx)) {
      goToBeat(idx);
    }
  });
  targetEl.addEventListener("dblclick", (e) => {
    const row = e.target.closest(".beat-row");
    if (!row) return;
    const idx = parseInt(row.dataset.index, 10);
    if (!isNaN(idx)) {
      goToBeat(idx);
      openEditor(idx);
    }
  });
}

/**
 * Get the count of visible script beats (excluding data declarations).
 */
export function getVisibleBeatCount() {
  const frames = state.frames;
  if (!frames) return 0;
  let count = 0;
  for (let i = 0; i < frames.length; i++) {
    if (!_isDataBeat(i)) count++;
  }
  return count;
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
    _nestDepth = [];
    return;
  }
  _nestDepth = _buildNestDepth(frames);
  _buildBranchGroups(frames);

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

  // Build search bar (fixed header) and beat rows (scrollable) separately
  let searchHTML = _searchBarHTML();
  if (_searchQuery.trim() && filtered.length < frames.length) {
    searchHTML += `<div class="beat-search-count">${filtered.length} / ${frames.length} beats</div>`;
  }

  let rowsHTML = "";
  const emittedGroups = new Set();
  const isSearching = !!_searchQuery.trim();
  for (const i of filtered) {
    const beat = frames[i].beat;
    // Data declarations (movement/text blocks) only show in Data tab, not Beats tab
    if (!isSearching && beat && (beat.type === "movement" || beat.type === "text")) continue;
    const gIdx = _beatToGroup[i];
    if (gIdx !== undefined && !isSearching) {
      if (!emittedGroups.has(gIdx)) {
        emittedGroups.add(gIdx);
        rowsHTML += _branchHeaderHTML(_branchGroups[gIdx], gIdx);
      }
      if (_hiddenBeats.has(i)) continue;
    }
    if (_hiddenBeats.has(i) && !isSearching) continue;
    rowsHTML += _rowHTML(i, frames[i]);
  }

  // Two-zone layout: fixed search header + scrollable beat rows
  _container.innerHTML =
    `<div class="beat-list-header">${searchHTML}</div>`
    + `<div class="beat-list-scroll">${rowsHTML}</div>`;

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
// Branch nesting depth tracking
// ---------------------------------------------------------------------------

let _nestDepth = [];      // per-frame nesting depth for indentation
let _branchGroups = [];   // [{startIdx, endIdx, type, branches: [{label, startBeat, endBeat}], activeTab}]
let _beatToGroup = {};    // frame index → group index (for beats that are part of a branch group)
let _hiddenBeats = new Set();  // frame indices hidden by branch group rendering
let _savedTabs = {};      // startIdx → activeTab (persists across rebuilds)
let _branchLastBeat = new Set();  // frame indices that are the last visible beat in a branch group
let _expandedMovements = new Set();  // beat indices with expanded movement sub-rows

function _buildBranchGroups(frames) {
  const groups = [];
  const stack = [];
  const beatMap = {};
  const hidden = new Set();

  for (let i = 0; i < frames.length; i++) {
    const beat = frames[i].beat;
    if (!beat) continue;
    const t = beat.type;
    const d = beat.data || {};

    // if (...) opens a new group
    if (t === "condition" && d.branch === "if") {
      stack.push({
        startIdx: i, type: "if",
        branches: [{ label: _condLabel(beat), startBeat: i + 1, condIdx: i }],
      });
      hidden.add(i); // hide the if beat itself
    }
    // elif / else adds a branch to the current group
    else if (t === "condition" && (d.branch === "elif" || d.branch === "else")) {
      if (stack.length) {
        const g = stack[stack.length - 1];
        g.branches[g.branches.length - 1].endBeat = i - 1;
        const label = d.branch === "else" ? "Else" : _condLabel(beat);
        g.branches.push({ label, startBeat: i + 1, condIdx: i });
        hidden.add(i); // hide the elif/else beat
      }
    }
    // endif closes the group
    else if (t === "endif") {
      if (stack.length) {
        const g = stack.pop();
        g.branches[g.branches.length - 1].endBeat = i - 1;
        g.endIdx = i;
        g.activeTab = _savedTabs[g.startIdx] || 0;
        const gIdx = groups.length;
        groups.push(g);
        hidden.add(i); // hide endif
        // Map all beats in this group to the group index
        beatMap[g.startIdx] = gIdx;
        for (const br of g.branches) {
          if (br.condIdx !== undefined) beatMap[br.condIdx] = gIdx;
          for (let j = br.startBeat; j <= br.endBeat; j++) {
            beatMap[j] = gIdx;
          }
        }
      }
    }
    // switch opens a group
    else if (t === "switch") {
      stack.push({
        startIdx: i, type: "switch",
        branches: [], switchVar: d.var || d.variable || "",
      });
      hidden.add(i);
    }
    // case adds a branch
    else if (t === "case") {
      if (stack.length && stack[stack.length - 1].type === "switch") {
        const g = stack[stack.length - 1];
        if (g.branches.length) g.branches[g.branches.length - 1].endBeat = i - 1;
        const label = d.value === "default" ? "Default" : `Case ${d.value || ""}`;
        g.branches.push({ label, startBeat: i + 1, condIdx: i });
        hidden.add(i);
      }
    }
    // endswitch closes
    else if (t === "endswitch") {
      if (stack.length && stack[stack.length - 1].type === "switch") {
        const g = stack.pop();
        if (g.branches.length) g.branches[g.branches.length - 1].endBeat = i - 1;
        g.endIdx = i;
        g.activeTab = _savedTabs[g.startIdx] || 0;
        const gIdx = groups.length;
        groups.push(g);
        hidden.add(i);
        beatMap[g.startIdx] = gIdx;
        for (const br of g.branches) {
          if (br.condIdx !== undefined) beatMap[br.condIdx] = gIdx;
          for (let j = br.startBeat; j <= br.endBeat; j++) {
            beatMap[j] = gIdx;
          }
        }
      }
    }
    // choice/option/endchoice: similar pattern
    else if (t === "choice") {
      stack.push({
        startIdx: i, type: "choice",
        branches: [], prompt: d.prompt || "",
      });
      hidden.add(i);
    }
    else if (t === "option") {
      if (stack.length && stack[stack.length - 1].type === "choice") {
        const g = stack[stack.length - 1];
        if (g.branches.length) g.branches[g.branches.length - 1].endBeat = i - 1;
        g.branches.push({ label: d.text || `Option ${g.branches.length + 1}`, startBeat: i + 1, condIdx: i });
        hidden.add(i);
      }
    }
    else if (t === "endchoice") {
      if (stack.length && stack[stack.length - 1].type === "choice") {
        const g = stack.pop();
        if (g.branches.length) g.branches[g.branches.length - 1].endBeat = i - 1;
        g.endIdx = i;
        g.activeTab = _savedTabs[g.startIdx] || 0;
        const gIdx = groups.length;
        groups.push(g);
        hidden.add(i);
        beatMap[g.startIdx] = gIdx;
        for (const br of g.branches) {
          if (br.condIdx !== undefined) beatMap[br.condIdx] = gIdx;
          for (let j = br.startBeat; j <= br.endBeat; j++) {
            beatMap[j] = gIdx;
          }
        }
      }
    }
  }

  // Merge adjacent if/endif groups that test the same variable.
  // Pattern: if VAR == A ... endif, if VAR == B ... endif → one group with two tabs
  const merged = [];
  let i2 = 0;
  while (i2 < groups.length) {
    const g = groups[i2];
    // Only merge simple if-type groups (no elif/else, single branch)
    if (g.type === "if" && g.branches.length === 1) {
      const varName = _extractVarFromGroup(g, frames);
      if (varName) {
        // Look ahead for adjacent groups testing the same variable
        let j2 = i2 + 1;
        while (j2 < groups.length) {
          const next = groups[j2];
          // Must be immediately adjacent (endIdx + 1 == next startIdx)
          if (next.type !== "if" || next.branches.length !== 1) break;
          if (next.startIdx !== groups[j2 - 1].endIdx + 1) break;
          const nextVar = _extractVarFromGroup(next, frames);
          if (nextVar !== varName) break;
          // Merge: absorb next group's branch into current group
          g.branches.push(next.branches[0]);
          g.endIdx = next.endIdx;
          // Hide the structural beats of the absorbed group
          hidden.add(next.startIdx);  // the if beat
          hidden.add(next.endIdx);    // the endif beat
          j2++;
        }
        if (j2 > i2 + 1) {
          // We merged — rebuild beat map for this group
          g.activeTab = _savedTabs[g.startIdx] || 0;
        }
      }
    }
    merged.push(g);
    i2++;
    // Skip groups that were absorbed
    while (i2 < groups.length && groups[i2].endIdx <= g.endIdx) i2++;
  }

  // Rebuild beat map from merged groups
  const finalMap = {};
  for (let gi = 0; gi < merged.length; gi++) {
    const g = merged[gi];
    finalMap[g.startIdx] = gi;
    for (const br of g.branches) {
      if (br.condIdx !== undefined) finalMap[br.condIdx] = gi;
      for (let j = br.startBeat; j <= br.endBeat; j++) {
        finalMap[j] = gi;
      }
    }
  }

  _branchGroups = merged;
  _beatToGroup = finalMap;
  _hiddenBeats = hidden;

  // Also hide beats in non-active tabs
  for (const g of merged) {
    _updateHiddenForGroup(g);
  }
}

function _extractVarFromGroup(group, frames) {
  // Extract the variable being tested from the first branch's condition
  const condIdx = group.branches[0].condIdx;
  if (condIdx === undefined) return null;
  const beat = frames[condIdx].beat;
  if (!beat || beat.type !== "condition") return null;
  const cond = (beat.data || {}).raw_condition || "";
  // Match "VAR_NAME == VALUE" or "VAR_NAME != VALUE" etc
  const m = cond.match(/^(\w+)\s*(?:==|!=|<|>|<=|>=)\s*/);
  if (m) return m[1];
  return null;
}

function _updateHiddenForGroup(group) {
  // Show beats in active tab, hide beats in other tabs
  // Also track the last visible beat for the bottom border
  for (let t = 0; t < group.branches.length; t++) {
    const br = group.branches[t];
    for (let j = br.startBeat; j <= br.endBeat; j++) {
      _branchLastBeat.delete(j);
      if (t === group.activeTab) {
        _hiddenBeats.delete(j);
      } else {
        _hiddenBeats.add(j);
      }
    }
    // Mark last beat of active tab
    if (t === group.activeTab && br.endBeat >= br.startBeat) {
      _branchLastBeat.add(br.endBeat);
    }
  }
}

function _branchHeaderHTML(group, groupIdx) {
  const num = group.startIdx + 1;
  let title = "";
  if (group.type === "if") title = "Branch";
  else if (group.type === "switch") title = `Switch ${group.switchVar || ""}`;
  else if (group.type === "choice") title = group.prompt ? `"${_esc(group.prompt.slice(0, 25))}"` : "Choice";

  let tabs = "";
  for (let t = 0; t < group.branches.length; t++) {
    const br = group.branches[t];
    const active = t === group.activeTab ? " active" : "";
    tabs += `<button class="branch-tab${active}" data-group="${groupIdx}" data-tab="${t}">${_esc(br.label)}</button>`;
  }

  const isSelected = state.currentBeat >= group.startIdx && state.currentBeat <= group.endIdx;
  let cls = "beat-row beat-branch-header";
  if (isSelected) cls += " beat-selected";

  const depth = (_nestDepth && _nestDepth[group.startIdx]) || 0;
  const indent = depth > 0
    ? `<span class="beat-indent" style="width:${depth * 12}px;border-left:2px solid var(--gold, #f8d030);display:inline-block;margin-right:2px;"></span>`
    : "";

  return `<div class="${cls}" data-index="${group.startIdx}" data-group-idx="${groupIdx}">`
    + `<span class="beat-num">${num}</span>`
    + `<span class="beat-tag beat-tag-brn" style="background:#b8860b;color:#fff;">BRN</span>`
    + indent
    + `<span class="branch-title">${_esc(title)}</span>`
    + `<span class="branch-tabs">${tabs}</span>`
    + `</div>`;
}

function _buildNestDepth(frames) {
  const depth = new Array(frames.length).fill(0);
  let d = 0;
  for (let i = 0; i < frames.length; i++) {
    const beat = frames[i].beat;
    if (!beat) { depth[i] = d; continue; }
    const t = beat.type;
    // Closing beats: reduce depth BEFORE this beat
    if (t === "endif" || t === "endswitch" || t === "endchoice"
        || (t === "condition" && beat.data.branch !== "if")
        || t === "case") {
      d = Math.max(0, d - 1);
    }
    depth[i] = d;
    // Opening beats: increase depth AFTER this beat
    if ((t === "condition" && (beat.data.branch === "if" || beat.data.branch === "elif" || beat.data.branch === "else"))
        || t === "switch" || t === "choice" || t === "case" || t === "option") {
      d++;
    }
  }
  return depth;
}

// Condition label: convert raw condition to human-readable text
function _condLabel(beat) {
  const d = beat.data || {};
  const cond = d.raw_condition || d.condition || "";
  if (d.branch === "else") return "else";
  // Common patterns
  if (cond.includes("== MALE")) return "if Male";
  if (cond.includes("== FEMALE")) return "if Female";
  if (cond.includes("== YES")) return "if Yes";
  if (cond.includes("== NO")) return "if No";
  if (cond.includes("== TRUE")) return "if True";
  if (cond.includes("== FALSE")) return "if False";
  const prefix = d.branch === "elif" ? "elif " : "if ";
  // Flag shorthand
  const fm = cond.match(/^(?:not )?FLAG_(.+)$/);
  if (fm) {
    const neg = cond.startsWith("not ") ? "not " : "";
    return prefix + neg + fm[1].replace(/_/g, " ").toLowerCase();
  }
  return prefix + cond;
}

// ---------------------------------------------------------------------------
// Movement block lookup
// ---------------------------------------------------------------------------

function _getMovementCommands(label) {
  const frames = state.frames || [];
  for (const f of frames) {
    const b = f.beat;
    if (b && b.type === "movement" && (b.data || {}).label === label) {
      return b.data.commands || [];
    }
  }
  return null;
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

  const depth = (_nestDepth && _nestDepth[index]) || 0;
  if (depth > 0) cls += " beat-nested";
  if (_beatToGroup[index] !== undefined) cls += " beat-in-branch";
  if (_branchLastBeat.has(index)) cls += " beat-branch-last";

  const num = index + 1;
  let tag = beat ? (BEAT_TAGS[beat.type] || "???") : "???";
  const t = beat ? beat.type : "";

  // Condition beats: show branch-specific tag
  if (t === "condition") {
    const br = (beat.data || {}).branch;
    if (br === "elif") tag = "ELF";
    else if (br === "else") tag = "ELS";
    else tag = "IF";
  }

  const tagCls = `beat-tag beat-tag-${tag.toLowerCase()}`;
  const indent = depth > 0
    ? `<span class="beat-indent" style="width:${depth * 12}px;border-left:2px solid var(--gold, #f8d030);display:inline-block;margin-right:2px;"></span>`
    : "";

  if (isLabel) {
    const name = (beat.data || {}).name || (beat.data || {}).label || tag;
    return `<div class="${cls}" data-index="${index}">`
      + `<span class="beat-num">${num}</span>`
      + `<span class="${tagCls}">${_esc(tag)}</span>`
      + indent
      + `<span class="beat-label-name">${_esc(name)}</span>`
      + `</div>`;
  }

  // Use human-readable labels for conditionals
  let summary;
  if (t === "condition") {
    summary = _condLabel(beat);
  } else {
    summary = beatSummary(beat);
  }

  // Collapsible movement header for "do" commands
  const d = beat ? (beat.data || {}) : {};
  const actions = d.actions || [];
  const firstAction = actions.length === 1 ? actions[0] : null;
  if (t === "move" && firstAction && firstAction.verb === "do" && firstAction.label) {
    const cmds = _getMovementCommands(firstAction.label);
    if (cmds && cmds.length > 0) {
      const expanded = _expandedMovements.has(index);
      const arrow = expanded ? "\u25BC" : "\u25B6";
      let html = `<div class="${cls} beat-movement-header" data-index="${index}">`
        + `<span class="beat-num">${num}</span>`
        + `<span class="${tagCls}">${_esc(tag)}</span>`
        + indent
        + `<span class="beat-mov-toggle" data-mov-idx="${index}">${arrow}</span>`
        + `<span class="beat-summary">${_esc(firstAction.actor || "")} ${_esc(cmds.join(", ").slice(0, 40))}</span>`
        + `</div>`;
      if (expanded) {
        for (const cmd of cmds) {
          html += `<div class="beat-movement-sub" data-index="${index}">`
            + `<span class="beat-num"></span>`
            + `<span class="beat-tag"></span>`
            + indent
            + `<span class="beat-mov-dot">\u00B7</span>`
            + `<span class="beat-summary">${_esc(cmd)}</span>`
            + `</div>`;
        }
      }
      return html;
    }
  }

  return `<div class="${cls}" data-index="${index}">`
    + `<span class="beat-num">${num}</span>`
    + `<span class="${tagCls}">${_esc(tag)}</span>`
    + indent
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
// Visible beat navigation (skips data beats hidden from Beats tab)
// ---------------------------------------------------------------------------

function _isDataBeat(index) {
  const frames = state.frames;
  if (!frames || index < 0 || index >= frames.length) return false;
  const beat = frames[index].beat;
  return beat && (beat.type === "movement" || beat.type === "text");
}

function _nextVisibleBeat(current, direction) {
  const frames = state.frames;
  if (!frames) return current;
  let idx = current + direction;
  while (idx >= 0 && idx < frames.length) {
    if (!_isDataBeat(idx)) return idx;
    idx += direction;
  }
  // No visible beat found — return out-of-bounds to trigger chain boundary
  return idx;
}

function _lastVisibleBeat() {
  const frames = state.frames;
  if (!frames) return 0;
  for (let i = frames.length - 1; i >= 0; i--) {
    if (!_isDataBeat(i)) return i;
  }
  return 0;
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
        goToBeat(_nextVisibleBeat(state.currentBeat, 1));
      }
      break;

    case "k":
    case "ArrowUp":
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        _moveBeat(-1);  // move up
      } else {
        e.preventDefault();
        goToBeat(_nextVisibleBeat(state.currentBeat, -1));
      }
      break;

    case "Home":
      e.preventDefault();
      goToBeat(0);
      break;

    case "End":
      e.preventDefault();
      goToBeat(_lastVisibleBeat());
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
      _container.dispatchEvent(new CustomEvent("beat-add-request", {
        bubbles: true,
        detail: { afterIndex: state.currentBeat, position: "after" },
      }));
      break;

    case "i":
      e.preventDefault();
      _container.dispatchEvent(new CustomEvent("beat-add-request", {
        bubbles: true,
        detail: { afterIndex: state.currentBeat, position: "before" },
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
  // Movement toggle click
  const movToggle = e.target.closest(".beat-mov-toggle");
  if (movToggle) {
    const idx = parseInt(movToggle.dataset.movIdx, 10);
    if (!isNaN(idx)) {
      if (_expandedMovements.has(idx)) {
        _expandedMovements.delete(idx);
      } else {
        _expandedMovements.add(idx);
      }
      _render();
      _container.focus();
    }
    return;
  }

  // Movement sub-row click — select the parent MOV beat
  const subRow = e.target.closest(".beat-movement-sub");
  if (subRow) {
    const idx = parseInt(subRow.dataset.index, 10);
    if (!isNaN(idx)) {
      goToBeat(idx);
      _container.focus();
    }
    return;
  }

  // Branch tab click
  const tab = e.target.closest(".branch-tab");
  if (tab) {
    const gIdx = parseInt(tab.dataset.group, 10);
    const tIdx = parseInt(tab.dataset.tab, 10);
    if (!isNaN(gIdx) && !isNaN(tIdx) && _branchGroups[gIdx]) {
      // Close any open editor — the beat may become hidden
      if (state.editingBeat >= 0) closeEditor();
      _branchGroups[gIdx].activeTab = tIdx;
      _savedTabs[_branchGroups[gIdx].startIdx] = tIdx;
      _updateHiddenForGroup(_branchGroups[gIdx]);
      // Navigate to first beat in the selected tab
      const br = _branchGroups[gIdx].branches[tIdx];
      if (br && br.startBeat <= br.endBeat) {
        goToBeat(br.startBeat);
      }
      _render();
      _container.focus();
    }
    return;
  }

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
