/**
 * TORCH Web GUI -- Dex Browser view.
 * Hub page with category cards, species grid, and sub-browsers for
 * moves, abilities, and items.
 */

import { api, versionGate } from "../app.js";
import { esc } from "../utils.js";
import { processSprite, processSpriteFrames } from "../spriteUtils.js";
import { MOVESET_REFACTOR } from "../version_constants.js";

const TYPE_COLOURS = {
  Normal:   "#A8A878", Fire:     "#F08030", Water:    "#6890F0",
  Electric: "#F8D030", Grass:    "#78C850", Ice:      "#98D8D8",
  Fighting: "#C03028", Poison:   "#A040A0", Ground:   "#E0C068",
  Flying:   "#A890F0", Psychic:  "#F85888", Bug:      "#A8B820",
  Rock:     "#B8A038", Ghost:    "#705898", Dragon:   "#7038F8",
  Dark:     "#705848", Steel:    "#B8B8D0", Fairy:    "#EE99AC",
};

const STAT_LABELS = ["HP", "Atk", "Def", "SpA", "SpD", "Spe"];
const STAT_KEYS   = ["hp", "atk", "def", "spa", "spd", "spe"];

let debounceTimer = null;
let allSpecies = [];     // full dataset from last fetch
let cachedSpecies = null; // full unfiltered list, survives navigation
let renderedCount = 0;   // how many cards are in the DOM
let scrollHandler = null; // reference for cleanup
let spriteObserver = null; // IntersectionObserver for sprite loading
let savedScrollY = 0;    // scroll position to restore on "Back to Dex"
const PAGE_SIZE = 36;

// Widget filter state
let activeTypes = [];        // max 2 type strings for dual-type AND filter
let activeGen = null;        // null or 1-9
let activeSortMode = "dex";  // "dex"|"name-az"|"name-za"|"bst-desc"|"bst-asc"

const GEN_RANGES = [
  [1, 151], [152, 251], [252, 386], [387, 493],
  [494, 649], [650, 721], [722, 809], [810, 905], [906, 1025],
];

function getGeneration(natDexNum) {
  for (let i = 0; i < GEN_RANGES.length; i++) {
    if (natDexNum >= GEN_RANGES[i][0] && natDexNum <= GEN_RANGES[i][1]) return i + 1;
  }
  return 9;
}

function isSimpleSearch(query) {
  return query && !query.includes(":") && !/bst[<>=]/.test(query);
}

function filterAndSortSpecies(species) {
  let result = species;
  if (activeTypes.length > 0) {
    result = result.filter(sp => {
      const t = sp.types || [];
      return activeTypes.every(at => t.includes(at));
    });
  }
  if (activeGen !== null) {
    result = result.filter(sp => getGeneration(sp.nat_dex_num) === activeGen);
  }
  if (activeSortMode === "name-az") {
    result = [...result].sort((a, b) => a.name.localeCompare(b.name));
  } else if (activeSortMode === "name-za") {
    result = [...result].sort((a, b) => b.name.localeCompare(a.name));
  } else if (activeSortMode === "bst-desc") {
    result = [...result].sort((a, b) => (b.bst || 0) - (a.bst || 0));
  } else if (activeSortMode === "bst-asc") {
    result = [...result].sort((a, b) => (a.bst || 0) - (b.bst || 0));
  }
  return result;
}

const PLACEHOLDER_SVG = "data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2296%22 height=%2296%22><circle cx=%2248%22 cy=%2248%22 r=%2240%22 fill=%22%23181818%22/></svg>";
const ERROR_SVG = "data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2296%22 height=%2296%22><rect fill=%22%23333%22 width=%2296%22 height=%2296%22 rx=%228%22/><text x=%2248%22 y=%2254%22 text-anchor=%22middle%22 fill=%22%23666%22 font-size=%2212%22>?</text></svg>";

// Sprite loading queue -- limits concurrent HTTP requests
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
    // Skip if no longer visible (scrolled away before we got to it)
    if (!img.dataset.pending) continue;
    spritesInFlight++;
    const realSrc = img.dataset.sprite;
    processSprite(realSrc).then(dataUrl => {
      if (img.dataset.pending) {
        img.src = dataUrl;
        img.dataset.frame1 = dataUrl;
        img.dataset.loaded = "1";
        delete img.dataset.pending;
      }
      spritesInFlight--;
      drainSpriteQueue();
      // Pre-fetch frame2 in the background (non-blocking)
      processSpriteFrames(realSrc).then(frames => {
        if (frames.frame2) img.dataset.frame2 = frames.frame2;
      }).catch(() => {});
    }).catch(() => {
      if (img.dataset.pending) {
        img.src = ERROR_SVG;
        delete img.dataset.pending;
      }
      spritesInFlight--;
      drainSpriteQueue();
    });
  }
}

// Cache learnset data per species+type so re-clicking tabs doesn't re-fetch
const learnsetCache = {};

function padDexNum(n) {
  return "#" + String(n).padStart(3, "0");
}

function renderCard(sp) {
  const types = (sp.types || []).map(t => {
    const bg = TYPE_COLOURS[t] || "#888";
    return `<span class="type-badge" style="background:${bg}">${t}</span>`;
  }).join("");

  const primaryType = sp.types?.[0] || "Normal";
  const borderColour = TYPE_COLOURS[primaryType] || "#888";

  return `<div class="dex-card" data-const="${sp.const}" data-type-color="${borderColour}" style="--dex-type-color: ${borderColour}; --dex-type-glow: ${borderColour}26; border-top: 3px solid ${borderColour}; background: radial-gradient(circle at center 30%, ${borderColour}08 0%, transparent 70%), var(--surface-2, #1a1a1a)">
    <div class="dex-sprite-wrap">
      <img src="${PLACEHOLDER_SVG}" data-sprite="/api/sprites/${sp.sprite_path}" alt="${sp.name}">
    </div>
    <span class="dex-name">${sp.name}</span>
    <div class="dex-types">${types}</div>
    <span class="dex-num">${padDexNum(sp.nat_dex_num)}</span>
  </div>`;
}

let _spriteObserverRoot = null;

function ensureSpriteObserver(root) {
  // Reuse existing observer if root hasn't changed
  if (spriteObserver && _spriteObserverRoot === (root || null)) return;
  if (spriteObserver) { spriteObserver.disconnect(); spriteObserver = null; }
  _spriteObserverRoot = root || null;
  spriteObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      const img = entry.target;
      if (entry.isIntersecting) {
        const realSrc = img.dataset.sprite;
        if (realSrc && !img.dataset.loaded && !img.dataset.pending) {
          img.dataset.pending = "1";
          queueSprite(img);
        }
      } else {
        // Cancel pending loads but keep already-loaded sprites
        if (img.dataset.pending) {
          delete img.dataset.pending;
        }
      }
    }
  }, { root: root || null, rootMargin: "400px" });
}

