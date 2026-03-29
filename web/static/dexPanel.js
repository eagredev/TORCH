/**
 * TORCH Web GUI -- Dex Reference Panel.
 * Persistent, compact Pokemon browser in the status bar area.
 * Slides up like the build drawer, usable from any page.
 */

import { api } from "./app.js";
import { esc } from "./utils.js";
import { processSprite } from "./spriteUtils.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TYPE_COLOURS = {
  Normal: "#A8A878", Fire: "#F08030", Water: "#6890F0", Electric: "#F8D030",
  Grass: "#78C850", Ice: "#98D8D8", Fighting: "#C03028", Poison: "#A040A0",
  Ground: "#E0C068", Flying: "#A890F0", Psychic: "#F85888", Bug: "#A8B820",
  Rock: "#B8A038", Ghost: "#705898", Dragon: "#7038F8", Dark: "#705848",
  Steel: "#B8B8D0", Fairy: "#EE99AC",
};

const ALL_TYPES = Object.keys(TYPE_COLOURS);
const GEN_RANGES = {
  1: [1, 151], 2: [152, 251], 3: [252, 386], 4: [387, 493],
  5: [494, 649], 6: [650, 721], 7: [722, 809], 8: [810, 905],
  9: [906, 1025],
};
const STAT_LABELS = ["HP", "Atk", "Def", "SpA", "SpD", "Spe"];
const STAT_KEYS = ["hp", "atk", "def", "spa", "spd", "spe"];
const PAGE_SIZE = 60;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let cachedList = null;    // full species list from API
let scrollFn = null;      // current scroll handler (for cleanup)
let filtered = [];        // current filtered/sorted set
let rendered = 0;         // cards in DOM
let observer = null;      // IntersectionObserver for sprites
let activeTypeFilters = []; // max 2 types (AND logic)
let activeGens = [];        // multiple gens (OR logic)
let activeSortMode = "dex"; // dex | name-az | name-za | bst-desc | bst-asc
let searchQuery = "";
let debounceTimer = null;
let detailCache = {};     // species_const -> detail data
let closeBuildDrawerFn = null;
let isOpen = false;

// Sprite loading queue (independent of dex.js)
let spriteQueue = [];
let spriteActive = 0;
const SPRITE_CONCURRENCY = 3;

function queueSprite(img) {
  spriteQueue.push(img);
  drainSpriteQueue();
}

function drainSpriteQueue() {
  while (spriteActive < SPRITE_CONCURRENCY && spriteQueue.length) {
    const img = spriteQueue.shift();
    const url = img.dataset.sprite;
    if (!url) continue;
    spriteActive++;
    processSprite(url).then(dataUrl => {
      img.src = dataUrl;
      img.style.display = "";
    }).catch(() => {
      img.style.display = "none";
    }).finally(() => {
      spriteActive--;
      drainSpriteQueue();
    });
  }
}

// ---------------------------------------------------------------------------
// Panel toggle
// ---------------------------------------------------------------------------

function getPanel() { return document.getElementById("dex-panel"); }
function getToggle() { return document.querySelector(".status-dex-toggle"); }

function openPanel() {
  const panel = getPanel();
  const toggle = getToggle();
  if (!panel) return;
  if (closeBuildDrawerFn) closeBuildDrawerFn();
  panel.classList.add("open");
  if (toggle) toggle.classList.add("active");
  isOpen = true;
  // Lazy-load data on first open
  if (!cachedList) loadSpecies();
}

function closePanel() {
  const panel = getPanel();
  const toggle = getToggle();
  if (panel) {
    panel.classList.remove("open");
    panel.classList.remove("expanded");
    const expandBtn = panel.querySelector(".dex-panel-expand");
    if (expandBtn) expandBtn.innerHTML = "&#9650;";
  }
  if (toggle) toggle.classList.remove("active");
  isOpen = false;
}

