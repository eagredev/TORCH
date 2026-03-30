/**
 * state.js — Central state module for the Script Editor (visualizer).
 * Architectural keystone: every other viz module imports from here.
 * No viz module imports from any other viz module — only from state.
 */

import { api, postApi } from "../../app.js";

// ---------------------------------------------------------------------------
// Event bus (lightweight, built on browser EventTarget)
// ---------------------------------------------------------------------------

const _bus = new EventTarget();

export function emit(name, detail) {
  _bus.dispatchEvent(new CustomEvent(name, { detail }));
}

export function on(name, fn) {
  const handler = e => fn(e.detail);
  _bus.addEventListener(name, handler);
  return handler;
}

export function off(name, handler) {
  _bus.removeEventListener(name, handler);
}

// ---------------------------------------------------------------------------
// Event name constants
// ---------------------------------------------------------------------------

export const BEAT_CHANGED = "beat-changed";
export const FRAMES_UPDATED = "frames-updated";
export const DIRTY_CHANGED = "dirty-changed";
export const EDITOR_OPENED = "editor-opened";
export const EDITOR_CLOSED = "editor-closed";
export const SOURCE_CHANGED = "source-changed";
export const CHAIN_CHANGED = "chain-changed";

// ---------------------------------------------------------------------------
// Beat tags (shared constant for beat list, transport, etc.)
// ---------------------------------------------------------------------------

export const BEAT_TAGS = {
  label: "LBL", dialogue: "DLG", move: "MOV", emote: "EMO",
  fade: "FAD", sound: "SND", pause: "PAU", flag: "FLG",
  battle: "BTL", hide: "HID", show: "SHW", setpos: "POS",
  flow: "FLW", pory: "POR", comment: "REM", lock: "LCK",
  faceplayer: "FPL", special: "SPC", waitstate: "WAI",
  gotoif: "GIF", var: "VAR", shake: "SHK", closemessage: "CLM",
  music: "MUS", fanfare: "FAN", cry: "CRY", text: "TXT",
  movement: "BLK", raw: "RAW", follower: "FOL", multi: "MLT",
  give: "GIV",
};

// ---------------------------------------------------------------------------
// State singleton
// ---------------------------------------------------------------------------

export const state = {
  mapName: "",
  scriptName: "",
  source: "",
  frames: [],
  cast: {},
  spriteIndex: {},
  currentBeat: 0,
  dirty: false,
  editingBeat: -1,
  playing: false,
  cameraLocked: true,
  spriteImages: {},
  triggerInfo: null,
  playerDistance: 0,
  npcPatrolIndex: 0,
  patrolMode: false,
  _ownTriggerInfo: null,        // this script's own trigger_info (before chain override)
  // Chain state
  chainName: "",                // active chain name, or "" for standalone
  chainData: null,              // full chain JSON
  chainSegment: null,           // this script's segment data
  chainStartPositions: null,    // merged initial positions from chain
  availableChains: [],          // chains containing this script
  clipboard: null,              // {type, text} for beat copy/paste
};

// ---------------------------------------------------------------------------
// State mutation functions
// ---------------------------------------------------------------------------

export const BEAT_BOUNDARY = "beat-boundary"; // { direction: "next"|"prev" }

export function goToBeat(index) {
  if (state.frames.length > 0) {
    if (index > state.frames.length - 1) {
      emit(BEAT_BOUNDARY, { direction: "next" });
      return;
    }
    if (index < 0) {
      emit(BEAT_BOUNDARY, { direction: "prev" });
      return;
    }
  }
  const clamped = Math.max(0, Math.min(index, state.frames.length - 1));
  state.currentBeat = clamped;
  emit(BEAT_CHANGED, clamped);
}

export function setDirty(isDirty) {
  state.dirty = isDirty;
  emit(DIRTY_CHANGED, isDirty);
}

export function setPlaying(isPlaying) {
  state.playing = isPlaying;
}

export function openEditor(beatIndex) {
  state.editingBeat = beatIndex;
  emit(EDITOR_OPENED, beatIndex);
}

export function closeEditor() {
  state.editingBeat = -1;
  emit(EDITOR_CLOSED);
}

export function setCameraLocked(locked) {
  state.cameraLocked = locked;
}

export const TRIGGER_DISTANCE_CHANGED = "trigger-distance-changed";
export const PATROL_MODE_CHANGED = "patrol-mode-changed";

