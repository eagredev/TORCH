/**
 * TORCH Web GUI -- NPC Editor view.
 * Map browser with NPC card grid, overworld sprite display, type badges.
 */

import { api, postApi } from "../app.js";
import { esc } from "../utils.js";
import { renderStudioNavbar } from "../studioNav.js";
import { renderNpcDetail, cleanupNpcDetail, wrapGbaText, renderGbaPreview } from "./npcDetail.js";
import { openNpcWizard } from "./npcWizard.js";

// === Module State ===
let cachedMaps = null;
let styleEl = null;
let debounceTimer = null;

// === Type border accent colors ===
const TYPE_BORDER_COLORS = {
  flavor:     "#6c7086",
  sign:       "#89b4fa",
  item_giver: "#f9e2af",
  nurse:      "#f5c2e7",
  pc:         "#94e2d5",
  complex:    "#cba6f7",
  custom:     "#cba6f7",
  trainer:    "#f38ba8",
  unknown:    "#6c7086",
  none:       "#6c7086",
};

// === Scoped CSS ===
const STYLES = `
.npc-layout { display: flex; gap: 1.5rem; }
.npc-sidebar {
  min-width: 200px; max-width: 260px; flex-shrink: 0;
}
.npc-search {
  width: 100%; padding: 0.5rem; margin-bottom: 0.75rem;
  background: var(--bg-secondary, #1e1e2e); color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border, #313244); border-radius: 6px;
  font-size: 0.85rem;
}
.npc-map-list { list-style: none; padding: 0; margin: 0; }
.npc-map-item {
  padding: 0.5rem 0.75rem; cursor: pointer; border-radius: 6px;
  margin-bottom: 2px; transition: background 0.15s;
  display: flex; justify-content: space-between; align-items: center;
  gap: 0.5rem;
}
.npc-map-item:hover { background: var(--bg-hover, #313244); }
.npc-map-item.active { background: var(--bg-active, #45475a); }
.npc-map-name {
  color: var(--text-primary, #cdd6f4); font-weight: 500; font-size: 0.85rem;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1;
}
.npc-map-badges {
  display: flex; gap: 0.25rem; align-items: center; flex-shrink: 0;
}
.npc-map-count {
  color: var(--text-muted, #6c7086); font-size: 0.75rem;
  background: var(--bg-secondary, #1e1e2e); border-radius: 10px;
  padding: 0.1rem 0.5rem;
}
.npc-map-nurse {
  font-size: 0.7rem; color: #f5c2e7; title: "Has Nurse";
}
.npc-map-trainers {
  font-size: 0.65rem; color: #f38ba8;
  background: rgba(243,139,168,0.1); border-radius: 10px;
  padding: 0.1rem 0.4rem; font-weight: 600;
}

.npc-main { flex: 1; min-width: 0; }

.npc-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 0.75rem;
}

.npc-card {
  background: var(--bg-secondary, #1e1e2e);
  border: 1px solid var(--border, #313244);
  border-left: 3px solid var(--type-color, #6c7086);
  border-radius: 8px;
  padding: 0.75rem;
  transition: border-color 0.15s;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.npc-card:hover {
  border-color: var(--accent, #cba6f7);
  border-left-color: var(--type-color, #6c7086);
  box-shadow: 0 2px 8px rgba(0,0,0,0.2);
}
.npc-card.dirty {
  border-left-color: #f9e2af !important;
}
.npc-card.saved {
  border-left-color: #a6e3a1 !important;
  transition: border-left-color 0.3s;
}

.npc-card-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.npc-sprite {
  height: 48px;
  width: auto;
  image-rendering: pixelated;
  object-fit: contain;
  flex-shrink: 0;
}
.npc-sprite-placeholder {
  width: 32px; height: 48px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: var(--bg-tertiary, #45475a); border-radius: 4px;
  color: var(--text-muted, #6c7086); font-size: 1.2rem; font-weight: 700;
}
.npc-card-info { flex: 1; min-width: 0; }
.npc-card-name {
  color: var(--text-primary, #cdd6f4); font-weight: 600; font-size: 0.85rem;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  cursor: pointer;
}
.npc-card-name:hover { color: var(--accent, #cba6f7); text-decoration: underline; }
.npc-card-meta {
  color: var(--text-muted, #6c7086); font-size: 0.75rem; margin-top: 0.15rem;
}
.npc-card-menu {
  background: none; border: none; cursor: pointer; padding: 0.2rem 0.4rem;
  color: var(--text-muted, #6c7086); font-size: 1rem; border-radius: 4px;
  flex-shrink: 0; line-height: 1;
}
.npc-card-menu:hover { background: var(--bg-hover, #313244); color: var(--text-primary, #cdd6f4); }

.npc-card-textarea {
  width: 100%; min-height: 3.5em; resize: vertical;
  background: var(--bg-tertiary, #45475a); color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border, #313244); border-radius: 4px;
  padding: 0.4rem 0.5rem; font-size: 0.8rem; font-family: inherit;
  box-sizing: border-box;
}
.npc-card-textarea:focus {
  outline: none;
  border-color: var(--accent, #89b4fa);
  box-shadow: 0 0 0 2px rgba(137,180,250,0.2);
}
.npc-card-textarea::placeholder {
  color: var(--text-muted, #6c7086);
  font-style: italic;
}
.npc-card-shared {
  color: var(--text-muted, #6c7086); font-size: 0.8rem; font-style: italic;
  padding: 0.3rem 0;
}
.npc-card-preview {
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.2s ease-out;
  margin-top: 0;
}
.npc-card-preview.visible {
  max-height: 200px;
  margin-top: 0.25rem;
}
.npc-card-preview .npcd-gba-preview-wrap {
  flex-direction: row;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.npc-card-footer {
  display: flex; align-items: center; gap: 0.5rem; min-height: 1.5rem;
}
.npc-card-save {
  padding: 0.25rem 0.65rem; font-size: 0.75rem; font-weight: 600;
  background: rgba(166,227,161,0.15); color: #a6e3a1;
  border: none; border-radius: 4px; cursor: pointer;
}
.npc-card-save:hover { background: rgba(166,227,161,0.3); }
.npc-card-status { font-size: 0.75rem; color: var(--text-muted, #6c7086); }
.npc-card-status.error { color: #f38ba8; }

.npc-card-badges { display: flex; gap: 0.3rem; flex-wrap: wrap; }

.npc-type-badge {
  font-size: 0.65rem;
  padding: 0.1rem 0.45rem;
  border-radius: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.npc-type-flavor   { background: var(--bg-tertiary, #45475a); color: var(--text-muted, #6c7086); }
.npc-type-sign     { background: rgba(137,180,250,0.15); color: #89b4fa; }
.npc-type-item_giver { background: rgba(249,226,175,0.15); color: #f9e2af; }
.npc-type-nurse    { background: rgba(245,194,231,0.15); color: #f5c2e7; }
.npc-type-pc       { background: rgba(148,226,213,0.15); color: #94e2d5; }
.npc-type-complex  { background: rgba(203,166,247,0.15); color: #cba6f7; }
.npc-type-unknown, .npc-type-none {
  background: var(--bg-tertiary, #45475a); color: var(--text-muted, #6c7086);
}
.npc-trainer-badge {
  background: rgba(243,139,168,0.15); color: #f38ba8;
  font-size: 0.65rem; padding: 0.1rem 0.45rem; border-radius: 10px;
  font-weight: 600; text-transform: uppercase;
}

.npc-section-divider {
  margin: 1.5rem 0 1rem;
  border: none; border-top: 1px solid var(--border, #313244);
  position: relative;
}
.npc-section-title {
  color: var(--text-muted, #6c7086); font-size: 0.8rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.75rem;
}

.npc-bg-list { list-style: none; padding: 0; margin: 0; }
.npc-bg-item {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.35rem 0.5rem; border-radius: 4px; font-size: 0.8rem;
  color: var(--text-secondary, #bac2de);
}
.npc-bg-item:hover { background: var(--bg-hover, #313244); }
.npc-bg-type {
  font-weight: 600; color: var(--text-primary, #cdd6f4);
  min-width: 3.5rem;
}
.npc-bg-pos { color: var(--text-muted, #6c7086); font-size: 0.75rem; }
.npc-bg-script {
  color: var(--text-muted, #6c7086); font-size: 0.75rem;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

.npc-empty {
  color: var(--text-muted, #6c7086); text-align: center; padding: 2rem;
  font-size: 0.9rem;
}
.npc-empty-state {
  text-align: center; padding: 3rem 1rem;
  color: var(--text-muted, #6c7086);
}
.npc-empty-icon {
  font-size: 2rem; margin-bottom: 0.5rem; opacity: 0.4;
}
.npc-skeleton {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 0.75rem;
}
.npc-skeleton-card {
  height: 160px;
  background: var(--bg-secondary, #1e1e2e);
  border: 1px solid var(--border, #313244);
  border-radius: 8px;
  animation: npc-pulse 1.5s ease-in-out infinite;
}
@keyframes npc-pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 0.8; }
}
.npc-grid-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 1rem;
}
.npc-grid-title {
  font-size: 0.9rem; font-weight: 600; color: var(--text-secondary, #bac2de);
}
.npc-add-btn {
  padding: 0.35rem 0.85rem;
  background: rgba(166,227,161,0.15); color: #a6e3a1;
  border: none; border-radius: 6px; cursor: pointer;
  font-size: 0.8rem; font-weight: 600;
}
.npc-add-btn:hover { background: rgba(166,227,161,0.3); }
.npc-health-error {
  background: rgba(243,139,168,0.2); color: #f38ba8;
  font-size: 0.65rem; padding: 0.1rem 0.4rem; border-radius: 10px;
  font-weight: 700; cursor: default;
}
.npc-health-warn {
  background: rgba(249,226,175,0.2); color: #f9e2af;
  font-size: 0.65rem; padding: 0.1rem 0.4rem; border-radius: 10px;
  font-weight: 700; cursor: default;
}
.npc-stats {
  display: flex; gap: 1.5rem; margin-bottom: 1rem; flex-wrap: wrap;
}
.npc-stat {
  background: var(--bg-secondary, #1e1e2e); border: 1px solid var(--border, #313244);
  border-radius: 8px; padding: 0.75rem 1rem; text-align: center; min-width: 100px;
}
.npc-stat-value {
  font-size: 1.25rem; font-weight: 700; color: var(--text-primary, #cdd6f4);
}
.npc-stat-label {
  font-size: 0.75rem; color: var(--text-muted, #6c7086); text-transform: uppercase;
  letter-spacing: 0.05em; margin-top: 0.25rem;
}
`;

