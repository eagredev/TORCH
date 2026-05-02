/**
 * TORCH Studio — Dex Status Bar Widget.
 * Floating pop-out species reference anchored to the IDE status bar.
 * Lightweight alternative to the full Dex view — quick lookup without
 * leaving the map editor.
 *
 * TORCH_MODULE
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
const PAGE_SIZE = 40;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _panelEl = null;
let _toggleBtn = null;
let _isOpen = false;
let _cachedList = null;
let _filtered = [];
let _rendered = 0;
let _searchQuery = "";
let _activeTypes = [];   // max 2 types (AND logic)
let _activeGens = [];    // multi-select (OR logic)
let _debounceTimer = null;
let _detailCache = {};
let _observer = null;
let _scrollFn = null;
let _spriteQueue = [];
let _spriteActive = 0;
const SPRITE_CONCURRENCY = 2;
let _escHandler = null;

// ---------------------------------------------------------------------------
// Sprite queue (independent of dexPanel.js)
// ---------------------------------------------------------------------------

function _queueSprite(img) {
  _spriteQueue.push(img);
  _drainQueue();
}

function _drainQueue() {
  while (_spriteActive < SPRITE_CONCURRENCY && _spriteQueue.length) {
    const img = _spriteQueue.shift();
    const url = img.dataset.sprite;
    if (!url) continue;
    _spriteActive++;
    processSprite(url).then(dataUrl => {
      img.src = dataUrl;
      img.style.visibility = "";
    }).catch(() => {
      img.style.visibility = "hidden";
    }).finally(() => {
      _spriteActive--;
      _drainQueue();
    });
  }
}

// ---------------------------------------------------------------------------
// Init / Cleanup
// ---------------------------------------------------------------------------

/**
 * Initialize the Dex widget. Call during IDE render().
 * @param {HTMLElement} containerEl — the ide-root or document.body
 */
export function initDexWidget(containerEl) {
  if (_panelEl) return; // already initialized

  // 1. Create toggle button in the status bar
  const statusBar = document.getElementById("ide-status");
  if (!statusBar) return;

  _toggleBtn = document.createElement("button");
  _toggleBtn.className = "dex-widget-toggle";
  _toggleBtn.textContent = "Dex";
  _toggleBtn.title = "Toggle Dex reference";
  _toggleBtn.addEventListener("click", _toggle);
  // Insert before version element so widget buttons sit left of version
  const versionEl = document.getElementById("ide-status-version");
  if (versionEl) statusBar.insertBefore(_toggleBtn, versionEl);
  else statusBar.appendChild(_toggleBtn);

  // 2. Create the floating panel
  _panelEl = document.createElement("div");
  _panelEl.className = "dex-widget-panel";
  // Build type chips HTML
  const typeChipsHtml = ALL_TYPES.map(t =>
    `<span class="dex-widget-chip dex-widget-type-chip" data-type="${t}" style="background:${TYPE_COLOURS[t]}">${t.slice(0, 3)}</span>`
  ).join("");
  // Build gen chips HTML
  const genChipsHtml = Object.keys(GEN_RANGES).map(g =>
    `<span class="dex-widget-chip dex-widget-gen-chip" data-gen="${g}">${g}</span>`
  ).join("");

  _panelEl.innerHTML = `
    <div class="dex-widget-header">
      <span class="dex-widget-title">Dex</span>
      <input type="text" class="dex-widget-search" placeholder="Search species..." autocomplete="off">
      <button class="dex-widget-filter-toggle" title="Toggle filters">\u25BC</button>
      <button class="dex-widget-close">\u00d7</button>
    </div>
    <div class="dex-widget-filters">
      <div class="dex-widget-filter-row">
        <span class="dex-widget-filter-label">Type</span>
        <span class="dex-widget-chip dex-widget-type-clear active">All</span>
        ${typeChipsHtml}
      </div>
      <div class="dex-widget-filter-row">
        <span class="dex-widget-filter-label">Gen</span>
        <span class="dex-widget-chip dex-widget-gen-clear active">All</span>
        ${genChipsHtml}
      </div>
    </div>
    <div class="dex-widget-body"></div>`;

  // Append to ide-root (or body) to avoid overflow clipping from panels
  const root = containerEl.querySelector(".ide-root") || containerEl;
  root.appendChild(_panelEl);

  // Wire close button
  _panelEl.querySelector(".dex-widget-close").addEventListener("click", _close);

  // Wire search
  const searchInput = _panelEl.querySelector(".dex-widget-search");
  searchInput.addEventListener("input", () => {
    clearTimeout(_debounceTimer);
    _debounceTimer = setTimeout(() => {
      _searchQuery = searchInput.value.trim();
      _applyFilters();
    }, 200);
  });

  // Filter toggle button
  const filterToggle = _panelEl.querySelector(".dex-widget-filter-toggle");
  const filtersEl = _panelEl.querySelector(".dex-widget-filters");
  filterToggle.addEventListener("click", () => {
    const show = !filtersEl.classList.contains("open");
    filtersEl.classList.toggle("open", show);
    filterToggle.textContent = show ? "\u25B2" : "\u25BC";
    filterToggle.title = show ? "Hide filters" : "Toggle filters";
  });

  // Type chips — max 2, AND logic
  _panelEl.querySelectorAll(".dex-widget-type-chip, .dex-widget-type-clear").forEach(chip => {
    chip.addEventListener("click", () => {
      if (chip.classList.contains("dex-widget-type-clear")) {
        _activeTypes = [];
      } else {
        const t = chip.dataset.type;
        const idx = _activeTypes.indexOf(t);
        if (idx >= 0) _activeTypes.splice(idx, 1);
        else if (_activeTypes.length < 2) _activeTypes.push(t);
        else { _activeTypes.shift(); _activeTypes.push(t); }
      }
      _syncTypeChips();
      _applyFilters();
    });
  });

  // Gen chips — multi-select, OR logic
  _panelEl.querySelectorAll(".dex-widget-gen-chip, .dex-widget-gen-clear").forEach(chip => {
    chip.addEventListener("click", () => {
      if (chip.classList.contains("dex-widget-gen-clear")) {
        _activeGens = [];
      } else {
        const g = parseInt(chip.dataset.gen, 10);
        const idx = _activeGens.indexOf(g);
        if (idx >= 0) _activeGens.splice(idx, 1);
        else _activeGens.push(g);
      }
      _syncGenChips();
      _applyFilters();
    });
  });

  // Escape key closes panel
  _escHandler = (e) => {
    if (e.key === "Escape" && _isOpen) {
      e.stopPropagation();
      _close();
    }
  };
  document.addEventListener("keydown", _escHandler);
}

