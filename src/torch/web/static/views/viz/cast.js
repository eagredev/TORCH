// cast.js — Cast panel with sprite thumbnails and alias management
// S235 — Phase 2 (Editors)

import { state, on, off, FRAMES_UPDATED, resimulate, setDirty } from "./state.js";
import { pushHistory } from "./history.js";
import { api } from "../../app.js";

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _container = null;
let _content = null;
let _toggleBtn = null;
let _body = null;
let _expanded = false;
let _handlers = [];
let _contentClickHandler = null;  // Delegated click handler on _content

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function init(containerEl) {
  _container = containerEl;

  _expanded = localStorage.getItem("torch-viz-cast") === "1";

  // Build panel HTML
  const panel = document.createElement("div");
  panel.className = "viz-cast-panel";

  const header = document.createElement("div");
  header.className = "viz-cast-header";

  _toggleBtn = document.createElement("button");
  _toggleBtn.className = "viz-cast-toggle";
  _toggleBtn.title = "Toggle cast panel";
  _toggleBtn.textContent = _expanded ? "Cast \u25be" : "Cast \u25b8";
  header.appendChild(_toggleBtn);

  _body = document.createElement("div");
  _body.className = "viz-cast-body";
  _body.style.display = _expanded ? "" : "none";

  _content = document.createElement("div");
  _content.className = "viz-cast-content";
  _body.appendChild(_content);

  panel.appendChild(header);
  panel.appendChild(_body);
  _container.appendChild(panel);

  _toggleBtn.addEventListener("click", _toggle);

  // Delegated click handler on _content — survives innerHTML rebuilds (Fix 2.3)
  _contentClickHandler = (e) => {
    const removeBtn = e.target.closest(".viz-cast-remove");
    if (removeBtn) { _onRemove(e); return; }

    const addBtn = e.target.closest("#viz-cast-add-btn");
    if (addBtn) { _onAddClick(); return; }

    const confirmBtn = e.target.closest("#viz-cast-confirm");
    if (confirmBtn) { _onConfirmAdd(); return; }

    const cancelBtn = e.target.closest("#viz-cast-cancel-add");
    if (cancelBtn) { _onCancelAdd(); return; }
  };
  _content.addEventListener("click", _contentClickHandler);

  _handlers = [
    { name: FRAMES_UPDATED, handler: on(FRAMES_UPDATED, _renderCast) },
  ];

  if (_expanded) _renderCast();
}

export function cleanup() {
  for (const { name, handler } of _handlers) {
    off(name, handler);
  }
  _handlers = [];

  if (_toggleBtn) {
    _toggleBtn.removeEventListener("click", _toggle);
  }
  if (_content && _contentClickHandler) {
    _content.removeEventListener("click", _contentClickHandler);
  }

  _container = null;
  _content = null;
  _toggleBtn = null;
  _body = null;
  _contentClickHandler = null;
}

// ---------------------------------------------------------------------------
// Expand / collapse
// ---------------------------------------------------------------------------

function _toggle() {
  _expanded = !_expanded;
  localStorage.setItem("torch-viz-cast", _expanded ? "1" : "0");
  _toggleBtn.textContent = _expanded ? "Cast \u25be" : "Cast \u25b8";
  _body.style.display = _expanded ? "" : "none";

  if (_expanded) {
    _renderCast();
  } else {
    _content.innerHTML = "";
  }

  _container.dispatchEvent(new CustomEvent("cast-panel-toggled", {
    bubbles: true,
    detail: { expanded: _expanded },
  }));
}

// ---------------------------------------------------------------------------
// Cast rendering
// ---------------------------------------------------------------------------

