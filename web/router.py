# TORCH_MODULE: Web Router
# TORCH_GROUP: Web
"""URL routing for the TORCH web GUI.

Dispatches requests to API handlers or serves static files from web/static/.
Any URL that doesn't match an API route or existing static file gets the
SPA fallback (index.html).
"""

import base64
import os
import re
import json
import mimetypes
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from torch.web.api import match_api_route, handle_api_request
from torch.web.events import broadcaster


_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg":  "image/svg+xml",
    ".ico":  "image/x-icon",
}


def _content_type(file_path):
    """Return Content-Type for a file path based on extension."""
    _, ext = os.path.splitext(file_path)
    return _CONTENT_TYPES.get(ext.lower(), "application/octet-stream")


def _is_safe_path(path):
    """Return True if path doesn't attempt directory traversal."""
    normalised = os.path.normpath(path)
    if ".." in normalised.split(os.sep):
        return False
    return True


def _serve_static(handler, url_path):
    """Serve a static file or fall back to index.html for SPA routing."""
    # Strip leading slash
    relative = url_path.lstrip("/")
    if not relative:
        relative = "index.html"

    if not _is_safe_path(relative):
        handler.send_error(403, "Forbidden")
        return

    file_path = os.path.join(_STATIC_DIR, relative)

    # If the path is a file, serve it
    if os.path.isfile(file_path):
        _send_file(handler, file_path)
        return

    # SPA fallback: serve index.html for any unmatched path
    index_path = os.path.join(_STATIC_DIR, "index.html")
    if os.path.isfile(index_path):
        _send_file(handler, index_path)
    else:
        handler.send_error(404, "Not Found")


def _send_file(handler, file_path):
    """Send a static file with the appropriate Content-Type."""
    try:
        with open(file_path, "rb") as f:
            data = f.read()
    except OSError:
        handler.send_error(500, "Internal Server Error")
        return

    ct = _content_type(file_path)
    handler.send_response(200)
    handler.send_header("Content-Type", ct)
    handler.send_header("Content-Length", str(len(data)))
    # Prevent browser caching of JS/CSS during development
    _, ext = os.path.splitext(file_path)
    if ext.lower() in (".js", ".css", ".html"):
        handler.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
    handler.end_headers()
    handler.wfile.write(data)


def _serve_sse(handler):
    """Stream Server-Sent Events to the client until disconnect."""
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.end_headers()

    q = broadcaster.subscribe()
    try:
        while True:
            try:
                msg = q.get(timeout=2)
            except Exception:
                # queue.Empty — ping to detect dead connections
                handler.wfile.write(b":\n\n")
                handler.wfile.flush()
                continue
            handler.wfile.write(msg)
            handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        broadcaster.unsubscribe(q)


def _check_auth(handler):
    """Return True if request is authenticated, False otherwise.
    If no credentials configured, always returns True.
    Localhost connections are always trusted (auth is for LAN only)."""
    # Host machine never needs a password
    client_ip = handler.client_address[0]
    if client_ip in ("127.0.0.1", "::1"):
        return True

    settings = getattr(handler.server, "settings", {})
    username = settings.get("gui_username", "")
    password = settings.get("gui_password", "")

    if not username or not password:
        return True  # no auth configured

    auth_header = handler.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return False

    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        req_user, req_pass = decoded.split(":", 1)
        return req_user == username and req_pass == password
    except Exception:
        return False


def _send_auth_required(handler):
    """Send 401 response requesting Basic auth."""
    handler.send_response(401)
    handler.send_header("WWW-Authenticate", 'Basic realm="TORCH"')
    handler.send_header("Content-Type", "text/plain")
    handler.end_headers()
    handler.wfile.write(b"Authentication required")


def dispatch_request(handler, method, path):
    """Route an HTTP request to the appropriate handler."""
    if not _check_auth(handler):
        _send_auth_required(handler)
        return

    parsed = urlparse(path)
    url_path = parsed.path
    query_params = parse_qs(parsed.query)

    # API routes
    if url_path.startswith("/api/"):
        route_match = match_api_route(method, url_path)
        if route_match:
            pattern, api_handler, match = route_match
            handle_api_request(handler, api_handler, match, query_params)
            return
        # No matching API route
        handler.send_response(404)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.end_headers()
        body = json.dumps({"ok": False, "error": "Not found"})
        handler.wfile.write(body.encode("utf-8"))
        return

    # SSE stream
    if url_path == "/events":
        _serve_sse(handler)
        return

    # Static files / SPA fallback
    _serve_static(handler, url_path)


class TorchHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the TORCH web GUI."""

    def do_GET(self):
        dispatch_request(self, "GET", self.path)

    def do_POST(self):
        dispatch_request(self, "POST", self.path)

    def do_DELETE(self):
        dispatch_request(self, "DELETE", self.path)

    def log_message(self, format, *args):
        """Suppress default access logging."""
        pass

    def handle(self):
        """Suppress BrokenPipeError during shutdown."""
        try:
            super().handle()
        except BrokenPipeError:
            pass
