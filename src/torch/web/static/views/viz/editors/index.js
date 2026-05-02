// index.js — Editor dispatcher, shared helpers, Add Beat menu
// S233 — Phase 2 (Editors)

import {
  state, on, off, emit, openEditor, closeEditor, goToBeat, setDirty,
  resimulate, BEAT_TAGS, EDITOR_OPENED, EDITOR_CLOSED,
} from "../state.js";
import { pushHistory } from "../history.js";
import { api } from "../../../app.js";
import { esc } from "../../../utils.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Map beat type → editor module filename (without .js) */
const TYPE_MODULE = {
  dialogue: "dialogue", text: "dialogue",
  move: "movement", movement: "movement",
  emote: "emote",
  flag: "flag", var: "var",
  page: "page",
  condition: "condition", endif: "structural",
  switch: "switchcase", case: "switchcase", endswitch: "structural",
  choice: "choice", option: "choice", endchoice: "structural",
  check: "check",
  sound: "sound", music: "sound", fanfare: "sound", cry: "sound",
  fade: "fade",
  flow: "flow", gotoif: "gotoif",
  battle: "battle",
  special: "special",
  lock: "simple", faceplayer: "simple",
  closemessage: "simple", waitstate: "simple",
  label: "label",
  pause: "pause",
  shake: "shake",
  hide: "visibility", show: "visibility",
  setpos: "position",
  give: "give", take: "give",
  pory: "pory", raw: "pory",
  comment: "comment",
  // Wait/sync — simple keyword beats
  waitmessage: "simple", waitbutton: "simple", waitse: "simple",
  waitmoncry: "simple", waitfanfare: "simple",
  // Extended commands — use generic editor for now
  message: "simple", wildbattle: "generic",
  random: "simple", shop: "simple", braille: "simple",
  showmon: "simple", hidemon: "simple",
  showmoney: "simple", showcoins: "simple",
  buffer: "generic", tile: "generic", door: "generic",
  stat: "simple", slots: "simple", getpos: "generic",
};

const ADD_CATEGORIES = [
  { name: "Dialogue", items: [
    { type: "msg", label: "Message (msg)", desc: "NPC speaks with portrait" },
    { type: "msgnpc", label: "Message NPC (msgnpc)", desc: "NPC speaks without portrait" },
    { type: "text", label: "Text block", desc: "Reusable text with label" },
  ]},
  { name: "NPC", items: [
    { type: "emote", label: "Emote", desc: "Show emote bubble" },
    { type: "faceplayer", label: "Face Player", desc: "NPC faces player" },
    { type: "hide", label: "Hide NPC", desc: "Hide an actor" },
    { type: "show", label: "Show NPC", desc: "Show an actor" },
    { type: "setpos", label: "Teleport", desc: "Instantly reposition actor (no animation)" },
  ]},
  { name: "Movement", items: [
    { type: "move", label: "Move", desc: "Walk/run/slide/jump" },
    { type: "movement", label: "Movement Block", desc: "Raw movement_block" },
  ]},
  { name: "Screen", items: [
    { type: "fade", label: "Fade", desc: "Screen fade" },
    { type: "shake", label: "Shake", desc: "Screen shake" },
    { type: "sound", label: "Sound", desc: "Play sound effect" },
    { type: "music", label: "Music", desc: "Change music" },
    { type: "fanfare", label: "Fanfare", desc: "Play fanfare" },
    { type: "cry", label: "Cry", desc: "Play Pokemon cry" },
    { type: "pause", label: "Pause", desc: "Wait N frames" },
  ]},
  { name: "Logic", items: [
    { type: "condition", label: "If / Elif", desc: "Conditional branch (flag, var, defeated)" },
    { type: "endif", label: "End If", desc: "Close if block" },
    { type: "switch", label: "Switch", desc: "Multi-way branch on variable" },
    { type: "case", label: "Case", desc: "Match value in switch" },
    { type: "endswitch", label: "End Switch", desc: "Close switch block" },
    { type: "choice", label: "Choice", desc: "Player choice menu" },
    { type: "option", label: "Option", desc: "Choice option" },
    { type: "endchoice", label: "End Choice", desc: "Close choice block" },
    { type: "check", label: "Check", desc: "Check item/party/money/badge" },
    { type: "flag", label: "Flag", desc: "Set/clear flag" },
    { type: "var", label: "Variable", desc: "Set/check variable" },
    { type: "gotoif", label: "Goto If (legacy)", desc: "Branch on flag (prefer If)" },
    { type: "flow", label: "Flow", desc: "goto/call/end/return" },
    { type: "special", label: "Special", desc: "Call special function" },
  ]},
  { name: "Structure", items: [
    { type: "page", label: "Page", desc: "NPC page (multi-state)" },
    { type: "label", label: "Label", desc: "Section label" },
    { type: "lock", label: "Lock", desc: "Lock NPCs" },
    { type: "closemessage", label: "Close Message", desc: "Close dialogue" },
    { type: "waitstate", label: "Wait State", desc: "Wait for special" },
    { type: "battle", label: "Battle", desc: "Trainer battle" },
    { type: "give", label: "Give Item", desc: "Give item to player" },
    { type: "pory", label: "Poryscript", desc: "Raw Poryscript" },
    { type: "raw", label: "Raw", desc: "Raw TorScript line" },
    { type: "comment", label: "Comment", desc: "# Comment" },
  ]},
];

