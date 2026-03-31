/**
 * TORCH IDE — Context Panel (right panel).
 * TORCH_MODULE
 *
 * Thin tab-hosting shell. Delegates content to tab modules via contextTabs.js.
 * Scripts Mode temporarily takes over the panel (suspendTabs/restoreTabs).
 *
 * Tabs registered:
 *   - Props (properties, map summary, event details)
 *   - Encounters (compact wild encounter table)
 */

import { api } from "./app.js";
import { esc } from "./utils.js";
import {
  ideOn, ideEmit,
  IDE_MAP_SELECTED, IDE_EVENT_SELECTED, IDE_EVENT_DESELECTED,
  IDE_OPEN_SCRIPT, IDE_SCRIPT_LOADED, IDE_SCRIPT_UNLOADED,
  IDE_MODE_CHANGED,
} from "./ide.js";
import {
  registerTab, initTabs, setMap, activateTab, getActiveTab,
  suspendTabs, restoreTabs, cleanupTabs,
} from "./contextTabs.js";
import { setViewContext } from "./viewContext.js";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _container = null;
let _headerEl = null;
let _tabBarEl = null;
let _bodyEl = null;
let _scriptsModeEl = null;  // dedicated container for scripts mode content
let _currentMap = null;
let _unsubs = [];
let _scriptsMode = false;
let _vizEditorUnsubs = [];
let _currentEditor = null;

// ---------------------------------------------------------------------------
// Init / Cleanup
// ---------------------------------------------------------------------------

export function initContextPanel(container) {
  _container = container;

  // Header (map name + collapse button)
  _headerEl = document.createElement("div");
  _headerEl.className = "ide-right-header";
  _headerEl.innerHTML = "<h3>Properties</h3>";
  container.appendChild(_headerEl);

  // Tab bar
  _tabBarEl = document.createElement("div");
  _tabBarEl.className = "ide-context-tabs";
  container.appendChild(_tabBarEl);

  // Body (tab content area)
  _bodyEl = document.createElement("div");
  _bodyEl.className = "ide-right-body";
  container.appendChild(_bodyEl);

  // Scripts mode container (hidden by default, lives alongside tabs body)
  _scriptsModeEl = document.createElement("div");
  _scriptsModeEl.className = "ide-right-body ide-scripts-mode-body";
  _scriptsModeEl.style.display = "none";
  container.appendChild(_scriptsModeEl);

  // Register tabs
  registerTab("props", "Props", () => import("./tabs/propsTab.js"));
  registerTab("npcs", "NPCs", () => import("./tabs/npcsTab.js"));
  registerTab("encounters", "Enc", () => import("./tabs/encountersTab.js"));
  registerTab("warps", "Warps", () => import("./tabs/warpsTab.js"));
  registerTab("scripts", "Scripts", () => import("./tabs/scriptsTab.js"));
  registerTab("flags", "Flags", () => import("./tabs/flagsTab.js"));
  registerTab("shops", "Shops", () => import("./tabs/shopsTab.js"));
  registerTab("trainers", "Trainers", () => import("./tabs/trainersTab.js"));
  registerTab("triggers", "Trigs", () => import("./tabs/triggersTab.js"));

  // Initialize tab system
  initTabs(_tabBarEl, _bodyEl);

  // Activate default tab
  activateTab("props");

  // Listen for IDE events
  _unsubs.push(ideOn(IDE_MAP_SELECTED, _onMapSelected));
  _unsubs.push(ideOn(IDE_EVENT_SELECTED, _onEventSelected));
  _unsubs.push(ideOn(IDE_EVENT_DESELECTED, _onEventDeselected));
  _unsubs.push(ideOn(IDE_MODE_CHANGED, _onModeChanged));
  _unsubs.push(ideOn(IDE_SCRIPT_LOADED, _onScriptLoaded));
  _unsubs.push(ideOn(IDE_SCRIPT_UNLOADED, _onScriptUnloaded));
}

export function cleanupContextPanel() {
  for (const unsub of _unsubs) unsub();
  _unsubs = [];
  _unwireVizEditorEvents();
  _currentEditor = null;
  cleanupTabs();
  _container = null;
  _headerEl = null;
  _tabBarEl = null;
  _bodyEl = null;
  _scriptsModeEl = null;
  _currentMap = null;
  _scriptsMode = false;
}

