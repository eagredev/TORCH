"""Update suite -- version reading, comparison, package discovery."""
import os
import tempfile
import shutil
import zipfile

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Update")

    try:
        from torch.update import (
            _read_version_from_zip, _compare_versions,
            _find_package_root, _find_update_source,
        )
    except ImportError as e:
        _skip("all tests", f"import failed: {e}")
        return

    # ---------------------------------------------------------------
    # _read_version_from_zip
    # ---------------------------------------------------------------

    # Valid zip with __init__.py containing VERSION
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="torch_update_test_")
        zip_path = os.path.join(tmp_dir, "test_pkg.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("__init__.py", 'VERSION = "1.2.3"\nBUILD_TRACK = "stable"\n')
        result = _read_version_from_zip(zip_path)
        _assert("_read_version_from_zip: extracts VERSION from zip",
                result == "1.2.3",
                f"got: {result!r}")
    except Exception as e:
        _fail("_read_version_from_zip: valid zip", str(e))
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # Zip with no __init__.py
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="torch_update_test_")
        zip_path = os.path.join(tmp_dir, "empty_pkg.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "no init here")
        result = _read_version_from_zip(zip_path)
        _assert("_read_version_from_zip: no __init__.py -> None",
                result is None,
                f"got: {result!r}")
    except Exception as e:
        _fail("_read_version_from_zip: no __init__.py", str(e))
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # Zip with __init__.py but no VERSION line
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="torch_update_test_")
        zip_path = os.path.join(tmp_dir, "no_ver.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("__init__.py", '# no version here\nNAME = "torch"\n')
        result = _read_version_from_zip(zip_path)
        _assert("_read_version_from_zip: no VERSION line -> None",
                result is None,
                f"got: {result!r}")
    except Exception as e:
        _fail("_read_version_from_zip: no VERSION line", str(e))
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ---------------------------------------------------------------
    # _compare_versions
    # ---------------------------------------------------------------
    try:
        _assert("_compare_versions: 1.0.0 < 1.0.1 -> -1",
                _compare_versions("1.0.0", "1.0.1") == -1,
                f"got: {_compare_versions('1.0.0', '1.0.1')!r}")
    except Exception as e:
        _fail("_compare_versions: less than", str(e))

    try:
        _assert("_compare_versions: 1.0.0 == 1.0.0 -> 0",
                _compare_versions("1.0.0", "1.0.0") == 0,
                f"got: {_compare_versions('1.0.0', '1.0.0')!r}")
    except Exception as e:
        _fail("_compare_versions: equal", str(e))

    try:
        _assert("_compare_versions: 2.1.0 > 1.9.9 -> 1",
                _compare_versions("2.1.0", "1.9.9") == 1,
                f"got: {_compare_versions('2.1.0', '1.9.9')!r}")
    except Exception as e:
        _fail("_compare_versions: greater than", str(e))

    # ---------------------------------------------------------------
    # _find_package_root
    # ---------------------------------------------------------------

    # __init__.py at root
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="torch_update_test_")
        with open(os.path.join(tmp_dir, "__init__.py"), "w") as f:
            f.write("# root init\n")
        result = _find_package_root(tmp_dir)
        _assert("_find_package_root: __init__.py at root -> returns root",
                result == tmp_dir,
                f"got: {result!r}")
    except Exception as e:
        _fail("_find_package_root: root __init__.py", str(e))
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # __init__.py in subdirectory
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="torch_update_test_")
        sub = os.path.join(tmp_dir, "torch_pkg")
        os.makedirs(sub)
        with open(os.path.join(sub, "__init__.py"), "w") as f:
            f.write("# sub init\n")
        result = _find_package_root(tmp_dir)
        _assert("_find_package_root: __init__.py in subdir -> returns subdir",
                result == sub,
                f"got: {result!r}")
    except Exception as e:
        _fail("_find_package_root: subdir __init__.py", str(e))
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ---------------------------------------------------------------
    # _find_update_source
    # ---------------------------------------------------------------

    # Explicit path to a valid zip
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="torch_update_test_")
        zip_path = os.path.join(tmp_dir, "torch_v1.5_stable.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("__init__.py", 'VERSION = "1.5.0"\n')
        path, ver = _find_update_source([zip_path])
        _assert("_find_update_source: explicit path returns (path, version)",
                path == zip_path and ver == "1.5.0",
                f"got: path={path!r}, ver={ver!r}")
    except Exception as e:
        _fail("_find_update_source: explicit path", str(e))
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # Explicit path to missing file
    try:
        path, ver = _find_update_source(["/tmp/torch_nonexistent_xyz.zip"])
        _assert("_find_update_source: missing file -> (None, None)",
                path is None and ver is None,
                f"got: path={path!r}, ver={ver!r}")
    except Exception as e:
        _fail("_find_update_source: missing file", str(e))
