/**
 * TORCH Web GUI -- Assets view.
 * Asset hub with import staging, custom asset dashboard, and category browser.
 */

import { api, postApi, deleteApi } from "../app.js";
import { esc } from "../utils.js";

// MIDI player — optional, degrades gracefully
let midiPlayer = null;
let midiPlayerLoaded = false;
async function loadMidiPlayer() {
  if (midiPlayerLoaded) return;
  midiPlayerLoaded = true;
  try {
    const mod = await import("../midiPlayer.js");
    if (mod.midiPlayer && mod.midiPlayer.canPlay()) {
      midiPlayer = mod.midiPlayer;
      midiPlayer.onStop = () => {
        // Reset all play buttons
        if (mainContainer) {
          mainContainer.querySelectorAll(".ab-play-btn.playing").forEach(btn => {
            btn.textContent = "\u25B6";
            btn.classList.remove("playing");
          });
        }
        currentlyPlayingConst = null;
      };
    }
  } catch (_) {
    // MIDI player not available — no play buttons will render
  }
}
let currentlyPlayingConst = null;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let categories = [];       // [{id, name, count, custom_count}]
let activeCategory = "__home__";
let allAssets = [];        // raw from API for current category
let filteredAssets = [];   // after filter + search
let filterMode = "all";    // "all" | "custom" | "vanilla"
let searchQuery = "";
let sortMode = "id";       // "id" | "name" | "custom_first"
let debounceTimer = null;
let scrollHandler = null;
let renderedCount = 0;
let mainContainer = null;
let selectedAsset = null;  // constant of selected asset for detail
let styleEl = null;
let homeData = null;       // cached from /api/assets/custom
let showingHome = true;    // true when Home tab is active

const PAGE_SIZE = 80;

// Category metadata for display
const CATEGORY_META = {
  trainer_sprites:      { icon: "\u{1F3AD}", visual: true,  imgSize: 64 },
  trainer_back_sprites: { icon: "\u{1F519}", visual: true,  imgSize: 64 },
  overworld_sprites:    { icon: "\u{1F6B6}", visual: true,  imgSize: 32 },
  item_icons:           { icon: "\u{1F392}", visual: true,  imgSize: 32 },
  music:                { icon: "\u{1F3B5}", visual: false, imgSize: 0  },
  sound_effects:        { icon: "\u{1F50A}", visual: false, imgSize: 0  },
  tilesets:             { icon: "\u{1F5BC}", visual: true,  imgSize: 64 },
};

// ---------------------------------------------------------------------------
// Image URL helpers
// ---------------------------------------------------------------------------