export async function setPlayerDistance(distance) {
  if (!state.triggerInfo) return;
  state.playerDistance = Math.max(
    state.triggerInfo.min_distance,
    Math.min(distance, state.triggerInfo.max_distance)
  );
  emit(TRIGGER_DISTANCE_CHANGED, state.playerDistance);

  // In chain mode, resimulate through the entire chain at this distance
  // so upstream scripts propagate the correct positions downstream.
  if (state.chainName) {
    await resimulateChainAtDistance(state.playerDistance);
  } else {
    await resimulate(state.source);
  }
}

export function togglePatrolMode() {
  state.patrolMode = !state.patrolMode;
  emit(PATROL_MODE_CHANGED, state.patrolMode);
}

export function setNpcPatrolIndex(index) {
  if (!state.triggerInfo) return;
  const positions = state.triggerInfo.npc_positions || [];
  if (index < 0 || index >= positions.length) return;
  state.npcPatrolIndex = index;

  const pos = positions[index];
  if (!pos) return;

  // Update trigger info for player distance calculations
  state.triggerInfo.npc_x = pos.x;
  state.triggerInfo.npc_y = pos.y;
  state.triggerInfo.facing = pos.facing;
  const dir_offsets = { left: [-1, 0], right: [1, 0], up: [0, -1], down: [0, 1] };
  const [dx, dy] = dir_offsets[pos.facing] || [0, 1];
  state.triggerInfo.dx = dx;
  state.triggerInfo.dy = dy;

  // Update positions directly in all frames (no server round-trip)
  const alias = state.triggerInfo.alias || "";
  const dist = state.playerDistance || state.triggerInfo.default_distance || 1;
  const opposite = { left: "right", right: "left", up: "down", down: "up" };

  for (const frame of state.frames) {
    if (!frame.actors) continue;
    // Move NPC to patrol position
    if (alias && frame.actors[alias]) {
      frame.actors[alias].x = pos.x;
      frame.actors[alias].y = pos.y;
      frame.actors[alias].facing = pos.facing;
    }
    // Move player based on sight distance from new NPC position
    if (frame.actors.player) {
      frame.actors.player.x = pos.x + dx * dist;
      frame.actors.player.y = pos.y + dy * dist;
      frame.actors.player.facing = opposite[pos.facing] || "up";
    }
  }

  emit(PATROL_MODE_CHANGED, state.patrolMode);  // triggers canvas re-render
  emit(BEAT_CHANGED, state.currentBeat);         // triggers overlay re-render
}

// ---------------------------------------------------------------------------
// Beat clipboard (copy/paste)
// ---------------------------------------------------------------------------

/**
 * Copy the current beat's source text to the clipboard.
 */
export function copyBeat(beatIndex) {
  const frame = state.frames[beatIndex];
  if (!frame || !frame.beat) return false;
  const beat = frame.beat;
  if (beat.source_line == null) return false;

  const lines = state.source.split("\n");
  const sl = beat.source_line;
  const el = beat.source_end_line != null ? beat.source_end_line : sl;
  const text = lines.slice(sl, el + 1).join("\n");
  state.clipboard = { type: beat.type, text };
  return true;
}

/**
 * Paste the clipboard contents after the current beat.
 * Caller must call pushHistory() before invoking this.
 * Returns true if paste succeeded.
 */
export async function pasteBeat() {
  if (!state.clipboard) return false;

  const frame = state.frames[state.currentBeat];
  if (!frame || !frame.beat) return false;
  const beat = frame.beat;
  if (beat.source_line == null) return false;

  const lines = state.source.split("\n");
  const insertAfter = beat.source_end_line != null ? beat.source_end_line : beat.source_line;
  lines.splice(insertAfter + 1, 0, state.clipboard.text);
  const newSource = lines.join("\n");

  const result = await resimulate(newSource);
  if (result.ok) {
    setDirty(true);
    goToBeat(state.currentBeat + 1);
  }
  return result.ok;
}

// ---------------------------------------------------------------------------
// Sprite preloading (consolidates 6 duplicated blocks from old code)
// ---------------------------------------------------------------------------

async function preloadSprites() {
  const toLoad = Object.keys(state.spriteIndex).filter(gfx => !state.spriteImages[gfx]);
  const promises = toLoad.map(gfx => new Promise(resolve => {
    const img = new Image();
    img.onload = () => { state.spriteImages[gfx] = img; resolve(); };
    img.onerror = () => { resolve(); };
    img.src = `/api/overworld-sprites/${gfx}`;
  }));
  await Promise.all(promises);
}

// ---------------------------------------------------------------------------
// Core: resimulate — the SINGLE function that calls the simulate API
// ---------------------------------------------------------------------------

