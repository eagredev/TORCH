/**
 * TORCH Web GUI — NPC Detail Panel.
 * TORCH_MODULE
 * Property editor, dialogue editor with GBA preview, script info, cast index.
 */

import { api, postApi, deleteApi } from "../app.js";
import { esc, createModal } from "../utils.js";
import { renderStudioNavbar } from "../studioNav.js";

let styleEl = null;
let cachedConstants = null;
let livePreviewTimer = null;

// ---------------------------------------------------------------------------
// Badge color map — mirrors npcs.js type badges
// ---------------------------------------------------------------------------
const TYPE_COLORS = {
  flavor:    { bg: "var(--bg-tertiary, #45475a)", color: "var(--text-muted, #6c7086)" },
  sign:      { bg: "rgba(137,180,250,0.15)", color: "#89b4fa" },
  item_giver:{ bg: "rgba(249,226,175,0.15)", color: "#f9e2af" },
  nurse:     { bg: "rgba(245,194,231,0.15)", color: "#f5c2e7" },
  pc:        { bg: "rgba(148,226,213,0.15)", color: "#94e2d5" },
  complex:   { bg: "rgba(203,166,247,0.15)", color: "#cba6f7" },
  workspace: { bg: "rgba(166,227,161,0.15)", color: "#a6e3a1" },
  inc:       { bg: "rgba(203,166,247,0.15)", color: "#cba6f7" },
  shared:    { bg: "var(--bg-tertiary, #45475a)", color: "var(--text-muted, #6c7086)" },
  unknown:   { bg: "var(--bg-tertiary, #45475a)", color: "var(--text-muted, #6c7086)" },
  none:      { bg: "var(--bg-tertiary, #45475a)", color: "var(--text-muted, #6c7086)" },
};

