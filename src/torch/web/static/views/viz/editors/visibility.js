/**
 * visibility.js — Editor for hide/show beats (actor visibility toggle).
 */

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  const currentActor = data.actor || "player";
  const isShow = beat.type === "show";

  bodyEl.innerHTML = `
    ${helpers.field("Actor", helpers.buildActorSelect("viz-vis-actor", currentActor))}
    ${helpers.field("Action", `
      <select id="viz-vis-action" class="viz-ed-select">
        <option value="show" ${isShow ? "selected" : ""}>Show (make visible)</option>
        <option value="hide" ${!isShow ? "selected" : ""}>Hide (make invisible)</option>
      </select>
    `)}
    <p class="viz-editor-info">${isShow
      ? "Makes the actor visible on the map. Use after a previous hide."
      : "Makes the actor invisible. They remain at their position but cannot be seen or interacted with."
    }</p>
  `;

  return {
    apply() {
      const actor = bodyEl.querySelector("#viz-vis-actor").value;
      const action = bodyEl.querySelector("#viz-vis-action").value;
      return `${action} ${actor}`;
    },
  };
}
