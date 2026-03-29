/**
 * TORCH Web GUI -- Encounter Editor view.
 * Map list with search, tabbed slot editor, species picker, write-back.
 */

import { api } from "../app.js";
import { esc } from "../utils.js";
import { processSprite } from "../spriteUtils.js";
import { renderStudioNavbar } from "../studioNav.js";

// ---------------------------------------------------------------------------
// Encounter rate presets & helpers
// ---------------------------------------------------------------------------

const RATE_PRESETS = [
  { label: "Very Common", value: 30 },
  { label: "Common",      value: 25 },
  { label: "Moderate",    value: 20 },
  { label: "Uncommon",    value: 15 },
  { label: "Rare",        value: 10 },
  { label: "Very Rare",   value: 5 },
];

const TYPE_COLOURS = {
  Normal: "#A8A878", Fire: "#F08030", Water: "#6890F0", Electric: "#F8D030",
  Grass: "#78C850", Ice: "#98D8D8", Fighting: "#C03028", Poison: "#A040A0",
  Ground: "#E0C068", Flying: "#A890F0", Psychic: "#F85888", Bug: "#A8B820",
  Rock: "#B8A038", Ghost: "#705898", Dragon: "#7038F8", Dark: "#705848",
  Steel: "#B8B8D0", Fairy: "#EE99AC",
};

const TYPE_GRADIENTS = {
  Normal:   { deep: "#8a8a6c", accent: "#A8A878" },
  Fire:     { deep: "#c4501a", accent: "#F08030" },
  Water:    { deep: "#4a6fc4", accent: "#6890F0" },
  Electric: { deep: "#c4a800", accent: "#F8D030" },
  Grass:    { deep: "#5a9830", accent: "#78C850" },
  Ice:      { deep: "#72b8b8", accent: "#98D8D8" },
  Fighting: { deep: "#9c2020", accent: "#C03028" },
  Poison:   { deep: "#803080", accent: "#A040A0" },
  Ground:   { deep: "#b8982e", accent: "#E0C068" },
  Flying:   { deep: "#8868d0", accent: "#A890F0" },
  Psychic:  { deep: "#d03868", accent: "#F85888" },
  Bug:      { deep: "#889810", accent: "#A8B820" },
  Rock:     { deep: "#968828", accent: "#B8A038" },
  Ghost:    { deep: "#584070", accent: "#705898" },
  Dragon:   { deep: "#5028c8", accent: "#7038F8" },
  Dark:     { deep: "#584038", accent: "#705848" },
  Steel:    { deep: "#9898b8", accent: "#B8B8D0" },
  Fairy:    { deep: "#c87098", accent: "#EE99AC" },
};

function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function slotRowStyle(sTypes) {
  if (!sTypes || !sTypes.length) return "";
  const g1 = TYPE_GRADIENTS[sTypes[0]] || TYPE_GRADIENTS.Normal;
  const g2 = sTypes[1] ? (TYPE_GRADIENTS[sTypes[1]] || TYPE_GRADIENTS.Normal) : null;
  // Species cell — gradient only for dual-type, flat tint for single
  const speciesBg = g2
    ? `linear-gradient(135deg, ${hexToRgba(g1.deep, 0.18)} 0%, ${hexToRgba(g1.deep, 0.07)} 40%, ${hexToRgba(g2.deep, 0.07)} 60%, ${hexToRgba(g2.deep, 0.18)} 100%)`
    : hexToRgba(g1.deep, 0.10);
  // Left border — gradient for dual-type, solid for single
  const border = g2
    ? `linear-gradient(to bottom, ${g1.accent}, ${g2.accent})`
    : `linear-gradient(to bottom, ${g1.accent}, ${g1.accent})`;
  return `--row-border:${border};--row-bg:${speciesBg}`;
}

function rateColor(pct) {
  if (pct >= 20) return "#4ade80";   // green -- common
  if (pct >= 10) return "#facc15";   // yellow -- moderate
  if (pct >= 5)  return "#f97316";   // orange -- uncommon
  return "#ef4444";                   // red -- rare
}

function speciesSpriteUrl(speciesConst) {
  if (!speciesConst || speciesConst === "SPECIES_NONE") return "";
  const name = speciesConst.replace("SPECIES_", "").toLowerCase();
  return `/api/sprites/${name}/anim_front.png`;
}

function folderToMapConst(folder) {
  // PascalCase folder → MAP_UPPER_SNAKE: Route33 → MAP_ROUTE33
  const snake = folder.replace(/([a-z])([A-Z])/g, "$1_$2");
  return "MAP_" + snake.toUpperCase();
}

let debounceTimer = null;
let allMaps = [];
let cachedMaps = null;   // full unfiltered list
let renderedCount = 0;
let scrollHandler = null;
let activeFilter = "all";    // "all" | "custom" | "vanilla"
let searchQuery = "";
let typeFilters = new Set();  // active encounter type filters
let typesRef = null;  // cached /api/encounters/types data
let dirty = false;
const PAGE_SIZE = 48;