function spriteUrl(asset, category) {
  if (category === "trainer_sprites") {
    if (!asset.file) return "";
    const filename = asset.file.replace("graphics/trainers/front_pics/", "");
    return `/api/trainers/sprites/${filename}`;
  }
  if (category === "trainer_back_sprites") {
    return `/api/assets/trainer-back/${asset.constant}`;
  }
  if (category === "overworld_sprites") {
    return `/api/assets/overworld-frame/${asset.constant}`;
  }
  if (category === "item_icons") {
    return `/api/assets/item-icon/${asset.constant}`;
  }
  if (category === "tilesets") {
    return `/api/assets/tilesets/${asset.constant}/image`;
  }
  return "";
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function fetchCategories() {
  const res = await api("/assets/categories");
  if (res && res.ok) {
    categories = res.data.categories || [];
  }
}

async function fetchAssets(categoryId) {
  const params = new URLSearchParams();
  if (filterMode !== "all") params.set("filter", filterMode);
  if (searchQuery) params.set("search", searchQuery);
  if (sortMode !== "id") params.set("sort", sortMode);

  const res = await api(`/assets/${categoryId}/list?${params.toString()}`);
  if (res && res.ok) {
    allAssets = res.data.assets || [];
    filteredAssets = allAssets;
    // Update category count in header from API response
    const cat = categories.find(c => c.id === categoryId);
    if (cat) {
      cat.count = res.data.total || cat.count;
      cat.custom_count = res.data.custom_count || 0;
    }
  }
}

async function fetchDetail(categoryId, constant) {
  const res = await api(`/assets/${categoryId}/detail/${constant}`);
  if (res && res.ok) return res.data;
  return null;
}

async function fetchHomeData() {
  const res = await api("/assets/custom");
  if (res && res.ok) {
    homeData = res.data;
    return homeData;
  }
  homeData = null;
  return null;
}

async function fetchStagedList() {
  const res = await api("/assets/staged");
  if (res && res.ok) return res.data;
  return null;
}

// ---------------------------------------------------------------------------
// Filtering & sorting (client-side re-filter for instant UX)
// ---------------------------------------------------------------------------

function applyClientFilter() {
  let result = allAssets;

  // Note: API already applies server-side filters, but we re-fetch on change.
  // This is used only for the currently loaded data.
  filteredAssets = result;
}

// ---------------------------------------------------------------------------
// Rendering — Summary bar
// ---------------------------------------------------------------------------

function renderSummaryBar() {
  const cat = categories.find(c => c.id === activeCategory);
  if (!cat) return "";
  const vanilla = cat.count - cat.custom_count;
  const note = activeCategory === "tilesets"
    ? `<div class="ab-summary-note">Tileset previews are greyscale \u2014 the GBA applies colour palettes at runtime.</div>`
    : "";
  return `<div class="ab-summary">
    Showing <strong>${filteredAssets.length}</strong> of ${cat.count} ${esc(cat.name)}
    <span class="ab-summary-breakdown">(${cat.custom_count} custom, ${vanilla} vanilla)</span>
    ${note}
  </div>`;
}

// ---------------------------------------------------------------------------
// Rendering — Category tabs
// ---------------------------------------------------------------------------

// Compact display names for navbar
const _TAB_NAMES = {
  trainer_sprites: "Front Sprites",
  trainer_back_sprites: "Back Sprites",
};

function renderCategoryTabs() {
  // Studio link (back to Studio view)
  const studioLink = `<a href="#/studio" class="ab-tab ab-tab-studio">Studio</a>`;

  // Assets tab (hub/home)
  const stagedCount = homeData ? homeData.total_staged : 0;
  const stagedBadge = stagedCount > 0
    ? ` <span class="ab-tab-count ab-home-badge">(${stagedCount})</span>`
    : "";
  const homeTab = `<button class="ab-tab ab-tab-home${showingHome ? " active" : ""}" data-cat="__home__">
      Assets${stagedBadge}
    </button>`;

  const catTabs = categories.map(cat => {
    const active = !showingHome && cat.id === activeCategory ? " active" : "";
    const label = _TAB_NAMES[cat.id] || cat.name;
    return `<button class="ab-tab${active}" data-cat="${cat.id}">
      ${esc(label)} <span class="ab-tab-count">(${cat.count})</span>
    </button>`;
  }).join("");

  return `<div class="ab-tabs">${studioLink}${homeTab}${catTabs}</div>`;
}

// ---------------------------------------------------------------------------
// Rendering — Toolbar
// ---------------------------------------------------------------------------

function renderToolbar() {
  const filters = ["all", "custom", "vanilla"];
  const filterBtns = filters.map(f => {
    const active = f === filterMode ? " active" : "";
    const label = f.charAt(0).toUpperCase() + f.slice(1);
    return `<button class="ab-filter-btn${active}" data-filter="${f}">${label}</button>`;
  }).join("");

  const sorts = [
    { key: "id", label: "By ID" },
    { key: "name", label: "By Name" },
    { key: "custom_first", label: "Custom First" },
  ];
  const sortBtns = sorts.map(s => {
    const active = s.key === sortMode ? " active" : "";
    return `<button class="ab-sort-btn${active}" data-sort="${s.key}">${s.label}</button>`;
  }).join("");

  return `<div class="ab-toolbar">
    <div class="ab-filter-group">${filterBtns}</div>
    <input type="text" class="ab-search" placeholder="Search by name..." value="${esc(searchQuery)}">
    <div class="ab-sort-group">${sortBtns}</div>
  </div>`;
}

// ---------------------------------------------------------------------------
// Rendering — Grid cell (visual categories)
// ---------------------------------------------------------------------------

function renderGridCell(asset) {
  const meta = CATEGORY_META[activeCategory] || {};
  const size = meta.imgSize || 64;
  const url = spriteUrl(asset, activeCategory);
  const customBadge = asset.is_custom
    ? `<span class="ab-custom-badge">Custom</span>`
    : "";

  // Overworld sprites: don't force width=height, let aspect ratio breathe
  // Item icons: scale up from 24px native for visibility
  const sizeAttrs = activeCategory === "overworld_sprites"
    ? `style="image-rendering:pixelated;height:${size * 2}px;width:auto"`
    : activeCategory === "item_icons"
      ? `width="${size}" height="${size}" style="image-rendering:pixelated"`
      : `width="${size}" height="${size}" style="image-rendering:pixelated"`;

  const imgHtml = url
    ? `<img class="ab-thumb" src="${url}" alt="${esc(asset.name)}"
           ${sizeAttrs} loading="lazy"
           onerror="this.onerror=null;this.style.display='none';this.parentElement.classList.add('ab-missing')">`
    : `<div class="ab-thumb-placeholder" style="width:${size}px;height:${size}px">?</div>`;

  return `<div class="ab-grid-cell${asset.is_custom ? " ab-cell-custom" : ""}" data-const="${esc(asset.constant)}">
    <div class="ab-cell-img">${imgHtml}</div>
    ${customBadge}
    <div class="ab-cell-name">${esc(asset.name)}</div>
  </div>`;
}

// ---------------------------------------------------------------------------
// Rendering — List row (non-visual categories: music, SFX)
// ---------------------------------------------------------------------------

function renderListRow(asset) {
  const meta = CATEGORY_META[activeCategory] || {};
  const icon = meta.icon || "";
  const customBadge = asset.is_custom
    ? `<span class="ab-custom-badge">Custom</span>`
    : "";

  // Play button for music tracks (only if MIDI player loaded)
  const playBtn = (activeCategory === "music" && midiPlayer)
    ? `<button class="ab-play-btn" data-midi="${esc(asset.constant)}" title="Preview">\u25B6</button>`
    : "";

  return `<div class="ab-list-row${asset.is_custom ? " ab-row-custom" : ""}" data-const="${esc(asset.constant)}">
    ${playBtn}
    <span class="ab-row-icon">${icon}</span>
    <span class="ab-row-name">${esc(asset.name)}</span>
    <span class="ab-row-const">${esc(asset.constant)}</span>
    ${customBadge}
    <span class="ab-row-id">#${asset.id}</span>
  </div>`;
}

// ---------------------------------------------------------------------------
// Rendering — Main grid/list
// ---------------------------------------------------------------------------

function isVisualCategory() {
  return (CATEGORY_META[activeCategory] || {}).visual !== false;
}

function renderAssetItem(asset) {
  return isVisualCategory() ? renderGridCell(asset) : renderListRow(asset);
}

function appendItems(container, count) {
  const listEl = container.querySelector(".ab-grid") || container.querySelector(".ab-list");
  if (!listEl) return;
  const end = Math.min(renderedCount + count, filteredAssets.length);
  let html = "";
  for (let i = renderedCount; i < end; i++) {
    html += renderAssetItem(filteredAssets[i]);
  }
  listEl.insertAdjacentHTML("beforeend", html);

  // Attach click handlers to new items
  const selector = isVisualCategory() ? ".ab-grid-cell" : ".ab-list-row";
  const items = listEl.querySelectorAll(selector);
  for (let i = renderedCount; i < end; i++) {
    const el = items[i];
    if (el) {
      el.addEventListener("click", (e) => {
        // Don't open detail if clicking play button
        if (e.target.closest(".ab-play-btn")) return;
        selectedAsset = el.dataset.const;
        showDetail(container, el.dataset.const);
      });
    }
  }

  // Wire MIDI play buttons
  if (activeCategory === "music" && midiPlayer) {
    listEl.querySelectorAll(".ab-play-btn[data-midi]").forEach(btn => {
      if (btn._wired) return;
      btn._wired = true;
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const constant = btn.dataset.midi;
        if (midiPlayer.isPlaying() && currentlyPlayingConst === constant) {
          midiPlayer.stop();
          return;
        }
        // Stop any current playback and reset buttons
        midiPlayer.stop();
        listEl.querySelectorAll(".ab-play-btn.playing").forEach(b => {
          b.textContent = "\u25B6";
          b.classList.remove("playing");
        });
        // Play this track
        btn.textContent = "\u25A0";
        btn.classList.add("playing");
        currentlyPlayingConst = constant;
        midiPlayer.play(`/api/assets/music/${constant}/midi`);
      });
    });
  }

  renderedCount = end;
}

