/**
 * TORCH Web GUI -- Trainer Browser + Team Builder view.
 * Grid browser with search/filters, detailed party viewer, and full edit mode.
 */

import { api, postApi } from "../app.js";
import { processSprite, processSpriteFrames } from "../spriteUtils.js";
import { esc } from "../utils.js";
import { renderStudioNavbar } from "../studioNav.js";

/** Run processSprite on all .tr-mon-sprite images within a container. */
function processMonSprites(root) {
  root.querySelectorAll("img.tr-mon-sprite").forEach(img => {
    const src = img.getAttribute("src");
    if (!src || src.startsWith("data:")) return;
    processSprite(src).then(dataUrl => { img.src = dataUrl; });
  });
}

/** Run processSprite on all .tr-item-icon images within a container (bg removal). */
function processItemIcons(root) {
  root.querySelectorAll("img.tr-item-icon").forEach(img => {
    const src = img.getAttribute("src");
    if (!src || src.startsWith("data:")) return;
    processSprite(src).then(dataUrl => { img.src = dataUrl; });
  });
}

/** Category icon cache + per-icon bg removal for the 3-icon spritesheet. */
const _catIconCache = {};

async function getCategoryIconDataUrl(category) {
  if (_catIconCache[category]) return _catIconCache[category];

  const img = await new Promise((resolve, reject) => {
    const el = new Image();
    el.onload = () => resolve(el);
    el.onerror = () => reject(new Error("Failed to load category icons"));
    el.src = "/api/category-icons";
  });

  const w = img.naturalWidth;                    // 20
  const h = Math.floor(img.naturalHeight / 3);   // 20
  const offsets = { physical: 0, special: h, status: h * 2 };
  const yOff = offsets[category] || 0;

  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(img, 0, yOff, w, h, 0, 0, w, h);

  // Remove background: sample pixel (0,0) of this slice
  try {
    const imageData = ctx.getImageData(0, 0, w, h);
    const d = imageData.data;
    const bgR = d[0], bgG = d[1], bgB = d[2];
    for (let i = 0; i < d.length; i += 4) {
      if (Math.abs(d[i] - bgR) <= 2 && Math.abs(d[i+1] - bgG) <= 2 && Math.abs(d[i+2] - bgB) <= 2) {
        d[i+3] = 0;
      }
    }
    ctx.putImageData(imageData, 0, 0);
  } catch { /* canvas security error */ }

  const dataUrl = canvas.toDataURL("image/png");
  _catIconCache[category] = dataUrl;
  return dataUrl;
}

/** Process category icon images within a container. */
function processCategoryIcons(root) {
  root.querySelectorAll("img.tr-pm-cat-img").forEach(img => {
    const cat = img.dataset.category;
    if (cat) getCategoryIconDataUrl(cat).then(url => { img.src = url; });
  });
}

// Stat bar colours (same as Dex)
const STAT_COLOURS = {
  hp: "#F08030", atk: "#F08030", def: "#F8D030",
  spa: "#6890F0", spd: "#78C850", spe: "#F85888",
};
const STAT_LABELS = { hp: "HP", atk: "Atk", def: "Def", spa: "SpA", spd: "SpD", spe: "Spe" };
const STAT_KEYS = ["hp", "atk", "def", "spa", "spd", "spe"];

let debounceTimer = null;
let allTrainers = [];        // current filtered set
let cachedTrainers = null;   // full unfiltered list
let renderedCount = 0;
let scrollHandler = null;
let spriteObserver = null;
let activeFilter = "all";    // "all" | "custom" | "vanilla"
let searchQuery = "";
let classFilter = "";
const PAGE_SIZE = 48;

// Edit mode state
let editMode = false;
let dirty = false;
let workingCopy = null;  // mutable copy of trainer detail data
let refData = null;      // cached /api/trainers/ref
let cachedMoves = null;  // cached /api/moves
let cachedItems = null;  // cached /api/items
const learnableCache = new Map(); // species_const -> { set: Set, levels: Map, tms: Set, eggs: Set }

async function getLearnableMoves(speciesConst) {
  if (learnableCache.has(speciesConst)) return learnableCache.get(speciesConst);

  const [lu, tm, egg] = await Promise.all([
    api(`/species/${speciesConst}/learnset/level_up`),
    api(`/species/${speciesConst}/learnset/teachable`),
    api(`/species/${speciesConst}/learnset/egg`),
  ]);

  const set = new Set();
  const levels = new Map();  // moveConst -> level (from level-up data)
  const tms = new Set();
  const eggs = new Set();

  if (lu.ok && Array.isArray(lu.data)) {
    lu.data.forEach(m => {
      set.add(m.move);
      levels.set(m.move, m.level);
    });
  }
  if (tm.ok && Array.isArray(tm.data)) {
    tm.data.forEach(m => { set.add(m.move); tms.add(m.move); });
  }
  if (egg.ok && Array.isArray(egg.data)) {
    egg.data.forEach(m => { set.add(m.move); eggs.add(m.move); });
  }

  const result = { set, levels, tms, eggs };
  learnableCache.set(speciesConst, result);
  return result;
}

const PLACEHOLDER_SVG = "data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2264%22 height=%2264%22><rect fill=%22%23222%22 width=%2264%22 height=%2264%22 rx=%228%22/></svg>";
const ERROR_SVG = "data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2264%22 height=%2264%22><rect fill=%22%23333%22 width=%2264%22 height=%2264%22 rx=%228%22/><text x=%2232%22 y=%2236%22 text-anchor=%22middle%22 fill=%22%23666%22 font-size=%2212%22>?</text></svg>";

// GBA textbox constants
const GBA_LINE_LEN = 38;
const GBA_LINES_PER_BOX = 2;

// Sprite loading queue (same pattern as Dex)
const spriteQueue = [];
let spritesInFlight = 0;
const MAX_CONCURRENT_SPRITES = 4;

function queueSprite(img) {
  spriteQueue.push(img);
  drainSpriteQueue();
}

function drainSpriteQueue() {
  while (spritesInFlight < MAX_CONCURRENT_SPRITES && spriteQueue.length > 0) {
    const img = spriteQueue.shift();
    if (!img.dataset.pending) continue;
    spritesInFlight++;
    const realSrc = img.dataset.sprite;
    // Trainer class sprites: pipe through processSprite for bg removal
    if (img.classList.contains("tr-card-sprite")) {
      processSprite(realSrc).then(dataUrl => {
        if (img.dataset.pending) { img.src = dataUrl; delete img.dataset.pending; }
        spritesInFlight--;
        drainSpriteQueue();
      }).catch(() => {
        if (img.dataset.pending) { img.src = ERROR_SVG; delete img.dataset.pending; }
        spritesInFlight--;
        drainSpriteQueue();
      });
    } else {
      const loader = new Image();
      loader.onload = () => {
        if (img.dataset.pending) { img.src = realSrc; delete img.dataset.pending; }
        spritesInFlight--;
        drainSpriteQueue();
      };
      loader.onerror = () => {
        if (img.dataset.pending) { img.src = ERROR_SVG; delete img.dataset.pending; }
        spritesInFlight--;
        drainSpriteQueue();
      };
      loader.src = realSrc;
    }
  }
}

function ensureSpriteObserver() {
  if (spriteObserver) return;
  spriteObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      const img = entry.target;
      if (entry.isIntersecting) {
        const realSrc = img.dataset.sprite;
        if (realSrc && img.src !== realSrc && !img.dataset.pending) {
          img.dataset.pending = "1";
          queueSprite(img);
        }
      } else {
        delete img.dataset.pending;
        if (img.dataset.sprite && img.src !== PLACEHOLDER_SVG) {
          img.src = PLACEHOLDER_SVG;
        }
      }
    }
  }, { rootMargin: "300px" });
}

// ---------------------------------------------------------------------------
// Party dots
// ---------------------------------------------------------------------------

function renderPartyDots(count) {
  let dots = "";
  for (let i = 0; i < 6; i++) {
    const cls = i < count ? "tr-dot filled" : "tr-dot";
    dots += `<span class="${cls}"></span>`;
  }
  return `<span class="tr-party-dots">${dots}</span>`;
}

// ---------------------------------------------------------------------------
// List view card
// ---------------------------------------------------------------------------

function renderCard(t) {
  const spriteSrc = t.sprite_path
    ? `/api/trainers/sprites/${t.sprite_path}`
    : PLACEHOLDER_SVG;

  const badges = [];
  if (t.is_custom) badges.push(`<span class="tr-badge tr-badge-custom">Custom</span>`);
  if (t.is_double) badges.push(`<span class="tr-badge tr-badge-double">2v2</span>`);

  return `<div class="tr-card" data-const="${t.const}">
    <div class="tr-card-sprite-wrap">
      <img class="tr-card-sprite" src="${PLACEHOLDER_SVG}" data-sprite="${spriteSrc}" alt="${t.name || t.const}">
    </div>
    <span class="tr-card-name">${t.name || "???"}</span>
    <span class="tr-card-class">${t.class || ""}</span>
    ${renderPartyDots(t.party_size || 0)}
    <div class="tr-card-badges">${badges.join("")}</div>
  </div>`;
}

function appendCards(grid, trainers, start, count) {
  ensureSpriteObserver();
  const end = Math.min(start + count, trainers.length);
  const fragment = document.createDocumentFragment();
  for (let i = start; i < end; i++) {
    const tmp = document.createElement("div");
    tmp.innerHTML = renderCard(trainers[i]);
    const card = tmp.firstElementChild;
    card.addEventListener("click", () => {
      window.location.hash = `#/trainers/${card.dataset.const}`;
    });
    const img = card.querySelector("img");
    if (img) spriteObserver.observe(img);
    fragment.appendChild(card);
  }
  grid.appendChild(fragment);
  return end;
}

function setupInfiniteScroll(container) {
  if (scrollHandler) {
    window.removeEventListener("scroll", scrollHandler);
    scrollHandler = null;
  }
  const grid = container.querySelector(".tr-grid");
  if (!grid) return;

  scrollHandler = () => {
    if (renderedCount >= allTrainers.length) return;
    const scrollBottom = window.innerHeight + window.scrollY;
    const docHeight = document.documentElement.scrollHeight;
    if (scrollBottom >= docHeight - 400) {
      renderedCount = appendCards(grid, allTrainers, renderedCount, PAGE_SIZE);
    }
  };
  window.addEventListener("scroll", scrollHandler);
}

// ---------------------------------------------------------------------------
// Filtering
// ---------------------------------------------------------------------------

function applyFilters(trainers) {
  let result = trainers;

  // Custom/vanilla filter
  if (activeFilter === "custom") result = result.filter(t => t.is_custom);
  else if (activeFilter === "vanilla") result = result.filter(t => !t.is_custom);

  // Class filter
  if (classFilter) {
    result = result.filter(t => (t.class_const || "") === classFilter);
  }

  // Search
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    result = result.filter(t =>
      (t.name || "").toLowerCase().includes(q) ||
      (t.const || "").toLowerCase().includes(q) ||
      (t.class || "").toLowerCase().includes(q)
    );
  }

  return result;
}

function renderGrid(container, trainers) {
  const grid = container.querySelector(".tr-grid");
  const results = container.querySelector(".tr-results");

  allTrainers = trainers;
  renderedCount = 0;

  if (!trainers.length) {
    grid.innerHTML = `<div class="tr-empty">No trainers match your search</div>`;
    results.textContent = "0 trainers";
    return;
  }

  results.textContent = `${trainers.length} trainers`;
  grid.innerHTML = "";
  renderedCount = appendCards(grid, trainers, 0, PAGE_SIZE);
  setupInfiniteScroll(container);
}

function refreshList(container) {
  if (!cachedTrainers) return;
  const filtered = applyFilters(cachedTrainers);
  renderGrid(container, filtered);
}

// ---------------------------------------------------------------------------
// List view
// ---------------------------------------------------------------------------

async function renderList(container) {
  container.innerHTML = `<article>
    ${renderStudioNavbar("Trainers")}
    <div class="tr-layout">
      <aside class="tr-filters">
        <input type="text" class="tr-search" placeholder="Search by name, class, or ID...">
        <div class="tr-filter-group">
          <button class="tr-filter-pill active" data-filter="all">All</button>
          <button class="tr-filter-pill" data-filter="custom">Custom Only</button>
          <button class="tr-filter-pill" data-filter="vanilla">Vanilla Only</button>
        </div>
        <select class="tr-class-select">
          <option value="">All Classes</option>
        </select>
        <div class="tr-results"></div>
      </aside>
      <div class="tr-grid"></div>
    </div>
  </article>`;

  const grid = container.querySelector(".tr-grid");
  const searchInput = container.querySelector(".tr-search");
  const pills = container.querySelectorAll(".tr-filter-pill");
  const classSelect = container.querySelector(".tr-class-select");

  // Loading state
  grid.innerHTML = `<div class="tr-empty">Loading...</div>`;

  const res = await api("/trainers");
  if (!res.ok) {
    grid.innerHTML = `<div class="tr-empty">Error: ${esc(res.error)}</div>`;
    return;
  }

  // Format warning — legacy/vanilla projects return no trainers + a warning
  if (res.data.format_warning) {
    grid.innerHTML = `<div class="tr-format-warning">
      <h3>Legacy Trainer Format</h3>
      <p>${esc(res.data.format_warning)}</p>
      <p class="tr-format-hint">Use <code>torch trainers</code> in the terminal for legacy project editing.</p>
    </div>`;
    container.querySelector(".tr-results").textContent = "";
    return;
  }

  cachedTrainers = res.data.trainers || [];

  // Populate class dropdown
  const classSet = new Set();
  for (const t of cachedTrainers) {
    if (t.class_const) classSet.add(t.class_const);
  }
  const sorted = [...classSet].sort();
  for (const cc of sorted) {
    const name = cachedTrainers.find(t => t.class_const === cc)?.class || cc;
    const opt = document.createElement("option");
    opt.value = cc;
    opt.textContent = name;
    classSelect.appendChild(opt);
  }

  // Initial render
  refreshList(container);

  // Search
  searchInput.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      searchQuery = searchInput.value.trim();
      refreshList(container);
    }, 200);
  });

  // Filter pills
  pills.forEach(pill => {
    pill.addEventListener("click", () => {
      pills.forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      activeFilter = pill.dataset.filter;
      refreshList(container);
    });
  });

  // Class filter
  classSelect.addEventListener("change", () => {
    classFilter = classSelect.value;
    refreshList(container);
  });
}