function appendCards(grid, species, start, count, scrollRoot) {
  const root = scrollRoot || null;
  ensureSpriteObserver(root);
  const end = Math.min(start + count, species.length);
  const fragment = document.createDocumentFragment();
  for (let i = start; i < end; i++) {
    const tmp = document.createElement("div");
    tmp.innerHTML = renderCard(species[i]);
    const card = tmp.firstElementChild;
    card.addEventListener("click", () => {
      const scrollBox = grid.closest(".dex-widget-scroll");
      savedScrollY = scrollBox ? scrollBox.scrollTop : window.scrollY;
      window.location.hash = `#/dex/${card.dataset.const}`;
    });
    const img = card.querySelector("img");
    if (img) spriteObserver.observe(img);

    // Hover animation: pop + random frame cycle
    let hoverTimeouts = [];
    card.addEventListener("mouseenter", () => {
      card.classList.add("dex-card-hover");
      if (img && img.dataset.frame2) {
        const f1 = img.dataset.frame1;
        const f2 = img.dataset.frame2;
        const pattern = Math.floor(Math.random() * 3);
        if (pattern === 0) {
          // Quick peek
          hoverTimeouts.push(setTimeout(() => { img.src = f2; }, 80));
          hoverTimeouts.push(setTimeout(() => { img.src = f1; }, 230));
        } else if (pattern === 1) {
          // Double bounce
          hoverTimeouts.push(setTimeout(() => { img.src = f2; }, 120));
          hoverTimeouts.push(setTimeout(() => { img.src = f1; }, 240));
          hoverTimeouts.push(setTimeout(() => { img.src = f2; }, 340));
          hoverTimeouts.push(setTimeout(() => { img.src = f1; }, 460));
        } else {
          // Hold pose
          hoverTimeouts.push(setTimeout(() => { img.src = f2; }, 60));
          hoverTimeouts.push(setTimeout(() => { img.src = f1; }, 410));
        }
      }
    });
    card.addEventListener("mouseleave", () => {
      card.classList.remove("dex-card-hover");
      hoverTimeouts.forEach(clearTimeout);
      hoverTimeouts = [];
      if (img && img.dataset.frame1 && img.dataset.loaded) {
        img.src = img.dataset.frame1;
      }
    });

    fragment.appendChild(card);
  }
  grid.appendChild(fragment);
  return end;
}

function setupInfiniteScroll(container) {
  const scrollBox = container.querySelector(".dex-widget-scroll");
  if (scrollHandler && scrollBox) {
    scrollBox.removeEventListener("scroll", scrollHandler);
    scrollHandler = null;
  } else if (scrollHandler) {
    window.removeEventListener("scroll", scrollHandler);
    scrollHandler = null;
  }

  const grid = container.querySelector(".dex-grid");
  if (!grid) return;

  if (scrollBox) {
    scrollHandler = () => {
      if (renderedCount >= allSpecies.length) return;
      const threshold = scrollBox.scrollHeight - scrollBox.clientHeight - 300;
      if (scrollBox.scrollTop >= threshold) {
        renderedCount = appendCards(grid, allSpecies, renderedCount, PAGE_SIZE, scrollBox);
      }
    };
    scrollBox.addEventListener("scroll", scrollHandler);
  } else {
    scrollHandler = () => {
      if (renderedCount >= allSpecies.length) return;
      const scrollBottom = window.innerHeight + window.scrollY;
      const docHeight = document.documentElement.scrollHeight;
      if (scrollBottom >= docHeight - 400) {
        renderedCount = appendCards(grid, allSpecies, renderedCount, PAGE_SIZE);
      }
    };
    window.addEventListener("scroll", scrollHandler);
  }
}

function fillScrollArea(container) {
  // Keep appending cards until the scroll area is full or we run out
  const scrollBox = container.querySelector(".dex-widget-scroll");
  const grid = container.querySelector(".dex-grid");
  if (!scrollBox || !grid) return;
  const fill = () => {
    if (renderedCount >= allSpecies.length) return;
    if (scrollBox.scrollHeight <= scrollBox.clientHeight + 100) {
      renderedCount = appendCards(grid, allSpecies, renderedCount, PAGE_SIZE, scrollBox);
      requestAnimationFrame(fill);
    }
  };
  requestAnimationFrame(fill);
}

function renderGrid(container, species) {
  const grid = container.querySelector(".dex-grid");
  const results = container.querySelector(".dex-widget-results") || container.querySelector(".dex-results");
  const scrollBox = container.querySelector(".dex-widget-scroll");

  allSpecies = species;
  renderedCount = 0;

  if (!species.length) {
    grid.innerHTML = `<div class="dex-empty">No species match your search</div>`;
    if (results) results.textContent = "0 results";
    return;
  }

  // Build result text with active filter info
  let resultText = `${species.length} species`;
  if (activeTypes.length === 2) {
    resultText += ` (${activeTypes[0]} + ${activeTypes[1]})`;
  } else if (activeTypes.length === 1) {
    resultText += ` (${activeTypes[0]})`;
  }
  if (results) results.textContent = resultText;

  grid.innerHTML = "";
  renderedCount = appendCards(grid, species, 0, PAGE_SIZE, scrollBox);
  setupInfiniteScroll(container);
  // Ensure scroll area is filled (compact/list modes need more cards)
  fillScrollArea(container);
}

async function fetchAndRender(container, query) {
  const grid = container.querySelector(".dex-grid");

  // Use cached list for unfiltered view
  if (!query && cachedSpecies) {
    renderGrid(container, cachedSpecies);
    return;
  }

  grid.innerHTML = `<div class="dex-empty">Loading...</div>`;

  const path = query ? `/species?q=${encodeURIComponent(query)}` : "/species";
  const res = await api(path);

  if (!res.ok) {
    grid.innerHTML = `<div class="dex-empty">Error: ${esc(res.error)}</div>`;
    return;
  }

  if (!query) cachedSpecies = res.data;
  renderGrid(container, res.data);
}

// ---------------------------------------------------------------------------
// Stat bar helpers
// ---------------------------------------------------------------------------

function statColour(val) {
  if (val >= 150) return "#6890F0";
  if (val >= 120) return "#98D8D8";
  if (val >= 90)  return "#78C850";
  if (val >= 60)  return "#E0C068";
  if (val >= 30)  return "#F8D030";
  return "#F08030";
}

function renderStatBars(data) {
  let bst = 0;
  const rows = STAT_KEYS.map((key, i) => {
    const val = data[key] || 0;
    bst += val;
    const pct = Math.min(100, (val / 255) * 100);
    const col = statColour(val);
    return `<div class="stat-row">
      <span class="stat-label">${STAT_LABELS[i]}</span>
      <span class="stat-num">${val}</span>
      <div class="stat-bar"><div class="stat-fill" style="width:${pct}%;background:${col}"></div></div>
    </div>`;
  }).join("");
  return rows + `<div class="stat-row bst-row">
    <span class="stat-label">BST</span>
    <span class="stat-num bst-num">${data.bst || bst}</span>
    <div class="stat-bar" style="background:none"></div>
  </div>`;
}

// ---------------------------------------------------------------------------
// Abilities (detail view helpers)
// ---------------------------------------------------------------------------

function renderAbilities(named) {
  if (!named || !named.length) return "---";
  const parts = [named[0]];
  if (named.length > 1 && named[1] !== named[0]) parts.push(named[1]);
  let result = parts.join(" / ");
  if (named.length > 2 && named[2]) {
    result += ` / ${named[2]} (H)`;
  }
  return result;
}

function renderAbilitiesDescribed(abilities) {
  if (!abilities || !abilities.length) return `<p>---</p>`;
  // Deduplicate (ability 1 and 2 can be the same)
  const seen = new Set();
  const unique = [];
  for (const a of abilities) {
    if (!seen.has(a.const)) {
      seen.add(a.const);
      unique.push(a);
    }
  }
  const isHidden = (idx) => idx === unique.length - 1 && abilities.length > 2;
  return unique.map((a, i) => {
    const hidden = isHidden(i) ? ` <span class="ability-hidden">(Hidden)</span>` : "";
    const desc = a.description
      ? `<span class="ability-desc">${a.description}</span>`
      : "";
    return `<div class="ability-item">
      <span class="ability-name">${a.name}${hidden}</span>
      ${desc}
    </div>`;
  }).join("");
}

function formLabel(formConst, baseName) {
  const info = detectFormInfo(formConst, baseName);
  if (info.badge) return `${info.badge} ${info.name}`;
  return info.name || baseName;
}

const FORM_SPRITE_ROW_MAX = 8;

