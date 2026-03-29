/**
 * special.js — Special function editor with searchable picker.
 */

import { api } from "../../../app.js";

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  const currentFn = data.function_name || data.name || data.special || "";

  bodyEl.innerHTML = `
    ${helpers.field("Special Function", helpers.buildSearchPicker("special-picker", [], currentFn))}
  `;

  // Load specials asynchronously
  api("/data/specials").then(res => {
    if (res.ok && res.data.specials) {
      const items = res.data.specials.map(s => s.name);
      helpers.attachSearchPicker(bodyEl, "special-picker", items);
    }
  });

  return {
    apply() {
      const input = bodyEl.querySelector("#special-picker");
      const fn = input ? input.value.trim() : "";
      if (!fn) return null;
      return `special ${fn}`;
    }
  };
}