// ---------------------------------------------------------------------------
// Detail view helpers
// ---------------------------------------------------------------------------

function formatEVs(evs) {
  if (!evs || typeof evs !== "object") return null;
  const parts = [];
  for (const key of STAT_KEYS) {
    const v = evs[key] || 0;
    if (v > 0) parts.push(`${v} ${STAT_LABELS[key]}`);
  }
  return parts.length ? parts.join(" / ") : null;
}

function formatIVs(ivs) {
  if (!ivs || typeof ivs !== "object") return null;
  const vals = STAT_KEYS.map(k => ivs[k] ?? 31);
  // All 31s is default -- don't show
  if (vals.every(v => v === 31)) return null;
  // All the same
  if (vals.every(v => v === vals[0])) return `${vals[0]} across all`;
  const parts = [];
  for (let i = 0; i < STAT_KEYS.length; i++) {
    if (vals[i] !== 31) parts.push(`${vals[i]} ${STAT_LABELS[STAT_KEYS[i]]}`);
  }
  return parts.join(" / ");
}

function renderEVBars(evs) {
  if (!evs || typeof evs !== "object") return "";
  const hasAny = STAT_KEYS.some(k => (evs[k] || 0) > 0);
  if (!hasAny) return "";

  const bars = STAT_KEYS.map(k => {
    const v = evs[k] || 0;
    const pct = Math.min(100, (v / 252) * 100);
    const col = STAT_COLOURS[k];
    return `<div class="tr-ev-segment" title="${STAT_LABELS[k]}: ${v}" style="width:${pct}%;background:${col}"></div>`;
  }).join("");

  return `<div class="tr-ev-bar">${bars}</div>`;
}

// ---------------------------------------------------------------------------
// Party row — view mode (full-width horizontal rows with type gradients)
// ---------------------------------------------------------------------------

/** Render a single move slot for the view-mode party row. */
function renderMoveSlotView(mv) {
  if (!mv) {
    return `<div class="tr-move-row-view"><span class="tr-move-dot" style="background:#333"></span><span class="tr-move-name tr-dim" style="font-style:italic">\u2014</span></div>`;
  }
  const mvType = mv.type || "Normal";
  const dotCol = PICKER_TYPE_COLOURS[mvType] || TYPE_GRADIENTS[mvType]?.accent || "#888";
  const mvName = mv.name || mv.const || "---";
  const power = (mv.power != null && mv.power !== 0) ? mv.power : "\u2014";
  const accuracy = (mv.accuracy != null && mv.accuracy !== 0) ? `${mv.accuracy}%` : "\u2014";
  const cat = (mv.category || "").toLowerCase();
  let catIcon = "\u25C8";
  let catClass = "tr-move-status";
  if (cat === "physical") { catIcon = "\u2694"; catClass = "tr-move-physical"; }
  else if (cat === "special") { catIcon = "\u2726"; catClass = "tr-move-special"; }
  return `<div class="tr-move-row-view"><span class="tr-move-dot" style="background:${dotCol}"></span><span class="tr-move-name">${esc(mvName)}</span><span class="tr-move-stats">${power} <span class="tr-move-label">pow</span> &middot; ${accuracy} <span class="tr-move-label">acc</span> <span class="tr-move-cat ${catClass}">${catIcon}</span></span></div>`;
}

/** Render the 4 move slots for a party row (auto, filled, or empty). */
function renderMovesColView(mon) {
  const moves = mon.moves || [];
  if (moves.length === 0) {
    const auto = `<div class="tr-move-row-view"><span class="tr-move-dot" style="background:#888"></span><span class="tr-move-name tr-auto-moves">Auto</span></div>`;
    return auto + auto + auto + auto;
  }
  let html = "";
  for (let i = 0; i < 4; i++) {
    html += renderMoveSlotView((i < moves.length) ? moves[i] : null);
  }
  return html;
}

/** Render the identity column content for a view-mode party row. */
function renderIdentityCol(mon) {
  const types = mon.types || [];
  const typeBadges = types.map(t => {
    const col = PICKER_TYPE_COLOURS[t] || "#888";
    return `<span class="type-badge" style="background:${col}">${t}</span>`;
  }).join("");

  let natureDisplay = "";
  if (mon.nature_name) {
    const isNeutral = NEUTRAL_NATURES.has(mon.nature);
    const natureEntry = refData?.natures?.find(n => n.const === mon.nature);
    const modifiers = (!isNeutral && natureEntry && natureEntry.plus)
      ? ` <span class="tr-dim">(+${natureEntry.plus} -${natureEntry.minus})</span>` : "";
    natureDisplay = `${esc(mon.nature_name)}${modifiers}`;
  }

  const abilityText = (mon.ability_name && mon.ability !== "ABILITY_NONE") ? esc(mon.ability_name) : "";
  const abilityNature = [abilityText, natureDisplay].filter(Boolean).join(" &middot; ");

  const heldItemHtml = (mon.held_item_name && mon.held_item !== "ITEM_NONE")
    ? `<div class="tr-mon-row-item"><img class="tr-item-icon" src="/api/items/icons/${mon.held_item}" alt="" onerror="this.style.display='none'" style="width:24px;height:24px"> ${esc(mon.held_item_name)}</div>` : "";

  const evBarHtml = renderEVBars(mon.evs);

  const ballHtml = (mon.ball && mon.ball !== "ITEM_POKE_BALL" && mon.ball !== "BALL_POKE")
    ? `<div class="tr-mon-row-ball"><img class="tr-item-icon" src="${getBallIconUrl(mon.ball)}" alt="" onerror="this.style.display='none'" style="width:24px;height:24px"> ${mon.ball.replace(/^(ITEM_|BALL_)/, "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}</div>` : "";

  return `<div class="tr-mon-name-row">
      <span class="tr-mon-species">${esc(mon.species_name || "???")}</span>
      <span class="tr-mon-level">Lv. ${mon.level || "?"}</span>
    </div>
    <div class="tr-mon-types">${typeBadges}</div>
    ${abilityNature ? `<div class="tr-mon-ability-nature">${abilityNature}</div>` : ""}
    ${heldItemHtml}${evBarHtml}${ballHtml}`;
}

/** Render the meta column (nickname, gender, shiny indicators). */
function renderMetaCol(mon) {
  let html = "";
  if (mon.nickname) html += `<span class="tr-mon-row-nickname">${esc(mon.nickname)}</span>`;
  if (mon.gender === "MON_MALE") html += `<span class="tr-gender-m" title="Male">&#9794;</span>`;
  else if (mon.gender === "MON_FEMALE") html += `<span class="tr-gender-f" title="Female">&#9792;</span>`;
  if (mon.shiny) html += `<span class="tr-mon-row-shiny" title="Shiny">&#10022;</span>`;
  return html;
}

/** Render sprite overlays (shiny star, gender symbol). */
function renderSpriteOverlays(mon) {
  let html = "";
  if (mon.shiny) html += `<span class="tr-mon-row-shiny-overlay" title="Shiny">&#10022;</span>`;
  if (mon.gender === "MON_MALE") html += `<span class="tr-mon-row-gender-overlay tr-gender-m">&#9794;</span>`;
  else if (mon.gender === "MON_FEMALE") html += `<span class="tr-mon-row-gender-overlay tr-gender-f">&#9792;</span>`;
  return html;
}

/** Set up hover/click sprite animation on view-mode party rows. */
function wirePartyRowAnimations(container) {
  container.querySelectorAll(".tr-mon-row").forEach(row => {
    const img = row.querySelector(".tr-mon-sprite-lg");
    if (!img) return;
    const rawUrl = img.dataset.spriteUrl;
    if (!rawUrl || rawUrl.startsWith("data:")) return;

    // Pre-fetch both frames in background
    processSpriteFrames(rawUrl).then(frames => {
      if (!frames || !frames.frame2) return;
      img.dataset.frame1 = frames.frame1;
      img.dataset.frame2 = frames.frame2;
    });

    let hoverTimeouts = [];
    function playAnimation() {
      if (!img.dataset.frame2) return;
      const f1 = img.dataset.frame1;
      const f2 = img.dataset.frame2;
      const pattern = Math.floor(Math.random() * 3);
      if (pattern === 0) {
        hoverTimeouts.push(setTimeout(() => { img.src = f2; }, 80));
        hoverTimeouts.push(setTimeout(() => { img.src = f1; }, 230));
      } else if (pattern === 1) {
        hoverTimeouts.push(setTimeout(() => { img.src = f2; }, 120));
        hoverTimeouts.push(setTimeout(() => { img.src = f1; }, 240));
        hoverTimeouts.push(setTimeout(() => { img.src = f2; }, 340));
        hoverTimeouts.push(setTimeout(() => { img.src = f1; }, 460));
      } else {
        hoverTimeouts.push(setTimeout(() => { img.src = f2; }, 60));
        hoverTimeouts.push(setTimeout(() => { img.src = f1; }, 410));
      }
    }

    row.addEventListener("mouseenter", playAnimation);
    row.addEventListener("click", playAnimation);
    row.addEventListener("mouseleave", () => {
      hoverTimeouts.forEach(clearTimeout);
      hoverTimeouts = [];
      if (img.dataset.frame1) img.src = img.dataset.frame1;
    });
  });
}

/**
 * Fetch species types for party members and update row gradients.
 * Fallback for when types aren't included in the API response.
 * If mon.types is already populated (server-side), this is a no-op.
 */
async function enrichPartyRowTypes(container, party) {
  if (!party.length) return;
  const rows = container.querySelectorAll(".tr-mon-row");
  if (!rows.length) return;

  // Deduplicate species to minimize API calls; skip if types already present
  const speciesSet = new Map(); // species_const -> [indices]
  party.forEach((mon, i) => {
    const sp = mon.species;
    if (!sp || (mon.types && mon.types.length)) return;
    if (!speciesSet.has(sp)) speciesSet.set(sp, []);
    speciesSet.get(sp).push(i);
  });
  if (!speciesSet.size) return;

  const fetches = [...speciesSet.entries()].map(async ([sp, indices]) => {
    try {
      const res = await api(`/species/${sp}`);
      if (!res.ok || !res.data || !res.data.types) return;
      const types = res.data.types;
      for (const idx of indices) {
        party[idx].types = types;
        updateRowGradient(rows[idx], types);
      }
    } catch (_) {}
  });

  await Promise.all(fetches);
}

/** Update a party row's gradient and border based on fetched types. */
function updateRowGradient(row, types) {
  if (!row) return;
  const primaryType = types[0] || "Normal";
  const secondaryType = types[1] || null;
  const grad = TYPE_GRADIENTS[primaryType] || TYPE_GRADIENTS.Normal;
  const grad2 = secondaryType ? (TYPE_GRADIENTS[secondaryType] || TYPE_GRADIENTS.Normal) : null;

  row.style.borderLeftColor = grad.accent;
  row.style.background = grad2
    ? `linear-gradient(135deg, ${hexToRgba(grad.deep, 0.12)} 0%, ${hexToRgba(grad.deep, 0.06)} 35%, ${hexToRgba(grad2.deep, 0.06)} 65%, ${hexToRgba(grad2.deep, 0.12)} 100%)`
    : `linear-gradient(135deg, ${hexToRgba(grad.deep, 0.07)} 0%, transparent 60%)`;

  // Update type badges in the identity column
  const typesDiv = row.querySelector(".tr-mon-types");
  if (typesDiv) {
    typesDiv.innerHTML = types.map(t => {
      const col = PICKER_TYPE_COLOURS[t] || "#888";
      return `<span class="type-badge" style="background:${col}">${t}</span>`;
    }).join("");
  }
}

