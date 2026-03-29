/**
 * TORCH Web GUI -- NPC Creation Wizard.
 * TORCH_MODULE
 * Multi-step modal for creating NPCs via wizard templates.
 */

import { api, postApi } from "../app.js";
import { esc, createModal } from "../utils.js";

let cachedConstants = null;

// ---------------------------------------------------------------------------
// Scoped CSS
// ---------------------------------------------------------------------------

const STYLES = `
.npcw-backdrop {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0,0,0,0.65);
  display: flex; align-items: center; justify-content: center;
}
.npcw-modal {
  background: var(--bg-secondary, #1e1e2e);
  border: 1px solid var(--border, #313244);
  border-radius: 12px;
  width: 520px; max-width: 95vw; max-height: 85vh;
  overflow-y: auto;
  box-shadow: 0 20px 60px rgba(0,0,0,0.4);
}
.npcw-header {
  display: flex; align-items: center; padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--border, #313244);
}
.npcw-title { flex: 1; font-size: 1rem; font-weight: 600; color: var(--text-primary, #cdd6f4); }
.npcw-close {
  background: none; border: none; color: var(--text-muted, #6c7086);
  font-size: 1.2rem; cursor: pointer; padding: 0.25rem;
}
.npcw-close:hover { color: var(--text-primary, #cdd6f4); }
.npcw-body { padding: 1.25rem; }

/* Step 1: Type selection */
.npcw-section-label {
  font-size: 0.75rem; color: var(--text-muted, #6c7086); font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.05em;
  margin-bottom: 0.5rem; margin-top: 1rem;
}
.npcw-section-label:first-child { margin-top: 0; }
.npcw-type-list { display: flex; flex-direction: column; gap: 0.4rem; }
.npcw-type-btn {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.6rem 0.75rem; border-radius: 8px; cursor: pointer;
  background: var(--bg-tertiary, #45475a); border: 1px solid transparent;
  transition: border-color 0.15s, background 0.15s;
}
.npcw-type-btn:hover {
  border-color: var(--accent, #cba6f7);
  background: var(--bg-hover, #313244);
}
.npcw-type-name {
  font-weight: 600; font-size: 0.85rem; color: var(--text-primary, #cdd6f4);
}
.npcw-type-desc {
  font-size: 0.8rem; color: var(--text-muted, #6c7086);
}
.npcw-divider {
  border: none; border-top: 1px solid var(--border, #313244); margin: 0.75rem 0;
}

/* Step 2: Form */
.npcw-field {
  display: flex; flex-direction: column; gap: 0.25rem; margin-bottom: 0.75rem;
}
.npcw-label {
  font-size: 0.8rem; color: var(--text-secondary, #bac2de); font-weight: 600;
}
.npcw-required::after { content: " *"; color: #f38ba8; }
.npcw-row { display: flex; gap: 0.5rem; align-items: center; }
.npcw-input, .npcw-select {
  width: 100%; padding: 0.4rem 0.6rem;
  background: var(--bg-tertiary, #45475a); color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border, #313244); border-radius: 6px;
  font-size: 0.85rem; font-family: inherit;
}
.npcw-input:focus, .npcw-select:focus {
  outline: none; border-color: var(--accent, #89b4fa);
}
.npcw-input-num { width: 70px; }
.npcw-textarea {
  width: 100%; min-height: 60px; resize: vertical;
  background: var(--bg-tertiary, #45475a); color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border, #313244); border-radius: 6px;
  padding: 0.5rem 0.6rem; font-size: 0.85rem; font-family: inherit; line-height: 1.4;
}
.npcw-textarea:focus { outline: none; border-color: var(--accent, #89b4fa); }

.npcw-gba-preview {
  font-family: "Courier New", monospace;
  font-size: 0.8rem; line-height: 1.4;
  background: var(--bg-primary, #11111b);
  border: 2px solid var(--border, #313244);
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
  color: var(--text-primary, #cdd6f4);
  max-width: 320px; white-space: pre-wrap; word-break: break-all;
  margin-top: 0.25rem;
}

/* Multi-state */
.npcw-state {
  background: var(--bg-tertiary, #45475a); border: 1px solid var(--border, #313244);
  border-radius: 8px; padding: 0.75rem; margin-bottom: 0.5rem;
}
.npcw-state-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 0.4rem;
}
.npcw-state-label { font-size: 0.8rem; font-weight: 600; color: var(--text-primary, #cdd6f4); }
.npcw-state-remove {
  background: rgba(243,139,168,0.15); color: #f38ba8; border: none;
  border-radius: 4px; padding: 0.2rem 0.5rem; font-size: 0.75rem; cursor: pointer;
}
.npcw-add-state {
  background: rgba(137,180,250,0.15); color: #89b4fa; border: none;
  border-radius: 6px; padding: 0.35rem 0.75rem; font-size: 0.8rem; cursor: pointer;
  font-weight: 600;
}
.npcw-add-state:hover { background: rgba(137,180,250,0.25); }

/* Actions */
.npcw-actions {
  display: flex; gap: 0.5rem; justify-content: flex-end;
  margin-top: 1rem; padding-top: 0.75rem;
  border-top: 1px solid var(--border, #313244);
}
.npcw-btn-back {
  padding: 0.4rem 0.85rem; background: var(--bg-tertiary, #45475a);
  color: var(--text-primary, #cdd6f4); border: none; border-radius: 6px;
  cursor: pointer; font-size: 0.85rem;
}
.npcw-btn-back:hover { background: var(--border, #313244); }
.npcw-btn-create {
  padding: 0.4rem 1rem; background: rgba(166,227,161,0.2);
  color: #a6e3a1; border: none; border-radius: 6px;
  cursor: pointer; font-size: 0.85rem; font-weight: 600;
}
.npcw-btn-create:hover { background: rgba(166,227,161,0.35); }
.npcw-btn-create:disabled { opacity: 0.5; cursor: default; }

.npcw-error {
  color: #f38ba8; font-size: 0.8rem; margin-top: 0.15rem;
}
.npcw-error-global {
  background: rgba(243,139,168,0.1); color: #f38ba8;
  border: 1px solid rgba(243,139,168,0.2); border-radius: 6px;
  padding: 0.5rem 0.75rem; font-size: 0.8rem; margin-top: 0.75rem;
}
`;

