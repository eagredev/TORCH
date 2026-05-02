/**
 * condition.js — If/elif/else editor with condition builder.
 *
 * Supports flag checks (with negation), variable comparisons (6 operators),
 * and defeated trainer checks.
 */

import { api } from "../../../app.js";
import { state } from "../state.js";
import { renderConditionBuilder, injectConditionBuilderCSS } from "../../../conditionBuilder.js";

export function render(bodyEl, beat, helpers) {
  injectConditionBuilderCSS();

  const data = beat.data || {};
  const branch = data.branch || "if";
  const rawCond = data.raw_condition || "";

  if (branch === "else") {
    bodyEl.innerHTML = `
      <div class="viz-simple-info">
        <p class="viz-simple-desc">Else branch — runs when no previous if/elif condition matched.</p>
      </div>
    `;
    return { apply() { return "else"; } };
  }

  bodyEl.innerHTML = `
    ${helpers.field("Branch", `
      <select id="cond-branch" class="viz-ed-select">
        <option value="if" ${branch === "if" ? "selected" : ""}>if</option>
        <option value="elif" ${branch === "elif" ? "selected" : ""}>elif</option>
      </select>
    `)}
    <div id="cond-builder-mount"></div>
  `;

  const mountEl = bodyEl.querySelector("#cond-builder-mount");
  const builder = renderConditionBuilder(mountEl, rawCond, api, "cnd", state.mapName || "");

  return {
    apply() {
      const branchVal = bodyEl.querySelector("#cond-branch").value;
      const condStr = builder.apply();
      if (!condStr) return null;
      return `${branchVal} ${condStr}`;
    }
  };
}
