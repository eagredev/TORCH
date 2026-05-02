/**
 * check.js — Game state check editor.
 *
 * Supports: check item, check partysize, check money, check badge.
 * Result stored in VAR_RESULT for subsequent if blocks.
 */

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  const currentType = data.check_type || "item";
  const currentArg = data.argument || "";

  const CHECK_TYPES = [
    { value: "item", label: "Has Item", argLabel: "Item", placeholder: "ITEM_POTION" },
    { value: "partysize", label: "Party Size", argLabel: null, placeholder: null },
    { value: "money", label: "Has Money", argLabel: "Amount", placeholder: "500" },
    { value: "badge", label: "Has Badge", argLabel: "Badge #", placeholder: "1" },
  ];

  bodyEl.innerHTML = `
    ${helpers.field("Check Type", `
      <select id="check-type" class="viz-ed-select">
        ${CHECK_TYPES.map(ct =>
          `<option value="${ct.value}" ${ct.value === currentType ? "selected" : ""}>${ct.label}</option>`
        ).join("")}
      </select>
    `)}
    <div id="check-arg-field"></div>
    <p class="viz-simple-tip">Result is stored in VAR_RESULT. Follow with an if/endif block to act on it.</p>
  `;

  const typeSelect = bodyEl.querySelector("#check-type");
  const argField = bodyEl.querySelector("#check-arg-field");

  function renderArgField() {
    const ct = CHECK_TYPES.find(c => c.value === typeSelect.value);
    if (!ct || !ct.argLabel) {
      argField.innerHTML = "";
      return;
    }
    argField.innerHTML = helpers.field(ct.argLabel, `
      <input type="text" id="check-arg" class="viz-editor-input"
             value="${helpers.esc(currentType === ct.value ? currentArg : "")}"
             placeholder="${ct.placeholder || ""}">
    `);
  }

  typeSelect.addEventListener("change", renderArgField);
  renderArgField();

  return {
    apply() {
      const ct = typeSelect.value;
      if (ct === "partysize") return "check partysize";
      const argEl = bodyEl.querySelector("#check-arg");
      const arg = argEl ? argEl.value.trim() : "";
      if (!arg) return null;
      return `check ${ct} ${arg}`;
    }
  };
}