const TYPE_LABELS = {
  land_mons: "Land", water_mons: "Water",
  fishing_mons: "Fish", rock_smash_mons: "Smash",
  honey_tree_mons: "Honey",
};

const TYPE_CSS = {
  land_mons: "enc-type-land", water_mons: "enc-type-water",
  fishing_mons: "enc-type-fishing", rock_smash_mons: "enc-type-rock",
  honey_tree_mons: "enc-type-honey",
};

// ---------------------------------------------------------------------------
// Map List view
// ---------------------------------------------------------------------------

function renderCard(m) {
  const badges = (m.types || []).map(t => {
    const label = TYPE_LABELS[t] || t;
    const cls = TYPE_CSS[t] || "";
    return `<span class="enc-type-badge ${cls}">${label}</span>`;
  }).join("");
  const statusBadge = m.is_custom
    ? `<span class="enc-badge enc-badge-custom">Custom</span>`
    : `<span class="enc-badge enc-badge-vanilla">Vanilla</span>`;
  return `<div class="enc-card" data-map="${m.map}">
    <div class="enc-card-name">${m.name}</div>
    <div class="enc-card-const">${m.map}</div>
    <div class="enc-card-types">${badges}</div>
    ${statusBadge}
  </div>`;
}

function appendCards(grid, maps, start, count) {
  const end = Math.min(start + count, maps.length);
  const fragment = document.createDocumentFragment();
  for (let i = start; i < end; i++) {
    const tmp = document.createElement("div");
    tmp.innerHTML = renderCard(maps[i]);
    const card = tmp.firstElementChild;
    card.addEventListener("click", () => {
      window.location.hash = `#/encounters/${card.dataset.map}`;
    });
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
  const grid = container.querySelector(".enc-grid");
  if (!grid) return;

  scrollHandler = () => {
    if (renderedCount >= allMaps.length) return;
    const scrollBottom = window.innerHeight + window.scrollY;
    const docHeight = document.documentElement.scrollHeight;
    if (scrollBottom >= docHeight - 400) {
      renderedCount = appendCards(grid, allMaps, renderedCount, PAGE_SIZE);
    }
  };
  window.addEventListener("scroll", scrollHandler);
}

function applyFilters(maps) {
  let result = maps;

  // Custom/vanilla filter
  if (activeFilter === "custom") result = result.filter(m => m.is_custom);
  else if (activeFilter === "vanilla") result = result.filter(m => !m.is_custom);

  // Encounter type filter
  if (typeFilters.size > 0) {
    result = result.filter(m =>
      [...typeFilters].every(t => (m.types || []).includes(t))
    );
  }

  // Search
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    result = result.filter(m =>
      m.name.toLowerCase().includes(q) || m.map.toLowerCase().includes(q)
    );
  }

  return result;
}

function renderGridContent(container, maps) {
  const grid = container.querySelector(".enc-grid");
  const results = container.querySelector(".enc-results");

  allMaps = maps;
  renderedCount = 0;

  const customCount = maps.filter(m => m.is_custom).length;
  const vanillaCount = maps.length - customCount;

  if (!maps.length) {
    grid.innerHTML = `<div class="enc-empty">No maps match your filters</div>`;
    results.textContent = "0 maps";
    return;
  }

  results.textContent = `${maps.length} maps (${customCount} custom, ${vanillaCount} vanilla)`;
  grid.innerHTML = "";
  renderedCount = appendCards(grid, maps, 0, PAGE_SIZE);
  setupInfiniteScroll(container);
}

function refreshList(container) {
  if (!cachedMaps) return;
  const filtered = applyFilters(cachedMaps);
  renderGridContent(container, filtered);
}