// ---------------------------------------------------------------------------
// Detail panel
// ---------------------------------------------------------------------------

async function showDetail(container, constant) {
  // Remove existing detail panel
  const existing = container.querySelector(".ab-detail-backdrop");
  if (existing) existing.remove();

  const detail = await fetchDetail(activeCategory, constant);
  if (!detail) return;

  const meta = CATEGORY_META[activeCategory] || {};
  const url = spriteUrl(detail, activeCategory);

  // Overworld sprites: scale up nicely; others use standard sizing
  let imgHtml = "";
  if (url && meta.visual) {
    const imgStyle = activeCategory === "overworld_sprites"
      ? `style="image-rendering:pixelated;height:128px;width:auto"`
      : `width="${meta.imgSize === 32 ? 96 : 128}" height="${meta.imgSize === 32 ? 96 : 128}" style="image-rendering:pixelated"`;
    imgHtml = `<div class="ab-detail-img">
      <img src="${url}" alt="${esc(detail.name)}"
           ${imgStyle}
           onerror="this.onerror=null;this.style.display='none';this.parentElement.classList.add('ab-missing')">
    </div>`;
  }

  const statusBadge = detail.is_custom
    ? `<span class="ab-badge ab-badge-custom">Custom</span>`
    : `<span class="ab-badge ab-badge-vanilla">Vanilla</span>`;

  let extraHtml = "";

  // Trainer sprite cross-reference
  if (activeCategory === "trainer_sprites" && detail.used_by_trainers) {
    const trainers = detail.used_by_trainers;
    if (trainers.length > 0) {
      const trainerList = trainers.map(t => {
        const name = t.constant.replace("TRAINER_", "").replace(/_/g, " ")
          .replace(/\b\w/g, ch => ch.toUpperCase());
        const loc = t.map ? ` <span class="ab-detail-dim">(${esc(t.map)})</span>` : "";
        return `<div class="ab-detail-trainer">${esc(name)}${loc}</div>`;
      }).join("");
      extraHtml += `<div class="ab-detail-section">
        <h4>Used by Trainers (${trainers.length})</h4>
        ${trainerList}
      </div>`;
    } else {
      extraHtml += `<div class="ab-detail-section">
        <h4>Used by Trainers</h4>
        <span class="ab-detail-dim">Not used by any trainer.</span>
      </div>`;
    }
  }

  // Tileset metadata
  if (activeCategory === "tilesets") {
    if (detail.metatile_count != null) {
      extraHtml += `<div class="ab-detail-field">
        <span class="ab-detail-label">Metatiles:</span>
        <span>${detail.metatile_count}</span>
      </div>`;
    }
    if (detail.palette_count != null) {
      extraHtml += `<div class="ab-detail-field">
        <span class="ab-detail-label">Palettes:</span>
        <span>${detail.palette_count}</span>
      </div>`;
    }
    extraHtml += `<div class="ab-detail-field" style="margin-top:0.5rem">
      <a href="#/tilesets/${encodeURIComponent(detail.constant)}"
         style="color:var(--accent,#cba6f7);font-size:0.85rem;text-decoration:none">
        Tileset Editor &rarr;
      </a>
    </div>`;
  }

  // Character sheet: fetch matching sprites across categories
  let characterSheetHtml = "";
  const spriteCategories = ["trainer_sprites", "trainer_back_sprites", "overworld_sprites"];
  if (spriteCategories.includes(activeCategory) && detail.name) {
    const sheetRes = await api(`/assets/character-sheet/${encodeURIComponent(detail.name)}`);
    if (sheetRes && sheetRes.ok && sheetRes.data.sprites) {
      const sprites = sheetRes.data.sprites;
      const cards = [];

      if (sprites.trainer_front && sprites.trainer_front.url) {
        cards.push(`<div class="ab-charsheet-sprite">
          <img src="${sprites.trainer_front.url}" width="64" height="64"
               style="image-rendering:pixelated"
               onerror="this.parentElement.style.display='none'">
          <div class="ab-charsheet-label">Front</div>
        </div>`);
      }
      if (sprites.trainer_back && sprites.trainer_back.url) {
        cards.push(`<div class="ab-charsheet-sprite">
          <img src="${sprites.trainer_back.url}" width="64" height="64"
               style="image-rendering:pixelated"
               onerror="this.parentElement.style.display='none'">
          <div class="ab-charsheet-label">Back</div>
        </div>`);
      }
      if (sprites.overworld && sprites.overworld.length > 0) {
        for (const ow of sprites.overworld) {
          const owLabel = ow.name || "Overworld";
          cards.push(`<div class="ab-charsheet-sprite">
            <img src="${ow.url}" style="image-rendering:pixelated;height:64px;width:auto"
                 onerror="this.parentElement.style.display='none'">
            <div class="ab-charsheet-label">${esc(owLabel)}</div>
          </div>`);
        }
      }

      if (cards.length > 1) {
        characterSheetHtml = `<div class="ab-detail-section">
          <h4>Character Sheet</h4>
          <div class="ab-charsheet">${cards.join("")}</div>
        </div>`;
      }
    }
  }

  const backdrop = document.createElement("div");
  backdrop.className = "ab-detail-backdrop";
  backdrop.innerHTML = `<div class="ab-detail-panel">
    <button class="ab-detail-close">&times;</button>
    ${imgHtml}
    <h3 class="ab-detail-name">${esc(detail.name)}</h3>
    <div class="ab-detail-meta">
      ${statusBadge}
      <span class="ab-detail-id">#${detail.id}</span>
    </div>
    <div class="ab-detail-field">
      <span class="ab-detail-label">Constant:</span>
      <span class="ab-detail-mono">${esc(detail.constant)}</span>
    </div>
    ${detail.file ? `<div class="ab-detail-field">
      <span class="ab-detail-label">File:</span>
      <span class="ab-detail-mono">${esc(detail.file)}</span>
    </div>` : ""}
    ${extraHtml}
    ${characterSheetHtml}
  </div>`;

  container.appendChild(backdrop);

  // Close handlers
  const closeBtn = backdrop.querySelector(".ab-detail-close");
  closeBtn.addEventListener("click", () => backdrop.remove());
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) backdrop.remove();
  });
  const onEsc = (e) => {
    if (e.key === "Escape") {
      backdrop.remove();
      document.removeEventListener("keydown", onEsc);
    }
  };
  document.addEventListener("keydown", onEsc);
}