/** Render a full-width horizontal party row (view mode). */
function renderMonRow(mon) {
  const spriteSrc = mon.sprite_path
    ? `/api/sprites/${mon.sprite_path}${mon.shiny ? "?shiny=1" : ""}`
    : PLACEHOLDER_SVG;

  const types = mon.types || [];
  const primaryType = types[0] || "Normal";
  const secondaryType = types[1] || null;
  const grad = TYPE_GRADIENTS[primaryType] || TYPE_GRADIENTS.Normal;
  const grad2 = secondaryType ? (TYPE_GRADIENTS[secondaryType] || TYPE_GRADIENTS.Normal) : null;

  const bgGradient = grad2
    ? `linear-gradient(135deg, ${hexToRgba(grad.deep, 0.12)} 0%, ${hexToRgba(grad.deep, 0.06)} 35%, ${hexToRgba(grad2.deep, 0.06)} 65%, ${hexToRgba(grad2.deep, 0.12)} 100%)`
    : `linear-gradient(135deg, ${hexToRgba(grad.deep, 0.07)} 0%, transparent 60%)`;

  return `<div class="tr-mon-row" style="border-left-color:${grad.accent};background:${bgGradient}">
    <div class="tr-mon-sprite-col">
      <img class="tr-mon-sprite-lg tr-mon-sprite" data-sprite-url="${spriteSrc}" src="${spriteSrc}" alt="${mon.species_name || "?"}" onerror="this.src='${ERROR_SVG}'">
      ${renderSpriteOverlays(mon)}
    </div>
    <div class="tr-mon-identity-col">${renderIdentityCol(mon)}</div>
    <div class="tr-mon-moves-col">${renderMovesColView(mon)}</div>
    <div class="tr-mon-meta-col">${renderMetaCol(mon)}</div>
  </div>`;
}

// ---------------------------------------------------------------------------
// Modal picker (reusable for species, moves, items, abilities, natures)
// ---------------------------------------------------------------------------

// Track active picker's document keydown handler for cleanup
let _activePickerKeyHandler = null;

function closeAllPickers() {
  if (_activePickerKeyHandler) {
    document.removeEventListener("keydown", _activePickerKeyHandler, true);
    _activePickerKeyHandler = null;
  }
  document.querySelectorAll(".tr-picker-overlay").forEach(p => p.remove());
}

// Type colours for badges (shared with Dex)
const PICKER_TYPE_COLOURS = {
  Normal: "#A8A878", Fire: "#F08030", Water: "#6890F0", Electric: "#F8D030",
  Grass: "#78C850", Ice: "#98D8D8", Fighting: "#C03028", Poison: "#A040A0",
  Ground: "#E0C068", Flying: "#A890F0", Psychic: "#F85888", Bug: "#A8B820",
  Rock: "#B8A038", Ghost: "#705898", Dragon: "#7038F8", Dark: "#705848",
  Steel: "#B8B8D0", Fairy: "#EE99AC",
};
const PICKER_ALL_TYPES = Object.keys(PICKER_TYPE_COLOURS);

// Type gradient system — deep/light/accent per type for party row backgrounds
const TYPE_GRADIENTS = {
  Normal:   { deep: "#8a8a6c", light: "#c6c6a7", accent: "#A8A878" },
  Fire:     { deep: "#c4501a", light: "#f5ac78", accent: "#F08030" },
  Water:    { deep: "#4a6fc4", light: "#9db7f5", accent: "#6890F0" },
  Electric: { deep: "#c4a800", light: "#fae078", accent: "#F8D030" },
  Grass:    { deep: "#5a9830", light: "#a7db8d", accent: "#78C850" },
  Ice:      { deep: "#72b8b8", light: "#bce0e0", accent: "#98D8D8" },
  Fighting: { deep: "#9c2020", light: "#d67873", accent: "#C03028" },
  Poison:   { deep: "#803080", light: "#c183c1", accent: "#A040A0" },
  Ground:   { deep: "#b8982e", light: "#ebd69d", accent: "#E0C068" },
  Flying:   { deep: "#8868d0", light: "#c6b7f5", accent: "#A890F0" },
  Psychic:  { deep: "#d03868", light: "#fa92b2", accent: "#F85888" },
  Bug:      { deep: "#889810", light: "#c6d16e", accent: "#A8B820" },
  Rock:     { deep: "#968828", light: "#d1c17d", accent: "#B8A038" },
  Ghost:    { deep: "#584070", light: "#a292bc", accent: "#705898" },
  Dragon:   { deep: "#5028c8", light: "#a27dfa", accent: "#7038F8" },
  Dark:     { deep: "#584038", light: "#a29288", accent: "#705848" },
  Steel:    { deep: "#9898b8", light: "#d1d1e0", accent: "#B8B8D0" },
  Fairy:    { deep: "#c87098", light: "#f4bdc9", accent: "#EE99AC" },
};

/** Convert hex colour to rgba string. */
function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// Nature stat modifier lookup for view mode display
const NATURE_STAT_NAMES = { Atk: "Atk", Def: "Def", SpA: "SpA", SpD: "SpD", Spe: "Spe" };
const NEUTRAL_NATURES = new Set([
  "NATURE_HARDY", "NATURE_DOCILE", "NATURE_SERIOUS", "NATURE_BASHFUL", "NATURE_QUIRKY",
]);