async function renderList(container) {
  container.innerHTML = `<article>
    ${renderStudioNavbar("Encounters")}
    <div class="enc-layout">
      <aside class="enc-filters">
        <input type="text" class="enc-search" placeholder="Search maps...">
        <div class="enc-filter-group">
          <button class="enc-filter-pill active" data-filter="all">All</button>
          <button class="enc-filter-pill" data-filter="custom">Custom Only</button>
          <button class="enc-filter-pill" data-filter="vanilla">Vanilla Only</button>
        </div>
        <div class="enc-type-filters"></div>
        <div class="enc-results"></div>
        <button class="enc-new-map-btn">+ New Map</button>
        <div class="enc-new-map-picker" style="display:none">
          <input type="text" class="enc-new-map-search" placeholder="Search all maps...">
          <div class="enc-new-map-results"></div>
        </div>
      </aside>
      <div class="enc-grid"></div>
    </div>
  </article>`;

  const grid = container.querySelector(".enc-grid");
  const searchInput = container.querySelector(".enc-search");
  const pills = container.querySelectorAll(".enc-filter-pill");
  const typeFiltersEl = container.querySelector(".enc-type-filters");

  // Loading state
  grid.innerHTML = `<div class="enc-empty">Loading...</div>`;

  const res = await api("/encounters");
  if (!res.ok) {
    grid.innerHTML = `<div class="enc-empty">Error: ${esc(res.error)}</div>`;
    return;
  }
  cachedMaps = res.data.maps || [];

  // Discover all encounter types present in the data
  const allTypes = new Set();
  for (const m of cachedMaps) {
    for (const t of (m.types || [])) allTypes.add(t);
  }

  // Render type filter checkboxes
  const sortedTypes = [...allTypes].sort();
  typeFiltersEl.innerHTML = sortedTypes.map(t => {
    const label = TYPE_LABELS[t] || t;
    const cls = TYPE_CSS[t] || "";
    return `<label class="enc-type-filter-label">
      <input type="checkbox" class="enc-type-checkbox" data-type="${t}">
      <span class="enc-type-badge ${cls}">${label}</span>
    </label>`;
  }).join("");

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

  // Type filters
  typeFiltersEl.querySelectorAll(".enc-type-checkbox").forEach(cb => {
    cb.addEventListener("change", () => {
      if (cb.checked) typeFilters.add(cb.dataset.type);
      else typeFilters.delete(cb.dataset.type);
      refreshList(container);
    });
  });

  // New Map button — pick any project map that doesn't have encounters yet
  const newMapBtn = container.querySelector(".enc-new-map-btn");
  const newMapPicker = container.querySelector(".enc-new-map-picker");
  const newMapSearch = container.querySelector(".enc-new-map-search");
  const newMapResults = container.querySelector(".enc-new-map-results");

  const encMapConsts = new Set(cachedMaps.map(m => m.map));

  newMapBtn.addEventListener("click", async () => {
    const open = newMapPicker.style.display !== "none";
    if (open) {
      newMapPicker.style.display = "none";
      return;
    }
    newMapPicker.style.display = "";
    newMapSearch.value = "";
    newMapSearch.focus();
    newMapResults.innerHTML = `<div class="enc-picker-empty">Type to search...</div>`;

    // Lazy-load all project maps
    if (!newMapPicker._allProjectMaps) {
      newMapResults.innerHTML = `<div class="enc-picker-empty">Loading maps...</div>`;
      const studioRes = await api("/studio/maps");
      if (studioRes.ok) {
        newMapPicker._allProjectMaps = (studioRes.data.maps || [])
          .filter(m => !encMapConsts.has(folderToMapConst(m.name)))
          .map(m => ({ name: m.name, map: folderToMapConst(m.name) }));
      } else {
        newMapPicker._allProjectMaps = [];
      }
      newMapResults.innerHTML = `<div class="enc-picker-empty">Type to search...</div>`;
    }
  });

  let newMapTimer = null;
  newMapSearch.addEventListener("input", () => {
    clearTimeout(newMapTimer);
    newMapTimer = setTimeout(() => {
      const q = newMapSearch.value.trim().toLowerCase();
      const pool = newMapPicker._allProjectMaps || [];
      if (!q) {
        newMapResults.innerHTML = pool.length
          ? `<div class="enc-picker-empty">${pool.length} maps without encounters</div>`
          : `<div class="enc-picker-empty">All maps already have encounters</div>`;
        return;
      }
      const matches = pool.filter(m =>
        m.name.toLowerCase().includes(q) || m.map.toLowerCase().includes(q)
      ).slice(0, 12);
      if (!matches.length) {
        newMapResults.innerHTML = `<div class="enc-picker-empty">No matches</div>`;
        return;
      }
      newMapResults.innerHTML = matches.map(m =>
        `<div class="enc-new-map-item" data-map="${m.map}" data-name="${esc(m.name)}">
          <span class="enc-new-map-name">${esc(m.name)}</span>
          <span class="enc-new-map-const">${m.map}</span>
        </div>`
      ).join("");
      newMapResults.querySelectorAll(".enc-new-map-item").forEach(item => {
        item.addEventListener("click", () => {
          window.location.hash = `#/encounters/${item.dataset.map}`;
        });
      });
    }, 150);
  });
}

// ---------------------------------------------------------------------------
// Detail view
// ---------------------------------------------------------------------------

async function loadTypesRef() {
  if (typesRef) return typesRef;
  const res = await api("/encounters/types");
  if (res.ok) typesRef = res.data;
  return typesRef || {};
}

// ---------------------------------------------------------------------------
// Creation wizard — shown when a map has no encounters
// ---------------------------------------------------------------------------