function injectCSS() {
  if (!styleEl) {
    styleEl = document.createElement("style");
    styleEl.textContent = STYLES;
    document.head.appendChild(styleEl);
  }
}

// ---------------------------------------------------------------------------
// Map List (sidebar)
// ---------------------------------------------------------------------------

function renderMapList(container, maps, selectedMap) {
  const q = container.querySelector(".npc-search");
  const query = q ? q.value.trim().toLowerCase() : "";

  const filtered = query
    ? maps.filter(m => m.name.toLowerCase().includes(query))
    : maps;

  const list = container.querySelector(".npc-map-list");
  if (!list) return;

  list.innerHTML = filtered.map(m => {
    const nurseBadge = m.has_nurse ? `<span class="npc-map-nurse" title="Has Nurse">+</span>` : "";
    const trainerBadge = m.trainer_count > 0
      ? `<span class="npc-map-trainers" title="${m.trainer_count} trainer${m.trainer_count !== 1 ? "s" : ""}">${m.trainer_count}T</span>`
      : "";
    return `
      <li class="npc-map-item${m.name === selectedMap ? " active" : ""}"
          data-map="${esc(m.name)}">
        <span class="npc-map-name">${esc(m.name)}</span>
        <span class="npc-map-badges">
          ${nurseBadge}${trainerBadge}
          <span class="npc-map-count">${m.npc_count}</span>
        </span>
      </li>
    `;
  }).join("") || `<li class="npc-empty">No matches</li>`;

  list.querySelectorAll(".npc-map-item").forEach(item => {
    item.addEventListener("click", () => {
      window.location.hash = `#/npcs/${item.dataset.map}`;
    });
  });
}