// ---------------------------------------------------------------------------
// CSS — all classes prefixed npcd- to avoid collisions with npcs.js npc-
// ---------------------------------------------------------------------------
const STYLES = `
.npcd-header {
  display: flex; align-items: center; gap: 0.75rem; padding: 0.75rem 1rem;
  background: var(--bg-secondary, #1e1e2e); border-bottom: 1px solid var(--border, #313244);
}
.npcd-header-title { flex: 1; font-size: 1rem; font-weight: 600; color: var(--text-primary, #cdd6f4); }
.npcd-back-btn, .npcd-delete-btn {
  padding: 0.35rem 0.75rem; border: none; border-radius: 6px; cursor: pointer;
  font-size: 0.8rem; font-weight: 600;
}
.npcd-back-btn {
  background: var(--bg-tertiary, #45475a); color: var(--text-primary, #cdd6f4);
}
.npcd-back-btn:hover { background: var(--border, #313244); }
.npcd-delete-btn { background: rgba(243,139,168,0.15); color: #f38ba8; }
.npcd-delete-btn:hover { background: rgba(243,139,168,0.3); }

/* Hero block — sprite + name + meta */
.npcd-hero {
  display: flex; align-items: center; gap: 1rem;
  padding: 1rem 0 0.75rem;
}
.npcd-hero-sprite {
  height: 64px; width: auto; image-rendering: pixelated; flex-shrink: 0;
}
.npcd-hero-placeholder {
  height: 64px; width: 48px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: var(--bg-tertiary, #45475a); border-radius: 6px;
  color: var(--text-muted, #6c7086); font-size: 1.5rem;
}
.npcd-hero-info { display: flex; flex-direction: column; gap: 0.3rem; }
.npcd-hero-name { font-size: 1.15rem; font-weight: 700; color: var(--text-primary, #cdd6f4); }
.npcd-hero-meta { font-size: 0.8rem; color: var(--text-muted, #6c7086); display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }

/* Single-column body */
.npcd-body {
  max-width: 720px; margin: 0 auto; padding: 0 1rem 2rem;
}

/* Section chrome */
.npcd-section {
  background: var(--bg-secondary, #1e1e2e); border: 1px solid var(--border, #313244);
  border-radius: 8px; padding: 0.75rem 1rem; margin-bottom: 0.85rem;
}
.npcd-section-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 0;
}
.npcd-section-header.has-content { margin-bottom: 0.6rem; }
.npcd-section-title {
  color: var(--text-muted, #6c7086); font-size: 0.75rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.05em;
}
.npcd-toggle-btn {
  padding: 0.2rem 0.55rem; border: 1px solid var(--border, #313244); border-radius: 5px;
  background: var(--bg-tertiary, #45475a); color: var(--text-secondary, #bac2de);
  font-size: 0.72rem; font-weight: 600; cursor: pointer;
}
.npcd-toggle-btn:hover { border-color: var(--accent, #89b4fa); color: var(--accent, #89b4fa); }
.npcd-section-divider {
  border: none; border-top: 1px solid var(--border, #313244); margin: 0.5rem 0 0.6rem;
}
.npcd-section-content { margin-top: 0.2rem; }

/* Old panel title — kept for inner panel titles */
.npcd-panel-title {
  color: var(--text-muted, #6c7086); font-size: 0.75rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.6rem;
  border-bottom: 1px solid var(--border, #313244); padding-bottom: 0.4rem;
}

/* Form fields */
.npcd-field {
  display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem;
}
.npcd-field-label {
  width: 90px; flex-shrink: 0; font-size: 0.8rem; color: var(--text-secondary, #bac2de);
  text-align: right;
}
.npcd-field-pair { display: flex; gap: 0.4rem; align-items: center; }
.npcd-pair-label { font-size: 0.7rem; color: var(--text-muted, #6c7086); }
.npcd-input, .npcd-select {
  background: var(--bg-tertiary, #45475a); color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border, #313244); border-radius: 4px;
  padding: 0.3rem 0.5rem; font-size: 0.8rem; font-family: inherit;
}
.npcd-input:focus, .npcd-select:focus {
  outline: none; border-color: var(--accent, #89b4fa);
}
.npcd-input-num { width: 60px; }
.npcd-input-text { width: 180px; }
.npcd-select { min-width: 180px; max-width: 240px; }

.npcd-save-btn, .npcd-save-dlg-btn {
  margin-top: 0.5rem; padding: 0.4rem 1rem; border: none; border-radius: 6px;
  font-size: 0.8rem; font-weight: 600; cursor: pointer;
  background: rgba(166,227,161,0.15); color: #a6e3a1;
}
.npcd-save-btn:hover, .npcd-save-dlg-btn:hover {
  background: rgba(166,227,161,0.3);
}
.npcd-save-btn:disabled, .npcd-save-dlg-btn:disabled {
  opacity: 0.5; cursor: default;
}
.npcd-status {
  display: inline-block; margin-left: 0.75rem; font-size: 0.8rem;
}
.npcd-status-ok { color: #a6e3a1; }
.npcd-status-err { color: #f38ba8; }
.npcd-decompile-row {
  margin-top: 0.5rem; display: flex; align-items: center; gap: 0.5rem;
}
.npcd-decompile-btn {
  padding: 0.4rem 1rem; border: none; border-radius: 6px;
  font-size: 0.8rem; font-weight: 600; cursor: pointer;
  background: var(--accent, #89b4fa); color: var(--bg-primary, #1e1e2e);
}
.npcd-decompile-btn:hover { opacity: 0.85; }
.npcd-decompile-btn:disabled { opacity: 0.5; cursor: default; }

/* Properties read-only summary */
.npcd-props-summary { margin-top: 0.2rem; }
.npcd-prop-row {
  display: flex; gap: 0.5rem; margin-bottom: 0.3rem; font-size: 0.8rem;
}
.npcd-prop-key {
  width: 80px; flex-shrink: 0; color: var(--text-muted, #6c7086); text-align: right;
}
.npcd-prop-val { color: var(--text-primary, #cdd6f4); }
.npcd-props-form { margin-top: 0.2rem; }

/* Script info */
.npcd-info-row {
  display: flex; gap: 0.5rem; margin-bottom: 0.35rem; font-size: 0.8rem;
}
.npcd-info-key {
  width: 70px; flex-shrink: 0; color: var(--text-muted, #6c7086); text-align: right;
}
.npcd-info-val { color: var(--text-primary, #cdd6f4); word-break: break-all; }
.npcd-type-badge {
  display: inline-block; font-size: 0.65rem; padding: 0.1rem 0.45rem;
  border-radius: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;
}
.npcd-managed-note {
  margin-top: 0.35rem; font-size: 0.75rem; color: #a6e3a1;
}
.npcd-managed-note a { color: #a6e3a1; text-decoration: underline; }

/* Dialogue */
.npcd-textarea {
  width: 30ch; max-width: 100%; min-height: 80px; resize: vertical;
  background: var(--bg-tertiary, #45475a); color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border, #313244); border-radius: 6px;
  padding: 0.5rem 0.65rem; font-size: 0.8rem; font-family: "Courier New", monospace;
  line-height: 1.4;
}
.npcd-textarea:focus { outline: none; border-color: var(--accent, #89b4fa); }
.npcd-readonly-text {
  background: var(--bg-tertiary, #45475a); border: 1px solid var(--border, #313244);
  border-radius: 6px; padding: 0.5rem 0.65rem; font-size: 0.8rem;
  color: var(--text-secondary, #bac2de); white-space: pre-wrap; line-height: 1.4;
  width: 30ch; max-width: 100%; font-family: "Courier New", monospace;
}
.npcd-edit-hint {
  font-size: 0.75rem; color: var(--text-muted, #6c7086); margin-top: 0.35rem;
}
.npcd-edit-hint a { color: var(--accent, #89b4fa); text-decoration: underline; }
.npcd-extra-logic-note {
  font-size: 0.75rem; color: var(--text-muted, #6c7086);
  font-style: italic; margin-top: 0.35rem;
}

.npcd-msgbox-row {
  display: flex; align-items: center; gap: 0.5rem; margin-top: 0.5rem;
}
.npcd-msgbox-label { font-size: 0.75rem; color: var(--text-muted, #6c7086); }

/* GBA Preview — pages side by side */
.npcd-gba-preview-wrap {
  display: flex; flex-direction: row; flex-wrap: wrap; gap: 0.75rem; margin-top: 0.5rem;
}
.npcd-gba-page {
  font-family: "Courier New", monospace;
  font-size: 0.8rem; line-height: 1.4;
  background: var(--bg-primary, #11111b);
  border: 2px solid var(--border, #313244);
  border-radius: 6px;
  padding: 0.5rem 0.65rem;
  color: var(--text-primary, #cdd6f4);
  width: 30ch; max-width: 100%; white-space: pre-wrap; word-break: break-all;
}

/* Referenced by */
.npcd-ref-item {
  margin-bottom: 0.5rem; font-size: 0.8rem;
}
.npcd-ref-file { color: var(--text-primary, #cdd6f4); font-weight: 600; }
.npcd-ref-alias { color: var(--text-muted, #6c7086); }
.npcd-ref-link {
  display: block; font-size: 0.75rem; color: var(--accent, #89b4fa);
  text-decoration: none; margin-top: 0.15rem;
}
.npcd-ref-link:hover { text-decoration: underline; }
.npcd-ref-empty { color: var(--text-muted, #6c7086); font-size: 0.8rem; font-style: italic; }

/* Delete modal */
.npcd-modal-backdrop {
  position: fixed; inset: 0; z-index: 999;
  background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center;
}
.npcd-modal {
  background: var(--bg-secondary, #1e1e2e); border: 1px solid var(--border, #313244);
  border-radius: 10px; padding: 1.5rem; max-width: 400px; width: 90%;
}
.npcd-modal h3 { margin: 0 0 0.75rem; color: var(--text-primary, #cdd6f4); font-size: 1rem; }
.npcd-modal p { margin: 0 0 0.5rem; font-size: 0.85rem; color: var(--text-secondary, #bac2de); }
.npcd-modal-warn { color: #f9e2af; font-size: 0.8rem; margin-bottom: 0.75rem; }
.npcd-modal-actions { display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1rem; }
.npcd-modal-cancel {
  padding: 0.35rem 0.75rem; background: var(--bg-tertiary, #45475a);
  color: var(--text-primary, #cdd6f4); border: none; border-radius: 6px; cursor: pointer;
  font-size: 0.8rem;
}
.npcd-modal-confirm {
  padding: 0.35rem 0.75rem; background: rgba(243,139,168,0.2);
  color: #f38ba8; border: none; border-radius: 6px; cursor: pointer;
  font-size: 0.8rem; font-weight: 600;
}

/* Loading */
.npcd-loading {
  text-align: center; padding: 3rem; color: var(--text-muted, #6c7086); font-size: 0.9rem;
}
.npcd-error {
  text-align: center; padding: 2rem; color: #f38ba8; font-size: 0.9rem;
}
`;