// ---------------------------------------------------------------------------
// Assets Home tab rendering
// ---------------------------------------------------------------------------

// Category metadata for drop zones
const _DROP_ZONE_META = {
  trainer_sprites:      { icon: "\u{1F3AD}", hint: "64\u00D764 PNG, 16 colours" },
  overworld_sprites:    { icon: "\u{1F6B6}", hint: "Spritesheet PNG, 16 colours" },
  trainer_back_sprites: { icon: "\u{1F519}", hint: "64\u00D7256 PNG, 4 frames" },
  item_icons:           { icon: "\u{1F392}", hint: "24\u00D724 PNG, 16 colours" },
  music_tracks:         { icon: "\u{1F3B5}", hint: "MIDI file (.mid)" },
  sound_effects:        { icon: "\u{1F50A}", hint: "Assembly file (.s)" },
};

async function renderHomeTab(container) {
  const contentArea = container.querySelector(".ab-content-area");
  contentArea.innerHTML = `<div class="ab-loading">Loading...</div>`;

  // Fetch dashboard + staged data in parallel
  const [_, stagedData] = await Promise.all([fetchHomeData(), fetchStagedList()]);

  if (!homeData) {
    contentArea.innerHTML = `<div class="ab-loading">Could not load asset data.</div>`;
    return;
  }

  // Auto-cleanup: move already-imported files from staging to backup
  if (stagedData && stagedData.categories) {
    const hasAlreadyImported = stagedData.categories.some(
      c => c.staged.some(f => f.already_imported));
    if (hasAlreadyImported) {
      const cleanup = await postApi("/assets/staged/cleanup", {});
      if (cleanup && cleanup.ok && cleanup.data.moved > 0) {
        // Re-fetch after cleanup
        await Promise.all([fetchHomeData(), fetchStagedList()]);
      }
    }
  }

  // Re-fetch staged after potential cleanup
  const staged = await fetchStagedList();

  let html = "";

  // === Zone 1: Staging Area ===
  const importDir = homeData.import_dir || "";
  const totalStaged = homeData.total_staged || 0;

  html += `<div class="ab-home-section">
    <div class="ab-home-section-header">
      <h2 class="ab-home-section-title">Import Staging</h2>
      <div class="ab-home-section-actions">
        <button class="ab-home-path-btn" title="Copy path to clipboard">${esc(importDir)}</button>
      </div>
    </div>`;

  // Drop zones grid
  html += `<div class="ab-drop-grid">`;
  for (const [typeKey, meta] of Object.entries(_DROP_ZONE_META)) {
    const atype = homeData.categories.find(c => c.type_key === typeKey);
    const count = atype ? atype.staged_count : 0;
    const countBadge = count > 0 ? `<span class="ab-drop-count">${count}</span>` : "";
    const name = atype ? atype.name : typeKey.replace(/_/g, " ");
    html += `<div class="ab-drop-zone" data-type-key="${typeKey}">
      <div class="ab-drop-icon">${meta.icon}</div>
      <div class="ab-drop-name">${esc(name)} ${countBadge}</div>
      <div class="ab-drop-hint">${esc(meta.hint)}</div>
      <div class="ab-drop-label">Drop files here</div>
    </div>`;
  }
  html += `</div>`;

  // Staged file listing
  if (staged && staged.categories && staged.categories.length > 0) {
    const readyCount = staged.total_ready || 0;
    html += `<div class="ab-staged-files">`;
    if (readyCount > 0) {
      html += `<button class="ab-import-all-btn">Import All (${readyCount})</button>`;
    }
    for (const cat of staged.categories) {
      for (const file of cat.staged) {
        if (file.already_imported) continue;
        const statusClass = file.valid ? "ab-staged-ready" : "ab-staged-invalid";
        const statusIcon = file.valid ? "\u25CF" : "\u2716";
        const statusLabel = file.valid ? "Ready" : esc(file.message);
        const dimInfo = file.width ? ` ${file.width}\u00D7${file.height}` : "";

        let previewHtml = "";
        if (file.preview_url && file.preview_url.endsWith(".png")) {
          previewHtml = `<img class="ab-staged-thumb" src="${file.preview_url}" style="image-rendering:pixelated" loading="lazy" onerror="this.style.display='none'">`;
        } else if (file.preview_url) {
          previewHtml = `<div class="ab-staged-midi-icon">\u{1F3B5}</div>`;
        }

        const importBtn = file.valid
          ? `<button class="ab-staged-import-btn" data-type="${esc(cat.type_key)}" data-file="${esc(file.filename)}">Import</button>`
          : "";
        const deleteBtn = `<button class="ab-staged-delete-btn" data-type="${esc(cat.type_key)}" data-file="${esc(file.filename)}" title="Remove">\u2716</button>`;

        html += `<div class="ab-staged-card ${statusClass}">
          <div class="ab-staged-preview">${previewHtml}</div>
          <div class="ab-staged-info">
            <div class="ab-staged-filename">${esc(file.filename)}</div>
            <div class="ab-staged-const">${esc(file.constant)}${dimInfo}</div>
            <div class="ab-staged-status">${statusIcon} ${statusLabel}</div>
          </div>
          ${importBtn}${deleteBtn}
        </div>`;
      }
    }
    html += `</div>`;
  } else if (totalStaged === 0) {
    html += `<div class="ab-home-empty">No files staged. Drop files onto a category above or place them in the import directory.</div>`;
  }

  html += `</div>`;

  // === Zone 2: Custom Assets Summary ===
  const totalCustom = homeData.total_custom || 0;
  html += `<div class="ab-home-section">
    <div class="ab-home-section-header">
      <h2 class="ab-home-section-title">Custom Assets</h2>
      <span class="ab-home-total">${totalCustom} total</span>
    </div>
    <div class="ab-custom-grid">`;

  for (const cat of homeData.categories) {
    if (cat.custom_count === 0) continue;
    html += `<div class="ab-custom-card" data-browse="${cat.id}">
      <div class="ab-custom-card-count">${cat.custom_count}</div>
      <div class="ab-custom-card-name">${esc(cat.name)}</div>
      <div class="ab-custom-card-browse">Browse \u2192</div>
    </div>`;
  }
  if (totalCustom === 0) {
    html += `<div class="ab-home-empty">No custom assets imported yet.</div>`;
  }

  html += `</div></div>`;

  // === Zone 3: Import Archive ===
  const backupTotal = homeData.backup_total || 0;
  if (backupTotal > 0) {
    html += `<div class="ab-home-section ab-archive-section">
      <div class="ab-home-section-header">
        <h2 class="ab-home-section-title">Import Archive</h2>
        <span class="ab-home-total">${backupTotal} file${backupTotal !== 1 ? "s" : ""} backed up</span>
        <button class="ab-archive-clear-btn">Clear Archive</button>
      </div>
    </div>`;
  }

  contentArea.innerHTML = html;

  // === Wire event handlers ===
  _wireHomeHandlers(container, contentArea);
}