/** Tear down the widget. Call during IDE cleanup(). */
export function cleanupDexWidget() {
  if (_escHandler) {
    document.removeEventListener("keydown", _escHandler);
    _escHandler = null;
  }
  if (_observer) { _observer.disconnect(); _observer = null; }
  if (_debounceTimer) clearTimeout(_debounceTimer);
  if (_panelEl) { _panelEl.remove(); _panelEl = null; }
  if (_toggleBtn) { _toggleBtn.remove(); _toggleBtn = null; }
  _isOpen = false;
  _cachedList = null;
  _filtered = [];
  _rendered = 0;
  _searchQuery = "";
  _activeTypes = [];
  _activeGens = [];
  _detailCache = {};
  _spriteQueue = [];
  _spriteActive = 0;
  _scrollFn = null;
}

// ---------------------------------------------------------------------------
// Open / Close / Toggle
// ---------------------------------------------------------------------------

function _toggle() {
  if (_isOpen) _close();
  else _open();
}

function _open() {
  if (!_panelEl) return;
  _panelEl.classList.add("open");
  if (_toggleBtn) _toggleBtn.classList.add("active");
  _isOpen = true;

  // Focus search
  const input = _panelEl.querySelector(".dex-widget-search");
  if (input) requestAnimationFrame(() => input.focus());

  // Lazy-load data on first open
  if (!_cachedList) _loadSpecies();
}

