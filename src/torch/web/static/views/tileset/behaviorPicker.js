/**
 * behaviorPicker.js — Smart behavior picker for the Tileset Editor.
 *
 * Categorized dropdown with:
 * - Categories grouped by purpose (visible when no search query)
 * - Triple-index search (name tokens + synonyms + category labels)
 * - Plain English descriptions for common behaviors
 * - Recently-used chips (localStorage)
 * - Full keyboard navigation (ArrowDown/Up, Enter, Escape)
 * - Direct numeric value entry
 */

import { esc } from "../../utils.js";
import { state, addChange, emit, DIRTY_CHANGED } from "./state.js";
import { updateGridCell } from "./grid.js";

// ---------------------------------------------------------------------------
// Static data: descriptions
// ---------------------------------------------------------------------------

const DESCRIPTIONS = {
  0: "Default walkable floor",
  1: "Impassable wall / barrier",
  2: "Wild encounters (tall grass animation)",
  3: "Wild encounters (long grass)",
  6: "Deep sand — slows movement",
  7: "Short decorative grass",
  8: "Cave floor (encounter type: cave)",
  9: "Long grass southern edge",
  10: "Prevents running",
  11: "Indoor encounter trigger",
  12: "Mountain top surface",
  13: "Battle Pyramid warp tile",
  14: "Mossdeep Gym warp tile",
  15: "Mt. Pyre hole",
  16: "Surfable pond water",
  17: "Interior deep water (same as deep water)",
  18: "Deep ocean water — surfable",
  19: "Waterfall — requires HM",
  20: "Sootopolis deep water",
  21: "Open ocean water",
  22: "Puddle — splash effect",
  23: "Shallow water — surfable",
  25: "Water — no surfacing allowed",
  27: "Exterior staircase (Abandoned Ship)",
  28: "Shoal Cave entrance",
  29: "Signpost interaction",
  30: "Pokemon Center sign",
  31: "Pokemart sign",
  32: "Slippery ice surface",
  33: "Sand — shows footprints",
  34: "Seaweed in water",
  36: "Ash-covered grass",
  37: "Shows footprints",
  38: "Thin ice — cracks on second step",
  39: "Cracked ice — breaks after stepping",
  40: "Hot springs floor",
  41: "Lavaridge Gym B1F warp",
  42: "Seaweed — no surfacing",
  43: "Reflection under bridge tile",
  48: "Blocks movement from the east",
  49: "Blocks movement from the west",
  50: "Blocks movement from the north",
  51: "Blocks movement from the south",
  52: "Blocks movement from the northeast",
  53: "Blocks movement from the northwest",
  54: "Blocks movement from the southeast",
  55: "Blocks movement from the southwest",
  56: "Ledge jump — east",
  57: "Ledge jump — west",
  58: "Ledge jump — north",
  59: "Ledge jump — south",
  60: "Ledge jump — northeast",
  61: "Ledge jump — northwest",
  62: "Ledge jump — southeast",
  63: "Ledge jump — southwest",
  64: "Forced walk — east",
  65: "Forced walk — west",
  66: "Forced walk — north",
  67: "Forced walk — south",
  68: "Slide tile — east (ice puzzle)",
  69: "Slide tile — west (ice puzzle)",
  70: "Slide tile — north (ice puzzle)",
  71: "Slide tile — south (ice puzzle)",
  72: "Trick House rotating floor tile",
  73: "Sideways stairs — right side",
  74: "Sideways stairs — left side",
  75: "Sideways stairs — right side top",
  76: "Sideways stairs — left side top",
  77: "Sideways stairs — right side bottom",
  78: "Sideways stairs — left side bottom",
  79: "Rock stairs",
  80: "Water current — east",
  81: "Water current — west",
  82: "Water current — north",
  83: "Water current — south",
  96: "Non-animated door warp",
  97: "Ladder warp",
  98: "Arrow warp — east",
  99: "Arrow warp — west",
  100: "Arrow warp — north",
  101: "Arrow warp — south (door mat)",
  102: "Cracked floor hole",
  103: "Aqua Hideout warp",
  104: "Lavaridge Gym 1F warp",
  105: "Auto-opening animated door",
  106: "Escalator — up",
  107: "Escalator — down",
  108: "Water door warp",
  109: "Water south arrow warp",
  110: "Deep south warp trigger",
  112: "Bridge over ocean",
  115: "Fortree City bridge",
  120: "Bridge over pond (med edge)",
  122: "Bike bridge over barrier",
  128: "NPC talks across this tile (counter)",
  131: "PC interaction",
  133: "Region map display",
  134: "Television interaction",
  135: "Pokeblock feeder",
  137: "Slot machine interaction",
  138: "Roulette table interaction",
  139: "Closed Sootopolis door",
  140: "Trick House puzzle door",
  141: "Petalburg Gym door",
  142: "Running shoes instruction",
  143: "Questionnaire interaction",
  160: "Berry tree soil",
  176: "Secret base PC",
  192: "Impassable — blocks north and south",
  193: "Impassable — blocks west and east",
  208: "Muddy slope — requires Acro Bike",
  209: "Bumpy slope",
  210: "Cracked floor — collapses",
  211: "Isolated vertical rail",
  212: "Isolated horizontal rail",
  213: "Vertical rail",
  214: "Horizontal rail",
  224: "Picture book shelf",
  225: "Bookshelf interaction",
  226: "Pokemon Center bookshelf",
  227: "Vase interaction",
  228: "Trash can interaction",
  229: "Shop shelf interaction",
  230: "Blueprint display",
  234: "Sky Pillar closed door",
  235: "Stair warp — up-right",
  236: "Stair warp — up-left",
  237: "Stair warp — down-right",
  238: "Stair warp — down-left",
  239: "Rock Climb wall",
};