function _wireHomeHandlers(container, contentArea) {
  // Drop zones
  contentArea.querySelectorAll(".ab-drop-zone").forEach(zone => {
    const typeKey = zone.dataset.typeKey;

    zone.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      zone.classList.add("ab-drop-active");
    });
    zone.addEventListener("dragleave", () => {
      zone.classList.remove("ab-drop-active");
    });
    zone.addEventListener("drop", async (e) => {
      e.preventDefault();
      zone.classList.remove("ab-drop-active");
      const files = Array.from(e.dataTransfer.files);
      for (const file of files) {
        await _uploadFile(file, typeKey, container);
      }
    });
  });

  // Copy path button
  const pathBtn = contentArea.querySelector(".ab-home-path-btn");
  if (pathBtn) {
    pathBtn.addEventListener("click", () => {
      navigator.clipboard.writeText(pathBtn.textContent).then(() => {
        const orig = pathBtn.textContent;
        pathBtn.textContent = "Copied!";
        setTimeout(() => { pathBtn.textContent = orig; }, 1500);
      });
    });
  }

  // Import buttons
  contentArea.querySelectorAll(".ab-staged-import-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "Importing...";
      const res = await postApi("/assets/staged/import", {
        type_key: btn.dataset.type, filename: btn.dataset.file });
      if (res && res.ok) {
        btn.textContent = "\u2714 Done";
        btn.classList.add("ab-import-done");
        await _refreshHome(container);
      } else {
        btn.textContent = "\u2716 Failed";
        btn.disabled = false;
        setTimeout(() => { btn.textContent = "Import"; }, 2000);
      }
    });
  });

  // Delete buttons
  contentArea.querySelectorAll(".ab-staged-delete-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const res = await deleteApi(`/assets/staged/${btn.dataset.type}/${btn.dataset.file}`);
      if (res && res.ok) {
        await _refreshHome(container);
      }
    });
  });

  // Import All button
  const importAllBtn = contentArea.querySelector(".ab-import-all-btn");
  if (importAllBtn) {
    importAllBtn.addEventListener("click", async () => {
      importAllBtn.disabled = true;
      importAllBtn.textContent = "Importing...";
      const res = await postApi("/assets/staged/import", { type_key: "all" });
      if (res && res.ok) {
        const count = res.data.total_imported || 0;
        importAllBtn.textContent = `\u2714 ${count} imported`;
        importAllBtn.classList.add("ab-import-done");
        await _refreshHome(container);
      } else {
        importAllBtn.textContent = "\u2716 Failed";
        importAllBtn.disabled = false;
      }
    });
  }

  // Custom asset cards — click to browse that category filtered to custom
  contentArea.querySelectorAll(".ab-custom-card").forEach(card => {
    card.addEventListener("click", () => {
      filterMode = "custom";
      switchCategory(container, card.dataset.browse);
    });
  });

  // Clear archive button
  const clearBtn = contentArea.querySelector(".ab-archive-clear-btn");
  if (clearBtn) {
    clearBtn.addEventListener("click", async () => {
      clearBtn.disabled = true;
      clearBtn.textContent = "Clearing...";
      const res = await deleteApi("/assets/imported/clear");
      if (res && res.ok) {
        await _refreshHome(container);
      } else {
        clearBtn.textContent = "Failed";
        clearBtn.disabled = false;
      }
    });
  }
}

async function _uploadFile(file, typeKey, container) {
  if (file.size > 2 * 1024 * 1024) {
    alert(`${file.name} exceeds 2MB limit`);
    return;
  }
  const reader = new FileReader();
  reader.onload = async () => {
    const base64 = reader.result.split(",")[1];
    const res = await postApi("/assets/upload", {
      type_key: typeKey,
      filename: file.name,
      data: base64,
    });
    if (res && res.ok) {
      await _refreshHome(container);
    } else {
      alert(res?.error || "Upload failed");
    }
  };
  reader.readAsDataURL(file);
}

async function _refreshHome(container) {
  await fetchHomeData();
  await fetchCategories();
  _buildCatMap();
  // Update home badge
  const homeTab = container.querySelector('[data-cat="__home__"]');
  if (homeTab && homeData) {
    const count = homeData.total_staged || 0;
    const badge = count > 0 ? ` <span class="ab-tab-count ab-home-badge">(${count} staged)</span>` : "";
    homeTab.innerHTML = `Home${badge}`;
  }
  updateTabCounts(container);
  if (showingHome) {
    await renderHomeTab(container);
  }
}

// ---------------------------------------------------------------------------
// Main render + re-render
// ---------------------------------------------------------------------------

async function renderContent(container) {
  const visual = isVisualCategory();
  const contentClass = visual ? "ab-grid" : "ab-list";

  container.querySelector(".ab-content-area").innerHTML = `
    ${renderSummaryBar()}
    ${renderToolbar()}
    <div class="${contentClass}"></div>
  `;

  renderedCount = 0;
  appendItems(container, PAGE_SIZE);
  wireToolbar(container);
}

function wireToolbar(container) {
  // Filter buttons
  container.querySelectorAll(".ab-filter-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      filterMode = btn.dataset.filter;
      container.querySelectorAll(".ab-filter-btn").forEach(b =>
        b.classList.toggle("active", b.dataset.filter === filterMode));
      await reloadAssets(container);
    });
  });

  // Sort buttons
  container.querySelectorAll(".ab-sort-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      sortMode = btn.dataset.sort;
      container.querySelectorAll(".ab-sort-btn").forEach(b =>
        b.classList.toggle("active", b.dataset.sort === sortMode));
      await reloadAssets(container);
    });
  });

  // Search input
  const searchInput = container.querySelector(".ab-search");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(async () => {
        searchQuery = searchInput.value.trim();
        await reloadAssets(container);
      }, 250);
    });
  }
}

