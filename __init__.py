"""TORCH — The Open ROM Creation Hub for pokeemerald-expansion."""
# TORCH_MODULE: Version Info
# TORCH_GROUP: Core
import os as _os

VERSION = "0.3.7"
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
