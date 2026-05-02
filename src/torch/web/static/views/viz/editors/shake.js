/**
 * shake.js — Shake editor (raw syntax input).
 */

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  // Reconstruct raw shake text from data fields
  const parts = ["shake"];
  if (data.intensity) parts.push(data.intensity);
  if (data.count) parts.push(data.count);
  const currentText = parts.length > 1 ? parts.join(" ") : "shake";

  bodyEl.innerHTML = `
    ${helpers.field("Shake Command", `
      <input type="text" id="shake-raw" class="viz-editor-input" value="${helpers.esc(currentText)}" placeholder="shake [intensity] [count]">
      <p class="viz-editor-info">Raw shake syntax. Examples: shake, shake 1 2</p>
    `)}
  `;

  return {
    apply() {
      const text = bodyEl.querySelector("#shake-raw").value.trim();
      if (!text) return "shake";
      return text.startsWith("shake") ? text : `shake ${text}`;
    }
  };
}