function renderFormNav(d) {
  if (!d.forms || d.forms.length <= 1) return "";
  const currentIndex = d.forms.indexOf(d.const);
  if (currentIndex < 0) return "";
  const baseName = d.form_names?.[0] || d.name;

  // For many forms (Alcremie 63, Unown 28, Vivillon 20) use a dropdown
  if (d.forms.length > FORM_SPRITE_ROW_MAX) {
    const options = d.forms.map((fc, i) => {
      const label = i === 0 ? baseName : formLabel(fc, baseName);
      const selected = fc === d.const ? " selected" : "";
      return `<option value="${fc}"${selected}>${label}</option>`;
    }).join("");
    return `<div class="form-nav">
      <select class="form-select">${options}</select>
      <span class="form-indicator">${currentIndex + 1} / ${d.forms.length}</span>
    </div>`;
  }

  // Visual sprite row for <=8 forms
  const items = d.forms.map((fc, i) => {
    const active = fc === d.const ? " form-thumb-active" : "";
    const label = i === 0 ? baseName : formLabel(fc, baseName);
    const spritePath = d.form_sprites?.[i] || "";
    const spriteUrl = spritePath ? `/api/sprites/${spritePath}` : "";
    return `<div class="form-thumb${active}" data-form="${fc}" title="${label}">
      <img src="${PLACEHOLDER_SVG}" data-form-sprite="${spriteUrl}" alt="${label}">
      <span class="form-thumb-label">${label}</span>
    </div>`;
  }).join("");

  return `<div class="form-row">${items}</div>`;
}

function setupFormNav(container, d) {
  if (!d.forms || d.forms.length <= 1) return;

  if (d.forms.length > FORM_SPRITE_ROW_MAX) {
    // Dropdown mode
    const select = container.querySelector(".form-select");
    if (select) {
      select.addEventListener("change", () => {
        window.location.hash = `#/dex/${select.value}`;
      });
    }
  } else {
    // Sprite row mode -- click thumbnails to navigate
    const thumbs = container.querySelectorAll(".form-thumb");
    thumbs.forEach(thumb => {
      thumb.addEventListener("click", () => {
        const fc = thumb.dataset.form;
        if (fc && fc !== d.const) {
          window.location.hash = `#/dex/${fc}`;
        }
      });
      // Process sprite (clip + bg removal)
      const img = thumb.querySelector("img[data-form-sprite]");
      if (img && img.dataset.formSprite) {
        processSprite(img.dataset.formSprite).then(dataUrl => {
          img.src = dataUrl;
        }).catch(() => {
          img.src = ERROR_SVG;
        });
      }
    });
  }
}

// ---------------------------------------------------------------------------
// Details section helpers
// ---------------------------------------------------------------------------

function formatGender(ratio) {
  if (!ratio) return "---";
  if (ratio === "MON_MALE" || ratio === "MON_GENDERLESS") {
    if (ratio === "MON_MALE") return "100% M";
    return "Genderless";
  }
  if (ratio === "MON_FEMALE") return "100% F";
  const m = ratio.match(/PERCENT_FEMALE\((\d+(?:\.\d+)?)\)/);
  if (m) {
    const f = parseFloat(m[1]);
    return `${(100 - f).toFixed(1)}% M / ${f.toFixed(1)}% F`;
  }
  // Numeric ratio (0-254 scale used in expansion)
  if (typeof ratio === "number") {
    if (ratio === 0) return "100% M";
    if (ratio === 254) return "100% F";
    if (ratio === 255) return "Genderless";
    const fPct = (ratio / 254 * 100).toFixed(1);
    return `${(100 - fPct).toFixed(1)}% M / ${fPct}% F`;
  }
  return String(ratio);
}

function formatEvYield(evs) {
  if (!evs || typeof evs !== "object") return "None";
  const labels = {hp:"HP", atk:"Atk", def:"Def", spa:"SpA", spd:"SpD", spe:"Spe"};
  const parts = [];
  for (const [k, v] of Object.entries(evs)) {
    if (v > 0) parts.push(`+${v} ${labels[k] || k}`);
  }
  return parts.length ? parts.join(", ") : "None";
}

function formatEggGroups(groups) {
  if (!groups || !groups.length) return "---";
  return groups.map(g => {
    if (g.startsWith("EGG_GROUP_")) g = g.slice(10);
    return g.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  }).join(", ");
}

