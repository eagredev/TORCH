/**
 * TORCH Web GUI -- Shop Editor view.
 * Map list with shop detail, inline item editor, searchable item picker.
 */

import { api, postApi } from "../app.js";
import { esc } from "../utils.js";
import { renderStudioNavbar } from "../studioNav.js";

let debounceTimer = null;
let cachedMaps = null;
let styleEl = null;

// ---------------------------------------------------------------------------
// CSS
// ---------------------------------------------------------------------------

const STYLES = `
.shop-layout { display: flex; gap: 1.5rem; }
.shop-sidebar {
  min-width: 200px; max-width: 260px; flex-shrink: 0;
}
.shop-search {
  width: 100%; padding: 0.5rem; margin-bottom: 0.75rem;
  background: var(--bg-secondary, #1e1e2e); color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border, #313244); border-radius: 6px;
  font-size: 0.85rem;
}
.shop-map-list { list-style: none; padding: 0; margin: 0; }
.shop-map-item {
  padding: 0.5rem 0.75rem; cursor: pointer; border-radius: 6px;
  margin-bottom: 2px; transition: background 0.15s;
  display: flex; justify-content: space-between; align-items: center;
}
.shop-map-item:hover { background: var(--bg-hover, #313244); }
.shop-map-item.active { background: var(--bg-active, #45475a); }
.shop-map-name {
  color: var(--text-primary, #cdd6f4); font-weight: 500; font-size: 0.85rem;
}
.shop-map-count {
  color: var(--text-muted, #6c7086); font-size: 0.75rem;
  background: var(--bg-secondary, #1e1e2e); border-radius: 10px;
  padding: 0.1rem 0.5rem;
}

.shop-main { flex: 1; min-width: 0; }

.shop-card {
  background: var(--bg-secondary, #1e1e2e); border: 1px solid var(--border, #313244);
  border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 1rem;
}
.shop-card.editing {
  border-color: var(--accent, #cba6f7);
  box-shadow: 0 0 0 1px var(--accent, #cba6f7);
}
.shop-card-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 0.75rem;
}
.shop-label {
  color: var(--text-primary, #cdd6f4); font-weight: 600; font-size: 1rem;
}
.shop-format-badge {
  font-size: 0.7rem; padding: 0.15rem 0.5rem; border-radius: 10px;
  background: var(--bg-tertiary, #45475a); color: var(--text-muted, #6c7086);
  text-transform: uppercase; font-weight: 600; letter-spacing: 0.05em;
}
.shop-npc-info {
  color: var(--text-muted, #6c7086); font-size: 0.8rem; margin-bottom: 0.75rem;
}

.shop-item-list { list-style: none; padding: 0; margin: 0; }
.shop-item-row {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.35rem 0.5rem; border-radius: 4px;
  transition: background 0.1s;
}
.shop-item-row:hover { background: var(--bg-hover, #313244); }
.shop-item-num {
  color: var(--text-muted, #6c7086); font-size: 0.75rem; min-width: 1.5rem;
  text-align: right;
}
.shop-item-icon {
  width: 24px; height: 24px; image-rendering: pixelated;
  flex-shrink: 0;
}
.shop-item-name {
  color: var(--text-primary, #cdd6f4); font-size: 0.85rem; font-weight: 500;
}
.shop-item-const {
  color: var(--text-muted, #6c7086); font-size: 0.75rem; margin-left: auto;
}

/* Edit mode controls */
.shop-item-row.editing { cursor: grab; }
.shop-item-row.editing:active { cursor: grabbing; }
.shop-item-row.dragging {
  opacity: 0.4; background: var(--bg-active, #45475a);
}
.shop-item-row.drag-over {
  border-top: 2px solid var(--accent, #cba6f7);
}
.shop-item-actions {
  display: flex; gap: 0.25rem; align-items: center;
}
.shop-move-btn, .shop-delete-btn {
  background: none; border: none; cursor: pointer; padding: 0.2rem 0.4rem;
  border-radius: 4px; font-size: 0.8rem; line-height: 1;
}
.shop-move-btn {
  color: var(--text-muted, #6c7086);
}
.shop-move-btn:hover { color: var(--text-primary, #cdd6f4); background: var(--bg-hover, #313244); }
.shop-delete-btn { color: var(--red, #f38ba8); }
.shop-delete-btn:hover { background: rgba(243,139,168,0.15); }

.shop-add-btn, .shop-edit-btn, .shop-save-btn, .shop-cancel-btn {
  padding: 0.4rem 0.8rem; border: none; border-radius: 6px; cursor: pointer;
  font-size: 0.8rem; font-weight: 500;
}
.shop-edit-btn {
  background: var(--bg-tertiary, #45475a); color: var(--text-primary, #cdd6f4);
}
.shop-edit-btn:hover { background: var(--bg-hover, #585b70); }
.shop-save-btn {
  background: var(--green, #a6e3a1); color: var(--bg-primary, #1e1e2e);
}
.shop-save-btn:hover { filter: brightness(1.1); }
.shop-save-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.shop-cancel-btn {
  background: var(--bg-tertiary, #45475a); color: var(--text-primary, #cdd6f4);
}
.shop-cancel-btn:hover { background: var(--bg-hover, #585b70); }
.shop-add-btn {
  background: var(--bg-tertiary, #45475a); color: var(--text-primary, #cdd6f4);
  width: 100%; margin-top: 0.5rem;
}
.shop-add-btn:hover { background: var(--bg-hover, #585b70); }
.shop-edit-actions {
  display: flex; gap: 0.5rem; margin-top: 0.75rem; align-items: center;
}
.shop-save-status {
  font-size: 0.8rem; margin-left: 0.5rem;
}
.shop-save-ok { color: var(--green, #a6e3a1); }
.shop-save-err { color: var(--red, #f38ba8); }

/* Item picker modal */
.shop-picker-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.shop-picker {
  background: var(--bg-primary, #1e1e2e); border: 1px solid var(--border, #313244);
  border-radius: 10px; width: 380px; max-height: 450px;
  display: flex; flex-direction: column; box-shadow: 0 8px 32px rgba(0,0,0,0.4);
}
.shop-picker-header {
  padding: 0.75rem 1rem; border-bottom: 1px solid var(--border, #313244);
  font-weight: 600; color: var(--text-primary, #cdd6f4); font-size: 0.9rem;
}
.shop-picker-search {
  width: 100%; padding: 0.6rem 1rem; border: none;
  border-bottom: 1px solid var(--border, #313244);
  background: var(--bg-secondary, #1e1e2e); color: var(--text-primary, #cdd6f4);
  font-size: 0.85rem; outline: none;
}
.shop-picker-results {
  overflow-y: auto; flex: 1; padding: 0.25rem 0;
}
.shop-picker-item {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.5rem 1rem; cursor: pointer; transition: background 0.1s;
}
.shop-picker-item:hover { background: var(--bg-hover, #313244); }
.shop-picker-item img {
  width: 24px; height: 24px; image-rendering: pixelated; flex-shrink: 0;
}
.shop-picker-item-name {
  color: var(--text-primary, #cdd6f4); font-size: 0.85rem;
}
.shop-picker-item-const {
  color: var(--text-muted, #6c7086); font-size: 0.75rem; margin-left: auto;
}
.shop-picker-empty {
  padding: 1rem; text-align: center; color: var(--text-muted, #6c7086);
  font-size: 0.85rem;
}

.shop-empty {
  color: var(--text-muted, #6c7086); text-align: center; padding: 2rem;
  font-size: 0.9rem;
}
`;

