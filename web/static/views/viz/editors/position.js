/**
 * position.js — Editor for setpos beats (instant actor repositioning).
 */

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  const currentActor = data.actor || "player";
  const currentX = data.x || "0";
  const currentY = data.y || "0";

  bodyEl.innerHTML = `
    ${helpers.field("Actor", helpers.buildActorSelect("viz-pos-actor", currentActor))}
    <div class="viz-editor-row">
      ${helpers.field("X", `<input type="number" id="viz-pos-x" class="viz-ed-input" value="${helpers.esc(currentX)}" />`)}
      ${helpers.field("Y", `<input type="number" id="viz-pos-y" class="viz-ed-input" value="${helpers.esc(currentY)}" />`)}
    </div>
    <p class="viz-editor-info">Instantly repositions the actor at the given tile coordinates. No walking animation — they just appear there. Use Move beats for visible movement.</p>
  `;

  return {
    apply() {
      const actor = bodyEl.querySelector("#viz-pos-actor").value;
      const x = bodyEl.querySelector("#viz-pos-x").value.trim();
      const y = bodyEl.querySelector("#viz-pos-y").value.trim();
      if (!x || !y) return null;
      return `setpos ${actor} ${x} ${y}`;
    },
  };
}
