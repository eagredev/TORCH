/**
 * switchcase.js — Editor for switch, case, default, and endswitch beats.
 *
 * switch: variable picker
 * case: value input
 * default/endswitch: info-only
 */

import { api } from "../../../app.js";

export function render(bodyEl, beat, helpers) {
  const btype = beat.type;
  const data = beat.data || {};

  if (btype === "switch") {
    return _renderSwitch(bodyEl, data, helpers);
  } else if (btype === "case") {
    return _renderCase(bodyEl, data, helpers);
  } else if (btype === "endswitch") {
    return _renderEndswitch(bodyEl, helpers);
  }
  // fallback
  return _renderEndswitch(bodyEl, helpers);
}

function _renderSwitch(bodyEl, data, helpers) {
  const currentVar = data.var || "";

  bodyEl.innerHTML = `
    ${helpers.field("Variable", helpers.buildSearchPicker("switch-var", [], currentVar))}
    <p class="viz-simple-tip">Multi-way branch on variable value. Follow with case/default beats.</p>
  `;

  api("/vars").then(res => {
    if (res.ok && res.data.vars) {
      const items = res.data.vars.map(v => v.name);
      helpers.attachSearchPicker(bodyEl, "switch-var", items);
    }
  });

  return {
    apply() {
      const varEl = bodyEl.querySelector("#switch-var");
      const varName = varEl ? varEl.value.trim() : "";
      if (!varName) return null;
      return `switch ${varName}`;
    }
  };
}

function _renderCase(bodyEl, data, helpers) {
  const currentValue = data.value || "";
  const isDefault = currentValue === "default";

  bodyEl.innerHTML = `
    ${helpers.field("Match Value", `
      <input type="text" id="case-value" class="viz-editor-input"
             value="${helpers.esc(isDefault ? "" : currentValue)}"
             placeholder="Number, constant, or leave empty for default">
    `)}
    <div class="viz-editor-field">
      <label><input type="checkbox" id="case-default" ${isDefault ? "checked" : ""}> Default (fallback)</label>
    </div>
  `;

  return {
    apply() {
      const isDefChk = bodyEl.querySelector("#case-default");
      if (isDefChk && isDefChk.checked) return "default";
      const val = bodyEl.querySelector("#case-value").value.trim();
      if (!val) return null;
      return `case ${val}`;
    }
  };
}

function _renderEndswitch(bodyEl, helpers) {
  bodyEl.innerHTML = `
    <div class="viz-simple-info">
      <p class="viz-simple-desc">Closes the switch block.</p>
    </div>
  `;
  return { apply() { return "endswitch"; } };
}
