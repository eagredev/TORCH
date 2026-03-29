/**
 * battle.js — Battle editor (type + raw args).
 */

const BATTLE_TYPES = ["single", "double", "gym", "trainer_hill"];

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  const currentType = data.battle_type || "single";
  const currentArgs = data.args || "";

  const options = BATTLE_TYPES.map(bt =>
    `<option value="${bt}" ${bt === currentType ? "selected" : ""}>${bt}</option>`
  ).join("");

  bodyEl.innerHTML = `
    ${helpers.field("Battle Type", `
      <select id="battle-type" class="viz-editor-select">${options}</select>
    `)}
    ${helpers.field("Arguments", `
      <textarea id="battle-args" class="viz-editor-input" rows="2" placeholder="TRAINER_CONSTANT, optional loss text, optional win text">${helpers.esc(currentArgs)}</textarea>
      <p class="viz-editor-info">Trainer constant, optional loss text, optional win text</p>
    `)}
  `;

  return {
    apply() {
      const btype = bodyEl.querySelector("#battle-type").value;
      const args = bodyEl.querySelector("#battle-args").value.trim();
      if (!args) return null;
      return `battle ${btype} ${args}`;
    }
  };
}
