"""Network Operations suite -- http_get, download_file, fetch_json, fetch_github_tags, check_connectivity."""
import json
import os
import tempfile
import shutil
from unittest.mock import patch, MagicMock

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Network Operations")

    try:
        from torch.netops import (
            http_get, download_file, fetch_json,
            fetch_github_tags, check_connectivity,
        )
        import urllib.error
        import urllib.request
    except ImportError as e:
        _skip("all tests", f"import failed: {e}")
        return

    # ---------------------------------------------------------------
    # http_get
    # ---------------------------------------------------------------

    # Success
    try:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"hello world"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            ok, data, err = http_get("https://example.com")
        _assert("http_get: success returns (True, bytes, '')",
                ok is True and data == b"hello world" and err == "",
                f"got: ok={ok!r}, data={data!r}, err={err!r}")
    except Exception as e:
        _fail("http_get: success", str(e))

    # HTTPError
    try:
        http_err = urllib.error.HTTPError(
            "https://example.com", 404, "Not Found", {}, None
        )
        with patch("urllib.request.urlopen", side_effect=http_err):
            ok, data, err = http_get("https://example.com")
        _assert("http_get: HTTPError returns (False, None, error string)",
                ok is False and data is None and "404" in err,
                f"got: ok={ok!r}, data={data!r}, err={err!r}")
    except Exception as e:
        _fail("http_get: HTTPError", str(e))

    # URLError
    try:
        url_err = urllib.error.URLError("Connection refused")
        with patch("urllib.request.urlopen", side_effect=url_err):
            ok, data, err = http_get("https://example.com")
        _assert("http_get: URLError returns (False, None, error string)",
                ok is False and data is None and len(err) > 0,
                f"got: ok={ok!r}, data={data!r}, err={err!r}")
    except Exception as e:
        _fail("http_get: URLError", str(e))

    # Timeout (generic Exception path)
    try:
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            ok, data, err = http_get("https://example.com")
        _assert("http_get: timeout returns (False, None, error string)",
                ok is False and data is None and len(err) > 0,
                f"got: ok={ok!r}, data={data!r}, err={err!r}")
    except Exception as e:
        _fail("http_get: timeout", str(e))

    # ---------------------------------------------------------------
    # download_file
    # ---------------------------------------------------------------

    # Success with progress_cb
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="torch_netops_test_")
        dest = os.path.join(tmp_dir, "downloaded.bin")
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Length": "11"}
        mock_resp.read.side_effect = [b"hello world", b""]
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        progress_calls = []
        def mock_progress(downloaded, total):
            progress_calls.append((downloaded, total))

        with patch("urllib.request.urlopen", return_value=mock_resp):
            ok, msg = download_file("https://example.com/file.bin", dest, progress_cb=mock_progress)
        _assert("download_file: success returns (True, message)",
                ok is True and "11" in msg,
                f"got: ok={ok!r}, msg={msg!r}")
        _assert("download_file: progress_cb was called",
                len(progress_calls) > 0,
                f"progress_calls={progress_calls!r}")
    except Exception as e:
        _fail("download_file: success", str(e))
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # HTTPError
    try:
        tmp_dir2 = tempfile.mkdtemp(prefix="torch_netops_test_")
        dest2 = os.path.join(tmp_dir2, "fail.bin")
        http_err = urllib.error.HTTPError(
            "https://example.com/file.bin", 500, "Server Error", {}, None
        )
        with patch("urllib.request.urlopen", side_effect=http_err):
            ok, msg = download_file("https://example.com/file.bin", dest2)
        _assert("download_file: HTTPError returns (False, error message)",
                ok is False and "500" in msg,
                f"got: ok={ok!r}, msg={msg!r}")
    except Exception as e:
        _fail("download_file: HTTPError", str(e))
    finally:
        shutil.rmtree(tmp_dir2, ignore_errors=True)

    # ---------------------------------------------------------------
    # fetch_json
    # ---------------------------------------------------------------

    # Valid JSON
    try:
        payload = {"key": "value", "num": 42}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            ok, data, err = fetch_json("https://api.example.com/data")
        _assert("fetch_json: valid JSON returns (True, dict, '')",
                ok is True and data == payload and err == "",
                f"got: ok={ok!r}, data={data!r}, err={err!r}")
    except Exception as e:
        _fail("fetch_json: valid JSON", str(e))

    # Invalid JSON
    try:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json {{"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            ok, data, err = fetch_json("https://api.example.com/data")
        _assert("fetch_json: invalid JSON returns (False, None, error)",
                ok is False and data is None and "JSON" in err,
                f"got: ok={ok!r}, data={data!r}, err={err!r}")
    except Exception as e:
        _fail("fetch_json: invalid JSON", str(e))

    # Network error
    try:
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            ok, data, err = fetch_json("https://api.example.com/data")
        _assert("fetch_json: network error returns (False, None, error)",
                ok is False and data is None and len(err) > 0,
                f"got: ok={ok!r}, data={data!r}, err={err!r}")
    except Exception as e:
        _fail("fetch_json: network error", str(e))

    # ---------------------------------------------------------------
    # fetch_github_tags
    # ---------------------------------------------------------------

    # Paginated response with tag objects
    try:
        import re
        tag_pattern = re.compile(r'^v(\d+)\.(\d+)\.(\d+)$')
        tags_page = [
            {"name": "v1.14.3"},
            {"name": "v1.14.2"},
            {"name": "v1.13.0"},
            {"name": "invalid-tag"},
        ]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(tags_page).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = fetch_github_tags("https://api.github.com/repos/test/tags", tag_pattern)
        _assert("fetch_github_tags: returns sorted version tuples",
                result is not None and len(result) == 3 and result[0] == (1, 14, 3),
                f"got: {result!r}")
    except Exception as e:
        _fail("fetch_github_tags: paginated response", str(e))

    # Network error
    try:
        import re
        tag_pattern = re.compile(r'^v(\d+)\.(\d+)\.(\d+)$')
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            result = fetch_github_tags("https://api.github.com/repos/test/tags", tag_pattern)
        _assert("fetch_github_tags: network error returns None",
                result is None,
                f"got: {result!r}")
    except Exception as e:
        _fail("fetch_github_tags: network error", str(e))

    # ---------------------------------------------------------------
    # check_connectivity
    # ---------------------------------------------------------------

    # Success
    try:
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = check_connectivity()
        _assert("check_connectivity: success returns True",
                result is True,
                f"got: {result!r}")
    except Exception as e:
        _fail("check_connectivity: success", str(e))

    # Failure
    try:
        with patch("urllib.request.urlopen", side_effect=OSError("no network")):
            result = check_connectivity()
        _assert("check_connectivity: failure returns False",
                result is False,
                f"got: {result!r}")
    except Exception as e:
        _fail("check_connectivity: failure", str(e))
