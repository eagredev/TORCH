/**
 * TORCH IDE — Context Panel (right panel).
 *
 * Shows context-sensitive properties based on what is selected:
 * - No selection: map summary (dimensions, tilesets, event counts)
 * - NPC selected: properties, script, dialogue preview
 * - Warp selected: destination, coordinates
 * - Trigger selected: script, variable, value
 * - Sign selected: type, script
 */

import { api } from "./app.js";
import { esc } from "./utils.js";
import {
  ideOn, ideEmit,
  IDE_MAP_SELECTED, IDE_EVENT_SELECTED, IDE_EVENT_DESELECTED,
  IDE_OPEN_SCRIPT, IDE_SCRIPT_LOADED, IDE_SCRIPT_UNLOADED,
  IDE_MODE_CHANGED,
} from "./ide.js";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _container = null;
let _headerEl = null;
let _bodyEl = null;
let _currentMap = null;
let _mapDetail = null;
let _unsubs = [];
let _scriptsMode = false;
let _vizEditorUnsubs = [];  // viz bus handlers for editor open/close
let _currentEditor = null;  // { apply() } from loaded editor module

// ---------------------------------------------------------------------------
// Init / Cleanup
// ---------------------------------------------------------------------------

export function initContextPanel(container) {
  _container = container;

  // Header
  _headerEl = document.createElement("div");
  _headerEl.className = "ide-right-header";
  _headerEl.innerHTML = "<h3>Properties</h3>";
  container.appendChild(_headerEl);

  // Body
  _bodyEl = document.createElement("div");
  _bodyEl.className = "ide-right-body";
  container.appendChild(_bodyEl);

  // Show default state
  _showDefault();

  // Listen for events
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
  _container = null;
  _headerEl = null;
  _bodyEl = null;
  _currentMap = null;
  _mapDetail = null;
  _scriptsMode = false;
  _unwireVizEditorEvents();
  _currentEditor = null;
}

// ---------------------------------------------------------------------------
// Event handlers
// ---------------------------------------------------------------------------

async function _onMapSelected(detail) {
  _currentMap = detail.name;
  _mapDetail = null;

  _setHeader(detail.name);
  _bodyEl.innerHTML = '<div style="padding:0.5rem;color:var(--text-dim)">Loading...</div>';

  // Load map detail
  try {
    const res = await api(`/explorer/map/${encodeURIComponent(detail.name)}`);
    if (res.ok) {
      _mapDetail = res.data;
      _showMapSummary();
    }
  } catch (_) {
    _bodyEl.innerHTML = '<div style="padding:0.5rem;color:var(--text-dim)">Failed to load map data</div>';
  }
}

function _onEventSelected(detail) {
  if (!detail || !detail.type) return;
  if (_scriptsMode) return; // don't show NPC properties in scripts mode

  // Auto-expand the right panel if it's collapsed
  _expandIfCollapsed();

  switch (detail.type) {
    case "npc": _showNpcProperties(detail.data); break;
    case "warp": _showWarpProperties(detail.data); break;
    case "trigger": _showTriggerProperties(detail.data); break;
    case "sign": _showSignProperties(detail.data); break;
    default: _showMapSummary(); break;
  }
}

function _onEventDeselected() {
  if (_scriptsMode) return; // don't override script view
  if (_mapDetail) {
    _showMapSummary();
  } else {
    _showDefault();
  }
}