function createPicker(anchor, searchFn, onSelect, opts = {}) {
  closeAllPickers();

  // Build modal overlay
  const overlay = document.createElement("div");
  overlay.className = "tr-picker-overlay";

  const modal = document.createElement("div");
  modal.className = "tr-picker-modal";

  // Header with search + close
  const header = document.createElement("div");
  header.className = "tr-picker-header";
  header.innerHTML = `
    <input type="text" class="tr-picker-input" placeholder="Search..." autocomplete="off" spellcheck="false">
    <button class="tr-picker-close" title="Close">&times;</button>
  `;
  modal.appendChild(header);

  // Type filter bar (hidden initially, shown when results have sprites = species mode)
  const typeBar = document.createElement("div");
  typeBar.className = "tr-picker-type-bar";
  typeBar.style.display = "none";
  let activeType = null;

  // Build type filter buttons
  for (const t of PICKER_ALL_TYPES) {
    const btn = document.createElement("button");
    btn.className = "tr-picker-type-btn";
    btn.textContent = t;
    btn.style.background = PICKER_TYPE_COLOURS[t];
    btn.dataset.type = t;
    btn.addEventListener("click", () => {
      if (activeType === t) {
        // Deselect
        activeType = null;
        typeBar.querySelectorAll(".tr-picker-type-btn").forEach(b => b.classList.remove("active"));
      } else {
        activeType = t;
        typeBar.querySelectorAll(".tr-picker-type-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
      }
      triggerSearch();
    });
    typeBar.appendChild(btn);
  }
  modal.appendChild(typeBar);

  // Results count
  const countBar = document.createElement("div");
  countBar.className = "tr-picker-count";
  modal.appendChild(countBar);

  // Results grid/list container
  const results = document.createElement("div");
  results.className = "tr-picker-results";
  modal.appendChild(results);

  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  const input = modal.querySelector(".tr-picker-input");
  const closeBtn = modal.querySelector(".tr-picker-close");
  let searchTimer = null;
  let isSpeciesMode = false; // auto-detected from first results batch

  // Move table filter/sort state
  const moveFilters = { type: null, category: null, learnable: !!opts.speciesConst, learnMethod: null };
  const moveSort = { col: null, dir: "asc" }; // col: "name"|"power"|"accuracy"|"pp", dir: "asc"|"desc"
  const LEARN_METHODS = ["lvl", "egg", "tm"];
  let learnableData = null; // { set, levels, tms, eggs }

  // Fetch learnable moves in background if species provided
  if (opts.speciesConst) {
    getLearnableMoves(opts.speciesConst).then(data => {
      learnableData = data;
      triggerSearch();
    });
  }

  function closePicker() {
    document.removeEventListener("keydown", keyHandler, true);
    if (_activePickerKeyHandler === keyHandler) _activePickerKeyHandler = null;
    overlay.remove();
  }

  // Escape key closes
  function keyHandler(e) {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      closePicker();
    }
  }
  _activePickerKeyHandler = keyHandler;
  document.addEventListener("keydown", keyHandler, true);

  // Close button
  closeBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    closePicker();
  });

  // Click on overlay backdrop closes
  overlay.addEventListener("mousedown", (e) => {
    if (e.target === overlay) closePicker();
  });

  // Render results
  async function doSearch(q) {
    results.innerHTML = `<div class="tr-picker-loading">Searching...</div>`;

    let items;
    if (activeType && isSpeciesMode) {
      // Two-phase: filter by type server-side, then filter client-side
      const isSpecialQuery = q && /^(bst|stat:|.*[><]=?)/.test(q.trim());
      if (isSpecialQuery) {
        const [typeItems, queryItems] = await Promise.all([
          searchFn(`type:${activeType.toLowerCase()}`),
          searchFn(q),
        ]);
        const querySet = new Set(queryItems.map(it => it.const));
        items = typeItems.filter(it => querySet.has(it.const));
      } else if (q) {
        const typeItems = await searchFn(`type:${activeType.toLowerCase()}`);
        const lq = q.toLowerCase();
        items = typeItems.filter(it => it.name.toLowerCase().includes(lq)
          || it.const.toLowerCase().includes(lq));
      } else {
        items = await searchFn(`type:${activeType.toLowerCase()}`);
      }
    } else {
      items = await searchFn(q);
    }

    // Auto-detect species mode from first batch (items with sprites)
    if (!isSpeciesMode && items.length > 0 && items[0].sprite) {
      isSpeciesMode = true;
      typeBar.style.display = "flex";
      results.classList.add("tr-picker-grid");
    }

    results.innerHTML = "";
    if (!items.length) {
      results.innerHTML = `<div class="tr-picker-empty">No results found</div>`;
      countBar.textContent = "0 results";
      return;
    }

    const maxDisplay = isSpeciesMode ? 150 : 0;
    const display = maxDisplay ? items.slice(0, maxDisplay) : items;
    countBar.textContent = maxDisplay && items.length > maxDisplay
      ? `Showing ${maxDisplay} of ${items.length} results`
      : `${items.length} result${items.length === 1 ? "" : "s"}`;

    if (isSpeciesMode) {
      // Grid of species cards with sprites
      for (const item of display) {
        const card = document.createElement("div");
        card.className = "tr-picker-species-card";

        // Type-coloured top border
        const primaryType = (item.types && item.types[0]) || "Normal";
        const typeCol = PICKER_TYPE_COLOURS[primaryType] || "#888";
        card.style.borderTopColor = typeCol;

        // Sprite
        const img = document.createElement("img");
        img.className = "tr-picker-sprite";
        img.alt = item.name;
        img.loading = "lazy";
        if (item.sprite) {
          // Use processSprite for background removal and frame clipping
          img.src = PLACEHOLDER_SVG;
          import("../spriteUtils.js").then(({ processSprite }) => {
            processSprite(item.sprite).then(dataUrl => { img.src = dataUrl; });
          }).catch(() => { img.src = item.sprite; });
        } else {
          img.src = PLACEHOLDER_SVG;
        }

        // Name
        const nameEl = document.createElement("div");
        nameEl.className = "tr-picker-species-name";
        nameEl.textContent = item.name;

        // Type badges
        const typesEl = document.createElement("div");
        typesEl.className = "tr-picker-species-types";
        for (const t of (item.types || [])) {
          const badge = document.createElement("span");
          badge.className = "type-badge";
          badge.style.background = PICKER_TYPE_COLOURS[t] || "#888";
          badge.textContent = t;
          typesEl.appendChild(badge);
        }

        card.appendChild(img);
        card.appendChild(nameEl);
        card.appendChild(typesEl);

        card.addEventListener("mouseenter", () => { card.style.borderColor = typeCol; });
        card.addEventListener("mouseleave", () => {
          card.style.borderColor = "";
          card.style.borderTopColor = typeCol;
        });
        card.addEventListener("click", (e) => {
          e.stopPropagation();
          onSelect(item);
          closePicker();
        });
        results.appendChild(card);
      }
    } else {
      // List mode for moves, items, abilities, natures
      results.classList.remove("tr-picker-grid");
      // Detect move items (have type + category fields)
      const isMoveMode = display.length > 0 && display[0].type && display[0].category;

      // Apply move filters
      let filtered = display;
      if (isMoveMode) {
        if (moveFilters.learnable && learnableData && learnableData.set.size > 0) {
          filtered = filtered.filter(m => learnableData.set.has(m.const));
        }
        if (moveFilters.type) filtered = filtered.filter(m => m.type === moveFilters.type);
        if (moveFilters.category) filtered = filtered.filter(m => m.category === moveFilters.category);

        // Annotate with learn level for display + sorting
        if (learnableData) {
          filtered = filtered.map(m => {
            const lvl = learnableData.levels.get(m.const);
            const isTM = learnableData.tms.has(m.const);
            const isEgg = learnableData.eggs.has(m.const);
            return { ...m, _learnLevel: lvl != null ? lvl : (isTM ? -1 : (isEgg ? -2 : -3)) };
          });
        }

        // Learn method filter (cycle: lvl -> egg -> tm -> off)
        if (moveFilters.learnMethod && learnableData) {
          if (moveFilters.learnMethod === "lvl") {
            filtered = filtered.filter(m => learnableData.levels.has(m.const));
          } else if (moveFilters.learnMethod === "egg") {
            filtered = filtered.filter(m => learnableData.eggs.has(m.const));
          } else if (moveFilters.learnMethod === "tm") {
            filtered = filtered.filter(m => learnableData.tms.has(m.const));
          }
          // Sort by learn level ascending when filtering by level-up
          if (moveFilters.learnMethod === "lvl") {
            filtered = [...filtered].sort((a, b) => {
              const al = learnableData.levels.get(a.const) || 999;
              const bl = learnableData.levels.get(b.const) || 999;
              return al - bl;
            });
          }
        }

        if (moveSort.col) {
          const col = moveSort.col;
          const dir = moveSort.dir === "asc" ? 1 : -1;
          filtered = [...filtered].sort((a, b) => {
            if (col === "name") return dir * a.name.localeCompare(b.name);
            const av = (a[col] != null ? a[col] : -1);
            const bv = (b[col] != null ? b[col] : -1);
            return dir * (av - bv);
          });
        }
        // Update count after filtering
        countBar.textContent = `${filtered.length} result${filtered.length === 1 ? "" : "s"}`;
      }

      const ALL_TYPES = Object.keys(PICKER_TYPE_COLOURS);
      const ALL_CATS = ["Physical", "Special", "Status"];

      if (isMoveMode) {
        // Build interactive header
        const header = document.createElement("div");
        header.className = "tr-picker-move-header";

        function sortArrow(col) {
          if (moveSort.col !== col) return "";
          return moveSort.dir === "asc" ? " \u25B2" : " \u25BC";
        }

        function makeSort(span, col) {
          span.classList.add("tr-pmh-sortable");
          if (moveSort.col === col) span.classList.add("tr-pmh-active");
          span.addEventListener("click", () => {
            if (moveSort.col === col) {
              moveSort.dir = moveSort.dir === "asc" ? "desc" : "asc";
            } else {
              moveSort.col = col;
              moveSort.dir = "asc";
            }
            triggerSearch();
          });
        }

        function makeCycle(span, key, values, labelFn) {
          if (moveFilters[key]) span.classList.add("tr-pmh-active");
          span.addEventListener("click", () => {
            const idx = moveFilters[key] ? values.indexOf(moveFilters[key]) : -1;
            moveFilters[key] = idx < values.length - 1 ? values[idx + 1] : null;
            triggerSearch();
          });
        }

        const hName = document.createElement("span");
        hName.className = "tr-pmh-name tr-pmh-sortable";
        hName.textContent = "Name" + sortArrow("name");
        makeSort(hName, "name");

        const hLvl = document.createElement("span");
        hLvl.className = "tr-pmh-lvl tr-pmh-sortable";
        if (moveFilters.learnMethod) {
          hLvl.classList.add("tr-pmh-active");
          hLvl.textContent = moveFilters.learnMethod === "lvl" ? "LVL" :
                             moveFilters.learnMethod === "egg" ? "Egg" : "TM";
        } else {
          hLvl.textContent = "Lvl";
        }
        hLvl.style.cursor = "pointer";
        hLvl.addEventListener("click", () => {
          const idx = moveFilters.learnMethod ? LEARN_METHODS.indexOf(moveFilters.learnMethod) : -1;
          moveFilters.learnMethod = idx < LEARN_METHODS.length - 1 ? LEARN_METHODS[idx + 1] : null;
          triggerSearch();
        });

        const hType = document.createElement("span");
        hType.className = "tr-pmh-type";
        if (moveFilters.type) {
          hType.innerHTML = `<span class="type-badge" style="background:${PICKER_TYPE_COLOURS[moveFilters.type] || "#888"};font-size:0.55rem">${moveFilters.type}</span>`;
        } else {
          hType.textContent = "Type";
        }
        makeCycle(hType, "type", ALL_TYPES);

        const hCat = document.createElement("span");
        hCat.className = "tr-pmh-cat";
        if (moveFilters.category) {
          const cc = moveFilters.category.toLowerCase();
          const catImg = document.createElement("img");
          catImg.className = "tr-pm-cat-img";
          catImg.alt = moveFilters.category;
          catImg.style.cssText = "width:16px;height:16px;image-rendering:pixelated;vertical-align:middle";
          getCategoryIconDataUrl(cc).then(url => { catImg.src = url; });
          hCat.appendChild(catImg);
        } else {
          hCat.textContent = "Cat.";
        }
        makeCycle(hCat, "category", ALL_CATS);

        const hPwr = document.createElement("span");
        hPwr.className = "tr-pmh-num";
        hPwr.textContent = "Pwr" + sortArrow("power");
        makeSort(hPwr, "power");

        const hAcc = document.createElement("span");
        hAcc.className = "tr-pmh-num";
        hAcc.textContent = "Acc" + sortArrow("accuracy");
        makeSort(hAcc, "accuracy");

        const hPP = document.createElement("span");
        hPP.className = "tr-pmh-num";
        hPP.textContent = "PP" + sortArrow("pp");
        makeSort(hPP, "pp");

        const hDesc = document.createElement("span");
        hDesc.className = "tr-pmh-desc";
        hDesc.textContent = "Effect";

        header.append(hName, hLvl, hType, hCat, hPwr, hAcc, hPP, hDesc);

        // Learnable toggle (only if species context provided)
        if (opts.speciesConst) {
          const filterBar = document.createElement("div");
          filterBar.className = "tr-picker-filter-bar";

          // Species + level context label
          const speciesName = opts.speciesName || opts.speciesConst.replace("SPECIES_", "").replace(/_/g, " ");
          const lvlLabel = opts.level ? ` (Lv. ${opts.level})` : "";
          const ctxLabel = document.createElement("span");
          ctxLabel.className = "tr-picker-ctx-label";
          ctxLabel.textContent = `Moves for ${speciesName}${lvlLabel}`;
          filterBar.appendChild(ctxLabel);

          const learnBtn = document.createElement("button");
          learnBtn.className = "tr-learnable-toggle";
          if (moveFilters.learnable) learnBtn.classList.add("tr-learnable-active");
          learnBtn.textContent = moveFilters.learnable ? "Learnable" : "All Moves";
          if (moveFilters.learnable && !learnableData) {
            learnBtn.textContent = "Learnable...";
          }
          learnBtn.title = "Toggle between learnable moves and all moves";
          learnBtn.addEventListener("click", () => {
            moveFilters.learnable = !moveFilters.learnable;
            triggerSearch();
          });
          filterBar.appendChild(learnBtn);
          results.appendChild(filterBar);
        }

        results.appendChild(header);
      }

      for (const item of filtered) {
        const row = document.createElement("div");
        if (isMoveMode) {
          row.className = "tr-picker-move-row";
          const typeColor = PICKER_TYPE_COLOURS[item.type] || "#888";
          const catCls = (item.category || "").toLowerCase();
          const pwr = item.power != null && item.power !== 0 ? item.power : "\u2014";
          const acc = item.accuracy != null && item.accuracy !== 0 ? item.accuracy : "\u2014";
          const pp = item.pp != null && item.pp !== 0 ? item.pp : "\u2014";
          // Level column: show learn level, TM, Egg, or dash
          let lvlText = "\u2014";
          if (item._learnLevel != null) {
            if (item._learnLevel >= 0) lvlText = String(item._learnLevel);
            else if (item._learnLevel === -1) lvlText = "TM";
            else if (item._learnLevel === -2) lvlText = "Egg";
          }
          row.innerHTML = `<span class="tr-pm-name">${esc(item.name)}</span><span class="tr-pm-lvl">${lvlText}</span><span class="tr-pm-type"><span class="type-badge" style="background:${typeColor}">${esc(item.type)}</span></span><span class="tr-pm-cat" title="${esc(item.category)}"><img class="tr-pm-cat-img" data-category="${catCls}" alt="${esc(item.category)}" style="width:20px;height:20px;image-rendering:pixelated;vertical-align:middle"></span><span class="tr-pm-num">${pwr}</span><span class="tr-pm-num">${acc}</span><span class="tr-pm-num">${pp}</span><span class="tr-pm-desc">${esc(item.description || "")}</span>`;
        } else {
          row.className = "tr-picker-list-item";
          if (item.icon) {
            const iconImg = document.createElement("img");
            iconImg.className = "tr-item-icon";
            iconImg.alt = "";
            iconImg.src = item.icon;
            processSprite(item.icon).then(dataUrl => { iconImg.src = dataUrl; });
            row.appendChild(iconImg);
            row.appendChild(document.createTextNode(" " + item.name));
          } else {
            row.textContent = item.name;
          }
        }
        row.addEventListener("click", (e) => {
          e.stopPropagation();
          onSelect(item);
          closePicker();
        });
        results.appendChild(row);
      }
      // Process category icon backgrounds (per-icon bg removal)
      if (isMoveMode) processCategoryIcons(results);
    }
  }

  function triggerSearch() {
    clearTimeout(searchTimer);
    doSearch(input.value.trim());
  }

  input.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => triggerSearch(), 150);
  });

  // Initial results
  doSearch("");

  // Focus search input after a tick (ensures modal is rendered)
  requestAnimationFrame(() => input.focus());

  return overlay;
}

// ---------------------------------------------------------------------------
// Search helpers for pickers
// ---------------------------------------------------------------------------

async function searchSpecies(q) {
  const res = await api(`/species?q=${encodeURIComponent(q || "")}`);
  if (!res.ok) return [];
  const list = Array.isArray(res.data) ? res.data : [];
  return list.map(s => ({
    const: s.const,
    name: s.name || s.const.replace("SPECIES_", "").replace(/_/g, " "),
    sprite: s.sprite_path ? `/api/sprites/${s.sprite_path}` : null,
    types: s.types || [],
  }));
}

async function searchMoves(q) {
  if (!cachedMoves) {
    const res = await api("/moves");
    cachedMoves = res.ok ? res.data : [];
  }
  if (!q) return cachedMoves;
  const lq = q.toLowerCase();
  return cachedMoves.filter(m =>
    m.name.toLowerCase().includes(lq) ||
    m.const.toLowerCase().includes(lq) ||
    (m.type || "").toLowerCase().includes(lq)
  );
}

async function searchItems(q) {
  if (!cachedItems) {
    const res = await api("/items?holdable=1");
    cachedItems = res.ok ? res.data : [];
  }
  if (!q) return cachedItems;
  const lq = q.toLowerCase();
  return cachedItems.filter(i => i.name.toLowerCase().includes(lq) || i.const.toLowerCase().includes(lq));
}

// ---------------------------------------------------------------------------
// Search helpers for all-items picker (trainer battle items — not holdable-only)
// ---------------------------------------------------------------------------

let cachedAllItems = null;
async function searchAllItems(q) {
  if (!cachedAllItems) {
    const res = await api("/items");
    cachedAllItems = res.ok ? res.data : [];
  }
  if (!q) return cachedAllItems;
  const lq = q.toLowerCase();
  return cachedAllItems.filter(i => i.name.toLowerCase().includes(lq) || i.const.toLowerCase().includes(lq));
}

// ---------------------------------------------------------------------------
// Edit mode: mon row (full-width horizontal, matches view-mode layout)
// ---------------------------------------------------------------------------

/** Build nature display text from mon data. */
function getNatureDisplay(mon) {
  const name = mon.nature
    ? (refData?.natures?.find(n => n.const === mon.nature)?.name || mon.nature.replace("NATURE_", ""))
    : "Hardy";
  const entry = refData?.natures?.find(n => n.const === mon.nature);
  const detail = (entry && entry.plus) ? ` (+${entry.plus} -${entry.minus})` : "";
  return { name, detail };
}

/** Get ball icon URL from a ball constant. */
function getBallIconUrl(ballConst) {
  if (!ballConst) return "/api/items/icons/ITEM_POKE_BALL";
  if (ballConst.startsWith("BALL_")) {
    return `/api/items/icons/ITEM_${ballConst.slice(5)}_BALL`;
  }
  return `/api/items/icons/${ballConst}`;
}