let styleEl = null;

function injectCSS() {
  if (!styleEl) {
    styleEl = document.createElement("style");
    styleEl.textContent = STYLES;
    document.head.appendChild(styleEl);
  }
}

// ---------------------------------------------------------------------------
// GBA text preview (simplified version)
// ---------------------------------------------------------------------------

function wrapGbaText(text, lineWidth = 31) {
  if (!text) return [[""]];
  const pages = text.split(/\\p/);
  return pages.map(page => {
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
  if (!text) return "";
  const pages = wrapGbaText(text);
  return pages.map(lines =>
    `<div class="npcw-gba-preview">${esc(lines.join("\n"))}</div>`
  ).join("");
}

// ---------------------------------------------------------------------------
// Constants loader
// ---------------------------------------------------------------------------

async function loadConstants() {
  if (cachedConstants) return cachedConstants;
  const res = await api("/npcs/constants");
  if (res?.ok && res.data) {
    cachedConstants = res.data;
  }
  return cachedConstants || { movement_types: [], graphics_ids: [] };
}

// ---------------------------------------------------------------------------
// Template definitions (fallback if API not yet available)
// ---------------------------------------------------------------------------

const WIZARD_TYPES = [
  { type: "flavor", name: "Flavor NPC", description: "Simple dialogue NPC", category: "npc" },
  { type: "sign", name: "Sign", description: "Readable sign or plaque", category: "npc" },
  { type: "item_giver", name: "Item Giver", description: "Gives an item once", category: "npc" },
  { type: "multi_state", name: "Multi-State", description: "Flag-based dialogue", category: "npc" },
  { type: "nurse", name: "Nurse Joy", description: "Pokemon Center healing", category: "infra" },
  { type: "pc", name: "PC", description: "Storage system", category: "infra" },
  { type: "infra_sign", name: "Infra Sign", description: "Standard sign BG event", category: "infra" },
];

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

/**
 * Open the NPC creation wizard as a modal.
 * @param {string} mapName - Target map name
 * @param {function} onCreated - Callback after successful creation (receives new NPC data)
 */
/**
 * Open the NPC creation wizard.
 * @param {string} mapName — target map folder name
 * @param {function} onCreated — callback after successful creation
 * @param {object} [opts] — optional: { x, y } to pre-fill position fields
 */
export function openNpcWizard(mapName, onCreated, opts) {
  injectCSS();

  const backdrop = document.createElement("div");
  backdrop.className = "npcw-backdrop";
  document.body.appendChild(backdrop);

  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    document.removeEventListener("keydown", onEsc);
    backdrop.remove();
  };
  function onEsc(e) { if (e.key === "Escape") close(); }
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
  document.addEventListener("keydown", onEsc);

  const modal = document.createElement("div");
  modal.className = "npcw-modal";
  backdrop.appendChild(modal);

  // Store pre-fill coords so step 2 can use them
  modal._prefillX = opts?.x ?? null;
  modal._prefillY = opts?.y ?? null;

  showStep1(modal, mapName, onCreated, close);
}

// ---------------------------------------------------------------------------
// Step 1: Type Selection
// ---------------------------------------------------------------------------

async function showStep1(modal, mapName, onCreated, close) {
  // Try loading templates from API, fall back to hardcoded list
  let templates = WIZARD_TYPES;
  try {
    const res = await api("/npcs/templates");
    if (res?.ok && res.data?.templates) {
      templates = res.data.templates;
    }
  } catch (_) { /* use fallback */ }

  const npcTypes = templates.filter(t => t.category !== "infra");
  const infraTypes = templates.filter(t => t.category === "infra");

  modal.innerHTML = `
    <div class="npcw-header">
      <span class="npcw-title">Create New NPC</span>
      <button class="npcw-close" data-action="close">&times;</button>
    </div>
    <div class="npcw-body">
      <div class="npcw-section-label">What kind of NPC?</div>
      <div class="npcw-type-list">
        ${npcTypes.map(t => `
          <div class="npcw-type-btn" data-type="${esc(t.type)}">
            <span class="npcw-type-name">${esc(t.name)}</span>
            <span class="npcw-type-desc">${esc(t.description)}</span>
          </div>
        `).join("")}
      </div>
      ${infraTypes.length ? `
        <hr class="npcw-divider">
        <div class="npcw-section-label">Infrastructure</div>
        <div class="npcw-type-list">
          ${infraTypes.map(t => `
            <div class="npcw-type-btn" data-type="${esc(t.type)}">
              <span class="npcw-type-name">${esc(t.name)}</span>
              <span class="npcw-type-desc">${esc(t.description)}</span>
            </div>
          `).join("")}
        </div>
      ` : ""}
    </div>
  `;

  modal.querySelector('[data-action="close"]').addEventListener("click", close);

  modal.querySelectorAll(".npcw-type-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const type = btn.dataset.type;
      const template = templates.find(t => t.type === type) || { type, name: type };
      showStep2(modal, mapName, template, onCreated, close);
    });
  });
}

