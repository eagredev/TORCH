# TORCH_MODULE: Browser Launch
# TORCH_GROUP: Web
"""Browser launcher for standalone application presentation.

Detects the best available browser and launches TORCH in a chrome-less
window — no tab bar, no address bar, no bookmarks.  Falls back to the
system default browser if no supported browser is found.

Supported strategies (tried in order):
  1. Chromium / Google Chrome  — ``--app=URL`` flag (simplest)
  2. Firefox Flatpak           — dedicated profile with userChrome.css
  3. Native Firefox            — same profile approach, different path
  4. Fallback                  — ``webbrowser.open_new(url)``
"""

import os
import shutil
import subprocess
import webbrowser


# ---------------------------------------------------------------------------
# Firefox profile setup
# ---------------------------------------------------------------------------

# CSS to hide all browser chrome (tabs, address bar, bookmarks, title bar)
_USER_CHROME_CSS = """\
/* TORCH Studio — hide browser chrome for standalone mode */
#TabsToolbar { display: none !important; }
#nav-bar { display: none !important; }
#PersonalToolbar { display: none !important; }
"""

# Firefox preferences for the TORCH profile
_USER_JS = """\
// TORCH Studio profile preferences
user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.tabs.inTitlebar", 0);
user_pref("browser.aboutConfig.showWarning", false);
user_pref("browser.startup.firstrunSkipsHomepage", true);
user_pref("startup.homepage_welcome_url", "");
user_pref("startup.homepage_welcome_url.additional", "");
user_pref("browser.messaging-system.whatsNewPanel.enabled", false);
user_pref("extensions.pocket.enabled", false);
"""

_PROFILE_DIR_NAME = "torch-studio"


def _firefox_flatpak_profile_path():
    """Return the host-side path for a Firefox Flatpak profile directory.

    Flatpak's ``persistent=.mozilla`` mapping means Firefox sees
    ``~/.mozilla/`` which maps to ``~/.var/app/org.mozilla.firefox/.mozilla/``
    on the host.
    """
    return os.path.join(
        os.path.expanduser("~"),
        ".var", "app", "org.mozilla.firefox",
        ".mozilla", "firefox", _PROFILE_DIR_NAME,
    )


def _firefox_native_profile_path():
    """Return the host-side path for a native Firefox profile directory."""
    return os.path.join(
        os.path.expanduser("~"),
        ".mozilla", "firefox", _PROFILE_DIR_NAME,
    )


def _ensure_firefox_profile(profile_dir):
    """Create the TORCH Firefox profile if it doesn't exist.

    Writes ``chrome/userChrome.css`` and ``user.js`` into the profile.
    If the profile already exists, only updates files that are missing
    or outdated.
    """
    chrome_dir = os.path.join(profile_dir, "chrome")
    os.makedirs(chrome_dir, exist_ok=True)

    css_path = os.path.join(chrome_dir, "userChrome.css")
    if not os.path.isfile(css_path) or _file_outdated(css_path, _USER_CHROME_CSS):
        with open(css_path, "w", encoding="utf-8") as f:
            f.write(_USER_CHROME_CSS)

    js_path = os.path.join(profile_dir, "user.js")
    if not os.path.isfile(js_path) or _file_outdated(js_path, _USER_JS):
        with open(js_path, "w", encoding="utf-8") as f:
            f.write(_USER_JS)


def _file_outdated(path, expected_content):
    """Check if a file's content differs from the expected content."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read() != expected_content
    except OSError:
        return True


# ---------------------------------------------------------------------------
# Browser detection
# ---------------------------------------------------------------------------

def _find_chromium():
    """Find a Chromium-based browser binary, or None."""
    for name in ("chromium-browser", "chromium", "google-chrome-stable",
                 "google-chrome", "brave-browser"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _has_firefox_flatpak():
    """Check if Firefox Flatpak is installed."""
    try:
        result = subprocess.run(
            ["flatpak", "info", "org.mozilla.firefox"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _find_native_firefox():
    """Find a native (non-Flatpak) Firefox binary, or None."""
    return shutil.which("firefox")


# ---------------------------------------------------------------------------
# Launch strategies
# ---------------------------------------------------------------------------

def _launch_chromium(binary, url):
    """Launch Chromium in app mode (no browser chrome)."""
    subprocess.Popen(
        [binary, f"--app={url}", "--class=torch-studio"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return True


def _launch_firefox_flatpak(url):
    """Launch Firefox Flatpak with the TORCH profile."""
    host_path = _firefox_flatpak_profile_path()
    _ensure_firefox_profile(host_path)

    # Inside the Flatpak sandbox, ~/.mozilla maps to the host's
    # ~/.var/app/org.mozilla.firefox/.mozilla via the persistent mapping.
    # The -profile flag needs the path as Firefox sees it inside the sandbox.
    sandbox_path = os.path.join(
        os.path.expanduser("~"), ".mozilla", "firefox", _PROFILE_DIR_NAME,
    )

    subprocess.Popen(
        ["flatpak", "run", "org.mozilla.firefox",
         "--new-instance", "-profile", sandbox_path,
         "--new-window", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return True


def _launch_native_firefox(binary, url):
    """Launch native Firefox with the TORCH profile."""
    profile_path = _firefox_native_profile_path()
    _ensure_firefox_profile(profile_path)

    subprocess.Popen(
        [binary, "--new-instance", "-profile", profile_path,
         "--new-window", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def launch_browser(url, mode="standalone"):
    """Launch TORCH in the best available browser.

    Parameters
    ----------
    url : str
        The localhost URL to open (e.g. ``http://127.0.0.1:8642/``).
    mode : str
        ``"standalone"`` (default) hides browser chrome.
        ``"browser"`` uses the system default browser as-is.
    """
    if mode != "standalone":
        webbrowser.open_new(url)
        return

    # 1. Chromium (simplest — native --app flag)
    chromium = _find_chromium()
    if chromium:
        _launch_chromium(chromium, url)
        return

    # 2. Firefox Flatpak (common on Steam Deck / SteamOS)
    if _has_firefox_flatpak():
        _launch_firefox_flatpak(url)
        return

    # 3. Native Firefox
    firefox = _find_native_firefox()
    if firefox:
        _launch_native_firefox(firefox, url)
        return

    # 4. Fallback — system default browser
    webbrowser.open_new(url)