function togglePanel() {
  if (isOpen) closePanel();
  else openPanel();
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadSpecies() {
  const panel = getPanel();
  if (!panel) return;

  const body = panel.querySelector(".dex-panel-body");
  if (!body) return;

  body.innerHTML = `<div class="dex-panel-loading">Loading...</div>`;

  const res = await api("/species");
  if (!res.ok) {
    body.innerHTML = `<div class="dex-panel-loading">Error loading species</div>`;
    return;
  }
  cachedList = res.data || [];
  applyFilters();
}

function applyTypeAndGenFilters(list) {
  let result = list;
  // Type filters (AND logic — must have ALL selected types)
  if (activeTypeFilters.length) {
    result = result.filter(sp => {
      const spTypes = (sp.types || []).map(t => t.toLowerCase());
      return activeTypeFilters.every(f => spTypes.includes(f.toLowerCase()));
    });
  }
  // Generation filter (OR — match any selected gen)
  if (activeGens.length) {
    result = result.filter(sp => {
      const dex = sp.nat_dex_num || 0;
      return activeGens.some(g => {
        const [lo, hi] = GEN_RANGES[g] || [0, 0];
        return dex >= lo && dex <= hi;
      });
    });
  }
  // Sort
  if (activeSortMode === "name-az") {
    result = [...result].sort((a, b) => a.name.localeCompare(b.name));
  } else if (activeSortMode === "name-za") {
    result = [...result].sort((a, b) => b.name.localeCompare(a.name));
  } else if (activeSortMode === "bst-desc") {
    result = [...result].sort((a, b) => (b.bst || 0) - (a.bst || 0));
  } else if (activeSortMode === "bst-asc") {
    result = [...result].sort((a, b) => (a.bst || 0) - (b.bst || 0));
  }
  // Default "dex" uses native API order
  return result;
}

function applyFilters() {
  if (!cachedList) return;

  // Advanced search → server-side
  if (searchQuery && (searchQuery.includes(":") || /bst[<>=]/.test(searchQuery))) {
    serverSearch(searchQuery);
    return;
  }

  let result = cachedList;

  // Simple name search
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    result = result.filter(sp => sp.name.toLowerCase().includes(q));
  }

  filtered = applyTypeAndGenFilters(result);
  renderGrid();
}

async function serverSearch(query) {
  const res = await api(`/species?q=${encodeURIComponent(query)}`);
  if (!res.ok) return;
  filtered = applyTypeAndGenFilters(res.data || []);
  renderGrid();
}

// ---------------------------------------------------------------------------
// Card grid
// ---------------------------------------------------------------------------

function isExpanded() {
  const panel = getPanel();
  return panel && panel.classList.contains("expanded");
}

function renderGrid() {
  const panel = getPanel();
  if (!panel) return;
  const body = panel.querySelector(".dex-panel-body");
  const resultsEl = panel.querySelector(".dex-panel-results");
  if (!body) return;

  // Clean up previous observer and scroll handler
  if (observer) { observer.disconnect(); observer = null; }
  if (scrollFn && body) { body.removeEventListener("scroll", scrollFn); scrollFn = null; }
  spriteQueue = [];

  rendered = 0;
  const containerClass = isExpanded() ? "dex-panel-list" : "dex-panel-grid";
  body.innerHTML = `<div class="${containerClass}"></div>`;
  const container = body.firstElementChild;

  if (!filtered.length) {
    container.innerHTML = `<div class="dex-panel-empty">No results</div>`;
    if (resultsEl) resultsEl.textContent = "0";
    return;
  }

  if (resultsEl) resultsEl.textContent = String(filtered.length);
  const appendFn = isExpanded() ? appendListRows : appendCards;
  rendered = appendFn(container, 0, PAGE_SIZE);
  setupObserver(body);
  setupScroll(body, appendFn);

  // Fill visible area
  requestAnimationFrame(() => fillViewport(body, appendFn));
}

function fillViewport(scrollContainer, appendFn) {
  if (rendered >= filtered.length) return;
  if (scrollContainer.scrollHeight <= scrollContainer.clientHeight + 50) {
    const container = scrollContainer.firstElementChild;
    if (container) {
      rendered = appendFn(container, rendered, PAGE_SIZE);
      observeNewSprites(scrollContainer);
      if (rendered < filtered.length) {
        requestAnimationFrame(() => fillViewport(scrollContainer, appendFn));
      }
    }
  }
}

function observeNewSprites(scrollContainer) {
  if (!observer) return;
  scrollContainer.querySelectorAll(".dex-panel-sprite[data-sprite]").forEach(img => {
    if (!img.src || img.style.display === "none") observer.observe(img);
  });
}