function formatGrowthRate(rate) {
  if (!rate) return "---";
  let s = rate;
  if (s.startsWith("GROWTH_")) s = s.slice(7);
  return s.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// Evolution chain
// ---------------------------------------------------------------------------

function renderEvoChain(chain) {
  if (!chain || chain.length <= 1) {
    if (!chain || !chain.length) return `<span class="evo-none">Does not evolve</span>`;
  }
  return chain.map((entry, i) => {
    const link = `<a href="#/dex/${entry.const}" class="evo-species">${entry.name}</a>`;
    if (i === 0) return link;
    const arrow = evoArrow(entry.method, entry.param);
    return `<span class="evo-arrow">${arrow}</span>${link}`;
  }).join("");
}

function evoArrow(method, param) {
  if (!method) return " > ";
  if (method === "LEVEL") return param === "0" ? " Level > " : ` Lv.${param} > `;
  if (method === "ITEM" || method === "USE_ITEM") return ` ${constToName(param, "ITEM_")} > `;
  if (method === "TRADE") return " Trade > ";
  if (method === "TRADE_ITEM") return ` Trade w/${constToName(param, "ITEM_")} > `;
  if (method === "FRIENDSHIP") return " Friendship > ";
  if (method === "MOVE") return ` Know ${constToName(param, "MOVE_")} > `;
  if (method === "USE_ITEM_MALE") return ` ${constToName(param, "ITEM_")} (M) > `;
  if (method === "USE_ITEM_FEMALE") return ` ${constToName(param, "ITEM_")} (F) > `;
  return ` ${method} > `;
}

function constToName(c, prefix) {
  if (c && c.startsWith(prefix)) {
    return c.slice(prefix.length).replace(/_/g, " ").replace(/\b\w/g, ch => ch.toUpperCase());
  }
  return c || "???";
}

// ---------------------------------------------------------------------------
// Learnset tabs
// ---------------------------------------------------------------------------

async function loadLearnset(speciesConst, ltype) {
  const key = `${speciesConst}/${ltype}`;
  if (learnsetCache[key]) return learnsetCache[key];
  const res = await api(`/species/${speciesConst}/learnset/${ltype}`);
  if (res.ok) {
    learnsetCache[key] = res.data;
    return res.data;
  }
  return [];
}

function renderLearnsetTable(data, ltype) {
  if (!data || !data.length) return `<div class="learnset-empty">No data available</div>`;
  const rows = data.map(m => {
    const typeColour = TYPE_COLOURS[m.type] || "#888";
    const catClass = `dex-move-cat-${(m.category || "physical").toLowerCase()}`;
    const power = m.power ? m.power : "—";
    const accuracy = m.accuracy ? m.accuracy : "—";
    const pp = m.pp ? m.pp : "—";
    const levelBadge = ltype === "level_up"
      ? `<span class="ls-level-badge">Lv.${m.level}</span>` : "";
    const desc = m.description || "";
    return `<div class="ls-row" style="border-left-color: ${typeColour}">
      <div class="ls-row-top">
        ${levelBadge}<span class="ls-type-pip" style="background:${typeColour}">${m.type || "?"}</span><span class="ls-name">${m.name}</span><span class="dex-move-cat ${catClass}"></span><span class="ls-stats"><span>Pwr ${power}</span><span>Acc ${accuracy}</span><span>PP ${pp}</span></span>
      </div>
      ${desc ? `<div class="ls-row-desc">${desc}</div>` : ""}
    </div>`;
  }).join("");
  return `<div class="learnset-move-list">${rows}</div>`;
}

function setupLearnsetTabs(container, speciesConst) {
  const tabs = container.querySelectorAll(".learnset-tab");
  const body = container.querySelector(".learnset-body");
  let activeType = "level_up";

  tabs.forEach(tab => {
    tab.addEventListener("click", async () => {
      const ltype = tab.dataset.ltype;
      if (ltype === activeType) return;
      activeType = ltype;
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      body.innerHTML = `<div class="learnset-loading">Loading...</div>`;
      const data = await loadLearnset(speciesConst, ltype);
      body.innerHTML = renderLearnsetTable(data, ltype);
    });
  });
}

// ---------------------------------------------------------------------------
// Form badge detection
// ---------------------------------------------------------------------------

function detectFormInfo(speciesConst, displayName) {
  const c = speciesConst.toUpperCase();
  let badge = "";
  let suffix = "";

  if (c.includes("_MEGA_X")) { badge = "Mega"; suffix = "X"; }
  else if (c.includes("_MEGA_Y")) { badge = "Mega"; suffix = "Y"; }
  else if (c.includes("_MEGA")) { badge = "Mega"; }
  else if (c.includes("_GMAX") || c.includes("_GIGANTAMAX")) { badge = "Gmax"; }
  else if (c.includes("_ALOLA")) { badge = "Alolan"; }
  else if (c.includes("_GALAR")) { badge = "Galarian"; }
  else if (c.includes("_HISUI")) { badge = "Hisuian"; }
  else if (c.includes("_PALDEA")) { badge = "Paldean"; }
  else if (c.includes("_PRIMAL")) { badge = "Primal"; }

  // Build the display name: "Charizard X" not just "Charizard"
  let name = displayName;
  if (suffix && !name.endsWith(` ${suffix}`)) {
    name = `${displayName} ${suffix}`;
  }

  return { badge, name };
}

function renderFormBadge(badge) {
  if (!badge) return "";
  const cls = `form-badge form-badge-${badge.toLowerCase()}`;
  return `<span class="${cls}">${badge}</span>`;
}

// ---------------------------------------------------------------------------
// Detail card
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Cry playback
// ---------------------------------------------------------------------------

function isMuted() {
  const val = localStorage.getItem("torch-dex-mute");
  // Default to muted (no auto-play) on first visit
  return val !== "false";
}

function playCryManual(speciesConst) {
  // Always plays — called by the ♪ button
  const audio = new Audio(`/api/cries/${speciesConst}`);
  audio.volume = 0.5;
  audio.play().catch(() => {});
}

function playCryAuto(speciesConst) {
  // Only plays if auto-play is enabled (not muted)
  if (isMuted()) return;
  playCryManual(speciesConst);
}

function playRandomAnimation(img) {
  if (!img || !img.dataset) return;
  const f1 = img.dataset.frame1 || img.src;
  const f2 = img.dataset.frame2;
  if (!f2) return;
  const pattern = Math.floor(Math.random() * 3);
  if (pattern === 0) {
    setTimeout(() => { img.src = f2; }, 80);
    setTimeout(() => { img.src = f1; }, 230);
  } else if (pattern === 1) {
    setTimeout(() => { img.src = f2; }, 120);
    setTimeout(() => { img.src = f1; }, 240);
    setTimeout(() => { img.src = f2; }, 340);
    setTimeout(() => { img.src = f1; }, 460);
  } else {
    setTimeout(() => { img.src = f2; }, 60);
    setTimeout(() => { img.src = f1; }, 410);
  }
}

// Speaker icon for mute state — used across hub card and in-page toggle
const ICON_UNMUTED = "\uD83D\uDD0A"; // 🔊
const ICON_MUTED   = "\uD83D\uDD07"; // 🔇

function _updateMuteBtn(btn, muted) {
  btn.textContent = muted ? ICON_MUTED : ICON_UNMUTED;
  btn.title = muted ? "Cries: Manual (click to auto-play)" : "Cries: Auto (click for manual only)";
  btn.classList.toggle("dex-muted", muted);
}

// Compact icon toggle for grid & detail views
function createMuteButton() {
  const btn = document.createElement("button");
  btn.className = "dex-mute-btn";
  _updateMuteBtn(btn, isMuted());
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const wasMuted = isMuted();
    localStorage.setItem("torch-dex-mute", wasMuted ? "false" : "true");
    _updateMuteBtn(btn, !wasMuted);
    // Sync any other mute buttons on the page
    document.querySelectorAll(".dex-mute-btn, .dex-hub-cries-zone").forEach(el => {
      if (el !== btn) _updateMuteBtn(el, !wasMuted);
    });
  });
  return btn;
}