function _close() {
  if (!_panelEl) return;
  _panelEl.classList.remove("open");
  if (_toggleBtn) _toggleBtn.classList.remove("active");
  _isOpen = false;
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function _loadSpecies() {
  const body = _panelEl.querySelector(".dex-widget-body");
  if (!body) return;
  body.innerHTML = `<div class="dex-widget-loading">Loading...</div>`;

  const res = await api("/species");
  if (!res.ok) {
    body.innerHTML = `<div class="dex-widget-loading">Error loading species</div>`;
    return;
  }
  _cachedList = res.data || [];
  _applyFilters();
}

function _applyFilters() {
  if (!_cachedList) return;
  let result = _cachedList;
  if (_searchQuery) {
    const q = _searchQuery.toLowerCase();
    result = result.filter(sp => sp.name.toLowerCase().includes(q));
  }
  // Type filters (AND — must have ALL selected types)
  if (_activeTypes.length) {
    result = result.filter(sp => {
      const spTypes = (sp.types || []).map(t => t.toLowerCase());
      return _activeTypes.every(f => spTypes.includes(f.toLowerCase()));
    });
  }
  // Gen filters (OR — match any selected gen)
  if (_activeGens.length) {
    result = result.filter(sp => {
      const num = sp.nat_dex_num || 0;
      return _activeGens.some(g => {
        const [lo, hi] = GEN_RANGES[g] || [0, 0];
        return num >= lo && num <= hi;
      });
    });
  }
  _filtered = result;
  _renderList();
}

function _syncTypeChips() {
  if (!_panelEl) return;
  _panelEl.querySelectorAll(".dex-widget-type-chip, .dex-widget-type-clear").forEach(c => {
    if (c.classList.contains("dex-widget-type-clear")) {
      c.classList.toggle("active", _activeTypes.length === 0);
    } else {
      c.classList.toggle("active", _activeTypes.includes(c.dataset.type));
    }
  });
}

function _syncGenChips() {
  if (!_panelEl) return;
  _panelEl.querySelectorAll(".dex-widget-gen-chip, .dex-widget-gen-clear").forEach(c => {
    if (c.classList.contains("dex-widget-gen-clear")) {
      c.classList.toggle("active", _activeGens.length === 0);
    } else {
      c.classList.toggle("active", _activeGens.includes(parseInt(c.dataset.gen, 10)));
    }
  });
}

// ---------------------------------------------------------------------------
// Species list
// ---------------------------------------------------------------------------

function _renderList() {
  const body = _panelEl.querySelector(".dex-widget-body");
  if (!body) return;

  // Clean up previous
  if (_observer) { _observer.disconnect(); _observer = null; }
  if (_scrollFn) { body.removeEventListener("scroll", _scrollFn); _scrollFn = null; }
  _spriteQueue = [];
  _rendered = 0;

  body.innerHTML = `<div class="dex-widget-list"></div>`;
  const list = body.firstElementChild;

  if (!_filtered.length) {
    list.innerHTML = `<div class="dex-widget-empty">No results</div>`;
    return;
  }

  _rendered = _appendRows(list, 0, PAGE_SIZE);
  _setupObserver(body);
  _setupScroll(body);

  // Fill visible area
  requestAnimationFrame(() => _fillViewport(body));
}

function _fillViewport(scrollContainer) {
  if (_rendered >= _filtered.length) return;
  if (scrollContainer.scrollHeight <= scrollContainer.clientHeight + 50) {
    const list = scrollContainer.firstElementChild;
    if (list) {
      _rendered = _appendRows(list, _rendered, PAGE_SIZE);
      _observeNewSprites(scrollContainer);
      if (_rendered < _filtered.length) {
        requestAnimationFrame(() => _fillViewport(scrollContainer));
      }
    }
  }
}

function _appendRows(container, start, count) {
  const end = Math.min(start + count, _filtered.length);
  const frag = document.createDocumentFragment();
  for (let i = start; i < end; i++) {
    const sp = _filtered[i];
    const row = document.createElement("div");
    row.className = "dex-widget-row";

    // Sprite
    const img = document.createElement("img");
    img.className = "dex-widget-row-sprite";
    img.width = 32;
    img.height = 32;
    img.style.imageRendering = "pixelated";
    img.style.visibility = "hidden";
    img.dataset.sprite = `/api/sprites/${sp.sprite_path}`;
    img.onerror = () => { img.style.visibility = "hidden"; };
    row.appendChild(img);

    // Name
    const name = document.createElement("span");
    name.className = "dex-widget-row-name";
    name.textContent = sp.name;
    row.appendChild(name);

    // Type badges
    const types = document.createElement("span");
    types.className = "dex-widget-row-types";
    for (const t of (sp.types || [])) {
      const badge = document.createElement("span");
      badge.className = "dex-widget-type-badge";
      badge.style.background = TYPE_COLOURS[t] || "#888";
      badge.textContent = t;
      types.appendChild(badge);
    }
    row.appendChild(types);

    row.addEventListener("click", () => _showDetail(sp.const));
    frag.appendChild(row);
  }
  container.appendChild(frag);
  return end;
}

function _setupObserver(scrollContainer) {
  _observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        const img = entry.target;
        _observer.unobserve(img);
        _queueSprite(img);
      }
    }
  }, { root: scrollContainer, rootMargin: "100px" });

  scrollContainer.querySelectorAll(".dex-widget-row-sprite[data-sprite]").forEach(img => {
    _observer.observe(img);
  });
}

