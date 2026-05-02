/**
 * give.js — Editor for give beats (give item to player).
 */

import { api } from "../../../app.js";

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  const currentItem = data.item || "";
  const currentQty = data.quantity || "1";

  bodyEl.innerHTML = `
    ${helpers.field("Item", helpers.buildSearchPicker("viz-give-item", [], currentItem))}
    ${helpers.field("Quantity", `<input type="number" id="viz-give-qty" class="viz-ed-input" min="1" max="999" value="${helpers.esc(currentQty)}" />`)}
    <p class="viz-editor-info">Gives the specified item to the player. The game shows a fanfare and "obtained" message automatically.</p>
  `;

  // Try to load items from API (may not exist yet)
  api("/data/items").then(res => {
    if (res && res.ok && res.data && res.data.items) {
      helpers.attachSearchPicker(bodyEl, "viz-give-item", res.data.items);
    }
  }).catch(() => {});

  return {
    apply() {
      const itemInput = bodyEl.querySelector("#viz-give-item");
      const qtyInput = bodyEl.querySelector("#viz-give-qty");
      const item = itemInput ? itemInput.value.trim() : "";
      const qty = qtyInput ? qtyInput.value.trim() : "1";
      if (!item) return null;
      return qty === "1" ? `give ${item}` : `give ${item} ${qty}`;
    },
  };
}