const NEW_BEAT_DEFAULTS = {
  msg: 'msg "Text here$"',
  msgnpc: 'msgnpc "Text here$"',
  text: 'text NewText "Text here$"',
  move: "player walk down 1",
  emote: "player emote !",
  fade: "fade to_black",
  sound: "sound SE_SELECT",
  music: "music MUS_DUMMY",
  fanfare: "fanfare MUS_FANFARE1",
  cry: "cry SPECIES_NONE",
  pause: "pause 30",
  page: "page 1",
  condition: "if FLAG_TEMP_1",
  endif: "endif",
  switch: "switch VAR_TEMP_0",
  case: "case 0",
  endswitch: "endswitch",
  choice: 'choice "What will you do?"',
  option: 'option "Yes"',
  endchoice: "endchoice",
  check: "check item ITEM_POTION",
  flag: "flag set FLAG_TEMP_1",
  var: "var set VAR_TEMP_1 0",
  gotoif: "gotoif FLAG_TEMP_1 LabelName",
  flow: "end",
  label: "label NewLabel",
  lock: "lock",
  faceplayer: "faceplayer",
  closemessage: "closemessage",
  waitstate: "waitstate",
  special: "special HealPlayerParty",
  battle: "battle single TRAINER_FOE",
  hide: "hide player",
  show: "show player",
  setpos: "setpos player 0 0",
  shake: "shake",
  movement: "movement player {}",
  pory: "pory {}",
  raw: "raw nop",
  comment: "# Comment",
  give: "give ITEM_POTION 1",
};

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _container = null;
let _panelEl = null;
let _bodyEl = null;
let _handlers = [];         // [{name, handler}]
let _currentEditor = null;  // { apply() } from the loaded editor module
let _addMenu = null;        // Add Beat popover element
let _addMenuCleanup = null; // Cleanup function for add menu listeners

// Panel button handler refs (Fix 2.4)
let _closeBtnEl = null;
let _cancelBtnEl = null;
let _applyBtnEl = null;

// ---------------------------------------------------------------------------
// Shared helpers (passed to every editor module)
// ---------------------------------------------------------------------------

// esc() removed — now imported from utils.js

function getActorNames() {
  const names = Object.keys(state.cast);
  if (!names.includes("player")) names.unshift("player");
  return names;
}

function getLabelNames() {
  return state.frames
    .filter(f => f.beat && f.beat.type === "label")
    .map(f => (f.beat.data || {}).name || (f.beat.data || {}).label || "")
    .filter(Boolean);
}

function buildActorSelect(id, selected) {
  const names = getActorNames();
  const options = names.map(n =>
    `<option value="${esc(n)}" ${n === selected ? "selected" : ""}>${esc(n)}</option>`
  ).join("");
  return `<select id="${id}" class="viz-ed-select">${options}</select>`;
}

function buildLabelSelect(id, selected) {
  const labels = getLabelNames();
  const options = ['<option value="">--</option>'].concat(
    labels.map(l =>
      `<option value="${esc(l)}" ${l === selected ? "selected" : ""}>${esc(l)}</option>`
    )
  ).join("");
  return `<select id="${id}" class="viz-ed-select">${options}</select>`;
}

function buildSearchPicker(id, items, selected) {
  return `<div class="viz-search-picker">
    <input type="text" id="${id}" autocomplete="off" value="${esc(selected || "")}" placeholder="Search..." />
    <div class="viz-search-dropdown" id="${id}-dropdown"></div>
  </div>`;
}

