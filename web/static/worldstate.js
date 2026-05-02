/**
 * TORCH IDE — Worldstate Simulator Engine.
 * TORCH_MODULE
 *
 * Client-side engine that evaluates game conditions (flags, vars) against
 * NPC pages, visibility flags, and map scripts.  Entirely stateless on
 * the server — all evaluation happens in the browser.
 *
 * Usage:
 *   import { WorldState } from "./worldstate.js";
 *   const ws = new WorldState();
 *   ws.setFlag("FLAG_BEAT_GYM_1", true);
 *   ws.setVar("VAR_STORY", 5);
 *   const result = ws.resolveMap(mapWorldstateData);
 *   // result.npcs = [{ npc_id, visible, activePage, dialoguePreview }, ...]
 */

// ---------------------------------------------------------------------------
// WorldState class
// ---------------------------------------------------------------------------

export class WorldState {
  constructor() {
    this.flags = new Map();     // FLAG_NAME → boolean
    this.vars = new Map();      // VAR_NAME → integer
    this.globalConditions = []; // global conditions from project config
    this._listeners = new Set();
  }

  // --- State manipulation ---

  setFlag(name, value) {
    this.flags.set(name, !!value);
    this._notify();
  }

  getFlag(name) {
    return this.flags.get(name) ?? false;
  }

  setVar(name, value) {
    this.vars.set(name, parseInt(value, 10) || 0);
    this._notify();
  }

  getVar(name) {
    return this.vars.get(name) ?? 0;
  }

  toggleFlag(name) {
    this.setFlag(name, !this.getFlag(name));
  }

  /**
   * Apply global conditions to the internal state.
   * Called when global conditions are loaded or changed.
   * Sets special variables that the engine/game checks:
   *   PLAYER_GENDER → sets VAR_RESULT context for checkplayergender patterns
   */
  applyGlobalConditions(conditions) {
    this.globalConditions = conditions || [];
    for (const cond of this.globalConditions) {
      const val = cond.current || cond.default || "";
      if (cond.variable === "PLAYER_GENDER") {
        // In pokeemerald, MALE=0, FEMALE=1
        this._playerGender = val;
      } else if (cond.type === "choice") {
        // Generic choice: set the variable to the option's value
        const opt = (cond.options || []).find(o => o.label === val || o.value === val);
        if (opt && cond.variable) {
          this.vars.set(cond.variable, parseInt(opt.value, 10) || 0);
        }
      } else if (cond.type === "number" && cond.variable) {
        this.vars.set(cond.variable, parseInt(val, 10) || 0);
      }
    }
    this._notify();
  }

  /** Get the configured player gender ("MALE" or "FEMALE"). */
  getPlayerGender() {
    return this._playerGender || "MALE";
  }

  reset() {
    this.flags.clear();
    this.vars.clear();
    this._notify();
  }

  // --- Listeners ---

  onChange(fn) {
    this._listeners.add(fn);
    return () => this._listeners.delete(fn);
  }

  _notify() {
    for (const fn of this._listeners) {
      try { fn(this); } catch (_) {}
    }
  }

  // --- Condition evaluation ---

  /**
   * Evaluate a single condition object.
   * Condition shapes:
   *   { type: "flag", flag: "FLAG_X", negated: false }
   *   { type: "var", var: "VAR_X", op: ">=", value: 5 }
   *   { type: "defeated", trainer: "TRAINER_X" }
   *   { type: "compound", logic: "and"|"or", conditions: [...] }
   *
   * Returns boolean.
   */
  evaluateCondition(cond) {
    if (!cond) return true;

    switch (cond.type) {
      case "flag": {
        const val = this.getFlag(cond.flag);
        return cond.negated ? !val : val;
      }
      case "var": {
        const val = this.getVar(cond.var);
        const target = parseInt(cond.value, 10) || 0;
        let result;
        switch (cond.op) {
          case "==": result = val === target; break;
          case "!=": result = val !== target; break;
          case ">":  result = val > target; break;
          case "<":  result = val < target; break;
          case ">=": result = val >= target; break;
          case "<=": result = val <= target; break;
          default:   result = val !== 0; break; // truthiness
        }
        return cond.negated ? !result : result;
      }
      case "defeated": {
        // Defeated trainers are tracked via flags in pokeemerald
        // TRAINER_FLAGS_START + trainer_id, but we approximate with a flag check
        const flagName = `FLAG_DEFEATED_${cond.trainer || ""}`;
        return this.getFlag(flagName) || this.getFlag(cond.trainer || "");
      }
      case "compound": {
        const subs = cond.conditions || [];
        if (cond.logic === "or") {
          return subs.some(c => this.evaluateCondition(c));
        }
        return subs.every(c => this.evaluateCondition(c));
      }
      default:
        return true;
    }
  }