function _onModeChanged(detail) {
  const wasScripts = _scriptsMode;
  _scriptsMode = detail.mode === "scripts";
  if (_scriptsMode) {
    _wireVizEditorEvents();
    _showScriptSelector();
  } else {
    _unwireVizEditorEvents();
    _currentEditor = null;
    // Restore normal view
    if (_mapDetail) _showMapSummary();
    else _showDefault();
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
// Views
// ---------------------------------------------------------------------------

function _showDefault() {
  _setHeader("Properties");
  if (_bodyEl) {
    _bodyEl.innerHTML = `
      <div style="padding:1rem;color:var(--text-dim);text-align:center;font-size:0.8rem">
        Select a map to see its properties
      </div>
    `;
  }
}

function _showMapSummary() {
  if (!_mapDetail || !_bodyEl) return;

  const d = _mapDetail;
  const lay = d.layout || {};
  _setHeader(d.name || _currentMap);

  let html = "";

  // Layout section (always visible)
  html += `<div class="ide-prop-section">`;
  html += `<h4>Layout</h4>`;
  html += _propRow("Size", `${lay.width || "?"}x${lay.height || "?"} metatiles`);
  if (lay.primary_tileset) html += _propRow("Primary", _formatTilesetName(lay.primary_tileset));
  if (lay.secondary_tileset) html += _propRow("Secondary", _formatTilesetName(lay.secondary_tileset));
  html += `</div>`;

  // Event counts
  html += `<div class="ide-prop-section">`;
  html += `<h4>Events</h4>`;
  html += `<div class="ide-event-counts">`;
  html += _eventBadge("npc", "NPCs", lay.npc_count || 0);
  html += _eventBadge("warp", "Warps", lay.warp_event_count || 0);
  html += _eventBadge("trigger", "Triggers", lay.trigger_count || 0);
  html += _eventBadge("sign", "Signs", lay.sign_count || 0);
  html += `</div>`;
  html += `</div>`;

  // Tabs: Info | Connections | Scripts
  html += `<div class="ide-right-tabs">`;
  html += `<button class="ide-right-tab active" data-tab="info">Info</button>`;
  html += `<button class="ide-right-tab" data-tab="connections">Connections</button>`;
  html += `<button class="ide-right-tab" data-tab="scripts">Scripts</button>`;
  html += `</div>`;

  // Tab: Info
  html += `<div class="ide-tab-content" data-tab-content="info">`;
  if (d.type) html += _propRow("Type", d.type);
  if (d.region) html += _propRow("Region", d.region);
  html += `</div>`;

  // Tab: Connections
  html += `<div class="ide-tab-content" data-tab-content="connections" style="display:none">`;
  const connsOut = d.connections_out || [];
  const warpsOut = d.warps_out || [];
  if (connsOut.length === 0 && warpsOut.length === 0) {
    html += `<div style="color:var(--text-dim);font-size:0.78rem">No connections</div>`;
  } else {
    for (const c of connsOut) {
      html += _propRow(c.direction || "?", `<a data-nav-map="${esc(c.map)}">${esc(c.map)}</a>`);
    }
    if (warpsOut.length > 0) {
      const destMaps = [...new Set(warpsOut.map(w => w.dest_map))];
      for (const dest of destMaps) {
        html += _propRow("Warp", `<a data-nav-map="${esc(dest)}">${esc(dest)}</a>`);
      }
    }
  }
  html += `</div>`;

  // Tab: Scripts
  html += `<div class="ide-tab-content" data-tab-content="scripts" style="display:none">`;
  html += `<div id="ide-scripts-list" style="color:var(--text-dim);font-size:0.78rem">Loading...</div>`;
  html += `</div>`;

  _bodyEl.innerHTML = html;

  // Tab switching
  _bodyEl.querySelectorAll(".ide-right-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      _bodyEl.querySelectorAll(".ide-right-tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      _bodyEl.querySelectorAll(".ide-tab-content").forEach(c => {
        c.style.display = c.dataset.tabContent === tab.dataset.tab ? "" : "none";
      });
    });
  });

  // Navigation click handlers
  _bodyEl.querySelectorAll("[data-nav-map]").forEach(el => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      ideEmit(IDE_MAP_SELECTED, { name: el.dataset.navMap, source: "context" });
    });
  });

  // Load scripts list
  _loadScriptsList();
}

async function _loadScriptsList() {
  const el = document.getElementById("ide-scripts-list");
  if (!el || !_currentMap) return;

  try {
    const res = await api(`/scenes/${encodeURIComponent(_currentMap)}`);
    if (res.ok && Array.isArray(res.data)) {
      if (res.data.length === 0) {
        el.innerHTML = '<span style="color:var(--text-dim)">No scripts</span>';
        return;
      }
      el.innerHTML = res.data.map(s => {
        const name = s.name || s;
        return `<div class="ide-prop-row">
          <a class="ide-script-link" data-map="${esc(_currentMap)}" data-script="${esc(name)}"
             style="color:var(--accent);cursor:pointer;font-size:0.78rem">${esc(name)}</a>
        </div>`;
      }).join("");

      // Wire script click -> open drawer
      el.querySelectorAll(".ide-script-link").forEach(link => {
        link.addEventListener("click", () => {
          ideEmit(IDE_OPEN_SCRIPT, {
            mapName: link.dataset.map,
            scriptName: link.dataset.script,
          });
        });
      });
    } else {
      el.innerHTML = '<span style="color:var(--text-dim)">No scripts</span>';
    }
  } catch (_) {
    el.innerHTML = '<span style="color:var(--text-dim)">Failed to load</span>';
  }
}