async function renderDetail(container, speciesConst) {
  container.innerHTML = `<article><div class="dex-empty">Loading...</div></article>`;

  const [specRes, lsRes] = await Promise.all([
    api(`/species/${speciesConst}`),
    api(`/species/${speciesConst}/learnset/level_up`),
  ]);

  if (!specRes.ok) {
    container.innerHTML = `<article>
      <p>Error: ${specRes.error}</p>
      <p><a href="#/dex/pokemon" class="detail-back">Back to Pokemon</a></p>
    </article>`;
    return;
  }

  const d = specRes.data;
  const levelUpData = lsRes.ok ? lsRes.data : [];
  // Cache it
  learnsetCache[`${speciesConst}/level_up`] = levelUpData;

  const types = (d.types || []).map(t => {
    const bg = TYPE_COLOURS[t] || "#888";
    return `<span class="type-badge" style="background:${bg}">${t}</span>`;
  }).join(" ");

  const dexNum = d.nat_dex_num ? padDexNum(d.nat_dex_num) : "#---";
  const heightM = ((d.height || 0) / 10).toFixed(1);
  const weightKg = ((d.weight || 0) / 10).toFixed(1);

  const formInfo = detectFormInfo(speciesConst, d.name);
  const displayName = formInfo.name;
  const badgeHtml = renderFormBadge(formInfo.badge);

  container.innerHTML = `<article class="dex-detail">
    <a href="#/dex/pokemon" class="detail-back">Back to Pokemon</a>

    <div class="dex-detail-header">
      <div class="dex-detail-sprite-wrap">
        <img src="${PLACEHOLDER_SVG}" data-detail-sprite="/api/sprites/${d.sprite_path}" alt="${displayName}">
      </div>
      <div class="dex-detail-info">
        ${badgeHtml}
        <h2>${displayName} <span class="dex-detail-num">${dexNum}</span></h2>
        <div class="dex-types">${types}</div>
      </div>
    </div>

    ${renderFormNav(d)}

    ${d.description ? `<p class="dex-entry-text">${d.description}</p>` : ""}

    <div class="dex-detail-section">
      <h3>Stats</h3>
      ${renderStatBars(d)}
    </div>

    <div class="dex-detail-section">
      <h3>Abilities</h3>
      ${d.abilities_described ? renderAbilitiesDescribed(d.abilities_described) : `<p>${renderAbilities(d.abilities_named)}</p>`}
    </div>

    <div class="dex-detail-section">
      <h3>Details</h3>
      <div class="detail-grid">
        <span>Height</span><span>${heightM}m</span>
        <span>Weight</span><span>${weightKg}kg</span>
        <span>Catch Rate</span><span>${d.catch_rate ?? "---"}</span>
        <span>Friendship</span><span>${d.friendship ?? "---"}</span>
        <span>Egg Groups</span><span>${formatEggGroups(d.egg_groups)}</span>
        <span>Growth Rate</span><span>${formatGrowthRate(d.growth_rate)}</span>
        <span>Gender</span><span>${formatGender(d.gender_ratio)}</span>
        <span>EV Yield</span><span>${formatEvYield(d.evs)}</span>
      </div>
    </div>

    <div class="dex-detail-section">
      <h3>Evolution</h3>
      <div class="evo-chain">${renderEvoChain(d.evolution_chain)}</div>
    </div>

    <div class="dex-detail-section">
      <h3>Learnset</h3>
      <div class="learnset-tabs" id="learnset-tabs-placeholder"></div>
      <div class="learnset-body">
        ${renderLearnsetTable(levelUpData, "level_up")}
      </div>
    </div>
  </article>`;

  // Populate learnset tabs based on expansion version
  const hasTeachable = await versionGate(...MOVESET_REFACTOR);
  const tabsEl = container.querySelector("#learnset-tabs-placeholder");
  if (tabsEl) {
    tabsEl.id = "";
    let tabsHtml = '<button class="learnset-tab active" data-ltype="level_up">Level Up</button>';
    if (hasTeachable) {
      tabsHtml += '<button class="learnset-tab" data-ltype="teachable">TM/Tutor</button>';
    }
    tabsHtml += '<button class="learnset-tab" data-ltype="egg">Egg Moves</button>';
    tabsEl.innerHTML = tabsHtml;
  }

  setupLearnsetTabs(container, speciesConst);
  setupFormNav(container, d);

  // Add mute button to the detail page
  const detailArticle = container.querySelector(".dex-detail");
  if (detailArticle) {
    detailArticle.style.position = "relative";
    detailArticle.appendChild(createMuteButton());
  }

  // Process detail sprite (clip + remove background) with auto-animate
  const detailImg = container.querySelector("[data-detail-sprite]");
  if (detailImg) {
    const spriteUrl = detailImg.dataset.detailSprite;

    // Add cry button to sprite container
    const spriteWrap = container.querySelector(".dex-detail-sprite-wrap");
    if (spriteWrap) {
      spriteWrap.style.position = "relative";
      const cryBtn = document.createElement("button");
      cryBtn.className = "dex-cry-btn";
      cryBtn.textContent = "\u266A";
      cryBtn.title = "Play cry";
      cryBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        playCryManual(speciesConst);
        playRandomAnimation(detailImg);
      });
      spriteWrap.appendChild(cryBtn);

      // Shiny toggle button
      const shinyBtn = document.createElement("button");
      shinyBtn.className = "dex-shiny-btn";
      shinyBtn.textContent = "\u2728";
      shinyBtn.title = "Toggle shiny sprite";
      let isShiny = false;
      shinyBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        isShiny = !isShiny;
        shinyBtn.classList.toggle("active", isShiny);
        const baseSpriteUrl = `/api/sprites/${d.sprite_path}`;
        const targetUrl = isShiny ? baseSpriteUrl + (baseSpriteUrl.includes("?") ? "&" : "?") + "shiny=1" : baseSpriteUrl;
        processSprite(targetUrl).then(dataUrl => {
          detailImg.src = dataUrl;
          detailImg.dataset.frame1 = dataUrl;
          processSpriteFrames(targetUrl).then(frames => {
            if (frames.frame2) {
              detailImg.dataset.frame2 = frames.frame2;
            } else {
              delete detailImg.dataset.frame2;
            }
          }).catch(() => {});
        }).catch(() => {});
      });
      spriteWrap.appendChild(shinyBtn);
    }

    processSprite(spriteUrl).then(dataUrl => {
      detailImg.src = dataUrl;
      detailImg.dataset.frame1 = dataUrl;
      // Auto-animate: one random frame cycle after load
      processSpriteFrames(spriteUrl).then(frames => {
        if (frames.frame2) {
          detailImg.dataset.frame2 = frames.frame2;
          const f1 = frames.frame1;
          const f2 = frames.frame2;
          const pattern = Math.floor(Math.random() * 3);
          if (pattern === 0) {
            setTimeout(() => { detailImg.src = f2; }, 300);
            setTimeout(() => { detailImg.src = f1; }, 450);
          } else if (pattern === 1) {
            setTimeout(() => { detailImg.src = f2; }, 300);
            setTimeout(() => { detailImg.src = f1; }, 420);
            setTimeout(() => { detailImg.src = f2; }, 520);
            setTimeout(() => { detailImg.src = f1; }, 640);
          } else {
            setTimeout(() => { detailImg.src = f2; }, 250);
            setTimeout(() => { detailImg.src = f1; }, 600);
          }
        }
      }).catch(() => {});
      // Auto-play cry after sprite loads (respects mute setting)
      playCryAuto(speciesConst);
    }).catch(() => {
      detailImg.src = ERROR_SVG;
    });
  }
}

// ---------------------------------------------------------------------------
// Hub page -- category cards
// ---------------------------------------------------------------------------

const HUB_CATEGORIES = [
  { key: "pokemon",   icon: "\u2B21", label: "Pokemon",   endpoint: "/species",   countKey: null },
  { key: "moves",     icon: "\u2694", label: "Moves",     endpoint: "/moves",     countKey: null },
  { key: "abilities", icon: "\u2726", label: "Abilities", endpoint: "/abilities", countKey: null },
  { key: "items",     icon: "\u25C6", label: "Items",     endpoint: "/items",     countKey: null },
  { key: "learnsets", icon: "\u270E", label: "Learnsets", endpoint: "/species",   countKey: null },
];

async function renderHub(container) {
  // Render the shell immediately so the user sees something
  const cards = HUB_CATEGORIES.map(cat => {
    const cls = `dex-hub-card dex-hub-card-${cat.key}`;
    // Pokemon card gets an integrated cries zone in the bottom quarter
    const criesZone = cat.key === "pokemon"
      ? `<div class="dex-hub-cries-zone" title="Toggle auto-play cries">${isMuted() ? ICON_MUTED : ICON_UNMUTED}</div>`
      : "";
    return `<div class="${cls}" data-hub="${cat.key}">
      <span class="dex-hub-icon">${cat.icon}</span>
      <span class="dex-hub-label">${cat.label}</span>
      <span class="dex-hub-count" data-hub-count="${cat.key}">...</span>
      ${criesZone}
    </div>`;
  }).join("");

  container.innerHTML = `<article class="dex-hub-article">
    <div class="dex-hub">${cards}</div>
  </article>`;

  // Wire up the cries zone on the Pokemon card
  const criesZone = container.querySelector(".dex-hub-cries-zone");
  if (criesZone) {
    _updateMuteBtn(criesZone, isMuted());
    criesZone.addEventListener("click", (e) => {
      e.stopPropagation();
      const wasMuted = isMuted();
      localStorage.setItem("torch-dex-mute", wasMuted ? "false" : "true");
      _updateMuteBtn(criesZone, !wasMuted);
    });
  }

  // Wire up click handlers — Pokemon card uses zone-based hit detection
  container.querySelectorAll(".dex-hub-card").forEach(card => {
    card.addEventListener("click", (e) => {
      // If the click was on the cries zone, don't navigate
      if (e.target.closest(".dex-hub-cries-zone")) return;
      const key = card.dataset.hub;
      if (key === "moves") { window.location.hash = "#/moves"; return; }
      if (key === "items") { window.location.hash = "#/items"; return; }
      if (key === "learnsets") { window.location.hash = "#/learnsets"; return; }
      window.location.hash = "#/dex/" + key;
    });
  });

  // Fetch counts in parallel
  const fetches = HUB_CATEGORIES.map(cat => api(cat.endpoint));
  const results = await Promise.all(fetches);

  results.forEach((res, i) => {
    const cat = HUB_CATEGORIES[i];
    const countEl = container.querySelector(`[data-hub-count="${cat.key}"]`);
    if (countEl && res.ok && Array.isArray(res.data)) {
      countEl.textContent = cat.key === "learnsets" ? "Editor" : res.data.length + " entries";
    } else if (countEl) {
      countEl.textContent = "";
    }
  });

  // Async: fetch a random Pokemon sprite for the Pokemon card
  _loadHubPokemonSprite(container);
  // Async: fetch a random item icon for the Items card
  _loadHubItemIcon(container);
}

