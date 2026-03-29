/** Shared utilities for TORCH Web GUI. */

/** HTML-escape a string for safe innerHTML/attribute insertion. */
export function esc(s) {
  const d = document.createElement("div");
  d.textContent = String(s ?? "");
  return d.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/** Create a modal with backdrop click-to-close and Escape key support. */
export function createModal(className, innerHtml) {
  const backdrop = document.createElement("div");
  backdrop.className = className + "-backdrop";
  backdrop.innerHTML = `<div class="${className}">${innerHtml}</div>`;
  document.body.appendChild(backdrop);
  const close = () => { document.removeEventListener("keydown", onEsc); backdrop.remove(); };
  function onEsc(e) { if (e.key === "Escape") close(); }
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
  document.addEventListener("keydown", onEsc);
  return { el: backdrop.querySelector(`.${className}`), close };
}

/** Safely unwrap API response envelope. Returns null on error. */
export function unwrap(resp, key) {
  if (!resp || resp.ok === false) return null;
  return resp.data?.[key] ?? resp[key] ?? null;
}
