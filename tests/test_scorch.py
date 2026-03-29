"""Tests for scorch.py — Scorched Earth orchestrator.

Covers preflight checks, plan display, plan report saving, and patch
target display.  Skips all interactive menu/wizard functions.
"""
import io
import json
import os
import shutil
import tempfile
from contextlib import redirect_stdout

from torch.tests.harness import _begin_suite, _assert, _ok, _fail, _skip


def _write(path, content):
    """Write content to path, creating parent dirs as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _read(path):
    """Read a file and return its contents."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class _FakeScorchPlan:
    """Minimal stand-in for ScorchPlan with the fields used by scorch.py."""

    def __init__(self):
        self.nuke_maps = set()
        self.keep_maps = set()
        self.vanilla_trainers = []
        self.custom_trainers = []
        self.vanilla_encounters = []
        self.custom_encounters = []
        self.vanilla_scripts = []
        self.vanilla_tilesets = []
        self.custom_tilesets = []
        self.orphaned_layouts = set()
        self.referenced_layouts = set()
        self.vanilla_mapsecs = set()
        self.custom_mapsecs = set()
        self.vanilla_heal_ids = []
        self.custom_heal_ids = []
        self.c_patch_targets = []
        self.errors = []

    def summary(self):
        return {
            "maps":       (len(self.nuke_maps), len(self.keep_maps)),
            "layouts":    (len(self.orphaned_layouts), len(self.referenced_layouts)),
            "trainers":   (len(self.vanilla_trainers), len(self.custom_trainers)),
            "encounters": (len(self.vanilla_encounters), len(self.custom_encounters)),
            "scripts":    (len(self.vanilla_scripts), 0),
            "tilesets":   (len(self.vanilla_tilesets), len(self.custom_tilesets)),
            "mapsecs":    (len(self.vanilla_mapsecs), len(self.custom_mapsecs)),
            "heal_locs":  (len(self.vanilla_heal_ids), len(self.custom_heal_ids)),
            "c_patches":  (len(self.c_patch_targets), 0),
        }