async function reloadAssets(container) {
  await fetchAssets(activeCategory);
  applyClientFilter();
  await renderContent(container);
  // Update tab counts
  updateTabCounts(container);
}

function updateTabCounts(container) {
  container.querySelectorAll(".ab-tab").forEach(btn => {
    const catId = btn.dataset.cat;
    const cat = categories.find(c => c.id === catId);
    if (cat) {
      const countEl = btn.querySelector(".ab-tab-count");
      if (countEl) countEl.textContent = `(${cat.count})`;
    }
  });
}

async function switchCategory(container, categoryId) {
  // Handle Home tab
  if (categoryId === "__home__") {
    showingHome = true;
    activeCategory = "__home__";
    container.querySelectorAll(".ab-tab").forEach(btn =>
      btn.classList.toggle("active", btn.dataset.cat === "__home__"));
    await renderHomeTab(container);
    return;
  }

  showingHome = false;
  // Preserve filterMode if explicitly set before this call (e.g. from custom card click)
  const preserveFilter = filterMode !== "all";
  activeCategory = categoryId;
  // Reset search and sort on category switch; only reset filter if not pre-set
  searchQuery = "";
  if (!preserveFilter) filterMode = "all";
  sortMode = "id";

  // Update tab active state
  container.querySelectorAll(".ab-tab").forEach(btn =>
    btn.classList.toggle("active", btn.dataset.cat === categoryId));

  container.querySelector(".ab-content-area").innerHTML =
    `<div class="ab-loading">Loading ${esc(_CATEGORIES_MAP[categoryId] || categoryId)}...</div>`;

  await fetchAssets(categoryId);
  applyClientFilter();
  await renderContent(container);
}

