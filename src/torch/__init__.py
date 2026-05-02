"""TORCH — The Open ROM Creation Hub for pokeemerald-expansion."""
# TORCH_MODULE: Version Info
# TORCH_GROUP: Core
import os as _os

VERSION = "0.4.0"
BATTLE_VERSION = "0.2.11"
SCRIPT_VERSION = "0.2.4"
MAP_SCANNER_VERSION = "0.1.2"
SHARED_INFRA_VERSION = "0.1.0"
TEST_HARNESS_VERSION = "0.2.5"
SCORCH_VERSION = "0.2.6"
VAULT_VERSION = "0.2.0"
VERIFIED_VERSION = "0.1.0"
UPGRADE_VERSION = "0.1.0"
ENCOUNTER_VERSION = "0.1.1"
HEAL_VERSION = "0.1.0"
TUNER_VERSION = "0.1.1"
DEX_VERSION = "0.2.1"
MAP_EXPLORER_VERSION = "0.1.0"

# Detect which install is running based on package path + optional track marker.
# "stable"       — installed via installer to ~/torch_stable/, stable track
# "experimental" — installed via installer, experimental track
# "dev"          — active dev copy at ~/torch_dev/
# "unknown"      — running from somewhere else
_PACKAGE_DIR = _os.path.realpath(_os.path.dirname(_os.path.abspath(__file__)))
_HOME = _os.path.expanduser("~")
if _PACKAGE_DIR == _os.path.join(_HOME, "torch_dev"):
    BUILD_TRACK = "dev"
elif _PACKAGE_DIR == _os.path.join(_HOME, "torch_stable"):
    # Read track marker written by installer; default to stable
    _marker = _os.path.join(_PACKAGE_DIR, "_track.txt")
    try:
        with open(_marker, encoding="utf-8") as _f:
            _track_raw = _f.read().strip()
        BUILD_TRACK = _track_raw if _track_raw in ("stable", "experimental") else "stable"
    except OSError:
        BUILD_TRACK = "stable"
elif _PACKAGE_DIR == _os.path.join(_HOME, "torch_exp"):
    # Experimental install location — read track marker; default to experimental
    _marker = _os.path.join(_PACKAGE_DIR, "_track.txt")
    try:
        with open(_marker, encoding="utf-8") as _f:
            _track_raw = _f.read().strip()
        BUILD_TRACK = _track_raw if _track_raw in ("stable", "experimental") else "experimental"
    except OSError:
        BUILD_TRACK = "experimental"
else:
    BUILD_TRACK = "unknown"


# ── Backward-compatible module aliases ──────────────────────────────────────
# Modules have been reorganised into subpackages (core/, compiler/, editors/,
# battle/, scorch/, project/, script/, studio/). These aliases ensure that
# existing `from torch.module_name import ...` imports continue to work.

import importlib as _importlib
import importlib.abc as _importlib_abc
import importlib.machinery as _importlib_machinery
import sys as _sys

_MODULE_MAP = {
    # core/
    "colours": "core", "config": "core", "data": "core",
    "expansion_compat": "core", "filewriter": "core", "gamedata": "core",
    "gitops": "core", "list_widget": "core", "names": "core",
    "netops": "core", "pickers": "core", "project_files": "core",
    "registry": "core", "textutils": "core", "ui": "core",
    "vanilla_maps": "core",
    # compiler/
    "compiler": "compiler", "decompiler": "compiler",
    "inc_decompiler": "compiler", "camera_patch": "compiler",
    "script_model": "compiler", "script_movements": "compiler",
    "scene_sim": "compiler", "self_flags": "compiler",
    "bulk_decompile": "compiler",
    # editors/
    "npc_editor": "editors", "encounter_editor": "editors", "dex": "editors",
    "flag_browser": "editors", "flag_scanner": "editors",
    "var_scanner": "editors", "shop_editor": "editors",
    "item_editor": "editors", "learnset_editor": "editors",
    "move_editor": "editors", "heal_locations": "editors",
    "config_tuner": "editors",
    # battle/
    "battle_card": "battle", "battle_io": "battle",
    "battle_manager": "battle", "battle_migrator": "battle",
    "battle_partners": "battle", "battle_wizard": "battle",
    # scorch/
    "scorch": "scorch", "scorch_scanner": "scorch",
    "scorch_writer": "scorch", "scorch_patcher": "scorch",
    "cleanup": "scorch", "cleanup_scanner": "scorch",
    "cleanup_writer": "scorch", "cleanup_packages": "scorch",
    # project/
    "backup": "project", "fork": "project", "sandbox": "project",
    "init": "project", "new_project": "project", "update": "project",
    "upgrade": "project", "vault": "project",
    "verified_snapshots": "project", "game_versions": "project",
    "promote": "project", "check": "project",
    # script/
    "script_editor": "script", "script_hub": "script", "sync": "script",
    "templates": "script", "chain_model": "script", "chain_sync": "script",
    # studio/
    "studio": "studio", "map_explorer": "studio", "map_scanner": "studio",
    "asset_browser": "studio", "asset_manager": "studio",
    "building_templates": "studio", "template_stamper": "studio",
    "tileset_assistant": "studio", "custom_stamps": "studio",
    "music_browser": "studio", "music_player": "studio",
    "midi_synth": "studio", "pokemon_patch": "studio",
    "config_ui": "studio",
}


# Names that collide with subpackage directories must be excluded from
# the finder — Python resolves these naturally as packages.
_SUBPACKAGE_NAMES = frozenset({
    "core", "compiler", "editors", "battle", "scorch",
    "project", "script", "studio",
})


class _TorchModuleFinder(_importlib_abc.MetaPathFinder):
    """Lazy import redirector: `torch.X` -> `torch.<subpkg>.X` on demand.

    Only intercepts names that are in _MODULE_MAP but NOT also a real
    subpackage directory. When a module name collides with its subpackage
    name (e.g. torch.compiler -> torch/compiler/ package AND
    torch/compiler/compiler.py module), the subpackage takes priority
    and the module is accessed as torch.compiler.compiler.
    """

    def find_spec(self, fullname, path, target=None):
        if not fullname.startswith("torch."):
            return None
        short = fullname[len("torch."):]
        # Don't intercept subpackage names or nested paths
        if "." in short or short in _SUBPACKAGE_NAMES:
            return None
        if short in _MODULE_MAP:
            real = f"torch.{_MODULE_MAP[short]}.{short}"
            return _importlib_machinery.ModuleSpec(
                fullname, _TorchAliasLoader(real))
        return None


class _TorchAliasLoader(_importlib_abc.Loader):
    """Loads a module by importing its real path and aliasing it."""

    def __init__(self, real_name):
        self._real_name = real_name

    def create_module(self, spec):
        return None  # Use default semantics

    def exec_module(self, module):
        real = _importlib.import_module(self._real_name)
        # Replace the alias module with the real one in sys.modules
        _sys.modules[module.__name__] = real
        _sys.modules[self._real_name] = real


_sys.meta_path.insert(0, _TorchModuleFinder())
