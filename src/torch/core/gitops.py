"""Git subprocess wrappers for TORCH.

Stdlib-only (subprocess, shutil).  All public functions return bool, a
(bool, str) tuple, or a safe default — never raise.
"""
# TORCH_MODULE: Git Operations
# TORCH_GROUP: Core
import os
import shutil
import subprocess

GITOPS_VERSION = "1.0"


def git_available():
    """Return True if git is on PATH."""
    return shutil.which("git") is not None


def _run_git(repo_path, args, timeout=30):
    """Run a git command in *repo_path*.

    Returns (stdout, stderr, returncode).  On subprocess error returns
    ("", str(e), -1).
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "git command timed out", -1
    except FileNotFoundError:
        return "", "git not found", -1
    except Exception as e:
        return "", str(e), -1


def git_status(repo_path):
    """Return a dict describing the current git status of *repo_path*.

    Keys: clean (bool), branch (str), modified ([str]), untracked ([str]).
    Returns a safe default dict on error.
    """
    default = {"clean": False, "branch": "", "modified": [], "untracked": []}
    if not os.path.isdir(repo_path):
        return default

    # Current branch
    stdout, _, rc = _run_git(repo_path, ["branch", "--show-current"])
    branch = stdout.strip() if rc == 0 else ""

    # Porcelain status
    stdout, _, rc = _run_git(repo_path, ["status", "--porcelain"])
    if rc != 0:
        return default

    modified = []
    untracked = []
    for line in stdout.splitlines():
        if not line:
            continue
        code = line[:2]
        path = line[3:]
        if code.startswith("?"):
            untracked.append(path)
        else:
            modified.append(path)

    return {
        "clean": not modified and not untracked,
        "branch": branch,
        "modified": modified,
        "untracked": untracked,
    }


def git_clone(url, dest_path, depth=None, branch=None):
    """Clone *url* into *dest_path*.

    If *depth* is given, passes --depth=<depth> for a shallow clone.
    If *branch* is given, passes --branch=<branch> to check out that ref.
    Returns (bool, message).
    """
    args = ["clone"]
    if branch is not None:
        args += [f"--branch={branch}"]
    if depth is not None:
        args += [f"--depth={depth}"]
    args += [url, dest_path]
    stdout, stderr, rc = _run_git(".", args, timeout=120)
    if rc == 0:
        return True, f"Cloned into {dest_path}"
    return False, stderr.strip()


def git_checkout(repo_path, ref):
    """Checkout *ref* (branch, tag, or commit) in *repo_path*.

    Returns (bool, message).
    """
    stdout, stderr, rc = _run_git(repo_path, ["checkout", ref])
    if rc == 0:
        return True, f"Checked out {ref}"
    return False, stderr.strip()


def git_diff_files(repo_path, ref_a, ref_b=None):
    """Return a list of files changed between *ref_a* and *ref_b*.

    If *ref_b* is None, compares *ref_a* against the working tree.
    Returns empty list on error.
    """
    args = ["diff", "--name-only", ref_a]
    if ref_b is not None:
        args.append(ref_b)
    stdout, _, rc = _run_git(repo_path, args)
    if rc != 0:
        return []
    return [line for line in stdout.splitlines() if line]


def git_log(repo_path, n=10):
    """Return the last *n* commits as a list of dicts.

    Each dict has keys: hash, date, message.
    Returns empty list on error.
    """
    fmt = "%H\x1f%ci\x1f%s"
    stdout, _, rc = _run_git(repo_path, ["log", f"-{n}", f"--format={fmt}"])
    if rc != 0:
        return []
    entries = []
    for line in stdout.splitlines():
        parts = line.split("\x1f", 2)
        if len(parts) == 3:
            entries.append({"hash": parts[0], "date": parts[1], "message": parts[2]})
    return entries