/** Compact card grid (default / collapsed mode) */
function appendCards(container, start, count) {
  const end = Math.min(start + count, filtered.length);
  const frag = document.createDocumentFragment();
  for (let i = start; i < end; i++) {
    const sp = filtered[i];
    const card = document.createElement("div");
    card.className = "dex-panel-card";
    card.dataset.const = sp.const;
    const primaryType = (sp.types || [])[0] || "Normal";
    const col = TYPE_COLOURS[primaryType] || "#888";
    card.style.borderTopColor = col;
    card.style.setProperty("--dp-glow", col + "30");

    card.innerHTML = `<img class="dex-panel-sprite" data-sprite="/api/sprites/${sp.sprite_path}"
      width="48" height="48" style="image-rendering:pixelated;display:none"
      onerror="this.style.display='none'">
      <span class="dex-panel-card-name">${esc(sp.name)}</span>`;

    card.addEventListener("click", () => showDetail(sp.const));
    frag.appendChild(card);
  }
  container.appendChild(frag);
  return end;
}

/** Estimate level range from inline evo_from + evo_to_level data. */
function inlineLevelRange(sp) {
  const evo = sp.evo_from;
  const evoToLv = sp.evo_to_level;  // level this species evolves at (null if none)

  if (!evo) {
    // Base form — show range if it has a level-based evo
    if (evoToLv) return `Lv.1\u2013${evoToLv - 1}`;
    return ""; // no evo data at all
  }

  // Evolved via level (param must be non-zero for a real level evo)
  if (evo.method === "LEVEL" && evo.param && evo.param !== "0") {
    const minLv = parseInt(evo.param, 10);
    if (evoToLv) return `Lv.${minLv}\u2013${evoToLv - 1}`;
    return `Lv.${minLv}+`;
  }

  // Non-level evolution methods
  if (evo.method === "ITEM") return formatItemName(evo.param) || "Item";
  if (evo.method === "TRADE") {
    const item = formatItemName(evo.param);
    return item ? `Trade (${item})` : "Trade";
  }
  if (evo.method === "FRIENDSHIP") return "Friendship";
  // LEVEL with param=0 is friendship/condition-based (Pichu, Eevee, etc.)
  if (evo.method === "LEVEL" && (!evo.param || evo.param === "0")) return "Friendship";
  return evoLabel(evo.method, evo.param);
}

/** Full list rows (expanded mode) — dex#, sprite, name, BST, level range, type badges */
function appendListRows(container, start, count) {
  const end = Math.min(start + count, filtered.length);
  const frag = document.createDocumentFragment();
  for (let i = start; i < end; i++) {
    const sp = filtered[i];
    const row = document.createElement("div");
    row.className = "dex-panel-row";
    row.dataset.const = sp.const;
    const primaryType = (sp.types || [])[0] || "Normal";
    const col = TYPE_COLOURS[primaryType] || "#888";
    row.style.borderLeftColor = col;

    const dexNum = sp.nat_dex_num ? `#${String(sp.nat_dex_num).padStart(3, "0")}` : "";
    const types = (sp.types || []).map(t => {
      const c = TYPE_COLOURS[t] || "#888";
      return `<span class="dex-panel-type-badge" style="background:${c}">${t}</span>`;
    }).join("");

    const bst = sp.bst || 0;
    const lvRange = inlineLevelRange(sp);
    const lvHtml = lvRange ? `<span class="dex-panel-row-lv">${lvRange}</span>` : "";

    row.innerHTML = `<span class="dex-panel-row-num">${dexNum}</span>
      <img class="dex-panel-sprite dex-panel-row-sprite" data-sprite="/api/sprites/${sp.sprite_path}"
        width="32" height="32" style="image-rendering:pixelated;display:none"
        onerror="this.style.display='none'">
      <span class="dex-panel-row-name">${esc(sp.name)}</span>
      ${lvHtml}
      <span class="dex-panel-row-bst">${bst}</span>
      <span class="dex-panel-row-types">${types}</span>`;

    row.addEventListener("click", () => showDetail(sp.const));
    frag.appendChild(row);
  }
  container.appendChild(frag);
  return end;
}

function setupObserver(scrollContainer) {
  observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        const img = entry.target;
        observer.unobserve(img);
        queueSprite(img);
      }
    }
  }, { root: scrollContainer, rootMargin: "200px" });

  scrollContainer.querySelectorAll(".dex-panel-sprite[data-sprite]").forEach(img => {
    observer.observe(img);
  });
}