// ---------------------------------------------------------------------------
// NPC Card Grid
// ---------------------------------------------------------------------------

function renderNpcCards(container, npcs, bgEvents, mapName, onRefresh) {
  const main = container.querySelector(".npc-main");
  if (!main) return;

  // Always show the header with [+ New NPC]
  let html = `<div class="npc-grid-header">
    <span class="npc-grid-title">${esc(mapName)} &mdash; ${npcs.length} NPC${npcs.length !== 1 ? "s" : ""}</span>
    <button class="npc-add-btn" data-action="add-npc">+ New NPC</button>
  </div>`;

  if (!npcs.length && !bgEvents.length) {
    html += `<div class="npc-empty-state">
      <div class="npc-empty-icon">--</div>
      <div>No NPCs in this map yet.</div>
      <button class="npc-add-btn" data-action="add-npc" style="margin-top:0.75rem">+ Create First NPC</button>
    </div>`;
    main.innerHTML = html;
    wireAddButton(main, mapName, onRefresh);
    return;
  }

  if (npcs.length) {
    html += `<div class="npc-grid">`;
    html += npcs.map(npc => {
      const borderColor = npc.is_trainer
        ? TYPE_BORDER_COLORS.trainer
        : (TYPE_BORDER_COLORS[npc.script_type] || TYPE_BORDER_COLORS.unknown);

      const spriteHtml = npc.sprite_url
        ? `<img class="npc-sprite" src="${esc(npc.sprite_url)}" alt=""
               onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
           <div class="npc-sprite-placeholder" style="display:none">?</div>`
        : `<div class="npc-sprite-placeholder">?</div>`;

      const posText = `(${npc.x}, ${npc.y})`;
      const typeClass = `npc-type-${(npc.script_type || "unknown").replace(/[^a-z_]/g, "")}`;
      const typeBadge = `<span class="npc-type-badge ${typeClass}">${esc(npc.script_type || "unknown")}</span>`;
      const trainerBadge = npc.is_trainer ? `<span class="npc-trainer-badge">Trainer</span>` : "";

      // Shared-script types get a read-only note; editable types get a textarea
      const isShared = npc.script_type === "nurse" || npc.script_type === "pc";
      const dialogueArea = isShared
        ? `<div class="npc-card-shared">Uses shared script: ${esc(npc.script || "")}</div>`
        : `<textarea class="npc-card-textarea" data-npc-id="${npc.object_id}"
               data-original="${esc(npc.dialogue_preview || "")}"
               placeholder="Enter dialogue...">${esc(npc.dialogue_preview || "")}</textarea>
           <div class="npc-card-preview" data-preview-for="${npc.object_id}"></div>`;

      return `
        <div class="npc-card" data-map="${esc(mapName)}" data-id="${npc.object_id}"
             style="border-left-color:${borderColor}">
          <div class="npc-card-header">
            ${spriteHtml}
            <div class="npc-card-info">
              <div class="npc-card-name" data-action="open-detail"
                   data-map="${esc(mapName)}" data-id="${npc.object_id}">NPC ${npc.object_id}: ${esc(npc.display_name)}</div>
              <div class="npc-card-meta">${posText} · ${typeBadge}${trainerBadge}</div>
            </div>
            <button class="npc-card-menu" data-action="open-detail"
                    data-map="${esc(mapName)}" data-id="${npc.object_id}" title="Details">···</button>
          </div>
          ${dialogueArea}
          <div class="npc-card-footer">
            <button class="npc-card-save" data-action="save-dialogue"
                    data-npc-id="${npc.object_id}" style="display:none">Save</button>
            <span class="npc-card-status" data-status-for="${npc.object_id}"></span>
          </div>
        </div>
      `;
    }).join("");
    html += `</div>`;
  }

  if (bgEvents.length) {
    html += `<hr class="npc-section-divider">`;
    html += `<div class="npc-section-title">Background Events</div>`;
    html += `<ul class="npc-bg-list">`;
    html += bgEvents.map(ev => {
      const pos = `(${ev.x}, ${ev.y})`;
      const scriptLabel = ev.script || "";
      return `
        <li class="npc-bg-item">
          <span class="npc-bg-type">${esc(ev.type || "Sign")}</span>
          <span class="npc-bg-pos">@ ${pos}</span>
          <span class="npc-bg-script">${scriptLabel ? esc(scriptLabel) : ""}</span>
        </li>
      `;
    }).join("");
    html += `</ul>`;
  }

  main.innerHTML = html;

  // Open-detail: name link and ··· button both navigate to detail page
  main.querySelectorAll("[data-action='open-detail']").forEach(el => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      window.location.hash = `#/npcs/${el.dataset.map}/${el.dataset.id}`;
    });
  });

  // Inline dialogue editing
  wireInlineDialogue(main, mapName);

  wireAddButton(main, mapName, onRefresh);

  // Health indicators — async, non-blocking
  loadHealthIndicators(main, mapName);
}