/** Build ball display name from mon data. */
function getBallDisplay(mon) {
  if (mon.ball && mon.ball !== "ITEM_POKE_BALL" && mon.ball !== "BALL_POKE") {
    return mon.ball.replace(/^(ITEM_|BALL_)/, "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  }
  return "Poke Ball";
}

/** Build the edit-mode identity column HTML. */
function buildEditIdentityCol(mon) {
  const types = mon.types || [];
  const typeBadges = types.map(t => {
    const col = PICKER_TYPE_COLOURS[t] || "#888";
    return `<span class="type-badge" style="background:${col}">${t}</span>`;
  }).join("");

  const { name: natureName, detail: natureDetail } = getNatureDisplay(mon);
  const heldItemIcon = (mon.held_item && mon.held_item !== "ITEM_NONE")
    ? `<img class="tr-item-icon" src="/api/items/icons/${mon.held_item}" alt="" onerror="this.style.display='none'" style="width:20px;height:20px">` : "";
  const ballDisplay = getBallDisplay(mon);
  const ballIconHtml = `<img class="tr-item-icon" src="${getBallIconUrl(mon.ball)}" alt="" onerror="this.style.display='none'" style="width:20px;height:20px">`;
  const evs = mon.evs || {};
  const evTotal = STAT_KEYS.reduce((sum, k) => sum + (evs[k] || 0), 0);

  return `<div class="tr-mon-name-row">
        <span class="tr-mon-species tr-edit-species-btn" style="cursor:pointer">${esc(mon.species_name || "???")}</span>
        <span class="tr-mon-level">Lv.</span>
        <input type="number" class="tr-level-input" value="${mon.level || 5}" min="1" max="100">
        <input type="text" class="tr-nickname-input" value="${esc(mon.nickname || "")}" maxlength="10" placeholder="Nickname...">
      </div>
      <div class="tr-mon-types">${typeBadges}</div>
      <div class="tr-mon-ability-nature">
        <span class="tr-mon-ability-text">${(mon.ability_name && mon.ability !== "ABILITY_NONE") ? esc(mon.ability_name) : '<span class="tr-dim" style="font-style:italic">Ability\u2026</span>'}</span>
        <span class="tr-dim"> &middot; </span>
        <span class="tr-mon-nature-text">${esc(natureName)}${esc(natureDetail)}</span>
      </div>
      <div class="tr-mon-row-item">
        ${heldItemIcon}
        <span class="tr-mon-item-text">${esc(mon.held_item_name || "None")}</span>
      </div>
      <div class="tr-mon-row-ball-edit">
        <span class="tr-dim">Ball: </span>${ballIconHtml}<span class="tr-mon-ball-text">${esc(ballDisplay)}</span>
      </div>
      <div class="tr-mon-detail-row tr-edit-ev-toggle" style="cursor:pointer">
        <span class="tr-dim">EVs:</span> <span class="tr-ev-toggle-text">${evTotal}/510</span>
      </div>
      ${renderEditEVBlock(mon, "evs", 255, 510)}
      <div class="tr-mon-detail-row tr-edit-iv-toggle" style="cursor:pointer">
        <span class="tr-dim">IVs:</span> <span>Click to edit</span>
      </div>
      ${renderEditEVBlock(mon, "ivs", 31, null)}`;
}

/** Build the edit-mode meta column HTML. */
function buildEditMetaCol(mon, canDelete) {
  const deleteBtn = canDelete
    ? `<button class="tr-mon-delete" title="Remove">&times;</button>` : "";
  return `<select class="tr-select tr-gender-select">
        <option value="" ${!mon.gender ? "selected" : ""}>Random</option>
        <option value="MON_MALE" ${mon.gender === "MON_MALE" ? "selected" : ""}>Male</option>
        <option value="MON_FEMALE" ${mon.gender === "MON_FEMALE" ? "selected" : ""}>Female</option>
      </select>
      <label class="tr-shiny-label"><input type="checkbox" class="tr-shiny-check" ${mon.shiny ? "checked" : ""}> <span class="tr-dim">Shiny</span></label>
      ${deleteBtn}`;
}

function renderEditMonRow(mon, monIndex, container, d) {
  const isBlank = !mon.species || mon.species === "SPECIES_NONE";
  const spriteSrc = (!isBlank && mon.sprite_path)
    ? `/api/sprites/${mon.sprite_path}${mon.shiny ? "?shiny=1" : ""}`
    : PLACEHOLDER_SVG;

  const types = mon.types || [];
  const primaryType = types[0] || "Normal";
  const grad = TYPE_GRADIENTS[primaryType] || TYPE_GRADIENTS.Normal;
  const grad2 = types[1] ? (TYPE_GRADIENTS[types[1]] || TYPE_GRADIENTS.Normal) : null;
  const bgGradient = isBlank ? "none"
    : grad2
      ? `linear-gradient(135deg, ${hexToRgba(grad.deep, 0.12)} 0%, ${hexToRgba(grad.deep, 0.06)} 35%, ${hexToRgba(grad2.deep, 0.06)} 65%, ${hexToRgba(grad2.deep, 0.12)} 100%)`
      : `linear-gradient(135deg, ${hexToRgba(grad.deep, 0.07)} 0%, transparent 60%)`;

  const row = document.createElement("div");
  row.className = "tr-mon-row tr-mon-row-edit";
  row.style.borderLeftColor = isBlank ? "#333" : grad.accent;
  row.style.background = bgGradient;
  row.dataset.monIndex = monIndex;

  if (isBlank) {
    // Blank slot — show a simple prompt to select a species
    row.innerHTML = `
      <div class="tr-mon-sprite-col">
        <img class="tr-mon-sprite-lg tr-edit-species-btn" src="${PLACEHOLDER_SVG}" alt="?"
             title="Click to select a Pokemon" style="cursor:pointer;opacity:0.4">
      </div>
      <div class="tr-mon-identity-col">
        <div class="tr-mon-name-row">
          <span class="tr-mon-species tr-edit-species-btn tr-dim" style="cursor:pointer;font-style:italic">Click to select a Pokemon...</span>
        </div>
      </div>
      <div class="tr-mon-moves-col"></div>
      <div class="tr-mon-meta-col tr-mon-meta-edit">${buildEditMetaCol(mon, d._workingParty.length > 1)}</div>`;
  } else {
    row.innerHTML = `
      <div class="tr-mon-sprite-col">
        <img class="tr-mon-sprite-lg tr-mon-sprite tr-edit-species-btn" data-sprite-url="${spriteSrc}" src="${spriteSrc}" alt="${mon.species_name || "?"}"
             onerror="this.src='${ERROR_SVG}'" title="Click to change species" style="cursor:pointer">
      </div>
      <div class="tr-mon-identity-col">${buildEditIdentityCol(mon)}</div>
      <div class="tr-mon-moves-col">${buildEditMoveSlots(mon)}</div>
      <div class="tr-mon-meta-col tr-mon-meta-edit">${buildEditMetaCol(mon, d._workingParty.length > 1)}</div>`;
  }

  wireEditMonRow(row, mon, monIndex, container, d);
  return row;
}

/** Render a single edit-mode move slot with type dot and stats. */
function renderEditMoveSlot(mv, idx, isAutoMode) {
  if (mv && (mv.name || mv.const)) {
    const mvType = mv.type || "Normal";
    const dotCol = PICKER_TYPE_COLOURS[mvType] || TYPE_GRADIENTS[mvType]?.accent || "#888";
    const mvName = mv.name || mv.const || "---";
    const power = (mv.power != null && mv.power !== 0) ? mv.power : "\u2014";
    const accuracy = (mv.accuracy != null && mv.accuracy !== 0) ? `${mv.accuracy}%` : "\u2014";
    const cat = (mv.category || "").toLowerCase();
    let catIcon = "\u25C8", catClass = "tr-move-status";
    if (cat === "physical") { catIcon = "\u2694"; catClass = "tr-move-physical"; }
    else if (cat === "special") { catIcon = "\u2726"; catClass = "tr-move-special"; }
    return `<div class="tr-move-row-view tr-move-edit-slot" data-move-idx="${idx}" style="cursor:pointer"><span class="tr-move-dot" style="background:${dotCol}"></span><span class="tr-move-name">${esc(mvName)}</span><span class="tr-move-stats">${power} <span class="tr-move-label">pow</span> &middot; ${accuracy} <span class="tr-move-label">acc</span> <span class="tr-move-cat ${catClass}">${catIcon}</span></span></div>`;
  }
  const label = isAutoMode && idx === 0 ? "Auto (click to set)" : "+ Add Move";
  return `<div class="tr-move-row-view tr-move-edit-slot tr-dim" data-move-idx="${idx}" style="cursor:pointer;font-style:italic"><span class="tr-move-dot" style="background:#333"></span><span class="tr-move-name">${label}</span></div>`;
}

/** Build the 4 move slot HTML for edit mode. */
function buildEditMoveSlots(mon) {
  const moves = mon.moves || [];
  let html = "";
  for (let i = 0; i < 4; i++) {
    html += renderEditMoveSlot((i < moves.length) ? moves[i] : null, i, moves.length === 0);
  }
  return html;
}

function renderEditEVBlock(mon, field, max, totalCap) {
  const vals = mon[field] || {};
  const rows = STAT_KEYS.map(k => {
    const v = vals[k] || 0;
    const col = STAT_COLOURS[k];
    return `<div class="tr-ev-row">
      <span class="tr-ev-label" style="color:${col}">${STAT_LABELS[k]}</span>
      <input type="number" class="tr-input tr-stat-input" data-stat="${k}" data-field="${field}"
             value="${v}" min="0" max="${max}">
    </div>`;
  }).join("");

  const totalClass = field === "evs" ? "tr-ev-total" : "tr-iv-total";
  const total = STAT_KEYS.reduce((s, k) => s + (vals[k] || 0), 0);
  const totalDisplay = totalCap ? `<div class="${totalClass}">${total}/${totalCap}</div>` : "";

  return `<div class="tr-ev-editor tr-${field}-editor" style="display:none">
    ${rows}${totalDisplay}
  </div>`;
}

function wireEditMonRow(row, mon, monIndex, container, d) {
  const party = d._workingParty;

  // Delete button
  const deleteBtn = row.querySelector(".tr-mon-delete");
  if (deleteBtn) {
    deleteBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (party.length <= 1) return;
      party.splice(monIndex, 1);
      markDirty();
      rerenderEditParty(container, d);
    });
  }

  // Species picker (sprite + name)
  row.querySelectorAll(".tr-edit-species-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      createPicker(btn, searchSpecies, async (item) => {
        mon.species = item.const;
        mon.species_name = item.name;
        mon.sprite_path = item.sprite ? item.sprite.replace("/api/sprites/", "") : null;
        mon.types = item.types || [];
        mon.ability = null;
        mon.ability_name = null;
        markDirty();
        rerenderEditParty(container, d);
      });
    });
  });

  // Level input
  const levelInput = row.querySelector(".tr-level-input");
  if (levelInput) {
    levelInput.addEventListener("change", () => {
      const v = Math.max(1, Math.min(100, parseInt(levelInput.value) || 1));
      levelInput.value = v;
      mon.level = v;
      markDirty();
    });
  }

  // Ability picker
  const abilityBtn = row.querySelector(".tr-mon-ability-text");
  if (abilityBtn) {
    abilityBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      let abilities = [];
      if (mon.species) {
        try {
          const res = await api(`/species/${mon.species}`);
          if (res.ok && res.data && res.data.abilities) {
            abilities = res.data.abilities.map(a => ({
              const: a.const || a,
              name: a.name || (a.const || a).replace("ABILITY_", "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()),
            }));
          }
        } catch (_) {}
      }
      if (!abilities.length) abilities = [{ const: "", name: "None" }];
      createPicker(abilityBtn, async () => abilities, (item) => {
        mon.ability = item.const;
        mon.ability_name = item.name;
        abilityBtn.textContent = item.name;
        markDirty();
      });
    });
  }

  // Nature picker
  const natureBtn = row.querySelector(".tr-mon-nature-text");
  if (natureBtn) {
    natureBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const natures = (refData?.natures || []).map(n => {
        let label = n.name;
        if (n.plus) label += ` (+${n.plus} -${n.minus})`;
        return { const: n.const, name: label };
      });
      createPicker(natureBtn, async () => natures, (item) => {
        mon.nature = item.const;
        mon.nature_name = item.name.split(" (")[0];
        natureBtn.textContent = item.name;
        markDirty();
      });
    });
  }

  // Held item picker
  const itemBtn = row.querySelector(".tr-mon-item-text");
  if (itemBtn) {
    itemBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      createPicker(itemBtn, searchItems, (item) => {
        mon.held_item = item.const;
        mon.held_item_name = item.name;
        itemBtn.textContent = item.name;
        const iconEl = itemBtn.parentElement.querySelector(".tr-item-icon");
        if (item.const && item.const !== "ITEM_NONE") {
          const iconUrl = `/api/items/icons/${item.const}`;
          if (iconEl) {
            processSprite(iconUrl).then(dataUrl => { iconEl.src = dataUrl; });
            iconEl.style.display = "";
          } else {
            const img = document.createElement("img");
            img.className = "tr-item-icon";
            img.alt = "";
            img.style.cssText = "width:20px;height:20px";
            processSprite(iconUrl).then(dataUrl => { img.src = dataUrl; });
            img.onerror = function() { this.style.display = "none"; };
            itemBtn.parentElement.insertBefore(img, itemBtn);
          }
        } else if (iconEl) {
          iconEl.style.display = "none";
        }
        markDirty();
      });
    });
  }

  // Ball picker
  const ballBtn = row.querySelector(".tr-mon-ball-text");
  if (ballBtn) {
    ballBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const balls = (refData?.balls || []).map(b => ({
        const: b.const || b,
        name: b.name || (b.const || b).replace(/^(ITEM_|BALL_)/, "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()),
        icon: b.icon || `/api/items/icons/${b.const || b}`,
      }));
      if (!balls.length) {
        balls.push(
          { const: "ITEM_POKE_BALL", name: "Poke Ball", icon: "/api/items/icons/ITEM_POKE_BALL" },
          { const: "ITEM_GREAT_BALL", name: "Great Ball", icon: "/api/items/icons/ITEM_GREAT_BALL" },
          { const: "ITEM_ULTRA_BALL", name: "Ultra Ball", icon: "/api/items/icons/ITEM_ULTRA_BALL" },
          { const: "ITEM_MASTER_BALL", name: "Master Ball", icon: "/api/items/icons/ITEM_MASTER_BALL" },
        );
      }
      createPicker(ballBtn, async (q) => {
        if (!q) return balls;
        const lq = q.toLowerCase();
        return balls.filter(b => b.name.toLowerCase().includes(lq));
      }, (item) => {
        mon.ball = item.const;
        ballBtn.textContent = item.name;
        const ballRow = ballBtn.closest(".tr-mon-row-ball-edit");
        if (ballRow) {
          const iconEl = ballRow.querySelector(".tr-item-icon");
          const iconUrl = item.icon || `/api/items/icons/${item.const}`;
          if (iconEl) {
            processSprite(iconUrl).then(dataUrl => { iconEl.src = dataUrl; });
            iconEl.style.display = "";
          } else {
            const img = document.createElement("img");
            img.className = "tr-item-icon";
            img.alt = "";
            img.style.cssText = "width:20px;height:20px";
            processSprite(iconUrl).then(dataUrl => { img.src = dataUrl; });
            img.onerror = function() { this.style.display = "none"; };
            ballRow.insertBefore(img, ballBtn);
          }
        }
        markDirty();
      });
    });
  }

  // Move pickers
  row.querySelectorAll(".tr-move-edit-slot").forEach(slot => {
    slot.addEventListener("click", (e) => {
      e.stopPropagation();
      const idx = parseInt(slot.dataset.moveIdx);
      createPicker(slot, searchMoves, (item) => {
        if (!mon.moves) mon.moves = [];
        while (mon.moves.length <= idx) mon.moves.push(null);
        mon.moves[idx] = { const: item.const, name: item.name, type: item.type, power: item.power, accuracy: item.accuracy, category: item.category };
        markDirty();
        rerenderEditParty(container, d);
      }, { speciesConst: mon.species, speciesName: mon.species_name, level: mon.level });
    });
  });

  // EV/IV toggle + inputs
  wireStatEditors(row, mon);

  // Gender
  const genderSelect = row.querySelector(".tr-gender-select");
  if (genderSelect) {
    genderSelect.addEventListener("change", () => {
      mon.gender = genderSelect.value || null;
      markDirty();
    });
  }

  // Shiny
  const shinyCheck = row.querySelector(".tr-shiny-check");
  if (shinyCheck) {
    shinyCheck.addEventListener("change", () => {
      mon.shiny = shinyCheck.checked;
      const spriteImg = row.querySelector(".tr-mon-sprite");
      if (spriteImg && mon.sprite_path) {
        const url = `/api/sprites/${mon.sprite_path}${mon.shiny ? "?shiny=1" : ""}`;
        processSprite(url).then(dataUrl => { spriteImg.src = dataUrl; });
      }
      markDirty();
    });
  }

  // Nickname
  const nickInput = row.querySelector(".tr-nickname-input");
  if (nickInput) {
    nickInput.addEventListener("input", () => {
      mon.nickname = nickInput.value || null;
      markDirty();
    });
  }
}

