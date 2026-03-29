/**
 * flag.js — Flag set/clear editor with searchable picker.
 */

import { api } from "../../../app.js";

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  const currentAction = data.action || "set";
  const currentFlag = data.flag_name || data.flag || "";

  bodyEl.innerHTML = `
    ${helpers.field("Action", `
      <label class="viz-radio-label">
        <input type="radio" name="flag-action" value="set" ${currentAction === "set" ? "checked" : ""}> Set
      </label>
      <label class="viz-radio-label">
        <input type="radio" name="flag-action" value="clear" ${currentAction === "clear" ? "checked" : ""}> Clear
      </label>
    `)}
    ${helpers.field("Flag", helpers.buildSearchPicker("flag-picker", [], currentFlag))}
  `;

  // Load flags asynchronously
  api("/data/flags").then(res => {
    if (res.ok && res.data.flags) {
      const items = res.data.flags.map(f => f.const || f.display);
      helpers.attachSearchPicker(bodyEl, "flag-picker", items);
    }
  });

  return {
    apply() {
      const radios = bodyEl.querySelectorAll('input[name="flag-action"]');
      let action = "set";
      for (const r of radios) {
        if (r.checked) { action = r.value; break; }
      }
      const flagInput = bodyEl.querySelector("#flag-picker");
      const flag = flagInput ? flagInput.value.trim() : "";
      if (!flag) return null;
      return `flag ${action} ${flag}`;
    }
  };
}