function injectCSS() {
  if (styleEl) return;
  styleEl = document.createElement("style");
  styleEl.textContent = STYLES;
  document.head.appendChild(styleEl);
}

// ---------------------------------------------------------------------------
// GBA text preview
// ---------------------------------------------------------------------------
function wrapGbaText(text, lineWidth = 31) {
  if (!text) return [[""]];
  // Split on \p (page break) — handle both literal \p and actual \p in the string
  const pages = text.split(/\\p/);
  return pages.map(page => {
    // Also handle \n (newline within page) as a forced line break
    const segments = page.split(/\\n/);
    const lines = [];
    for (const seg of segments) {
      const words = seg.split(" ");
      let currentLine = "";
      for (const word of words) {
        if (!word) continue;
        if (currentLine.length > 0 && currentLine.length + 1 + word.length > lineWidth) {
          lines.push(currentLine);
          currentLine = word;
        } else {
          currentLine = currentLine ? currentLine + " " + word : word;
        }
      }
      if (currentLine || lines.length === 0) lines.push(currentLine);
    }
    return lines;
  });
}

function renderGbaPreview(text) {
  const pages = wrapGbaText(text);
  return pages.map(lines =>
    `<div class="npcd-gba-page">${esc(lines.join("\n"))}</div>`
  ).join("");
}