function _renderCast() {
  if (!_expanded || !_content) return;
  const cast = state.cast;
  const entries = Object.entries(cast);

  if (entries.length === 0) {
    _content.innerHTML = '<p class="viz-cast-empty">No cast members. Add aliases to your script.</p>';
    return;
  }

  let html = '<div class="viz-cast-section"><h4>Cast</h4>';

  for (const [name, info] of entries) {
    const gfxId = info.graphics_id || "";
    const spriteImg = state.spriteImages[gfxId];

    html += `<div class="viz-cast-row" data-alias="${_esc(name)}">`;

    // Sprite thumbnail
    if (spriteImg && spriteImg.complete) {
      html += `<img class="viz-cast-sprite" src="${_esc(spriteImg.src)}" `
        + `alt="${_esc(gfxId)}" title="${_esc(gfxId)}" />`;
    } else {
      html += `<div class="viz-cast-sprite-placeholder" title="No sprite"></div>`;
    }

    // Name + NPC ID
    html += `<span class="viz-cast-name">${_esc(name)}</span>`;
    if (info.npc_id) {
      html += `<span class="viz-cast-npc">${_esc(info.npc_id)}</span>`;
    }

    // Remove button (not for player)
    if (name !== "player") {
      html += `<button class="viz-cast-remove" data-alias="${_esc(name)}" title="Remove alias">\u00d7</button>`;
    }

    html += `</div>`;
  }

  html += '</div>';

  // Add alias form
  html += `<button class="viz-cast-add" id="viz-cast-add-btn">+ Add Alias</button>`;
  html += `<div class="viz-cast-add-form" id="viz-cast-add-form" style="display:none">`;
  html += `<div class="viz-editor-field"><label>Alias Name</label>`;
  html += `<input type="text" id="viz-cast-alias-name" placeholder="e.g., buster" /></div>`;
  html += `<div class="viz-editor-field"><label>NPC</label>`;
  html += `<select id="viz-cast-npc-select"><option value="">Select NPC...</option></select></div>`;
  html += `<div class="viz-cast-add-actions">`;
  html += `<button class="btn-apply" id="viz-cast-confirm">Add</button>`;
  html += `<button class="btn-cancel" id="viz-cast-cancel-add">Cancel</button>`;
  html += `</div></div>`;

  _content.innerHTML = html;
  // Button events handled by delegated click handler on _content (Fix 2.3)
}

// ---------------------------------------------------------------------------
// Remove alias
// ---------------------------------------------------------------------------

async function _onRemove(e) {
  const btn = e.target.closest(".viz-cast-remove");
  const aliasName = btn ? btn.dataset.alias : null;
  if (!aliasName) return;

  const lines = state.source.split("\n");
  const rx = new RegExp(`^\\s*alias\\s+${_escRegex(aliasName)}\\s+`, "i");
  const filtered = lines.filter(line => !rx.test(line));

  if (filtered.length === lines.length) return; // No match found

  pushHistory(state.source);
  const newSource = filtered.join("\n");
  await resimulate(newSource);
  setDirty(true);
}

// ---------------------------------------------------------------------------
// Add alias
// ---------------------------------------------------------------------------

async function _onAddClick() {
  const form = _content.querySelector("#viz-cast-add-form");
  if (!form) return;
  form.style.display = "";

  // Fetch NPC list
  const select = _content.querySelector("#viz-cast-npc-select");
  if (!select) return;

  try {
    const res = await api(`/scenes/${state.mapName}/npcs`);
    if (res.ok && res.data) {
      const npcs = res.data.npcs || res.data || [];
      let opts = '<option value="">Select NPC...</option>';
      for (const npc of npcs) {
        const id = npc.id ?? npc.npc_id ?? "";
        const script = npc.script || npc.script_label || "";
        const gfx = npc.graphics_id || "";
        const label = `#${id} - ${script} (${gfx})`;
        opts += `<option value="npc${id}">${_esc(label)}</option>`;
      }
      select.innerHTML = opts;
    }
  } catch {
    select.innerHTML = '<option value="">Failed to load NPCs</option>';
  }
}

function _onCancelAdd() {
  const form = _content.querySelector("#viz-cast-add-form");
  if (form) form.style.display = "none";
}

async function _onConfirmAdd() {
  const nameInput = _content.querySelector("#viz-cast-alias-name");
  const npcSelect = _content.querySelector("#viz-cast-npc-select");
  if (!nameInput || !npcSelect) return;

  const aliasName = nameInput.value.trim();
  const npcValue = npcSelect.value;

  if (!aliasName || aliasName.includes(" ")) {
    nameInput.focus();
    return;
  }
  if (!npcValue) {
    npcSelect.focus();
    return;
  }

  const newLine = `alias ${aliasName} ${npcValue}`;
  const insertAt = _findAliasInsertLine(state.source);
  const lines = state.source.split("\n");
  lines.splice(insertAt, 0, newLine);

  pushHistory(state.source);
  const newSource = lines.join("\n");
  await resimulate(newSource);
  setDirty(true);
}

// ---------------------------------------------------------------------------
// Find alias insertion point
// ---------------------------------------------------------------------------

function _findAliasInsertLine(source) {
  const lines = source.split("\n");
  let lastAliasLine = -1;
  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (trimmed.startsWith("alias ") || trimmed.startsWith("#") || trimmed === "") {
      lastAliasLine = i;
    } else {
      break;
    }
  }
  return lastAliasLine + 1;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _esc(s) {
  if (!s) return "";
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function _escRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