function setupScroll(scrollContainer, appendFn) {
  scrollFn = () => {
    if (rendered >= filtered.length) return;
    const threshold = scrollContainer.scrollHeight - scrollContainer.clientHeight - 200;
    if (scrollContainer.scrollTop >= threshold) {
      const container = scrollContainer.firstElementChild;
      if (container) {
        rendered = appendFn(container, rendered, PAGE_SIZE);
        observeNewSprites(scrollContainer);
      }
    }
  };
  scrollContainer.addEventListener("scroll", scrollFn);
}

// ---------------------------------------------------------------------------
// Detail popover
// ---------------------------------------------------------------------------

async function showDetail(speciesConst) {
  const panel = getPanel();
  if (!panel) return;
  const body = panel.querySelector(".dex-panel-body");
  if (!body) return;

  body.innerHTML = `<div class="dex-panel-loading">Loading...</div>`;

  let data = detailCache[speciesConst];
  if (!data) {
    const res = await api(`/species/${speciesConst}`);
    if (!res.ok) {
      body.innerHTML = `<div class="dex-panel-detail">
        <a href="#" class="dex-panel-back">Back</a>
        <p>Error loading species</p>
      </div>`;
      wireBackButton(body);
      return;
    }
    data = res.data;
    detailCache[speciesConst] = data;
  }

  const types = (data.types || []).map(t => {
    const c = TYPE_COLOURS[t] || "#888";
    return `<span class="dex-panel-type-badge" style="background:${c}">${t}</span>`;
  }).join("");

  const dexNum = data.nat_dex_num ? `#${String(data.nat_dex_num).padStart(3, "0")}` : "";

  // Stats
  const statRows = STAT_KEYS.map((key, i) => {
    const val = data[key] || 0;
    const pct = Math.min(100, (val / 255) * 100);
    const col = statColour(val);
    return `<div class="dex-panel-stat-row">
      <span class="dex-panel-stat-label">${STAT_LABELS[i]}</span>
      <span class="dex-panel-stat-num">${val}</span>
      <div class="dex-panel-stat-bar"><div class="dex-panel-stat-fill" style="width:${pct}%;background:${col}"></div></div>
    </div>`;
  }).join("");

  const bst = data.bst || STAT_KEYS.reduce((s, k) => s + (data[k] || 0), 0);

  // Abilities
  const abilities = (data.abilities_described || []).map(a =>
    `<span class="dex-panel-ability" title="${esc(a.description || "")}">${esc(a.name)}</span>`
  ).join(" ");

  // Evolution chain + level range
  const evoHtml = renderEvoChain(data.evolution_chain || [], speciesConst);

  // Level range for this species
  const levelRange = estimateLevelRange(data.evolution_chain || [], speciesConst);
  const levelHtml = levelRange
    ? `<div class="dex-panel-level-range">${levelRange}</div>`
    : "";

  body.innerHTML = `<div class="dex-panel-detail">
    <a href="#" class="dex-panel-back">&larr; Back</a>
    <div class="dex-panel-detail-header">
      <img class="dex-panel-detail-sprite" data-sprite="/api/sprites/${data.sprite_path || ""}"
        width="96" height="96" style="image-rendering:pixelated;display:none">
      <div class="dex-panel-detail-info">
        <div class="dex-panel-detail-name">${esc(data.name || "")} <span class="dex-panel-detail-num">${dexNum}</span></div>
        <div class="dex-panel-detail-types">${types}</div>
        ${levelHtml}
        <div class="dex-panel-detail-abilities">${abilities || ""}</div>
      </div>
    </div>
    <div class="dex-panel-stats">
      ${statRows}
      <div class="dex-panel-stat-row dex-panel-bst-row">
        <span class="dex-panel-stat-label">BST</span>
        <span class="dex-panel-stat-num dex-panel-bst-num">${bst}</span>
      </div>
    </div>
    ${evoHtml}
  </div>`;

  // Load detail sprite
  const detailImg = body.querySelector(".dex-panel-detail-sprite");
  if (detailImg && detailImg.dataset.sprite) {
    processSprite(detailImg.dataset.sprite).then(url => {
      detailImg.src = url;
      detailImg.style.display = "";
    }).catch(() => {});
  }

  wireBackButton(body);
}