/** Load a random Pokemon sprite onto the Pokemon hub card (non-blocking). */
async function _loadHubPokemonSprite(container) {
  try {
    const res = await api("/random-sprites?count=1");
    if (!res.ok || !res.data.length) return;
    const pick = res.data[0];
    const card = container.querySelector(".dex-hub-card-pokemon");
    if (!card) return;

    // Replace the icon with a sprite image
    const iconEl = card.querySelector(".dex-hub-icon");
    if (iconEl) iconEl.style.display = "none";

    const img = document.createElement("img");
    img.className = "dex-hub-sprite";
    img.alt = pick.name;
    img.src = PLACEHOLDER_SVG;
    card.insertBefore(img, card.querySelector(".dex-hub-label"));

    // Process sprite (bg removal)
    const spriteUrl = `/api/sprites/${pick.sprite_path}`;
    processSprite(spriteUrl).then(dataUrl => { img.src = dataUrl; }).catch(() => {});

    // Apply type colour to card border
    const primaryType = (pick.types && pick.types[0]) || "";
    const typeColour = TYPE_COLOURS[primaryType];
    if (typeColour) {
      card.style.setProperty("--dex-hub-type-color", typeColour);
    }
  } catch (_e) { /* non-blocking */ }
}

/** Load a random item icon onto the Items hub card (non-blocking). */
async function _loadHubItemIcon(container) {
  try {
    const res = await api("/random-items?count=1");
    if (!res.ok || !res.data.length) return;
    const pick = res.data[0];
    const card = container.querySelector(".dex-hub-card-items");
    if (!card) return;

    // Replace the icon with an item image
    const iconEl = card.querySelector(".dex-hub-icon");
    if (iconEl) iconEl.style.display = "none";

    const img = document.createElement("img");
    img.className = "dex-hub-item-icon";
    img.alt = pick.name;
    img.src = pick.icon;
    card.insertBefore(img, card.querySelector(".dex-hub-label"));

    // Process icon (bg removal)
    processSprite(pick.icon).then(dataUrl => { img.src = dataUrl; }).catch(() => {});
  } catch (_e) { /* non-blocking */ }
}

// ---------------------------------------------------------------------------
// Species grid (relocated from default render)
// ---------------------------------------------------------------------------

async function refilterGrid(container) {
  const searchInput = container.querySelector(".dex-widget-search");
  const query = searchInput ? searchInput.value.trim() : "";

  let source;
  if (query && !isSimpleSearch(query)) {
    // Advanced query — hit server
    const res = await api(`/species?q=${encodeURIComponent(query)}`);
    source = res.ok ? res.data : [];
  } else if (query) {
    // Simple name search — client-side
    const q = query.toLowerCase();
    source = (cachedSpecies || []).filter(sp => sp.name.toLowerCase().includes(q));
  } else {
    source = cachedSpecies || [];
  }

  const filtered = filterAndSortSpecies(source);
  renderGrid(container, filtered);
}

function updateTypeChipStyles(container) {
  container.querySelectorAll(".dex-type-chip").forEach(chip => {
    const t = chip.dataset.type;
    if (t === "") {
      // "All" chip — active when no types selected
      chip.classList.toggle("active", activeTypes.length === 0);
    } else {
      chip.classList.toggle("active", activeTypes.includes(t));
    }
  });
}

function updateGenChipStyles(container) {
  container.querySelectorAll(".dex-gen-chip").forEach(chip => {
    chip.classList.toggle("active", activeGen === parseInt(chip.dataset.gen));
  });
}

// Persist search query across detail navigation
let _savedSearchQuery = "";

async function renderSpeciesGrid(container) {
  // Only reset filter state on fresh entry (no cached data)
  // When returning from a detail page, cachedSpecies is still populated
  if (!cachedSpecies) {
    activeTypes = [];
    activeGen = null;
    activeSortMode = "dex";
    _savedSearchQuery = "";
  }

  const typeChips = [`<button class="dex-type-chip${activeTypes.length === 0 ? " active" : ""}" data-type="">All</button>`]
    .concat(ALL_TYPES.map(t => {
      const bg = TYPE_COLOURS[t];
      const active = activeTypes.includes(t) ? " active" : "";
      return `<button class="dex-type-chip${active}" data-type="${t}" style="--chip-color:${bg}">${t}</button>`;
    })).join("");

  const genChips = Array.from({length: 9}, (_, i) => i + 1).map(g =>
    `<button class="dex-gen-chip${activeGen === g ? " active" : ""}" data-gen="${g}">Gen ${g}</button>`
  ).join("");

  container.innerHTML = `<article>
    <div class="dex-widget">
      <div class="dex-widget-header">
        <a href="#/dex" class="dex-widget-back">\u2190</a>
        <h2 class="dex-widget-title">Pokemon</h2>
        <div class="dex-widget-toolbar">
          <input type="text" class="dex-widget-search" placeholder="Search... (name, type:fire, ability:overgrow, bst>500)">
          <select class="dex-sort-select">
            <option value="dex">Dex #</option>
            <option value="name-az">Name A\u2013Z</option>
            <option value="name-za">Name Z\u2013A</option>
            <option value="bst-desc">BST \u2193</option>
            <option value="bst-asc">BST \u2191</option>
          </select>
        </div>
      </div>
      <div class="dex-widget-scroll">
        <div class="dex-grid"></div>
      </div>
      <div class="dex-widget-footer">
        <div class="dex-type-chips">${typeChips}</div>
        <div class="dex-gen-chips">${genChips}<span class="dex-widget-results"></span></div>
      </div>
    </div>
  </article>`;

  // Add view mode toggle + mute button to toolbar
  const toolbar = container.querySelector(".dex-widget-toolbar");
  if (toolbar) {
    const VIEW_MODES = ["normal", "compact", "list"];
    const VIEW_ICONS = { normal: "\u25A6", compact: "\u2637", list: "\u2630" };
    const VIEW_TITLES = { normal: "Normal view", compact: "Compact view", list: "List view" };

    const viewBtn = document.createElement("button");
    viewBtn.className = "dex-view-btn";
    let viewMode = localStorage.getItem("torch-dex-view") || "normal";
    if (!VIEW_MODES.includes(viewMode)) viewMode = "normal";

    function applyViewMode(mode) {
      const scroll = container.querySelector(".dex-widget-scroll");
      if (!scroll) return;
      scroll.classList.remove("dex-compact", "dex-list");
      if (mode === "compact") scroll.classList.add("dex-compact");
      if (mode === "list") scroll.classList.add("dex-list");
      // Show icon for the NEXT mode (what clicking will switch to)
      const nextIdx = (VIEW_MODES.indexOf(mode) + 1) % VIEW_MODES.length;
      const next = VIEW_MODES[nextIdx];
      viewBtn.textContent = VIEW_ICONS[mode];
      viewBtn.title = `${VIEW_TITLES[mode]} (click for ${VIEW_TITLES[next].toLowerCase()})`;
      localStorage.setItem("torch-dex-view", mode);
      fillScrollArea(container);
    }

    viewBtn.addEventListener("click", () => {
      const nextIdx = (VIEW_MODES.indexOf(viewMode) + 1) % VIEW_MODES.length;
      viewMode = VIEW_MODES[nextIdx];
      applyViewMode(viewMode);
    });

    toolbar.appendChild(viewBtn);
    toolbar.appendChild(createMuteButton());
    applyViewMode(viewMode);
  }

  // --- Wire up type chips ---
  container.querySelectorAll(".dex-type-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const t = chip.dataset.type;
      if (t === "") {
        // "All" — clear type filter
        activeTypes = [];
      } else if (activeTypes.includes(t)) {
        // Deselect
        activeTypes = activeTypes.filter(x => x !== t);
      } else if (activeTypes.length >= 2) {
        // FIFO: drop oldest, add new
        activeTypes = [activeTypes[1], t];
      } else {
        activeTypes.push(t);
      }
      updateTypeChipStyles(container);
      refilterGrid(container);
    });
  });

  // --- Wire up gen chips ---
  container.querySelectorAll(".dex-gen-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const g = parseInt(chip.dataset.gen);
      activeGen = (activeGen === g) ? null : g;
      updateGenChipStyles(container);
      refilterGrid(container);
    });
  });

  // --- Wire up sort ---
  const sortSelect = container.querySelector(".dex-sort-select");
  if (sortSelect) {
    sortSelect.addEventListener("change", () => {
      activeSortMode = sortSelect.value;
      refilterGrid(container);
    });
  }

  // --- Wire up search ---
  const searchInput = container.querySelector(".dex-widget-search");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      _savedSearchQuery = searchInput.value;
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => refilterGrid(container), 300);
    });
  }

  // Restore previous state when returning from detail page
  if (cachedSpecies) {
    if (searchInput && _savedSearchQuery) searchInput.value = _savedSearchQuery;
    if (sortSelect) sortSelect.value = activeSortMode;
    updateTypeChipStyles(container);
    updateGenChipStyles(container);
  }

  // Initial data fetch
  if (!cachedSpecies) {
    const grid = container.querySelector(".dex-grid");
    if (grid) grid.innerHTML = `<div class="dex-empty">Loading...</div>`;
    const res = await api("/species");
    if (res.ok) {
      cachedSpecies = res.data;
    } else {
      if (grid) grid.innerHTML = `<div class="dex-empty">Error: ${esc(res.error)}</div>`;
      return;
    }
  }

  refilterGrid(container);

  // Restore scroll position after navigating back from a detail page
  if (savedScrollY > 0) {
    const scrollBox = container.querySelector(".dex-widget-scroll");
    const grid = container.querySelector(".dex-grid");
    if (scrollBox && grid) {
      while (renderedCount < allSpecies.length &&
             scrollBox.scrollHeight < savedScrollY + scrollBox.clientHeight) {
        renderedCount = appendCards(grid, allSpecies, renderedCount, PAGE_SIZE, scrollBox);
      }
    }
    const restoreY = savedScrollY;
    savedScrollY = 0;
    if (scrollBox) {
      requestAnimationFrame(() => scrollBox.scrollTo(0, restoreY));
    }
  }
}

