/**
 * TORCH Web GUI — Metatile Layer Editor (redirect shim).
 * Redirects to the new Tileset Editor at /tilesets.
 * Preserves backward compatibility with /metatiles/<name> URLs from the asset browser.
 */

export async function render(container) {
  const hash = window.location.hash || "";
  const match = hash.match(/^#\/metatiles\/(.+)$/);
  if (match) {
    // Redirect to new tileset editor
    window.location.hash = `#/tilesets/${match[1]}`;
    return;
  }
  // Fallback: load the tileset editor directly
  const mod = await import("./tilesets.js");
  return mod.render(container);
}

export function cleanup() {
  // Delegate to tilesets cleanup if it was loaded
}
