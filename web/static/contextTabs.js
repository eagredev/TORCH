/**
 * TORCH IDE — Context Panel Tab System.
 * TORCH_MODULE
 *
 * Registry and lifecycle manager for right-panel tabs.
 * Each tab gets its own container div (shown/hidden on switch).
 *
 * Exports: registerTab, initTabs, setMap, activateTab, getActiveTab,
 *          suspendTabs, restoreTabs, cleanupTabs
 */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/** @type {{ id:string, label:string, loader:()=>Promise, mod:object|null, containerEl:HTMLElement|null, initialized:boolean, stale:boolean }[]} */
const _tabs = [];
let _activeTabId = null;
let _mapName = null;
let _tabBarEl = null;
let _bodyEl = null;
let _suspended = false;
let _savedTabId = null;

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

export function registerTab(id, label, loader) {
  _tabs.push({ id, label, loader, mod: null, containerEl: null, initialized: false, stale: false });
}

// ---------------------------------------------------------------------------
// Init / Cleanup
// ---------------------------------------------------------------------------

export function initTabs(tabBarEl, bodyEl) {
  _tabBarEl = tabBarEl;
  _bodyEl = bodyEl;
  _renderTabBar();
}

export function cleanupTabs() {
  for (const tab of _tabs) {
    if (tab.mod && tab.mod.cleanup) tab.mod.cleanup();
    tab.mod = null;
    tab.containerEl = null;
    tab.initialized = false;
    tab.stale = false;
  }
  _tabs.length = 0;
  _activeTabId = null;
  _mapName = null;
  _tabBarEl = null;
  _bodyEl = null;
  _suspended = false;
  _savedTabId = null;
}

// ---------------------------------------------------------------------------
// Tab bar rendering
// ---------------------------------------------------------------------------

function _renderTabBar() {
  if (!_tabBarEl) return;
  _tabBarEl.innerHTML = "";
  for (const tab of _tabs) {
    const btn = document.createElement("button");
    btn.className = "ide-context-tab" + (tab.id === _activeTabId ? " active" : "");
    btn.dataset.tabId = tab.id;
    btn.textContent = tab.label;
    btn.addEventListener("click", () => activateTab(tab.id));
    _tabBarEl.appendChild(btn);
  }
}

function _updateTabBarActive() {
  if (!_tabBarEl) return;
  _tabBarEl.querySelectorAll(".ide-context-tab").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.tabId === _activeTabId);
  });
}

// ---------------------------------------------------------------------------
// Map changes
// ---------------------------------------------------------------------------

export function setMap(mapName) {
  _mapName = mapName;
  for (const tab of _tabs) {
    if (tab.id === _activeTabId && tab.initialized && tab.mod) {
      tab.mod.update(mapName);
      tab.stale = false;
    } else {
      tab.stale = true;
    }
  }
}

// ---------------------------------------------------------------------------
// Tab activation
// ---------------------------------------------------------------------------

export async function activateTab(id) {
  if (_suspended) return;
  const tab = _tabs.find(t => t.id === id);
  if (!tab) return;

  // Deselect current — hide its container
  const prev = _tabs.find(t => t.id === _activeTabId);
  if (prev) {
    if (prev.mod && prev.mod.onDeselect) prev.mod.onDeselect();
    if (prev.containerEl) prev.containerEl.style.display = "none";
  }

  _activeTabId = id;
  _updateTabBarActive();

  // Lazy-load module on first activation
  if (!tab.mod) {
    try {
      tab.mod = await tab.loader();
    } catch (err) {
      console.warn(`[contextTabs] Failed to load tab "${id}":`, err);
      if (_bodyEl) _bodyEl.innerHTML = `<div style="padding:0.5rem;color:var(--status-error)">Failed to load tab</div>`;
      return;
    }
  }

  // Create per-tab container if needed
  if (!tab.containerEl) {
    tab.containerEl = document.createElement("div");
    tab.containerEl.className = "ide-tab-container";
    tab.containerEl.dataset.tabId = id;
    if (_bodyEl) _bodyEl.appendChild(tab.containerEl);
  }

  // Show this tab's container
  tab.containerEl.style.display = "";

  // Initialize or update
  if (!tab.initialized) {
    tab.mod.init(tab.containerEl, _mapName);
    tab.initialized = true;
    tab.stale = false;
  } else if (tab.stale) {
    tab.mod.update(_mapName);
    tab.stale = false;
  }

  if (tab.mod.onSelect) tab.mod.onSelect();
}

export function getActiveTab() { return _activeTabId; }

// ---------------------------------------------------------------------------
// Scripts Mode suspend / restore
// ---------------------------------------------------------------------------

export function suspendTabs() {
  _suspended = true;
  _savedTabId = _activeTabId;

  const cur = _tabs.find(t => t.id === _activeTabId);
  if (cur) {
    if (cur.mod && cur.mod.onDeselect) cur.mod.onDeselect();
    if (cur.containerEl) cur.containerEl.style.display = "none";
  }

  if (_tabBarEl) _tabBarEl.style.display = "none";
}

export function restoreTabs() {
  _suspended = false;
  if (_tabBarEl) _tabBarEl.style.display = "";

  if (_savedTabId) {
    activateTab(_savedTabId);
    _savedTabId = null;
  }
}