// ---------------------------------------------------------------------------
// Build select options
// ---------------------------------------------------------------------------
function buildOptions(list, currentValue) {
  return list.map(item => {
    const val = item.const || item;
    const label = item.label || item.const || item;
    const sel = val === currentValue ? " selected" : "";
    return `<option value="${esc(val)}"${sel}>${esc(label)}</option>`;
  }).join("");
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

/**
 * Render the full NPC detail view.
 * @param {HTMLElement} container - The #app element
 * @param {string} mapName - Map name from route
 * @param {number|string} npcId - NPC object_id from route
 */
export async function renderNpcDetail(container, mapName, npcId) {
  injectCSS();

  container.innerHTML = renderStudioNavbar("NPCs") +
    `<div class="npcd-loading">Loading NPC detail\u2026</div>`;

  // Fetch NPC detail + constants in parallel
  const [detailRes, constRes] = await Promise.all([
    api(`/npcs/${encodeURIComponent(mapName)}/${encodeURIComponent(npcId)}`),
    cachedConstants ? Promise.resolve({ ok: true, data: cachedConstants }) : api("/npcs/constants"),
  ]);

  if (!detailRes || !detailRes.ok) {
    container.innerHTML = renderStudioNavbar("NPCs") +
      `<div class="npcd-error">Failed to load NPC: ${esc(detailRes?.error || "Unknown error")}</div>`;
    return;
  }

  const npc = detailRes.data?.npc || detailRes.data;
  if (constRes && constRes.ok && constRes.data) {
    cachedConstants = constRes.data;
  }
  const constants = cachedConstants || { movement_types: [], graphics_ids: [], trainer_types: [] };

  // Display name
  const displayName = npc.display_name || npc.graphics_id || `NPC ${npcId}`;

  // Type badge
  const st = npc.script_type || "unknown";
  const tc = TYPE_COLORS[st] || TYPE_COLORS.flavor;
  const badgeStyle = `background:${tc.bg};color:${tc.color}`;

  // Build HTML
  container.innerHTML = renderStudioNavbar("NPCs") + `
    <div class="npcd-header">
      <span class="npcd-header-title">
        <a href="#/npcs/${esc(mapName)}" style="color:var(--text-muted);text-decoration:none">
          ${esc(mapName)}</a> &rsaquo; NPC ${esc(String(npcId))}: ${esc(displayName)}
      </span>
      <button class="npcd-back-btn" data-action="back">\u2190 Back</button>
      <button class="npcd-delete-btn" data-action="delete">Delete</button>
    </div>
    <div class="npcd-body">
      ${renderHero(npc, npcId, displayName, badgeStyle, st)}
      ${renderDialogueSection(npc)}
      ${renderPropertiesSection(npc, constants)}
      ${renderScriptInfoSection(npc, badgeStyle, st)}
      ${renderReferencedBySection(npc)}
    </div>
  `;

  // Wire events
  wireBackButton(container, mapName);
  wireDeleteButton(container, mapName, npcId, npc);
  wirePropertiesSave(container, mapName, npcId);
  wireDialogue(container, mapName, npcId, npc);
  wireDecompile(container, mapName, npcId);
  wireCollapsibles(container);
}

export function cleanupNpcDetail() {
  if (styleEl) { styleEl.remove(); styleEl = null; }
  if (livePreviewTimer) { clearTimeout(livePreviewTimer); livePreviewTimer = null; }
}

export { wrapGbaText, renderGbaPreview };


/**
 * Render a streamlined NPC detail view for the IDE modal.
 * No navbar, no back button, compact layout, themed GBA preview.
 */
export async function renderNpcDetailModal(container, mapName, npcId) {
  injectCSS();
  _injectModalCSS();

  container.innerHTML = `<div class="npcd-loading">Loading\u2026</div>`;

  const [detailRes, constRes] = await Promise.all([
    api(`/npcs/${encodeURIComponent(mapName)}/${encodeURIComponent(npcId)}`),
    cachedConstants ? Promise.resolve({ ok: true, data: cachedConstants }) : api("/npcs/constants"),
  ]);

  if (!detailRes || !detailRes.ok) {
    container.innerHTML = `<div class="npcd-error">Failed to load NPC: ${esc(detailRes?.error || "Unknown error")}</div>`;
    return;
  }

  const npc = detailRes.data?.npc || detailRes.data;
  if (constRes?.ok?.data || constRes?.data) {
    cachedConstants = constRes.data;
  }
  const constants = cachedConstants || { movement_types: [], graphics_ids: [], trainer_types: [] };

  const displayName = npc.display_name || npc.graphics_id || `NPC ${npcId}`;
  const st = npc.script_type || "unknown";
  const tc = TYPE_COLORS[st] || TYPE_COLORS.flavor;
  const badgeStyle = `background:${tc.bg};color:${tc.color}`;
  const gfxId = npc.graphics_id || "";
  const gfxLabel = _humanizeConst(gfxId, "OBJ_EVENT_GFX_");
  const moveLabel = _humanizeConst(npc.movement_type || "", "MOVEMENT_TYPE_");

  // Dialogue + GBA preview
  const text = npc.dialogue_readable || npc.dialogue || "";
  const hasDialogue = !!text;
  const isEditable = !!npc.is_editable;

  let dialogueHtml = "";
  if (isEditable) {
    const msgboxType = npc.msgbox_type || "MSGBOX_NPC";
    const msgboxOptions = ["MSGBOX_NPC", "MSGBOX_SIGN", "MSGBOX_DEFAULT", "MSGBOX_YESNO"];
    dialogueHtml = `
      <textarea class="npcm-textarea" data-field="dialogue" placeholder="Enter dialogue\u2026">${esc(text)}</textarea>
      ${npc.has_extra_logic ? `<div class="npcm-hint">Script has additional logic beyond this line.</div>` : ""}
      <div class="npcm-dlg-controls">
        <select class="npcm-select" data-field="msgbox_type">
          ${msgboxOptions.map(m => `<option value="${esc(m)}"${m === msgboxType ? " selected" : ""}>${esc(m)}</option>`).join("")}
        </select>
        <button class="npcm-save-btn" data-action="save-dialogue">Save</button>
        <span class="npcd-status" data-status="dialogue"></span>
      </div>`;
  } else if (hasDialogue) {
    dialogueHtml = `<div class="npcm-readonly-text">${esc(text)}</div>`;
  } else {
    dialogueHtml = `<div class="npcm-hint">No dialogue</div>`;
  }

  // GBA preview with separate text boxes per page
  const gbaHtml = hasDialogue ? _renderGbaPages(text) : "";

  container.innerHTML = `
    <div class="npcm-root">
      <div class="npcm-hero">
        <img class="npcm-sprite" src="/api/assets/overworld-frame/${esc(gfxId)}" alt=""
             onerror="this.style.display='none'">
        <div class="npcm-hero-info">
          <div class="npcm-name">${esc(displayName)}</div>
          <div class="npcm-meta">
            <span class="npcd-type-badge" style="${badgeStyle}">${esc(st)}</span>
            <span>${esc(gfxLabel)}</span>
            <span>(${npc.x}, ${npc.y})</span>
          </div>
        </div>
      </div>

      <div class="npcm-columns">
        <div class="npcm-col-main">
          <div class="npcm-section">
            <div class="npcm-section-title">Dialogue</div>
            ${dialogueHtml}
          </div>
          ${gbaHtml ? `<div class="npcm-section">
            <div class="npcm-section-title">GBA Preview</div>
            <div class="npcm-gba-wrap" data-preview="gba">${gbaHtml}</div>
          </div>` : ""}
        </div>
        <div class="npcm-col-side">
          <div class="npcm-section">
            <div class="npcm-section-title">Properties</div>
            <div class="npcm-props">
              ${_modalPropRow("Graphics", gfxLabel)}
              ${_modalPropRow("Movement", moveLabel)}
              ${_modalPropRow("Elevation", npc.elevation || 0)}
              ${_modalPropRow("Range", `${npc.movement_range_x || 0} \u00d7 ${npc.movement_range_y || 0}`)}
              ${_modalPropRow("Flag", npc.flag || "0")}
              ${npc.trainer_type && npc.trainer_type !== "TRAINER_TYPE_NONE"
                ? _modalPropRow("Trainer", _humanizeConst(npc.trainer_type, "TRAINER_TYPE_")) : ""}
            </div>
          </div>
          <div class="npcm-section">
            <div class="npcm-section-title">Script</div>
            <div class="npcm-props">
              ${_modalPropRow("Label", npc.script || "none")}
              ${_modalPropRow("Source", npc.script_source || "—")}
            </div>
          </div>
        </div>
      </div>
    </div>`;

  // Wire dialogue save + live preview
  wireDialogue(container, mapName, npcId, npc);
  wireDecompile(container, mapName, npcId);
}

function _humanizeConst(name, prefix) {
  if (!name) return "None";
  let s = name;
  if (prefix && s.startsWith(prefix)) s = s.slice(prefix.length);
  return s.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

function _modalPropRow(label, value) {
  return `<div class="npcm-prop-row">
    <span class="npcm-prop-key">${esc(label)}</span>
    <span class="npcm-prop-val">${esc(String(value))}</span>
  </div>`;
}

function _renderGbaPages(text) {
  // Split on \p (literal backslash-p) or double newline (readable format)
  const rawPages = text.split(/\\p|\n\n/);
  return rawPages.map(page => {
    if (!page.trim()) return "";
    // Word-wrap each page to ~30 chars (GBA line width)
    const lines = [];
    for (const seg of page.split(/\\n|\n/)) {
      const words = seg.split(" ");
      let cur = "";
      for (const w of words) {
        if (!w) continue;
        if (cur.length > 0 && cur.length + 1 + w.length > 30) {
          lines.push(cur);
          cur = w;
        } else {
          cur = cur ? cur + " " + w : w;
        }
      }
      if (cur || lines.length === 0) lines.push(cur);
    }
    return `<div class="npcm-gba-box"><div class="npcm-gba-text">${esc(lines.join("\n"))}</div></div>`;
  }).filter(Boolean).join("");
}

let _modalStyleEl = null;
function _injectModalCSS() {
  if (_modalStyleEl) return;
  _modalStyleEl = document.createElement("style");
  _modalStyleEl.textContent = `
.npcm-root { padding: 0; font-size: 0.85rem; }
.npcm-hero {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.6rem 0.8rem;
  border-bottom: 1px solid var(--border-subtle, #2a2a2a);
  background: var(--surface-1, #1a1a1a);
}
.npcm-sprite { height: 48px; image-rendering: pixelated; flex-shrink: 0; }
.npcm-hero-info { display: flex; flex-direction: column; gap: 0.15rem; }
.npcm-name { font-size: 1rem; font-weight: 700; color: var(--text-primary, #fff); }
.npcm-meta {
  font-size: 0.75rem; color: var(--text-dim, #888);
  display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;
}
.npcm-columns {
  display: flex; gap: 0; min-height: 0;
}
.npcm-col-main {
  flex: 1; padding: 0.6rem 0.8rem; overflow-y: auto;
  border-right: 1px solid var(--border-subtle, #2a2a2a);
}
.npcm-col-side {
  width: 260px; flex-shrink: 0; padding: 0.6rem 0.8rem; overflow-y: auto;
}
.npcm-section { margin-bottom: 0.85rem; }
.npcm-section-title {
  font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.05em; color: var(--accent, #d4a017);
  margin-bottom: 0.35rem;
}
.npcm-textarea {
  width: 30ch; max-width: 100%; min-height: 120px; resize: vertical;
  background: var(--surface-1, #1a1a1a); color: var(--text-primary, #fff);
  border: 1px solid var(--border-subtle, #2a2a2a); border-radius: 6px;
  padding: 0.5rem 0.65rem; font-size: 0.8rem; font-family: "Courier New", monospace;
  line-height: 1.4;
}
.npcm-textarea:focus { outline: none; border-color: var(--accent, #d4a017); }
.npcm-readonly-text {
  background: var(--surface-1, #1a1a1a); border: 1px solid var(--border-subtle, #2a2a2a);
  border-radius: 6px; padding: 0.5rem 0.65rem; font-size: 0.8rem;
  color: var(--text-secondary, #ccc); white-space: pre-wrap; line-height: 1.4;
  width: 30ch; max-width: 100%; font-family: "Courier New", monospace;
}
.npcm-hint { font-size: 0.75rem; color: var(--text-dim, #888); font-style: italic; margin-top: 0.2rem; }
.npcm-dlg-controls {
  display: flex; align-items: center; gap: 0.4rem; margin-top: 0.4rem; flex-wrap: wrap;
}
.npcm-select {
  background: var(--surface-1, #1a1a1a); color: var(--text-primary, #fff);
  border: 1px solid var(--border-subtle, #2a2a2a); border-radius: 6px;
  padding: 0.25rem 0.4rem; font-size: 0.72rem; max-width: 180px;
}
.npcm-save-btn {
  padding: 0.25rem 0.6rem; border: none; border-radius: 6px;
  background: var(--accent, #d4a017); color: #111;
  font-size: 0.75rem; font-weight: 600; cursor: pointer;
}
.npcm-save-btn:hover { filter: brightness(1.1); }

/* Properties */
.npcm-props { display: flex; flex-direction: column; gap: 0.2rem; }
.npcm-prop-row { display: flex; gap: 0.4rem; font-size: 0.78rem; }
.npcm-prop-key {
  width: 70px; flex-shrink: 0; color: var(--text-dim, #888);
  text-align: right; font-size: 0.72rem;
}
.npcm-prop-val { color: var(--text-primary, #fff); word-break: break-word; }

/* GBA Preview — separate textbox per \p page, GBA-authentic dark style */
.npcm-gba-wrap { display: flex; flex-direction: column; gap: 0.5rem; }
.npcm-gba-box {
  background: #1a1f2e;
  border: 2px solid #4a5570;
  border-radius: 6px;
  padding: 0.5rem 0.65rem;
  width: 30ch;
  max-width: 100%;
  box-shadow: inset 0 1px 4px rgba(0,0,0,0.3), 0 1px 3px rgba(0,0,0,0.2);
}
.npcm-gba-text {
  font-family: "Courier New", monospace;
  font-size: 0.78rem; line-height: 1.5;
  color: #e0e4f0; white-space: pre-wrap;
  text-shadow: 1px 1px 0 rgba(0,0,0,0.5);
}
@media (max-width: 600px) {
  .npcm-columns { flex-direction: column; }
  .npcm-col-main { border-right: none; border-bottom: 1px solid var(--border-subtle, #2a2a2a); }
  .npcm-col-side { width: auto; }
}
`;
  document.head.appendChild(_modalStyleEl);
}

// ---------------------------------------------------------------------------
// Section renderers
// ---------------------------------------------------------------------------

function renderHero(npc, npcId, displayName, badgeStyle, scriptType) {
  const gfxId = npc.graphics_id || "";
  return `
    <div class="npcd-hero">
      <img class="npcd-hero-sprite"
           src="/api/assets/overworld-frame/${esc(gfxId)}"
           alt=""
           style="image-rendering:pixelated"
           onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
      <div class="npcd-hero-placeholder" style="display:none">?</div>
      <div class="npcd-hero-info">
        <div class="npcd-hero-name">NPC ${esc(String(npcId))}: ${esc(displayName)}</div>
        <div class="npcd-hero-meta">
          ${esc(gfxId)}
          &middot; (${esc(String(Number(npc.x) || 0))}, ${esc(String(Number(npc.y) || 0))})
          &middot; <span class="npcd-type-badge" style="${badgeStyle}">${esc(scriptType)}</span>
        </div>
      </div>
    </div>`;
}

function renderDialogueSection(npc) {
  if (!npc.is_editable && !npc.can_decompile) {
    return renderReadOnlyDialogueSection(npc);
  }
  // Not yet in workspace — show decompile button (auto-re-renders after convert)
  if (npc.can_decompile) {
    return renderDecompileSection(npc);
  }

  const text = npc.dialogue_readable || npc.dialogue || "";
  const msgboxType = npc.msgbox_type || "MSGBOX_NPC";
  const msgboxOptions = ["MSGBOX_NPC", "MSGBOX_SIGN", "MSGBOX_DEFAULT", "MSGBOX_YESNO"];
  const extraLogicNote = npc.has_extra_logic
    ? `<div class="npcd-extra-logic-note">This script has additional logic beyond this dialogue line.</div>`
    : "";

  return `<div class="npcd-section">
    <div class="npcd-section-header has-content">
      <span class="npcd-section-title">Dialogue</span>
    </div>
    <textarea class="npcd-textarea" data-field="dialogue" placeholder="Enter dialogue text\u2026">${esc(text)}</textarea>
    ${extraLogicNote}
    <div class="npcd-msgbox-row">
      <span class="npcd-msgbox-label">Msgbox:</span>
      <select class="npcd-select" data-field="msgbox_type" style="min-width:150px">
        ${msgboxOptions.map(m => `<option value="${esc(m)}"${m === msgboxType ? " selected" : ""}>${esc(m)}</option>`).join("")}
      </select>
      <button class="npcd-save-dlg-btn" data-action="save-dialogue" style="margin-top:0">Save Dialogue</button>
      <span class="npcd-status" data-status="dialogue"></span>
    </div>
    <div class="npcd-panel-title" style="margin-top:0.75rem">GBA Preview</div>
    <div class="npcd-gba-preview-wrap" data-preview="gba">
      ${renderGbaPreview(text)}
    </div>
  </div>`;
}

function renderReadOnlyDialogueSection(npc) {
  const text = npc.dialogue_readable || npc.dialogue || "";
  const st = npc.script_type || "";
  let hint = "";

  if (st === "complex" || st === "workspace") {
    hint = `<div class="npcd-edit-hint">This script is too complex for inline editing.
      <a href="#/scripts">Edit in Script Editor \u2192</a></div>`;
  } else if (st === "nurse" || st === "pc") {
    hint = `<div class="npcd-edit-hint">Uses shared common script.</div>`;
  } else {
    hint = `<div class="npcd-edit-hint">This script is not editable inline.</div>`;
  }

  const previewHtml = text
    ? `<div class="npcd-panel-title" style="margin-top:0.75rem">GBA Preview</div>
       <div class="npcd-gba-preview-wrap">${renderGbaPreview(text)}</div>`
    : "";

  return `<div class="npcd-section">
    <div class="npcd-section-header has-content">
      <span class="npcd-section-title">Dialogue</span>
    </div>
    ${text ? `<div class="npcd-readonly-text">${esc(text)}</div>` : `<div class="npcd-ref-empty">No dialogue</div>`}
    ${hint}
    ${previewHtml}
  </div>`;
}

function renderDecompileSection(npc) {
  const text = npc.dialogue_readable || npc.dialogue || "";
  const previewHtml = text
    ? `<div class="npcd-panel-title" style="margin-top:0.75rem">GBA Preview</div>
       <div class="npcd-gba-preview-wrap">${renderGbaPreview(text)}</div>`
    : "";

  return `<div class="npcd-section">
    <div class="npcd-section-header has-content">
      <span class="npcd-section-title">Dialogue</span>
    </div>
    ${text ? `<div class="npcd-readonly-text">${esc(text)}</div>` : `<div class="npcd-ref-empty">No dialogue</div>`}
    <div class="npcd-decompile-row">
      <button class="npcd-decompile-btn" data-action="decompile">Convert to Editable</button>
      <span class="npcd-status" data-status="decompile"></span>
    </div>
    <div class="npcd-edit-hint">This vanilla script can be converted to a TORCH workspace file for editing.</div>
    ${previewHtml}
  </div>`;
}

function renderPropertiesSection(npc, constants) {
  // Read-only summary rows
  const summary = `
    <div class="npcd-prop-row"><span class="npcd-prop-key">Graphics</span><span class="npcd-prop-val">${esc(npc.graphics_id || "—")}</span></div>
    <div class="npcd-prop-row"><span class="npcd-prop-key">Movement</span><span class="npcd-prop-val">${esc(npc.movement_type || "—")}</span></div>
    <div class="npcd-prop-row"><span class="npcd-prop-key">Range</span><span class="npcd-prop-val">${esc(String(Number(npc.movement_range_x) || 0))} &times; ${esc(String(Number(npc.movement_range_y) || 0))}</span></div>
    <div class="npcd-prop-row"><span class="npcd-prop-key">Elevation</span><span class="npcd-prop-val">${esc(String(Number(npc.elevation) || 0))}</span></div>
    <div class="npcd-prop-row"><span class="npcd-prop-key">Flag</span><span class="npcd-prop-val">${esc(npc.flag || "0")}</span></div>
    <div class="npcd-prop-row"><span class="npcd-prop-key">Trainer</span><span class="npcd-prop-val">${esc(npc.trainer_type || "—")}</span></div>
    <div class="npcd-prop-row"><span class="npcd-prop-key">Sight</span><span class="npcd-prop-val">${esc(String(Number(npc.trainer_sight_or_berry_tree_id) || 0))}</span></div>`;

  // Full edit form (hidden by default)
  const form = `
    <div class="npcd-field">
      <span class="npcd-field-label">Graphics</span>
      <select class="npcd-select" data-prop="graphics_id">
        ${buildOptions(constants.graphics_ids || [], npc.graphics_id)}
      </select>
    </div>
    <div class="npcd-field">
      <span class="npcd-field-label">Position</span>
      <div class="npcd-field-pair">
        <span class="npcd-pair-label">X</span>
        <input type="number" class="npcd-input npcd-input-num" data-prop="x" value="${Number(npc.x) || 0}" min="0">
        <span class="npcd-pair-label">Y</span>
        <input type="number" class="npcd-input npcd-input-num" data-prop="y" value="${Number(npc.y) || 0}" min="0">
      </div>
    </div>
    <div class="npcd-field">
      <span class="npcd-field-label">Elevation</span>
      <input type="number" class="npcd-input npcd-input-num" data-prop="elevation" value="${Number(npc.elevation) || 0}" min="0" max="15">
    </div>
    <div class="npcd-field">
      <span class="npcd-field-label">Movement</span>
      <select class="npcd-select" data-prop="movement_type">
        ${buildOptions(constants.movement_types || [], npc.movement_type)}
      </select>
    </div>
    <div class="npcd-field">
      <span class="npcd-field-label">Range</span>
      <div class="npcd-field-pair">
        <span class="npcd-pair-label">X</span>
        <input type="number" class="npcd-input npcd-input-num" data-prop="movement_range_x" value="${Number(npc.movement_range_x) || 0}" min="0">
        <span class="npcd-pair-label">Y</span>
        <input type="number" class="npcd-input npcd-input-num" data-prop="movement_range_y" value="${Number(npc.movement_range_y) || 0}" min="0">
      </div>
    </div>
    <div class="npcd-field">
      <span class="npcd-field-label">Flag</span>
      <input type="text" class="npcd-input npcd-input-text" data-prop="flag" value="${esc(npc.flag || "0")}" placeholder="0 or FLAG_NAME">
    </div>
    <div class="npcd-field">
      <span class="npcd-field-label">Trainer</span>
      <select class="npcd-select" data-prop="trainer_type">
        ${buildOptions(constants.trainer_types || [], npc.trainer_type)}
      </select>
    </div>
    <div class="npcd-field">
      <span class="npcd-field-label">Sight</span>
      <input type="number" class="npcd-input npcd-input-num" data-prop="trainer_sight_or_berry_tree_id"
        value="${Number(npc.trainer_sight_or_berry_tree_id) || 0}" min="0">
    </div>
    <div style="display:flex;align-items:center;margin-top:0.5rem">
      <button class="npcd-save-btn" data-action="save-props">Save Properties</button>
      <span class="npcd-status" data-status="props"></span>
    </div>`;

  return `<div class="npcd-section">
    <div class="npcd-section-header" data-toggle="properties">
      <span class="npcd-section-title">Properties</span>
      <button class="npcd-toggle-btn">Edit</button>
    </div>
    <div class="npcd-props-summary">${summary}</div>
    <div class="npcd-props-form" style="display:none">${form}</div>
  </div>`;
}

function renderScriptInfoSection(npc, badgeStyle, scriptType) {
  const managedNote = npc.is_workspace_managed
    ? `<div class="npcd-managed-note">Managed by Scene Editor &mdash; <a href="#/scripts">Open</a></div>`
    : "";

  const content = `
    <div class="npcd-info-row">
      <span class="npcd-info-key">Type</span>
      <span class="npcd-info-val">
        <span class="npcd-type-badge" style="${badgeStyle}">${esc(scriptType)}</span>
      </span>
    </div>
    <div class="npcd-info-row">
      <span class="npcd-info-key">Label</span>
      <span class="npcd-info-val">${esc(npc.script || "—")}</span>
    </div>
    <div class="npcd-info-row">
      <span class="npcd-info-key">Source</span>
      <span class="npcd-info-val">${esc(npc.script_source || "—")}</span>
    </div>
    ${managedNote}`;

  return `<div class="npcd-section">
    <div class="npcd-section-header" data-toggle="script-info">
      <span class="npcd-section-title">Script Info</span>
      <button class="npcd-toggle-btn">Show</button>
    </div>
    <div class="npcd-section-content" data-content="script-info" style="display:none">
      ${content}
    </div>
  </div>`;
}

function renderReferencedBySection(npc) {
  const refs = npc.referenced_by || [];
  let body;
  if (refs.length === 0) {
    body = `<div class="npcd-ref-empty">Not referenced by any scene files</div>`;
  } else {
    body = refs.map(r => `
      <div class="npcd-ref-item">
        <span class="npcd-ref-file">${esc(r.file || r.script_name)}</span>
        ${r.alias_name ? ` <span class="npcd-ref-alias">(as &ldquo;${esc(r.alias_name)}&rdquo;)</span>` : ""}
        <a class="npcd-ref-link" href="#/scripts">\u2192 Open in Script Editor</a>
      </div>
    `).join("");
  }

  return `<div class="npcd-section">
    <div class="npcd-section-header" data-toggle="referenced-by">
      <span class="npcd-section-title">Referenced By</span>
      <button class="npcd-toggle-btn">Show</button>
    </div>
    <div class="npcd-section-content" data-content="referenced-by" style="display:none">
      ${body}
    </div>
  </div>`;
}

// ---------------------------------------------------------------------------
// Event wiring
// ---------------------------------------------------------------------------

function wireCollapsibles(container) {
  container.querySelectorAll("[data-toggle]").forEach(header => {
    const btn = header.querySelector(".npcd-toggle-btn");
    if (!btn) return;
    const key = header.dataset.toggle;

    btn.addEventListener("click", () => {
      if (key === "properties") {
        const summary = container.querySelector(".npcd-props-summary");
        const form = container.querySelector(".npcd-props-form");
        const showing = form.style.display !== "none";
        summary.style.display = showing ? "" : "none";
        form.style.display = showing ? "none" : "";
        btn.textContent = showing ? "Edit" : "Close";
      } else {
        const content = container.querySelector(`[data-content="${key}"]`);
        if (!content) return;
        const showing = content.style.display !== "none";
        content.style.display = showing ? "none" : "";
        btn.textContent = showing ? "Show" : "Hide";
      }
    });
  });
}

function wireBackButton(container, mapName) {
  const backBtn = container.querySelector('[data-action="back"]');
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      location.hash = `#/npcs/${mapName}`;
    });
  }
}

