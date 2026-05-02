/**
 * branch.js — Branch group editor for conditional blocks.
 *
 * Displays when a branch header (BRN) is selected in the beat list.
 * Shows the branch structure with tabs for each outcome, condition
 * details per branch, and add/delete branch actions.
 */

export function render(bodyEl, beat, helpers) {
  // beat here is the opening condition beat of the group.
  // We need the branch group data from the beat list module.
  // Since editors don't have direct access to branch groups,
  // we render based on the condition beat's data.
  const data = beat.data || {};
  const rawCond = data.raw_condition || data.condition || "";
  const branch = data.branch || "if";

  const title = _humanTitle(rawCond);

  bodyEl.innerHTML = `
    <div style="margin-bottom:12px;">
      <div style="font-size:14px;font-weight:bold;color:#f8d030;margin-bottom:8px;">
        Branch: ${_esc(title)}
      </div>
      <div style="font-size:12px;color:var(--text-secondary, #aaa);margin-bottom:12px;">
        This is a conditional branch point. Use the tabs in the beat list
        to switch between outcomes. Each tab shows the beats that execute
        when that condition is met.
      </div>
    </div>
    <div style="margin-bottom:8px;">
      <span style="font-size:11px;color:var(--text-dim, #666);text-transform:uppercase;">Condition</span>
      <div style="font-family:monospace;font-size:13px;color:var(--text-primary, #ddd);padding:6px 8px;background:rgba(0,0,0,0.2);border-radius:4px;margin-top:4px;">
        ${branch} ${_esc(rawCond)}
      </div>
    </div>
    <div style="font-size:11px;color:var(--text-dim, #666);margin-top:12px;">
      Tip: Click the branch tabs in the beat list to view each outcome.
      Edit individual beats within each branch by selecting them.
    </div>
  `;

  return {
    apply() {
      // Branch headers are read-only for now — editing happens
      // via the condition editor on individual if/elif beats
      return null;
    },
  };
}

function _humanTitle(cond) {
  if (cond.includes("== MALE") || cond.includes("== FEMALE")) return "Gender Check";
  if (cond.includes("== YES") || cond.includes("== NO")) return "Yes/No Check";
  if (cond.match(/FLAG_/)) return "Flag Check";
  if (cond.match(/VAR_/)) return "Variable Check";
  if (cond.match(/defeated/i)) return "Trainer Check";
  return "Condition";
}

function _esc(s) {
  if (!s) return "";
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