let _previewTimers = {};

function wireInlineDialogue(main, mapName) {
  main.querySelectorAll(".npc-card-textarea").forEach(textarea => {
    const npcId = textarea.dataset.npcId;
    const saveBtn = main.querySelector(`.npc-card-save[data-npc-id="${npcId}"]`);
    const statusEl = main.querySelector(`.npc-card-status[data-status-for="${npcId}"]`);
    const previewEl = main.querySelector(`.npc-card-preview[data-preview-for="${npcId}"]`);
    const card = main.querySelector(`.npc-card[data-id="${npcId}"]`);

    function updateDirtyState() {
      const changed = textarea.value !== textarea.dataset.original;
      if (saveBtn) saveBtn.style.display = changed ? "" : "none";
      if (card) card.classList.toggle("dirty", changed);
    }

    textarea.addEventListener("input", () => {
      updateDirtyState();

      // Live GBA preview with debounce
      clearTimeout(_previewTimers[npcId]);
      _previewTimers[npcId] = setTimeout(() => {
        if (previewEl) {
          previewEl.innerHTML = renderGbaPreview(textarea.value);
        }
      }, 200);
    });

    textarea.addEventListener("focus", () => {
      if (previewEl) {
        previewEl.innerHTML = renderGbaPreview(textarea.value);
        previewEl.classList.add("visible");
      }
    });

    textarea.addEventListener("blur", () => {
      setTimeout(() => {
        if (previewEl) previewEl.classList.remove("visible");
      }, 300);
    });

    if (saveBtn) {
      saveBtn.addEventListener("click", async () => {
        saveBtn.disabled = true;
        if (statusEl) { statusEl.textContent = "Saving…"; statusEl.className = "npc-card-status"; }
        try {
          const res = await postApi(`/npcs/${encodeURIComponent(mapName)}/${npcId}/dialogue`, { text: textarea.value });
          if (res && res.ok) {
            textarea.dataset.original = textarea.value;
            saveBtn.style.display = "none";
            if (card) {
              card.classList.remove("dirty");
              card.classList.add("saved");
              setTimeout(() => card.classList.remove("saved"), 1500);
            }
            if (statusEl) {
              statusEl.textContent = "Saved";
              statusEl.className = "npc-card-status";
              setTimeout(() => { statusEl.textContent = ""; }, 2000);
            }
          } else {
            const msg = (res && res.error) ? res.error : "Save failed";
            if (statusEl) { statusEl.textContent = msg; statusEl.className = "npc-card-status error"; }
          }
        } catch (err) {
          if (statusEl) { statusEl.textContent = String(err); statusEl.className = "npc-card-status error"; }
        }
        saveBtn.disabled = false;
      });
    }
  });
}