// ---------------------------------------------------------------------------
// Map List
// ---------------------------------------------------------------------------

function renderMapList(container, maps, selectedMap) {
  const q = container.querySelector(".shop-search");
  const query = q ? q.value.trim().toLowerCase() : "";

  const filtered = query
    ? maps.filter(m => m.name.toLowerCase().includes(query))
    : maps;

  const list = container.querySelector(".shop-map-list");
  if (!list) return;

  list.innerHTML = filtered.map(m => `
    <li class="shop-map-item${m.name === selectedMap ? " active" : ""}"
        data-map="${esc(m.name)}">
      <span class="shop-map-name">${esc(m.name)}</span>
      <span class="shop-map-count">${m.shop_count}</span>
    </li>
  `).join("") || `<li class="shop-empty">No matches</li>`;

  list.querySelectorAll(".shop-map-item").forEach(item => {
    item.addEventListener("click", () => {
      window.location.hash = `#/shops/${item.dataset.map}`;
    });
  });
}

// ---------------------------------------------------------------------------
// Shop Detail
// ---------------------------------------------------------------------------

function renderShopCards(container, shops, mapName) {
  const main = container.querySelector(".shop-main");
  if (!main) return;

  if (!shops.length) {
    main.innerHTML = `<div class="shop-empty">No shops found in ${esc(mapName)}</div>`;
    return;
  }

  main.innerHTML = shops.map((shop, idx) => {
    const npcHtml = shop.npc
      ? `<div class="shop-npc-info">NPC #${shop.npc.object_id} at (${shop.npc.x}, ${shop.npc.y})${shop.npc.script_label ? ` &mdash; ${esc(shop.npc.script_label)}` : ""}</div>`
      : "";

    const itemsHtml = shop.items.map((item, i) => `
      <li class="shop-item-row" data-index="${i}">
        <span class="shop-item-num">${i + 1}</span>
        <img class="shop-item-icon" src="/api/items/icons/${esc(item)}"
             onerror="this.style.display='none'" alt="">
        <span class="shop-item-name">${esc(shop.item_names[i] || item)}</span>
        <span class="shop-item-const">${esc(item)}</span>
      </li>
    `).join("");

    return `
      <div class="shop-card" data-shop-idx="${idx}" data-label="${esc(shop.label)}">
        <div class="shop-card-header">
          <span class="shop-label">${esc(shop.label)}</span>
          <div style="display:flex;gap:0.5rem;align-items:center">
            <span class="shop-format-badge">${esc(shop.format)}</span>
            <button class="shop-edit-btn" data-idx="${idx}">Edit</button>
          </div>
        </div>
        ${npcHtml}
        <ul class="shop-item-list">${itemsHtml}</ul>
      </div>
    `;
  }).join("");

  // Attach edit button handlers
  main.querySelectorAll(".shop-edit-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.dataset.idx, 10);
      enterEditMode(container, shops, idx, mapName);
    });
  });
}