// ---------------------------------------------------------------------------
// Step 2: Form (varies by type)
// ---------------------------------------------------------------------------

async function showStep2(modal, mapName, template, onCreated, close) {
  const constants = await loadConstants();
  const type = template.type;

  const gfxOptions = (constants.graphics_ids || []).map(g =>
    `<option value="${esc(g.const)}">${esc(g.label)}</option>`
  ).join("");
  const moveOptions = (constants.movement_types || []).map(m =>
    `<option value="${esc(m.const)}"${m.const === "MOVEMENT_TYPE_FACE_DOWN" ? " selected" : ""}>${esc(m.label)}</option>`
  ).join("");

  let formHtml = "";

  if (type === "flavor") {
    formHtml = buildFlavorForm(gfxOptions, moveOptions);
  } else if (type === "sign") {
    formHtml = buildSignForm();
  } else if (type === "item_giver") {
    formHtml = buildItemGiverForm(gfxOptions, moveOptions);
  } else if (type === "multi_state") {
    formHtml = buildMultiStateForm(gfxOptions, moveOptions);
  } else if (type === "nurse") {
    formHtml = buildNurseForm();
  } else if (type === "pc") {
    formHtml = buildPcForm();
  } else if (type === "infra_sign") {
    formHtml = buildInfraSignForm();
  }

  modal.innerHTML = `
    <div class="npcw-header">
      <span class="npcw-title">New ${esc(template.name)}</span>
      <button class="npcw-close" data-action="close">&times;</button>
    </div>
    <div class="npcw-body">
      ${formHtml}
      <div class="npcw-error-global" data-error="global" style="display:none"></div>
      <div class="npcw-actions">
        <button class="npcw-btn-back" data-action="back">Back</button>
        <button class="npcw-btn-create" data-action="create">Create NPC</button>
      </div>
    </div>
  `;

  // Pre-fill position from canvas context menu if provided
  if (modal._prefillX != null) {
    const xInput = modal.querySelector('[data-field="x"]');
    if (xInput) xInput.value = modal._prefillX;
  }
  if (modal._prefillY != null) {
    const yInput = modal.querySelector('[data-field="y"]');
    if (yInput) yInput.value = modal._prefillY;
  }

  modal.querySelector('[data-action="close"]').addEventListener("click", close);
  modal.querySelector('[data-action="back"]').addEventListener("click", () => {
    showStep1(modal, mapName, onCreated, close);
  });

  // Wire live GBA previews
  wireLivePreview(modal);

  // Wire multi-state add/remove
  if (type === "multi_state") wireMultiState(modal);

  // Wire create
  modal.querySelector('[data-action="create"]').addEventListener("click", async () => {
    await handleCreate(modal, mapName, type, onCreated, close);
  });
}