// ---------------------------------------------------------------------------
// Event handlers
// ---------------------------------------------------------------------------

function _onMapSelected(detail) {
  _currentMap = detail.name;
  setViewContext(detail.name);
  _setHeader(detail.name);

  if (!_scriptsMode) {
    setMap(detail.name);
  }
}

function _onEventSelected(detail) {
  if (!detail || !detail.type) return;
  if (_scriptsMode) return;

  _expandIfCollapsed();

  // Only auto-switch to Props if we're not on a tab that handles events itself
  const active = getActiveTab();
  if (active !== "props" && active !== "npcs" && active !== "warps") {
    activateTab("props");
  }
}

function _onEventDeselected() {
  if (_scriptsMode) return;
  // Props tab handles this internally
}

function _onModeChanged(detail) {
  _scriptsMode = detail.mode === "scripts";
  if (_scriptsMode) {
    suspendTabs();
    _bodyEl.style.display = "none";
    _scriptsModeEl.style.display = "";
    _wireVizEditorEvents();
    _showScriptSelector();
  } else {
    _unwireVizEditorEvents();
    _currentEditor = null;
    _scriptsModeEl.style.display = "none";
    _scriptsModeEl.innerHTML = "";
    _bodyEl.style.display = "";
    restoreTabs();
  }
}

function _onScriptLoaded(detail) {
  if (!_scriptsMode) return;
  _expandIfCollapsed();
  _showScriptInfo(detail.mapName, detail.scriptName);
}

function _onScriptUnloaded() {
  if (!_scriptsMode) return;
  _showScriptSelector();
}

// ---------------------------------------------------------------------------
// Scripts Mode — viz editor event bridge (unchanged from original)
// ---------------------------------------------------------------------------

function _wireVizEditorEvents() {
  _unwireVizEditorEvents();
  import("./views/viz/state.js").then(({ on, EDITOR_OPENED, EDITOR_CLOSED }) => {
    const h1 = on(EDITOR_OPENED, () => _showBeatEditor());
    const h2 = on(EDITOR_CLOSED, () => {
      _currentEditor = null;
      import("./views/viz/state.js").then(({ state }) => {
        if (state.mapName && state.scriptName) {
          _showScriptInfo(state.mapName, state.scriptName);
        }
      });
    });
    _vizEditorUnsubs.push({ cleanup: () => {
      import("./views/viz/state.js").then(({ off, EDITOR_OPENED, EDITOR_CLOSED }) => {
        off(EDITOR_OPENED, h1);
        off(EDITOR_CLOSED, h2);
      });
    }});
  });
}

function _unwireVizEditorEvents() {
  for (const u of _vizEditorUnsubs) {
    if (u.cleanup) u.cleanup();
  }
  _vizEditorUnsubs = [];
}

async function _showBeatEditor() {
  const el = _scriptsModeEl;
  if (!el) return;
  _expandIfCollapsed();

  const { state, closeEditor, resimulate, setDirty } = await import("./views/viz/state.js");
  const { pushHistory } = await import("./views/viz/history.js");

  const idx = state.editingBeat;
  if (idx < 0 || idx >= state.frames.length) return;

  const frame = state.frames[idx];
  if (!frame || !frame.beat) return;

  const beat = frame.beat;
  const beatType = beat.type || "raw";

  const TYPE_MODULE = {
    dialogue: "dialogue", text: "dialogue",
    move: "movement", movement: "movement",
    emote: "emote", flag: "flag", var: "var",
    sound: "sound", music: "sound", fanfare: "sound", cry: "sound",
    fade: "fade", flow: "flow", gotoif: "gotoif",
    battle: "battle", special: "special",
    lock: "simple", faceplayer: "simple",
    closemessage: "simple", waitstate: "simple",
    label: "label", pause: "pause", shake: "shake",
    hide: "visibility", show: "visibility",
    setpos: "position", give: "give", comment: "comment",
  };
  const moduleName = TYPE_MODULE[beatType] || "generic";

  _setHeader(`Edit: ${beatType}`);

  let html = `<div class="ide-beat-editor-body" id="ide-beat-ed-body"></div>
    <div style="display:flex;gap:0.4rem;margin-top:0.5rem;padding:0 0.2rem">
      <button id="ide-beat-ed-apply" style="flex:1;padding:0.3rem;font-size:0.78rem;font-weight:600;
        background:var(--accent);color:#111;border:none;border-radius:4px;cursor:pointer">Apply</button>
      <button id="ide-beat-ed-cancel" style="flex:1;padding:0.3rem;font-size:0.78rem;
        background:var(--surface-2);color:var(--text-secondary);border:1px solid var(--border-subtle);
        border-radius:4px;cursor:pointer">Cancel</button>
    </div>`;
  el.innerHTML = html;

  const bodyEl = document.getElementById("ide-beat-ed-body");
  const applyBtn = document.getElementById("ide-beat-ed-apply");
  const cancelBtn = document.getElementById("ide-beat-ed-cancel");

  const helpers = await _buildEditorHelpers();

  let mod;
  try {
    mod = await import(`./views/viz/editors/${moduleName}.js`);
  } catch {
    try { mod = await import("./views/viz/editors/generic.js"); } catch { return; }
  }

  _currentEditor = mod.render(bodyEl, beat, helpers);

  applyBtn.addEventListener("click", async () => {
    if (!_currentEditor) return;
    const newText = _currentEditor.apply();
    if (newText == null) return;

    const sl = beat.source_line;
    const el = beat.source_end_line != null ? beat.source_end_line : sl + 1;
    pushHistory(state.source);
    const lines = state.source.split("\n");
    lines.splice(sl, el - sl, ...newText.split("\n"));
    await resimulate(lines.join("\n"));
    setDirty(true);
    closeEditor();
  });

  cancelBtn.addEventListener("click", () => closeEditor());
}

