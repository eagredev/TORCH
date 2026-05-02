/**
 * TORCH Web GUI — Client-side router and API helper.
 */

import { esc } from "./utils.js";
import { initDexPanel, closeDexPanel } from "./dexPanel.js";

// API helpers — exported for use by view modules
export async function api(path) {
  const res = await fetch(`/api${path}`);
  return res.json();
}

export async function postApi(path, body) {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

export async function deleteApi(path) {
  const res = await fetch(`/api${path}`, { method: "DELETE" });
  return res.json();
}

// ---------------------------------------------------------------------------
// Expansion version gating for the web GUI.
// Caches the version from /api/status on first call.
//
// Usage:
//   import { versionGate, getExpansionVersion } from "./app.js";
//   if (await versionGate(1, 14, 0)) { /* show TM/Tutor tab */ }
//   const ver = await getExpansionVersion(); // "1.14.3" or null
// ---------------------------------------------------------------------------

let _expansionVersion = undefined;  // undefined = not fetched, null = vanilla/N/A, [M,m,p] = parsed tuple

/**
 * Fetch and cache the expansion version. Returns the version string or null (vanilla).
 */
export async function getExpansionVersion() {
  if (_expansionVersion !== undefined) {
    return _expansionVersion ? _expansionVersion.str : null;
  }
  try {
    const res = await api("/status");
    if (res.ok) {
      const d = res.data;
      // Prefer pre-parsed tuple from backend
      if (Array.isArray(d.expansion_version_tuple) && d.expansion_version_tuple.length === 3) {
        _expansionVersion = {
          tuple: d.expansion_version_tuple,
          str: d.expansion_version || d.expansion_version_tuple.join("."),
        };
      } else if (d.expansion_version && d.expansion_version !== "N/A") {
        // Fallback: parse the string
        const parts = d.expansion_version.split(".").map(Number);
        if (parts.length === 3 && parts.every(n => Number.isInteger(n))) {
          _expansionVersion = { tuple: parts, str: d.expansion_version };
        } else {
          _expansionVersion = null;
        }
      } else {
        _expansionVersion = null;
      }
    } else {
      _expansionVersion = null;
    }
  } catch (_) {
    _expansionVersion = null;
  }
  return _expansionVersion ? _expansionVersion.str : null;
}

/**
 * Check if the detected expansion version meets a minimum threshold.
 * Returns false for vanilla (no expansion) or on parse failure.
 */
export async function versionGate(major, minor, patch) {
  await getExpansionVersion();
  if (!_expansionVersion) return false;
  const [a, b, c] = _expansionVersion.tuple;
  if (a !== major) return a > major;
  if (b !== minor) return b > minor;
  return c >= patch;
}

/**
 * Clear the cached version. Call when the active project changes.
 */
export function clearVersionCache() {
  _expansionVersion = undefined;
}

// ---------------------------------------------------------------------------
// Global SSE connection — persists across view changes to keep the server
// alive (auto-shutdown watches for disconnected SSE clients).
// ---------------------------------------------------------------------------

let _eventSource = null;

function connectGlobalSSE() {
  if (_eventSource) return;
  _eventSource = new EventSource("/events");
  _eventSource.onerror = () => {
    // Auto-reconnect is built into EventSource; nothing extra needed.
  };
}

/**
 * Get the shared EventSource. Views can call addEventListener on this
 * to react to SSE events without owning the connection lifecycle.
 */
export function getEventSource() {
  if (!_eventSource) connectGlobalSSE();
  return _eventSource;
}

// Open immediately on page load
connectGlobalSSE();

// Route table: hash path -> view module loader
const routes = {
  "/":            () => import("./views/dashboard.js"),
  "/dashboard":   () => import("./views/dashboard.js"),
  "/studio":      () => import("./ide.js"),
  "/dex":         () => import("./views/dex.js"),
  "/encounters":  () => import("./views/encounters.js"),
  "/trainers":    () => import("./views/trainers.js"),
  "/settings":    () => import("./views/settings.js"),
  "/visualizer":  () => import("./views/visualizer.js"),
  "/project":     () => import("./views/project.js"),
  "/scripts":     () => import("./views/scripts.js"),
  "/chains":      () => import("./views/chains.js"),
  "/flags":       () => import("./views/flags.js"),
  "/items":       () => import("./views/items.js"),
  "/moves":       () => import("./views/moves.js"),
  "/shops":       () => import("./views/shops.js"),
  "/learnsets":   () => import("./views/learnsets.js"),
  "/heals":       () => import("./views/heals.js"),
  "/assets":      () => import("./views/assets.js"),
  "/explorer":    () => import("./views/explorer.js"),
  "/scorch":      () => import("./views/scorch.js"),
  "/metatiles":   () => import("./views/metatiles.js"),
  "/tilesets":    () => import("./views/tilesets.js"),
  "/templates":   () => import("./views/templates.js"),
  "/stamp-library": () => import("./views/stampLibrary.js"),
  "/npcs":        () => import("./views/npcs.js"),
  "/versions":    () => import("./views/versions.js"),
  "/music":       () => import("./views/music.js"),
  "/ide":         () => import("./ide.js"),
};

// Resolve current hash to a route key
function currentRoute() {
  const hash = window.location.hash || "#/";
  return hash.slice(1) || "/";
}

// Track current view cleanup function
let currentCleanup = null;

// Render the view for the current route
async function navigate() {
  const route = currentRoute();
  // Match sub-routes: #/dex/SPECIES_X -> /dex view handles it
  const baseRoute = "/" + route.split("/").filter(Boolean)[0];
  const loader = routes[route] || routes[baseRoute] || routes["/"];
  const container = document.getElementById("app");

  // Routes that belong to the Studio family — sidebar highlights "Studio"
  const STUDIO_ROUTES = new Set([
    "/encounters", "/trainers", "/scripts", "/flags", "/shops",
    "/heals", "/assets", "/explorer", "/items", "/moves", "/learnsets",
    "/visualizer", "/chains", "/metatiles", "/tilesets", "/templates",
    "/npcs", "/music", "/stamp-library",
  ]);

  // Update active nav link — handle both top-level and sub-nav
  document.querySelectorAll(".nav-link").forEach(link => {
    const linkRoute = link.dataset.route;
    // Exact match or base-route match for sub-routes
    let isActive = linkRoute === route || linkRoute === baseRoute;
    // Studio family: highlight "Studio" in sidebar when on any Studio tool
    if (linkRoute === "/studio" && STUDIO_ROUTES.has(baseRoute)) {
      isActive = true;
    }
    link.classList.toggle("active", isActive);
  });

  // Cleanup previous view
  if (currentCleanup) {
    currentCleanup();
    currentCleanup = null;
  }

  // IDE/Studio mode: hide nav/footer chrome for full-viewport layout
  const isIDE = baseRoute === "/ide" || baseRoute === "/studio";
  const nav = document.querySelector("nav");
  const footer = document.querySelector("footer.status-bar");
  const dexPanel = document.getElementById("dex-panel");
  const buildDrawer = document.getElementById("build-drawer");
  if (nav) nav.style.display = isIDE ? "none" : "";
  if (footer) footer.style.display = isIDE ? "none" : "";
  if (dexPanel) dexPanel.style.display = isIDE ? "none" : "";
  if (buildDrawer && isIDE) buildDrawer.classList.remove("open");
  if (container) container.style.maxWidth = isIDE ? "none" : "";

  try {
    const view = await loader();
    container.innerHTML = "";
    view.render(container);
    currentCleanup = view.cleanup || null;
  } catch (err) {
    container.innerHTML = `<article><header><h2>Error</h2></header><p>${esc(err.message)}</p></article>`;
  }
}

let _previousHash = window.location.hash || "#/";

// Global flag: set to true to suppress the next hashchange navigation.
// Used by scriptDrawer.js to temporarily set the hash for visualizer routing.
window._torchSuppressHashChange = false;

window.addEventListener("hashchange", () => {
  if (window._torchSuppressHashChange) {
    window._torchSuppressHashChange = false;
    return;
  }
  // Check if navigating away from visualizer with unsaved changes
  const prevBase = "/" + _previousHash.slice(1).split("/").filter(Boolean)[0];
  if (prevBase === "/visualizer" && window._torchVisualizerDirty) {
    if (!confirm("You have unsaved changes. Discard and leave?")) {
      // Restore the previous hash without triggering another hashchange
      history.replaceState(null, "", _previousHash);
      return;
    }
  }
  _previousHash = window.location.hash || "#/";
  navigate();
});

navigate();

// ---------------------------------------------------------------------------
// Theme switcher — persisted in localStorage
// ---------------------------------------------------------------------------

const THEME_MASCOTS = {
  torch: "torchic",
  porygon: "porygon",
  rayquaza: "rayquaza",
};

function setTheme(name) {
  // Always keep data-theme="dark" for Pico CSS dark mode.
  // TORCH themes use a separate data-torch-theme attribute.
  document.documentElement.setAttribute("data-theme", "dark");
  if (name === "torch") {
    document.documentElement.removeAttribute("data-torch-theme");
  } else {
    document.documentElement.setAttribute("data-torch-theme", name);
  }
  localStorage.setItem("torch-theme", name);
  document.querySelectorAll(".theme-dot").forEach(d => {
    d.classList.toggle("active", d.dataset.theme === name);
  });
  // Update mascot sprite
  const mascotEl = document.getElementById("nav-mascot");
  if (mascotEl) {
    const species = THEME_MASCOTS[name] || "torchic";
    const spriteUrl = `/api/sprites/${species}/anim_front.png`;
    import("./spriteUtils.js").then(({ processSprite }) => {
      processSprite(spriteUrl).then(dataUrl => { mascotEl.src = dataUrl; });
    });
  }
}

// Load saved theme on startup
setTheme(localStorage.getItem("torch-theme") || "torch");

// Wire click handlers
document.querySelectorAll(".theme-dot").forEach(dot => {
  dot.addEventListener("click", () => setTheme(dot.dataset.theme));
});


// ---------------------------------------------------------------------------
// Mobile menu toggle — hamburger button for narrow screens
// ---------------------------------------------------------------------------

const menuToggle = document.querySelector('.mobile-menu-toggle');
if (menuToggle) {
  menuToggle.addEventListener('click', () => {
    document.querySelector('nav').classList.toggle('mobile-open');
  });
  // Close menu when navigating
  window.addEventListener('hashchange', () => {
    document.querySelector('nav').classList.remove('mobile-open');
  });
}

// ---------------------------------------------------------------------------
// Nav layout toggle — switch between top bar and sidebar, with collapse
// ---------------------------------------------------------------------------

function setNavLayout(mode) {
  document.body.classList.toggle("nav-sidebar", mode === "sidebar" || mode === "sidebar-collapsed");
  document.body.classList.toggle("nav-collapsed", mode === "sidebar-collapsed");
  localStorage.setItem("torch-nav-layout", mode);
}

// Restore saved layout on startup
setNavLayout(localStorage.getItem("torch-nav-layout") || "topbar");

// Layout toggle button (horizontal <-> sidebar, remembers collapsed)
const layoutToggle = document.querySelector(".nav-layout-toggle");
if (layoutToggle) {
  layoutToggle.addEventListener("click", () => {
    const isSidebar = document.body.classList.contains("nav-sidebar");
    if (isSidebar) {
      setNavLayout("topbar");
    } else {
      // Restore collapsed state if that's how the sidebar was last used
      const wasCollapsed = localStorage.getItem("torch-sidebar-collapsed") === "1";
      setNavLayout(wasCollapsed ? "sidebar-collapsed" : "sidebar");
    }
  });
}

// Collapse toggle arrow (expand/collapse sidebar)
const collapseToggle = document.querySelector(".nav-collapse-toggle");
if (collapseToggle) {
  collapseToggle.addEventListener("click", () => {
    const isCollapsed = document.body.classList.contains("nav-collapsed");
    const newMode = isCollapsed ? "sidebar" : "sidebar-collapsed";
    localStorage.setItem("torch-sidebar-collapsed", isCollapsed ? "0" : "1");
    setNavLayout(newMode);
  });
}

// ---------------------------------------------------------------------------
// Status bar — populate on load and react to SSE build events
// ---------------------------------------------------------------------------

function initStatusBar() {
  const projectEl = document.querySelector(".status-project");
  const expansionEl = document.querySelector(".status-expansion");
  const torchVersionEl = document.querySelector(".status-torch-version");
  const dotEl = document.querySelector(".status-dot");
  const textEl = document.querySelector(".status-build-text");
  const drawer = document.getElementById("build-drawer");
  const drawerLog = drawer ? drawer.querySelector(".build-drawer-log") : null;
  const drawerTitle = drawer ? drawer.querySelector(".build-drawer-title") : null;
  const progressFill = document.querySelector(".status-progress-fill");
  const buildIndicator = document.querySelector(".status-build-indicator");

  if (!projectEl) return;

  const lanUrlEl = document.querySelector(".status-lan-url");
  const lanSepEl = document.querySelector(".status-sep-lan");

  // Populate from /api/status
  api("/status").then(res => {
    if (res.ok) {
      const d = res.data;
      projectEl.textContent = d.project_name || "--";
      expansionEl.textContent = d.expansion_version ? `Expansion ${d.expansion_version}` : "--";
      torchVersionEl.textContent = `TORCH ${d.torch_version || "?"}`;
      if (d.lan_url && lanUrlEl) {
        let lanText = d.lan_url;
        if (d.lan_user) {
          lanText += `  (user: ${d.lan_user})`;
        }
        lanUrlEl.textContent = lanText;
        lanUrlEl.title = "LAN access — type this URL on another device";
        lanUrlEl.classList.add("visible");
        if (lanSepEl) lanSepEl.classList.add("visible");
      }
    }
  }).catch(() => {});

  // Drawer toggle button
  const drawerToggle = document.querySelector(".status-drawer-toggle");

  function syncDrawerToggle() {
    if (!drawerToggle || !drawer) return;
    const isOpen = drawer.classList.contains("open");
    drawerToggle.innerHTML = isOpen ? "&#9660;" : "&#9650;";
    drawerToggle.classList.toggle("active", isOpen);
  }

  function toggleDrawer() {
    if (!drawer) return;
    drawer.classList.toggle("open");
    if (drawer.classList.contains("open")) closeDexPanel();
    syncDrawerToggle();
  }

  // Toggle drawer on build indicator click
  if (buildIndicator && drawer) {
    buildIndicator.addEventListener("click", toggleDrawer);
  }

  if (drawerToggle && drawer) {
    drawerToggle.addEventListener("click", toggleDrawer);
  }

  syncDrawerToggle();

  // Dex reference panel
  function closeBuildDrawer() {
    if (drawer) {
      drawer.classList.remove("open");
      syncDrawerToggle();
    }
  }
  initDexPanel(closeBuildDrawer);

  // SSE build events
  let clearTimer = null;
  let buildStart = null;
  let buildLineCount = 0;
  const es = getEventSource();
  const LAST_LINES_KEY = "torch-build-last-lines";

  function setStatus(dotClass, text) {
    dotEl.className = "status-dot " + dotClass;
    textEl.textContent = text;
    if (clearTimer) clearTimeout(clearTimer);
  }

  const MAX_DRAWER_LINES = 200;
  let _drawerLines = [];

  es.addEventListener("build_start", () => {
    setStatus("status-dot-building", "Building...");
    buildStart = Date.now();
    buildLineCount = 0;
    _drawerLines = [];
    if (drawerLog) drawerLog.textContent = "";
    if (drawerTitle) drawerTitle.textContent = "Build Output";
    if (drawer) drawer.classList.add("open");
    closeDexPanel();
    syncDrawerToggle();
    if (progressFill) {
      progressFill.style.width = "0%";
      progressFill.className = "status-progress-fill";
      const lastLines = parseInt(localStorage.getItem(LAST_LINES_KEY), 10);
      if (!lastLines) progressFill.classList.add("indeterminate");
    }
  });

  es.addEventListener("build_output", (e) => {
    try {
      const d = JSON.parse(e.data);
      if (drawerLog) {
        _drawerLines.push(d.line);
        if (_drawerLines.length > MAX_DRAWER_LINES) {
          _drawerLines = _drawerLines.slice(-MAX_DRAWER_LINES);
        }
        drawerLog.textContent = _drawerLines.join("\n") + "\n";
        if (drawer) drawer.scrollTop = drawer.scrollHeight;
      }
      buildLineCount++;
      if (progressFill) {
        const lastLines = parseInt(localStorage.getItem(LAST_LINES_KEY), 10);
        if (lastLines > 0) {
          const pct = Math.min(98, (buildLineCount / lastLines) * 100);
          progressFill.style.width = pct + "%";
          progressFill.classList.remove("indeterminate");
        }
      }
    } catch (_) {}
  });

  es.addEventListener("build_complete", (e) => {
    try {
      const d = JSON.parse(e.data);
      localStorage.setItem(LAST_LINES_KEY, String(buildLineCount));
      if (progressFill) {
        progressFill.style.width = "100%";
        progressFill.classList.remove("indeterminate");
        progressFill.classList.add(d.success ? "success" : "failed");
      }
      if (d.success) {
        setStatus("status-dot-ok", "Build OK");
      } else {
        setStatus("status-dot-error", "Build failed");
      }
      // Show duration in drawer header
      if (drawerTitle && buildStart) {
        const secs = ((Date.now() - buildStart) / 1000).toFixed(1);
        drawerTitle.textContent = d.success
          ? `Build OK -- ${secs}s`
          : `Build failed (exit ${d.exit_code}) -- ${secs}s`;
      }
    } catch (_) {
      setStatus("status-dot-ok", "Build done");
    }
    // Auto-clear status dot after 30 seconds
    clearTimer = setTimeout(() => {
      setStatus("status-dot-idle", "Ready");
      if (progressFill) {
        progressFill.style.width = "0%";
        progressFill.className = "status-progress-fill";
      }
    }, 30000);
  });

  // Sync SSE events — shown in status bar on desktop only.
  // The .sync-active class hides the text on mobile via CSS so the status
  // bar doesn't get crowded on small screens.
  es.addEventListener("sync_start", (e) => {
    try {
      const d = JSON.parse(e.data);
      if (buildIndicator) buildIndicator.classList.add("sync-active");
      setStatus("status-dot-building", `Syncing ${d.map}...`);
    } catch (_) {}
  });

  es.addEventListener("sync_all_done", (e) => {
    try {
      const d = JSON.parse(e.data);
      if (d.failed === 0) {
        setStatus("status-dot-ok",
          `Synced ${d.total} map${d.total !== 1 ? "s" : ""}`);
      } else {
        setStatus("status-dot-error",
          `Synced ${d.total - d.failed}/${d.total} (${d.failed} failed)`);
      }
    } catch (_) {
      setStatus("status-dot-ok", "Sync done");
    }
    // Auto-clear after 10 seconds
    clearTimer = setTimeout(() => {
      setStatus("status-dot-idle", "Ready");
      if (buildIndicator) buildIndicator.classList.remove("sync-active");
    }, 10000);
  });
}

initStatusBar();