function wireDeleteButton(container, mapName, npcId, npc) {
  const delBtn = container.querySelector('[data-action="delete"]');
  if (!delBtn) return;

  delBtn.addEventListener("click", () => {
    const displayName = npc.display_name || npc.graphics_id || `NPC ${npcId}`;
    const trainerWarn = npc.is_trainer
      ? `<div class="npcd-modal-warn">\u26a0 This NPC is a trainer. Associated trainer data may need manual cleanup.</div>`
      : "";

    const { el, close } = createModal("npcd-modal", `
      <h3>Delete NPC?</h3>
      <p>Delete NPC ${esc(String(npcId))} (${esc(displayName)}) from <strong>${esc(mapName)}</strong>?</p>
      ${trainerWarn}
      <p style="color:var(--text-muted,#6c7086);font-size:0.8rem;margin-top:0.35rem">
        This will remove the NPC from map.json. Script files are not deleted.</p>
      <div style="font-size:0.8rem;color:#f38ba8;margin-top:0.35rem;display:none" data-delete-error></div>
      <div class="npcd-modal-actions">
        <button class="npcd-modal-cancel" data-action="cancel">Cancel</button>
        <button class="npcd-modal-confirm" data-action="confirm-delete">Delete</button>
      </div>
    `);

    el.querySelector('[data-action="cancel"]').addEventListener("click", close);

    el.querySelector('[data-action="confirm-delete"]').addEventListener("click", async () => {
      const confirmBtn = el.querySelector('[data-action="confirm-delete"]');
      const errEl = el.querySelector('[data-delete-error]');
      confirmBtn.disabled = true;
      confirmBtn.textContent = "Deleting\u2026";

      try {
        const res = await deleteApi(`/npcs/${encodeURIComponent(mapName)}/${encodeURIComponent(npcId)}`);
        if (res?.ok) {
          close();
          location.hash = `#/npcs/${mapName}`;
        } else {
          errEl.textContent = res?.error || "Deletion failed";
          errEl.style.display = "block";
          confirmBtn.disabled = false;
          confirmBtn.textContent = "Delete";
        }
      } catch (err) {
        errEl.textContent = "Network error: " + (err.message || "unknown");
        errEl.style.display = "block";
        confirmBtn.disabled = false;
        confirmBtn.textContent = "Delete";
      }
    });
  });
}

