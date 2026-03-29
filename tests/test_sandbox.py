"""Sandbox (fork) compat shim — delegates to test_fork."""
from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Sandbox  (compat shim via fork)")

    try:
        import torch.sandbox as sandbox_mod
    except ImportError as e:
        _skip("sandbox compat import", f"import failed: {e}")
        return

    # Verify the shim re-exports work
    _assert(
        "shim: sandbox_command is fork_command",
        hasattr(sandbox_mod, "sandbox_command"),
        "sandbox_command not found on shim"
    )
    _assert(
        "shim: _sanitize_name available",
        hasattr(sandbox_mod, "_sanitize_name"),
        "_sanitize_name not found on shim"
    )
    _assert(
        "shim: _sanitize_name works through shim",
        sandbox_mod._sanitize_name("My Fork") == "my-fork",
        f"got: {sandbox_mod._sanitize_name('My Fork')!r}"
    )
    _assert(
        "shim: _load_registry available",
        hasattr(sandbox_mod, "_load_registry"),
        "_load_registry not found on shim"
    )
