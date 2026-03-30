/**
 * TORCH IDE — Properties Tab (inline event editor).
 * TORCH_MODULE
 *
 * Full Porymap-parity property editor: NPC sprite/movement/flag/dialogue,
 * warp destinations, trigger script/var/value, sign type/text.
 * All editable in-place with Save/Discard.
 *
 * Tab API: init(container, mapName), update(mapName), onSelect(), onDeselect(), cleanup()
 */

import { api, postApi } from "../app.js";
import { esc } from "../utils.js";
import {
  ideOn, ideEmit,
  IDE_MAP_SELECTED, IDE_EVENT_SELECTED, IDE_EVENT_DESELECTED, IDE_OPEN_SCRIPT,
} from "../ide.js";
import { openToolModal } from "../toolbar.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MOVEMENT_TYPES = [
  "MOVEMENT_TYPE_NONE", "MOVEMENT_TYPE_FACE_UP", "MOVEMENT_TYPE_FACE_DOWN",
  "MOVEMENT_TYPE_FACE_LEFT", "MOVEMENT_TYPE_FACE_RIGHT",
  "MOVEMENT_TYPE_LOOK_AROUND", "MOVEMENT_TYPE_WANDER_AROUND",
  "MOVEMENT_TYPE_WANDER_UP_AND_DOWN", "MOVEMENT_TYPE_WANDER_LEFT_AND_RIGHT",
  "MOVEMENT_TYPE_WALK_IN_PLACE_UP", "MOVEMENT_TYPE_WALK_IN_PLACE_DOWN",
  "MOVEMENT_TYPE_WALK_IN_PLACE_LEFT", "MOVEMENT_TYPE_WALK_IN_PLACE_RIGHT",
  "MOVEMENT_TYPE_JOG_IN_PLACE_UP", "MOVEMENT_TYPE_JOG_IN_PLACE_DOWN",
  "MOVEMENT_TYPE_JOG_IN_PLACE_LEFT", "MOVEMENT_TYPE_JOG_IN_PLACE_RIGHT",
  "MOVEMENT_TYPE_WALK_UP_AND_DOWN", "MOVEMENT_TYPE_WALK_LEFT_AND_RIGHT",
  "MOVEMENT_TYPE_FACE_UP_AND_DOWN", "MOVEMENT_TYPE_FACE_LEFT_AND_RIGHT",
  "MOVEMENT_TYPE_WALK_SEQUENCE_UP_RIGHT_LEFT_DOWN",
  "MOVEMENT_TYPE_WALK_SEQUENCE_RIGHT_LEFT_DOWN_UP",
  "MOVEMENT_TYPE_WALK_SEQUENCE_DOWN_UP_RIGHT_LEFT",
  "MOVEMENT_TYPE_WALK_SEQUENCE_LEFT_DOWN_UP_RIGHT",
  "MOVEMENT_TYPE_WALK_SEQUENCE_UP_LEFT_RIGHT_DOWN",
  "MOVEMENT_TYPE_WALK_SEQUENCE_LEFT_RIGHT_DOWN_UP",
  "MOVEMENT_TYPE_WALK_SEQUENCE_DOWN_UP_LEFT_RIGHT",
  "MOVEMENT_TYPE_WALK_SEQUENCE_RIGHT_DOWN_UP_LEFT",
  "MOVEMENT_TYPE_COPY_PLAYER", "MOVEMENT_TYPE_COPY_PLAYER_OPPOSITE",
  "MOVEMENT_TYPE_COPY_PLAYER_COUNTERCLOCKWISE",
  "MOVEMENT_TYPE_COPY_PLAYER_CLOCKWISE",
  "MOVEMENT_TYPE_HIDDEN", "MOVEMENT_TYPE_WALK_SLOWLY_IN_PLACE_DOWN",
];

const TRAINER_TYPES = [
  "TRAINER_TYPE_NONE", "TRAINER_TYPE_NORMAL",
  "TRAINER_TYPE_SEE_ALL_DIRECTIONS", "TRAINER_TYPE_BURIED",
];