function wirePropertiesSave(container, mapName, npcId) {
  const saveBtn = container.querySelector('[data-action="save-props"]');
  if (!saveBtn) return;

  saveBtn.addEventListener("click", async () => {
    const statusEl = container.querySelector('[data-status="props"]');
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving\u2026";
    statusEl.textContent = "";
    statusEl.className = "npcd-status";

    // Gather form values
    const payload = {};
    const fields = container.querySelectorAll("[data-prop]");
    for (const f of fields) {
      const key = f.dataset.prop;
      const val = f.type === "number" ? Number(f.value) : f.value;
      payload[key] = val;
    }

    const res = await postApi(`/npcs/${encodeURIComponent(mapName)}/${encodeURIComponent(npcId)}`, payload);

    if (res && res.ok) {
      statusEl.textContent = "Saved!";
      statusEl.className = "npcd-status npcd-status-ok";
      setTimeout(() => { statusEl.textContent = ""; }, 3000);
    } else {
      statusEl.textContent = res?.error || "Save failed";
      statusEl.className = "npcd-status npcd-status-err";
    }

    saveBtn.disabled = false;
    saveBtn.textContent = "Save Properties";
  });
}

function wireDialogue(container, mapName, npcId, npc) {
  if (!npc.is_editable) return;

  const textarea = container.querySelector('[data-field="dialogue"]');
  const previewWrap = container.querySelector('[data-preview="gba"]');
  const saveBtn = container.querySelector('[data-action="save-dialogue"]');
  const statusEl = container.querySelector('[data-status="dialogue"]');

  if (!textarea || !previewWrap) return;

  // Live GBA preview
  textarea.addEventListener("input", () => {
    if (livePreviewTimer) clearTimeout(livePreviewTimer);
    livePreviewTimer = setTimeout(() => {
      previewWrap.innerHTML = renderGbaPreview(textarea.value);
    }, 150);
  });

  if (!saveBtn) return;

  saveBtn.addEventListener("click", async () => {
    const msgboxSelect = container.querySelector('[data-field="msgbox_type"]');
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving\u2026";
    statusEl.textContent = "";
    statusEl.className = "npcd-status";

    const res = await postApi(
      `/npcs/${encodeURIComponent(mapName)}/${encodeURIComponent(npcId)}/dialogue`,
      {
        text: textarea.value,
        msgbox_type: msgboxSelect ? msgboxSelect.value : "MSGBOX_NPC",
      }
    );

    if (res && res.ok) {
      statusEl.textContent = "Saved!";
      statusEl.className = "npcd-status npcd-status-ok";
      setTimeout(() => { statusEl.textContent = ""; }, 3000);
    } else {
      statusEl.textContent = res?.error || "Save failed";
      statusEl.className = "npcd-status npcd-status-err";
    }

    saveBtn.disabled = false;
    saveBtn.textContent = "Save Dialogue";
  });
}