// ---------------------------------------------------------------------------
// Form builders
// ---------------------------------------------------------------------------

function positionFields() {
  return `
    <div class="npcw-field">
      <label class="npcw-label npcw-required">Position</label>
      <div class="npcw-row">
        <span style="font-size:0.8rem;color:var(--text-muted)">X</span>
        <input type="number" class="npcw-input npcw-input-num" data-field="x" value="0" min="0">
        <span style="font-size:0.8rem;color:var(--text-muted)">Y</span>
        <input type="number" class="npcw-input npcw-input-num" data-field="y" value="0" min="0">
      </div>
    </div>
  `;
}

function nameField() {
  return `
    <div class="npcw-field">
      <label class="npcw-label npcw-required">Name</label>
      <input type="text" class="npcw-input" data-field="name" placeholder="e.g. OldMan, Ranger, Hiker">
      <div class="npcw-error" data-error="name" style="display:none"></div>
    </div>
  `;
}

function spriteField(gfxOptions) {
  return `
    <div class="npcw-field">
      <label class="npcw-label npcw-required">Sprite</label>
      <select class="npcw-select" data-field="graphics_id">${gfxOptions}</select>
    </div>
  `;
}

function movementField(moveOptions) {
  return `
    <div class="npcw-field">
      <label class="npcw-label">Facing / Movement</label>
      <select class="npcw-select" data-field="movement_type">${moveOptions}</select>
    </div>
  `;
}

function dialogueField(label = "Dialogue", field = "dialogue") {
  return `
    <div class="npcw-field">
      <label class="npcw-label">${esc(label)}</label>
      <textarea class="npcw-textarea" data-field="${esc(field)}" placeholder="Enter dialogue text..."></textarea>
      <div data-preview="${esc(field)}"></div>
    </div>
  `;
}

function buildFlavorForm(gfxOptions, moveOptions) {
  return nameField() +
    spriteField(gfxOptions) +
    positionFields() +
    movementField(moveOptions) +
    dialogueField();
}

function buildSignForm() {
  return nameField() +
    positionFields() +
    dialogueField();
}

function buildItemGiverForm(gfxOptions, moveOptions) {
  return nameField() +
    spriteField(gfxOptions) +
    positionFields() +
    movementField(moveOptions) +
    `<div class="npcw-field">
      <label class="npcw-label npcw-required">Item Constant</label>
      <input type="text" class="npcw-input" data-field="item" placeholder="ITEM_POTION">
      <div class="npcw-error" data-error="item" style="display:none"></div>
    </div>
    <div class="npcw-field">
      <label class="npcw-label npcw-required">Flag Constant</label>
      <input type="text" class="npcw-input" data-field="flag" placeholder="FLAG_RECEIVED_POTION">
      <div class="npcw-error" data-error="flag" style="display:none"></div>
    </div>` +
    dialogueField("Before Text", "before_text") +
    dialogueField("After Text", "after_text");
}