function _observeNewSprites(scrollContainer) {
  if (!_observer) return;
  scrollContainer.querySelectorAll(".dex-widget-row-sprite[data-sprite]").forEach(img => {
    if (!img.src || img.style.visibility === "hidden") _observer.observe(img);
  });
}

function _setupScroll(scrollContainer) {
  _scrollFn = () => {
    if (_rendered >= _filtered.length) return;
    const threshold = scrollContainer.scrollHeight - scrollContainer.clientHeight - 200;
    if (scrollContainer.scrollTop >= threshold) {
      const list = scrollContainer.firstElementChild;
      if (list) {
        _rendered = _appendRows(list, _rendered, PAGE_SIZE);
        _observeNewSprites(scrollContainer);
      }
    }
  };
  scrollContainer.addEventListener("scroll", _scrollFn);
}

// ---------------------------------------------------------------------------
// Detail view
// ---------------------------------------------------------------------------

async function _showDetail(speciesConst) {
  const body = _panelEl.querySelector(".dex-widget-body");
  if (!body) return;

  body.innerHTML = `<div class="dex-widget-loading">Loading...</div>`;

  let data = _detailCache[speciesConst];
  if (!data) {
    const res = await api(`/species/${speciesConst}`);
    if (!res.ok) {
      body.innerHTML = `<div class="dex-widget-detail">
        <a href="#" class="dex-widget-back">\u2190 Back</a>
        <p>Error loading species</p>
      </div>`;
      _wireBack(body);
      return;
    }
    data = res.data;
    _detailCache[speciesConst] = data;
  }

  const detail = document.createElement("div");
  detail.className = "dex-widget-detail";

  // Back button
  const back = document.createElement("a");
  back.href = "#";
  back.className = "dex-widget-back";
  back.textContent = "\u2190 Back";
  back.addEventListener("click", (e) => { e.preventDefault(); _renderList(); });
  detail.appendChild(back);

  // Header: sprite + name/types
  const header = document.createElement("div");
  header.className = "dex-widget-detail-header";

  const spriteImg = document.createElement("img");
  spriteImg.className = "dex-widget-detail-sprite";
  spriteImg.width = 80;
  spriteImg.height = 80;
  spriteImg.style.imageRendering = "pixelated";
  spriteImg.style.visibility = "hidden";
  header.appendChild(spriteImg);

  const info = document.createElement("div");
  info.className = "dex-widget-detail-info";

  const nameEl = document.createElement("div");
  nameEl.className = "dex-widget-detail-name";
  nameEl.textContent = data.name || "";
  if (data.nat_dex_num) {
    const num = document.createElement("span");
    num.className = "dex-widget-detail-num";
    num.textContent = ` #${String(data.nat_dex_num).padStart(3, "0")}`;
    nameEl.appendChild(num);
  }
  info.appendChild(nameEl);

  // Types
  const typesEl = document.createElement("div");
  typesEl.className = "dex-widget-detail-types";
  for (const t of (data.types || [])) {
    const badge = document.createElement("span");
    badge.className = "dex-widget-type-badge";
    badge.style.background = TYPE_COLOURS[t] || "#888";
    badge.textContent = t;
    typesEl.appendChild(badge);
  }
  info.appendChild(typesEl);

  // Abilities
  const abilities = data.abilities_described || [];
  if (abilities.length) {
    const abEl = document.createElement("div");
    abEl.className = "dex-widget-detail-abilities";
    for (const a of abilities) {
      const span = document.createElement("span");
      span.className = "dex-widget-ability";
      span.textContent = a.name;
      span.title = a.description || "";
      abEl.appendChild(span);
    }
    info.appendChild(abEl);
  }

  header.appendChild(info);
  detail.appendChild(header);

  // Stats
  const statsEl = document.createElement("div");
  statsEl.className = "dex-widget-stats";
  let bst = 0;
  for (let i = 0; i < STAT_KEYS.length; i++) {
    const val = data[STAT_KEYS[i]] || 0;
    bst += val;
    const pct = Math.min(100, (val / 255) * 100);

    const row = document.createElement("div");
    row.className = "dex-widget-stat-row";

    const label = document.createElement("span");
    label.className = "dex-widget-stat-label";
    label.textContent = STAT_LABELS[i];
    row.appendChild(label);

    const numEl = document.createElement("span");
    numEl.className = "dex-widget-stat-num";
    numEl.textContent = String(val);
    row.appendChild(numEl);

    const bar = document.createElement("div");
    bar.className = "dex-widget-stat-bar";
    const fill = document.createElement("div");
    fill.className = "dex-widget-stat-fill";
    fill.style.width = pct + "%";
    fill.style.background = _statColour(val);
    bar.appendChild(fill);
    row.appendChild(bar);

    statsEl.appendChild(row);
  }

  // BST total
  const bstRow = document.createElement("div");
  bstRow.className = "dex-widget-stat-row dex-widget-bst-row";
  const bstLabel = document.createElement("span");
  bstLabel.className = "dex-widget-stat-label";
  bstLabel.textContent = "BST";
  bstRow.appendChild(bstLabel);
  const bstNum = document.createElement("span");
  bstNum.className = "dex-widget-stat-num dex-widget-bst-num";
  bstNum.textContent = String(data.bst || bst);
  bstRow.appendChild(bstNum);
  statsEl.appendChild(bstRow);

  detail.appendChild(statsEl);

  // Evolution chain
  const chain = data.evolution_chain || [];
  if (chain.length > 1) {
    const evoEl = document.createElement("div");
    evoEl.className = "dex-widget-evo-chain";
    for (const e of chain) {
      if (e.method) {
        const arrow = document.createElement("span");
        arrow.className = "dex-widget-evo-arrow";
        arrow.textContent = "\u2192 " + _evoLabel(e.method, e.param);
        evoEl.appendChild(arrow);
      }
      const nameSpan = document.createElement("span");
      nameSpan.className = "dex-widget-evo-name";
      if (e.const === speciesConst) nameSpan.classList.add("current");
      nameSpan.textContent = e.name;
      nameSpan.addEventListener("click", () => _showDetail(e.const));
      evoEl.appendChild(nameSpan);
    }
    detail.appendChild(evoEl);
  }

  body.innerHTML = "";
  body.appendChild(detail);

  // Load sprite
  if (data.sprite_path) {
    processSprite(`/api/sprites/${data.sprite_path}`).then(url => {
      spriteImg.src = url;
      spriteImg.style.visibility = "";
    }).catch(() => {});
  }
}

