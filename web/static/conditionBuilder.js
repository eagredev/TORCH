/**
 * TORCH IDE — Shared Condition Builder Component.
 * TORCH_MODULE
 *
 * Reusable point-and-click condition editor for flag/var/defeated conditions.
 * Used by: page beat editor, condition (if/elif) beat editor.
 *
 * Usage:
 *   import { renderConditionBuilder, parseConditionString } from "./conditionBuilder.js";
 *
 *   // Render into a container element, returns { apply() → raw condition string | null }
 *   const builder = renderConditionBuilder(containerEl, initialCondStr, apiFunc);
 *
 *   // Later:
 *   const condStr = builder.apply();  // e.g. "FLAG_BEAT_GYM_1" or "VAR_STORY >= 5"
 */

import { esc } from "./utils.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CONDITION_TYPES = [
  { value: "flag",     label: "Flag" },
  { value: "var",      label: "Variable" },
  { value: "defeated", label: "Defeated Trainer" },
];

const OPERATORS = ["==", "!=", ">", "<", ">=", "<="];

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Render a condition builder into `containerEl`.
 *
 * @param {HTMLElement} containerEl - Target container (innerHTML will be replaced)
 * @param {string}      initialCond - Existing raw condition string (may be empty)
 * @param {Function}    apiFn       - The `api(path)` function from app.js
 * @param {string}      [idPrefix]  - Optional prefix for element IDs (default "cb")
 * @param {string}      [mapName]   - Current map name for on-map trainer suggestions
 *
 * @returns {{ apply(): string|null }}
 *   apply() returns the built raw condition string, or null if incomplete.
 */