  /**
   * Evaluate a raw condition string (from TorScript page directives).
   * Also handles special global condition tokens:
   *   PLAYER_GENDER_MALE → true if player gender is MALE
   *   PLAYER_GENDER_FEMALE → true if player gender is FEMALE
   * Returns boolean.
   */
  evaluateRawCondition(raw) {
    if (!raw || !raw.trim()) return true;
    // Special global condition tokens
    if (raw === "PLAYER_GENDER_MALE") return this.getPlayerGender() === "MALE";
    if (raw === "PLAYER_GENDER_FEMALE") return this.getPlayerGender() === "FEMALE";
    const cond = parseRawCondition(raw);
    return this.evaluateCondition(cond);
  }

  // --- Page resolution ---

  /**
   * Resolve which page is active for an NPC.
   * pages: [{ page_num, condition (raw string) }, ...]
   * Returns the active page object (highest-numbered matching page).
   */
  resolveActivePage(pages) {
    if (!pages || pages.length === 0) return null;
    // Sort descending by page_num
    const sorted = [...pages].sort((a, b) => b.page_num - a.page_num);
    for (const page of sorted) {
      if (!page.condition || this.evaluateRawCondition(page.condition)) {
        return page;
      }
    }
    return sorted[sorted.length - 1]; // fallback to lowest page
  }

  // --- Map resolution ---

  /**
   * Resolve worldstate for an entire map.
   * mapData: { npcs, transition_rules }
   * Returns: { npcs: [{ npc_id, visible, activePage, changed, overrideX, overrideY }] }
   */
  resolveMap(mapData) {
    if (!mapData || !mapData.npcs) return { npcs: [] };

    // First, evaluate transition rules to build override maps
    const posOverrides = new Map();     // local_id -> {x, y}
    const visOverrides = new Map();     // local_id -> "remove"|"add"
    const moveOverrides = new Map();    // local_id -> movement_type
    const spriteOverrides = new Map();  // VAR_OBJ_GFX_ID_N -> OBJ_EVENT_GFX_*

    // Pre-populate sprite overrides from global conditions.
    // VAR_OBJ_GFX_ID_0 is the rival/opposite-gender sprite, set by the game at startup.
    if (this._playerGender === "FEMALE") {
      spriteOverrides.set("VAR_OBJ_GFX_ID_0", "OBJ_EVENT_GFX_BRENDAN_NORMAL");
    } else {
      spriteOverrides.set("VAR_OBJ_GFX_ID_0", "OBJ_EVENT_GFX_MAY_NORMAL");
    }

    for (const rule of (mapData.transition_rules || [])) {
      const condMet = !rule.condition || this.evaluateRawCondition(rule.condition);
      if (!condMet) continue;
      for (const action of (rule.actions || [])) {
        const lid = action.local_id;
        if (action.type === "setpos") {
          posOverrides.set(lid, { x: action.x, y: action.y });
        } else if (action.type === "remove") {
          visOverrides.set(lid, "remove");
        } else if (action.type === "add") {
          visOverrides.set(lid, "add");
        } else if (action.type === "setmovement") {
          moveOverrides.set(lid, action.movement);
        } else if (action.type === "setsprite") {
          spriteOverrides.set(action.var, action.gfx);
        }
      }
    }

    // Build LOCALID lookup: npc_id -> possible LOCALID_* strings
    // The API uses npc_id (1-based index), but transition rules use LOCALID_* constants
    // We need to match them. The map.json object_events have local_id fields.
    const localIdToNpcId = new Map();
    for (const npc of mapData.npcs) {
      // The graphics_id-based constant name is our best bet for matching
      // But we can also match by direct npc_id
      if (npc.local_id_const) {
        localIdToNpcId.set(npc.local_id_const, npc.npc_id);
      }
      // Fallback: LOCALID_ patterns use the npc_id directly in some maps
      localIdToNpcId.set(String(npc.npc_id), npc.npc_id);
    }

    const results = mapData.npcs.map(npc => {
      // Visibility: hidden if the visibility flag is set
      let visible = true;
      if (npc.visibility_flag) {
        visible = !this.getFlag(npc.visibility_flag);
      }

      // Check transition rule visibility overrides
      let overrideX = null;
      let overrideY = null;
      const lid = npc.local_id_const || String(npc.npc_id);

      // Try matching by LOCALID constant name or by npc_id
      for (const [ruleLid, vis] of visOverrides) {
        if (ruleLid === lid || localIdToNpcId.get(ruleLid) === npc.npc_id) {
          if (vis === "remove") visible = false;
          else if (vis === "add") visible = true;
        }
      }

      // Check position overrides
      for (const [ruleLid, pos] of posOverrides) {
        if (ruleLid === lid || localIdToNpcId.get(ruleLid) === npc.npc_id) {
          overrideX = pos.x;
          overrideY = pos.y;
        }
      }

      // Page resolution
      let activePage = null;
      let changed = false;
      if (npc.pages && npc.pages.length > 0) {
        activePage = this.resolveActivePage(npc.pages);
        if (activePage && activePage.page_num !== 1) {
          changed = true;
        }
        if (activePage && activePage.hide) {
          visible = false;
          changed = true;
        }
      }

      // Check sprite variable overrides
      let overrideGfx = null;
      const gfxId = npc.graphics_id || "";
      if (gfxId.startsWith("OBJ_EVENT_GFX_VAR_")) {
        // Map OBJ_EVENT_GFX_VAR_N -> VAR_OBJ_GFX_ID_N
        const varNum = gfxId.replace("OBJ_EVENT_GFX_VAR_", "");
        const varName = `VAR_OBJ_GFX_ID_${varNum}`;
        if (spriteOverrides.has(varName)) {
          overrideGfx = spriteOverrides.get(varName);
        }
      }

      // Mark as changed if position, visibility, or sprite was overridden
      if (overrideX !== null || overrideY !== null) changed = true;
      if (visOverrides.has(lid)) changed = true;
      if (overrideGfx) changed = true;

      return {
        npc_id: npc.npc_id,
        name: npc.name || `NPC ${npc.npc_id}`,
        visible,
        activePage: activePage ? activePage.page_num : null,
        pageCount: npc.pages ? npc.pages.length : 0,
        changed,
        dialoguePreview: activePage ? activePage.dialogue_preview || "" : "",
        overrideX,
        overrideY,
        overrideGfx,
      };
    });

    return { npcs: results };
  }