function buildMultiStateForm(gfxOptions, moveOptions) {
  return nameField() +
    spriteField(gfxOptions) +
    positionFields() +
    movementField(moveOptions) +
    `<div class="npcw-field">
      <label class="npcw-label">States</label>
      <div data-states>
        <div class="npcw-state" data-state-index="0">
          <div class="npcw-state-header">
            <span class="npcw-state-label">State 1 (default)</span>
          </div>
          <textarea class="npcw-textarea" data-field="state_text_0" placeholder="Default dialogue..."></textarea>
        </div>
        <div class="npcw-state" data-state-index="1">
          <div class="npcw-state-header">
            <span class="npcw-state-label">State 2</span>
            <button class="npcw-state-remove" data-remove-state="1">Remove</button>
          </div>
          <input type="text" class="npcw-input" data-field="state_flag_1" placeholder="FLAG_NAME" style="margin-bottom:0.4rem">
          <textarea class="npcw-textarea" data-field="state_text_1" placeholder="Dialogue after flag is set..."></textarea>
        </div>
      </div>
      <button class="npcw-add-state" data-action="add-state">+ Add State</button>
    </div>`;
}

function buildNurseForm() {
  return `<p style="font-size:0.85rem;color:var(--text-secondary,#bac2de);margin-bottom:0.75rem">
    Creates a Nurse Joy NPC with standard healing script. Only position is needed.
  </p>` + positionFields();
}

function buildPcForm() {
  return `<p style="font-size:0.85rem;color:var(--text-secondary,#bac2de);margin-bottom:0.75rem">
    Creates a PC background event with storage system script. Only position is needed.
  </p>` + positionFields();
}

function buildInfraSignForm() {
  return positionFields() + dialogueField("Sign Text", "dialogue");
}

// ---------------------------------------------------------------------------
// Live GBA preview wiring
// ---------------------------------------------------------------------------

function wireLivePreview(modal) {
  modal.querySelectorAll(".npcw-textarea").forEach(ta => {
    const field = ta.dataset.field;
    const previewEl = modal.querySelector(`[data-preview="${field}"]`);
    if (!previewEl) return;

    let timer = null;
    ta.addEventListener("input", () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        previewEl.innerHTML = renderGbaPreview(ta.value);
      }, 150);
    });
  });
}

// ---------------------------------------------------------------------------
// Multi-state add/remove
// ---------------------------------------------------------------------------

function wireMultiState(modal) {
  const statesContainer = modal.querySelector("[data-states]");
  const addBtn = modal.querySelector('[data-action="add-state"]');
  if (!statesContainer || !addBtn) return;

  let stateCount = 2;

  addBtn.addEventListener("click", () => {
    stateCount++;
    const div = document.createElement("div");
    div.className = "npcw-state";
    div.dataset.stateIndex = String(stateCount - 1);
    div.innerHTML = `
      <div class="npcw-state-header">
        <span class="npcw-state-label">State ${stateCount}</span>
        <button class="npcw-state-remove" data-remove-state="${stateCount - 1}">Remove</button>
      </div>
      <input type="text" class="npcw-input" data-field="state_flag_${stateCount - 1}" placeholder="FLAG_NAME" style="margin-bottom:0.4rem">
      <textarea class="npcw-textarea" data-field="state_text_${stateCount - 1}" placeholder="Dialogue after flag is set..."></textarea>
    `;
    statesContainer.appendChild(div);
    wireRemoveButtons(statesContainer);
  });

  wireRemoveButtons(statesContainer);
}

function wireRemoveButtons(container) {
  container.querySelectorAll(".npcw-state-remove").forEach(btn => {
    // Replace to clear previous listeners
    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);
    newBtn.addEventListener("click", () => {
      const stateEl = newBtn.closest(".npcw-state");
      if (stateEl) stateEl.remove();
    });
  });
}

// ---------------------------------------------------------------------------
// Form validation + submission
// ---------------------------------------------------------------------------