const SIGN_TYPES = [
  "BG_EVENT_PLAYER_FACING_ANY",
  "BG_EVENT_PLAYER_FACING_NORTH", "BG_EVENT_PLAYER_FACING_SOUTH",
  "BG_EVENT_PLAYER_FACING_EAST", "BG_EVENT_PLAYER_FACING_WEST",
];

const BG_EVENT_TYPES = [
  "sign", "hidden_item", "secret_base",
];

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _container = null;
let _currentMap = null;
let _mapDetail = null;
let _unsubs = [];
let _active = false;
let _dirty = false;
let _originalEvent = null;  // snapshot for discard

// ---------------------------------------------------------------------------
// Tab API
// ---------------------------------------------------------------------------

export function init(container, mapName) {
  _container = container;
  _currentMap = mapName;
  _active = true;

  _unsubs.push(ideOn(IDE_EVENT_SELECTED, _onEventSelected));
  _unsubs.push(ideOn(IDE_EVENT_DESELECTED, _onEventDeselected));

  if (mapName) {
    _loadMapDetail(mapName);
  } else {
    _showDefault();
  }
}

export function update(mapName) {
  _currentMap = mapName;
  _mapDetail = null;
  _dirty = false;
  if (mapName) {
    _loadMapDetail(mapName);
  } else {
    _showDefault();
  }
}

export function onSelect() { _active = true; }
export function onDeselect() { _active = false; }