  // --- Presets ---

  toPreset() {
    const flags = {};
    for (const [k, v] of this.flags) {
      if (v) flags[k] = true;
    }
    const vars = {};
    for (const [k, v] of this.vars) {
      if (v !== 0) vars[k] = v;
    }
    return { flags, vars };
  }

  loadPreset(preset) {
    this.flags.clear();
    this.vars.clear();
    if (preset.flags) {
      for (const [k, v] of Object.entries(preset.flags)) {
        this.flags.set(k, !!v);
      }
    }
    if (preset.vars) {
      for (const [k, v] of Object.entries(preset.vars)) {
        this.vars.set(k, parseInt(v, 10) || 0);
      }
    }
    this._notify();
  }
}

// ---------------------------------------------------------------------------
// Condition string parser
// ---------------------------------------------------------------------------

const _OPS = new Set(["==", "!=", ">", "<", ">=", "<="]);

/**
 * Parse a raw TorScript condition string into a structured condition object.
 * "FLAG_X" → { type: "flag", flag: "FLAG_X" }
 * "FLAG_X and VAR_Y >= 5" → { type: "compound", logic: "and", conditions: [...] }
 */
export function parseRawCondition(raw) {
  const tokens = raw.trim().split(/\s+/);
  if (tokens.length === 0) return null;

  // Split on 'and' / 'or'
  for (let i = 1; i < tokens.length; i++) {
    if (tokens[i] === "and" || tokens[i] === "or") {
      const left = tokens.slice(0, i).join(" ");
      const right = tokens.slice(i + 1).join(" ");
      return {
        type: "compound",
        logic: tokens[i],
        conditions: [
          parseRawCondition(left),
          parseRawCondition(right),
        ],
      };
    }
  }

  return _parseSingle(tokens);
}

function _parseSingle(tokens) {
  let negated = false;
  let idx = 0;

  if (tokens[0] === "not") {
    negated = true;
    idx = 1;
  }

  if (idx >= tokens.length) return null;

  // defeated TRAINER_X
  if (tokens[idx] === "defeated" && idx + 1 < tokens.length) {
    return { type: "defeated", trainer: tokens[idx + 1], negated };
  }

  const name = tokens[idx];

  // VAR_X op value
  if (name.startsWith("VAR_") && idx + 2 < tokens.length && _OPS.has(tokens[idx + 1])) {
    return {
      type: "var", var: name,
      op: tokens[idx + 1],
      value: parseInt(tokens[idx + 2], 10) || 0,
      negated,
    };
  }

  // FLAG_X
  if (name.startsWith("FLAG_")) {
    return { type: "flag", flag: name, negated };
  }

  // Bare VAR_X (truthiness)
  if (name.startsWith("VAR_")) {
    return { type: "var", var: name, op: "!=", value: 0, negated };
  }

  // self.NAME — treated as flag
  if (name.startsWith("self.")) {
    return { type: "flag", flag: name, negated };
  }

  return null;
}

// ---------------------------------------------------------------------------
// Singleton instance
// ---------------------------------------------------------------------------

export const worldState = new WorldState();
