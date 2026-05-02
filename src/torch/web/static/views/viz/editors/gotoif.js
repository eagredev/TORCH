/**
 * gotoif.js — Conditional goto editor (flag picker + label picker).
 */

import { api } from "../../../app.js";

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  const currentFlag = data.condition || data.flag || "";
  const currentLabel = data.label || data.target || "";

  const labels = helpers.getLabelNames();

  bodyEl.innerHTML = `
    ${helpers.field("Flag (condition)", helpers.buildSearchPicker("gotoif-flag", [], currentFlag))}
    ${helpers.field("Target Label", helpers.buildSearchPicker("gotoif-label", labels, currentLabel))}
  `;

  // Load flags asynchronously
  api("/data/flags").then(res => {
    if (res.ok && res.data.flags) {
      const items = res.data.flags.map(f => f.const || f.display);
      helpers.attachSearchPicker(bodyEl, "gotoif-flag", items);
    }
  });

  // Attach label picker immediately with available labels
  helpers.attachSearchPicker(bodyEl, "gotoif-label", labels);

  return {
    apply() {
      const flagInput = bodyEl.querySelector("#gotoif-flag");
      const labelInput = bodyEl.querySelector("#gotoif-label");
      const flag = flagInput ? flagInput.value.trim() : "";
      const label = labelInput ? labelInput.value.trim() : "";
      if (!flag || !label) return null;
      return `gotoif ${flag} ${label}`;
    }
  };
}