async function _buildEditorHelpers() {
  const { state } = await import("./views/viz/state.js");
  const { esc: escUtil } = await import("./utils.js");

  function getActorNames() {
    const names = new Set(["player"]);
    for (const name of Object.keys(state.cast || {})) names.add(name);
    for (const f of state.frames || []) {
      for (const name of Object.keys(f.actors || {})) names.add(name);
    }
    return [...names];
  }

  function getLabelNames() {
    return (state.frames || [])
      .filter(f => f.beat && f.beat.type === "label")
      .map(f => f.beat.data?.label_name || f.beat.data?.name || "");
  }

  function buildActorSelect(id, selected) {
    const names = getActorNames();
    return `<select id="${escUtil(id)}" class="viz-ed-select">${names.map(n =>
      `<option value="${escUtil(n)}"${n === selected ? " selected" : ""}>${escUtil(n)}</option>`
    ).join("")}</select>`;
  }

  function buildLabelSelect(id, selected) {
    const labels = getLabelNames();
    return `<select id="${escUtil(id)}" class="viz-ed-select">${labels.map(l =>
      `<option value="${escUtil(l)}"${l === selected ? " selected" : ""}>${escUtil(l)}</option>`
    ).join("")}</select>`;
  }

  function buildSearchPicker(id, items, selected) {
    return `<input type="text" id="${escUtil(id)}" class="viz-ed-input"
      value="${escUtil(selected || "")}" list="${escUtil(id)}-list" autocomplete="off" />
      <datalist id="${escUtil(id)}-list">${items.map(i =>
        `<option value="${escUtil(i)}">`).join("")}</datalist>`;
  }

  function attachSearchPicker() {}

  function field(label, inputHTML) {
    return `<div class="viz-ed-field"><label class="viz-ed-label">${escUtil(label)}</label>${inputHTML}</div>`;
  }

  return {
    getActorNames, getLabelNames,
    buildActorSelect, buildLabelSelect,
    buildSearchPicker, attachSearchPicker,
    esc: escUtil, field,
  };
}

// ---------------------------------------------------------------------------
// Scripts Mode views
// ---------------------------------------------------------------------------