function wireBackButton(body) {
  const back = body.querySelector(".dex-panel-back");
  if (back) {
    back.addEventListener("click", (e) => {
      e.preventDefault();
      renderGrid();
    });
  }
}

function statColour(val) {
  if (val >= 150) return "#6890F0";
  if (val >= 120) return "#78C850";
  if (val >= 90)  return "#78C850";
  if (val >= 60)  return "#E0C068";
  if (val >= 30)  return "#F8D030";
  return "#F08030";
}

/** Format ITEM_WATER_STONE -> "Water Stone" */
function formatItemName(param) {
  if (!param || param === "0") return "";
  let name = param;
  if (name.startsWith("ITEM_")) name = name.slice(5);
  return name.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

/** Describe an evolution method + param as a short label. */
function evoLabel(method, param) {
  if (method === "LEVEL" && param && param !== "0") return `Lv.${param}`;
  if (method === "ITEM") return formatItemName(param) || "Item";
  if (method === "TRADE") {
    const item = formatItemName(param);
    return item ? `Trade (${item})` : "Trade";
  }
  if (method === "FRIENDSHIP") return "Friendship";
  if (method === "LEVEL_NIGHT" || method === "FRIENDSHIP_NIGHT") return "Night";
  if (method === "LEVEL_DAY" || method === "FRIENDSHIP_DAY") return "Day";
  if (method === "BEAUTY") return "Beauty";
  if (method) return method.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
  return "";
}

function estimateLevelRange(chain, currentConst) {
  if (!chain || chain.length <= 1) return null;

  const idx = chain.findIndex(e => e.const === currentConst);
  if (idx < 0) return null;

  if (idx === 0) {
    // Base form
    const next = chain[idx + 1];
    if (next && next.method === "LEVEL" && next.param && next.param !== "0") {
      return `Expected wild range: Lv. 1\u2013${parseInt(next.param) - 1}`;
    }
    return "Expected wild range: Lv. 1+";
  }

  // Evolved form
  const thisEntry = chain[idx];
  if (thisEntry.method === "LEVEL" && thisEntry.param && thisEntry.param !== "0") {
    const evoLevel = parseInt(thisEntry.param);
    const next = chain[idx + 1];
    if (next && next.method === "LEVEL" && next.param && next.param !== "0") {
      return `Expected wild range: Lv. ${evoLevel}\u2013${parseInt(next.param) - 1}`;
    }
    return `Expected wild range: Lv. ${evoLevel}+`;
  }

  // Non-level evolution — show what method was used
  const label = evoLabel(thisEntry.method, thisEntry.param);
  return `Evolved via ${label}`;
}

function renderEvoChain(chain, currentConst) {
  if (!chain || chain.length <= 1) return "";
  const items = chain.map(e => {
    const isCurrent = e.const === currentConst;
    let arrow = "";
    if (e.method) {
      const label = evoLabel(e.method, e.param);
      arrow = `<span class="dex-panel-evo-arrow">&rarr; ${label}</span>`;
    }
    return `${arrow}<span class="dex-panel-evo-name${isCurrent ? " current" : ""}" data-const="${e.const}">${esc(e.name)}</span>`;
  }).join(" ");

  return `<div class="dex-panel-evo-chain">${items}</div>`;
}

// ---------------------------------------------------------------------------
// Panel DOM setup (called once from app.js)
// ---------------------------------------------------------------------------

export function initDexPanel(closeBuildDrawer) {
  closeBuildDrawerFn = closeBuildDrawer;

  const panel = getPanel();
  const toggle = getToggle();
  if (!panel) return;

  // Build panel inner HTML
  const genButtons = Object.keys(GEN_RANGES).map(g =>
    `<button class="dex-panel-gen-chip" data-gen="${g}">Gen ${g}</button>`
  ).join("");

  panel.innerHTML = `
    <div class="dex-panel-header">
      <span class="dex-panel-title">Dex</span>
      <select class="dex-panel-sort">
        <option value="dex">Dex #</option>
        <option value="name-az">A\u2013Z</option>
        <option value="name-za">Z\u2013A</option>
        <option value="bst-desc">BST \u2193</option>
        <option value="bst-asc">BST \u2191</option>
      </select>
      <input type="text" class="dex-panel-search" placeholder="Search..." autocomplete="off">
      <span class="dex-panel-results"></span>
      <button class="dex-panel-expand" title="Expand">&#9650;</button>
      <button class="dex-panel-close">&times;</button>
    </div>
    <div class="dex-panel-filters">
      <div class="dex-panel-filter-row">
        ${ALL_TYPES.map(t => {
          const c = TYPE_COLOURS[t];
          return `<button class="dex-panel-type-chip" data-type="${t}" style="--chip-col:${c}">${t}</button>`;
        }).join("")}
        <button class="dex-panel-type-chip dex-panel-chip-clear" style="--chip-col:var(--text-muted)">Clear</button>
      </div>
      <div class="dex-panel-filter-row">
        ${genButtons}
        <button class="dex-panel-gen-chip dex-panel-gen-clear">All Gens</button>
      </div>
    </div>
    <div class="dex-panel-body"></div>`;

  // Toggle button
  if (toggle) {
    toggle.addEventListener("click", togglePanel);
  }

  // Close button
  panel.querySelector(".dex-panel-close").addEventListener("click", closePanel);

  // Expand/collapse button — toggles between compact (400px) and full-screen
  const expandBtn = panel.querySelector(".dex-panel-expand");
  expandBtn.addEventListener("click", () => {
    panel.classList.toggle("expanded");
    const isExpanded = panel.classList.contains("expanded");
    expandBtn.innerHTML = isExpanded ? "&#9660;" : "&#9650;";
    expandBtn.title = isExpanded ? "Collapse" : "Expand";
    // Re-render to fill the larger/smaller viewport
    if (filtered.length) renderGrid();
  });

  // Search
  const searchInput = panel.querySelector(".dex-panel-search");
  searchInput.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      searchQuery = searchInput.value.trim();
      if (searchQuery && (searchQuery.includes(":") || /bst[<>=]/.test(searchQuery))) {
        serverSearch(searchQuery);
      } else {
        applyFilters();
      }
    }, 250);
  });

  // Sort dropdown
  const sortSelect = panel.querySelector(".dex-panel-sort");
  sortSelect.addEventListener("change", () => {
    activeSortMode = sortSelect.value;
    applyFilters();
  });

  // Type chips — dual-type support (max 2, AND logic)
  function syncTypeChips() {
    panel.querySelectorAll(".dex-panel-type-chip").forEach(c => {
      if (c.classList.contains("dex-panel-chip-clear")) {
        c.classList.toggle("active", activeTypeFilters.length === 0);
      } else {
        c.classList.toggle("active", activeTypeFilters.includes(c.dataset.type));
      }
    });
  }

  panel.querySelectorAll(".dex-panel-type-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      if (chip.classList.contains("dex-panel-chip-clear")) {
        activeTypeFilters = [];
      } else {
        const t = chip.dataset.type;
        const idx = activeTypeFilters.indexOf(t);
        if (idx >= 0) {
          activeTypeFilters.splice(idx, 1);
        } else if (activeTypeFilters.length < 2) {
          activeTypeFilters.push(t);
        } else {
          // Replace oldest
          activeTypeFilters.shift();
          activeTypeFilters.push(t);
        }
      }
      syncTypeChips();
      applyFilters();
    });
  });

  // Generation chips — multi-select (OR logic)
  function syncGenChips() {
    panel.querySelectorAll(".dex-panel-gen-chip").forEach(c => {
      if (c.classList.contains("dex-panel-gen-clear")) {
        c.classList.toggle("active", activeGens.length === 0);
      } else {
        c.classList.toggle("active", activeGens.includes(parseInt(c.dataset.gen, 10)));
      }
    });
  }
  syncGenChips();

  panel.querySelectorAll(".dex-panel-gen-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      if (chip.classList.contains("dex-panel-gen-clear")) {
        activeGens = [];
      } else {
        const g = parseInt(chip.dataset.gen, 10);
        const idx = activeGens.indexOf(g);
        if (idx >= 0) activeGens.splice(idx, 1);
        else activeGens.push(g);
      }
      syncGenChips();
      applyFilters();
    });
  });

  // Evolution chain clicks (delegated)
  panel.addEventListener("click", (e) => {
    const evoName = e.target.closest(".dex-panel-evo-name");
    if (evoName && evoName.dataset.const) {
      showDetail(evoName.dataset.const);
    }
  });
}

/** Close the panel programmatically (called by app.js when build drawer opens). */
export { closePanel as closeDexPanel };