// Quick lookup for category names
const _CATEGORIES_MAP = {};
function _buildCatMap() {
  for (const c of categories) _CATEGORIES_MAP[c.id] = c.name;
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

export async function render(container) {
  mainContainer = container;
  container.innerHTML = `<div class="ab-loading">Loading Assets...</div>`;

  // Inject scoped styles
  if (!styleEl) {
    styleEl = document.createElement("style");
    styleEl.textContent = AB_STYLES;
    document.head.appendChild(styleEl);
  }

  // Load MIDI player (non-blocking)
  loadMidiPlayer();

  // Fetch categories and home dashboard data in parallel
  await Promise.all([fetchCategories(), fetchHomeData()]);
  _buildCatMap();

  if (!categories.length) {
    container.innerHTML = `<div class="ab-loading" style="color:var(--status-error)">No asset categories found. Is a game project configured?</div>`;
    return;
  }

  container.innerHTML = `
    <div class="ab-root">
      ${renderCategoryTabs()}
      <div class="ab-content-area"></div>
    </div>
  `;

  // Wire category tabs
  container.querySelectorAll(".ab-tab").forEach(btn => {
    btn.addEventListener("click", () => switchCategory(container, btn.dataset.cat));
  });

  // Default to Home tab
  if (activeCategory === "__home__") {
    await renderHomeTab(container);
  } else {
    // Ensure active category is valid
    if (!categories.find(c => c.id === activeCategory)) {
      activeCategory = categories[0].id;
    }
    showingHome = false;
    await fetchAssets(activeCategory);
    applyClientFilter();
    await renderContent(container);
  }

  // Infinite scroll
  scrollHandler = () => {
    if (renderedCount >= filteredAssets.length) return;
    const threshold = document.documentElement.scrollHeight - window.innerHeight - 400;
    if (window.scrollY >= threshold) {
      appendItems(container, PAGE_SIZE);
    }
  };
  window.addEventListener("scroll", scrollHandler);
}

export function cleanup() {
  if (scrollHandler) {
    window.removeEventListener("scroll", scrollHandler);
    scrollHandler = null;
  }
  if (styleEl) {
    styleEl.remove();
    styleEl = null;
  }
  // Stop MIDI playback on view change
  if (midiPlayer && midiPlayer.isPlaying()) {
    midiPlayer.stop();
  }
  currentlyPlayingConst = null;
  clearTimeout(debounceTimer);
  categories = [];
  allAssets = [];
  filteredAssets = [];
  selectedAsset = null;
  renderedCount = 0;
  mainContainer = null;
  filterMode = "all";
  searchQuery = "";
  sortMode = "id";
  activeCategory = "__home__";
  homeData = null;
  showingHome = true;
}

// ---------------------------------------------------------------------------
// Scoped CSS
// ---------------------------------------------------------------------------

const AB_STYLES = `
/* Asset Browser — scoped styles */

.ab-root {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 1rem 1rem;
}

/* Sticky navbar tabs */
.ab-tabs {
  position: sticky;
  top: 0;
  z-index: 50;
  display: flex;
  flex-wrap: wrap;
  gap: 0;
  background: var(--surface-1);
  border-bottom: 1px solid var(--border-subtle);
  padding: 0;
  margin: 0 0 1rem;
}

.ab-tab {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 0.6rem 0.75rem;
  color: var(--text-muted);
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
  flex-shrink: 0;
}

.ab-tab:hover {
  color: var(--text-secondary);
  background: var(--surface-2);
}

.ab-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
  background: transparent;
}

.ab-tab-count {
  font-size: 0.7rem;
  opacity: 0.7;
}

/* Summary bar */
.ab-summary {
  color: var(--text-muted);
  font-size: 0.85rem;
  margin-bottom: 0.75rem;
}
.ab-summary strong {
  color: var(--text-primary);
}
.ab-summary-breakdown {
  opacity: 0.7;
}
.ab-summary-note {
  font-size: 0.75rem;
  color: var(--text-dim);
  font-style: italic;
  margin-top: 0.25rem;
}

/* Toolbar */
.ab-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  margin-bottom: 1rem;
}

.ab-filter-group,
.ab-sort-group {
  display: flex;
  gap: 2px;
}

.ab-filter-btn,
.ab-sort-btn {
  background: var(--surface-2);
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
  padding: 0.3rem 0.6rem;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.15s;
}

.ab-filter-btn:first-child,
.ab-sort-btn:first-child {
  border-radius: 4px 0 0 4px;
}

.ab-filter-btn:last-child,
.ab-sort-btn:last-child {
  border-radius: 0 4px 4px 0;
}

.ab-filter-btn.active,
.ab-sort-btn.active {
  background: var(--accent-bg);
  border-color: var(--accent-border-faint);
  color: var(--accent);
}

.ab-search {
  flex: 1;
  min-width: 180px;
  padding: 0.35rem 0.6rem;
  background: var(--surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.8rem;
}

.ab-search:focus {
  border-color: var(--accent);
  outline: none;
}

/* Grid layout for visual categories */
.ab-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 0.75rem;
}

.ab-grid-cell {
  position: relative;
  background: var(--surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 0.75rem 0.5rem 0.5rem;
  text-align: center;
  cursor: pointer;
  transition: all 0.15s;
  overflow: hidden;
}

.ab-grid-cell:hover {
  border-color: var(--accent);
  background: var(--accent-bg);
  transform: translateY(-1px);
}

.ab-cell-custom {
  border-color: var(--accent-border-faint);
}

.ab-cell-img {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 64px;
  margin-bottom: 0.35rem;
}

.ab-thumb {
  image-rendering: pixelated;
  max-width: 100%;
  height: auto;
}

.ab-thumb-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-3);
  border-radius: 4px;
  color: var(--text-dim);
  font-size: 1.5rem;
}

.ab-missing {
  position: relative;
  min-height: 48px;
}

.ab-missing::after {
  content: '?';
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 48px;
  color: var(--text-dim);
  font-size: 1.5rem;
  background: var(--surface-3);
  border-radius: 4px;
}

.ab-cell-name {
  font-size: 0.7rem;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ab-custom-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  background: var(--accent-bg-medium);
  color: var(--accent);
  font-size: 0.55rem;
  font-weight: 600;
  padding: 1px 4px;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

/* List layout for non-visual categories */
.ab-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ab-list-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: var(--surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.ab-list-row:hover {
  border-color: var(--accent);
  background: var(--accent-bg);
}

.ab-row-custom {
  border-left: 3px solid var(--accent);
}

.ab-row-icon {
  font-size: 1.1rem;
  flex-shrink: 0;
}

.ab-row-name {
  color: var(--text-primary);
  font-size: 0.85rem;
  font-weight: 500;
  flex: 1;
}

.ab-row-const {
  color: var(--text-dim);
  font-size: 0.7rem;
  font-family: monospace;
}

.ab-row-id {
  color: var(--text-dim);
  font-size: 0.7rem;
  min-width: 40px;
  text-align: right;
}

/* Loading indicator */
.ab-loading {
  color: var(--text-muted);
  padding: 2rem;
  text-align: center;
}

/* Detail panel (slide-in modal) */
.ab-detail-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0,0,0,0.6);
  z-index: 200;
  display: flex;
  justify-content: flex-end;
  animation: ab-fade-in 0.15s ease-out;
}

@keyframes ab-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes ab-slide-in {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

.ab-detail-panel {
  width: 380px;
  max-width: 90vw;
  height: 100vh;
  background: var(--surface-1);
  border-left: 1px solid var(--border-emphasis);
  padding: 1.5rem;
  overflow-y: auto;
  animation: ab-slide-in 0.2s ease-out;
  position: relative;
}

.ab-detail-close {
  position: absolute;
  top: 0.75rem;
  right: 0.75rem;
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 1.5rem;
  cursor: pointer;
  padding: 0.25rem 0.5rem;
  line-height: 1;
}

.ab-detail-close:hover {
  color: var(--text-primary);
}

.ab-detail-img {
  text-align: center;
  margin-bottom: 1rem;
  padding: 1rem;
  background: var(--surface-2);
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
}

.ab-detail-img img {
  image-rendering: pixelated;
  max-width: 100%;
  height: auto;
}

.ab-detail-name {
  margin: 0 0 0.5rem;
  color: var(--text-primary);
  font-size: 1.25rem;
}

.ab-detail-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.ab-badge {
  font-size: 0.7rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.ab-badge-custom {
  background: var(--accent-bg-medium);
  color: var(--accent);
}

.ab-badge-vanilla {
  background: rgba(136,136,136,0.15);
  color: var(--text-muted);
}

.ab-detail-id {
  color: var(--text-dim);
  font-size: 0.8rem;
}

.ab-detail-field {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
  align-items: baseline;
}

.ab-detail-label {
  color: var(--text-muted);
  font-size: 0.8rem;
  min-width: 80px;
  flex-shrink: 0;
}

.ab-detail-mono {
  font-family: monospace;
  font-size: 0.75rem;
  color: var(--text-secondary);
  word-break: break-all;
}

.ab-detail-section {
  margin-top: 1.25rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border-subtle);
}

.ab-detail-section h4 {
  margin: 0 0 0.5rem;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.ab-detail-trainer {
  font-size: 0.8rem;
  color: var(--text-primary);
  padding: 0.15rem 0;
}

.ab-detail-dim {
  color: var(--text-dim);
  font-size: 0.75rem;
}

/* Character sheet — cross-reference sprite display */
.ab-charsheet {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
  justify-content: center;
  padding: 0.75rem;
  background: var(--surface-2);
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
}

.ab-charsheet-sprite {
  text-align: center;
}

.ab-charsheet-sprite img {
  image-rendering: pixelated;
  display: block;
  margin: 0 auto 0.25rem;
}

.ab-charsheet-label {
  font-size: 0.65rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* Music play button */
.ab-play-btn {
  background: var(--accent-bg);
  border: 1px solid var(--accent-border-faint);
  color: var(--accent);
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s;
  min-width: 28px;
  text-align: center;
}

.ab-play-btn:hover {
  background: var(--accent-bg-medium);
}

.ab-play-btn.playing {
  background: var(--status-error-bg, rgba(255,80,80,0.15));
  border-color: var(--status-error, #f55);
  color: var(--status-error, #f55);
}

/* Studio back-link */
.ab-tab-studio {
  text-decoration: none;
  color: var(--text-dim);
  border-right: 1px solid var(--border-subtle);
  margin-right: 0.25rem;
}
.ab-tab-studio:hover {
  color: var(--text-secondary);
}

/* Assets home tab */
.ab-tab-home {
  font-weight: 600;
}
.ab-home-badge {
  color: var(--accent);
  font-weight: 600;
}

/* Home tab sections */
.ab-home-section {
  margin-bottom: 1.5rem;
  padding: 1rem;
  background: var(--surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
}

.ab-home-section-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.ab-home-section-title {
  margin: 0;
  font-size: 1rem;
  color: var(--text-primary);
  flex: 1;
}

.ab-home-section-actions {
  display: flex;
  gap: 0.5rem;
}

.ab-home-total {
  font-size: 0.8rem;
  color: var(--text-muted);
}

.ab-home-path-btn {
  background: var(--surface-3);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  color: var(--text-dim);
  font-family: monospace;
  font-size: 0.65rem;
  padding: 0.2rem 0.5rem;
  cursor: pointer;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ab-home-path-btn:hover {
  color: var(--text-secondary);
  border-color: var(--accent);
}

.ab-home-empty {
  color: var(--text-dim);
  font-size: 0.85rem;
  padding: 1rem;
  text-align: center;
  font-style: italic;
}

/* Drop zones grid */
.ab-drop-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.ab-drop-zone {
  border: 2px dashed var(--border-subtle);
  border-radius: 8px;
  padding: 0.75rem;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  min-height: 80px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.25rem;
}

.ab-drop-zone:hover {
  border-color: var(--accent-border-faint);
  background: var(--accent-bg);
}

.ab-drop-zone.ab-drop-active {
  border-color: var(--accent);
  background: var(--accent-bg-medium);
  transform: scale(1.02);
}

.ab-drop-icon {
  font-size: 1.3rem;
}

.ab-drop-name {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-primary);
}

.ab-drop-count {
  background: var(--accent-bg-medium);
  color: var(--accent);
  padding: 0 4px;
  border-radius: 3px;
  font-size: 0.65rem;
  margin-left: 2px;
}

.ab-drop-hint {
  font-size: 0.6rem;
  color: var(--text-dim);
}

.ab-drop-label {
  font-size: 0.6rem;
  color: var(--text-dim);
  margin-top: 0.25rem;
}

/* Staged files within Home */
.ab-staged-files {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

/* Custom asset summary cards */
.ab-custom-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 0.5rem;
}

.ab-custom-card {
  background: var(--surface-3);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 0.75rem;
  cursor: pointer;
  transition: all 0.15s;
  text-align: center;
}

.ab-custom-card:hover {
  border-color: var(--accent);
  background: var(--accent-bg);
  transform: translateY(-1px);
}

.ab-custom-card-count {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--accent);
}

.ab-custom-card-name {
  font-size: 0.75rem;
  color: var(--text-secondary);
  margin: 0.25rem 0;
}

.ab-custom-card-browse {
  font-size: 0.65rem;
  color: var(--text-dim);
}

/* Archive section */
.ab-archive-section {
  opacity: 0.7;
}

.ab-archive-section:hover {
  opacity: 1;
}

.ab-archive-clear-btn {
  background: var(--surface-3);
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
  padding: 0.2rem 0.6rem;
  border-radius: 4px;
  font-size: 0.7rem;
  cursor: pointer;
}

.ab-archive-clear-btn:hover {
  border-color: var(--status-error, #f55);
  color: var(--status-error, #f55);
}

/* Delete button for staged files */
.ab-staged-delete-btn {
  background: none;
  border: 1px solid transparent;
  color: var(--text-dim);
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  font-size: 0.7rem;
  cursor: pointer;
  flex-shrink: 0;
}

.ab-staged-delete-btn:hover {
  color: var(--status-error, #f55);
  border-color: var(--status-error, #f55);
}

/* Staged imports content (reused from old staged tab) */
.ab-staged-header {
  margin-bottom: 1.25rem;
  padding: 1rem;
  background: var(--surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
}

.ab-staged-summary {
  color: var(--text-secondary);
  font-size: 0.9rem;
  flex: 1;
}

.ab-staged-path {
  font-family: monospace;
  font-size: 0.7rem;
  color: var(--text-dim);
  width: 100%;
  word-break: break-all;
}

.ab-import-all-btn {
  background: var(--accent-bg);
  border: 1px solid var(--accent);
  color: var(--accent);
  padding: 0.4rem 1rem;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.ab-import-all-btn:hover {
  background: var(--accent-bg-medium);
}

.ab-import-all-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ab-import-all-btn.ab-import-done {
  background: rgba(80,200,80,0.15);
  border-color: #4c4;
  color: #4c4;
}

.ab-staged-category {
  margin-bottom: 1.5rem;
}

.ab-staged-cat-title {
  margin: 0 0 0.25rem;
  font-size: 1rem;
  color: var(--text-primary);
}

.ab-staged-cat-desc {
  font-size: 0.75rem;
  color: var(--text-dim);
  margin-bottom: 0.75rem;
}

.ab-staged-grid {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.ab-staged-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6rem 0.75rem;
  background: var(--surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  transition: all 0.15s;
}

.ab-staged-card.ab-staged-ready {
  border-left: 3px solid var(--accent);
}

.ab-staged-card.ab-staged-invalid {
  border-left: 3px solid var(--status-error, #f55);
  opacity: 0.7;
}

.ab-staged-card.ab-staged-imported {
  border-left: 3px solid var(--text-dim);
  opacity: 0.5;
}

.ab-staged-preview {
  flex-shrink: 0;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-3);
  border-radius: 4px;
  overflow: hidden;
}

.ab-staged-thumb {
  max-width: 48px;
  max-height: 48px;
}

.ab-staged-midi-icon {
  font-size: 1.5rem;
}

.ab-staged-info {
  flex: 1;
  min-width: 0;
}

.ab-staged-filename {
  font-size: 0.85rem;
  color: var(--text-primary);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ab-staged-const {
  font-family: monospace;
  font-size: 0.7rem;
  color: var(--text-dim);
}

.ab-staged-status {
  font-size: 0.7rem;
  margin-top: 0.15rem;
}

.ab-staged-ready .ab-staged-status {
  color: var(--accent);
}

.ab-staged-invalid .ab-staged-status {
  color: var(--status-error, #f55);
}

.ab-staged-imported .ab-staged-status {
  color: var(--text-dim);
}

.ab-staged-import-btn {
  background: var(--accent-bg);
  border: 1px solid var(--accent-border-faint);
  color: var(--accent);
  padding: 0.3rem 0.75rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s;
}

.ab-staged-import-btn:hover {
  background: var(--accent-bg-medium);
}

.ab-staged-import-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ab-staged-import-btn.ab-import-done {
  background: rgba(80,200,80,0.15);
  border-color: #4c4;
  color: #4c4;
}
`;