async function _showScriptSelector() {
  _setHeader("Scripts");
  const el = _scriptsModeEl;
  if (!el || !_currentMap) {
    if (el) el.innerHTML = `<div style="padding:0.8rem;color:var(--text-dim);font-size:0.8rem">
      Select a map to see its scripts</div>`;
    return;
  }

  el.innerHTML = `<div style="padding:0.5rem;color:var(--text-dim);font-size:0.8rem">Loading scripts...</div>`;

  try {
    const res = await api(`/scenes/${encodeURIComponent(_currentMap)}`);
    const scripts = res.ok && res.data ? (res.data.scripts || res.data) : [];
    if (!Array.isArray(scripts) || scripts.length === 0) {
      el.innerHTML = `<div style="padding:0.8rem;color:var(--text-dim);font-size:0.8rem">
        No workspace scripts for this map.<br>
        <span style="font-size:0.72rem">Double-click an NPC to try loading its script.</span>
      </div>`;
      return;
    }

    let html = `<div class="ide-prop-section"><h4>Available Scripts</h4>`;
    for (const s of scripts) {
      const name = s.name || s;
      const beats = s.beat_count ? ` (${s.beat_count} beats)` : "";
      html += `<div class="ide-prop-row" style="cursor:pointer;padding:0.2rem 0">
        <a class="ide-script-mode-link" data-map="${esc(_currentMap)}" data-script="${esc(name)}"
           style="color:var(--accent);cursor:pointer;font-size:0.8rem;font-weight:500">
          ${esc(name)}</a>
        <span style="color:var(--text-dim);font-size:0.72rem">${esc(beats)}</span>
      </div>`;
    }
    html += `</div>`;
    el.innerHTML = html;

    el.querySelectorAll(".ide-script-mode-link").forEach(link => {
      link.addEventListener("click", () => {
        ideEmit(IDE_OPEN_SCRIPT, {
          mapName: link.dataset.map,
          scriptName: link.dataset.script,
        });
      });
    });
  } catch (_) {
    el.innerHTML = `<div style="padding:0.5rem;color:var(--text-dim)">Failed to load scripts</div>`;
  }
}

