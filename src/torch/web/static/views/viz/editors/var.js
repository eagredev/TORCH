/**
 * var.js — Variable set/check editor.
 */

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  const currentAction = data.action || "set";
  const currentVar = data.var_name || data.variable || "";
  const currentValue = data.value || "";

  bodyEl.innerHTML = `
    ${helpers.field("Action", `
      <label class="viz-radio-label">
        <input type="radio" name="var-action" value="set" ${currentAction === "set" ? "checked" : ""}> Set
      </label>
      <label class="viz-radio-label">
        <input type="radio" name="var-action" value="check" ${currentAction === "check" ? "checked" : ""}> Check
      </label>
    `)}
    ${helpers.field("Variable Name", `
      <input type="text" id="var-name" class="viz-editor-input" value="${helpers.esc(currentVar)}" placeholder="VAR_0x4001">
    `)}
    ${helpers.field("Value", `
      <input type="text" id="var-value" class="viz-editor-input" value="${helpers.esc(currentValue)}" placeholder="Number or constant">
    `)}
  `;

  return {
    apply() {
      const radios = bodyEl.querySelectorAll('input[name="var-action"]');
      let action = "set";
      for (const r of radios) {
        if (r.checked) { action = r.value; break; }
      }
      const varName = bodyEl.querySelector("#var-name").value.trim();
      const value = bodyEl.querySelector("#var-value").value.trim();
      if (!varName) return null;
      return `var ${action} ${varName}${value ? " " + value : ""}`;
    }
  };
}