function attachSearchPicker(container, id, items) {
  const input = container.querySelector(`#${id}`);
  const dropdown = container.querySelector(`#${id}-dropdown`);
  if (!input || !dropdown) return;

  const normalized = items.map(item => {
    if (typeof item === "string") return { value: item, display: item };
    return { value: item.const || item.name || "", display: item.display || item.name || item.const || "" };
  });

  function showMatches(filter) {
    const lower = (filter || "").toLowerCase();
    const matches = lower
      ? normalized.filter(it => it.display.toLowerCase().includes(lower)).slice(0, 20)
      : normalized.slice(0, 20);
    dropdown.innerHTML = matches.map(m =>
      `<div class="viz-search-item" data-value="${esc(m.value)}">${esc(m.display)}</div>`
    ).join("");
    dropdown.style.display = matches.length ? "block" : "none";
  }

  input.addEventListener("input", () => showMatches(input.value));
  input.addEventListener("focus", () => { if (input.value) showMatches(input.value); });

  dropdown.addEventListener("mousedown", e => {
    // mousedown so it fires before blur
    const el = e.target.closest(".viz-search-item");
    if (el) {
      input.value = el.dataset.value;
      dropdown.style.display = "none";
    }
  });

  input.addEventListener("blur", () => {
    setTimeout(() => { dropdown.style.display = "none"; }, 150);
  });
}

function field(label, inputHTML) {
  return `<div class="viz-editor-field"><label>${esc(label)}</label>${inputHTML}</div>`;
}

const helpers = {
  getActorNames, getLabelNames,
  buildActorSelect, buildLabelSelect,
  buildSearchPicker, attachSearchPicker,
  esc, field,
};

// ---------------------------------------------------------------------------
// Editor panel DOM
// ---------------------------------------------------------------------------

function _createPanel() {
  _panelEl = document.createElement("div");
  _panelEl.className = "viz-editor-panel";
  _panelEl.style.display = "none";
  _panelEl.innerHTML = `
    <div class="viz-editor-header">
      <span class="viz-editor-tag"></span>
      <span class="viz-editor-title">Edit</span>
      <button class="viz-editor-close" title="Close">\u00d7</button>
    </div>
    <div class="viz-editor-body"></div>
    <div class="viz-editor-actions">
      <button class="btn-apply" id="viz-ed-apply" title="Apply changes (Enter)">Apply</button>
      <button class="btn-cancel" id="viz-ed-cancel" title="Cancel editing (Escape)">Cancel</button>
    </div>`;
  _container.appendChild(_panelEl);
  _bodyEl = _panelEl.querySelector(".viz-editor-body");

  _closeBtnEl = _panelEl.querySelector(".viz-editor-close");
  _cancelBtnEl = _panelEl.querySelector("#viz-ed-cancel");
  _applyBtnEl = _panelEl.querySelector("#viz-ed-apply");
  _closeBtnEl.addEventListener("click", _handleCancel);
  _cancelBtnEl.addEventListener("click", _handleCancel);
  _applyBtnEl.addEventListener("click", _handleApply);
}

// ---------------------------------------------------------------------------
// Editor open / close lifecycle
// ---------------------------------------------------------------------------

async function _onEditorOpened() {
  try {
    const idx = state.editingBeat;
    if (idx < 0 || idx >= state.frames.length) return;

    const frame = state.frames[idx];
    if (!frame || !frame.beat) return;

    const beat = frame.beat;
    const beatType = beat.type || "raw";
    const moduleName = TYPE_MODULE[beatType] || "generic";

    // Update header
    const tag = BEAT_TAGS[beatType] || "???";
    const tagEl = _panelEl.querySelector(".viz-editor-tag");
    tagEl.textContent = tag;
    tagEl.className = `viz-editor-tag beat-tag beat-tag-${beatType}`;
    _panelEl.querySelector(".viz-editor-title").textContent =
      `Edit ${beatType.charAt(0).toUpperCase() + beatType.slice(1)}`;

    // Clear body
    _bodyEl.innerHTML = "";
    _currentEditor = null;

    // Dynamically import the editor module
    let mod;
    try {
      mod = await import(`./${moduleName}.js`);
    } catch {
      try {
        mod = await import("./generic.js");
      } catch {
        _bodyEl.innerHTML = `<div class="viz-editor-info">No editor available for "${esc(beatType)}"</div>`;
        _panelEl.style.display = "block";
        return;
      }
    }

    _currentEditor = mod.render(_bodyEl, beat, helpers);
    _panelEl.style.display = "block";
  } catch (err) {
    if (_panelEl) _panelEl.style.display = "block";
    if (_bodyEl) _bodyEl.innerHTML = `<div class="viz-editor-info">Error: ${esc(err.message)}</div>`;
  }
}

function _onEditorClosed() {
  _panelEl.style.display = "none";
  _bodyEl.innerHTML = "";
  _currentEditor = null;
}

async function _handleApply() {
  if (!_currentEditor) return;

  const newText = _currentEditor.apply();
  if (newText == null) return; // validation failed

  const idx = state.editingBeat;
  if (idx < 0 || idx >= state.frames.length) return;
  const beat = state.frames[idx].beat;

  pushHistory(state.source);

  const lines = state.source.split("\n");
  const sl = beat.source_line;
  const el = beat.source_end_line != null ? beat.source_end_line : sl + 1;
  const newLines = newText.split("\n");
  lines.splice(sl, el - sl, ...newLines);
  const newSource = lines.join("\n");

  await resimulate(newSource);
  setDirty(true);
  closeEditor();
}

