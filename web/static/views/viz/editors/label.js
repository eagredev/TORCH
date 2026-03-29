/**
 * label.js — Label name editor with validation.
 */

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  const currentName = data.name || data.label || "";

  bodyEl.innerHTML = `
    ${helpers.field("Label Name", `
      <input type="text" id="label-name" class="viz-editor-input" value="${helpers.esc(currentName)}" placeholder="SectionName">
      <p class="viz-editor-info">Alphanumeric and underscores only, no spaces.</p>
    `)}
  `;

  return {
    apply() {
      const name = bodyEl.querySelector("#label-name").value.trim();
      if (!name || /\s/.test(name)) return null;
      return `label ${name}`;
    }
  };
}