function wireAddButton(main, mapName, onRefresh) {
  const addBtn = main.querySelector('[data-action="add-npc"]');
  if (!addBtn) return;
  addBtn.addEventListener("click", () => {
    openNpcWizard(mapName, () => {
      if (onRefresh) onRefresh();
    });
  });
}

async function loadHealthIndicators(main, mapName) {
  try {
    const healthRes = await api(`/npcs/${encodeURIComponent(mapName)}/health`);
    if (!healthRes?.ok || !healthRes.data?.issues) return;
    for (const issue of healthRes.data.issues) {
      const card = main.querySelector(`.npc-card[data-id="${issue.object_id}"]`);
      if (!card) continue;
      const badgesEl = card.querySelector(".npc-card-badges");
      if (!badgesEl) continue;
      const badge = document.createElement("span");
      badge.className = issue.issue === "missing" ? "npc-health-error" : "npc-health-warn";
      badge.title = issue.description || issue.issue;
      badge.textContent = issue.issue === "missing" ? "!" : "?";
      badgesEl.appendChild(badge);
    }
  } catch (_) { /* health check is best-effort */ }
}

// ---------------------------------------------------------------------------
// Map Browser (landing)
// ---------------------------------------------------------------------------

async function renderMapBrowser(container) {
  container.innerHTML = `<article>
    ${renderStudioNavbar("NPCs")}
    <div class="npc-skeleton">
      <div class="npc-skeleton-card"></div>
      <div class="npc-skeleton-card"></div>
      <div class="npc-skeleton-card"></div>
    </div>
  </article>`;

  const res = await api("/npcs");
  if (!res.ok) {
    container.innerHTML = `<article>
      ${renderStudioNavbar("NPCs")}
      <div class="npc-empty">Error: ${esc(res.error)}</div>
    </article>`;
    return;
  }

  const maps = res.data.maps || [];
  cachedMaps = maps;

  if (!maps.length) {
    container.innerHTML = `<article>
      ${renderStudioNavbar("NPCs")}
      <div class="npc-empty">No maps with NPCs found. Enroll maps with <code>torch enroll</code> first.</div>
    </article>`;
    return;
  }

  // Compute totals for stats
  const totalNpcs = maps.reduce((s, m) => s + m.npc_count, 0);
  const totalTrainers = maps.reduce((s, m) => s + m.trainer_count, 0);
  const totalNurses = maps.filter(m => m.has_nurse).length;

  container.innerHTML = `<article>
    ${renderStudioNavbar("NPCs")}
    <div class="npc-stats">
      <div class="npc-stat"><div class="npc-stat-value">${maps.length}</div><div class="npc-stat-label">Maps</div></div>
      <div class="npc-stat"><div class="npc-stat-value">${totalNpcs}</div><div class="npc-stat-label">NPCs</div></div>
      <div class="npc-stat"><div class="npc-stat-value">${totalTrainers}</div><div class="npc-stat-label">Trainers</div></div>
      <div class="npc-stat"><div class="npc-stat-value">${totalNurses}</div><div class="npc-stat-label">Nurses</div></div>
    </div>
    <div class="npc-layout">
      <aside class="npc-sidebar">
        <input type="text" class="npc-search" placeholder="Search maps...">
        <ul class="npc-map-list"></ul>
      </aside>
      <div class="npc-main">
        <div class="npc-empty">Select a map to view its NPCs</div>
      </div>
    </div>
  </article>`;

  renderMapList(container, maps, null);

  const searchInput = container.querySelector(".npc-search");
  if (searchInput) searchInput.focus();

  container.querySelector(".npc-search").addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      renderMapList(container, maps, null);
    }, 200);
  });
}

