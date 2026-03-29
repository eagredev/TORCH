# TORCH_MODULE: Web Server
# TORCH_GROUP: Web
"""ThreadingHTTPServer for the TORCH web GUI.

Supports localhost-only (default) and LAN mode (opt-in).  Runs as a daemon
thread so it dies when the main process exits.  The main thread blocks on
a simple input loop (press q to stop).
"""

import json
import os
import socket
import sys
import threading
import webbrowser  # fallback only — see browser_launch.py
from http.server import ThreadingHTTPServer

from torch.web.router import TorchHandler
from torch.config import load_config, resolve_project


_DEFAULT_PORT = 8642


def _kill_existing_torch_on_port(port):
    """Kill an existing TORCH GUI process on the given port.

    Only kills processes whose command line contains 'torch' to avoid
    accidentally terminating unrelated services.
    """
    import signal
    import subprocess
    try:
        # Find PIDs listening on this port
        result = subprocess.run(
            ["fuser", f"{port}/tcp"],
            capture_output=True, text=True, timeout=5
        )
        pids_str = result.stdout.strip()
        if not pids_str:
            pids_str = result.stderr.strip()
        if not pids_str:
            return False

        # Parse PIDs (fuser output: "8642/tcp:  12345 12346")
        pids = []
        for token in pids_str.replace("/tcp:", "").split():
            token = token.strip()
            if token.isdigit():
                pid = int(token)
                if pid != os.getpid():
                    pids.append(pid)

        if not pids:
            return False

        killed = False
        for pid in pids:
            # Verify it's a TORCH process before killing
            try:
                cmdline_path = f"/proc/{pid}/cmdline"
                with open(cmdline_path, "r") as f:
                    cmdline = f.read().lower()
                if "torch" not in cmdline:
                    continue  # not ours — leave it alone
            except (OSError, PermissionError):
                continue  # can't read cmdline — don't risk killing it

            try:
                os.kill(pid, signal.SIGTERM)
                killed = True
            except ProcessLookupError:
                pass

        return killed
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _try_bind(host, port):
    """Test if we can bind to host:port. Uses SO_REUSEADDR."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _claim_port(host, port):
    """Claim the preferred port, killing any existing TORCH session if needed."""
    if _try_bind(host, port):
        return port

    # Port is in use — try to kill an existing TORCH session
    print(f"  Port {port} in use, checking for existing TORCH session...")
    if not _kill_existing_torch_on_port(port):
        print(f"  Port {port} is held by a non-TORCH process. Cannot take over.")
        return None

    # Wait for the port to actually free up (up to 2 seconds)
    import time
    for _ in range(8):
        if _try_bind(host, port):
            return port
        time.sleep(0.25)

    print(f"  Port {port} still busy after killing old session.")
    return None


def _get_lan_ip():
    """Get this machine's LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


def _resolve_host(settings):
    """Determine the bind host from settings. Returns (host, is_lan_mode)."""
    host = settings.get("gui_host", "127.0.0.1")
    lan_enabled = settings.get("gui_lan_enabled", False)
    lan_override = settings.get("_lan_override", False)

    if lan_enabled or lan_override:
        return "0.0.0.0", True

    is_lan = (host == "0.0.0.0")
    return host, is_lan


def start_gui_server(game_path, project_dir, settings, proj_name):
    """Launch the TORCH web GUI server and block until user quits."""
    host, lan_mode = _resolve_host(settings)
    preferred_port = int(settings.get("gui_port", _DEFAULT_PORT))
    port = _claim_port(host, preferred_port)
    if port is None:
        print(f"  ERROR: Could not bind port {preferred_port} "
              f"(another process may be holding it).")
        return

    # Detect expansion version
    expansion_version = None
    try:
        from torch.expansion_compat import detect_expansion_version, version_str
        ver = detect_expansion_version(game_path)
        if ver:
            expansion_version = version_str(ver)
    except ImportError:
        pass

    lan_ip = _get_lan_ip() if lan_mode else None

    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((host, port), TorchHandler)
    server.game_path = game_path
    server.project_dir = project_dir
    server.settings = settings
    server.proj_name = proj_name
    server.expansion_version = expansion_version
    server.shutdown_event = threading.Event()
    server.lan_mode = lan_mode
    server.lan_ip = lan_ip
    server.port = port

    # Auto-shutdown when all browser tabs close (localhost mode only)
    _setup_auto_shutdown(server, lan_mode)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    local_url = f"http://127.0.0.1:{port}/"
    gui_mode = settings.get("gui_mode", "standalone")
    try:
        from torch.web.browser_launch import launch_browser
        launch_browser(local_url, mode=gui_mode)
    except Exception:
        webbrowser.open_new(local_url)

    interactive = sys.stdin.isatty()
    if interactive:
        _print_startup_banner(port, lan_mode, lan_ip, settings)

    try:
        if interactive:
            _wait_for_quit_key(server)
        else:
            # Headless mode (desktop shortcut) — just wait for shutdown signal
            server.shutdown_event.wait()
    except KeyboardInterrupt:
        pass

    server.shutdown()
    if interactive:
        print("  Server stopped.")


def _print_startup_banner(port, lan_mode, lan_ip, settings):
    """Print the server startup banner with URLs and auth info."""
    print()
    print("  TORCH Web GUI")
    print(f"  Local:   http://127.0.0.1:{port}/")
    if lan_mode and lan_ip:
        print(f"  Network: http://{lan_ip}:{port}/")

    username = settings.get("gui_username", "")
    password = settings.get("gui_password", "")
    if username and password:
        masked = password[0] + "*" * (len(password) - 1) if len(password) > 1 else "*"
        print(f"  Auth:    {username} / {masked}")

    print()
    print("  Press q to stop the server.")
    print()


def _wait_for_quit_key(server):
    """Block until user presses q or the shutdown event fires."""
    while not server.shutdown_event.is_set():
        try:
            if sys.stdin in _select_stdin(0.5):
                key = sys.stdin.readline()
                if not key or key.strip().lower() == "q":
                    break
        except EOFError:
            break


def _select_stdin(timeout):
    """Wait up to *timeout* seconds for stdin to be readable. Returns list."""
    import select
    try:
        readable, _, _ = select.select([sys.stdin], [], [], timeout)
        return readable
    except (ValueError, OSError):
        return []


_AUTO_SHUTDOWN_GRACE = 3  # seconds to wait before shutting down


def _setup_auto_shutdown(server, lan_mode):
    """Register a callback that shuts down the server when all tabs close.

    In LAN mode, auto-shutdown is disabled — multiple clients can connect
    and disconnect freely.
    """
    if lan_mode:
        return  # no auto-shutdown in LAN mode

    import time
    from torch.web.events import broadcaster

    def on_last_disconnect():
        def _check_and_shutdown():
            time.sleep(_AUTO_SHUTDOWN_GRACE)
            if broadcaster.client_count == 0:
                server.shutdown_event.set()
        threading.Thread(target=_check_and_shutdown, daemon=True).start()

    broadcaster._on_last_disconnect = on_last_disconnect