// ---------------------------------------------------------------------------
// Edit Mode
// ---------------------------------------------------------------------------

function enterEditMode(container, shops, idx, mapName) {
  const shop = shops[idx];
  const card = container.querySelector(`.shop-card[data-shop-idx="${idx}"]`);
  if (!card) return;

  const originalItems = [...shop.items];
  const originalNames = [...shop.item_names];
  let workingItems = [...shop.items];
  let workingNames = [...shop.item_names];

  card.classList.add("editing");

  function redraw() {
    const listEl = card.querySelector(".shop-item-list");
    listEl.innerHTML = workingItems.map((item, i) => `
      <li class="shop-item-row editing" draggable="true" data-index="${i}">
        <span class="shop-item-num">${i + 1}</span>
        <img class="shop-item-icon" src="/api/items/icons/${esc(item)}"
             onerror="this.style.display='none'" alt="">
        <span class="shop-item-name">${esc(workingNames[i] || item)}</span>
        <span class="shop-item-const">${esc(item)}</span>
        <div class="shop-item-actions">
          <button class="shop-move-btn" data-dir="up" data-i="${i}" title="Move up"
                  ${i === 0 ? "disabled" : ""}>&uarr;</button>
          <button class="shop-move-btn" data-dir="down" data-i="${i}" title="Move down"
                  ${i === workingItems.length - 1 ? "disabled" : ""}>&darr;</button>
          <button class="shop-delete-btn" data-i="${i}" title="Remove">&#x2715;</button>
        </div>
      </li>
    `).join("") || `<li class="shop-empty">No items — add some below</li>`;

    // Drag events
    attachDragHandlers(listEl, workingItems, workingNames, redraw);

    // Move buttons
    listEl.querySelectorAll(".shop-move-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const i = parseInt(btn.dataset.i, 10);
        const dir = btn.dataset.dir;
        if (dir === "up" && i > 0) {
          [workingItems[i - 1], workingItems[i]] = [workingItems[i], workingItems[i - 1]];
          [workingNames[i - 1], workingNames[i]] = [workingNames[i], workingNames[i - 1]];
        } else if (dir === "down" && i < workingItems.length - 1) {
          [workingItems[i + 1], workingItems[i]] = [workingItems[i], workingItems[i + 1]];
          [workingNames[i + 1], workingNames[i]] = [workingNames[i], workingNames[i + 1]];
        }
        redraw();
      });
    });

    // Delete buttons
    listEl.querySelectorAll(".shop-delete-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const i = parseInt(btn.dataset.i, 10);
        workingItems.splice(i, 1);
        workingNames.splice(i, 1);
        redraw();
      });
    });
  }

  // Replace the edit button area with save/cancel/add
  const headerRight = card.querySelector(".shop-card-header > div:last-child");
  const formatBadge = headerRight.querySelector(".shop-format-badge");
  headerRight.innerHTML = "";
  headerRight.appendChild(formatBadge);

  // Add button below list
  let actionsEl = card.querySelector(".shop-edit-actions");
  if (actionsEl) actionsEl.remove();
  actionsEl = document.createElement("div");
  actionsEl.className = "shop-edit-actions";
  actionsEl.innerHTML = `
    <button class="shop-add-btn">+ Add Item</button>
    <div style="flex:1"></div>
    <span class="shop-save-status"></span>
    <button class="shop-cancel-btn">Cancel</button>
    <button class="shop-save-btn">Save</button>
  `;
  card.appendChild(actionsEl);

  redraw();

  // Add item
  actionsEl.querySelector(".shop-add-btn").addEventListener("click", () => {
    openItemPicker((itemConst, itemName) => {
      workingItems.push(itemConst);
      workingNames.push(itemName);
      redraw();
    });
  });

  // Cancel
  actionsEl.querySelector(".shop-cancel-btn").addEventListener("click", () => {
    shop.items = originalItems;
    shop.item_names = originalNames;
    renderShopCards(container, shops, mapName);
  });

  // Save
  const saveBtn = actionsEl.querySelector(".shop-save-btn");
  const statusEl = actionsEl.querySelector(".shop-save-status");

  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    statusEl.textContent = "Saving...";
    statusEl.className = "shop-save-status";

    const res = await postApi(`/shops/${mapName}/${shop.label}`, {
      items: workingItems,
    });

    if (res.ok) {
      statusEl.textContent = "Saved!";
      statusEl.className = "shop-save-status shop-save-ok";
      shop.items = [...workingItems];
      shop.item_names = res.data.item_names || [...workingNames];
      setTimeout(() => renderShopCards(container, shops, mapName), 800);
    } else {
      statusEl.textContent = res.error || "Save failed";
      statusEl.className = "shop-save-status shop-save-err";
      saveBtn.disabled = false;
    }
  });
}

