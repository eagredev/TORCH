"""TORCH Test Harness — Phase 2.13

Run with:  torchdev test
           torchdev test compiler           (single suite)
           torchdev test compiler::label     (single test by name substring)
           torchdev test --fail-fast         (stop on first failure)
           torchdev test --quiet             (only show failures + summary)
           torchdev test --quiet compiler    (combine flags)
           python3 ~/torch_dev/ test
"""
import sys
import time
from torch.tests.harness import (
    _summary, _BOLD, _DIM, _RST, _results,
    _quiet, _fail_fast, _test_filter, _aborted,
)
from torch.colours import BAR, DIM, RST
import torch.tests.harness as _harness

# All test suites — import order doesn't matter
from torch.tests import (
    test_compiler, test_decompiler, test_script_model, test_battle_io,
    test_gamedata, test_registry, test_config,
    test_filewriter, test_names, test_textutils,
    test_cleanup, test_verified_snapshots, test_build_assistant,
    test_smoke, test_sync, test_scorch_patcher,
    test_scorch_scanner, test_cleanup_packages,
    test_torscript, test_battle_wizard,
    test_backup, test_integration,
    test_upgrade, test_expansion_compat,
    test_project_files, test_colours,
    test_list_widget,
    test_check, test_scorch_writer,
    test_battle_card, test_battle_migrator,
    test_map_scanner, test_studio, test_data,
    test_pickers, test_sandbox,
    test_encounter_editor, test_species_data,
    test_config_tuner, test_dex,
    test_fork, test_new_project,
    test_script_editor,
    test_script_hub,
    test_heal_locations,
    test_vanilla_maps,
    test_npc_detection,
    test_asset_manager,
    test_templates,
    test_npc_editor,
    test_asset_browser,
    test_shop_editor,
    test_item_editor,
    test_move_editor,
    test_learnset_editor,
    test_tileset_assistant,
    test_map_explorer,
    test_battle_partners,
    test_flag_scanner,
    test_give_and_coord,
    test_main_menu,
    test_cleanup_scanner,
    test_ui_helpers,
    test_update,
    test_netops,
    test_gitops,
    test_battle_manager,
    test_vault,
    test_flag_browser,
    test_scorch,
    test_web_server,
    test_scene_sim,
    test_web_gui,
    test_missing_coverage,
    test_pokemon_patch,
    test_building_templates,
    test_api_npcs,
    test_api_npc_editor,
    test_template_stamper,
    test_game_versions,
    test_midi_synth,
    test_music_player,
    test_music_browser,
    test_inc_decompiler,
    test_custom_stamps,
    test_api_stamps,
    test_collision,
)

_SUITES = [
    ("smoke",               test_smoke),
    ("compiler",            test_compiler),
    ("decompiler",          test_decompiler),
    ("script_model",        test_script_model),
    ("battle_io",           test_battle_io),
    ("gamedata",            test_gamedata),
    ("registry",            test_registry),
    ("config",              test_config),
    ("filewriter",          test_filewriter),
    ("names",               test_names),
    ("textutils",           test_textutils),
    ("cleanup",             test_cleanup),
    ("verified_snapshots",  test_verified_snapshots),
    ("build_assistant",     test_build_assistant),
    ("sync",                test_sync),
    ("scorch_patcher",      test_scorch_patcher),
    ("scorch_scanner",      test_scorch_scanner),
    ("cleanup_packages",    test_cleanup_packages),
    ("torscript",           test_torscript),
    ("battle_wizard",       test_battle_wizard),
    ("backup",              test_backup),
    ("integration",         test_integration),
    ("upgrade",             test_upgrade),
    ("expansion_compat",    test_expansion_compat),
    ("project_files",       test_project_files),
    ("colours",             test_colours),
    ("list_widget",         test_list_widget),
    ("check",               test_check),
    ("scorch_writer",       test_scorch_writer),
    ("battle_card",         test_battle_card),
    ("battle_migrator",     test_battle_migrator),
    ("map_scanner",         test_map_scanner),
    ("studio",              test_studio),
    ("data",                test_data),
    ("pickers",             test_pickers),
    ("sandbox",             test_sandbox),
    ("encounter_editor",    test_encounter_editor),
    ("species_data",        test_species_data),
    ("config_tuner",        test_config_tuner),
    ("dex",                 test_dex),
    ("fork",                test_fork),
    ("new_project",         test_new_project),
    ("script_editor",       test_script_editor),
    ("script_hub",          test_script_hub),
    ("heal_locations",      test_heal_locations),
    ("vanilla_maps",        test_vanilla_maps),
    ("npc_detection",       test_npc_detection),
    ("asset_manager",       test_asset_manager),
    ("templates",           test_templates),
    ("npc_editor",          test_npc_editor),
    ("asset_browser",       test_asset_browser),
    ("shop_editor",         test_shop_editor),
    ("item_editor",         test_item_editor),
    ("move_editor",         test_move_editor),
    ("learnset_editor",    test_learnset_editor),
    ("tileset_assistant",  test_tileset_assistant),
    ("map_explorer",       test_map_explorer),
    ("battle_partners",    test_battle_partners),
    ("flag_scanner",       test_flag_scanner),
    ("give_and_coord",     test_give_and_coord),
    ("main_menu",          test_main_menu),
    ("cleanup_scanner",    test_cleanup_scanner),
    ("ui_helpers",         test_ui_helpers),
    ("update",             test_update),
    ("netops",             test_netops),
    ("gitops",             test_gitops),
    ("battle_manager",     test_battle_manager),
    ("vault",              test_vault),
    ("flag_browser",       test_flag_browser),
    ("scorch",             test_scorch),
    ("web_server",         test_web_server),
    ("scene_sim",          test_scene_sim),
    ("web_gui",            test_web_gui),
    ("missing_coverage",   test_missing_coverage),
    ("pokemon_patch",      test_pokemon_patch),
    ("building_templates", test_building_templates),
    ("api_npcs",           test_api_npcs),
    ("api_npc_editor",     test_api_npc_editor),
    ("template_stamper",   test_template_stamper),
    ("game_versions",      test_game_versions),
    ("midi_synth",         test_midi_synth),
    ("music_player",       test_music_player),
    ("music_browser",      test_music_browser),
    ("inc_decompiler",     test_inc_decompiler),
    ("custom_stamps",      test_custom_stamps),
    ("api_stamps",         test_api_stamps),
    ("collision",          test_collision),
]