// ---------------------------------------------------------------------------
// Generic list browser (moves, abilities, items)
// ---------------------------------------------------------------------------

// State for list browser infinite scroll
let browserAllItems = [];
let browserRenderedCount = 0;
let browserScrollHandler = null;

function cleanupBrowserScroll() {
  if (browserScrollHandler) {
    window.removeEventListener("scroll", browserScrollHandler);
    browserScrollHandler = null;
  }
}

function appendBrowserItems(list, items, start, count, renderFn) {
  const end = Math.min(start + count, items.length);
  const fragment = document.createDocumentFragment();
  for (let i = start; i < end; i++) {
    const div = document.createElement("div");
    div.className = "dex-browser-item";
    div.innerHTML = renderFn(items[i]);
    fragment.appendChild(div);
  }
  list.appendChild(fragment);
  return end;
}

function setupBrowserScroll(container, renderFn) {
  cleanupBrowserScroll();

  const list = container.querySelector(".dex-browser-list");
  if (!list) return;

  browserScrollHandler = () => {
    if (browserRenderedCount >= browserAllItems.length) return;
    const scrollBottom = window.innerHeight + window.scrollY;
    const docHeight = document.documentElement.scrollHeight;
    if (scrollBottom >= docHeight - 400) {
      browserRenderedCount = appendBrowserItems(
        list, browserAllItems, browserRenderedCount, PAGE_SIZE, renderFn
      );
    }
  };
  window.addEventListener("scroll", browserScrollHandler);
}

async function renderListBrowser(container, opts) {
  const { title, endpoint, renderItem, searchPlaceholder } = opts;

  container.innerHTML = `<article>
    <div class="dex-browser">
      <div class="dex-browser-header">
        <a href="#/dex" class="dex-browser-back">\u2190 Back to Dex</a>
        <h2>${title}</h2>
      </div>
      <input type="text" class="dex-browser-search" placeholder="${searchPlaceholder || "Search..."}">
      <div class="dex-browser-results"></div>
      <div class="dex-browser-list"></div>
    </div>
  </article>`;

  const searchInput = container.querySelector(".dex-browser-search");
  const resultInfo = container.querySelector(".dex-browser-results");
  const list = container.querySelector(".dex-browser-list");

  let fullCache = null;
  let browserDebounce = null;

  async function loadAndDisplay(query) {
    // Use cache for unfiltered
    if (!query && fullCache) {
      displayItems(fullCache);
      return;
    }

    list.innerHTML = `<div class="dex-empty">Loading...</div>`;
    const path = query ? `${endpoint}?q=${encodeURIComponent(query)}` : endpoint;
    const res = await api(path);

    if (!res.ok) {
      list.innerHTML = `<div class="dex-empty">Error: ${esc(res.error)}</div>`;
      resultInfo.textContent = "";
      return;
    }

    if (!query) fullCache = res.data;
    displayItems(res.data);
  }

  function displayItems(items) {
    browserAllItems = items;
    browserRenderedCount = 0;

    if (!items.length) {
      list.innerHTML = `<div class="dex-empty">No results</div>`;
      resultInfo.textContent = "0 results";
      return;
    }

    resultInfo.textContent = `${items.length} results`;
    list.innerHTML = "";
    browserRenderedCount = appendBrowserItems(list, items, 0, PAGE_SIZE, renderItem);
    setupBrowserScroll(container, renderItem);
  }

  searchInput.addEventListener("input", () => {
    clearTimeout(browserDebounce);
    browserDebounce = setTimeout(() => {
      loadAndDisplay(searchInput.value.trim());
    }, 300);
  });

  await loadAndDisplay("");
}

// ---------------------------------------------------------------------------
// Moves browser (rich cards with type filter)
// ---------------------------------------------------------------------------

const ALL_TYPES = [
  "Normal", "Fire", "Water", "Electric", "Grass", "Ice",
  "Fighting", "Poison", "Ground", "Flying", "Psychic", "Bug",
  "Rock", "Ghost", "Dragon", "Dark", "Steel", "Fairy",
];

let movesFullCache = null;     // complete unfiltered move list from API
let movesAllItems = [];        // current filtered/searched list for display
let movesRenderedCount = 0;
let movesScrollHandler = null;
let movesActiveType = null;    // active type filter (null = show all)
const MOVES_PAGE_SIZE = 60;

function cleanupMovesScroll() {
  if (movesScrollHandler) {
    window.removeEventListener("scroll", movesScrollHandler);
    movesScrollHandler = null;
  }
}

function renderMoveCard(move) {
  const typeColour = TYPE_COLOURS[move.type] || "#888";
  const catClass = `dex-move-cat-${(move.category || "physical").toLowerCase()}`;
  const power = move.power ? move.power : "--";
  const accuracy = move.accuracy ? move.accuracy : "--";
  const pp = move.pp ? move.pp : "--";

  return `<div class="dex-move-row" style="--dex-move-type-color: ${typeColour}; border-left-color: ${typeColour}">
    <div class="dex-move-top">
      <span class="type-badge" style="background:${typeColour}">${move.type || "Normal"}</span>
      <span class="dex-move-name">${move.name}</span>
      <span class="dex-move-cat ${catClass}" title="${move.category || "Physical"}"></span>
      <div class="dex-move-stats">
        <span class="dex-move-stat"><strong>Pwr</strong> ${power}</span>
        <span class="dex-move-stat"><strong>Acc</strong> ${accuracy}</span>
        <span class="dex-move-stat"><strong>PP</strong> ${pp}</span>
      </div>
    </div>
    ${move.description ? `<div class="dex-move-desc">${move.description}</div>` : ""}
  </div>`;
}