export function renderConditionBuilder(containerEl, initialCond, apiFn, idPrefix = "cb", mapName = "") {
  const parsed = parseConditionString(initialCond || "");
  const p = idPrefix;

  containerEl.innerHTML = `
    <div class="cond-builder">
      <div class="cond-builder-row">
        <label class="cond-builder-label">Type</label>
        <select id="${p}-type" class="cond-builder-select">
          ${CONDITION_TYPES.map(ct =>
            `<option value="${ct.value}" ${ct.value === parsed.type ? "selected" : ""}>${ct.label}</option>`
          ).join("")}
        </select>
      </div>
      <div id="${p}-fields"></div>
    </div>
  `;

  const typeSelect = containerEl.querySelector(`#${p}-type`);
  const fieldsDiv  = containerEl.querySelector(`#${p}-fields`);

  function renderFields() {
    const ct = typeSelect.value;
    if (ct === "flag") {
      fieldsDiv.innerHTML = `
        <div class="cond-builder-row">
          <label class="cond-builder-label">Flag</label>
          <div class="cond-search-wrap">
            <input type="text" id="${p}-flag" class="cond-builder-input" autocomplete="off"
                   value="${esc(parsed.flag || "")}" placeholder="FLAG_...">
            <div class="cond-search-dropdown" id="${p}-flag-drop"></div>
          </div>
        </div>
        <div class="cond-builder-row">
          <label class="cond-builder-label"></label>
          <label class="cond-builder-checkbox">
            <input type="checkbox" id="${p}-negate" ${parsed.negated ? "checked" : ""}>
            NOT (flag is cleared / false)
          </label>
        </div>
      `;
      apiFn("/data/flags").then(res => {
        if (res.ok && res.data && res.data.flags) {
          const items = res.data.flags.map(f => f.const || f.display || f);
          _attachPicker(containerEl, `${p}-flag`, `${p}-flag-drop`, items);
        }
      });
    } else if (ct === "var") {
      fieldsDiv.innerHTML = `
        <div class="cond-builder-row">
          <label class="cond-builder-label">Variable</label>
          <div class="cond-search-wrap">
            <input type="text" id="${p}-var" class="cond-builder-input" autocomplete="off"
                   value="${esc(parsed.varName || "")}" placeholder="VAR_...">
            <div class="cond-search-dropdown" id="${p}-var-drop"></div>
          </div>
        </div>
        <div class="cond-builder-row">
          <label class="cond-builder-label">Operator</label>
          <select id="${p}-op" class="cond-builder-select">
            ${OPERATORS.map(op =>
              `<option value="${op}" ${op === (parsed.op || "==") ? "selected" : ""}>${op}</option>`
            ).join("")}
          </select>
        </div>
        <div class="cond-builder-row">
          <label class="cond-builder-label">Value</label>
          <input type="text" id="${p}-val" class="cond-builder-input"
                 value="${esc(parsed.value || "")}" placeholder="0">
        </div>
      `;
      apiFn("/vars").then(res => {
        if (res.ok && res.data && res.data.vars) {
          const items = res.data.vars.map(v => v.name || v);
          _attachPicker(containerEl, `${p}-var`, `${p}-var-drop`, items);
        }
      });
    } else if (ct === "defeated") {
      fieldsDiv.innerHTML = `
        <div class="cond-builder-row">
          <label class="cond-builder-label">Trainer</label>
          <input type="text" id="${p}-trainer" class="cond-builder-input" autocomplete="off"
                 value="${esc(parsed.trainer || "")}" placeholder="Search trainers...">
        </div>
        <div class="cond-trainer-list" id="${p}-trainer-list"></div>
      `;

      const input   = fieldsDiv.querySelector(`#${p}-trainer`);
      const listEl  = fieldsDiv.querySelector(`#${p}-trainer-list`);

      function trainerLabel(t) {
        return t.replace(/^TRAINER_/, "").replace(/_/g, " ").toLowerCase()
          .replace(/\b\w/g, c => c.toUpperCase());
      }

      function renderList(onMap, all, filter) {
        const lower = filter.toLowerCase().trim();
        const onMapSet = new Set(onMap);
        let items;

        if (!lower) {
          items = onMap.length
            ? onMap.map(t => ({ t, badge: true }))
            : all.slice(0, 20).map(t => ({ t, badge: false }));
        } else {
          const matched = all.filter(t => t.toLowerCase().includes(lower));
          const onMapHits = matched.filter(t => onMapSet.has(t));
          const rest = matched.filter(t => !onMapSet.has(t));
          items = [
            ...onMapHits.map(t => ({ t, badge: true })),
            ...rest.map(t => ({ t, badge: false })),
          ].slice(0, 25);
        }

        if (!items.length) {
          listEl.innerHTML = `<div class="cond-trainer-empty">No trainers found</div>`;
        } else {
          listEl.innerHTML = items.map(({ t, badge }) => {
            const label = trainerLabel(t);
            const badgeHtml = badge ? `<span class="cond-trainer-badge">map</span>` : "";
            return `<div class="cond-trainer-row${input.value === t ? " cond-trainer-row-active" : ""}" data-value="${esc(t)}">
              <div class="cond-trainer-item-name">${esc(label)}${badgeHtml}</div>
              <div class="cond-trainer-item-const">${esc(t)}</div>
            </div>`;
          }).join("");
          listEl.querySelectorAll(".cond-trainer-row").forEach(el => {
            el.addEventListener("mousedown", e => {
              e.preventDefault(); // keep focus on input
              input.value = el.dataset.value;
              // Highlight selected row
              listEl.querySelectorAll(".cond-trainer-row").forEach(r => r.classList.remove("cond-trainer-row-active"));
              el.classList.add("cond-trainer-row-active");
            });
          });
        }
      }

      const onMapPromise = mapName
        ? apiFn(`/map/${encodeURIComponent(mapName)}/trainers`).then(r => r.ok ? r.data.trainers || [] : [])
        : Promise.resolve([]);
      const allPromise = apiFn("/trainers/ref").then(r =>
        r.ok && r.data ? (r.data.trainers || []).map(t => t.const || t) : []
      );

      Promise.all([onMapPromise, allPromise]).then(([onMap, all]) => {
        renderList(onMap, all, input.value);
        let timer = null;
        input.addEventListener("input", () => {
          clearTimeout(timer);
          timer = setTimeout(() => renderList(onMap, all, input.value), 80);
        });
      });
    }
  }

  typeSelect.addEventListener("change", renderFields);
  renderFields();

  return {
    apply() {
      const ct = typeSelect.value;
      if (ct === "flag") {
        const flagEl = containerEl.querySelector(`#${p}-flag`);
        const flag = flagEl ? flagEl.value.trim() : "";
        if (!flag) return null;
        const neg = containerEl.querySelector(`#${p}-negate`);
        return (neg && neg.checked ? "not " : "") + flag;
      } else if (ct === "var") {
        const varEl  = containerEl.querySelector(`#${p}-var`);
        const varName = varEl ? varEl.value.trim() : "";
        const op   = containerEl.querySelector(`#${p}-op`).value;
        const val  = containerEl.querySelector(`#${p}-val`).value.trim();
        if (!varName || val === "") return null;
        return `${varName} ${op} ${val}`;
      } else if (ct === "defeated") {
        const trEl = containerEl.querySelector(`#${p}-trainer`);
        const trainer = trEl ? trEl.value.trim() : "";
        if (!trainer) return null;
        return `defeated ${trainer}`;
      }
      return null;
    }
  };
}