// ---------------------------------------------------------------------------
// Map NPC Detail
// ---------------------------------------------------------------------------

async function renderMapNpcs(container, mapName) {
  if (!cachedMaps) {
    const listRes = await api("/npcs");
    if (listRes.ok) cachedMaps = listRes.data.maps || [];
  }

  container.innerHTML = `<article>
    ${renderStudioNavbar("NPCs")}
    <div class="npc-skeleton">
      <div class="npc-skeleton-card"></div>
      <div class="npc-skeleton-card"></div>
      <div class="npc-skeleton-card"></div>
    </div>
  </article>`;

  const detailRes = await api(`/npcs/${encodeURIComponent(mapName)}`);
  if (!detailRes.ok) {
    container.innerHTML = `<article>
      ${renderStudioNavbar("NPCs")}
      <div class="npc-empty">Error: ${esc(detailRes.error)}</div>
    </article>`;
    return;
  }

  const npcs = detailRes.data.npcs || [];
  const bgEvents = detailRes.data.bg_events || [];

  container.innerHTML = `<article>
    ${renderStudioNavbar("NPCs")}
    <div class="npc-layout">
      <aside class="npc-sidebar">
        <input type="text" class="npc-search" placeholder="Search maps...">
        <ul class="npc-map-list"></ul>
      </aside>
      <div class="npc-main"></div>
    </div>
  </article>`;

  if (cachedMaps) {
    renderMapList(container, cachedMaps, mapName);
    container.querySelector(".npc-search").addEventListener("input", () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        renderMapList(container, cachedMaps, mapName);
      }, 200);
    });
  }

  renderNpcCards(container, npcs, bgEvents, mapName, () => renderMapNpcs(container, mapName));
}

// ---------------------------------------------------------------------------
// Main render + cleanup
// ---------------------------------------------------------------------------

export async function render(container) {
  injectCSS();

  const hash = window.location.hash || "";
  // Match #/npcs/MapName/123 (detail view)
  const detailMatch = hash.match(/^#\/npcs\/([A-Za-z0-9_]+)\/(\d+)$/);
  // Match #/npcs/MapName (card grid)
  const mapMatch = hash.match(/^#\/npcs\/([A-Za-z0-9_]+)$/);

  if (detailMatch) {
    await renderNpcDetail(container, detailMatch[1], detailMatch[2]);
  } else if (mapMatch) {
    await renderMapNpcs(container, mapMatch[1]);
  } else {
    await renderMapBrowser(container);
  }
}

export function cleanup() {
  clearTimeout(debounceTimer);
  debounceTimer = null;
  cachedMaps = null;
  for (const t of Object.values(_previewTimers)) clearTimeout(t);
  _previewTimers = {};
  cleanupNpcDetail();
  if (styleEl) {
    styleEl.remove();
    styleEl = null;
  }
}