function _showScriptInfo(mapName, scriptName) {
  _setHeader(`Script: ${scriptName}`);
  const el = _scriptsModeEl;
  if (!el) return;

  import("./views/viz/state.js").then(({ state, on, off, goToBeat, togglePatrolMode, BEAT_CHANGED, FRAMES_UPDATED, PATROL_MODE_CHANGED }) => {
    const render = () => {
      const frameCount = state.frames.length;
      const beat = state.currentBeat;
      const castNames = Object.keys(state.cast);
      const frame = state.frames[beat];
      const dialogue = frame?.dialogue || "";

      let html = "";

      html += `<div class="ide-prop-section">`;
      html += `<h4>Scene</h4>`;
      html += _propRow("Map", mapName);
      html += _propRow("Script", scriptName);
      html += _propRow("Beats", `${beat + 1} / ${frameCount}`);
      if (castNames.length > 0) html += _propRow("Cast", castNames.join(", "));
      html += `</div>`;

      html += `<div class="ide-prop-section">`;
      html += `<h4>Navigate</h4>`;
      html += `<div style="display:flex;gap:0.3rem;flex-wrap:wrap">`;
      html += `<button class="ide-script-nav" data-action="first" title="First beat"
                style="padding:0.2rem 0.5rem;font-size:0.75rem;cursor:pointer;
                background:var(--surface-2);color:var(--text-secondary);border:1px solid var(--border-subtle);border-radius:3px">|&lt;</button>`;
      html += `<button class="ide-script-nav" data-action="prev" title="Previous beat"
                style="padding:0.2rem 0.5rem;font-size:0.75rem;cursor:pointer;
                background:var(--surface-2);color:var(--text-secondary);border:1px solid var(--border-subtle);border-radius:3px">&lt;</button>`;
      html += `<button class="ide-script-nav" data-action="next" title="Next beat"
                style="padding:0.2rem 0.5rem;font-size:0.75rem;cursor:pointer;
                background:var(--surface-2);color:var(--text-secondary);border:1px solid var(--border-subtle);border-radius:3px">&gt;</button>`;
      html += `<button class="ide-script-nav" data-action="last" title="Last beat"
                style="padding:0.2rem 0.5rem;font-size:0.75rem;cursor:pointer;
                background:var(--surface-2);color:var(--text-secondary);border:1px solid var(--border-subtle);border-radius:3px">&gt;|</button>`;
      html += `</div></div>`;

      if (dialogue) {
        const clean = dialogue.replace(/\\p/g, "\n").replace(/\\n/g, "\n");
        html += `<div class="ide-prop-section">`;
        html += `<h4>Dialogue</h4>`;
        html += `<div style="background:#1a1f2e;border:2px solid #4a5570;border-radius:4px;
                  padding:0.4rem 0.5rem;font-family:monospace;font-size:0.75rem;
                  color:#e0e4f0;white-space:pre-wrap;line-height:1.4;max-height:120px;overflow-y:auto">${esc(clean)}</div>`;
        html += `</div>`;
      }

      if (frame?.beat) {
        html += `<div class="ide-prop-section">`;
        html += `<h4>Current Beat</h4>`;
        html += _propRow("Type", frame.beat.type || "?");
        if (frame.beat.data?.actor) html += _propRow("Actor", frame.beat.data.actor);
        html += `</div>`;
      }

      // Starting Position button — for NPCs with patrol positions
      const ti = state.triggerInfo;
      const hasPatrol = ti && ti.npc_positions && ti.npc_positions.length > 1;
      if (hasPatrol) {
        const active = state.patrolMode;
        html += `<div class="ide-prop-section">`;
        html += `<h4>Preview Setup</h4>`;
        html += `<button class="ide-patrol-toggle" style="padding:0.25rem 0.6rem;font-size:0.72rem;cursor:pointer;
                  background:${active ? "var(--accent)" : "var(--surface-2)"};
                  color:${active ? "#111" : "var(--text-secondary)"};
                  border:1px solid ${active ? "var(--accent)" : "var(--border-subtle)"};
                  border-radius:4px;font-weight:${active ? "600" : "400"};width:100%">
                  ${active ? "Hide Patrol Tiles" : "Starting Position"}</button>`;
        if (active) {
          const pos = ti.npc_positions[state.npcPatrolIndex || 0];
          if (pos) {
            html += `<div style="font-size:0.7rem;color:var(--text-dim);margin-top:0.3rem;text-align:center">
              Click a tile on the map to set NPC start position.
              <br>Currently: (${pos.x}, ${pos.y}) facing ${pos.facing}
            </div>`;
          }
        }
        html += `</div>`;
      }

      el.innerHTML = html;

      el.querySelectorAll(".ide-script-nav").forEach(btn => {
        btn.addEventListener("click", () => {
          const action = btn.dataset.action;
          if (action === "first") goToBeat(0);
          else if (action === "prev") goToBeat(Math.max(0, state.currentBeat - 1));
          else if (action === "next") goToBeat(Math.min(state.frames.length - 1, state.currentBeat + 1));
          else if (action === "last") goToBeat(state.frames.length - 1);
        });
      });
      // Patrol mode toggle
      const patrolBtn = el.querySelector(".ide-patrol-toggle");
      if (patrolBtn) {
        patrolBtn.addEventListener("click", () => togglePatrolMode());
      }
    };

    render();

    const h1 = on(BEAT_CHANGED, render);
    const h2 = on(FRAMES_UPDATED, render);
    const h3 = on(PATROL_MODE_CHANGED, render);

    el._vizCleanup = () => {
      off(BEAT_CHANGED, h1);
      off(FRAMES_UPDATED, h2);
      off(PATROL_MODE_CHANGED, h3);
    };
  });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _setHeader(title) {
  if (_scriptsModeEl && _scriptsModeEl._vizCleanup) {
    _scriptsModeEl._vizCleanup();
    _scriptsModeEl._vizCleanup = null;
  }
  if (_headerEl) {
    _headerEl.innerHTML = `<button class="ide-right-collapse" title="Collapse panel">\u25B6</button><h3>${esc(title)}</h3>`;
    _headerEl.querySelector(".ide-right-collapse").addEventListener("click", _toggleCollapse);
  }
}

function _toggleCollapse() {
  const right = document.getElementById("ide-right");
  const handle = document.getElementById("ide-resize-right");
  if (!right) return;

  const collapsed = right.classList.toggle("collapsed");
  if (handle) handle.style.display = collapsed ? "none" : "";

  const btn = _headerEl?.querySelector(".ide-right-collapse");
  if (btn) btn.textContent = collapsed ? "\u25C0" : "\u25B6";
}

function _expandIfCollapsed() {
  const right = document.getElementById("ide-right");
  if (!right || !right.classList.contains("collapsed")) return;
  const handle = document.getElementById("ide-resize-right");
  right.classList.remove("collapsed");
  if (handle) handle.style.display = "";
  const btn = _headerEl?.querySelector(".ide-right-collapse");
  if (btn) btn.textContent = "\u25B6";
}

function _propRow(label, value) {
  return `<div class="ide-prop-row">
    <span class="ide-prop-label">${esc(label)}</span>
    <span class="ide-prop-value">${value}</span>
  </div>`;
}