function _wireBack(body) {
  const back = body.querySelector(".dex-widget-back");
  if (back) {
    back.addEventListener("click", (e) => { e.preventDefault(); _renderList(); });
  }
}

function _statColour(val) {
  if (val >= 150) return "#6890F0";
  if (val >= 120) return "#78C850";
  if (val >= 90)  return "#78C850";
  if (val >= 60)  return "#E0C068";
  if (val >= 30)  return "#F8D030";
  return "#F08030";
}

function _evoLabel(method, param) {
  if (method === "LEVEL" && param && param !== "0") return `Lv.${param}`;
  if (method === "ITEM") return _formatItemName(param) || "Item";
  if (method === "TRADE") {
    const item = _formatItemName(param);
    return item ? `Trade (${item})` : "Trade";
  }
  if (method === "FRIENDSHIP") return "Friendship";
  if (method === "LEVEL_NIGHT" || method === "FRIENDSHIP_NIGHT") return "Night";
  if (method === "LEVEL_DAY" || method === "FRIENDSHIP_DAY") return "Day";
  if (method === "BEAUTY") return "Beauty";
  if (method) return method.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
  return "";
}

function _formatItemName(param) {
  if (!param || param === "0") return "";
  let name = param;
  if (name.startsWith("ITEM_")) name = name.slice(5);
  return name.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}