function wireDecompile(container, mapName, npcId) {
  const btn = container.querySelector('[data-action="decompile"]');
  if (!btn) return;

  const statusEl = container.querySelector('[data-status="decompile"]');

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "Converting\u2026";
    if (statusEl) { statusEl.textContent = ""; statusEl.className = "npcd-status"; }

    const res = await postApi(
      `/npcs/${encodeURIComponent(mapName)}/${encodeURIComponent(npcId)}/decompile`,
      {}
    );

    if (res && res.ok) {
      if (statusEl) {
        statusEl.textContent = "Converted!";
        statusEl.className = "npcd-status npcd-status-ok";
      }
      // Re-render the detail to show editable dialogue
      const detail = await api(`/npcs/${encodeURIComponent(mapName)}/${encodeURIComponent(npcId)}`);
      if (detail && detail.ok && detail.data) {
        // Find the parent container and re-render
        const parent = container.closest(".npcd-root") || container.closest(".npcm-detail") || container;
        if (parent) {
          await renderNpcDetail(parent, mapName, npcId);
        }
      }
    } else {
      btn.disabled = false;
      btn.textContent = "Convert to Editable";
      if (statusEl) {
        statusEl.textContent = res?.error || "Conversion failed";
        statusEl.className = "npcd-status npcd-status-err";
      }
    }
  });
}
