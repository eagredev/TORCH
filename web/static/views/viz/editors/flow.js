/**
 * flow.js — Flow control editor (goto, call, end, release, return).
 */

const FLOW_TYPES = ["goto", "call", "end", "release", "return"];
const NEEDS_LABEL = new Set(["goto", "call"]);

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};

  // Determine current flow type from data or source line
  let currentType = "goto";
  if (data.flow_type) {
    currentType = data.flow_type;
  } else if (data.label || data.target) {
    // Has a label target — must be goto or call
    currentType = "goto";
  } else {
    // Try to detect from source: end, release, return have no label
    for (const ft of ["end", "release", "return", "goto", "call"]) {
      if (data[ft] !== undefined || data.type === ft) {
        currentType = ft;
        break;
      }
    }
  }

  const currentLabel = data.label || data.target || "";

  const options = FLOW_TYPES.map(ft =>
    `<option value="${ft}" ${ft === currentType ? "selected" : ""}>${ft}</option>`
  ).join("");

  // Use search picker for labels so users can type custom names too
  const labels = helpers.getLabelNames();

  bodyEl.innerHTML = `
    ${helpers.field("Flow Type", `
      <select id="flow-type" class="viz-editor-select">${options}</select>
    `)}
    <div id="flow-label-wrapper" style="${NEEDS_LABEL.has(currentType) ? "" : "display:none"}">
      ${helpers.field("Target Label", helpers.buildSearchPicker("flow-label", labels, currentLabel))}
    </div>
  `;

  // Attach the search picker with label items
  helpers.attachSearchPicker(bodyEl, "flow-label", labels);

  // Toggle label visibility on type change
  const typeSelect = bodyEl.querySelector("#flow-type");
  const labelWrapper = bodyEl.querySelector("#flow-label-wrapper");
  typeSelect.addEventListener("change", () => {
    labelWrapper.style.display = NEEDS_LABEL.has(typeSelect.value) ? "" : "none";
  });

  return {
    apply() {
      const flowType = typeSelect.value;
      if (NEEDS_LABEL.has(flowType)) {
        const labelInput = bodyEl.querySelector("#flow-label");
        const label = labelInput ? labelInput.value.trim() : "";
        if (!label) return null;
        return `${flowType} ${label}`;
      }
      return flowType;
    }
  };
}