// ---------------------------------------------------------------------------
// Static data: categories (values are enum indices, 0-based)
// ---------------------------------------------------------------------------

const CATEGORIES = [
  {
    id: "common", label: "Common",
    members: [0, 1, 2, 128],
  },
  {
    id: "walkable", label: "Walkable Surfaces",
    members: [0, 2, 3, 6, 7, 8, 9, 10, 11, 12, 32, 33, 36, 37, 38, 39, 40, 160],
  },
  {
    id: "impassable", label: "Walls & Barriers",
    members: [1, 48, 49, 50, 51, 52, 53, 54, 55, 192, 193],
  },
  {
    id: "doors", label: "Doors & Warps",
    members: [96, 97, 98, 99, 100, 101, 105, 106, 107, 108, 109, 110, 235, 236, 237, 238],
  },
  {
    id: "water", label: "Water",
    members: [16, 17, 18, 19, 20, 21, 22, 23, 25, 34, 42, 80, 81, 82, 83],
  },
  {
    id: "ledges", label: "Ledges & Jumps",
    members: [56, 57, 58, 59, 60, 61, 62, 63],
  },
  {
    id: "movement", label: "Movement Effects",
    members: [64, 65, 66, 67, 68, 69, 70, 71, 72, 208, 209, 210],
  },
  {
    id: "stairs", label: "Stairs & Rails",
    members: [27, 73, 74, 75, 76, 77, 78, 79, 211, 212, 213, 214],
  },
  {
    id: "interactive", label: "Interactive Objects",
    members: [128, 131, 133, 134, 135, 137, 138, 142, 143, 224, 225, 226, 227, 228, 229, 230],
  },
  {
    id: "bridges", label: "Bridges",
    members: [112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125],
  },
  {
    id: "signs", label: "Signs",
    members: [29, 30, 31],
  },
  {
    id: "gym", label: "Gym & Special",
    members: [13, 14, 15, 28, 41, 102, 103, 104, 139, 140, 141, 234, 239],
  },
  {
    id: "secretbase", label: "Secret Base", collapsed: true,
    members: [1, 144, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 155, 156, 157,
              176, 177, 178, 179, 180, 181, 183, 184, 185, 186, 187, 188, 189, 190, 191,
              194, 195, 196, 197, 198, 199],
  },
];

// ---------------------------------------------------------------------------
// Static data: synonym search map
// ---------------------------------------------------------------------------