def run_all_tests(suite_filter=None, quiet=False, fail_fast=False):
    """Run test suites. Returns True if all passed.

    *suite_filter* can be:
    - A suite name: "battle_wizard"
    - A suite::test filter: "compiler::label_validation"
    - A file path: "tests/test_battle_wizard.py" or the full absolute path
    - A pytest-style "-- path" argument (the "--" is stripped by the caller)
    """
    # Reset results and options for clean run
    _results.clear()
    _harness._quiet = quiet
    _harness._fail_fast = fail_fast
    _harness._test_filter = None
    _harness._aborted = False

    test_filter = None

    # Normalise file-path filters to suite names
    if suite_filter:
        # Strip leading "--" (common pytest convention agents try)
        suite_filter = suite_filter.lstrip("-").strip()

        # Handle suite::test_name filter
        if "::" in suite_filter:
            parts = suite_filter.split("::", 1)
            suite_filter = parts[0]
            test_filter = parts[1]
            _harness._test_filter = test_filter

        # Handle file paths like "tests/test_battle_wizard.py"
        import os
        base = os.path.basename(suite_filter)
        if base.startswith("test_") and base.endswith(".py"):
            suite_filter = base[5:-3]  # "test_battle_wizard.py" -> "battle_wizard"
        elif base.startswith("test_"):
            suite_filter = base[5:]

    print()
    print(BAR)
    label = f"  {_BOLD}TORCH Test Harness{_RST}  {DIM}(Phase 2.13){RST}"
    flags = []
    if quiet:
        flags.append("quiet")
    if fail_fast:
        flags.append("fail-fast")
    if test_filter:
        flags.append(f"filter: {test_filter}")
    if flags:
        label += f"  {DIM}[{', '.join(flags)}]{RST}"
    print(label)
    print(BAR)

    suite_times = []
    suites_run = 0

    for name, module in _SUITES:
        if suite_filter and name != suite_filter:
            continue
        if _harness._aborted:
            break

        t0 = time.monotonic()
        before = len(_results)
        module.run_suite()
        elapsed = time.monotonic() - t0
        after = len(_results)
        count = after - before
        suite_times.append((name, elapsed, count))
        suites_run += 1

    # Print timing summary
    print()
    print(BAR)
    ok = _summary()

    if suites_run > 1 and not quiet:
        # Show per-suite timing (sorted slowest first, top 10)
        suite_times.sort(key=lambda x: -x[1])
        slow = [s for s in suite_times if s[1] >= 0.1]
        if slow:
            print(f"  {DIM}Slowest suites:{RST}")
            for name, elapsed, count in slow[:10]:
                print(f"    {DIM}{elapsed:5.1f}s  {name} ({count} tests){RST}")
            print()

    if _harness._aborted:
        print(f"  {_BOLD}Stopped after first failure (--fail-fast){_RST}")
        print()

    total_time = sum(t for _, t, _ in suite_times)
    print(f"  {DIM}Total: {total_time:.1f}s across {suites_run} suite{'s' if suites_run != 1 else ''}{RST}")
    print()

    return ok
