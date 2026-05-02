/**
 * fade.js — Fade type editor with visual swatch grid.
 */

const FADE_TYPES = [
  { value: "to_black",   label: "Fade to Black",  bg: "#000" },
  { value: "from_black", label: "From Black",      bg: "linear-gradient(to right, #000, #666)" },
  { value: "to_white",   label: "Fade to White",   bg: "#fff" },
  { value: "from_white", label: "From White",       bg: "linear-gradient(to right, #fff, #ccc)" },
];

export function render(bodyEl, beat, helpers) {
  const data = beat.data || {};
  const current = data.fade_type || data.direction || "to_black";

  const buttons = FADE_TYPES.map(ft => {
    const active = ft.value === current ? " active" : "";
    const border = ft.value.includes("white") ? "border:1px solid #555;" : "";
    return `<button class="viz-fade-btn${active}" data-fade="${ft.value}">
      <div class="viz-fade-swatch" style="background:${ft.bg};${border}"></div>
      <span>${helpers.esc(ft.label)}</span>
    </button>`;
  }).join("");

  bodyEl.innerHTML = `
    ${helpers.field("Fade Type", `<div class="viz-fade-grid">${buttons}</div>`)}
  `;

  // Wire click handlers
  const grid = bodyEl.querySelector(".viz-fade-grid");
  grid.addEventListener("click", e => {
    const btn = e.target.closest(".viz-fade-btn");
    if (!btn) return;
    grid.querySelectorAll(".viz-fade-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
  });

  return {
    apply() {
      const active = grid.querySelector(".viz-fade-btn.active");
      return active ? `fade ${active.dataset.fade}` : "fade to_black";
    }
  };
}