function _showNpcProperties(npc) {
  if (!_bodyEl) return;
  _setHeader(`NPC #${npc.object_id}`);

  let html = "";

  // Basic info
  html += `<div class="ide-prop-section">`;
  html += `<h4>Object Event</h4>`;
  html += _propRow("ID", npc.object_id);
  html += _propRow("Position", `(${npc.x}, ${npc.y})`);
  html += _propRow("Elevation", npc.elevation);
  html += _propRow("Graphics", _formatConstName(npc.graphics_id, "OBJ_EVENT_GFX_"));
  html += _propRow("Movement", _formatConstName(npc.movement_type, "MOVEMENT_TYPE_"));
  html += `</div>`;

  // Script
  if (npc.script) {
    html += `<div class="ide-prop-section">`;
    html += `<h4>Script</h4>`;
    html += _propRow("Label", `<code>${esc(npc.script)}</code>`);
    html += `</div>`;
  }

  // Edit NPC button (always shown)
  html += `<div class="ide-prop-section">`;
  html += `<button class="ide-edit-npc-btn" data-map="${esc(_currentMap)}" data-npc-id="${npc.object_id}"
            style="margin-top:0.2rem;padding:0.3rem 0.6rem;font-size:0.75rem;
            background:var(--accent);color:#111;border:none;border-radius:4px;
            cursor:pointer;font-weight:600;width:100%">Edit NPC</button>`;
  html += `</div>`;

  // Trainer info
  if (npc.is_trainer) {
    html += `<div class="ide-prop-section">`;
    html += `<h4>Trainer</h4>`;
    html += _propRow("Type", _formatConstName(npc.trainer_type, "TRAINER_TYPE_"));
    html += `</div>`;
  }

  // Flag
  if (npc.flag && npc.flag !== "0") {
    html += `<div class="ide-prop-section">`;
    html += `<h4>Flag</h4>`;
    html += _propRow("Flag", `<code>${esc(npc.flag)}</code>`);
    html += `</div>`;
  }

  _bodyEl.innerHTML = html;

  // Wire "Edit NPC" button
  const editBtn = _bodyEl.querySelector(".ide-edit-npc-btn");
  if (editBtn) {
    editBtn.addEventListener("click", async () => {
      const mapName = editBtn.dataset.map;
      const npcId = editBtn.dataset.npcId;
      if (mapName && npcId) {
        const { openToolModal } = await import("./toolbar.js");
        openToolModal(`NPC #${npcId}`, async () => {
          const mod = await import("./views/npcDetail.js");
          return {
            render: (container) => mod.renderNpcDetailModal(container, mapName, npcId),
            cleanup: () => mod.cleanupNpcDetail(),
          };
        });
      }
    });
  }
}

function _showWarpProperties(warp) {
  _setHeader(`Warp #${warp.id}`);

  let html = `<div class="ide-prop-section">`;
  html += `<h4>Warp Event</h4>`;
  html += _propRow("Position", `(${warp.x}, ${warp.y})`);
  html += _propRow("Elevation", warp.elevation);
  html += _propRow("Dest Map", `<a data-nav-map="${esc(warp.dest_map)}">${esc(warp.dest_map)}</a>`);
  html += _propRow("Dest Warp", warp.dest_warp_id);
  html += `</div>`;

  _bodyEl.innerHTML = html;

  _bodyEl.querySelectorAll("[data-nav-map]").forEach(el => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      ideEmit(IDE_MAP_SELECTED, { name: el.dataset.navMap, source: "context" });
    });
  });
}

function _showTriggerProperties(trig) {
  _setHeader(`Trigger #${trig.id}`);

  let html = `<div class="ide-prop-section">`;
  html += `<h4>Coord Event</h4>`;
  html += _propRow("Position", `(${trig.x}, ${trig.y})`);
  html += _propRow("Type", trig.type || "trigger");
  if (trig.script) html += _propRow("Script", `<code>${esc(trig.script)}</code>`);
  if (trig.var) html += _propRow("Variable", `<code>${esc(trig.var)}</code>`);
  if (trig.var_value) html += _propRow("Value", trig.var_value);
  if (trig.weather) html += _propRow("Weather", trig.weather);
  html += `</div>`;

  _bodyEl.innerHTML = html;
}