// ---------------------------------------------------------------------------
// Condition string parser
// ---------------------------------------------------------------------------

/**
 * Parse a raw TorScript condition string into structured fields.
 * Returns an object usable for pre-filling the builder UI.
 *
 * Handles single conditions only (not compound and/or — use raw text for those).
 */
export function parseConditionString(raw) {
  const result = {
    type: "flag",
    flag: "", negated: false,
    varName: "", op: "==", value: "",
    trainer: "",
  };
  if (!raw || !raw.trim()) return result;

  const parts = raw.trim().split(/\s+/);
  if (!parts.length) return result;

  let idx = 0;
  if (parts[0] === "not") {
    result.negated = true;
    idx = 1;
  }

  if (parts[idx] === "defeated") {
    result.type = "defeated";
    result.trainer = parts[idx + 1] || "";
    return result;
  }

  const name = parts[idx] || "";

  if (name.startsWith("VAR_") && parts.length > idx + 2 && OPERATORS.includes(parts[idx + 1])) {
    result.type = "var";
    result.varName = name;
    result.op = parts[idx + 1];
    result.value = parts[idx + 2] || "";
    return result;
  }

  // FLAG_* or VAR_* treated as flag truthiness check, or any bare token
  result.type = "flag";
  result.flag = name || raw.trim();
  return result;
}

// ---------------------------------------------------------------------------
// CSS injection
// ---------------------------------------------------------------------------

let _cssInjected = false;