export function cleanup() {
  for (const unsub of _unsubs) unsub();
  _unsubs = [];
  _container = null;
  _currentMap = null;
  _mapDetail = null;
  _active = false;
  _dirty = false;
  _originalEvent = null;
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function _loadMapDetail(mapName) {
  if (!_container) return;
  _container.innerHTML = '<div style="padding:0.5rem;color:var(--text-dim)">Loading...</div>';

  try {
    const res = await api(`/explorer/map/${encodeURIComponent(mapName)}`);
    if (res.ok) {
      _mapDetail = res.data;
      _showMapSummary();
    }
  } catch (_) {
    _container.innerHTML = '<div style="padding:0.5rem;color:var(--text-dim)">Failed to load map data</div>';
  }
}

// ---------------------------------------------------------------------------
// Event handlers
// ---------------------------------------------------------------------------

function _onEventSelected(detail) {
  if (!detail || !detail.type || !_active) return;
  _dirty = false;

  switch (detail.type) {
    case "npc": _showNpcEditor(detail.data); break;
    case "warp": _showWarpEditor(detail.data); break;
    case "trigger": _showTriggerEditor(detail.data); break;
    case "sign": _showSignEditor(detail.data); break;
    default: _showMapSummary(); break;
  }
}

function _onEventDeselected() {
  if (!_active) return;
  if (_mapDetail) _showMapSummary();
  else _showDefault();
}

// ---------------------------------------------------------------------------
// Helper: build a select dropdown
// ---------------------------------------------------------------------------

function _buildSelect(id, options, selected) {
  return `<select id="${esc(id)}" class="ide-edit-select">${options.map(o =>
    `<option value="${esc(o)}"${o === selected ? " selected" : ""}>${esc(_humanize(o))}</option>`
  ).join("")}</select>`;
}

function _humanize(name) {
  if (!name) return "None";
  // Remove common prefixes
  for (const pfx of ["MOVEMENT_TYPE_", "TRAINER_TYPE_", "BG_EVENT_PLAYER_FACING_", "BG_EVENT_", "OBJ_EVENT_GFX_"]) {
    if (name.startsWith(pfx)) { name = name.slice(pfx.length); break; }
  }
  return name.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// Helper: save/discard button row
// ---------------------------------------------------------------------------

function _saveDiscardRow() {
  return `<div class="ide-edit-actions">
    <button class="ide-edit-save" disabled>Save Changes</button>
    <button class="ide-edit-discard" disabled>Discard</button>
  </div>`;
}

function _wireSaveDiscard(eventType, eventIndex, getChanges) {
  if (!_container) return;

  const saveBtn = _container.querySelector(".ide-edit-save");
  const discardBtn = _container.querySelector(".ide-edit-discard");
  if (!saveBtn || !discardBtn) return;

  // Watch for changes on all inputs/selects/textareas
  _container.querySelectorAll("input, select, textarea").forEach(el => {
    el.addEventListener("input", () => _markDirty());
    el.addEventListener("change", () => _markDirty());
  });

  function _markDirty() {
    _dirty = true;
    saveBtn.disabled = false;
    discardBtn.disabled = false;
    saveBtn.classList.add("active");
  }

  saveBtn.addEventListener("click", async () => {
    const changes = getChanges();
    if (!changes || Object.keys(changes).length === 0) return;

    saveBtn.textContent = "Saving...";
    saveBtn.disabled = true;

    try {
      const res = await postApi(
        `/map/${encodeURIComponent(_currentMap)}/events/${eventType}/${eventIndex}`,
        changes
      );
      if (res.ok) {
        _dirty = false;
        saveBtn.textContent = "Saved!";
        saveBtn.classList.remove("active");
        discardBtn.disabled = true;

        // Notify canvas to refresh
        ideEmit("ide:event-updated", { mapName: _currentMap });

        setTimeout(() => {
          if (saveBtn) saveBtn.textContent = "Save Changes";
        }, 1500);
      } else {
        saveBtn.textContent = "Failed!";
        saveBtn.disabled = false;
        setTimeout(() => {
          if (saveBtn) saveBtn.textContent = "Save Changes";
        }, 2000);
      }
    } catch (_) {
      saveBtn.textContent = "Error";
      saveBtn.disabled = false;
    }
  });

  discardBtn.addEventListener("click", () => {
    if (_originalEvent) {
      // Re-render with original data
      _dirty = false;
      switch (eventType) {
        case "object": _showNpcEditor(_originalEvent); break;
        case "warp": _showWarpEditor(_originalEvent); break;
        case "coord": _showTriggerEditor(_originalEvent); break;
        case "bg": _showSignEditor(_originalEvent); break;
      }
    }
  });
}

// ---------------------------------------------------------------------------
// NPC Editor
// ---------------------------------------------------------------------------

function _showNpcEditor(npc) {
  if (!_container) return;
  _originalEvent = { ...npc };

  const idx = npc.object_id != null ? npc.object_id - 1 : npc._index || 0;

  let html = `<div class="ide-edit-header">NPC #${npc.object_id}
    <span class="ide-edit-coords">(${npc.x}, ${npc.y})</span></div>`;

  // Sprite preview (single frame) + graphics_id
  const gfxId = npc.graphics_id || "";
  const frameUrl = gfxId ? `/api/assets/overworld-frame/${encodeURIComponent(gfxId)}` : "";
  html += `<div class="ide-edit-sprite-row">`;
  if (frameUrl) {
    html += `<img class="ide-edit-sprite-preview" src="${esc(frameUrl)}" alt="">`;
  }
  html += `<input type="text" id="ed-gfx" class="ide-edit-input" value="${esc(gfxId)}" style="flex:1;min-width:0">`;
  html += `</div>`;

  html += _field("Movement", _buildSelect("ed-movement", MOVEMENT_TYPES, npc.movement_type));
  html += _field("Trainer", _buildSelect("ed-trainer", TRAINER_TYPES, npc.trainer_type || "TRAINER_TYPE_NONE"));
  html += _field("Sight", `<input type="number" id="ed-sight" class="ide-edit-input"
    value="${esc(String(npc.trainer_sight_or_berry_tree_id || "0"))}" min="0" max="15">`);

  // Trainer card button (for trainer NPCs)
  const isTrainer = npc.trainer_type && npc.trainer_type !== "TRAINER_TYPE_NONE";
  if (isTrainer && npc.script) {
    html += `<div class="ide-edit-trainer-link">
      <button class="ide-edit-trainer-btn" title="Open this trainer's card in the Trainers view">View Trainer Card</button>
    </div>`;
  }

  html += _field("Flag", `<input type="text" id="ed-flag" class="ide-edit-input" value="${esc(npc.flag || "0")}">`);

  // Script label + edit button
  html += _field("Script", `<div class="ide-edit-script-row">
    <code style="font-size:0.72rem;color:var(--text-secondary)">${esc(npc.script || "(none)")}</code>
    ${npc.script ? `<button class="ide-edit-script-btn" title="Edit Script">Edit</button>` : ""}
  </div>`);
  html += `<div class="ide-edit-script-status" style="display:none;padding:0.1rem 0;font-size:0.72rem;color:var(--text-dim)"></div>`;

  html += _field("Elevation", `<input type="number" id="ed-elev" class="ide-edit-input"
    value="${npc.elevation || 0}" min="0" max="15">`);

  // Movement range (side by side)
  html += `<div style="display:flex;gap:0.3rem">`;
  html += `<div style="flex:1">${_field("Range X", `<input type="number" id="ed-rx" class="ide-edit-input"
    value="${npc.movement_range_x || 0}" min="0" max="15">`)}</div>`;
  html += `<div style="flex:1">${_field("Range Y", `<input type="number" id="ed-ry" class="ide-edit-input"
    value="${npc.movement_range_y || 0}" min="0" max="15">`)}</div>`;
  html += `</div>`;

  html += _saveDiscardRow();

  _container.innerHTML = html;

  // Wire script edit button — one-click: auto-decompile if needed, then open editor
  const scriptBtn = _container.querySelector(".ide-edit-script-btn");
  if (scriptBtn && npc.script && _currentMap) {
    const npcId = npc.object_id || (idx + 1);
    const statusEl = _container.querySelector(".ide-edit-script-status");

    scriptBtn.addEventListener("click", async () => {
      // Strip script prefix: MapName_EventScript_Name → Name, MapName_Name → Name
      let scriptName = npc.script;
      const evPrefix = _currentMap + "_EventScript_";
      const mapPrefix = _currentMap + "_";
      if (scriptName.startsWith(evPrefix)) {
        scriptName = scriptName.slice(evPrefix.length);
      } else if (scriptName.startsWith(mapPrefix)) {
        scriptName = scriptName.slice(mapPrefix.length);
      }

      // Check if script needs decompilation first
      scriptBtn.disabled = true;
      const res = await api(`/npcs/${encodeURIComponent(_currentMap)}/${npcId}`);
      if (!res || !res.ok || !res.data) {
        scriptBtn.disabled = false;
        return;
      }
      const detail = res.data;

      if (detail.can_decompile) {
        // Auto-decompile, then open
        scriptBtn.textContent = "Converting\u2026";
        if (statusEl) { statusEl.style.display = ""; statusEl.textContent = "Decompiling vanilla script\u2026"; }
        const r = await postApi(`/npcs/${encodeURIComponent(_currentMap)}/${npcId}/decompile`, {});
        if (r && r.ok) {
          // Use the name returned by API (properly stripped)
          const sn = r.data?.script_name || scriptName;
          if (statusEl) { statusEl.style.display = "none"; }
          scriptBtn.textContent = "Edit";
          scriptBtn.disabled = false;
          ideEmit(IDE_OPEN_SCRIPT, { mapName: _currentMap, scriptName: sn });
        } else {
          scriptBtn.textContent = "Edit";
          scriptBtn.disabled = false;
          if (statusEl) { statusEl.style.display = ""; statusEl.textContent = r?.error || "Decompile failed"; statusEl.style.color = "var(--status-error)"; }
        }
      } else {
        // Already in workspace — open directly
        scriptBtn.textContent = "Edit";
        scriptBtn.disabled = false;
        ideEmit(IDE_OPEN_SCRIPT, { mapName: _currentMap, scriptName });
      }
    });
  }

  // Wire trainer card button
  const trainerBtn = _container.querySelector(".ide-edit-trainer-btn");
  if (trainerBtn && npc.script) {
    trainerBtn.addEventListener("click", async () => {
      // Extract trainer name from script label: MapName_EventScript_Name → TRAINER_NAME
      let tName = npc.script;
      const evPfx = _currentMap + "_EventScript_";
      const mapPfx = _currentMap + "_";
      if (tName.startsWith(evPfx)) tName = tName.slice(evPfx.length);
      else if (tName.startsWith(mapPfx)) tName = tName.slice(mapPfx.length);
      const trainerConst = "TRAINER_" + tName.toUpperCase();
      openToolModal("Trainer", () => import("../views/trainers.js"), { trainerConst });
    });
  }

  // Wire save/discard
  _wireSaveDiscard("object", idx, () => {
    const gfx = document.getElementById("ed-gfx")?.value;
    const movement = document.getElementById("ed-movement")?.value;
    const trainer = document.getElementById("ed-trainer")?.value;
    const sight = document.getElementById("ed-sight")?.value;
    const flag = document.getElementById("ed-flag")?.value;
    const elev = document.getElementById("ed-elev")?.value;
    const rx = document.getElementById("ed-rx")?.value;
    const ry = document.getElementById("ed-ry")?.value;

    const changes = {};
    if (gfx !== _originalEvent.graphics_id) changes.graphics_id = gfx;
    if (movement !== _originalEvent.movement_type) changes.movement_type = movement;
    if (trainer !== (_originalEvent.trainer_type || "TRAINER_TYPE_NONE")) changes.trainer_type = trainer;
    if (sight !== String(_originalEvent.trainer_sight_or_berry_tree_id || "0")) changes.trainer_sight_or_berry_tree_id = sight;
    if (flag !== (_originalEvent.flag || "0")) changes.flag = flag;
    if (Number(elev) !== (_originalEvent.elevation || 0)) changes.elevation = Number(elev);
    if (Number(rx) !== (_originalEvent.movement_range_x || 0)) changes.movement_range_x = Number(rx);
    if (Number(ry) !== (_originalEvent.movement_range_y || 0)) changes.movement_range_y = Number(ry);

    return changes;
  });
}

// ---------------------------------------------------------------------------
// Warp Editor
// ---------------------------------------------------------------------------

function _showWarpEditor(warp) {
  if (!_container) return;
  _originalEvent = { ...warp };

  const idx = warp.id != null ? warp.id : warp._index || 0;

  let html = `<div class="ide-edit-header">Warp #${warp.id}
    <span class="ide-edit-coords">(${warp.x}, ${warp.y})</span></div>`;

  html += _field("Dest Map", `<input type="text" id="ed-dest-map" class="ide-edit-input" value="${esc(warp.dest_map || "")}">`);
  html += _field("Dest Warp", `<input type="number" id="ed-dest-warp" class="ide-edit-input"
    value="${esc(String(warp.dest_warp_id || "0"))}" min="0" style="width:4em">`);
  html += _field("Elevation", `<input type="number" id="ed-elev" class="ide-edit-input"
    value="${warp.elevation || 0}" min="0" max="15" style="width:4em">`);

  // Navigate button
  if (warp.dest_map) {
    html += `<button class="ide-edit-nav-btn" style="margin-top:0.3rem">Go to ${esc(warp.dest_map)}</button>`;
  }

  html += _saveDiscardRow();

  _container.innerHTML = html;

  // Wire navigation
  const navBtn = _container.querySelector(".ide-edit-nav-btn");
  if (navBtn && warp.dest_map) {
    navBtn.addEventListener("click", () => {
      ideEmit(IDE_MAP_SELECTED, { name: warp.dest_map, source: "context" });
    });
  }

  _wireSaveDiscard("warp", idx, () => {
    const destMap = document.getElementById("ed-dest-map")?.value;
    const destWarp = document.getElementById("ed-dest-warp")?.value;
    const elev = document.getElementById("ed-elev")?.value;

    const changes = {};
    if (destMap !== (_originalEvent.dest_map || "")) changes.dest_map = destMap;
    if (destWarp !== String(_originalEvent.dest_warp_id || "0")) changes.dest_warp_id = destWarp;
    if (Number(elev) !== (_originalEvent.elevation || 0)) changes.elevation = Number(elev);

    return changes;
  });
}

// ---------------------------------------------------------------------------
// Trigger Editor
// ---------------------------------------------------------------------------

function _showTriggerEditor(trig) {
  if (!_container) return;
  _originalEvent = { ...trig };

  const idx = trig.id != null ? trig.id : trig._index || 0;

  let html = `<div class="ide-edit-header">Trigger #${trig.id}
    <span class="ide-edit-coords">(${trig.x}, ${trig.y})</span></div>`;

  html += _field("Script", `<input type="text" id="ed-script" class="ide-edit-input" value="${esc(trig.script || "")}">`);
  html += _field("Variable", `<input type="text" id="ed-var" class="ide-edit-input" value="${esc(trig.var || "0")}">`);
  html += _field("Value", `<input type="text" id="ed-val" class="ide-edit-input" value="${esc(trig.var_value || "0")}">`);
  html += _field("Elevation", `<input type="number" id="ed-elev" class="ide-edit-input"
    value="${trig.elevation || 0}" min="0" max="15" style="width:4em">`);

  html += _saveDiscardRow();

  _container.innerHTML = html;

  _wireSaveDiscard("coord", idx, () => {
    const script = document.getElementById("ed-script")?.value;
    const v = document.getElementById("ed-var")?.value;
    const val = document.getElementById("ed-val")?.value;
    const elev = document.getElementById("ed-elev")?.value;

    const changes = {};
    if (script !== (_originalEvent.script || "")) changes.script = script;
    if (v !== (_originalEvent.var || "0")) changes.var = v;
    if (val !== (_originalEvent.var_value || "0")) changes.var_value = val;
    if (Number(elev) !== (_originalEvent.elevation || 0)) changes.elevation = Number(elev);

    return changes;
  });
}

// ---------------------------------------------------------------------------
// Sign Editor
// ---------------------------------------------------------------------------

function _showSignEditor(sign) {
  if (!_container) return;
  _originalEvent = { ...sign };

  const idx = sign.id != null ? sign.id : sign._index || 0;

  let html = `<div class="ide-edit-header">Sign #${sign.id}
    <span class="ide-edit-coords">(${sign.x}, ${sign.y})</span></div>`;

  html += _field("Type", _buildSelect("ed-type", BG_EVENT_TYPES, sign.type || "sign"));
  html += _field("Facing", _buildSelect("ed-facing", SIGN_TYPES, sign.player_facing_dir || "BG_EVENT_PLAYER_FACING_ANY"));
  html += _field("Script", `<input type="text" id="ed-script" class="ide-edit-input" value="${esc(sign.script || "")}">`);

  // Placeholder for inline sign text (populated async)
  html += `<div id="ed-sign-text-area"></div>`;

  if (sign.item) {
    html += _field("Item", `<input type="text" id="ed-item" class="ide-edit-input" value="${esc(sign.item || "")}">`);
  }
  if (sign.flag && sign.flag !== "0") {
    html += _field("Flag", `<input type="text" id="ed-flag" class="ide-edit-input" value="${esc(sign.flag || "0")}">`);
  }

  html += _field("Elevation", `<input type="number" id="ed-elev" class="ide-edit-input"
    value="${sign.elevation || 0}" min="0" max="15" style="width:4em">`);

  html += _saveDiscardRow();

  _container.innerHTML = html;

  // Try to resolve sign text for basic signs
  if (sign.script && _currentMap) {
    _loadSignText(sign.script, _currentMap);
  }

  _wireSaveDiscard("bg", idx, () => {
    const type = document.getElementById("ed-type")?.value;
    const facing = document.getElementById("ed-facing")?.value;
    const script = document.getElementById("ed-script")?.value;
    const elev = document.getElementById("ed-elev")?.value;

    const changes = {};
    if (type !== (_originalEvent.type || "sign")) changes.type = type;
    if (facing !== (_originalEvent.player_facing_dir || "BG_EVENT_PLAYER_FACING_ANY")) changes.player_facing_dir = facing;
    if (script !== (_originalEvent.script || "")) changes.script = script;
    if (Number(elev) !== (_originalEvent.elevation || 0)) changes.elevation = Number(elev);

    // Optional fields
    const itemEl = document.getElementById("ed-item");
    if (itemEl && itemEl.value !== (_originalEvent.item || "")) changes.item = itemEl.value;
    const flagEl = document.getElementById("ed-flag");
    if (flagEl && flagEl.value !== (_originalEvent.flag || "0")) changes.flag = flagEl.value;

    return changes;
  });
}

const GBA_LINE_MAX = 18;

function _toNatural(coded) {
  if (!coded) return "";
  let t = coded.endsWith("$") ? coded.slice(0, -1) : coded;
  t = t.replace(/\\p/g, "\n\n");
  t = t.replace(/\\n/g, "\n");
  return t;
}

function _toCoded(natural) {
  if (!natural) return "";
  let t = natural.replace(/\n\s*\n/g, "\\p");
  t = t.replace(/\n/g, "\\n");
  return t;
}

function _renderSignPreview(previewEl, naturalText) {
  if (!previewEl) return;
  const coded = _toCoded(naturalText);
  const pages = coded.split("\\p");
  let html = "";
  for (let p = 0; p < pages.length; p++) {
    if (p > 0) html += '<div style="border-top:1px solid #333;margin:2px 0"></div>';
    for (const line of pages[p].split("\\n")) {
      const clean = line.replace(/\$$/g, "");
      const warn = clean.length > GBA_LINE_MAX ? "color:var(--status-error)" : "";
      html += `<div style="${warn}">${esc(clean) || "&nbsp;"}</div>`;
    }
  }
  previewEl.innerHTML = html;
}

async function _loadSignText(scriptLabel, mapName) {
  const area = document.getElementById("ed-sign-text-area");
  if (!area) return;

  const res = await api(`/map/${encodeURIComponent(mapName)}/sign-text/${encodeURIComponent(scriptLabel)}`);
  if (!res || !res.ok || !res.data || !res.data.simple) return;

  const text = res.data.text || "";
  const natural = _toNatural(text);

  area.innerHTML = `
    <div class="ide-edit-field-wrap">
      <label class="ide-edit-label">Sign Text</label>
      <textarea id="ed-sign-text" class="ide-edit-input" rows="3"
        style="font-family:monospace;font-size:0.72rem;resize:vertical">${esc(natural)}</textarea>
      <div id="ed-sign-preview" class="ide-sign-preview"></div>
      <button id="ed-sign-save-text" class="ide-edit-sign-save">Save Text</button>
    </div>
  `;

  const textarea = document.getElementById("ed-sign-text");
  const preview = document.getElementById("ed-sign-preview");
  const saveBtn = document.getElementById("ed-sign-save-text");

  _renderSignPreview(preview, natural);
  textarea.addEventListener("input", () => _renderSignPreview(preview, textarea.value));

  saveBtn.addEventListener("click", async () => {
    const coded = _toCoded(textarea.value);
    const finalText = coded.endsWith("$") ? coded : coded + "$";
    saveBtn.textContent = "Saving\u2026";
    saveBtn.disabled = true;
    const r = await postApi(`/map/${encodeURIComponent(mapName)}/sign-text/${encodeURIComponent(scriptLabel)}`, { text: finalText });
    if (r && r.ok) {
      saveBtn.textContent = "Saved";
      setTimeout(() => { saveBtn.textContent = "Save Text"; saveBtn.disabled = false; }, 1500);
    } else {
      saveBtn.textContent = "Error";
      saveBtn.disabled = false;
    }
  });
}

// ---------------------------------------------------------------------------
// Map Summary (no event selected)
// ---------------------------------------------------------------------------

function _showDefault() {
  if (!_container) return;
  _container.innerHTML = `
    <div style="padding:1rem;color:var(--text-dim);text-align:center;font-size:0.8rem">
      Select a map to see its properties
    </div>`;
}

function _showMapSummary() {
  if (!_mapDetail || !_container) return;

  const d = _mapDetail;
  const lay = d.layout || {};

  let html = "";

  html += `<div class="ide-prop-section">`;
  html += `<h4>Layout</h4>`;
  html += _propRow("Size", `${lay.width || "?"}x${lay.height || "?"} metatiles`);
  if (lay.primary_tileset) html += _propRow("Primary", _formatTilesetName(lay.primary_tileset));
  if (lay.secondary_tileset) html += _propRow("Secondary", _formatTilesetName(lay.secondary_tileset));
  html += `</div>`;

  html += `<div class="ide-prop-section">`;
  html += `<h4>Events</h4>`;
  html += `<div class="ide-event-counts">`;
  html += _eventBadge("npc", "NPCs", lay.npc_count || 0);
  html += _eventBadge("warp", "Warps", lay.warp_event_count || 0);
  html += _eventBadge("trigger", "Triggers", lay.trigger_count || 0);
  html += _eventBadge("sign", "Signs", lay.sign_count || 0);
  html += `</div></div>`;

  // Sub-tabs
  html += `<div class="ide-right-tabs">`;
  html += `<button class="ide-right-tab active" data-tab="info">Info</button>`;
  html += `<button class="ide-right-tab" data-tab="connections">Connections</button>`;
  html += `<button class="ide-right-tab" data-tab="scripts">Scripts</button>`;
  html += `</div>`;

  html += `<div class="ide-tab-content" data-tab-content="info">`;
  if (d.type) html += _propRow("Type", d.type);
  if (d.region) html += _propRow("Region", d.region);
  html += `</div>`;

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

  html += `<div class="ide-tab-content" data-tab-content="scripts" style="display:none">`;
  html += `<div id="ide-scripts-list" style="color:var(--text-dim);font-size:0.78rem">Loading...</div>`;
  html += `</div>`;

  _container.innerHTML = html;

  // Sub-tab switching
  _container.querySelectorAll(".ide-right-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      _container.querySelectorAll(".ide-right-tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      _container.querySelectorAll(".ide-tab-content").forEach(c => {
        c.style.display = c.dataset.tabContent === tab.dataset.tab ? "" : "none";
      });
    });
  });

  _container.querySelectorAll("[data-nav-map]").forEach(el => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      ideEmit(IDE_MAP_SELECTED, { name: el.dataset.navMap, source: "context" });
    });
  });

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

      el.querySelectorAll(".ide-script-link").forEach(link => {
        link.addEventListener("click", () => {
          ideEmit(IDE_OPEN_SCRIPT, { mapName: link.dataset.map, scriptName: link.dataset.script });
        });
      });
    } else {
      el.innerHTML = '<span style="color:var(--text-dim)">No scripts</span>';
    }
  } catch (_) {
    el.innerHTML = '<span style="color:var(--text-dim)">Failed to load</span>';
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _field(label, inputHTML) {
  return `<div class="ide-edit-field">
    <label class="ide-edit-label">${esc(label)}</label>
    ${inputHTML}
  </div>`;
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

function _formatTilesetName(name) {
  if (!name) return "?";
  if (name.startsWith("gTileset_")) return name.slice(9);
  return name;
}