/** Wire EV/IV toggle and stat input handlers for a row/card. */
function wireStatEditors(el, mon) {
  const evToggle = el.querySelector(".tr-edit-ev-toggle");
  const evEditor = el.querySelector(".tr-evs-editor");
  if (evToggle && evEditor) {
    evToggle.addEventListener("click", () => {
      evEditor.style.display = evEditor.style.display === "none" ? "" : "none";
    });
  }

  const ivToggle = el.querySelector(".tr-edit-iv-toggle");
  const ivEditor = el.querySelector(".tr-ivs-editor");
  if (ivToggle && ivEditor) {
    ivToggle.addEventListener("click", () => {
      ivEditor.style.display = ivEditor.style.display === "none" ? "" : "none";
    });
  }

  el.querySelectorAll(".tr-stat-input").forEach(inp => {
    inp.addEventListener("change", () => {
      const field = inp.dataset.field;
      const stat = inp.dataset.stat;
      const max = field === "evs" ? 255 : 31;
      const v = Math.max(0, Math.min(max, parseInt(inp.value) || 0));
      inp.value = v;
      if (!mon[field]) mon[field] = {};
      mon[field][stat] = v;
      markDirty();

      if (field === "evs") {
        const total = STAT_KEYS.reduce((s, k) => s + (mon.evs[k] || 0), 0);
        const totalEl = el.querySelector(".tr-ev-total");
        if (totalEl) {
          totalEl.textContent = `${total}/510`;
          totalEl.style.color = total > 510 ? "#f44" : (total === 510 ? "var(--accent)" : "#ccc");
        }
        const toggleSpan = el.querySelector(".tr-ev-toggle-text");
        if (toggleSpan) toggleSpan.textContent = `${total}/510`;
      }
    });
  });
}

function rerenderEditParty(container, d) {
  const partyDiv = container.querySelector(".tr-party-rows");
  if (!partyDiv) return;
  partyDiv.innerHTML = "";
  d._workingParty.forEach((mon, i) => {
    partyDiv.appendChild(renderEditMonRow(mon, i, container, d));
  });
  // Process Pokemon sprites (frame clip + bg removal)
  processMonSprites(partyDiv);
  processItemIcons(partyDiv);

  // Set up sprite hover/click animation in edit mode too
  wirePartyRowAnimations(partyDiv);

  // Enrich types for any mons missing them
  enrichPartyRowTypes(partyDiv, d._workingParty);

  // Add Pokemon row — only show if party is under 6 AND no blank slots exist
  const hasBlankSlot = d._workingParty.some(m => !m.species || m.species === "SPECIES_NONE");
  if (d._workingParty.length < 6 && !hasBlankSlot) {
    const addRow = document.createElement("div");
    addRow.className = "tr-add-mon-row";
    addRow.innerHTML = `<span>+ Add Pokemon</span>`;
    addRow.addEventListener("click", () => {
      d._workingParty.push({
        species: "SPECIES_NONE",
        species_name: null,
        sprite_path: null,
        level: 5,
        moves: [],
        evs: {},
        ivs: {},
      });
      markDirty();
      rerenderEditParty(container, d);
    });
    partyDiv.appendChild(addRow);
  }

  // Showdown paste section
  renderShowdownPaste(partyDiv, container, d);
}

/** Render the Showdown import section at the bottom of the party editor. */
function renderShowdownPaste(partyDiv, container, d) {
  const pasteSection = document.createElement("div");
  pasteSection.className = "tr-paste-section";
  pasteSection.innerHTML = `
    <h4>Import from Showdown</h4>
    <textarea class="tr-paste-box" placeholder="Paste a Showdown team export here..."></textarea>
    <div class="tr-paste-actions">
      <button class="tr-paste-btn">Import</button>
      <span class="tr-paste-status"></span>
    </div>
    <div class="tr-paste-warnings"></div>`;

  const pasteBox = pasteSection.querySelector(".tr-paste-box");
  const pasteBtn = pasteSection.querySelector(".tr-paste-btn");
  const pasteStatus = pasteSection.querySelector(".tr-paste-status");
  const pasteWarnings = pasteSection.querySelector(".tr-paste-warnings");

  pasteBtn.addEventListener("click", async () => {
    const text = pasteBox.value.trim();
    if (!text) return;

    pasteBtn.disabled = true;
    pasteStatus.textContent = "Parsing...";
    pasteWarnings.innerHTML = "";

    try {
      const res = await postApi("/trainers/parse-showdown", { text });

      if (!res.ok) {
        pasteStatus.textContent = res.error || "Parse failed";
        pasteBtn.disabled = false;
        return;
      }

      const newMons = res.data.pokemon || [];
      const warns = res.data.warnings || [];

      if (warns.length) {
        pasteWarnings.innerHTML = warns
          .map(w => `<div class="tr-paste-warn">${esc(w)}</div>`)
          .join("");
      }

      if (!newMons.length) {
        pasteStatus.textContent = "Could not parse any Pokemon from paste.";
        pasteBtn.disabled = false;
        return;
      }

      const PARTY_LIMIT = 6;
      const existing = d._workingParty.length;
      const total = existing + newMons.length;
      let toAdd = newMons;

      if (total > PARTY_LIMIT) {
        const canAdd = PARTY_LIMIT - existing;
        if (canAdd <= 0) {
          pasteStatus.textContent = "Party is already full (6 Pokemon).";
          pasteBtn.disabled = false;
          return;
        }
        const ok = confirm(
          `This paste has ${newMons.length} Pokemon but only ${canAdd} slot(s) remain. ` +
          `Import the first ${canAdd} and discard the rest?`
        );
        if (!ok) {
          pasteStatus.textContent = "Import cancelled.";
          pasteBtn.disabled = false;
          return;
        }
        toAdd = newMons.slice(0, canAdd);
      }

      for (const m of toAdd) {
        d._workingParty.push({
          species: m.species,
          species_name: m.species_name,
          sprite_path: m.sprite_path || null,
          level: m.level || 100,
          held_item: m.held_item,
          held_item_name: m.held_item_name,
          moves: m.moves || [],
          ability: m.ability,
          ability_name: m.ability_name,
          evs: m.evs || {},
          ivs: m.ivs || {},
          nature: m.nature,
          nature_name: m.nature_name,
          gender: m.gender,
          shiny: m.shiny || false,
        });
      }

      markDirty();
      rerenderEditParty(container, d);
    } catch (err) {
      pasteStatus.textContent = "Error: " + (err.message || "unknown");
      pasteBtn.disabled = false;
    }
  });

  partyDiv.appendChild(pasteSection);
}

// ---------------------------------------------------------------------------
// Trainer items editor (4 fixed slots — Task 2)
// ---------------------------------------------------------------------------

function renderItemsEditor(container, d) {
  // Find or create the items section
  let section = container.querySelector(".tr-items-editor");
  if (section) { section.remove(); }

  section = document.createElement("div");
  section.className = "tr-items-editor";

  // Insert after the trainer header, before the dialogue/party sections
  const header = container.querySelector(".tr-detail-header");
  if (header && header.nextElementSibling) {
    header.parentElement.insertBefore(section, header.nextElementSibling);
  } else {
    container.querySelector("article")?.appendChild(section);
  }

  rebuildItemSlots(section, d);
}

function rebuildItemSlots(section, d) {
  const items = d._editItems || [];

  let slotsHtml = "";
  for (let i = 0; i < 4; i++) {
    const itemConst = items[i] || null;
    if (itemConst && itemConst !== "ITEM_NONE") {
      const name = itemConst.replace("ITEM_", "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
      slotsHtml += `<div class="tr-item-slot tr-item-filled" data-idx="${i}">
        <img class="tr-item-slot-icon" src="/api/items/icons/${itemConst}" alt="" onerror="this.style.display='none'">
        <span>${esc(name)}</span>
        <button class="tr-item-remove">&times;</button>
      </div>`;
    } else {
      slotsHtml += `<div class="tr-item-slot tr-item-empty" data-idx="${i}">
        <span class="tr-item-add">+</span>
      </div>`;
    }
  }

  section.innerHTML = `<div class="tr-items-label">Battle Items</div><div class="tr-items-slots">${slotsHtml}</div>`;

  // Process item icons
  processItemIcons(section);

  // Wire slot clicks
  section.querySelectorAll(".tr-item-slot").forEach(slot => {
    const idx = parseInt(slot.dataset.idx);

    // Remove button
    const rmBtn = slot.querySelector(".tr-item-remove");
    if (rmBtn) {
      rmBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        d._editItems.splice(idx, 1);
        markDirty();
        rebuildItemSlots(section, d);
      });
    }

    // Click to pick item
    slot.addEventListener("click", (e) => {
      if (e.target.closest(".tr-item-remove")) return;
      e.stopPropagation();
      createPicker(slot, searchAllItems, (item) => {
        if (idx < d._editItems.length) {
          d._editItems[idx] = item.const;
        } else {
          d._editItems.push(item.const);
        }
        markDirty();
        rebuildItemSlots(section, d);
      });
    });
  });
}

// ---------------------------------------------------------------------------
// Encounter music selector (Task 4)
// ---------------------------------------------------------------------------

