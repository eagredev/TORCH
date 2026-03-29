"""Network utilities for TORCH.

Stdlib-only (urllib.request, urllib.error, json).  All functions return
bool, (bool, data, error_str), or (bool, str) — never raise.
"""
# TORCH_MODULE: Network Operations
# TORCH_GROUP: Core
import json
import os
import tempfile
import urllib.error
import urllib.request

NETOPS_VERSION = "1.0"

_CHUNK_SIZE = 65536  # 64 KB


def http_get(url, timeout=15):
    """Perform an HTTP GET request.

    Returns (success: bool, data: bytes or None, error: str).
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read()
        return True, data, ""
    except urllib.error.HTTPError as e:
        return False, None, f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return False, None, str(e.reason)
    except Exception as e:
        return False, None, str(e)


def download_file(url, dest_path, timeout=60, progress_cb=None):
    """Download *url* to *dest_path*, streaming in 64 KB chunks.

    *progress_cb*, if provided, is called with (bytes_downloaded, total_bytes_or_None)
    after each chunk.

    Uses an atomic rename on success so a partial download never overwrites
    an existing file.

    Returns (bool, message).
    """
    dirpath = os.path.dirname(os.path.abspath(dest_path))
    try:
        os.makedirs(dirpath, exist_ok=True)
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            total = None
            content_length = resp.headers.get("Content-Length")
            if content_length:
                try:
                    total = int(content_length)
                except ValueError:
                    pass

            fd, tmp_path = tempfile.mkstemp(dir=dirpath)
            try:
                downloaded = 0
                with os.fdopen(fd, "wb") as f:
                    while True:
                        chunk = resp.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb:
                            progress_cb(downloaded, total)
                os.replace(tmp_path, dest_path)
                return True, f"Downloaded {downloaded} bytes -> {dest_path}"
            except Exception as e:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                return False, str(e)
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return False, str(e.reason)
    except Exception as e:
        return False, str(e)


def fetch_json(url, timeout=15):
    """GET *url* and parse the response body as JSON.

    Returns (success: bool, data: dict or None, error: str).
    """
    ok, raw, err = http_get(url, timeout=timeout)
    if not ok:
        return False, None, err
    try:
        data = json.loads(raw)
        return True, data, ""
    except json.JSONDecodeError as e:
        return False, None, f"JSON parse error: {e}"


def fetch_github_tags(api_url, tag_pattern, per_page=100):
    """Fetch version tags from a GitHub API endpoint (paginated).

    *api_url* is the tags API URL (e.g. .../repos/owner/repo/tags).
    *tag_pattern* is a compiled regex with three capture groups for
    (major, minor, patch).

    Returns a list of (major, minor, patch) tuples sorted newest-first,
    or None on network/API error.
    """
    all_versions = []
    page = 1
    while True:
        url = f"{api_url}?per_page={per_page}&page={page}"
        ok, data, err = fetch_json(url, timeout=15)
        if not ok:
            if all_versions:
                break  # Got some pages, return what we have
            return None
        if not isinstance(data, list):
            break
        for tag_info in data:
            name = tag_info.get("name", "")
            m = tag_pattern.match(name)
            if m:
                all_versions.append(
                    (int(m.group(1)), int(m.group(2)), int(m.group(3)))
                )
        if len(data) < per_page:
            break  # Last page
        page += 1
    all_versions.sort(reverse=True)
    return all_versions


def check_connectivity(test_url="https://github.com"):
    """Perform a quick HEAD request to check internet connectivity.

    Returns True if reachable, False otherwise.
    """
    req = urllib.request.Request(test_url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception:
        return False