async function renderCreateWizard(container, mapData, mapConst) {
  const ref = await loadTypesRef();
  const typeLabels = ref.type_labels || {};
  const slotCounts = ref.type_slot_counts || {};

  const typeKeys = Object.keys(typeLabels);
  const typeCheckboxes = typeKeys.map(tk => {
    const label = typeLabels[tk] || tk;
    const count = slotCounts[tk] || 5;
    const cls = TYPE_CSS[tk] || "";
    return `<label class="enc-wizard-type">
      <input type="checkbox" class="enc-wizard-cb" data-type="${tk}" checked>
      <span class="enc-type-badge ${cls}">${label}</span>
      <span class="enc-wizard-slots">${count} slots</span>
    </label>`;
  }).join("");

  container.innerHTML = `<article class="enc-detail">
    <a href="#/encounters" class="detail-back">Back to Encounters</a>
    <h2>${esc(mapData.name)} <span class="enc-map-const">${esc(mapConst)}</span></h2>
    <div class="enc-wizard">
      <p class="enc-wizard-intro">This map has no encounters yet. Choose which encounter types to add:</p>
      <div class="enc-wizard-types">${typeCheckboxes}</div>
      <div class="enc-wizard-actions">
        <button class="enc-save-btn enc-wizard-create">Create Encounters</button>
        <span class="enc-wizard-status"></span>
      </div>
    </div>
  </article>`;

  const createBtn = container.querySelector(".enc-wizard-create");
  const statusEl = container.querySelector(".enc-wizard-status");

  createBtn.addEventListener("click", async () => {
    const selected = [...container.querySelectorAll(".enc-wizard-cb:checked")]
      .map(cb => cb.dataset.type);

    if (!selected.length) {
      statusEl.textContent = "Select at least one encounter type";
      statusEl.className = "enc-wizard-status enc-save-err";
      return;
    }

    createBtn.disabled = true;
    statusEl.textContent = "Creating...";
    statusEl.className = "enc-wizard-status";

    try {
      const res = await fetch("/api/encounters/new", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ map: mapConst, types: selected }),
      });
      const body = await res.json();
      if (body.ok) {
        // Reload as the normal editor
        await renderDetail(container, mapConst);
      } else {
        statusEl.textContent = body.error || "Creation failed";
        statusEl.className = "enc-wizard-status enc-save-err";
        createBtn.disabled = false;
      }
    } catch (err) {
      statusEl.textContent = "Network error: " + err.message;
      statusEl.className = "enc-wizard-status enc-save-err";
      createBtn.disabled = false;
    }
  });
}

function speciesDisplay(species) {
  if (!species || species === "SPECIES_NONE") return "None";
  if (species.startsWith("SPECIES_"))
    return species.slice(8).replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  return species;
}

