"""Git Operations suite -- git_available, _run_git, status, log, diff, clone, checkout."""
import os
import tempfile
import shutil
import subprocess
from unittest.mock import patch, MagicMock

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Git Operations")

    try:
        from torch.gitops import (
            git_available, _run_git, git_status, git_log,
            git_diff_files, git_clone, git_checkout,
        )
    except ImportError as e:
        _skip("all tests", f"import failed: {e}")
        return

    # ---------------------------------------------------------------
    # git_available
    # ---------------------------------------------------------------
    try:
        with patch("shutil.which", return_value="/usr/bin/git"):
            _assert("git_available: returns True when git found",
                    git_available() is True,
                    "expected True")
    except Exception as e:
        _fail("git_available: True", str(e))

    try:
        with patch("shutil.which", return_value=None):
            _assert("git_available: returns False when git missing",
                    git_available() is False,
                    "expected False")
    except Exception as e:
        _fail("git_available: False", str(e))

    # ---------------------------------------------------------------
    # _run_git (mocked subprocess)
    # ---------------------------------------------------------------
    try:
        mock_result = MagicMock()
        mock_result.stdout = "output text"
        mock_result.stderr = ""
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            stdout, stderr, rc = _run_git("/tmp", ["status"])
        _assert("_run_git: success returns (stdout, stderr, 0)",
                stdout == "output text" and stderr == "" and rc == 0,
                f"got: stdout={stdout!r}, stderr={stderr!r}, rc={rc!r}")
    except Exception as e:
        _fail("_run_git: success", str(e))

    try:
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30)):
            stdout, stderr, rc = _run_git("/tmp", ["status"])
        _assert("_run_git: timeout returns ('', 'timed out', -1)",
                rc == -1 and "timed out" in stderr,
                f"got: stderr={stderr!r}, rc={rc!r}")
    except Exception as e:
        _fail("_run_git: timeout", str(e))

    try:
        with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            stdout, stderr, rc = _run_git("/tmp", ["status"])
        _assert("_run_git: FileNotFoundError returns ('', 'git not found', -1)",
                rc == -1 and "git not found" in stderr,
                f"got: stderr={stderr!r}, rc={rc!r}")
    except Exception as e:
        _fail("_run_git: FileNotFoundError", str(e))

    # ---------------------------------------------------------------
    # Real git tests (require git on PATH)
    # ---------------------------------------------------------------
    _has_git = shutil.which("git") is not None
    if not _has_git:
        _skip("git_status: clean repo", "git not available")
        _skip("git_status: dirty repo", "git not available")
        _skip("git_log: after commit", "git not available")
        _skip("git_diff_files: modified file", "git not available")
    else:
        # git_status: clean repo
        tmp_dir = None
        try:
            tmp_dir = tempfile.mkdtemp(prefix="torch_gitops_test_")
            subprocess.run(["git", "init", tmp_dir], capture_output=True, timeout=10)
            subprocess.run(["git", "-C", tmp_dir, "config", "user.email", "test@test.com"],
                           capture_output=True, timeout=10)
            subprocess.run(["git", "-C", tmp_dir, "config", "user.name", "Test"],
                           capture_output=True, timeout=10)
            # Create initial commit so branch exists
            dummy = os.path.join(tmp_dir, "dummy.txt")
            with open(dummy, "w") as f:
                f.write("init\n")
            subprocess.run(["git", "-C", tmp_dir, "add", "."], capture_output=True, timeout=10)
            subprocess.run(["git", "-C", tmp_dir, "commit", "-m", "init"],
                           capture_output=True, timeout=10)
            status = git_status(tmp_dir)
            _assert("git_status: clean repo",
                    status["clean"] is True and len(status["modified"]) == 0 and len(status["untracked"]) == 0,
                    f"got: {status!r}")
        except Exception as e:
            _fail("git_status: clean repo", str(e))
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        # git_status: dirty repo with untracked file
        tmp_dir = None
        try:
            tmp_dir = tempfile.mkdtemp(prefix="torch_gitops_test_")
            subprocess.run(["git", "init", tmp_dir], capture_output=True, timeout=10)
            subprocess.run(["git", "-C", tmp_dir, "config", "user.email", "test@test.com"],
                           capture_output=True, timeout=10)
            subprocess.run(["git", "-C", tmp_dir, "config", "user.name", "Test"],
                           capture_output=True, timeout=10)
            # Initial commit
            dummy = os.path.join(tmp_dir, "dummy.txt")
            with open(dummy, "w") as f:
                f.write("init\n")
            subprocess.run(["git", "-C", tmp_dir, "add", "."], capture_output=True, timeout=10)
            subprocess.run(["git", "-C", tmp_dir, "commit", "-m", "init"],
                           capture_output=True, timeout=10)
            # Add an untracked file
            with open(os.path.join(tmp_dir, "new_file.txt"), "w") as f:
                f.write("untracked\n")
            status = git_status(tmp_dir)
            _assert("git_status: dirty repo with untracked file",
                    status["clean"] is False and "new_file.txt" in status["untracked"],
                    f"got: {status!r}")
        except Exception as e:
            _fail("git_status: dirty repo", str(e))
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        # git_log: after a commit
        tmp_dir = None
        try:
            tmp_dir = tempfile.mkdtemp(prefix="torch_gitops_test_")
            subprocess.run(["git", "init", tmp_dir], capture_output=True, timeout=10)
            subprocess.run(["git", "-C", tmp_dir, "config", "user.email", "test@test.com"],
                           capture_output=True, timeout=10)
            subprocess.run(["git", "-C", tmp_dir, "config", "user.name", "Test"],
                           capture_output=True, timeout=10)
            dummy = os.path.join(tmp_dir, "file.txt")
            with open(dummy, "w") as f:
                f.write("content\n")
            subprocess.run(["git", "-C", tmp_dir, "add", "."], capture_output=True, timeout=10)
            subprocess.run(["git", "-C", tmp_dir, "commit", "-m", "test commit message"],
                           capture_output=True, timeout=10)
            entries = git_log(tmp_dir, n=5)
            _assert("git_log: returns commit entries",
                    len(entries) >= 1 and entries[0]["message"] == "test commit message",
                    f"got: {entries!r}")
            _assert("git_log: entry has hash, date, message",
                    all(k in entries[0] for k in ("hash", "date", "message")),
                    f"keys: {list(entries[0].keys())!r}")
        except Exception as e:
            _fail("git_log: after commit", str(e))
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        # git_diff_files: after modifying a tracked file
        tmp_dir = None
        try:
            tmp_dir = tempfile.mkdtemp(prefix="torch_gitops_test_")
            subprocess.run(["git", "init", tmp_dir], capture_output=True, timeout=10)
            subprocess.run(["git", "-C", tmp_dir, "config", "user.email", "test@test.com"],
                           capture_output=True, timeout=10)
            subprocess.run(["git", "-C", tmp_dir, "config", "user.name", "Test"],
                           capture_output=True, timeout=10)
            tracked = os.path.join(tmp_dir, "tracked.txt")
            with open(tracked, "w") as f:
                f.write("original\n")
            subprocess.run(["git", "-C", tmp_dir, "add", "."], capture_output=True, timeout=10)
            subprocess.run(["git", "-C", tmp_dir, "commit", "-m", "initial"],
                           capture_output=True, timeout=10)
            # Modify the tracked file
            with open(tracked, "w") as f:
                f.write("modified\n")
            diff_files = git_diff_files(tmp_dir, "HEAD")
            _assert("git_diff_files: detects modified file",
                    "tracked.txt" in diff_files,
                    f"got: {diff_files!r}")
        except Exception as e:
            _fail("git_diff_files: modified file", str(e))
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    # ---------------------------------------------------------------
    # git_clone (mocked)
    # ---------------------------------------------------------------
    try:
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            ok, msg = git_clone("https://github.com/test/repo.git", "/tmp/dest")
        _assert("git_clone: success returns (True, message)",
                ok is True and "dest" in msg.lower() or "/tmp/dest" in msg,
                f"got: ok={ok!r}, msg={msg!r}")
    except Exception as e:
        _fail("git_clone: success", str(e))

    try:
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "fatal: repository not found"
        mock_result.returncode = 128
        with patch("subprocess.run", return_value=mock_result):
            ok, msg = git_clone("https://github.com/test/repo.git", "/tmp/dest")
        _assert("git_clone: failure returns (False, error message)",
                ok is False and "not found" in msg,
                f"got: ok={ok!r}, msg={msg!r}")
    except Exception as e:
        _fail("git_clone: failure", str(e))

    # ---------------------------------------------------------------
    # git_checkout (mocked)
    # ---------------------------------------------------------------
    try:
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            ok, msg = git_checkout("/tmp/repo", "main")
        _assert("git_checkout: success returns (True, message)",
                ok is True and "main" in msg,
                f"got: ok={ok!r}, msg={msg!r}")
    except Exception as e:
        _fail("git_checkout: success", str(e))

    try:
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "error: pathspec 'nonexistent' did not match"
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            ok, msg = git_checkout("/tmp/repo", "nonexistent")
        _assert("git_checkout: failure returns (False, error message)",
                ok is False and "nonexistent" in msg,
                f"got: ok={ok!r}, msg={msg!r}")
    except Exception as e:
        _fail("git_checkout: failure", str(e))

    # ---------------------------------------------------------------
    # git_status: nonexistent directory
    # ---------------------------------------------------------------
    try:
        status = git_status("/tmp/torch_nonexistent_repo_xyz")
        _assert("git_status: nonexistent dir returns safe default",
                status["clean"] is False and status["branch"] == "",
                f"got: {status!r}")
    except Exception as e:
        _fail("git_status: nonexistent dir", str(e))
