"""Tests for browser_launch.py -- standalone app browser detection and launch."""

import os
import shutil
import subprocess
import tempfile
import webbrowser

from torch.tests.harness import _begin_suite, _ok, _fail, _assert


def run_suite():
    _begin_suite("Browser Launch  (standalone app detection)")

    from torch.web import browser_launch
    from torch.web.browser_launch import (
        find_app_browser, launch_browser, wait_for_close,
        _find_chromium, _ensure_firefox_profile, _file_outdated,
        _CHROMIUM_NAMES, _CHROMIUM_FLATPAK_IDS,
    )

    # -- Chromium names list ---------------------------------------------------

    for name in ("chromium", "google-chrome-stable", "brave-browser",
                 "microsoft-edge", "vivaldi"):
        _assert(f"chromium_names: {name} in list", name in _CHROMIUM_NAMES)

    for app_id in ("org.chromium.Chromium", "com.google.Chrome",
                   "com.brave.Browser"):
        _assert(f"flatpak_ids: {app_id} in list",
                app_id in _CHROMIUM_FLATPAK_IDS)

    # -- _find_chromium with mocked PATH ---------------------------------------

    _orig_which = shutil.which

    def _test_find_chromium_in_path():
        def _mock(name):
            return "/usr/bin/chromium" if name == "chromium" else None
        shutil.which = _mock
        try:
            path, name = _find_chromium()
            _assert("find_chromium: found in PATH",
                    path == "/usr/bin/chromium" and name == "chromium",
                    f"got ({path}, {name})")
        finally:
            shutil.which = _orig_which

    _test_find_chromium_in_path()

    def _test_find_chromium_prefers_first():
        def _mock(name):
            if name == "chromium-browser":
                return "/usr/bin/chromium-browser"
            if name == "google-chrome":
                return "/usr/bin/google-chrome"
            return None
        shutil.which = _mock
        try:
            path, name = _find_chromium()
            _assert("find_chromium: prefers chromium-browser over chrome",
                    name == "chromium-browser", f"got {name}")
        finally:
            shutil.which = _orig_which

    _test_find_chromium_prefers_first()

    def _test_find_chromium_brave():
        def _mock(name):
            return "/usr/bin/brave-browser" if name == "brave-browser" else None
        shutil.which = _mock
        try:
            path, name = _find_chromium()
            _assert("find_chromium: brave-browser",
                    name == "brave-browser", f"got {name}")
        finally:
            shutil.which = _orig_which

    _test_find_chromium_brave()

    def _test_find_chromium_edge():
        def _mock(name):
            return "/usr/bin/microsoft-edge" if name == "microsoft-edge" else None
        shutil.which = _mock
        try:
            path, name = _find_chromium()
            _assert("find_chromium: microsoft-edge",
                    name == "microsoft-edge", f"got {name}")
        finally:
            shutil.which = _orig_which

    _test_find_chromium_edge()

    def _test_find_chromium_vivaldi():
        def _mock(name):
            return "/usr/bin/vivaldi" if name == "vivaldi" else None
        shutil.which = _mock
        try:
            path, name = _find_chromium()
            _assert("find_chromium: vivaldi",
                    name == "vivaldi", f"got {name}")
        finally:
            shutil.which = _orig_which

    _test_find_chromium_vivaldi()

    def _test_find_chromium_none():
        shutil.which = lambda name: None
        orig_dirs = browser_launch._FLATPAK_BIN_DIRS
        browser_launch._FLATPAK_BIN_DIRS = ()  # disable Flatpak scan
        try:
            path, name = _find_chromium()
            _assert("find_chromium: none found",
                    path is None and name is None, f"got ({path}, {name})")
        finally:
            shutil.which = _orig_which
            browser_launch._FLATPAK_BIN_DIRS = orig_dirs

    _test_find_chromium_none()

    # -- Flatpak bin detection -------------------------------------------------

    def _test_find_chromium_flatpak_bin():
        shutil.which = lambda name: None
        orig_dirs = browser_launch._FLATPAK_BIN_DIRS
        with tempfile.TemporaryDirectory() as tmp:
            fake_bin = os.path.join(tmp, "org.chromium.Chromium")
            with open(fake_bin, "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(fake_bin, 0o755)
            browser_launch._FLATPAK_BIN_DIRS = (tmp,)
            try:
                path, name = _find_chromium()
                _assert("find_chromium: flatpak bin dir",
                        path == fake_bin and name == "org.chromium.Chromium",
                        f"got ({path}, {name})")
            finally:
                shutil.which = _orig_which
                browser_launch._FLATPAK_BIN_DIRS = orig_dirs

    _test_find_chromium_flatpak_bin()

    # -- find_app_browser (full chain) -----------------------------------------

    def _test_find_app_browser_chromium():
        def _mock(name):
            return "/usr/bin/chromium" if name == "chromium" else None
        shutil.which = _mock
        try:
            path, name = find_app_browser()
            _assert("find_app_browser: chromium",
                    path == "/usr/bin/chromium" and name == "chromium",
                    f"got ({path}, {name})")
        finally:
            shutil.which = _orig_which

    _test_find_app_browser_chromium()

    def _test_find_app_browser_firefox_flatpak():
        orig_run = subprocess.run
        shutil.which = lambda name: None
        orig_dirs = browser_launch._FLATPAK_BIN_DIRS
        browser_launch._FLATPAK_BIN_DIRS = ()
        subprocess.run = lambda *a, **kw: type("R", (), {"returncode": 0})()
        try:
            path, name = find_app_browser()
            _assert("find_app_browser: firefox flatpak",
                    path == "flatpak:org.mozilla.firefox"
                    and name == "Firefox Flatpak",
                    f"got ({path}, {name})")
        finally:
            shutil.which = _orig_which
            subprocess.run = orig_run
            browser_launch._FLATPAK_BIN_DIRS = orig_dirs

    _test_find_app_browser_firefox_flatpak()

    def _test_find_app_browser_native_firefox():
        orig_run = subprocess.run
        def _mock(name):
            return "/usr/bin/firefox" if name == "firefox" else None
        shutil.which = _mock
        orig_dirs = browser_launch._FLATPAK_BIN_DIRS
        browser_launch._FLATPAK_BIN_DIRS = ()
        subprocess.run = lambda *a, **kw: type("R", (), {"returncode": 1})()
        try:
            path, name = find_app_browser()
            _assert("find_app_browser: native firefox",
                    path == "/usr/bin/firefox" and name == "Firefox",
                    f"got ({path}, {name})")
        finally:
            shutil.which = _orig_which
            subprocess.run = orig_run
            browser_launch._FLATPAK_BIN_DIRS = orig_dirs

    _test_find_app_browser_native_firefox()

    def _test_find_app_browser_none():
        orig_run = subprocess.run
        shutil.which = lambda name: None
        orig_dirs = browser_launch._FLATPAK_BIN_DIRS
        browser_launch._FLATPAK_BIN_DIRS = ()
        subprocess.run = lambda *a, **kw: type("R", (), {"returncode": 1})()
        try:
            path, name = find_app_browser()
            _assert("find_app_browser: none",
                    path is None and name is None, f"got ({path}, {name})")
        finally:
            shutil.which = _orig_which
            subprocess.run = orig_run
            browser_launch._FLATPAK_BIN_DIRS = orig_dirs

    _test_find_app_browser_none()

    # -- launch_browser --------------------------------------------------------

    def _test_launch_browser_mode():
        orig_open = webbrowser.open_new
        opened = []
        webbrowser.open_new = lambda url: opened.append(url)
        try:
            result = launch_browser("http://localhost:8642/", mode="browser")
            _assert("launch_browser: browser mode returns None",
                    result is None, f"got {result}")
            _assert("launch_browser: browser mode opens URL",
                    opened == ["http://localhost:8642/"], f"got {opened}")
        finally:
            webbrowser.open_new = orig_open

    _test_launch_browser_mode()

    def _test_launch_browser_standalone_fallback():
        """Falls back to webbrowser when no browser found."""
        orig_open = webbrowser.open_new
        orig_run = subprocess.run
        shutil.which = lambda name: None
        orig_dirs = browser_launch._FLATPAK_BIN_DIRS
        browser_launch._FLATPAK_BIN_DIRS = ()
        subprocess.run = lambda *a, **kw: type("R", (), {"returncode": 1})()
        opened = []
        webbrowser.open_new = lambda url: opened.append(url)
        try:
            result = launch_browser("http://localhost:8642/", mode="standalone")
            _assert("launch_browser: standalone fallback returns None",
                    result is None)
            _assert("launch_browser: standalone fallback opens URL",
                    len(opened) == 1, f"got {len(opened)}")
        finally:
            webbrowser.open_new = orig_open
            shutil.which = _orig_which
            subprocess.run = orig_run
            browser_launch._FLATPAK_BIN_DIRS = orig_dirs

    _test_launch_browser_standalone_fallback()

    # -- Chromium launch flags -------------------------------------------------

    def _test_chromium_flags():
        orig_popen = subprocess.Popen
        captured = []

        class FakePopen:
            def __init__(self, args, **kw):
                captured.extend(args)
                self.returncode = None
            def wait(self):
                pass

        subprocess.Popen = FakePopen
        try:
            proc = browser_launch._launch_chromium(
                "/usr/bin/chromium", "http://localhost:8642/")
            _assert("chromium_flags: binary first",
                    captured[0] == "/usr/bin/chromium")
            _assert("chromium_flags: --app",
                    "--app=http://localhost:8642/" in captured)
            _assert("chromium_flags: --window-size",
                    "--window-size=1280,800" in captured)
            _assert("chromium_flags: --disable-extensions",
                    "--disable-extensions" in captured)
            _assert("chromium_flags: --class",
                    "--class=torch-studio" in captured)
        finally:
            subprocess.Popen = orig_popen

    _test_chromium_flags()

    # -- wait_for_close --------------------------------------------------------

    wait_for_close(None)  # should not raise
    _ok("wait_for_close: None is no-op")

    class FakeProc:
        def __init__(self):
            self.waited = False
        def wait(self):
            self.waited = True

    fp = FakeProc()
    wait_for_close(fp)
    _assert("wait_for_close: calls wait()", fp.waited)

    # -- Firefox profile -------------------------------------------------------

    with tempfile.TemporaryDirectory() as tmp:
        _ensure_firefox_profile(tmp)
        css = os.path.join(tmp, "chrome", "userChrome.css")
        js = os.path.join(tmp, "user.js")
        _assert("firefox_profile: css created", os.path.isfile(css))
        _assert("firefox_profile: user.js created", os.path.isfile(js))
        with open(css) as f:
            content = f.read()
        _assert("firefox_profile: css has TabsToolbar",
                "#TabsToolbar" in content)
        _assert("firefox_profile: css has nav-bar", "#nav-bar" in content)

        # Idempotent
        _ensure_firefox_profile(tmp)
        _assert("firefox_profile: idempotent", os.path.isfile(css))

    # -- _file_outdated --------------------------------------------------------

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                     delete=False) as f:
        f.write("hello")
        fpath = f.name
    try:
        _assert("file_outdated: match returns False",
                not _file_outdated(fpath, "hello"))
        _assert("file_outdated: mismatch returns True",
                _file_outdated(fpath, "world"))
    finally:
        os.unlink(fpath)

    _assert("file_outdated: missing returns True",
            _file_outdated("/tmp/does_not_exist_torch_xyz.txt", "x"))