function clearErrors(modal) {
  modal.querySelectorAll(".npcw-error, .npcw-error-global").forEach(el => {
    el.style.display = "none";
    el.textContent = "";
  });
}

function showFieldError(modal, field, msg) {
  const errEl = modal.querySelector(`[data-error="${field}"]`);
  if (errEl) {
    errEl.textContent = msg;
    errEl.style.display = "block";
  }
}

function getField(modal, name) {
  const el = modal.querySelector(`[data-field="${name}"]`);
  if (!el) return "";
  return el.type === "number" ? Number(el.value) : el.value.trim();
}

async function handleCreate(modal, mapName, type, onCreated, close) {
  clearErrors(modal);
  const createBtn = modal.querySelector('[data-action="create"]');
  let valid = true;

  // Build body based on type
  let body = { type };

  if (type === "flavor") {
    const name = getField(modal, "name");
    if (!name) { showFieldError(modal, "name", "Name is required"); valid = false; }
    body.name = name;
    body.graphics_id = getField(modal, "graphics_id");
    body.x = getField(modal, "x");
    body.y = getField(modal, "y");
    body.movement_type = getField(modal, "movement_type");
    body.dialogue = getField(modal, "dialogue");
  } else if (type === "sign") {
    const name = getField(modal, "name");
    if (!name) { showFieldError(modal, "name", "Name is required"); valid = false; }
    body.name = name;
    body.x = getField(modal, "x");
    body.y = getField(modal, "y");
    body.dialogue = getField(modal, "dialogue");
  } else if (type === "item_giver") {
    const name = getField(modal, "name");
    if (!name) { showFieldError(modal, "name", "Name is required"); valid = false; }
    const item = getField(modal, "item");
    if (!item) { showFieldError(modal, "item", "Item constant is required"); valid = false; }
    const flag = getField(modal, "flag");
    if (!flag) { showFieldError(modal, "flag", "Flag constant is required"); valid = false; }
    body.name = name;
    body.graphics_id = getField(modal, "graphics_id");
    body.x = getField(modal, "x");
    body.y = getField(modal, "y");
    body.movement_type = getField(modal, "movement_type");
    body.item = item;
    body.flag = flag;
    body.before_text = getField(modal, "before_text");
    body.after_text = getField(modal, "after_text");
  } else if (type === "multi_state") {
    const name = getField(modal, "name");
    if (!name) { showFieldError(modal, "name", "Name is required"); valid = false; }
    body.name = name;
    body.graphics_id = getField(modal, "graphics_id");
    body.x = getField(modal, "x");
    body.y = getField(modal, "y");
    body.movement_type = getField(modal, "movement_type");
    // Collect states
    const stateEls = modal.querySelectorAll("[data-states] .npcw-state");
    body.states = [];
    stateEls.forEach((stateEl, idx) => {
      const sIdx = stateEl.dataset.stateIndex;
      const text = getField(modal, `state_text_${sIdx}`);
      if (idx === 0) {
        body.states.push({ text });
      } else {
        const flag = getField(modal, `state_flag_${sIdx}`);
        body.states.push({ flag, text });
      }
    });
  } else if (type === "nurse") {
    body.x = getField(modal, "x");
    body.y = getField(modal, "y");
  } else if (type === "pc") {
    body.x = getField(modal, "x");
    body.y = getField(modal, "y");
  } else if (type === "infra_sign") {
    body.x = getField(modal, "x");
    body.y = getField(modal, "y");
    body.dialogue = getField(modal, "dialogue");
  }

  if (!valid) return;

  // Submit
  createBtn.disabled = true;
  createBtn.textContent = "Creating...";

  try {
    const res = await postApi(`/npcs/${encodeURIComponent(mapName)}/create`, body);

    if (res?.ok) {
      close();
      if (onCreated) onCreated(res.data);
    } else {
      const errEl = modal.querySelector('[data-error="global"]');
      errEl.textContent = res?.error || "Creation failed";
      errEl.style.display = "block";
    }
  } catch (err) {
    const errEl = modal.querySelector('[data-error="global"]');
    errEl.textContent = "Network error: " + (err.message || "unknown");
    errEl.style.display = "block";
  }

  createBtn.disabled = false;
  createBtn.textContent = "Create NPC";
}
