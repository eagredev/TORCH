/**
 * pause.js — Pause duration editor with GBA frame info.
 */

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  const currentDuration = data.duration || "30";

  bodyEl.innerHTML = `
    ${helpers.field("Duration (frames)", `
      <input type="number" id="pause-duration" class="viz-editor-input" min="1" max="999" value="${helpers.esc(String(currentDuration))}">
      <p class="viz-editor-info">60 frames ≈ 1 second on GBA</p>
    `)}
  `;

  return {
    apply() {
      const dur = parseInt(bodyEl.querySelector("#pause-duration").value, 10);
      if (isNaN(dur) || dur < 1) return null;
      return `pause ${dur}`;
    }
  };
}