// ---------------------------------------------------------------------------
// Drag and Drop reorder
// ---------------------------------------------------------------------------

function attachDragHandlers(listEl, items, names, redrawFn) {
  let dragIdx = null;

  listEl.querySelectorAll(".shop-item-row.editing").forEach(row => {
    row.addEventListener("dragstart", (e) => {
      dragIdx = parseInt(row.dataset.index, 10);
      row.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
    });

    row.addEventListener("dragend", () => {
      row.classList.remove("dragging");
      listEl.querySelectorAll(".drag-over").forEach(el => el.classList.remove("drag-over"));
      dragIdx = null;
    });

    row.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      listEl.querySelectorAll(".drag-over").forEach(el => el.classList.remove("drag-over"));
      row.classList.add("drag-over");
    });

    row.addEventListener("dragleave", () => {
      row.classList.remove("drag-over");
    });

    row.addEventListener("drop", (e) => {
      e.preventDefault();
      row.classList.remove("drag-over");
      const dropIdx = parseInt(row.dataset.index, 10);
      if (dragIdx === null || dragIdx === dropIdx) return;

      const [movedItem] = items.splice(dragIdx, 1);
      const [movedName] = names.splice(dragIdx, 1);
      items.splice(dropIdx, 0, movedItem);
      names.splice(dropIdx, 0, movedName);
      redrawFn();
    });
  });
}

// ---------------------------------------------------------------------------
// Item Picker Modal
// ---------------------------------------------------------------------------

