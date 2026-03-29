"""Smoke tests -- verify all modules import and key functions exist."""
import importlib

from torch.tests.harness import _begin_suite, _ok, _fail, _assert


_MODULES = [
    "torch.backup",
    "torch.battle_card",
    "torch.battle_io",
    "torch.battle_manager",
    "torch.battle_migrator",
    "torch.battle_wizard",
    "torch.cleanup",
    "torch.cleanup_packages",
    "torch.cleanup_scanner",
    "torch.cleanup_writer",
    "torch.compiler",
    "torch.config",
    "torch.config_ui",
    "torch.data",
    "torch.filewriter",
    "torch.gamedata",
    "torch.gitops",
    "torch.init",
    "torch.map_scanner",
    "torch.names",
    "torch.netops",
    "torch.pickers",
    "torch.dex",
    "torch.registry",
    "torch.script_editor",
    "torch.script_hub",
    "torch.script_model",
    "torch.script_movements",
    "torch.scorch",
    "torch.scorch_patcher",
    "torch.scorch_scanner",
    "torch.scorch_writer",
    "torch.studio",
    "torch.sync",
    "torch.textutils",
    "torch.ui",
    "torch.update",
    "torch.vault",
    "torch.verified_snapshots",
]

_KEY_FUNCTIONS = [
    ("torch.compiler",            "compile_script"),
    ("torch.sync",                "sync_map"),
    ("torch.config",              "load_config"),
    ("torch.registry",            "load_registry"),
    ("torch.verified_snapshots",  "create_verified_snapshot"),
]


def run_suite():
    _begin_suite("Smoke (imports + key functions)")

    # --- Module imports ---
    loaded = {}
    for mod_name in _MODULES:
        short = mod_name.replace("torch.", "")
        try:
            loaded[mod_name] = importlib.import_module(mod_name)
            _ok(f"import {short}")
        except Exception as exc:
            _fail(f"import {short}", str(exc))

    # --- Version checks ---
    import torch
    _assert("VERSION is non-empty string",
            isinstance(torch.VERSION, str) and len(torch.VERSION) > 0,
            f"got {torch.VERSION!r}")

    _assert("VERSION contains a digit",
            any(c.isdigit() for c in torch.VERSION),
            f"got {torch.VERSION!r}")

    _assert("BUILD_TRACK is valid",
            torch.BUILD_TRACK in ("dev", "stable", "experimental", "unknown"),
            f"got {torch.BUILD_TRACK!r}")

    # --- Key function existence ---
    for mod_name, func_name in _KEY_FUNCTIONS:
        short = mod_name.replace("torch.", "")
        mod = loaded.get(mod_name)
        if mod is None:
            _fail(f"{short}.{func_name} exists",
                  f"module {mod_name} failed to import")
            continue
        has_it = hasattr(mod, func_name) and callable(getattr(mod, func_name))
        _assert(f"{short}.{func_name} exists", has_it,
                f"not found or not callable on {mod_name}")