const SYNONYMS = {
  "floor":     [0, 210],
  "ground":    [0, 6, 33],
  "wall":      [1, 48, 49, 50, 51, 52, 53, 54, 55, 192, 193],
  "block":     [1, 48, 49, 50, 51, 52, 53, 54, 55],
  "barrier":   [1, 48, 49, 50, 51],
  "door":      [96, 105, 108, 139, 140, 141, 234],
  "entrance":  [96, 105, 97, 28],
  "exit":      [101, 98, 99, 100, 110],
  "warp":      [96, 97, 98, 99, 100, 101, 105, 106, 107, 108, 109, 110, 235, 236, 237, 238],
  "grass":     [2, 3, 7, 9, 36],
  "encounter": [2, 3, 7, 11],
  "wild":      [2, 3, 7, 11],
  "surf":      [16, 17, 18, 21, 23],
  "swim":      [16, 17, 18, 21, 23],
  "water":     [16, 17, 18, 19, 20, 21, 22, 23, 25, 34, 42, 80, 81, 82, 83],
  "jump":      [56, 57, 58, 59, 60, 61, 62, 63],
  "ledge":     [56, 57, 58, 59, 60, 61, 62, 63],
  "slide":     [68, 69, 70, 71],
  "ice":       [32, 38, 39, 68, 69, 70, 71],
  "stair":     [27, 73, 74, 75, 76, 77, 78, 79, 235, 236, 237, 238],
  "ladder":    [97],
  "bridge":    [112, 113, 114, 115, 116, 117, 118, 119, 120, 122],
  "counter":   [128],
  "shop":      [229],
  "pc":        [131, 176],
  "computer":  [131, 176],
  "tv":        [134],
  "book":      [224, 225, 226],
  "shelf":     [224, 225, 226, 229],
  "sign":      [29, 30, 31],
  "read":      [224, 225, 226, 29],
  "current":   [80, 81, 82, 83],
  "waterfall": [19],
  "crack":     [39, 210],
  "sand":      [6, 33],
  "mud":       [208],
  "slope":     [208, 209],
  "bike":      [122, 208, 209],
  "escalator": [106, 107],
  "rail":      [211, 212, 213, 214],
  "rock":      [79, 239],
  "climb":     [239],
  "berry":     [160],
  "run":       [10, 142],
  "trash":     [228],
  "vase":      [227],
  "slot":      [137],
  "roulette":  [138],
  "footprint": [37],
  "hot":       [40],
  "spring":    [40],
  "ash":       [36],
  "cave":      [8, 28],
  "puddle":    [22],
  "ocean":     [21],
  "seaweed":   [34, 42],
  "mountain":  [12],
  "impassable":[1, 48, 49, 50, 51, 52, 53, 54, 55, 192, 193],
};

// ---------------------------------------------------------------------------
// Search index (built once from behaviors list)
// ---------------------------------------------------------------------------

let _index = null;

function _buildIndex(behaviors) {
  // Build category lookup: value -> category
  const catMap = new Map();
  for (const cat of CATEGORIES) {
    for (const v of cat.members) {
      if (!catMap.has(v)) catMap.set(v, cat);
    }
  }

  // Build synonym lookup: value -> [synonym words]
  const synMap = new Map();
  for (const [word, vals] of Object.entries(SYNONYMS)) {
    for (const v of vals) {
      if (!synMap.has(v)) synMap.set(v, []);
      synMap.get(v).push(word);
    }
  }

  _index = behaviors.map(b => {
    const isUnused = b.name.includes("UNUSED");
    const tokens = b.name.replace(/^MB_/, "").toLowerCase().split("_");
    const cat = catMap.get(b.value) || null;
    const synonymHits = synMap.get(b.value) || [];
    const catWords = cat ? cat.label.toLowerCase().split(/[\s&]+/).filter(Boolean) : [];
    const desc = DESCRIPTIONS[b.value] || "";

    return {
      value: b.value,
      name: b.name,
      tokens,
      desc,
      category: cat,
      isUnused,
      searchable: [...tokens, ...synonymHits, ...catWords],
    };
  });

  return _index;
}