function appendMoveCards(list, items, start, count) {
  const end = Math.min(start + count, items.length);
  const fragment = document.createDocumentFragment();
  for (let i = start; i < end; i++) {
    const div = document.createElement("div");
    div.innerHTML = renderMoveCard(items[i]);
    fragment.appendChild(div.firstElementChild);
  }
  list.appendChild(fragment);
  return end;
}

function setupMovesScroll(container) {
  cleanupMovesScroll();
  const list = container.querySelector(".dex-browser-list");
  if (!list) return;

  movesScrollHandler = () => {
    if (movesRenderedCount >= movesAllItems.length) return;
    const scrollBottom = window.innerHeight + window.scrollY;
    const docHeight = document.documentElement.scrollHeight;
    if (scrollBottom >= docHeight - 400) {
      movesRenderedCount = appendMoveCards(
        list, movesAllItems, movesRenderedCount, MOVES_PAGE_SIZE
      );
    }
  };
  window.addEventListener("scroll", movesScrollHandler);
}

function displayMoves(container, items) {
  const list = container.querySelector(".dex-browser-list");
  const resultInfo = container.querySelector(".dex-browser-results");

  movesAllItems = items;
  movesRenderedCount = 0;

  if (!items.length) {
    list.innerHTML = `<div class="dex-empty">No moves match your search</div>`;
    resultInfo.textContent = "0 results";
    return;
  }

  resultInfo.textContent = `${items.length} moves`;
  list.innerHTML = "";
  movesRenderedCount = appendMoveCards(list, items, 0, MOVES_PAGE_SIZE);
  setupMovesScroll(container);
}

function filterMoves(container, query) {
  if (!movesFullCache) return;
  let items = movesFullCache;

  // Type filter
  if (movesActiveType) {
    items = items.filter(m => m.type === movesActiveType);
  }

  // Text search
  if (query) {
    const q = query.toLowerCase();
    items = items.filter(m =>
      m.name.toLowerCase().includes(q) ||
      m.const.toLowerCase().includes(q) ||
      (m.type || "").toLowerCase().includes(q) ||
      (m.description || "").toLowerCase().includes(q)
    );
  }

  displayMoves(container, items);
}

async function renderMovesBrowser(container) {
  // Build type filter buttons
  const typeButtons = ALL_TYPES.map(t => {
    const bg = TYPE_COLOURS[t] || "#888";
    return `<button class="dex-type-filter-btn" data-type="${t}" style="background:${bg}">${t}</button>`;
  }).join("");

  container.innerHTML = `<article>
    <div class="dex-browser">
      <div class="dex-browser-header">
        <a href="#/dex" class="dex-browser-back">\u2190 Back to Dex</a>
        <h2>Moves</h2>
      </div>
      <input type="text" class="dex-browser-search" placeholder="Search moves by name, type, or description...">
      <div class="dex-type-filter">${typeButtons}</div>
      <div class="dex-browser-results"></div>
      <div class="dex-browser-list"></div>
    </div>
  </article>`;

  const searchInput = container.querySelector(".dex-browser-search");
  const list = container.querySelector(".dex-browser-list");
  let movesDebounce = null;
  movesActiveType = null;

  // Wire up type filter buttons
  container.querySelectorAll(".dex-type-filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const t = btn.dataset.type;
      if (movesActiveType === t) {
        // Deselect
        movesActiveType = null;
        btn.classList.remove("active");
      } else {
        // Select new type, deselect others
        container.querySelectorAll(".dex-type-filter-btn").forEach(b => b.classList.remove("active"));
        movesActiveType = t;
        btn.classList.add("active");
      }
      filterMoves(container, searchInput.value.trim());
    });
  });

  // Wire up search
  searchInput.addEventListener("input", () => {
    clearTimeout(movesDebounce);
    movesDebounce = setTimeout(() => {
      filterMoves(container, searchInput.value.trim());
    }, 300);
  });

  // Fetch full move list
  list.innerHTML = `<div class="dex-empty">Loading...</div>`;
  const res = await api("/moves");
  if (!res.ok) {
    list.innerHTML = `<div class="dex-empty">Error: ${esc(res.error)}</div>`;
    return;
  }
  movesFullCache = res.data;
  displayMoves(container, movesFullCache);
}

// ---------------------------------------------------------------------------
// Abilities browser
// ---------------------------------------------------------------------------

function renderAbilityItem(ability) {
  const desc = ability.description
    ? `<span class="dex-browser-item-desc">${ability.description}</span>`
    : "";
  return `<span class="dex-browser-item-name">${ability.name}</span>` +
         `<span class="dex-browser-item-const">${ability.const}</span>` +
         desc;
}

async function renderAbilitiesBrowser(container) {
  await renderListBrowser(container, {
    title: "Abilities",
    endpoint: "/abilities",
    renderItem: renderAbilityItem,
    searchPlaceholder: "Search abilities...",
  });
}

// ---------------------------------------------------------------------------
// Items browser
// ---------------------------------------------------------------------------

function renderItemItem(item) {
  return `<span class="dex-browser-item-name">${item.name}</span>` +
         `<span class="dex-browser-item-const">${item.const}</span>`;
}

async function renderItemsBrowser(container) {
  await renderListBrowser(container, {
    title: "Items",
    endpoint: "/items",
    renderItem: renderItemItem,
    searchPlaceholder: "Search items...",
  });
}

// ---------------------------------------------------------------------------
// Main render (hub, grid, browsers, or detail)
// ---------------------------------------------------------------------------

export async function render(container) {
  const hash = window.location.hash || "";

  // Detail: #/dex/SPECIES_*
  if (hash.match(/^#\/dex\/SPECIES_/)) {
    return renderDetail(container, decodeURIComponent(hash.split("/").pop()));
  }

  // Sub-browsers
  if (hash === "#/dex/pokemon") return renderSpeciesGrid(container);
  if (hash === "#/dex/moves") return renderMovesBrowser(container);
  if (hash === "#/dex/abilities") return renderAbilitiesBrowser(container);
  if (hash === "#/dex/items") return renderItemsBrowser(container);

  // Default: hub
  return renderHub(container);
}

export function cleanup() {
  clearTimeout(debounceTimer);
  debounceTimer = null;
  if (scrollHandler) {
    // Try removing from widget scroll container first, then window
    const scrollBox = document.querySelector(".dex-widget-scroll");
    if (scrollBox) scrollBox.removeEventListener("scroll", scrollHandler);
    window.removeEventListener("scroll", scrollHandler);
    scrollHandler = null;
  }
  if (spriteObserver) {
    spriteObserver.disconnect();
    spriteObserver = null;
    _spriteObserverRoot = null;
  }
  cleanupBrowserScroll();
  cleanupMovesScroll();
  allSpecies = [];
  renderedCount = 0;
  // Preserve cachedSpecies, filters, scroll position, and search query
  // across intra-dex navigation (grid → detail → grid).
  // They are reset when the dex view is re-entered fresh (cachedSpecies
  // check in renderSpeciesGrid) or on full page reload.
  browserAllItems = [];
  browserRenderedCount = 0;
  movesFullCache = null;
  movesAllItems = [];
  movesRenderedCount = 0;
  movesActiveType = null;
}