function renderMusicSelector(container, d) {
  let row = container.querySelector(".tr-music-row");
  if (row) row.remove();

  row = document.createElement("div");
  row.className = "tr-music-row";

  const musicOptions = (refData?.music || []);
  if (!musicOptions.length) return; // No music data available

  let optionsHtml = `<option value="">Default</option>`;
  for (const m of musicOptions) {
    const name = m.name || m.const.replace("TRAINER_ENCOUNTER_MUSIC_", "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    const sel = (m.const === d._editMusic) ? " selected" : "";
    optionsHtml += `<option value="${m.const}"${sel}>${esc(name)}</option>`;
  }

  row.innerHTML = `
    <span class="tr-dim" style="font-size:0.75rem">Music:</span>
    <select class="tr-select tr-music-select">${optionsHtml}</select>
    <label style="font-size:0.75rem;color:#888;display:flex;align-items:center;gap:0.25rem">
      <input type="checkbox" class="tr-female-music-check" ${d._editFemaleMusic ? "checked" : ""}>
      &#9792; Female
    </label>`;

  // Insert after AI flags
  const aiDiv = container.querySelector(".tr-detail-ai");
  if (aiDiv) {
    aiDiv.parentElement.insertBefore(row, aiDiv.nextElementSibling);
  }

  const musicSelect = row.querySelector(".tr-music-select");
  musicSelect.addEventListener("change", () => {
    d._editMusic = musicSelect.value;
    markDirty();
  });

  const femaleCheck = row.querySelector(".tr-female-music-check");
  femaleCheck.addEventListener("change", () => {
    d._editFemaleMusic = femaleCheck.checked;
    markDirty();
  });
}

// ---------------------------------------------------------------------------
// Edit mode: header
// ---------------------------------------------------------------------------

function renderEditHeader(container, d) {
  const headerDiv = container.querySelector(".tr-detail-info");
  if (!headerDiv) return;

  // Replace the h2 with an input
  const h2 = headerDiv.querySelector("h2");
  if (h2) {
    const input = document.createElement("input");
    input.type = "text";
    input.className = "tr-input tr-name-input";
    input.value = d.name || "";
    input.maxLength = 15;
    input.addEventListener("input", () => {
      d._editName = input.value;
      markDirty();
    });
    h2.replaceWith(input);
  }

  // Replace class/id text with class dropdown
  const sub = headerDiv.querySelector(".tr-detail-sub");
  if (sub && refData) {
    const select = document.createElement("select");
    select.className = "tr-select tr-class-edit";
    for (const cls of refData.classes) {
      const opt = document.createElement("option");
      opt.value = cls.const;
      opt.textContent = cls.name;
      if (cls.const === d.class_const) opt.selected = true;
      select.appendChild(opt);
    }
    sub.innerHTML = "";
    sub.appendChild(select);
    sub.append(` #${d.id || "?"}`);

    // Pic selector (controls the trainer sprite)
    let picSelect = null;
    if (refData.pics && refData.pics.length) {
      picSelect = document.createElement("select");
      picSelect.className = "tr-select tr-pic-edit";
      for (const pic of refData.pics) {
        const opt = document.createElement("option");
        opt.value = pic.const;
        opt.textContent = pic.name;
        if (pic.const === (d._editPicConst || d.pic_const)) opt.selected = true;
        picSelect.appendChild(opt);
      }
      picSelect.addEventListener("change", () => {
        d._editPicConst = picSelect.value;
        markDirty();
        // Update sprite live
        const picEntry = refData.pics.find(p => p.const === picSelect.value);
        if (picEntry) {
          const spriteImg = container.querySelector(".tr-detail-sprite");
          if (spriteImg) {
            const picUrl = `/api/trainers/sprites/${picEntry.file}`;
            processSprite(picUrl).then(dataUrl => { spriteImg.src = dataUrl; });
          }
        }
      });
      const picLabel = document.createElement("div");
      picLabel.className = "tr-pic-selector";
      picLabel.innerHTML = `<span class="tr-dim">Sprite: </span>`;
      picLabel.appendChild(picSelect);
      sub.appendChild(picLabel);
    }

    // Class change -> auto-match pic and update sprite
    select.addEventListener("change", () => {
      d._editClassConst = select.value;
      markDirty();
      // Try to match TRAINER_CLASS_X -> TRAINER_PIC_X
      if (refData.pics && refData.pics.length) {
        const suffix = select.value.replace("TRAINER_CLASS_", "");
        const matchPic = refData.pics.find(p => p.const === "TRAINER_PIC_" + suffix);
        if (matchPic) {
          d._editPicConst = matchPic.const;
          if (picSelect) picSelect.value = matchPic.const;
          const spriteImg = container.querySelector(".tr-detail-sprite");
          if (spriteImg) {
            const matchUrl = `/api/trainers/sprites/${matchPic.file}`;
            processSprite(matchUrl).then(dataUrl => { spriteImg.src = dataUrl; });
          }
        }
      }
    });
  }

  // Battle type selector (replaces is_double checkbox)
  // Note: .party format only stores is_double (bool). We expose the full battle_type
  // list for script-level context, but the save payload derives is_double from it.
  const badgesDiv = headerDiv.querySelector(".tr-detail-badges");
  if (badgesDiv) {
    const currentBattleType = d._editBattleType || "single";
    const battleTypes = (refData && refData.battle_types) || [];

    const wrapper = document.createElement("div");
    wrapper.className = "tr-edit-field";

    const lbl = document.createElement("label");
    lbl.textContent = "Battle Type";
    lbl.className = "tr-edit-field-label";
    wrapper.appendChild(lbl);

    const btSelect = document.createElement("select");
    btSelect.className = "tr-select tr-battle-type-select";
    for (const bt of battleTypes) {
      const opt = document.createElement("option");
      opt.value = bt.name;
      opt.textContent = formatBattleTypeName(bt.name);
      opt.title = bt.description || "";
      if (bt.name === currentBattleType) opt.selected = true;
      btSelect.appendChild(opt);
    }
    // Fallback if no battle_types from backend — show at least single/double
    if (!battleTypes.length) {
      for (const name of ["single", "double"]) {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = formatBattleTypeName(name);
        if (name === currentBattleType) opt.selected = true;
        btSelect.appendChild(opt);
      }
    }
    wrapper.appendChild(btSelect);

    const descSpan = document.createElement("span");
    descSpan.className = "tr-battle-type-desc";
    const curDesc = battleTypes.find(b => b.name === currentBattleType);
    descSpan.textContent = curDesc ? curDesc.description : "";
    wrapper.appendChild(descSpan);

    btSelect.addEventListener("change", () => {
      const bt = btSelect.value;
      d._editBattleType = bt;
      d._editDouble = bt.includes("double");
      const desc = battleTypes.find(b => b.name === bt);
      descSpan.textContent = desc ? desc.description : "";
      markDirty();
    });

    badgesDiv.innerHTML = "";
    badgesDiv.appendChild(wrapper);
  }

  // AI flags — collapsible section
  const aiDiv = headerDiv.querySelector(".tr-detail-ai");
  if (aiDiv && refData) {
    const currentFlags = new Set(
      (d.ai_flags || "").split("|").map(f => f.trim()).filter(Boolean)
    );
    const activeCount = currentFlags.size;

    aiDiv.innerHTML = "";
    // Summary toggle
    const toggle = document.createElement("div");
    toggle.className = "tr-ai-toggle";
    toggle.style.cssText = "cursor:pointer;font-size:0.8rem;color:#ccc;display:flex;align-items:center;gap:0.4rem;";
    toggle.innerHTML = `<span class="tr-ai-toggle-arrow" style="font-size:0.6rem;display:inline-block;transition:transform 0.15s">&#x25B6;</span> AI Flags (${activeCount} active)`;
    aiDiv.appendChild(toggle);

    // Grid container (collapsed by default)
    const grid = document.createElement("div");
    grid.className = "tr-ai-grid";
    grid.style.display = "none";
    for (const flag of refData.ai_flags) {
      const label = document.createElement("label");
      label.className = "tr-ai-flag-edit";
      if (flag.description) label.title = flag.description;
      const checked = currentFlags.has(flag.const);
      const descHtml = flag.description
        ? `<span class="tr-ai-flag-desc">${esc(flag.description)}</span>`
        : "";
      label.innerHTML = `<span class="tr-ai-flag-row"><input type="checkbox" data-flag="${flag.const}" ${checked ? "checked" : ""}> <span class="tr-ai-flag-name">${esc(flag.name)}</span></span>${descHtml}`;
      label.querySelector("input").addEventListener("change", () => {
        markDirty();
        // Update count in toggle text
        const checkedCount = grid.querySelectorAll("input:checked").length;
        toggle.innerHTML = `<span class="tr-ai-toggle-arrow" style="font-size:0.6rem;display:inline-block;transition:transform 0.15s;transform:rotate(90deg)">&#x25B6;</span> AI Flags (${checkedCount} active)`;
      });
      grid.appendChild(label);
    }
    aiDiv.appendChild(grid);

    toggle.addEventListener("click", () => {
      const open = grid.style.display === "none";
      grid.style.display = open ? "" : "none";
      const arrow = toggle.querySelector(".tr-ai-toggle-arrow");
      if (arrow) arrow.style.transform = open ? "rotate(90deg)" : "";
    });
  }
}

// ---------------------------------------------------------------------------
// Dialogue editor
// ---------------------------------------------------------------------------

function renderEditDialogue(container, d) {
  const section = container.querySelector(".tr-dialogue-section");
  if (!section) return;

  section.innerHTML = `<h3>Dialogue</h3>`;

  for (const field of ["intro", "defeat"]) {
    const label = field.charAt(0).toUpperCase() + field.slice(1);
    const raw = (d._editDialogue && d._editDialogue[field]) || "";
    const plain = poryToPlain(raw);

    const block = document.createElement("div");
    block.className = "tr-dialogue-edit-block";

    block.innerHTML = `
      <span class="tr-dialogue-label">${label}</span>
      <textarea class="tr-dialogue-input" data-field="${field}" rows="4"
        placeholder="Type dialogue here. Use Enter for new lines, double-Enter for new textbox page."
      >${esc(plain)}</textarea>
      <div class="gba-preview-live"></div>
      <div class="gba-box-count"></div>
    `;

    const textarea = block.querySelector("textarea");
    const previewDiv = block.querySelector(".gba-preview-live");
    const countDiv = block.querySelector(".gba-box-count");

    function updatePreview() {
      const pory = plainToPory(textarea.value);
      d._editDialogue[field] = pory || null;
      const { html, boxCount, warnings } = renderGbaPreview(pory);
      previewDiv.innerHTML = html;
      let countText = `${boxCount} textbox${boxCount !== 1 ? "es" : ""}`;
      if (boxCount > 3) countText += " (aim for 3 or fewer)";
      countDiv.textContent = countText;
      countDiv.className = "gba-box-count" + (boxCount > 3 ? " gba-box-warn" : "");
    }

    textarea.addEventListener("input", () => {
      updatePreview();
      markDirty();
    });

    // Initial preview
    section.appendChild(block);
    updatePreview();
  }
}

// ---------------------------------------------------------------------------
// Detail view
// ---------------------------------------------------------------------------

async function renderDetail(container, trainerConst) {
  container.innerHTML = `<article><div class="tr-empty">Loading...</div></article>`;

  // Load detail + ref in parallel
  const [res, refRes] = await Promise.all([
    api(`/trainers/${trainerConst}`),
    refData ? Promise.resolve({ ok: true, data: refData }) : api("/trainers/ref"),
  ]);

  if (!res.ok) {
    container.innerHTML = `<article>
      <a href="#/trainers" class="detail-back">Back to Trainers</a>
      <p>Error: ${res.error}</p>
    </article>`;
    return;
  }

  if (refRes.ok) refData = refRes.data;

  const d = res.data;

  const spriteSrc = d.sprite_path
    ? `/api/trainers/sprites/${d.sprite_path}`
    : PLACEHOLDER_SVG;

  // Badges
  const badges = [];
  if (d.is_custom) badges.push(`<span class="tr-badge tr-badge-custom">Custom</span>`);
  if (d.battle_type && d.battle_type !== "single") {
    badges.push(`<span class="tr-badge tr-badge-double">${formatBattleTypeName(d.battle_type)}</span>`);
  } else if (d.is_double) {
    badges.push(`<span class="tr-badge tr-badge-double">Double Battle</span>`);
  }

  // AI flags
  const aiFlags = d.ai_flags
    ? d.ai_flags.split("|").map(f => f.trim()).filter(Boolean)
        .map(f => {
          const name = f.replace("AI_FLAG_", "").replace(/_/g, " ")
            .replace(/\b\w/g, c => c.toUpperCase());
          return `<span class="tr-ai-flag">${name}</span>`;
        }).join("")
    : "";

  // Encounter music (view mode)
  let musicHtml = "";
  if (d.encounter_music_name) {
    const femaleIcon = d.is_female_music ? ` <span title="Female variant" style="color:#F85888">&#9792;</span>` : "";
    musicHtml = `<div class="tr-music-view" style="font-size:0.75rem;color:#aaa;margin-top:0.3rem"><span class="tr-dim">Music:</span> ${esc(d.encounter_music_name)}${femaleIcon}</div>`;
  }

  // Items
  const itemsRaw = (d.items_raw || []).filter(i => i && i !== "ITEM_NONE");
  const items = (d.items || []).filter(i => i && i !== "None");
  const itemsSection = items.length
    ? `<div class="tr-detail-section">
        <h3>Items</h3>
        <div class="tr-item-pills">${items.map((name, idx) => {
          const iconConst = itemsRaw[idx] || "";
          const iconHtml = iconConst ? `<img class="tr-item-icon tr-battle-item-icon" src="/api/items/icons/${iconConst}" alt="" onerror="this.style.display='none'"> ` : "";
          return `<span class="tr-item-pill">${iconHtml}${name}</span>`;
        }).join("")}</div>
      </div>`
    : "";

  // Dialogue
  let dialogueSection = "";
  if (d.is_custom) {
    let dhtml = `<div class="tr-detail-section tr-dialogue-section"><h3>Dialogue</h3>`;
    if (d.dialogue && (d.dialogue.intro || d.dialogue.defeat)) {
      if (d.dialogue.intro) {
        const preview = renderGbaPreview(d.dialogue.intro);
        dhtml += `<div class="tr-dialogue-block"><span class="tr-dialogue-label">Intro</span><div class="gba-preview">${preview.html}</div></div>`;
      }
      if (d.dialogue.defeat) {
        const preview = renderGbaPreview(d.dialogue.defeat);
        dhtml += `<div class="tr-dialogue-block"><span class="tr-dialogue-label">Defeat</span><div class="gba-preview">${preview.html}</div></div>`;
      }
    } else {
      dhtml += `<div class="tr-empty">No dialogue file found</div>`;
    }
    dhtml += `</div>`;
    dialogueSection = dhtml;
  }

  // Party — view mode uses full-width horizontal rows
  const partyHtml = (d.party || []).map(renderMonRow).join("");

  container.innerHTML = `<article class="tr-detail">
    <div class="tr-detail-topbar">
      <a href="#/trainers" class="detail-back">Back to Trainers</a>
      <button class="tr-edit-btn">Edit</button>
    </div>

    <div class="tr-detail-header">
      <img class="tr-detail-sprite" src="${spriteSrc}" alt="${d.name || d.const}"
           onerror="this.src='${ERROR_SVG}'">
      <div class="tr-detail-info">
        <h2>${d.name || "???"}</h2>
        <span class="tr-detail-sub">${d.class || ""} #${d.id || "?"}</span>
        <div class="tr-detail-badges">${badges.join("")}</div>
        ${aiFlags ? `<div class="tr-detail-ai">${aiFlags}</div>` : `<div class="tr-detail-ai"></div>`}
        ${musicHtml}
      </div>
    </div>

    ${itemsSection}

    ${dialogueSection}

    <div class="tr-detail-section">
      <h3>Party</h3>
      <div class="tr-party-rows">${partyHtml || `<div class="tr-empty">No party data</div>`}</div>
    </div>

    <div class="tr-actions" style="display:none">
      <button class="tr-save-btn" disabled>Save</button>
      <button class="tr-discard-btn">Discard</button>
      <span class="tr-dirty-indicator" style="display:none">Unsaved changes</span>
      <span class="tr-save-status"></span>
    </div>
  </article>`;

  // Process trainer class sprite (bg removal)
  const detailSprite = container.querySelector(".tr-detail-sprite");
  if (detailSprite && detailSprite.src && !detailSprite.src.startsWith("data:")) {
    processSprite(detailSprite.src).then(dataUrl => { detailSprite.src = dataUrl; });
  }

  // Process Pokemon sprites and item icons (frame clip + bg removal)
  processMonSprites(container);
  processItemIcons(container);

  // Set up sprite hover/click animation on party rows
  wirePartyRowAnimations(container);

  // Enrich party rows with species types (fetched in parallel, updates gradients)
  enrichPartyRowTypes(container, d.party || []);

  // Edit button handler
  const editBtn = container.querySelector(".tr-edit-btn");
  const actionsDiv = container.querySelector(".tr-actions");

  editBtn.addEventListener("click", () => {
    if (editMode) {
      // Exit edit mode - re-render
      editMode = false;
      dirty = false;
      workingCopy = null;
      renderDetail(container, trainerConst);
      return;
    }

    // Enter edit mode
    editMode = true;
    dirty = false;
    editBtn.textContent = "Cancel";
    editBtn.classList.add("tr-edit-btn-active");
    actionsDiv.style.display = "";

    // Deep copy party for editing
    d._workingParty = JSON.parse(JSON.stringify(d.party || []));
    d._editName = d.name;
    d._editClassConst = d.class_const;
    d._editDouble = d.is_double;
    d._editBattleType = d.battle_type || (d.is_double ? "double" : "single");
    d._editItems = [...(d.items_raw || [])].filter(i => i && i !== "ITEM_NONE");
    d._editMusic = d.encounter_music || "";
    d._editFemaleMusic = d.is_female_music || false;
    d._editDialogue = {
      intro: d.dialogue ? d.dialogue.intro : null,
      defeat: d.dialogue ? d.dialogue.defeat : null,
    };
    workingCopy = d;

    // Transform header to edit mode
    renderEditHeader(container, d);

    // Render trainer items editor
    renderItemsEditor(container, d);

    // Render encounter music selector
    renderMusicSelector(container, d);

    // Rebuild party as editable rows (same container, interactive content)
    rerenderEditParty(container, d);

    // Transform dialogue to edit mode
    renderEditDialogue(container, d);
  });

  // Save button
  const saveBtn = container.querySelector(".tr-save-btn");
  const discardBtn = container.querySelector(".tr-discard-btn");
  const dirtyEl = container.querySelector(".tr-dirty-indicator");
  const saveStatus = container.querySelector(".tr-save-status");

  saveBtn.addEventListener("click", async () => {
    if (!workingCopy) return;

    // Gather AI flags from checkboxes
    const aiCheckboxes = container.querySelectorAll(".tr-ai-flag-edit input[type=checkbox]");
    const checkedFlags = [];
    aiCheckboxes.forEach(cb => {
      if (cb.checked) checkedFlags.push(cb.dataset.flag);
    });

    // Dialogue — only include if changed
    const dialoguePayload = {};
    if (workingCopy._editDialogue) {
      dialoguePayload.intro = workingCopy._editDialogue.intro || null;
      dialoguePayload.defeat = workingCopy._editDialogue.defeat || null;
    }

    const payload = {
      trainer_const: d.const,
      trainer_name: workingCopy._editName || d.name || "",
      trainer_class: workingCopy._editClassConst || d.class_const || "",
      trainer_pic: workingCopy._editPicConst || d.pic_const || "",
      // is_double derived from battle type; battle_type sent as forward-compatible metadata
      is_double: workingCopy._editBattleType?.includes("double") ?? workingCopy._editDouble ?? d.is_double ?? false,
      battle_type: workingCopy._editBattleType || (d.is_double ? "double" : "single"),
      ai_flags: checkedFlags.join(" | "),
      trainer_items: workingCopy._editItems || d.items_raw || [],
      encounter_music: workingCopy._editMusic || "",
      is_female_music: workingCopy._editFemaleMusic || false,
      dialogue: dialoguePayload,
      mons: (workingCopy._workingParty || []).filter(mon => mon.species && mon.species !== "SPECIES_NONE").map(mon => ({
        species: mon.species,
        level: mon.level || 5,
        held_item: mon.held_item || null,
        moves: (mon.moves || []).filter(Boolean).map(m => typeof m === "string" ? m : (m.const || m)),
        ability: mon.ability || null,
        evs: mon.evs || null,
        ivs: mon.ivs || null,
        nature: mon.nature || null,
        gender: mon.gender || null,
        shiny: mon.shiny || false,
        ball: mon.ball || null,
        nickname: mon.nickname || null,
      })),
    };

    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";
    saveStatus.textContent = "";

    try {
      const res = await fetch(`/api/trainers/${d.const}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await res.json();
      if (body.ok) {
        saveStatus.textContent = "Saved!";
        saveStatus.className = "tr-save-status tr-save-ok";
        dirty = false;
        dirtyEl.style.display = "none";
        saveBtn.textContent = "Save";

        // Offer build
        const buildBtn = document.createElement("button");
        buildBtn.className = "tr-build-btn";
        buildBtn.textContent = "Build ROM";
        buildBtn.addEventListener("click", async () => {
          buildBtn.disabled = true;
          buildBtn.textContent = "Building...";
          try {
            await fetch("/api/build", { method: "POST" });
            buildBtn.textContent = "Build started";
          } catch (err) {
            buildBtn.textContent = "Build error";
          }
        });
        actionsDiv.appendChild(buildBtn);

        // Invalidate cached trainer list
        cachedTrainers = null;
      } else {
        saveStatus.textContent = body.error || "Save failed";
        saveStatus.className = "tr-save-status tr-save-err";
        saveBtn.textContent = "Save";
        saveBtn.disabled = false;
      }
    } catch (err) {
      saveStatus.textContent = "Network error";
      saveStatus.className = "tr-save-status tr-save-err";
      saveBtn.textContent = "Save";
      saveBtn.disabled = false;
    }
  });

  // Discard button
  discardBtn.addEventListener("click", () => {
    editMode = false;
    dirty = false;
    workingCopy = null;
    renderDetail(container, trainerConst);
  });

  // Navigation guard
  const hashGuard = (e) => {
    if (dirty) {
      if (!confirm("You have unsaved changes. Leave anyway?")) {
        e.preventDefault();
        history.pushState(null, "", `#/trainers/${trainerConst}`);
      }
    }
  };
  window.addEventListener("hashchange", hashGuard, { once: true });
}

function markDirty() {
  dirty = true;
  const dirtyEl = document.querySelector(".tr-dirty-indicator");
  if (dirtyEl) dirtyEl.style.display = "";
  const saveBtn = document.querySelector(".tr-save-btn");
  if (saveBtn) {
    saveBtn.disabled = false;
    saveBtn.textContent = "Save";
  }
  const saveStatus = document.querySelector(".tr-save-status");
  if (saveStatus) saveStatus.textContent = "";
}

// ---------------------------------------------------------------------------
// Battle type helper
// ---------------------------------------------------------------------------

function formatBattleTypeName(name) {
  return name.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// GBA text utilities (mirrors textutils.py)
// ---------------------------------------------------------------------------

/**
 * Convert raw pory dialogue (with \n \p $) to human-readable plain text.
 * \n -> newline, \p -> double newline (paragraph), $ stripped.
 */
function poryToPlain(text) {
  if (!text) return "";
  let s = text.replace(/\$$/g, "");
  // \p -> double newline (paragraph break)
  s = s.replace(/\\p/g, "\n\n");
  // \n -> single newline
  s = s.replace(/\\n/g, "\n");
  return s;
}

/**
 * Convert plain text back to pory format.
 * Double newlines -> \p, single newlines -> \n, then auto-wrap
 * lines that exceed GBA_LINE_LEN, and upgrade every 2nd \n to \p.
 */
function plainToPory(text) {
  if (!text || !text.trim()) return "";
  // Normalize line endings
  let s = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  // Double newline = paragraph break (\p)
  s = s.replace(/\n\n+/g, "\\p");
  // Single newline = line break (\n)
  s = s.replace(/\n/g, "\\n");
  // Now auto-wrap with box management
  s = wrapGbaText(s);
  // Add trailing $
  if (!s.endsWith("$")) s += "$";
  return s;
}

/**
 * Word-wrap text into GBA textbox format (38 chars/line, 2 lines/box).
 * Preserves existing \n and \p markers. Upgrades every 2nd \n to \p.
 */
function wrapGbaText(text) {
  const segments = text.split(/(\\n|\\p)/);
  const tokens = [];

  for (const seg of segments) {
    if (seg === "\\n" || seg === "\\p") {
      tokens.push(seg);
      continue;
    }
    // Word-wrap this segment
    const words = seg.split(" ").filter(w => w.length > 0);
    let line = "";
    for (const word of words) {
      if (!line) {
        line = word;
      } else if (line.length + 1 + word.length <= GBA_LINE_LEN) {
        line += " " + word;
      } else {
        tokens.push(line);
        tokens.push("\\n");
        line = word;
      }
    }
    if (line) tokens.push(line);
  }

  // Walk tokens, upgrading every 2nd \n in a box to \p
  let out = "";
  let linesInBox = 0;

  for (const tok of tokens) {
    if (tok === "\\p") {
      out += "\\p";
      linesInBox = 0;
    } else if (tok === "\\n") {
      linesInBox++;
      if (linesInBox >= GBA_LINES_PER_BOX) {
        out += "\\p";
        linesInBox = 0;
      } else {
        out += "\\n";
      }
    } else {
      out += tok;
    }
  }
  return out;
}

/**
 * Render a GBA textbox preview as HTML.
 * Returns {html, boxCount, warnings[]} where warnings are lines > 38 chars.
 */
function renderGbaPreview(poryText) {
  if (!poryText) return { html: "", boxCount: 0, warnings: [] };

  const warnings = [];
  const tokens = poryText.replace(/\$$/, "").split(/(\\n|\\p)/);
  let html = "";
  let boxNum = 1;
  let linesInBox = 0;
  let currentLine = "";

  function flushLine() {
    if (currentLine === "" && linesInBox === 0) return;
    const len = currentLine.length;
    const warn = len > GBA_LINE_LEN;
    if (warn) warnings.push(`Line exceeds ${GBA_LINE_LEN} chars (${len})`);
    const cls = warn ? "gba-line gba-line-warn" : "gba-line";
    html += `<div class="${cls}"><span class="gba-text">${esc(currentLine)}</span><span class="gba-count">${len}</span></div>`;
    currentLine = "";
  }

  html += `<div class="gba-box" data-box="${boxNum}">`;

  for (const tok of tokens) {
    if (tok === "\\p") {
      flushLine();
      html += `</div><div class="gba-box-sep"></div><div class="gba-box" data-box="${++boxNum}">`;
      linesInBox = 0;
    } else if (tok === "\\n") {
      flushLine();
      linesInBox++;
    } else {
      currentLine += tok;
    }
  }
  flushLine();
  html += `</div>`;

  return { html, boxCount: boxNum, warnings };
}

// escapeHtml removed — now imported as esc from utils.js

// ---------------------------------------------------------------------------
// Main render
// ---------------------------------------------------------------------------

export async function render(container) {
  const hash = window.location.hash || "";
  const detailMatch = hash.match(/^#\/trainers\/(.+)$/);
  if (detailMatch) {
    await renderDetail(container, decodeURIComponent(detailMatch[1]));
    return;
  }
  await renderList(container);
}

export function cleanup() {
  clearTimeout(debounceTimer);
  debounceTimer = null;
  if (scrollHandler) {
    window.removeEventListener("scroll", scrollHandler);
    scrollHandler = null;
  }
  if (spriteObserver) {
    spriteObserver.disconnect();
    spriteObserver = null;
  }
  closeAllPickers();
  allTrainers = [];
  cachedTrainers = null;
  renderedCount = 0;
  searchQuery = "";
  activeFilter = "all";
  classFilter = "";
  editMode = false;
  dirty = false;
  workingCopy = null;
}