export async function resimulate(newSource) {
  state.source = newSource;
  emit(SOURCE_CHANGED, newSource);
  try {
    const body = { source: newSource };
    if (state.triggerInfo && state.playerDistance != null) {
      body.player_distance = state.playerDistance;
    }
    if (state.npcPatrolIndex > 0) {
      body.npc_patrol_index = state.npcPatrolIndex;
    }
    // Chain support: pass initial_positions when chain is active
    if (state.chainStartPositions) {
      body.initial_positions = state.chainStartPositions;
    }
    const res = await postApi(`/scenes/${state.mapName}/${state.scriptName}/simulate`, body);
    if (res.ok) {
      state.frames = res.data.frames || [];
      state.cast = res.data.cast || {};
      state.spriteIndex = res.data.sprite_index || {};
      await preloadSprites();
      if (state.currentBeat >= state.frames.length) {
        state.currentBeat = Math.max(0, state.frames.length - 1);
      }
      emit(FRAMES_UPDATED, { frames: state.frames, cast: state.cast });
      return { ok: true };
    } else {
      return { ok: false, error: res.error || "Simulation failed" };
    }
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

// ---------------------------------------------------------------------------
// Chain-aware resimulation at a specific trigger distance
// ---------------------------------------------------------------------------

async function resimulateChainAtDistance(distance) {
  try {
    const res = await postApi(`/chains/${state.chainName}/simulate-at`, {
      script_name: state.scriptName,
      player_distance: distance,
    });
    if (res.ok) {
      state.frames = res.data.frames || [];
      state.cast = res.data.cast || {};
      state.spriteIndex = res.data.sprite_index || {};
      await preloadSprites();
      if (state.currentBeat >= state.frames.length) {
        state.currentBeat = Math.max(0, state.frames.length - 1);
      }
      emit(FRAMES_UPDATED, { frames: state.frames, cast: state.cast });
      return { ok: true };
    } else {
      return { ok: false, error: res.error || "Chain simulation failed" };
    }
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

// ---------------------------------------------------------------------------
// Scene loading
// ---------------------------------------------------------------------------

export async function loadScene(mapName, scriptName) {
  state.mapName = mapName;
  state.scriptName = scriptName;
  state.currentBeat = 0;
  state.editingBeat = -1;
  state.dirty = false;
  state.playing = false;
  state.clipboard = null;

  const res = await api(`/scenes/${mapName}/${scriptName}`);
  if (!res.ok) return { ok: false, error: res.error };

  state.source = res.data.source || "";
  state.frames = res.data.frames || [];
  state.cast = res.data.cast || {};
  state.spriteIndex = res.data.sprite_index || {};
  state.triggerInfo = res.data.trigger_info || null;
  state._ownTriggerInfo = state.triggerInfo;  // save before chain may override
  state.playerDistance = state.triggerInfo ? state.triggerInfo.default_distance : 0;
  state.npcPatrolIndex = 0;
  state.patrolMode = false;
  await preloadSprites();

  // Discover chains containing this script
  await loadChainContext(mapName, scriptName);

  emit(FRAMES_UPDATED, { frames: state.frames, cast: state.cast });
  emit(BEAT_CHANGED, 0);
  emit(DIRTY_CHANGED, false);
  return { ok: true };
}

// ---------------------------------------------------------------------------
// Chain context — discover, activate, deactivate
// ---------------------------------------------------------------------------

/**
 * Load chain context for the current script. Auto-called by loadScene.
 * Discovers available chains and auto-activates if exactly one exists.
 */
export async function loadChainContext(mapName, scriptName) {
  // Reset chain state
  state.chainName = "";
  state.chainData = null;
  state.chainSegment = null;
  state.chainStartPositions = null;
  state.availableChains = [];

  try {
    const res = await api(`/chains/by-script/${mapName}/${scriptName}`);
    if (!res.ok || !res.data) return;
    state.availableChains = res.data.chains || [];
  } catch (_) {
    return;
  }

  // Auto-activate if exactly one chain (head scripts always implicitly ON)
  if (state.availableChains.length === 1) {
    await activateChain(state.availableChains[0].name);
  }
}

/**
 * Activate a specific chain for the current script.
 * Loads the full chain data, computes starting positions, and resimulates.
 */
export async function activateChain(chainName) {
  try {
    const res = await api(`/chains/${chainName}`);
    if (!res.ok || !res.data) return;

    state.chainName = chainName;
    state.chainData = res.data;

    // Find this script's segment
    const seg = (res.data.segments || {})[state.scriptName] || null;
    state.chainSegment = seg;

    // Adopt the chain's head-script trigger_info so the distance slider
    // appears for every script in the chain, not just the head.
    if (res.data.trigger_info) {
      state.triggerInfo = res.data.trigger_info;
      // Always adopt the chain's default distance — it may differ from
      // the standalone default (e.g. chain restricts approach tiles)
      state.playerDistance = state.triggerInfo.default_distance;
    }

    // Compute starting positions from chain
    state.chainStartPositions = _computeChainStartPositions(res.data, state.scriptName);

    emit(CHAIN_CHANGED, { chainName, active: true });
    // Resimulate with chain positions
    await resimulate(state.source);
  } catch (_) {
    // If chain loading fails, fall back to standalone
    deactivateChain();
  }
}

/**
 * Deactivate chain mode — return to standalone map.json positions.
 */
export function deactivateChain() {
  state.chainName = "";
  state.chainData = null;
  state.chainSegment = null;
  state.chainStartPositions = null;
  // Restore the script's own trigger_info (may be null for non-trainer scripts)
  state.triggerInfo = state._ownTriggerInfo;
  state.playerDistance = state.triggerInfo ? state.triggerInfo.default_distance : 0;
  emit(CHAIN_CHANGED, { chainName: "", active: false });
  // Resimulate without chain positions (will use map.json defaults)
  resimulate(state.source);
}

/**
 * Compute starting positions for a script within a chain.
 * For the head script: use anchor positions.
 * For subsequent scripts: use the previous segment's output.
 * Merge manual overrides on top.
 */
function _computeChainStartPositions(chainData, scriptName) {
  const seg = (chainData.segments || {})[scriptName];
  if (!seg) return null;

  const position = seg.position || 0;
  let positions = {};

  if (position === 0) {
    // Head script — use anchor
    const anchor = chainData.anchor || {};
    const anchorActors = anchor.actors || {};
    for (const [name, data] of Object.entries(anchorActors)) {
      positions[name] = { ...data };
    }
    if (anchor.player) {
      positions.player = { ...anchor.player };
    }
  } else {
    // Non-head — use previous segment's output
    const seq = chainData.sequence || [];
    if (position > 0 && position <= seq.length) {
      const prevScript = seq[position - 1].script;
      const prevSeg = (chainData.segments || {})[prevScript];
      if (prevSeg && prevSeg.output) {
        const actors = prevSeg.output.actors || {};
        for (const [name, data] of Object.entries(actors)) {
          // Position ranges: use midpoint for display
          const pos = {};
          for (const [key, val] of Object.entries(data)) {
            if (Array.isArray(val) && val.length === 2 && typeof val[0] === "number") {
              pos[key] = Math.round((val[0] + val[1]) / 2);
            } else {
              pos[key] = val;
            }
          }
          positions[name] = pos;
        }
      }
    }
  }

  // Merge introduces from this segment
  const introduces = seg.introduces || {};
  for (const [name, data] of Object.entries(introduces)) {
    positions[name] = { ...data };
  }

  // Merge manual overrides on top
  const overrides = (chainData.manual_overrides || {})[scriptName];
  if (overrides && overrides.actors) {
    for (const [actor, fields] of Object.entries(overrides.actors)) {
      if (!positions[actor]) positions[actor] = {};
      for (const [key, val] of Object.entries(fields)) {
        if (key === "note" || key === "stale_warning") continue;
        if (Array.isArray(val) && val.length === 2 && typeof val[0] === "number") {
          positions[actor][key] = Math.round((val[0] + val[1]) / 2);
        } else {
          positions[actor][key] = val;
        }
      }
    }
  }

  return Object.keys(positions).length > 0 ? positions : null;
}

// ---------------------------------------------------------------------------
// Map/script listing
// ---------------------------------------------------------------------------

export async function listMaps() {
  const res = await api("/studio/maps");
  if (!res.ok) return [];
  return (res.data.maps || []).filter(m => m.enrolled || m.is_custom);
}

export async function listScripts(mapName) {
  const res = await api(`/scenes/${mapName}`);
  if (!res.ok) return [];
  return res.data.scripts || [];
}

// ---------------------------------------------------------------------------
// Save / build
// ---------------------------------------------------------------------------

export async function saveScript() {
  if (!state.mapName || !state.scriptName) return { ok: false, error: "No script loaded" };
  const res = await postApi(`/scenes/${state.mapName}/${state.scriptName}/save`, { source: state.source });
  if (res.ok) {
    setDirty(false);
    // Post-save validation: check for warnings/errors in the saved source
    try {
      const valRes = await postApi(
        `/scenes/${state.mapName}/${state.scriptName}/validate`,
        { source: state.source }
      );
      if (valRes.ok && valRes.data && !valRes.data.valid) {
        res.validation = valRes.data;
      } else if (valRes.ok && valRes.data && valRes.data.warnings && valRes.data.warnings.length > 0) {
        res.validation = valRes.data;
      }
    } catch (_) {
      // Validation is best-effort — don't fail the save
    }
  }
  return res;
}

export async function saveAndBuild() {
  const saveRes = await saveScript();
  if (!saveRes.ok) return saveRes;
  const syncRes = await postApi("/sync", { map_name: state.mapName });
  if (!syncRes.ok) return { ok: false, error: syncRes.error || "Sync failed", step: "sync" };
  const buildRes = await postApi("/build", {});
  if (!buildRes.ok) return { ok: false, error: buildRes.error || "Build failed", step: "build" };
  // Pass through validation from saveScript if present
  return { ok: true, validation: saveRes.validation };
}

// ---------------------------------------------------------------------------
// beatSummary — shared helper (ported from old visualizer.js)
// ---------------------------------------------------------------------------

export function beatSummary(beat) {
  if (!beat) return "";
  const t = beat.type;
  const d = beat.data || {};

  switch (t) {
    case "label":
      return d.name || d.label || "";
    case "dialogue":
    case "text": {
      let txt = d.text || d.content || "";
      if (d.label) txt = `${d.label}: ${txt}`;
      if (txt.length > 40) txt = txt.slice(0, 40) + "...";
      return `"${txt}"`;
    }
    case "move": {
      const actions = d.actions || [];
      if (actions.length > 0) {
        const summaries = actions.map(a => {
          const parts = [a.actor, a.verb, a.direction, a.count].filter(Boolean);
          return parts.join(" ");
        });
        const s = summaries.join(" + ");
        return s.length > 50 ? s.slice(0, 50) + "..." : s;
      }
      const parts = [d.actor, d.verb, d.direction, d.count].filter(Boolean);
      return parts.join(" ");
    }
    case "emote":
      return `${d.actor || ""} ${d.emote_name || d.emote || ""}`.trim();
    case "fade":
      return d.fade_type || d.direction || "";
    case "flag":
      return `${d.action || "set"} ${d.flag_name || d.flag || ""}`.trim();
    case "var":
      return `${d.action || "set"} ${d.var_name || d.variable || ""} ${d.value ?? ""}`.trim();
    case "sound":
    case "music":
    case "fanfare":
    case "cry":
      return d.constant || d.name || d.sound || "";
    case "setpos":
      return `${d.actor || ""} ${d.x ?? ""},${d.y ?? ""}`.trim();
    case "battle": {
      const bt = d.battle_type || "";
      const args = d.args || "";
      const first_arg = args.split(",")[0]?.trim() || "";
      const summary = bt + (first_arg ? ` ${first_arg}` : "");
      return summary.length > 40 ? summary.slice(0, 40) + "..." : summary;
    }
    case "hide":
    case "show":
      return d.actor || d.name || "";
    case "flow":
    case "gotoif":
      return d.label || d.condition || d.target || "";
    case "lock":
    case "faceplayer":
    case "closemessage":
    case "pause":
    case "waitstate":
      return d.duration || "";
    case "special":
      return d.function_name || d.name || d.special || "";
    case "shake":
      return `${d.intensity || ""} ${d.count || ""}`.trim();
    case "pory":
    case "raw":
      return (d.content || d.text || "").slice(0, 40);
    case "comment":
      return (d.text || d.content || "").slice(0, 40);
    case "movement":
      return `${d.actor || ""} movement block`;
    case "follower":
      return d.action || "";
    case "multi":
      return d.format || "";
    case "give":
      return `${d.item || ""} ${d.quantity || ""}`.trim();
    default:
      return JSON.stringify(d).slice(0, 40);
  }
}

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------

export function cleanup() {
  Object.assign(state, {
    mapName: "", scriptName: "", source: "", frames: [], cast: {},
    spriteIndex: {}, currentBeat: 0, dirty: false, editingBeat: -1,
    playing: false, cameraLocked: true, spriteImages: {},
    triggerInfo: null, playerDistance: 0, _ownTriggerInfo: null,
    chainName: "", chainData: null, chainSegment: null,
    chainStartPositions: null, availableChains: [],
    clipboard: null,
  });
}