export function injectConditionBuilderCSS() {
  if (_cssInjected) return;
  _cssInjected = true;
  const style = document.createElement("style");
  style.textContent = `
.cond-builder {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.cond-builder-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.cond-builder-label {
  min-width: 4.5rem;
  font-size: 0.75rem;
  color: var(--text-secondary, #aaa);
  flex-shrink: 0;
}
.cond-builder-select, .cond-builder-input {
  flex: 1;
  padding: 2px 5px;
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 3px;
  background: var(--bg-secondary, #111);
  color: var(--text-primary, #eee);
  font-size: 0.75rem;
}
.cond-builder-checkbox {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.75rem;
  color: var(--text-secondary, #aaa);
  cursor: pointer;
}
.cond-search-wrap {
  position: relative;
  flex: 1;
}
.cond-search-wrap input {
  width: 100%;
  box-sizing: border-box;
}
.cond-search-dropdown {
  display: none;
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: var(--bg-secondary, #1a1a2e);
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 3px;
  max-height: 160px;
  overflow-y: auto;
  z-index: 999;
  font-size: 0.72rem;
}
.cond-search-item {
  padding: 3px 6px;
  cursor: pointer;
  color: var(--text-primary, #eee);
}
.cond-search-item:hover {
  background: var(--accent, #4a9eff);
  color: #111;
}
/* Trainer in-flow list */
.cond-trainer-list {
  margin-top: 0.25rem;
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 4px;
  overflow: hidden;
}
.cond-trainer-row {
  padding: 5px 8px;
  cursor: pointer;
  border-bottom: 1px solid rgba(255,255,255,0.05);
}
.cond-trainer-row:last-child { border-bottom: none; }
.cond-trainer-row:hover { background: var(--accent-bg-subtle, rgba(74,158,255,0.12)); }
.cond-trainer-row-active { background: var(--accent-bg-medium, rgba(74,158,255,0.22)) !important; }
.cond-trainer-item-name {
  font-weight: 600;
  font-size: 0.78rem;
  color: var(--text-primary, #eee);
  display: flex;
  align-items: center;
  gap: 0.3rem;
}
.cond-trainer-item-const {
  font-size: 0.63rem;
  font-family: monospace;
  color: var(--text-dim, #888);
  margin-top: 1px;
}
.cond-trainer-empty {
  padding: 8px;
  font-size: 0.72rem;
  color: var(--text-dim, #666);
  font-style: italic;
  text-align: center;
}
.cond-trainer-badge {
  font-size: 0.58rem;
  padding: 1px 4px;
  border-radius: 3px;
  background: rgba(74,158,255,0.2);
  color: var(--accent, #4a9eff);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
  `;
  document.head.appendChild(style);
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Two-tier trainer picker.
 * Empty input or focus → show on-map section (if any) + top game-wide results.
 * Typing → filter game-wide list, with on-map matches promoted to top under their label.
 */
function _attachTrainerPicker(container, inputId, dropId, onMap, all) {
  const input    = container.querySelector(`#${inputId}`);
  const dropdown = container.querySelector(`#${dropId}`);
  if (!input || !dropdown) return;

  const onMapSet = new Set(onMap);

  function trainerLabel(t) {
    return t.replace(/^TRAINER_/, "").replace(/_/g, " ").toLowerCase()
      .replace(/\b\w/g, c => c.toUpperCase());
  }

  function renderItem(t, badge) {
    const label = trainerLabel(t);
    const badgeHtml = badge ? `<span class="cond-trainer-badge">${esc(badge)}</span>` : "";
    return `<div class="cond-search-item" data-value="${esc(t)}">${esc(label)}${badgeHtml}<span class="cond-trainer-const">${esc(t)}</span></div>`;
  }

  function show(filter) {
    const lower = (filter || "").toLowerCase();
    let html = "";

    if (!lower) {
      // No input: show on-map group first, then up to 15 game-wide
      if (onMap.length) {
        html += `<div class="cond-search-group">On this map</div>`;
        html += onMap.map(t => renderItem(t, "map")).join("");
        html += `<div class="cond-search-divider"></div>`;
      }
      const others = all.filter(t => !onMapSet.has(t)).slice(0, 15);
      html += others.map(t => renderItem(t, "")).join("");
    } else {
      // Typing: filter everything, promote on-map matches
      const matched = all.filter(t => t.toLowerCase().includes(lower));
      const onMapMatches = matched.filter(t => onMapSet.has(t));
      const rest = matched.filter(t => !onMapSet.has(t)).slice(0, 20);
      if (onMapMatches.length) {
        html += `<div class="cond-search-group">On this map</div>`;
        html += onMapMatches.map(t => renderItem(t, "map")).join("");
        if (rest.length) html += `<div class="cond-search-divider"></div>`;
      }
      html += rest.map(t => renderItem(t, "")).join("");
    }

    dropdown.innerHTML = html || `<div class="cond-search-empty">No trainers found</div>`;
    dropdown.style.display = "block";
  }

  input.addEventListener("input",  () => show(input.value));
  input.addEventListener("focus",  () => show(input.value));
  dropdown.addEventListener("mousedown", e => {
    const el = e.target.closest(".cond-search-item");
    if (el) { input.value = el.dataset.value; dropdown.style.display = "none"; }
  });
  input.addEventListener("blur", () => { setTimeout(() => { dropdown.style.display = "none"; }, 150); });
}

function _attachPicker(container, inputId, dropId, items) {
  const input    = container.querySelector(`#${inputId}`);
  const dropdown = container.querySelector(`#${dropId}`);
  if (!input || !dropdown) return;

  function showMatches(filter) {
    const lower = (filter || "").toLowerCase();
    const matches = lower
      ? items.filter(it => it.toLowerCase().includes(lower)).slice(0, 25)
      : items.slice(0, 25);
    dropdown.innerHTML = matches.map(m =>
      `<div class="cond-search-item" data-value="${esc(m)}">${esc(m)}</div>`
    ).join("");
    dropdown.style.display = matches.length ? "block" : "none";
  }

  input.addEventListener("input", () => showMatches(input.value));
  input.addEventListener("focus", () => showMatches(input.value));
  dropdown.addEventListener("mousedown", e => {
    const el = e.target.closest(".cond-search-item");
    if (el) {
      input.value = el.dataset.value;
      dropdown.style.display = "none";
    }
  });
  input.addEventListener("blur", () => {
    setTimeout(() => { dropdown.style.display = "none"; }, 150);
  });
}