def run_suite():
    _begin_suite("Scorched Earth")

    try:
        from torch.scorch import (
            _preflight_checks,
            _save_plan_report,
            _display_plan,
            _display_patch_targets,
        )
    except ImportError as e:
        _skip("import scorch", str(e))
        return

    # ==== _preflight_checks: missing game_path ====

    try:
        warnings = _preflight_checks("/nonexistent/fake_game_path")
        _assert("preflight: missing game_path warns",
                len(warnings) == 1 and "not found" in warnings[0].lower(),
                f"warnings: {warnings}")
    except Exception as e:
        _fail("preflight: missing game_path", str(e))

    # ==== _preflight_checks: missing map_groups.json ====

    tmp = tempfile.mkdtemp(prefix="torch_scorch_pf_")
    try:
        game = os.path.join(tmp, "game")
        os.makedirs(os.path.join(game, "data", "maps"), exist_ok=True)
        # No map_groups.json at all
        warnings = _preflight_checks(game)
        _assert("preflight: missing map_groups.json warns",
                any("map_groups" in w.lower() for w in warnings),
                f"warnings: {warnings}")
    except Exception as e:
        _fail("preflight: missing map_groups.json", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== _preflight_checks: git repo with uncommitted changes ====

    tmp = tempfile.mkdtemp(prefix="torch_scorch_git_")
    try:
        game = os.path.join(tmp, "game")
        os.makedirs(os.path.join(game, "data", "maps"), exist_ok=True)
        # Create map_groups.json with sentinel so that check passes
        mg_path = os.path.join(game, "data", "maps", "map_groups.json")
        # The sentinel is checked via has_sentinel — we need a real sentinel.
        # has_sentinel looks for a vanilla map name in the groups.
        # For this test, we only care about the git warning, so we can
        # accept the "sentinel not found" warning alongside.
        _write(mg_path, json.dumps({"group_order": ["gTest"], "gTest": ["Custom"]}))

        # Create a .git dir and mock git status by using a real git init
        import subprocess
        subprocess.run(["git", "init"], cwd=game, capture_output=True, timeout=10)
        # Create a file to have uncommitted changes
        _write(os.path.join(game, "dummy.txt"), "uncommitted")
        subprocess.run(["git", "add", "."], cwd=game, capture_output=True, timeout=10)

        warnings = _preflight_checks(game)
        _assert("preflight: git uncommitted warns",
                any("uncommitted" in w.lower() for w in warnings),
                f"warnings: {warnings}")
    except Exception as e:
        _fail("preflight: git uncommitted", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== _preflight_checks: clean setup (valid game dir, map_groups with sentinel, no git) ====

    tmp = tempfile.mkdtemp(prefix="torch_scorch_clean_")
    try:
        game = os.path.join(tmp, "game")
        os.makedirs(os.path.join(game, "data", "maps"), exist_ok=True)
        # Use a real vanilla map name as sentinel
        mg_data = {
            "group_order": ["gMapGroup_LittlerootTown"],
            "gMapGroup_LittlerootTown": ["LittlerootTown"],
        }
        mg_path = os.path.join(game, "data", "maps", "map_groups.json")
        _write(mg_path, json.dumps(mg_data))
        # No .git dir
        warnings = _preflight_checks(game)
        _assert("preflight: clean setup no warnings",
                len(warnings) == 0,
                f"warnings: {warnings}")
    except Exception as e:
        _fail("preflight: clean setup", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== _save_plan_report ====

    tmp = tempfile.mkdtemp(prefix="torch_scorch_report_")
    try:
        game = os.path.join(tmp, "game")
        os.makedirs(game, exist_ok=True)

        plan = _FakeScorchPlan()
        plan.nuke_maps = {"PetalburgCity", "LittlerootTown"}
        plan.keep_maps = {"CustomCity"}
        plan.vanilla_trainers = [("TRAINER_GRUNT_1", 1)]
        plan.c_patch_targets = [{"rel_path": "src/battle.c", "reason": "stub"}]

        report_path = _save_plan_report(game, plan)
        _assert("save_plan_report: file created",
                report_path is not None and os.path.isfile(report_path),
                f"report_path: {report_path}")

        content = _read(report_path)
        _assert("save_plan_report: contains MAPS TO NUKE",
                "MAPS TO NUKE" in content,
                f"content snippet: {content[:200]}")
        _assert("save_plan_report: contains nuke map names",
                "PetalburgCity" in content and "LittlerootTown" in content,
                f"content snippet: {content[:400]}")
        _assert("save_plan_report: contains MAPS TO KEEP",
                "MAPS TO KEEP" in content and "CustomCity" in content,
                f"content snippet: {content[:400]}")
        _assert("save_plan_report: contains C SOURCE PATCHES",
                "C SOURCE PATCHES" in content and "src/battle.c" in content,
                f"content snippet: {content[:600]}")
    except Exception as e:
        _fail("_save_plan_report", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ==== _display_plan: capture stdout ====

    try:
        plan = _FakeScorchPlan()
        plan.nuke_maps = {"MapA", "MapB"}
        plan.keep_maps = {"MapC"}
        plan.vanilla_trainers = [("T1", 1), ("T2", 2)]
        plan.custom_trainers = [("T3", 3)]

        buf = io.StringIO()
        with redirect_stdout(buf):
            _display_plan(plan)
        output = buf.getvalue()

        _assert("display_plan: has Category header",
                "Category" in output,
                f"output: {output[:200]}")
        _assert("display_plan: has Maps row",
                "Maps" in output,
                f"output: {output[:300]}")
        _assert("display_plan: has Total row",
                "Total" in output,
                f"output: {output[:400]}")
    except Exception as e:
        _fail("_display_plan", str(e))

    # ==== _display_patch_targets: with targets ====

    try:
        plan = _FakeScorchPlan()
        plan.c_patch_targets = [
            {"rel_path": "src/battle_main.c", "reason": "Remove trainer references"},
            {"rel_path": "src/field_control.c", "reason": "Remove map scripts"},
        ]

        buf = io.StringIO()
        with redirect_stdout(buf):
            _display_patch_targets(plan)
        output = buf.getvalue()

        _assert("display_patch_targets: has C Source Patches header",
                "C Source Patches" in output,
                f"output: {output[:200]}")
        _assert("display_patch_targets: shows file paths",
                "src/battle_main.c" in output and "src/field_control.c" in output,
                f"output: {output[:300]}")
        _assert("display_patch_targets: shows reasons",
                "Remove trainer references" in output,
                f"output: {output[:400]}")
    except Exception as e:
        _fail("_display_patch_targets: with targets", str(e))

    # ==== _display_patch_targets: empty targets = no output ====

    try:
        plan = _FakeScorchPlan()
        plan.c_patch_targets = []

        buf = io.StringIO()
        with redirect_stdout(buf):
            _display_patch_targets(plan)
        output = buf.getvalue()

        _assert("display_patch_targets: empty = no output",
                output == "",
                f"expected empty, got: {output!r}")
    except Exception as e:
        _fail("_display_patch_targets: empty", str(e))