function _getIndex() {
  if (!_index) _index = _buildIndex(state.behaviors);
  return _index;
}

// ---------------------------------------------------------------------------
// Search algorithm
// ---------------------------------------------------------------------------

function _search(query) {
  const index = _getIndex();
  const q = query.toLowerCase().replace(/^mb_/, "").trim();

  if (!q) return null; // null = show categorized view

  // Pure number? Match by value
  if (/^\d+$/.test(q)) {
    const num = parseInt(q, 10);
    return index
      .filter(b => String(b.value).startsWith(q) || b.value === num)
      .sort((a, b) => (a.value === num ? -1 : 1) - (b.value === num ? -1 : 1))
      .slice(0, 30);
  }

  const words = q.split(/[\s_]+/).filter(Boolean);

  // Score each behavior
  const scored = [];
  for (const b of index) {
    if (b.isUnused) continue; // hide unused during search
    let score = 0;

    for (const w of words) {
      // Exact token match (strongest)
      if (b.tokens.some(t => t === w)) { score += 100; continue; }
      // Token prefix match
      if (b.tokens.some(t => t.startsWith(w))) { score += 50; continue; }
      // Synonym match
      const synHits = SYNONYMS[w];
      if (synHits && synHits.includes(b.value)) { score += 40; continue; }
      // Category word match
      if (b.category && b.category.label.toLowerCase().includes(w)) { score += 10; continue; }
      // Token contains match (weakest)
      if (b.tokens.some(t => t.includes(w))) { score += 5; continue; }
    }

    if (score > 0) scored.push({ ...b, score });
  }

  scored.sort((a, b) => b.score - a.score || a.value - b.value);
  return scored.slice(0, 30);
}

// ---------------------------------------------------------------------------
// Recently used (localStorage)
// ---------------------------------------------------------------------------

const RECENT_KEY = "torch_recent_behaviors";
const MAX_RECENT = 8;

function _getRecent() {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY)) || []; }
  catch { return []; }
}

