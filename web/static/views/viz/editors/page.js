/**
 * page.js — NPC Page beat editor.
 *
 * Edits: page N [if CONDITION]
 * Page 1 = unconditional default. Page 2+ requires a condition.
 * Uses the shared conditionBuilder component for point-and-click condition editing.
 */

import { api } from "../../../app.js";
import { state } from "../state.js";
import { renderConditionBuilder, injectConditionBuilderCSS } from "../../../conditionBuilder.js";

export function render(bodyEl, beat, helpers) {
  injectConditionBuilderCSS();

  const data = beat.data || {};
  const currentNum  = data.page_num  || 1;
  const currentCond = data.condition || "";

  bodyEl.innerHTML = `
    ${helpers.field("Page Number", `
      <input type="number" id="page-num" class="viz-editor-input"
             value="${currentNum}" min="1" step="1" style="width:4rem">
    `)}
    <div id="page-cond-field"></div>
    <p class="viz-simple-tip" id="page-tip"></p>
  `;

  const numInput = bodyEl.querySelector("#page-num");
  const condField = bodyEl.querySelector("#page-cond-field");
  const tipEl     = bodyEl.querySelector("#page-tip");
  let _builder    = null;

  function updateCondField() {
    const num = parseInt(numInput.value, 10) || 1;
    if (num === 1) {
      condField.innerHTML = `<p class="viz-simple-desc">Page 1 is the unconditional default — no condition needed.</p>`;
      tipEl.textContent = "This page shows when no other page's conditions are met.";
      _builder = null;
    } else {
      condField.innerHTML = `
        <div class="viz-editor-field">
          <label>Condition</label>
          <div id="page-cond-mount"></div>
        </div>
      `;
      const mountEl = condField.querySelector("#page-cond-mount");
      _builder = renderConditionBuilder(mountEl, currentCond, api, "pg", state.mapName || "");
      tipEl.textContent = "Higher page numbers are checked first. Use flag, variable, or defeated conditions.";
    }
  }

  numInput.addEventListener("input", updateCondField);
  updateCondField();

  return {
    apply() {
      const num = parseInt(numInput.value, 10);
      if (!num || num < 1) return null;
      if (num === 1) return "page 1";
      if (!_builder) return null;
      const cond = _builder.apply();
      if (!cond) return null;
      return `page ${num} if ${cond}`;
    }
  };
}