function _showSignProperties(sign) {
  _setHeader(`Sign #${sign.id}`);

  let html = `<div class="ide-prop-section">`;
  html += `<h4>BG Event</h4>`;
  html += _propRow("Position", `(${sign.x}, ${sign.y})`);
  html += _propRow("Type", sign.type || "sign");
  if (sign.script) html += _propRow("Script", `<code>${esc(sign.script)}</code>`);
  if (sign.player_facing_dir) html += _propRow("Facing", sign.player_facing_dir);
  if (sign.item) html += _propRow("Item", sign.item);
  if (sign.flag) html += _propRow("Flag", `<code>${esc(sign.flag)}</code>`);
  html += `</div>`;

  _bodyEl.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Scripts Mode — viz editor event bridge
// ---------------------------------------------------------------------------

function _wireVizEditorEvents() {
  _unwireVizEditorEvents();
  import("./views/viz/state.js").then(({ on, EDITOR_OPENED, EDITOR_CLOSED }) => {
    const h1 = on(EDITOR_OPENED, () => _showBeatEditor());
    const h2 = on(EDITOR_CLOSED, () => {
      _currentEditor = null;
      // Return to script info view
      import("./views/viz/state.js").then(({ state }) => {
        if (state.mapName && state.scriptName) {
          _showScriptInfo(state.mapName, state.scriptName);
        }
      });
    });
    _vizEditorUnsubs.push({ mod: null, cleanup: () => {
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
  if (!_bodyEl) return;
  _expandIfCollapsed();

  const { state, closeEditor, resimulate, setDirty } = await import("./views/viz/state.js");
  const { pushHistory } = await import("./views/viz/history.js");

  const idx = state.editingBeat;
  if (idx < 0 || idx >= state.frames.length) return;

  const frame = state.frames[idx];
  if (!frame || !frame.beat) return;

  const beat = frame.beat;
  const beatType = beat.type || "raw";

  // Map beat type to editor module
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

  // Build editor chrome
  let html = `<div class="ide-beat-editor-body" id="ide-beat-ed-body"></div>
    <div style="display:flex;gap:0.4rem;margin-top:0.5rem;padding:0 0.2rem">
      <button id="ide-beat-ed-apply" style="flex:1;padding:0.3rem;font-size:0.78rem;font-weight:600;
        background:var(--accent);color:#111;border:none;border-radius:4px;cursor:pointer">Apply</button>
      <button id="ide-beat-ed-cancel" style="flex:1;padding:0.3rem;font-size:0.78rem;
        background:var(--surface-2);color:var(--text-secondary);border:1px solid var(--border-subtle);
        border-radius:4px;cursor:pointer">Cancel</button>
    </div>`;
  _bodyEl.innerHTML = html;

  const bodyEl = document.getElementById("ide-beat-ed-body");
  const applyBtn = document.getElementById("ide-beat-ed-apply");
  const cancelBtn = document.getElementById("ide-beat-ed-cancel");

  // Build helpers (same as editors/index.js provides)
  const helpers = await _buildEditorHelpers();

  // Load editor module
  let mod;
  try {
    mod = await import(`./views/viz/editors/${moduleName}.js`);
  } catch {
    try { mod = await import("./views/viz/editors/generic.js"); } catch { return; }
  }

  _currentEditor = mod.render(bodyEl, beat, helpers);

  // Wire buttons
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
  const { state, BEAT_TAGS } = await import("./views/viz/state.js");
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

  function attachSearchPicker(container, id, items) {
    // Datalist already handles this via the buildSearchPicker
  }

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
  if (!_bodyEl || !_currentMap) {
    if (_bodyEl) _bodyEl.innerHTML = `<div style="padding:0.8rem;color:var(--text-dim);font-size:0.8rem">
      Select a map to see its scripts</div>`;
    return;
  }

  _bodyEl.innerHTML = `<div style="padding:0.5rem;color:var(--text-dim);font-size:0.8rem">Loading scripts...</div>`;

  try {
    const res = await api(`/scenes/${encodeURIComponent(_currentMap)}`);
    const scripts = res.ok && res.data ? (res.data.scripts || res.data) : [];
    if (!Array.isArray(scripts) || scripts.length === 0) {
      _bodyEl.innerHTML = `<div style="padding:0.8rem;color:var(--text-dim);font-size:0.8rem">
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
    _bodyEl.innerHTML = html;

    // Wire clicks
    _bodyEl.querySelectorAll(".ide-script-mode-link").forEach(link => {
      link.addEventListener("click", () => {
        ideEmit(IDE_OPEN_SCRIPT, {
          mapName: link.dataset.map,
          scriptName: link.dataset.script,
        });
      });
    });
  } catch (_) {
    _bodyEl.innerHTML = `<div style="padding:0.5rem;color:var(--text-dim)">Failed to load scripts</div>`;
  }
}

function _showScriptInfo(mapName, scriptName) {
  _setHeader(`Script: ${scriptName}`);
  if (!_bodyEl) return;

  // Import viz state dynamically to show current beat info
  import("./views/viz/state.js").then(({ state, on, off, goToBeat, BEAT_CHANGED, FRAMES_UPDATED }) => {
    const render = () => {
      const frameCount = state.frames.length;
      const beat = state.currentBeat;
      const castNames = Object.keys(state.cast);
      const frame = state.frames[beat];
      const dialogue = frame?.dialogue || "";

      let html = "";

      // Script info
      html += `<div class="ide-prop-section">`;
      html += `<h4>Scene</h4>`;
      html += _propRow("Map", mapName);
      html += _propRow("Script", scriptName);
      html += _propRow("Beats", `${beat + 1} / ${frameCount}`);
      if (castNames.length > 0) html += _propRow("Cast", castNames.join(", "));
      html += `</div>`;

      // Beat navigation
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

      // Current dialogue preview
      if (dialogue) {
        const clean = dialogue.replace(/\\p/g, "\n").replace(/\\n/g, "\n");
        html += `<div class="ide-prop-section">`;
        html += `<h4>Dialogue</h4>`;
        html += `<div style="background:#1a1f2e;border:2px solid #4a5570;border-radius:4px;
                  padding:0.4rem 0.5rem;font-family:monospace;font-size:0.75rem;
                  color:#e0e4f0;white-space:pre-wrap;line-height:1.4;max-height:120px;overflow-y:auto">${esc(clean)}</div>`;
        html += `</div>`;
      }

      // Beat type info
      if (frame?.beat) {
        html += `<div class="ide-prop-section">`;
        html += `<h4>Current Beat</h4>`;
        html += _propRow("Type", frame.beat.type || "?");
        if (frame.beat.data?.actor) html += _propRow("Actor", frame.beat.data.actor);
        html += `</div>`;
      }

      _bodyEl.innerHTML = html;

      // Wire nav buttons
      _bodyEl.querySelectorAll(".ide-script-nav").forEach(btn => {
        btn.addEventListener("click", () => {
          const action = btn.dataset.action;
          if (action === "first") goToBeat(0);
          else if (action === "prev") goToBeat(Math.max(0, state.currentBeat - 1));
          else if (action === "next") goToBeat(Math.min(state.frames.length - 1, state.currentBeat + 1));
          else if (action === "last") goToBeat(state.frames.length - 1);
        });
      });
    };

    // Initial render
    render();

    // Re-render on beat change (store handlers for cleanup on next view switch)
    const h1 = on(BEAT_CHANGED, render);
    const h2 = on(FRAMES_UPDATED, render);

    // Store cleanup so next _bodyEl.innerHTML wipe doesn't leak
    _bodyEl._vizCleanup = () => {
      off(BEAT_CHANGED, h1);
      off(FRAMES_UPDATED, h2);
    };
  });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _setHeader(title) {
  // Cleanup any viz event listeners from previous script info view
  if (_bodyEl && _bodyEl._vizCleanup) {
    _bodyEl._vizCleanup();
    _bodyEl._vizCleanup = null;
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

  // Update arrow direction
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

function _eventBadge(type, label, count) {
  return `<span class="ide-event-badge">
    <span class="dot ${type}"></span>
    ${count} ${esc(label)}
  </span>`;
}

function _formatConstName(name, prefix) {
  if (!name) return "None";
  let s = name;
  if (prefix && s.startsWith(prefix)) s = s.slice(prefix.length);
  return s.replace(/_/g, " ").toLowerCase()
    .replace(/\b\w/g, c => c.toUpperCase());
}

function _formatTilesetName(name) {
  if (!name) return "?";
  if (name.startsWith("gTileset_")) return name.slice(9);
  return name;
}