function _addRecent(value) {
  let recent = _getRecent().filter(v => v !== value);
  recent.unshift(value);
  if (recent.length > MAX_RECENT) recent.length = MAX_RECENT;
  localStorage.setItem(RECENT_KEY, JSON.stringify(recent));
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

/**
 * Render the behavior picker HTML (to be inserted into the detail panel).
 * Returns HTML string.
 */
export function renderBehaviorPickerHTML(currentValue) {
  const beh = state.behaviors.find(b => b.value === currentValue);
  const displayName = beh ? `${beh.name} (${beh.value})` : `Unknown (${currentValue})`;
  const desc = DESCRIPTIONS[currentValue] || "";

  let html = `<div class="ts-section">`;
  html += `<div class="ts-section-label">Behavior</div>`;
  html += `<div class="bp-wrap">`;
  html += `<input type="text" class="bp-input" id="bp-input" autocomplete="off" spellcheck="false" `;
  html += `placeholder="Search by name, purpose, or value..." value="${esc(displayName)}">`;
  html += `<div class="bp-desc" id="bp-desc">${esc(desc)}</div>`;
  html += `<div class="bp-dropdown" id="bp-dropdown"></div>`;
  html += `</div></div>`;

  return html;
}

/**
 * Bind events on the behavior picker after it's in the DOM.
 * Must be called after renderBehaviorPickerHTML's output is inserted.
 */
export function bindBehaviorPicker(onSelect) {
  const input = document.getElementById("bp-input");
  const dropdown = document.getElementById("bp-dropdown");
  const descEl = document.getElementById("bp-desc");
  if (!input || !dropdown) return;

  let highlightIdx = -1;
  let currentResults = [];
  let showingCategories = false;

  function _updateDesc(value) {
    if (!descEl) return;
    const d = DESCRIPTIONS[value];
    descEl.textContent = d || "";
    descEl.classList.toggle("previewing", highlightIdx >= 0);
  }

  function _renderCategorized() {
    showingCategories = true;
    currentResults = [];
    highlightIdx = -1;
    const index = _getIndex();

    let html = "";

    // Recently used chips
    const recent = _getRecent();
    const recentBehaviors = recent
      .map(v => state.behaviors.find(b => b.value === v))
      .filter(Boolean);

    if (recentBehaviors.length > 0) {
      html += `<div class="bp-recent">`;
      html += `<span class="bp-recent-label">Recent</span>`;
      for (const b of recentBehaviors) {
        const short = b.name.replace(/^MB_/, "").replace(/_/g, " ");
        html += `<button class="bp-chip" data-value="${b.value}" title="${esc(b.name)}">${esc(short)}</button>`;
      }
      html += `<span class="bp-recent-clear" title="Clear recent">×</span>`;
      html += `</div>`;
    }

    // Categories
    for (const cat of CATEGORIES) {
      if (cat.collapsed) continue; // skip Secret Base etc. in categorized view
      const catBehaviors = cat.members
        .map(v => index.find(b => b.value === v))
        .filter(b => b && !b.isUnused);
      if (catBehaviors.length === 0) continue;

      html += `<div class="bp-group-label">${esc(cat.label)}</div>`;
      for (const b of catBehaviors) {
        html += `<div class="bp-option" data-value="${b.value}">`;
        html += `<span class="bp-name">${esc(b.name)}</span>`;
        html += `<span class="bp-val">${b.value}</span>`;
        html += `</div>`;
        currentResults.push(b);
      }
    }

    // "Show unused" toggle
    html += `<div class="bp-toggle-unused"><button class="bp-show-unused">Show collapsed categories & unused</button></div>`;

    dropdown.innerHTML = html;
    dropdown.classList.add("open");

    _bindDropdownClicks(onSelect, input, dropdown);
  }

  function _renderFiltered(results) {
    showingCategories = false;
    currentResults = results;
    highlightIdx = results.length > 0 ? 0 : -1;

    if (results.length === 0) {
      dropdown.innerHTML = `<div class="bp-option bp-no-match">No matches</div>`;
      dropdown.classList.add("open");
      return;
    }

    let html = "";
    for (let i = 0; i < results.length; i++) {
      const b = results[i];
      const cls = i === 0 ? " highlighted" : "";
      html += `<div class="bp-option${cls}" data-value="${b.value}" data-idx="${i}">`;
      html += `<span class="bp-name">${esc(b.name)}</span>`;
      html += `<span class="bp-val">${b.value}</span>`;
      html += `</div>`;
    }

    dropdown.innerHTML = html;
    dropdown.classList.add("open");

    if (highlightIdx >= 0) _updateDesc(results[0].value);
    _bindDropdownClicks(onSelect, input, dropdown);
  }

  function _bindDropdownClicks(onSelect, input, dropdown) {
    // Option clicks
    dropdown.querySelectorAll(".bp-option[data-value]").forEach(opt => {
      opt.addEventListener("mousedown", (e) => {
        e.preventDefault();
        const val = parseInt(opt.dataset.value, 10);
        _selectBehavior(val, onSelect, input, dropdown);
      });
    });

    // Chip clicks
    dropdown.querySelectorAll(".bp-chip[data-value]").forEach(chip => {
      chip.addEventListener("mousedown", (e) => {
        e.preventDefault();
        const val = parseInt(chip.dataset.value, 10);
        _selectBehavior(val, onSelect, input, dropdown);
      });
    });

    // Clear recent
    const clearBtn = dropdown.querySelector(".bp-recent-clear");
    if (clearBtn) {
      clearBtn.addEventListener("mousedown", (e) => {
        e.preventDefault();
        localStorage.removeItem(RECENT_KEY);
        _renderCategorized(); // re-render without recent
      });
    }

    // Show unused
    const unusedBtn = dropdown.querySelector(".bp-show-unused");
    if (unusedBtn) {
      unusedBtn.addEventListener("mousedown", (e) => {
        e.preventDefault();
        _renderAllBehaviors();
      });
    }
  }

  function _renderAllBehaviors() {
    const index = _getIndex();
    currentResults = index.filter(b => !b.isUnused);
    highlightIdx = -1;
    showingCategories = false;

    let html = "";
    for (const cat of CATEGORIES) {
      const catBehaviors = cat.members
        .map(v => index.find(b => b.value === v))
        .filter(b => b && !b.isUnused);
      if (catBehaviors.length === 0) continue;
      html += `<div class="bp-group-label">${esc(cat.label)}</div>`;
      for (const b of catBehaviors) {
        html += `<div class="bp-option" data-value="${b.value}">`;
        html += `<span class="bp-name">${esc(b.name)}</span>`;
        html += `<span class="bp-val">${b.value}</span>`;
        html += `</div>`;
      }
    }

    // Unused
    const unused = index.filter(b => b.isUnused);
    if (unused.length > 0) {
      html += `<div class="bp-group-label">Unused (${unused.length})</div>`;
      for (const b of unused) {
        html += `<div class="bp-option" data-value="${b.value}">`;
        html += `<span class="bp-name">${esc(b.name)}</span>`;
        html += `<span class="bp-val">${b.value}</span>`;
        html += `</div>`;
      }
    }

    dropdown.innerHTML = html;
    dropdown.classList.add("open");
    _bindDropdownClicks(onSelect, input, dropdown);
  }

  function _selectBehavior(value, onSelect, input, dropdown) {
    const b = state.behaviors.find(x => x.value === value);
    input.value = b ? `${b.name} (${b.value})` : `(${value})`;
    dropdown.classList.remove("open");
    _addRecent(value);
    _updateDesc(value);

    // Brief highlight pulse
    input.classList.add("just-selected");
    setTimeout(() => input.classList.remove("just-selected"), 300);

    if (onSelect) onSelect(value);
  }

  function _updateHighlight() {
    dropdown.querySelectorAll(".bp-option").forEach((opt, i) => {
      opt.classList.toggle("highlighted", i === highlightIdx);
    });
    // Scroll into view
    const highlighted = dropdown.querySelector(".bp-option.highlighted");
    if (highlighted) highlighted.scrollIntoView({ block: "nearest" });
    // Update description
    if (highlightIdx >= 0 && highlightIdx < currentResults.length) {
      _updateDesc(currentResults[highlightIdx].value);
    }
  }

  // --- Events ---

  input.addEventListener("focus", () => {
    input.select();
    // Invalidate index if behaviors changed
    _index = null;
    const results = _search(input.value);
    if (results === null) {
      _renderCategorized();
    } else {
      _renderFiltered(results);
    }
  });

  input.addEventListener("input", () => {
    const results = _search(input.value);
    if (results === null) {
      _renderCategorized();
    } else {
      _renderFiltered(results);
    }
  });

  input.addEventListener("blur", () => {
    setTimeout(() => dropdown.classList.remove("open"), 150);
  });

  input.addEventListener("keydown", (e) => {
    if (!dropdown.classList.contains("open")) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (showingCategories) return; // no keyboard nav in categorized view
      if (currentResults.length === 0) return;
      highlightIdx = (highlightIdx + 1) % currentResults.length;
      _updateHighlight();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (showingCategories) return;
      if (currentResults.length === 0) return;
      highlightIdx = (highlightIdx - 1 + currentResults.length) % currentResults.length;
      _updateHighlight();
    } else if (e.key === "Enter") {
      e.preventDefault();
      // Direct numeric value entry
      const trimmed = input.value.trim();
      if (/^\d+$/.test(trimmed)) {
        const val = parseInt(trimmed, 10);
        _selectBehavior(val, onSelect, input, dropdown);
        return;
      }
      // Select highlighted
      if (!showingCategories && highlightIdx >= 0 && highlightIdx < currentResults.length) {
        _selectBehavior(currentResults[highlightIdx].value, onSelect, input, dropdown);
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      dropdown.classList.remove("open");
      input.blur();
    }
  });
}

// ---------------------------------------------------------------------------
// CSS for the behavior picker
// ---------------------------------------------------------------------------

export const BEHAVIOR_PICKER_CSS = `
/* Behavior picker wrapper */
.bp-wrap { position: relative; }

.bp-input {
  width: 100%;
  box-sizing: border-box;
  padding: 0.4rem 0.5rem;
  background: var(--surface-0, #11111b);
  color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border-subtle, #45475a);
  border-radius: 4px;
  font-size: 0.82rem;
  font-family: monospace;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.bp-input:focus {
  outline: none;
  border-color: var(--accent, #f8d030);
}
.bp-input.just-selected {
  border-color: var(--accent, #f8d030);
  box-shadow: 0 0 0 2px rgba(248, 208, 48, 0.25);
}

/* Description line */
.bp-desc {
  font-size: 0.75rem;
  color: var(--text-muted, #6c7086);
  margin-top: 0.25rem;
  min-height: 1.1em;
  transition: color 0.15s;
}
.bp-desc.previewing { color: var(--text-secondary, #bac2de); }

/* Dropdown panel */
.bp-dropdown {
  display: none;
  position: absolute;
  top: calc(100% - 1px);
  left: 0;
  right: 0;
  z-index: 30;
  max-height: 300px;
  overflow-y: auto;
  background: var(--surface-1, #1e1e2e);
  border: 1px solid var(--border-subtle, #45475a);
  border-top: none;
  border-radius: 0 0 6px 6px;
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.5);
}
.bp-dropdown.open { display: block; }

/* Recent chips */
.bp-recent {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.4rem 0.5rem;
  border-bottom: 1px solid var(--border-subtle, #45475a);
  flex-wrap: wrap;
}
.bp-recent-label {
  font-size: 0.65rem;
  color: var(--text-dim, #585b70);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-right: 0.2rem;
}
.bp-chip {
  padding: 0.15rem 0.5rem;
  font-size: 0.68rem;
  font-family: monospace;
  background: var(--surface-2, #313244);
  color: var(--text-secondary, #bac2de);
  border: 1px solid var(--border-subtle, #45475a);
  border-radius: 3px;
  cursor: pointer;
  transition: background 0.1s, border-color 0.1s;
  text-transform: lowercase;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.bp-chip:hover {
  background: rgba(248, 208, 48, 0.08);
  border-color: var(--accent, #f8d030);
  color: var(--text-primary, #cdd6f4);
}
.bp-recent-clear {
  margin-left: auto;
  font-size: 0.75rem;
  color: var(--text-dim, #585b70);
  cursor: pointer;
  padding: 0.1rem 0.3rem;
}
.bp-recent-clear:hover { color: var(--status-error, #f38ba8); }

/* Category headers */
.bp-group-label {
  padding: 0.3rem 0.5rem 0.15rem;
  font-size: 0.65rem;
  font-weight: 600;
  color: var(--text-dim, #585b70);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: var(--surface-0, #11111b);
  position: sticky;
  top: 0;
  z-index: 1;
}

/* Individual option */
.bp-option {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.3rem 0.5rem;
  cursor: pointer;
  transition: background 0.08s;
}
.bp-option:hover,
.bp-option.highlighted {
  background: var(--surface-2, #313244);
}
.bp-option.highlighted {
  background: rgba(248, 208, 48, 0.08);
  border-left: 2px solid var(--accent, #f8d030);
  padding-left: calc(0.5rem - 2px);
}
.bp-option.bp-no-match {
  color: var(--text-dim, #585b70);
  cursor: default;
  font-style: italic;
}
.bp-name {
  font-size: 0.78rem;
  font-family: monospace;
  color: var(--text-primary, #cdd6f4);
}
.bp-val {
  font-size: 0.7rem;
  font-family: monospace;
  color: var(--text-dim, #585b70);
  min-width: 2em;
  text-align: right;
}

/* Toggle unused */
.bp-toggle-unused {
  padding: 0.4rem 0.5rem;
  text-align: center;
  border-top: 1px solid var(--border-subtle, #45475a);
}
.bp-show-unused {
  font-size: 0.7rem;
  color: var(--text-dim, #585b70);
  background: none;
  border: none;
  cursor: pointer;
  padding: 0.2rem;
}
.bp-show-unused:hover { color: var(--text-secondary, #bac2de); }
`;

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------

export function cleanupBehaviorPicker() {
  _index = null;
}
