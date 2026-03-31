/**
 * TORCH Web GUI -- Trigger Creation Wizard.
 * TORCH_MODULE
 * Multi-step modal for creating coord_event triggers.
 */

import { api, postApi } from "../app.js";
import { esc } from "../utils.js";

// ---------------------------------------------------------------------------
// Scoped CSS
// ---------------------------------------------------------------------------

const STYLES = `
.trigw-backdrop {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0,0,0,0.65);
  display: flex; align-items: center; justify-content: center;
}
.trigw-modal {
  background: var(--bg-secondary, #1e1e2e);
  border: 1px solid var(--border, #313244);
  border-radius: 12px;
  width: 480px; max-width: 95vw; max-height: 85vh;
  overflow-y: auto;
  box-shadow: 0 20px 60px rgba(0,0,0,0.4);
}
.trigw-header {
  display: flex; align-items: center; padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--border, #313244);
}
.trigw-title {
  flex: 1; font-size: 1rem; font-weight: 600; color: var(--text-primary, #cdd6f4);
}
.trigw-close {
  background: none; border: none; color: var(--text-muted, #6c7086);
  font-size: 1.2rem; cursor: pointer; padding: 0.25rem;
}
.trigw-close:hover { color: var(--text-primary, #cdd6f4); }
.trigw-body { padding: 1.25rem; }
.trigw-step-label {
  font-size: 0.72rem; color: var(--text-muted, #6c7086); font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.05em;
  margin-bottom: 0.75rem;
}
.trigw-field {
  display: flex; flex-direction: column; gap: 0.25rem; margin-bottom: 0.75rem;
}
.trigw-label {
  font-size: 0.8rem; color: var(--text-secondary, #bac2de); font-weight: 600;
}
.trigw-required::after { content: " *"; color: #f38ba8; }
.trigw-row { display: flex; gap: 0.5rem; align-items: center; }
.trigw-input, .trigw-select {
  width: 100%; padding: 0.4rem 0.6rem;
  background: var(--bg-tertiary, #45475a); color: var(--text-primary, #cdd6f4);
  border: 1px solid var(--border, #313244); border-radius: 6px;
  font-size: 0.85rem; font-family: inherit;
}
.trigw-input:focus, .trigw-select:focus {
  outline: none; border-color: var(--accent, #89b4fa);
}
.trigw-input-num { width: 80px; }
.trigw-hint {
  font-size: 0.72rem; color: var(--text-muted, #6c7086); margin-top: 0.1rem;
}
.trigw-template-list { display: flex; flex-direction: column; gap: 0.35rem; }
.trigw-template-btn {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.5rem 0.75rem; border-radius: 8px; cursor: pointer;
  background: var(--bg-tertiary, #45475a); border: 2px solid transparent;
  transition: border-color 0.15s, background 0.15s;
}
.trigw-template-btn:hover {
  border-color: var(--accent, #cba6f7);
  background: var(--bg-hover, #313244);
}
.trigw-template-btn.selected {
  border-color: var(--accent, #89b4fa);
  background: rgba(137,180,250,0.1);
}
.trigw-template-name {
  font-weight: 600; font-size: 0.85rem; color: var(--text-primary, #cdd6f4);
}
.trigw-template-desc {
  font-size: 0.75rem; color: var(--text-muted, #6c7086);
}
.trigw-summary {
  background: var(--bg-primary, #11111b);
  border: 1px solid var(--border, #313244);
  border-radius: 8px;
  padding: 0.75rem 1rem;
  font-size: 0.82rem; color: var(--text-secondary, #bac2de);
  line-height: 1.6;
}
.trigw-summary-label {
  font-weight: 600; color: var(--text-muted, #6c7086);
  display: inline-block; min-width: 90px;
}
.trigw-actions {
  display: flex; gap: 0.5rem; justify-content: flex-end;
  margin-top: 1rem; padding-top: 0.75rem;
  border-top: 1px solid var(--border, #313244);
}
.trigw-btn-back {
  padding: 0.4rem 0.85rem; background: var(--bg-tertiary, #45475a);
  color: var(--text-primary, #cdd6f4); border: none; border-radius: 6px;
  cursor: pointer; font-size: 0.85rem;
}
.trigw-btn-back:hover { background: var(--border, #313244); }
.trigw-btn-next, .trigw-btn-create {
  padding: 0.4rem 1rem; background: rgba(137,180,250,0.2);
  color: #89b4fa; border: none; border-radius: 6px;
  cursor: pointer; font-size: 0.85rem; font-weight: 600;
}
.trigw-btn-create {
  background: rgba(166,227,161,0.2); color: #a6e3a1;
}
.trigw-btn-next:hover { background: rgba(137,180,250,0.35); }
.trigw-btn-create:hover { background: rgba(166,227,161,0.35); }
.trigw-btn-create:disabled, .trigw-btn-next:disabled {
  opacity: 0.5; cursor: default;
}
.trigw-error {
  background: rgba(243,139,168,0.1); color: #f38ba8;
  border: 1px solid rgba(243,139,168,0.2); border-radius: 6px;
  padding: 0.5rem 0.75rem; font-size: 0.8rem; margin-top: 0.75rem;
}
.trigw-checkbox-row {
  display: flex; align-items: center; gap: 0.5rem;
  margin-bottom: 0.5rem;
}
.trigw-checkbox-row label {
  font-size: 0.82rem; color: var(--text-secondary, #bac2de); cursor: pointer;
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
// Wizard state
// ---------------------------------------------------------------------------

const COMMON_VARS = [
  "VAR_TEMP_1", "VAR_TEMP_2", "VAR_TEMP_3", "VAR_TEMP_4", "VAR_TEMP_5",
];

const FALLBACK_TEMPLATES = [
  { id: "basic", name: "Basic", description: "Lock + message + release" },
  { id: "cutscene", name: "Cutscene", description: "Lockall + dialogue + releaseall" },
  { id: "weather_change", name: "Weather Change", description: "Set weather effect" },
  { id: "warp", name: "Warp", description: "Silent warp to another map" },
  { id: "item_check", name: "Item Check", description: "Check for item + branch" },
  { id: "one_time", name: "One-Time", description: "Fire once via flag gate" },
];

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

/**
 * Open the trigger creation wizard.
 * @param {string} mapName
 * @param {function} onCreated — callback after success
 * @param {object} [opts] — { x, y } to pre-fill position
 */
export function openTriggerWizard(mapName, onCreated, opts) {
  injectCSS();

  const backdrop = document.createElement("div");
  backdrop.className = "trigw-backdrop";
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
  modal.className = "trigw-modal";
  backdrop.appendChild(modal);

  const state = {
    x: opts?.x ?? 0,
    y: opts?.y ?? 0,
    elevation: 0,
    var: "0",
    var_value: "0",
    noGating: true,
    template: "basic",
    script_label: "",
    templates: FALLBACK_TEMPLATES,
  };

  // Load templates from API, then show step 1
  api("/triggers/templates").then(res => {
    if (res?.ok && res.data?.templates) {
      state.templates = res.data.templates;
    }
    showStep1(modal, mapName, state, onCreated, close);
  }).catch(() => {
    showStep1(modal, mapName, state, onCreated, close);
  });
}

// ---------------------------------------------------------------------------
// Step 1: Position & Gating
// ---------------------------------------------------------------------------

function showStep1(modal, mapName, state, onCreated, close) {
  const hasCoords = state.x !== null && state.y !== null;
  modal.innerHTML = `
    <div class="trigw-header">
      <span class="trigw-title">Create Trigger</span>
      <button class="trigw-close" data-action="close">&times;</button>
    </div>
    <div class="trigw-body">
      <div class="trigw-step-label">Step 1 of 3 -- Position & Gating</div>

      <div class="trigw-row" style="gap:0.75rem;margin-bottom:0.75rem">
        <div class="trigw-field" style="flex:1;margin-bottom:0">
          <label class="trigw-label trigw-required">X</label>
          <input type="number" id="trigw-x" class="trigw-input trigw-input-num"
            value="${state.x}" min="0">
        </div>
        <div class="trigw-field" style="flex:1;margin-bottom:0">
          <label class="trigw-label trigw-required">Y</label>
          <input type="number" id="trigw-y" class="trigw-input trigw-input-num"
            value="${state.y}" min="0">
        </div>
        <div class="trigw-field" style="flex:1;margin-bottom:0">
          <label class="trigw-label">Elevation</label>
          <select id="trigw-elev" class="trigw-select">
            ${Array.from({ length: 16 }, (_, i) =>
              `<option value="${i}"${i === state.elevation ? " selected" : ""}>${i}${i === 0 ? " (any)" : ""}</option>`
            ).join("")}
          </select>
        </div>
      </div>

      <hr style="border:none;border-top:1px solid var(--border,#313244);margin:0.75rem 0">

      <div class="trigw-checkbox-row">
        <input type="checkbox" id="trigw-nogate" ${state.noGating ? "checked" : ""}>
        <label for="trigw-nogate">No variable gating (always fires)</label>
      </div>

      <div id="trigw-gate-fields" style="${state.noGating ? "display:none" : ""}">
        <div class="trigw-field">
          <label class="trigw-label">Variable</label>
          <input type="text" id="trigw-var" class="trigw-input"
            value="${esc(state.var)}" list="trigw-var-list" autocomplete="off">
          <datalist id="trigw-var-list">
            ${COMMON_VARS.map(v => `<option value="${esc(v)}">`).join("")}
          </datalist>
          <span class="trigw-hint">Trigger fires when this var equals the value below</span>
        </div>
        <div class="trigw-field">
          <label class="trigw-label">Value</label>
          <input type="text" id="trigw-val" class="trigw-input" value="${esc(state.var_value)}">
        </div>
      </div>

      <div class="trigw-actions">
        <button class="trigw-btn-back" data-action="close">Cancel</button>
        <button class="trigw-btn-next" id="trigw-next1">Next</button>
      </div>
    </div>
  `;

  modal.querySelector('[data-action="close"]').addEventListener("click", close);
  modal.querySelector('.trigw-close').addEventListener("click", close);

  // Toggle gate fields
  const noGateCheck = modal.querySelector("#trigw-nogate");
  const gateFields = modal.querySelector("#trigw-gate-fields");
  noGateCheck.addEventListener("change", () => {
    gateFields.style.display = noGateCheck.checked ? "none" : "";
  });

  modal.querySelector("#trigw-next1").addEventListener("click", () => {
    const xEl = modal.querySelector("#trigw-x");
    const yEl = modal.querySelector("#trigw-y");
    if (!xEl.value && xEl.value !== "0") { xEl.focus(); return; }
    if (!yEl.value && yEl.value !== "0") { yEl.focus(); return; }

    state.x = parseInt(xEl.value, 10);
    state.y = parseInt(yEl.value, 10);
    state.elevation = parseInt(modal.querySelector("#trigw-elev").value, 10);
    state.noGating = noGateCheck.checked;

    if (state.noGating) {
      state.var = "0";
      state.var_value = "0";
    } else {
      state.var = modal.querySelector("#trigw-var").value || "VAR_TEMP_1";
      state.var_value = modal.querySelector("#trigw-val").value || "0";
    }

    showStep2(modal, mapName, state, onCreated, close);
  });
}

// ---------------------------------------------------------------------------
// Step 2: Script Template
// ---------------------------------------------------------------------------

function showStep2(modal, mapName, state, onCreated, close) {
  const autoLabel = `${mapName}_Trigger_${state.x}_${state.y}`;

  modal.innerHTML = `
    <div class="trigw-header">
      <span class="trigw-title">Create Trigger</span>
      <button class="trigw-close" data-action="close">&times;</button>
    </div>
    <div class="trigw-body">
      <div class="trigw-step-label">Step 2 of 3 -- Script Template</div>

      <div class="trigw-field">
        <label class="trigw-label">Script Label</label>
        <input type="text" id="trigw-label" class="trigw-input"
          value="${esc(state.script_label || autoLabel)}"
          placeholder="${esc(autoLabel)}">
        <span class="trigw-hint">Auto-generated if left blank</span>
      </div>

      <div class="trigw-field">
        <label class="trigw-label" style="margin-bottom:0.35rem">Template</label>
        <div class="trigw-template-list" id="trigw-tpl-list">
          ${state.templates.map(t => `
            <div class="trigw-template-btn${t.id === state.template ? " selected" : ""}"
                 data-tpl="${esc(t.id)}">
              <div>
                <div class="trigw-template-name">${esc(t.name)}</div>
                <div class="trigw-template-desc">${esc(t.description)}</div>
              </div>
            </div>
          `).join("")}
        </div>
      </div>

      <div class="trigw-actions">
        <button class="trigw-btn-back" id="trigw-back2">Back</button>
        <button class="trigw-btn-next" id="trigw-next2">Next</button>
      </div>
    </div>
  `;

  modal.querySelector('.trigw-close').addEventListener("click", close);

  // Template selection
  let selectedTpl = state.template;
  modal.querySelectorAll(".trigw-template-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      modal.querySelectorAll(".trigw-template-btn").forEach(b => b.classList.remove("selected"));
      btn.classList.add("selected");
      selectedTpl = btn.dataset.tpl;
    });
  });

  modal.querySelector("#trigw-back2").addEventListener("click", () => {
    showStep1(modal, mapName, state, onCreated, close);
  });

  modal.querySelector("#trigw-next2").addEventListener("click", () => {
    state.script_label = modal.querySelector("#trigw-label").value.trim();
    state.template = selectedTpl;
    showStep3(modal, mapName, state, onCreated, close);
  });
}

// ---------------------------------------------------------------------------
// Step 3: Confirm
// ---------------------------------------------------------------------------

function showStep3(modal, mapName, state, onCreated, close) {
  const label = state.script_label || `${mapName}_Trigger_${state.x}_${state.y}`;
  const tplMeta = state.templates.find(t => t.id === state.template) || { name: state.template };
  const gateText = state.noGating
    ? "None (always fires)"
    : `${state.var} == ${state.var_value}`;

  modal.innerHTML = `
    <div class="trigw-header">
      <span class="trigw-title">Create Trigger</span>
      <button class="trigw-close" data-action="close">&times;</button>
    </div>
    <div class="trigw-body">
      <div class="trigw-step-label">Step 3 of 3 -- Confirm</div>

      <div class="trigw-summary">
        <div><span class="trigw-summary-label">Position</span> (${state.x}, ${state.y})</div>
        <div><span class="trigw-summary-label">Elevation</span> ${state.elevation}${state.elevation === 0 ? " (any)" : ""}</div>
        <div><span class="trigw-summary-label">Gating</span> ${esc(gateText)}</div>
        <div><span class="trigw-summary-label">Template</span> ${esc(tplMeta.name)}</div>
        <div><span class="trigw-summary-label">Script</span> <code style="font-size:0.78rem">${esc(label)}</code></div>
      </div>

      <div id="trigw-error-area"></div>

      <div class="trigw-actions">
        <button class="trigw-btn-back" id="trigw-back3">Back</button>
        <button class="trigw-btn-create" id="trigw-create">Create Trigger</button>
      </div>
    </div>
  `;

  modal.querySelector('.trigw-close').addEventListener("click", close);

  modal.querySelector("#trigw-back3").addEventListener("click", () => {
    showStep2(modal, mapName, state, onCreated, close);
  });

  const createBtn = modal.querySelector("#trigw-create");
  createBtn.addEventListener("click", async () => {
    createBtn.disabled = true;
    createBtn.textContent = "Creating...";

    const body = {
      x: state.x,
      y: state.y,
      elevation: state.elevation,
      var: state.var,
      var_value: state.var_value,
      template: state.template,
    };
    if (state.script_label) {
      body.script_label = state.script_label;
    }

    try {
      const res = await postApi(`/map/${encodeURIComponent(mapName)}/triggers`, body);
      if (res?.ok) {
        close();
        if (onCreated) onCreated(res.data);
      } else {
        const errArea = modal.querySelector("#trigw-error-area");
        errArea.innerHTML = `<div class="trigw-error">${esc(res?.error || "Failed to create trigger")}</div>`;
        createBtn.disabled = false;
        createBtn.textContent = "Create Trigger";
      }
    } catch (err) {
      const errArea = modal.querySelector("#trigw-error-area");
      errArea.innerHTML = `<div class="trigw-error">Network error</div>`;
      createBtn.disabled = false;
      createBtn.textContent = "Create Trigger";
    }
  });
}