function openItemPicker(onSelect) {
  const overlay = document.createElement("div");
  overlay.className = "shop-picker-overlay";
  overlay.innerHTML = `
    <div class="shop-picker">
      <div class="shop-picker-header">Add Item</div>
      <input type="text" class="shop-picker-search" placeholder="Search items..."
             autocomplete="off">
      <div class="shop-picker-results">
        <div class="shop-picker-empty">Type to search...</div>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  const searchInput = overlay.querySelector(".shop-picker-search");
  const results = overlay.querySelector(".shop-picker-results");
  let pickerTimer = null;

  searchInput.focus();

  searchInput.addEventListener("input", () => {
    clearTimeout(pickerTimer);
    pickerTimer = setTimeout(async () => {
      const q = searchInput.value.trim();
      if (!q) {
        results.innerHTML = `<div class="shop-picker-empty">Type to search...</div>`;
        return;
      }

      const res = await api(`/items?q=${encodeURIComponent(q)}`);
      if (!res.ok) {
        results.innerHTML = `<div class="shop-picker-empty">Error loading items</div>`;
        return;
      }

      const itemList = (res.data || []).slice(0, 20);
      if (!itemList.length) {
        results.innerHTML = `<div class="shop-picker-empty">No items found</div>`;
        return;
      }

      results.innerHTML = itemList.map(it => `
        <div class="shop-picker-item" data-const="${esc(it.const)}" data-name="${esc(it.name)}">
          <img src="${esc(it.icon)}" width="24" height="24"
               onerror="this.style.display='none'" alt="">
          <span class="shop-picker-item-name">${esc(it.name)}</span>
          <span class="shop-picker-item-const">${esc(it.const)}</span>
        </div>
      `).join("");

      results.querySelectorAll(".shop-picker-item").forEach(item => {
        item.addEventListener("click", () => {
          onSelect(item.dataset.const, item.dataset.name);
          overlay.remove();
        });
      });
    }, 200);
  });

  // Close on Escape or click outside
  function closePicker(e) {
    if (e.type === "keydown" && e.key !== "Escape") return;
    if (e.type === "click" && overlay.querySelector(".shop-picker").contains(e.target)) return;
    clearTimeout(pickerTimer);
    overlay.remove();
    document.removeEventListener("keydown", closePicker);
    document.removeEventListener("click", closePicker, true);
  }
  setTimeout(() => {
    document.addEventListener("keydown", closePicker);
    document.addEventListener("click", closePicker, true);
  }, 10);
}

// ---------------------------------------------------------------------------
// Main render
// ---------------------------------------------------------------------------

async function renderList(container) {
  container.innerHTML = `<article>
    ${renderStudioNavbar("Shops")}
    <div class="shop-empty">Loading...</div>
  </article>`;

  const res = await api("/shops");
  if (!res.ok) {
    container.innerHTML = `<article>
      ${renderStudioNavbar("Shops")}
      <div class="shop-empty">Error: ${esc(res.error)}</div>
    </article>`;
    return;
  }

  const maps = res.data.maps || [];

  if (!maps.length) {
    container.innerHTML = `<article>
      ${renderStudioNavbar("Shops")}
      <div class="shop-empty">
        No shops detected. Shops are found by scanning for MART_EMPLOYEE NPCs in enrolled maps.
      </div>
    </article>`;
    return;
  }

  cachedMaps = maps;

  container.innerHTML = `<article>
    ${renderStudioNavbar("Shops")}
    <div class="shop-layout">
      <aside class="shop-sidebar">
        <input type="text" class="shop-search" placeholder="Search maps...">
        <ul class="shop-map-list"></ul>
      </aside>
      <div class="shop-main">
        <div class="shop-empty">Select a map to view its shops</div>
      </div>
    </div>
  </article>`;

  renderMapList(container, maps, null);

  container.querySelector(".shop-search").addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      const hash = window.location.hash || "";
      const m = hash.match(/^#\/shops\/(.+)$/);
      renderMapList(container, maps, m ? decodeURIComponent(m[1]) : null);
    }, 150);
  });
}

async function renderDetail(container, mapName) {
  // If we have cached maps from the list, render sidebar + detail
  if (!cachedMaps) {
    const listRes = await api("/shops");
    if (listRes.ok) cachedMaps = listRes.data.maps || [];
  }

  const detailRes = await api(`/shops/${mapName}`);
  if (!detailRes.ok) {
    container.innerHTML = `<article>
      <a href="#/shops" class="detail-back">&larr; Back to Shops</a>
      <header><h2>Shops</h2></header>
      <div class="shop-empty">Error: ${esc(detailRes.error)}</div>
    </article>`;
    return;
  }

  const shops = detailRes.data.shops || [];

  container.innerHTML = `<article>
    <a href="#/shops" class="detail-back">&larr; Back to Shops</a>
    <header><h2>Shops</h2></header>
    <div class="shop-layout">
      <aside class="shop-sidebar">
        <input type="text" class="shop-search" placeholder="Search maps...">
        <ul class="shop-map-list"></ul>
      </aside>
      <div class="shop-main"></div>
    </div>
  </article>`;

  if (cachedMaps) {
    renderMapList(container, cachedMaps, mapName);
    container.querySelector(".shop-search").addEventListener("input", () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        renderMapList(container, cachedMaps, mapName);
      }, 150);
    });
  }

  renderShopCards(container, shops, mapName);
}

export async function render(container) {
  // Inject scoped styles
  if (!styleEl) {
    styleEl = document.createElement("style");
    styleEl.textContent = STYLES;
    document.head.appendChild(styleEl);
  }

  const hash = window.location.hash || "";
  const detailMatch = hash.match(/^#\/shops\/(.+)$/);
  if (detailMatch) {
    await renderDetail(container, decodeURIComponent(detailMatch[1]));
    return;
  }
  await renderList(container);
}

export function cleanup() {
  clearTimeout(debounceTimer);
  debounceTimer = null;
  cachedMaps = null;
  if (styleEl) {
    styleEl.remove();
    styleEl = null;
  }
}