async function renderDetail(container, mapConst) {
  container.innerHTML = `<article><div class="enc-empty">Loading...</div></article>`;

  const [detailRes, ref] = await Promise.all([
    api(`/encounters/${mapConst}`),
    loadTypesRef(),
  ]);

  if (!detailRes.ok) {
    container.innerHTML = `<article>
      <a href="#/encounters" class="detail-back">Back to Encounters</a>
      <p>Error: ${esc(detailRes.error)}</p>
    </article>`;
    return;
  }

  const d = detailRes.data;
  const typeKeys = Object.keys(d.types);
  if (!typeKeys.length) {
    await renderCreateWizard(container, d, mapConst);
    return;
  }

  const typeLabels = ref.type_labels || {};
  const allTypeKeys = Object.keys(ref.type_labels || {});
  const slotCounts = ref.type_slot_counts || {};
  const defaultRate = ref.default_encounter_rate || 20;
  const fishingGroups = ref.fishing_groups || {};

  container.innerHTML = `<article class="enc-detail">
    <a href="#/encounters" class="detail-back">Back to Encounters</a>
    <div class="enc-detail-header">
      <h2>${d.name} <span class="enc-map-const">${d.map}</span></h2>
      <div class="enc-help-card">
        <div class="enc-help-title">Rate %</div>
        <p class="enc-help-text">Each slot has a fixed chance of being picked when a wild battle starts. Slot 1 is the most common (20%), and lower slots get progressively rarer. You choose <em>which</em> Pokemon goes in each slot — the engine decides <em>how often</em> that slot is rolled.</p>
      </div>
    </div>
    <div class="enc-tabs"></div>
    <div class="enc-editor"></div>
    <div class="enc-actions">
      <button class="enc-save-btn">Save</button>
      <span class="enc-dirty-indicator" style="display:none">Unsaved changes</span>
      <span class="enc-save-status"></span>
      <button class="enc-delete-all-btn">Delete All Encounters</button>
    </div>
  </article>`;

  // Working copy of the data (mutable)
  const workingData = JSON.parse(JSON.stringify(d.types));
  dirty = false;

  const tabBar = container.querySelector(".enc-tabs");
  const editor = container.querySelector(".enc-editor");
  const dirtyEl = container.querySelector(".enc-dirty-indicator");
  let activeType = typeKeys[0];

  function renderTabBar() {
    const currentTypes = Object.keys(workingData);
    const missing = allTypeKeys.filter(t => !currentTypes.includes(t));

    let html = currentTypes.map(tk => {
      const label = typeLabels[tk] || tk;
      return `<span class="enc-tab-wrap${tk === activeType ? " active" : ""}">
        <button class="enc-tab${tk === activeType ? " active" : ""}" data-type="${tk}">${label}</button>
        <button class="enc-tab-remove" data-type="${tk}" title="Remove ${label}">×</button>
      </span>`;
    }).join("");

    if (missing.length) {
      html += `<button class="enc-tab enc-tab-add" data-action="add">+</button>`;
      html += `<div class="enc-add-menu" style="display:none">${
        missing.map(tk => {
          const label = typeLabels[tk] || tk;
          const count = slotCounts[tk] || 5;
          return `<button class="enc-add-item" data-type="${tk}">${label} (${count} slots)</button>`;
        }).join("")
      }</div>`;
    }

    tabBar.innerHTML = html;

    // Tab click handlers
    tabBar.querySelectorAll(".enc-tab:not(.enc-tab-add)").forEach(tab => {
      tab.addEventListener("click", () => showTab(tab.dataset.type));
    });

    // Tab remove buttons
    tabBar.querySelectorAll(".enc-tab-remove").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const etype = btn.dataset.type;
        const label = typeLabels[etype] || etype;
        if (!confirm(`Remove all ${label} encounters from this map?`)) return;
        delete workingData[etype];
        markDirty();
        const remaining = Object.keys(workingData);
        activeType = remaining[0] || null;
        renderTabBar();
        if (activeType) showTab(activeType);
        else editor.innerHTML = `<div class="enc-empty">No encounter types remaining. Save to apply, or add a new type.</div>`;
      });
    });

    // [+] button
    const addBtn = tabBar.querySelector(".enc-tab-add");
    const addMenu = tabBar.querySelector(".enc-add-menu");
    if (addBtn && addMenu) {
      addBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        addMenu.style.display = addMenu.style.display === "none" ? "" : "none";
      });
      tabBar.querySelectorAll(".enc-add-item").forEach(item => {
        item.addEventListener("click", () => {
          const newType = item.dataset.type;
          const count = slotCounts[newType] || 5;
          workingData[newType] = {
            encounter_rate: defaultRate,
            mons: Array.from({ length: count }, () => ({
              species: "SPECIES_NONE", min_level: 1, max_level: 1
            })),
          };
          markDirty();
          activeType = newType;
          renderTabBar();
          showTab(newType);
        });
      });
      // Close menu on outside click
      document.addEventListener("click", () => { addMenu.style.display = "none"; }, { once: true });
    }
  }

  function markDirty() {
    dirty = true;
    dirtyEl.style.display = "";
  }

  function renderSlotTable(etype) {
    const tdata = workingData[etype];
    if (!tdata) return `<div class="enc-empty">No data</div>`;

    const slots = tdata.mons || [];
    const fieldRates = (d.field_rates || {})[etype] || [];
    const isFishing = etype === "fishing_mons";
    const groups = isFishing ? fishingGroups : {};

    const currentRate = tdata.encounter_rate || 20;
    const matchedPreset = RATE_PRESETS.find(p => p.value === currentRate);
    const isCustom = !matchedPreset;

    let html = `<div class="enc-rate-row">
      <label>Encounter Rate <span class="enc-rate-hint">— how often wild battles trigger in this area</span></label>
      <div class="enc-rate-presets">
        ${RATE_PRESETS.map(p =>
          `<button class="enc-rate-preset${p.value === currentRate ? " active" : ""}"
                  data-rate="${p.value}">${p.label}</button>`
        ).join("")}
        <button class="enc-rate-preset enc-rate-preset-custom${isCustom ? " active" : ""}"
                data-rate="custom">Custom</button>
        <input type="number" class="enc-rate-custom-input" min="1" max="255"
               value="${currentRate}" data-type="${etype}"
               style="display:${isCustom ? "inline-block" : "none"}">
      </div>
    </div>`;

    html += `<table class="enc-slot-table"><thead><tr>
      <th>#</th><th>Species</th><th>Min Lv</th><th>Max Lv</th><th>Rate %</th><th></th>
    </tr></thead><tbody>`;

    // Determine rod group boundaries
    const rodRanges = isFishing ? Object.entries(groups) : [];

    for (let i = 0; i < slots.length; i++) {
      // Insert fishing group headers
      if (isFishing) {
        for (const [rod, [start, end]] of rodRanges) {
          if (i === start) {
            const rodLabel = rod.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
            html += `<tr class="enc-rod-header"><td colspan="6">${rodLabel}</td></tr>`;
          }
        }
      }

      const slot = slots[i];
      const rate = i < fieldRates.length ? fieldRates[i] : 0;
      const name = speciesDisplay(slot.species);
      const spriteUrl = speciesSpriteUrl(slot.species);
      const hasSpecies = slot.species && slot.species !== "SPECIES_NONE";
      const spriteHtml = spriteUrl
        ? `<img class="enc-slot-sprite" data-sprite-src="${spriteUrl}" src="" width="48" height="48" style="display:none" onerror="this.style.display='none'">`
        : `<div class="enc-slot-sprite-empty"></div>`;

      // Type-based styling
      const sTypes = slot.species_types || [];
      const rowStyle = hasSpecies ? slotRowStyle(sTypes) : "";

      // Type badges
      const typeBadges = hasSpecies && sTypes.length
        ? `<div class="enc-slot-types">${sTypes.map(t => {
            const c = TYPE_COLOURS[t] || "#888";
            return `<span class="enc-slot-type-badge" style="background:${c}">${t}</span>`;
          }).join("")}</div>`
        : "";

      html += `<tr class="enc-slot-row${hasSpecies ? "" : " enc-slot-empty"}" data-index="${i}" style="${rowStyle}">
        <td class="enc-slot-num">${i + 1}</td>
        <td class="enc-species-cell">
          <div class="enc-species-inner">
            ${spriteHtml}
            <div class="enc-species-info">
              <span class="enc-species-name" data-species="${slot.species || ""}">${name}</span>
              ${typeBadges}
            </div>
          </div>
        </td>
        <td><input type="number" class="enc-level-input enc-min-level" min="1" max="100"
                   value="${slot.min_level || 1}" data-index="${i}" data-field="min_level"></td>
        <td><input type="number" class="enc-level-input enc-max-level" min="1" max="100"
                   value="${slot.max_level || 1}" data-index="${i}" data-field="max_level"></td>
        <td class="enc-rate-pct">
          <div class="enc-rate-bar-wrap">
            <div class="enc-rate-bar-fill" style="width:${rate}%;background:${rateColor(rate)}"></div>
            <span class="enc-rate-bar-label">${rate}%</span>
          </div>
        </td>
        <td><button class="enc-clear-btn" data-index="${i}" title="Clear slot">x</button></td>
      </tr>`;
    }

    // Rate total — for fishing, check per rod group; for others, check overall
    html += `</tbody></table>`;
    if (isFishing && Object.keys(groups).length) {
      for (const [rod, [start, end]] of Object.entries(groups)) {
        const groupRates = fieldRates.slice(start, end);
        const groupTotal = groupRates.reduce((a, b) => a + b, 0);
        if (groupTotal && groupTotal !== 100) {
          const rodLabel = rod.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
          html += `<div class="enc-rate-warn">${rodLabel} rate total: ${groupTotal}% (expected 100%)</div>`;
        }
      }
    } else {
      const rateTotal = fieldRates.reduce((a, b) => a + b, 0);
      if (rateTotal && rateTotal !== 100) {
        html += `<div class="enc-rate-warn">Rate total: ${rateTotal}% (expected 100%)</div>`;
      }
    }

    return html;
  }

  function showTab(etype) {
    activeType = etype;
    tabBar.querySelectorAll(".enc-tab:not(.enc-tab-add)").forEach(t =>
      t.classList.toggle("active", t.dataset.type === etype)
    );
    editor.innerHTML = renderSlotTable(etype);
    attachEditorEvents(etype);
  }

  function attachEditorEvents(etype) {
    // Process sprites asynchronously after render
    editor.querySelectorAll(".enc-slot-sprite[data-sprite-src]").forEach(img => {
      const url = img.dataset.spriteSrc;
      if (!url) return;
      processSprite(url).then(dataUrl => {
        img.src = dataUrl;
        img.style.display = "";
      }).catch(() => {
        img.style.display = "none";
      });
    });

    // Encounter rate presets
    const presetBtns = editor.querySelectorAll(".enc-rate-preset:not(.enc-rate-preset-custom)");
    const customBtn = editor.querySelector(".enc-rate-preset-custom");
    const customInput = editor.querySelector(".enc-rate-custom-input");

    presetBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        const val = parseInt(btn.dataset.rate, 10);
        workingData[etype].encounter_rate = val;
        markDirty();
        // Update active state
        editor.querySelectorAll(".enc-rate-preset").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        if (customInput) customInput.style.display = "none";
      });
    });

    if (customBtn && customInput) {
      customBtn.addEventListener("click", () => {
        editor.querySelectorAll(".enc-rate-preset").forEach(b => b.classList.remove("active"));
        customBtn.classList.add("active");
        customInput.style.display = "inline-block";
        customInput.focus();
      });

      customInput.addEventListener("change", () => {
        let val = parseInt(customInput.value, 10);
        if (isNaN(val) || val < 1) val = 1;
        if (val > 255) val = 255;
        customInput.value = val;
        workingData[etype].encounter_rate = val;
        markDirty();
        // If the value now matches a preset, switch to it
        const match = RATE_PRESETS.find(p => p.value === val);
        if (match) {
          editor.querySelectorAll(".enc-rate-preset").forEach(b => b.classList.remove("active"));
          const matchBtn = editor.querySelector(`.enc-rate-preset[data-rate="${val}"]`);
          if (matchBtn) matchBtn.classList.add("active");
          customBtn.classList.remove("active");
          customInput.style.display = "none";
        }
      });
    }

    // Level inputs
    editor.querySelectorAll(".enc-level-input").forEach(input => {
      input.addEventListener("change", () => {
        const idx = parseInt(input.dataset.index, 10);
        const field = input.dataset.field;
        let val = parseInt(input.value, 10);
        if (isNaN(val) || val < 1) val = 1;
        if (val > 100) val = 100;
        input.value = val;

        const slot = workingData[etype].mons[idx];
        slot[field] = val;

        // Enforce min <= max
        if (field === "min_level" && slot.max_level < val) {
          slot.max_level = val;
          const maxInput = editor.querySelector(
            `.enc-max-level[data-index="${idx}"]`
          );
          if (maxInput) maxInput.value = val;
        }
        if (field === "max_level" && slot.min_level > val) {
          slot.min_level = val;
          const minInput = editor.querySelector(
            `.enc-min-level[data-index="${idx}"]`
          );
          if (minInput) minInput.value = val;
        }

        markDirty();
      });
    });

    // Clear buttons
    editor.querySelectorAll(".enc-clear-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.dataset.index, 10);
        workingData[etype].mons[idx] = {
          species: "SPECIES_NONE", min_level: 1, max_level: 1
        };
        markDirty();
        showTab(etype);
      });
    });

    // Species picker (click on species name)
    editor.querySelectorAll(".enc-species-name").forEach(cell => {
      cell.addEventListener("click", (e) => {
        openSpeciesPicker(e.target, etype);
      });
    });
  }

  function openSpeciesPicker(nameEl, etype) {
    // Close any existing picker
    const existing = document.querySelector(".enc-picker");
    if (existing) existing.remove();

    const row = nameEl.closest(".enc-slot-row");
    const idx = parseInt(row.dataset.index, 10);

    // Position picker on body to avoid table z-index issues
    const rect = nameEl.getBoundingClientRect();
    const picker = document.createElement("div");
    picker.className = "enc-picker";
    picker.style.position = "fixed";
    picker.style.top = (rect.bottom + 4) + "px";
    picker.style.left = rect.left + "px";
    picker.innerHTML = `<input type="text" class="enc-picker-input" placeholder="Search species..."
                               autocomplete="off">
                        <div class="enc-picker-results"></div>`;
    document.body.appendChild(picker);

    const input = picker.querySelector(".enc-picker-input");
    const results = picker.querySelector(".enc-picker-results");
    input.focus();

    let pickerTimer = null;

    input.addEventListener("input", () => {
      clearTimeout(pickerTimer);
      pickerTimer = setTimeout(async () => {
        const q = input.value.trim();
        if (!q) { results.innerHTML = ""; return; }
        const res = await api(`/species?q=${encodeURIComponent(q)}`);
        if (!res.ok) return;
        const items = (res.data || []).slice(0, 8);
        results.innerHTML = items.map(sp => {
          const types = (sp.types || []).join(",");
          const typeBadges = (sp.types || []).map(t => {
            const c = TYPE_COLOURS[t] || "#888";
            return `<span class="enc-slot-type-badge" style="background:${c}">${t}</span>`;
          }).join("");
          return `<div class="enc-picker-item" data-const="${sp.const}" data-types="${esc(types)}">
            <img class="enc-picker-sprite" data-sprite-src="/api/sprites/${sp.sprite_path}"
                 width="32" height="32" style="image-rendering:pixelated;display:none"
                 onerror="this.style.display='none'">
            <div class="enc-picker-info">
              <span>${sp.name}</span>
              <span class="enc-picker-types">${typeBadges}</span>
            </div>
          </div>`;
        }).join("") || `<div class="enc-picker-empty">No results</div>`;

        // Process sprites (crop to first frame, remove background)
        results.querySelectorAll(".enc-picker-sprite[data-sprite-src]").forEach(img => {
          processSprite(img.dataset.spriteSrc).then(dataUrl => {
            img.src = dataUrl;
            img.style.display = "";
          }).catch(() => { img.style.display = "none"; });
        });

        results.querySelectorAll(".enc-picker-item").forEach(item => {
          item.addEventListener("click", () => {
            const c = item.dataset.const;
            const types = (item.dataset.types || "").split(",").filter(Boolean);
            workingData[etype].mons[idx].species = c;
            workingData[etype].mons[idx].species_types = types;
            markDirty();
            picker.remove();
            showTab(etype);
          });
        });
      }, 200);
    });

    // Close picker on Escape or click outside
    function closePicker(e) {
      if (e.type === "keydown" && e.key !== "Escape") return;
      if (e.type === "click" && picker.contains(e.target)) return;
      picker.remove();
      document.removeEventListener("keydown", closePicker);
      document.removeEventListener("click", closePicker, true);
    }
    setTimeout(() => {
      document.addEventListener("keydown", closePicker);
      document.addEventListener("click", closePicker, true);
    }, 10);
  }

  // Save button
  const saveBtn = container.querySelector(".enc-save-btn");
  const saveStatus = container.querySelector(".enc-save-status");

  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    saveStatus.textContent = "Saving...";
    saveStatus.className = "enc-save-status";

    const payload = { map: d.map, base_label: d.base_label };
    for (const [etype, tdata] of Object.entries(workingData)) {
      payload[etype] = tdata;
    }

    try {
      const res = await fetch(`/api/encounters/${d.map}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await res.json();
      if (body.ok) {
        saveStatus.textContent = "Saved!";
        saveStatus.className = "enc-save-status enc-save-ok";
        dirty = false;
        dirtyEl.style.display = "none";

        // Offer build
        const buildBtn = document.createElement("button");
        buildBtn.className = "enc-build-btn";
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
        const actions = container.querySelector(".enc-actions");
        if (!actions.querySelector(".enc-build-btn")) {
          actions.appendChild(buildBtn);
        }
      } else {
        saveStatus.textContent = body.error || "Save failed";
        saveStatus.className = "enc-save-status enc-save-err";
      }
    } catch (err) {
      saveStatus.textContent = "Network error: " + err.message;
      saveStatus.className = "enc-save-status enc-save-err";
    }
    saveBtn.disabled = false;
  });

  // Delete All button
  const deleteAllBtn = container.querySelector(".enc-delete-all-btn");
  deleteAllBtn.addEventListener("click", async () => {
    if (!confirm(`Delete ALL encounters for ${d.name}? This cannot be undone.`)) return;
    deleteAllBtn.disabled = true;
    saveStatus.textContent = "Deleting...";
    saveStatus.className = "enc-save-status";
    try {
      const res = await fetch(`/api/encounters/${d.map}`, { method: "DELETE" });
      const body = await res.json();
      if (body.ok) {
        // Reload — will show the creation wizard
        await renderDetail(container, mapConst);
      } else {
        saveStatus.textContent = body.error || "Delete failed";
        saveStatus.className = "enc-save-status enc-save-err";
        deleteAllBtn.disabled = false;
      }
    } catch (err) {
      saveStatus.textContent = "Network error: " + err.message;
      saveStatus.className = "enc-save-status enc-save-err";
      deleteAllBtn.disabled = false;
    }
  });

  // Initial render
  renderTabBar();
  showTab(activeType);
}

// ---------------------------------------------------------------------------
// Main render
// ---------------------------------------------------------------------------

export async function render(container) {
  const hash = window.location.hash || "";
  const detailMatch = hash.match(/^#\/encounters\/(.+)$/);
  if (detailMatch) {
    let mapId = decodeURIComponent(detailMatch[1]);

    // If it doesn't look like a MAP_ constant, resolve it
    if (!mapId.startsWith("MAP_")) {
      // Try the encounters list first (map already has encounters)
      container.innerHTML = `<article><div class="enc-empty">Loading...</div></article>`;
      const res = await api("/encounters");
      if (res.ok) {
        allMaps = res.data.maps || [];
        const folderLower = mapId.toLowerCase();
        const found = allMaps.find(m =>
          m.name.toLowerCase() === folderLower || m.map === mapId
        );
        if (found) {
          mapId = found.map;
        } else {
          // Map has no encounters yet — convert folder name to MAP_ constant
          mapId = folderToMapConst(mapId);
        }
      }
    }

    await renderDetail(container, mapId);
    return;
  }
  await renderList(container);
}

export function cleanup() {
  // Remove any body-mounted picker
  const picker = document.querySelector(".enc-picker");
  if (picker) picker.remove();
  clearTimeout(debounceTimer);
  debounceTimer = null;
  if (scrollHandler) {
    window.removeEventListener("scroll", scrollHandler);
    scrollHandler = null;
  }
  dirty = false;
  activeFilter = "all";
  searchQuery = "";
  typeFilters = new Set();
  typesRef = null;
  cachedMaps = null;
  allMaps = [];
  renderedCount = 0;
}