function _handleCancel() {
  closeEditor();
}

// ---------------------------------------------------------------------------
// Add Beat menu
// ---------------------------------------------------------------------------

function _onAddRequest(e) {
  const afterIndex = (e.detail && e.detail.afterIndex != null) ? e.detail.afterIndex : state.currentBeat;
  _showAddMenu(afterIndex);
}

function _showAddMenu(afterIndex) {
  _closeAddMenu();

  _addMenu = document.createElement("div");
  _addMenu.className = "viz-add-menu";

  let html = "";
  for (const cat of ADD_CATEGORIES) {
    html += `<div class="viz-add-category">${esc(cat.name)}</div>`;
    for (const item of cat.items) {
      html += `<div class="viz-add-item" data-type="${esc(item.type)}" title="${esc(item.desc)}">${esc(item.label)}</div>`;
    }
  }
  _addMenu.innerHTML = html;
  _container.appendChild(_addMenu);

  // Click handler for items
  const onItemClick = async (ev) => {
    const el = ev.target.closest(".viz-add-item");
    if (!el) return;

    const type = el.dataset.type;
    const defaultLine = NEW_BEAT_DEFAULTS[type];
    if (!defaultLine) return;

    pushHistory(state.source);

    // Find insertion point
    const frame = state.frames[afterIndex];
    let insertLine;
    if (frame && frame.beat) {
      insertLine = frame.beat.source_end_line != null
        ? frame.beat.source_end_line
        : frame.beat.source_line + 1;
    } else {
      insertLine = state.source.split("\n").length;
    }

    const lines = state.source.split("\n");
    lines.splice(insertLine, 0, defaultLine);
    const newSource = lines.join("\n");

    await resimulate(newSource);
    setDirty(true);

    // Find the newly inserted beat by matching the insertion line
    let newIdx = -1;
    for (let i = 0; i < state.frames.length; i++) {
      if (state.frames[i].beat && state.frames[i].beat.source_line === insertLine) {
        newIdx = i;
        break;
      }
    }
    if (newIdx < 0) newIdx = afterIndex + 1;  // fallback
    if (newIdx >= 0 && newIdx < state.frames.length) {
      goToBeat(newIdx);
      openEditor(newIdx);
    }

    _closeAddMenu();
  };
  _addMenu.addEventListener("click", onItemClick);

  // Close on Escape or outside click
  const onKey = (ev) => {
    if (ev.key === "Escape") _closeAddMenu();
  };
  const onOutside = (ev) => {
    if (_addMenu && !_addMenu.contains(ev.target)) _closeAddMenu();
  };
  document.addEventListener("keydown", onKey);
  // Delay outside-click listener so the triggering click doesn't immediately close
  setTimeout(() => document.addEventListener("mousedown", onOutside), 0);

  _addMenuCleanup = () => {
    document.removeEventListener("keydown", onKey);
    document.removeEventListener("mousedown", onOutside);
    _addMenu.removeEventListener("click", onItemClick);
  };
}

function _closeAddMenu() {
  if (_addMenuCleanup) { _addMenuCleanup(); _addMenuCleanup = null; }
  if (_addMenu && _addMenu.parentNode) _addMenu.parentNode.removeChild(_addMenu);
  _addMenu = null;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function init(containerEl) {
  _container = containerEl;
  _createPanel();

  _handlers.push({ name: EDITOR_OPENED, handler: on(EDITOR_OPENED, _onEditorOpened) });
  _handlers.push({ name: EDITOR_CLOSED, handler: on(EDITOR_CLOSED, _onEditorClosed) });

  // Listen for add-beat requests from beatList (uses document since containers are in different DOM branches)
  document.addEventListener("beat-add-request", _onAddRequest);
}

export function cleanup() {
  for (const { name, handler } of _handlers) off(name, handler);
  _handlers = [];
  document.removeEventListener("beat-add-request", _onAddRequest);
  _closeAddMenu();

  // Remove panel button listeners (Fix 2.4)
  if (_closeBtnEl) _closeBtnEl.removeEventListener("click", _handleCancel);
  if (_cancelBtnEl) _cancelBtnEl.removeEventListener("click", _handleCancel);
  if (_applyBtnEl) _applyBtnEl.removeEventListener("click", _handleApply);
  _closeBtnEl = null;
  _cancelBtnEl = null;
  _applyBtnEl = null;

  if (_panelEl && _panelEl.parentNode) _panelEl.parentNode.removeChild(_panelEl);
  _panelEl = null;
  _bodyEl = null;
  _currentEditor = null;
  _container = null;
}
