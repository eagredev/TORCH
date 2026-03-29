"""Expansion Upgrade suite — version parsing, detection, and merge logic."""
import json
import os
import shutil
import tempfile

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Expansion Upgrade")

    try:
        from torch.expansion_compat import (
            detect_expansion_version,
            version_str as _version_tuple_to_str,
            parse_version_str as _str_to_version_tuple,
        )
        from torch.upgrade import (
            TAG_PATTERN,
            _check_disk_space,
            _detect_custom_maps,
            _detect_custom_map_groups,
            _detect_custom_tilesets,
            _detect_makefile_customizations,
            _detect_modified_vanilla_files,
            _reinject_map_groups,
            _reinject_layouts,
            _reinject_region_map_sections,
            _reinject_heal_locations,
            _reinject_custom_tilesets,
            _detect_custom_layouts,
            _detect_custom_region_map_sections,
            _detect_custom_heal_locations,
            _extract_tileset_c_lines,
            _should_preserve,
            _read_map_groups,
            _read_map_groups_raw,
            _read_json_safe,
            UpgradeManifest,
        )
    except ImportError as e:
        _skip("all upgrade tests", f"import failed: {e}")
        return

    # ================================================================
    # VERSION PARSING (5 tests)
    # ================================================================

    # Test 1: Standard expansion.h parsing
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        hdir = os.path.join(tmp, "include", "constants")
        os.makedirs(hdir)
        with open(os.path.join(hdir, "expansion.h"), "w") as f:
            f.write("#ifndef GUARD_CONSTANTS_EXPANSION_H\n")
            f.write("#define GUARD_CONSTANTS_EXPANSION_H\n\n")
            f.write("#define EXPANSION_VERSION_MAJOR 1\n")
            f.write("#define EXPANSION_VERSION_MINOR 7\n")
            f.write("#define EXPANSION_VERSION_PATCH 4\n")
            f.write("\n#endif\n")
        result = detect_expansion_version(tmp)
        _assert("version parse: standard expansion.h",
                result == (1, 7, 4),
                f"got {result!r}")
    except Exception as e:
        _fail("version parse: standard expansion.h", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 2: Missing expansion.h
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        result = detect_expansion_version(tmp)
        _assert("version parse: missing file returns None",
                result is None,
                f"got {result!r}")
    except Exception as e:
        _fail("version parse: missing file returns None", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 3: Round-trip conversion
    try:
        v = (2, 0, 1)
        s = _version_tuple_to_str(v)
        back = _str_to_version_tuple(s)
        _assert("version round-trip (2, 0, 1) -> '2.0.1' -> (2, 0, 1)",
                back == v,
                f"str={s!r}, back={back!r}")
    except Exception as e:
        _fail("version round-trip", str(e))

    # Test 4: Invalid version string
    try:
        result = _str_to_version_tuple("not.a.version")
        _assert("version parse: invalid string returns None",
                result is None,
                f"got {result!r}")
    except Exception as e:
        _fail("version parse: invalid string returns None", str(e))

    # Test 5: Partial version string
    try:
        result = _str_to_version_tuple("1.7")
        _assert("version parse: partial '1.7' returns None",
                result is None,
                f"got {result!r}")
    except Exception as e:
        _fail("version parse: partial '1.7' returns None", str(e))

    # ================================================================
    # TAG REGEX (3 tests)
    # ================================================================

    # Test 6: Valid tag match
    try:
        m = TAG_PATTERN.match("expansion/1.8.0")
        _assert("tag regex: matches expansion/1.8.0",
                m is not None and (int(m.group(1)), int(m.group(2)), int(m.group(3))) == (1, 8, 0),
                f"match={m}")
    except Exception as e:
        _fail("tag regex: matches expansion/1.8.0", str(e))

    # Test 7: Reject non-version tag
    try:
        m1 = TAG_PATTERN.match("v1.8.0")
        m2 = TAG_PATTERN.match("expansion/beta")
        m3 = TAG_PATTERN.match("expansion/1.8")
        _assert("tag regex: rejects non-version tags",
                m1 is None and m2 is None and m3 is None,
                f"m1={m1}, m2={m2}, m3={m3}")
    except Exception as e:
        _fail("tag regex: rejects non-version tags", str(e))

    # Test 8: Multiple tags sorted correctly
    try:
        tags = ["expansion/1.7.4", "expansion/1.8.0", "expansion/1.7.3",
                "expansion/2.0.0", "not-a-tag"]
        versions = []
        for t in tags:
            m = TAG_PATTERN.match(t)
            if m:
                versions.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
        versions.sort(reverse=True)
        expected = [(2, 0, 0), (1, 8, 0), (1, 7, 4), (1, 7, 3)]
        _assert("tag regex: sorted newest-first",
                versions == expected,
                f"got {versions}")
    except Exception as e:
        _fail("tag regex: sorted newest-first", str(e))

    # ================================================================
    # CUSTOM MAP DETECTION (4 tests)
    # ================================================================

    # Test 9: Extra dirs found
    tmp_user = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    tmp_base = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        # Create baseline with 2 maps
        base_maps = os.path.join(tmp_base, "data", "maps")
        os.makedirs(os.path.join(base_maps, "PetalburgCity"))
        os.makedirs(os.path.join(base_maps, "Route101"))

        # Create user with 2 baseline + 1 custom
        user_maps = os.path.join(tmp_user, "data", "maps")
        os.makedirs(os.path.join(user_maps, "PetalburgCity"))
        os.makedirs(os.path.join(user_maps, "Route101"))
        os.makedirs(os.path.join(user_maps, "CustomTown"))
        # Add a script to custom map
        with open(os.path.join(user_maps, "CustomTown", "scripts.pory"), "w") as f:
            f.write("// custom\n")

        result = _detect_custom_maps(tmp_user, tmp_base)
        _assert("custom maps: finds extra dirs",
                len(result) == 1 and result[0]["name"] == "CustomTown",
                f"got {result!r}")
        _assert("custom maps: detects scripts",
                result[0]["has_scripts"] is True,
                f"got has_scripts={result[0].get('has_scripts')}")
    except Exception as e:
        _fail("custom maps: finds extra dirs", str(e))
    finally:
        shutil.rmtree(tmp_user, ignore_errors=True)
        shutil.rmtree(tmp_base, ignore_errors=True)

    # Test 10: No extras
    tmp_user = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    tmp_base = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        base_maps = os.path.join(tmp_base, "data", "maps")
        os.makedirs(os.path.join(base_maps, "PetalburgCity"))
        user_maps = os.path.join(tmp_user, "data", "maps")
        os.makedirs(os.path.join(user_maps, "PetalburgCity"))

        result = _detect_custom_maps(tmp_user, tmp_base)
        _assert("custom maps: no extras returns empty",
                result == [],
                f"got {result!r}")
    except Exception as e:
        _fail("custom maps: no extras returns empty", str(e))
    finally:
        shutil.rmtree(tmp_user, ignore_errors=True)
        shutil.rmtree(tmp_base, ignore_errors=True)

    # Test 11: With layouts
    tmp_user = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    tmp_base = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        os.makedirs(os.path.join(tmp_base, "data", "maps"))
        user_maps = os.path.join(tmp_user, "data", "maps")
        os.makedirs(os.path.join(user_maps, "CustomTown"))
        # Add matching layout dir
        os.makedirs(os.path.join(tmp_user, "data", "layouts", "CustomTown"))

        result = _detect_custom_maps(tmp_user, tmp_base)
        _assert("custom maps: detects layout dir",
                len(result) == 1 and result[0]["layout_dir"] is not None,
                f"got {result!r}")
    except Exception as e:
        _fail("custom maps: detects layout dir", str(e))
    finally:
        shutil.rmtree(tmp_user, ignore_errors=True)
        shutil.rmtree(tmp_base, ignore_errors=True)

    # Test 12: Without layouts
    tmp_user = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    tmp_base = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        os.makedirs(os.path.join(tmp_base, "data", "maps"))
        user_maps = os.path.join(tmp_user, "data", "maps")
        os.makedirs(os.path.join(user_maps, "CustomTown"))

        result = _detect_custom_maps(tmp_user, tmp_base)
        _assert("custom maps: no layout dir -> None",
                len(result) == 1 and result[0]["layout_dir"] is None,
                f"got {result!r}")
    except Exception as e:
        _fail("custom maps: no layout dir -> None", str(e))
    finally:
        shutil.rmtree(tmp_user, ignore_errors=True)
        shutil.rmtree(tmp_base, ignore_errors=True)

    # ================================================================
    # MAKEFILE DETECTION (3 tests)
    # ================================================================

    # Test 13: Changed vars detected
    tmp_user = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    tmp_base = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        # Baseline Makefile
        with open(os.path.join(tmp_base, "Makefile"), "w") as f:
            f.write("TITLE       := POKEMON EMER\n")
            f.write("GAME_CODE   := BPEE\n")
            f.write("ROM_NAME    := pokeemerald.gba\n")
        # User Makefile with custom TITLE
        with open(os.path.join(tmp_user, "Makefile"), "w") as f:
            f.write("TITLE       := POKEMON SEIH\n")
            f.write("GAME_CODE   := BPEE\n")
            f.write("ROM_NAME    := pokeemerald.gba\n")

        result = _detect_makefile_customizations(tmp_user, tmp_base)
        _assert("makefile: detects changed TITLE",
                "TITLE" in result and result["TITLE"] == "POKEMON SEIH",
                f"got {result!r}")
        _assert("makefile: unchanged vars not included",
                "GAME_CODE" not in result,
                f"got {result!r}")
    except Exception as e:
        _fail("makefile: detects changed vars", str(e))
    finally:
        shutil.rmtree(tmp_user, ignore_errors=True)
        shutil.rmtree(tmp_base, ignore_errors=True)

    # Test 14: No changes
    tmp_user = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    tmp_base = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        content = "TITLE       := POKEMON EMER\nGAME_CODE   := BPEE\n"
        with open(os.path.join(tmp_base, "Makefile"), "w") as f:
            f.write(content)
        with open(os.path.join(tmp_user, "Makefile"), "w") as f:
            f.write(content)

        result = _detect_makefile_customizations(tmp_user, tmp_base)
        _assert("makefile: no changes -> empty dict",
                result == {},
                f"got {result!r}")
    except Exception as e:
        _fail("makefile: no changes -> empty dict", str(e))
    finally:
        shutil.rmtree(tmp_user, ignore_errors=True)
        shutil.rmtree(tmp_base, ignore_errors=True)

    # Test 15: Missing Makefile
    tmp_user = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    tmp_base = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        result = _detect_makefile_customizations(tmp_user, tmp_base)
        _assert("makefile: missing file -> empty dict",
                result == {},
                f"got {result!r}")
    except Exception as e:
        _fail("makefile: missing file -> empty dict", str(e))
    finally:
        shutil.rmtree(tmp_user, ignore_errors=True)
        shutil.rmtree(tmp_base, ignore_errors=True)

    # ================================================================
    # MAP_GROUPS MERGE (3 tests)
    # ================================================================

    # Test 16: Append custom groups
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        mg_path = os.path.join(tmp, "data", "maps", "map_groups.json")
        os.makedirs(os.path.dirname(mg_path))
        # Write a "new version" map_groups.json
        new_mg = {
            "group_order": ["gPetalburgCity"],
            "gPetalburgCity": ["PetalburgCity_Gym", "PetalburgCity_House1"],
        }
        with open(mg_path, "w") as f:
            json.dump(new_mg, f)

        manifest = UpgradeManifest()
        manifest.custom_map_groups = {
            "gCustomTown": ["CustomTown", "CustomTown_House1"],
        }

        result = _reinject_map_groups(tmp, manifest)
        _assert("map_groups merge: returns True",
                result is True,
                f"got {result!r}")

        # Verify the merged file
        with open(mg_path) as f:
            merged = json.load(f)
        _assert("map_groups merge: custom group added",
                "gCustomTown" in merged and merged["gCustomTown"] == ["CustomTown", "CustomTown_House1"],
                f"got groups={list(merged.keys())}")
        _assert("map_groups merge: group_order updated",
                "gCustomTown" in merged.get("group_order", []),
                f"got order={merged.get('group_order')}")
    except Exception as e:
        _fail("map_groups merge: append custom groups", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 17: Empty custom groups
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        manifest = UpgradeManifest()
        manifest.custom_map_groups = {}
        result = _reinject_map_groups(tmp, manifest)
        _assert("map_groups merge: empty custom -> True (no-op)",
                result is True,
                f"got {result!r}")
    except Exception as e:
        _fail("map_groups merge: empty custom -> True (no-op)", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 18: Preserve vanilla groups
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        mg_path = os.path.join(tmp, "data", "maps", "map_groups.json")
        os.makedirs(os.path.dirname(mg_path))
        new_mg = {
            "group_order": ["gPetalburgCity"],
            "gPetalburgCity": ["PetalburgCity_Gym"],
        }
        with open(mg_path, "w") as f:
            json.dump(new_mg, f)

        manifest = UpgradeManifest()
        # Add a map to an existing vanilla group
        manifest.custom_map_groups = {
            "gPetalburgCity": ["PetalburgCity_CustomShop"],
        }

        result = _reinject_map_groups(tmp, manifest)
        with open(mg_path) as f:
            merged = json.load(f)
        _assert("map_groups merge: vanilla group preserved + custom appended",
                "PetalburgCity_Gym" in merged["gPetalburgCity"]
                and "PetalburgCity_CustomShop" in merged["gPetalburgCity"],
                f"got {merged['gPetalburgCity']}")
    except Exception as e:
        _fail("map_groups merge: vanilla group preserved", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # DISK SPACE & MANIFEST (4 tests)
    # ================================================================

    # Test 19: Disk space check with a known path
    try:
        result = _check_disk_space("/tmp", min_gb=0.001)
        _assert("disk space: /tmp has >1 MB free",
                result is True,
                f"got {result}")
    except Exception as e:
        _fail("disk space: /tmp has >1 MB free", str(e))

    # Test 20: Disk space check with unreasonable threshold
    try:
        result = _check_disk_space("/tmp", min_gb=999999)
        _assert("disk space: 999999 GB threshold fails",
                result is False,
                f"got {result}")
    except Exception as e:
        _fail("disk space: 999999 GB threshold fails", str(e))

    # Test 21: Manifest initialization (updated with new fields)
    try:
        m = UpgradeManifest()
        _assert("manifest: initializes with defaults",
                m.current_version is None
                and m.target_version is None
                and m.custom_maps == []
                and m.custom_map_groups == {}
                and m.custom_layouts == []
                and m.custom_region_map_sections == []
                and m.custom_heal_locations == {}
                and m.custom_tilesets == []
                and m.makefile_vars == {}
                and m.modified_vanilla_files == []
                and m.scorch_detected is False,
                f"got current={m.current_version}, maps={m.custom_maps}")
    except Exception as e:
        _fail("manifest: initializes with defaults", str(e))

    # Test 22: Disk space with nonexistent path
    try:
        result = _check_disk_space("/nonexistent/path/that/does/not/exist")
        _assert("disk space: nonexistent path returns False",
                result is False,
                f"got {result}")
    except Exception as e:
        _fail("disk space: nonexistent path returns False", str(e))

    # ================================================================
    # LAYOUTS.JSON DETECTION & MERGE (3 tests)
    # ================================================================

    # Test 23: Detect custom layouts
    tmp_user = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    tmp_base = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        user_dir = os.path.join(tmp_user, "data", "layouts")
        base_dir = os.path.join(tmp_base, "data", "layouts")
        os.makedirs(user_dir)
        os.makedirs(base_dir)

        base_layouts = {
            "layouts_table_label": "gLayouts",
            "layouts": [
                {"id": "LAYOUT_PETALBURG", "name": "Petalburg_Layout"},
            ]
        }
        user_layouts = {
            "layouts_table_label": "gLayouts",
            "layouts": [
                {"id": "LAYOUT_PETALBURG", "name": "Petalburg_Layout"},
                {"id": "LAYOUT_CUSTOM_TOWN", "name": "CustomTown_Layout"},
            ]
        }
        with open(os.path.join(base_dir, "layouts.json"), "w") as f:
            json.dump(base_layouts, f)
        with open(os.path.join(user_dir, "layouts.json"), "w") as f:
            json.dump(user_layouts, f)

        result = _detect_custom_layouts(tmp_user, tmp_base)
        _assert("layouts detect: finds custom layout",
                len(result) == 1 and result[0]["id"] == "LAYOUT_CUSTOM_TOWN",
                f"got {result!r}")
    except Exception as e:
        _fail("layouts detect: finds custom layout", str(e))
    finally:
        shutil.rmtree(tmp_user, ignore_errors=True)
        shutil.rmtree(tmp_base, ignore_errors=True)

    # Test 24: Reinject layouts into new file
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        layouts_dir = os.path.join(tmp, "data", "layouts")
        os.makedirs(layouts_dir)
        new_layouts = {
            "layouts_table_label": "gLayouts",
            "layouts": [
                {"id": "LAYOUT_PETALBURG", "name": "Petalburg_Layout"},
            ]
        }
        with open(os.path.join(layouts_dir, "layouts.json"), "w") as f:
            json.dump(new_layouts, f)

        manifest = UpgradeManifest()
        manifest.custom_layouts = [
            {"id": "LAYOUT_CUSTOM_TOWN", "name": "CustomTown_Layout",
             "width": 20, "height": 20},
        ]
        result = _reinject_layouts(tmp, manifest)
        _assert("layouts merge: returns True", result is True, f"got {result!r}")

        with open(os.path.join(layouts_dir, "layouts.json")) as f:
            merged = json.load(f)
        ids = [e["id"] for e in merged["layouts"]]
        _assert("layouts merge: custom entry added",
                "LAYOUT_CUSTOM_TOWN" in ids,
                f"got ids={ids}")
    except Exception as e:
        _fail("layouts merge: reinject", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 25: Empty custom layouts is no-op
    try:
        manifest = UpgradeManifest()
        manifest.custom_layouts = []
        result = _reinject_layouts("/tmp", manifest)
        _assert("layouts merge: empty -> True (no-op)",
                result is True, f"got {result!r}")
    except Exception as e:
        _fail("layouts merge: empty -> True (no-op)", str(e))

    # ================================================================
    # REGION MAP SECTIONS DETECTION & MERGE (3 tests)
    # ================================================================

    # Test 26: Detect custom region map sections
    tmp_user = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    tmp_base = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        user_dir = os.path.join(tmp_user, "src", "data", "region_map")
        base_dir = os.path.join(tmp_base, "src", "data", "region_map")
        os.makedirs(user_dir)
        os.makedirs(base_dir)

        base_rms = {
            "map_sections": [
                {"map_section": "MAPSEC_PETALBURG", "name": "PETALBURG"},
            ]
        }
        user_rms = {
            "map_sections": [
                {"map_section": "MAPSEC_PETALBURG", "name": "PETALBURG"},
                {"map_section": "MAPSEC_CUSTOM_TOWN", "name": "CUSTOM TOWN"},
            ]
        }
        with open(os.path.join(base_dir, "region_map_sections.json"), "w") as f:
            json.dump(base_rms, f)
        with open(os.path.join(user_dir, "region_map_sections.json"), "w") as f:
            json.dump(user_rms, f)

        result = _detect_custom_region_map_sections(tmp_user, tmp_base)
        _assert("region_map detect: finds custom section",
                len(result) == 1 and result[0]["map_section"] == "MAPSEC_CUSTOM_TOWN",
                f"got {result!r}")
    except Exception as e:
        _fail("region_map detect: finds custom section", str(e))
    finally:
        shutil.rmtree(tmp_user, ignore_errors=True)
        shutil.rmtree(tmp_base, ignore_errors=True)

    # Test 27: Reinject region map sections
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        rms_dir = os.path.join(tmp, "src", "data", "region_map")
        os.makedirs(rms_dir)
        new_rms = {
            "map_sections": [
                {"map_section": "MAPSEC_PETALBURG", "name": "PETALBURG"},
            ]
        }
        with open(os.path.join(rms_dir, "region_map_sections.json"), "w") as f:
            json.dump(new_rms, f)

        manifest = UpgradeManifest()
        manifest.custom_region_map_sections = [
            {"map_section": "MAPSEC_CUSTOM_TOWN", "name": "CUSTOM TOWN"},
        ]
        result = _reinject_region_map_sections(tmp, manifest)
        _assert("region_map merge: returns True", result is True, f"got {result!r}")

        with open(os.path.join(rms_dir, "region_map_sections.json")) as f:
            merged = json.load(f)
        consts = [e["map_section"] for e in merged["map_sections"]]
        _assert("region_map merge: custom section added",
                "MAPSEC_CUSTOM_TOWN" in consts,
                f"got consts={consts}")
    except Exception as e:
        _fail("region_map merge: reinject", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 28: Empty custom sections is no-op
    try:
        manifest = UpgradeManifest()
        manifest.custom_region_map_sections = []
        result = _reinject_region_map_sections("/tmp", manifest)
        _assert("region_map merge: empty -> True (no-op)",
                result is True, f"got {result!r}")
    except Exception as e:
        _fail("region_map merge: empty -> True (no-op)", str(e))

    # ================================================================
    # HEAL LOCATIONS DETECTION & RESTORE (5 tests)
    # ================================================================

    # Test 29: Detect custom heal locations (JSON format)
    tmp_user = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    tmp_base = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        for d in [tmp_user, tmp_base]:
            os.makedirs(os.path.join(d, "src", "data"))

        base_hl = {"heal_locations": [
            {"id": "HEAL_LOCATION_PETALBURG", "map": "MAP_PETALBURG", "x": 1, "y": 1},
        ]}
        user_hl = {"heal_locations": [
            {"id": "HEAL_LOCATION_PETALBURG", "map": "MAP_PETALBURG", "x": 1, "y": 1},
            {"id": "HEAL_LOCATION_CUSTOM", "map": "MAP_CUSTOM_TOWN", "x": 5, "y": 5},
        ]}
        with open(os.path.join(tmp_base, "src", "data", "heal_locations.json"), "w") as f:
            json.dump(base_hl, f)
        with open(os.path.join(tmp_user, "src", "data", "heal_locations.json"), "w") as f:
            json.dump(user_hl, f)

        result = _detect_custom_heal_locations(tmp_user, tmp_base)
        _assert("heal_locations detect JSON: format is json",
                result.get("format") == "json",
                f"got {result!r}")
        entries = result.get("entries", [])
        _assert("heal_locations detect JSON: finds custom entry",
                len(entries) == 1 and entries[0]["id"] == "HEAL_LOCATION_CUSTOM",
                f"got {entries!r}")
    except Exception as e:
        _fail("heal_locations detect JSON", str(e))
    finally:
        shutil.rmtree(tmp_user, ignore_errors=True)
        shutil.rmtree(tmp_base, ignore_errors=True)

    # Test 30: Detect custom heal locations (old .h format)
    tmp_user = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    tmp_base = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        for d in [tmp_user, tmp_base]:
            os.makedirs(os.path.join(d, "include", "constants"))
            os.makedirs(os.path.join(d, "src", "data"))

        base_content = "#define HEAL_LOCATION_PETALBURG 1\n"
        user_content = "#define HEAL_LOCATION_PETALBURG 1\n#define HEAL_LOCATION_CUSTOM 2\n"

        with open(os.path.join(tmp_base, "include", "constants", "heal_locations.h"), "w") as f:
            f.write(base_content)
        with open(os.path.join(tmp_user, "include", "constants", "heal_locations.h"), "w") as f:
            f.write(user_content)
        # src/data heal_locations.h must also exist (old format uses both)
        with open(os.path.join(tmp_base, "src", "data", "heal_locations.h"), "w") as f:
            f.write("same\n")
        with open(os.path.join(tmp_user, "src", "data", "heal_locations.h"), "w") as f:
            f.write("same\n")

        result = _detect_custom_heal_locations(tmp_user, tmp_base)
        _assert("heal_locations detect .h: format is h",
                result.get("format") == "h",
                f"got {result!r}")
        files = result.get("files", {})
        _assert("heal_locations detect .h: finds modified file",
                len(files) == 1,
                f"got {len(files)} files: {list(files.keys())}")
        key = list(files.keys())[0] if files else ""
        _assert("heal_locations detect .h: correct file path",
                "heal_locations.h" in key,
                f"got key={key}")
    except Exception as e:
        _fail("heal_locations detect .h", str(e))
    finally:
        shutil.rmtree(tmp_user, ignore_errors=True)
        shutil.rmtree(tmp_base, ignore_errors=True)

    # Test 31: Reinject heal locations (JSON format)
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        hl_dir = os.path.join(tmp, "src", "data")
        os.makedirs(hl_dir)
        target_hl = {"heal_locations": [
            {"id": "HEAL_LOCATION_PETALBURG", "map": "MAP_PETALBURG", "x": 1, "y": 1},
        ]}
        with open(os.path.join(hl_dir, "heal_locations.json"), "w") as f:
            json.dump(target_hl, f)

        manifest = UpgradeManifest()
        manifest.custom_heal_locations = {
            "format": "json",
            "entries": [
                {"id": "HEAL_LOCATION_CUSTOM", "map": "MAP_CUSTOM_TOWN", "x": 5, "y": 5},
            ],
        }
        count = _reinject_heal_locations(tmp, manifest)
        _assert("heal_locations reinject JSON: returns 1",
                count == 1, f"got {count}")

        with open(os.path.join(hl_dir, "heal_locations.json")) as f:
            merged = json.load(f)
        ids = [e["id"] for e in merged["heal_locations"]]
        _assert("heal_locations reinject JSON: custom entry merged",
                "HEAL_LOCATION_CUSTOM" in ids,
                f"got ids={ids}")
    except Exception as e:
        _fail("heal_locations reinject JSON", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 32: Reinject heal locations (.h format, target still uses .h)
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        os.makedirs(os.path.join(tmp, "include", "constants"))
        with open(os.path.join(tmp, "include", "constants", "heal_locations.h"), "w") as f:
            f.write("#define HEAL_LOCATION_PETALBURG 1\n")

        manifest = UpgradeManifest()
        rel = os.path.join("include", "constants", "heal_locations.h")
        manifest.custom_heal_locations = {
            "format": "h",
            "files": {
                rel: "#define HEAL_LOCATION_PETALBURG 1\n#define HEAL_LOCATION_CUSTOM 2\n",
            },
        }
        count = _reinject_heal_locations(tmp, manifest)
        _assert("heal_locations reinject .h: returns 1",
                count == 1, f"got {count}")

        with open(os.path.join(tmp, rel)) as f:
            content = f.read()
        _assert("heal_locations reinject .h: custom content restored",
                "HEAL_LOCATION_CUSTOM" in content,
                f"got content length={len(content)}")
    except Exception as e:
        _fail("heal_locations reinject .h", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 33: Empty heal locations is no-op
    try:
        manifest = UpgradeManifest()
        manifest.custom_heal_locations = {}
        count = _reinject_heal_locations("/tmp", manifest)
        _assert("heal_locations reinject: empty -> 0",
                count == 0, f"got {count}")
    except Exception as e:
        _fail("heal_locations reinject: empty -> 0", str(e))

    # ================================================================
    # REGION MAP SECTIONS SCHEMA ADAPTATION (2 tests)
    # ================================================================

    # Test 34: Reinject adapts map_section -> id when target uses id
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        rms_dir = os.path.join(tmp, "src", "data", "region_map")
        os.makedirs(rms_dir)
        # Target uses "id" key (new schema)
        new_rms = {
            "map_sections": [
                {"id": "MAPSEC_PETALBURG", "name": "PETALBURG"},
            ]
        }
        with open(os.path.join(rms_dir, "region_map_sections.json"), "w") as f:
            json.dump(new_rms, f)

        manifest = UpgradeManifest()
        # Custom entry uses old "map_section" key
        manifest.custom_region_map_sections = [
            {"map_section": "MAPSEC_CUSTOM_TOWN", "name": "CUSTOM TOWN", "x": 5, "y": 10},
        ]
        result = _reinject_region_map_sections(tmp, manifest)
        _assert("region_map schema adapt: returns True", result is True, f"got {result!r}")

        with open(os.path.join(rms_dir, "region_map_sections.json")) as f:
            merged = json.load(f)
        custom = [e for e in merged["map_sections"] if e.get("name") == "CUSTOM TOWN"]
        _assert("region_map schema adapt: map_section renamed to id",
                len(custom) == 1 and "id" in custom[0] and "map_section" not in custom[0],
                f"got {custom!r}")
        _assert("region_map schema adapt: id value correct",
                custom[0]["id"] == "MAPSEC_CUSTOM_TOWN",
                f"got id={custom[0].get('id')}")
    except Exception as e:
        _fail("region_map schema adapt", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 35: Reinject keeps map_section key when target uses map_section
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        rms_dir = os.path.join(tmp, "src", "data", "region_map")
        os.makedirs(rms_dir)
        # Target uses "map_section" key (old schema)
        new_rms = {
            "map_sections": [
                {"map_section": "MAPSEC_PETALBURG", "name": "PETALBURG"},
            ]
        }
        with open(os.path.join(rms_dir, "region_map_sections.json"), "w") as f:
            json.dump(new_rms, f)

        manifest = UpgradeManifest()
        # Custom entry also uses old "map_section" key
        manifest.custom_region_map_sections = [
            {"map_section": "MAPSEC_CUSTOM_TOWN", "name": "CUSTOM TOWN"},
        ]
        result = _reinject_region_map_sections(tmp, manifest)
        _assert("region_map old schema: returns True", result is True, f"got {result!r}")

        with open(os.path.join(rms_dir, "region_map_sections.json")) as f:
            merged = json.load(f)
        consts = [e.get("map_section") for e in merged["map_sections"]]
        _assert("region_map old schema: custom section kept map_section key",
                "MAPSEC_CUSTOM_TOWN" in consts,
                f"got consts={consts}")
    except Exception as e:
        _fail("region_map old schema", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # EVENT_SCRIPTS.S REINJECT (3 tests)
    # ================================================================
    from torch.upgrade import _reinject_event_scripts

    # Test 36: Adds include for custom map with scripts
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        es_dir = os.path.join(tmp, "data")
        os.makedirs(es_dir)
        es_path = os.path.join(es_dir, "event_scripts.s")
        with open(es_path, "w") as f:
            f.write('\t.include "data/maps/PetalburgCity/scripts.inc"\n')

        # Create custom map with scripts.inc
        map_dir = os.path.join(tmp, "data", "maps", "MyCustomMap")
        os.makedirs(map_dir)
        with open(os.path.join(map_dir, "scripts.inc"), "w") as f:
            f.write("MyCustomMap_MapScripts::\n\t.byte 0\n")

        manifest = UpgradeManifest()
        manifest.custom_maps = [
            {"name": "MyCustomMap", "map_dir": "data/maps/MyCustomMap",
             "layout_dir": None, "has_scripts": True},
        ]

        result = _reinject_event_scripts(tmp, manifest)
        _assert("event_scripts reinject: returns 1", result == 1, f"got {result}")

        with open(es_path) as f:
            content = f.read()
        _assert("event_scripts reinject: include added",
                'data/maps/MyCustomMap/scripts.inc' in content,
                f"got {content!r}")
    except Exception as e:
        _fail("event_scripts reinject", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 37: Does not duplicate existing includes
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        es_dir = os.path.join(tmp, "data")
        os.makedirs(es_dir)
        es_path = os.path.join(es_dir, "event_scripts.s")
        with open(es_path, "w") as f:
            f.write('\t.include "data/maps/MyCustomMap/scripts.inc"\n')

        map_dir = os.path.join(tmp, "data", "maps", "MyCustomMap")
        os.makedirs(map_dir)
        with open(os.path.join(map_dir, "scripts.inc"), "w") as f:
            f.write("MyCustomMap_MapScripts::\n\t.byte 0\n")

        manifest = UpgradeManifest()
        manifest.custom_maps = [
            {"name": "MyCustomMap", "map_dir": "data/maps/MyCustomMap",
             "layout_dir": None, "has_scripts": True},
        ]

        result = _reinject_event_scripts(tmp, manifest)
        _assert("event_scripts reinject: no duplicate", result == 0, f"got {result}")
    except Exception as e:
        _fail("event_scripts reinject: no duplicate", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 38: Skips maps without scripts
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        es_dir = os.path.join(tmp, "data")
        os.makedirs(es_dir)
        es_path = os.path.join(es_dir, "event_scripts.s")
        with open(es_path, "w") as f:
            f.write('\t.include "data/maps/PetalburgCity/scripts.inc"\n')

        manifest = UpgradeManifest()
        manifest.custom_maps = [
            {"name": "NoScriptMap", "map_dir": "data/maps/NoScriptMap",
             "layout_dir": None, "has_scripts": False},
        ]

        result = _reinject_event_scripts(tmp, manifest)
        _assert("event_scripts reinject: skips no-script maps",
                result == 0, f"got {result}")
    except Exception as e:
        _fail("event_scripts reinject: skips no-script maps", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # VANILLA ADDITIONS DETECTION & REPORT (12 tests)
    # ================================================================
    from torch.upgrade import _extract_additions, _generate_vanilla_report

    # Test 39: Extract additions finds inserted lines
    try:
        base = ["line1\n", "line2\n", "line3\n"]
        user = ["line1\n", "line2\n", "CUSTOM_LINE\n", "line3\n"]
        result = _extract_additions(base, user)
        _assert("vanilla additions: detects inserted line",
                len(result) == 1 and "CUSTOM_LINE" in result[0]["lines"][0],
                f"got {result}")
    except Exception as e:
        _fail("vanilla additions: detects inserted line", str(e))

    # Test 40: Extract additions finds appended lines
    try:
        base = ["line1\n", "line2\n"]
        user = ["line1\n", "line2\n", "APPENDED\n"]
        result = _extract_additions(base, user)
        _assert("vanilla additions: detects appended line",
                len(result) == 1 and "APPENDED" in result[0]["lines"][0],
                f"got {result}")
    except Exception as e:
        _fail("vanilla additions: detects appended line", str(e))

    # Test 41: Generate vanilla report creates file with correct content
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        manifest = UpgradeManifest()
        manifest.current_version = (1, 7, 4)
        manifest.target_version = (1, 14, 3)
        manifest.snapshot_path = "/tmp/fake_backup.zip"
        manifest.modified_vanilla_files = [
            {
                "rel_path": "include/config/overworld.h",
                "reason": "config header modified",
                "additions": [{
                    "context_before": ["#define OW_SOMETHING TRUE"],
                    "lines": ["#define OW_FOLLOWERS_ENABLED TRUE"],
                }],
            },
            {
                "rel_path": "include/constants/flags.h",
                "reason": "constants file modified",
                "additions": [
                    {
                        "context_before": ["#define FLAG_UNUSED_0x500"],
                        "lines": ["#define FLAG_BEAT_ROCKET 0x510"],
                    },
                    {
                        "replaces": ["#define OW_PC_HEAL FALSE"],
                        "lines": ["#define OW_PC_HEAL TRUE"],
                    },
                ],
            },
        ]

        result = _generate_vanilla_report(tmp, manifest)
        _assert("vanilla report: returns path", result is not None, f"got {result}")
        _assert("vanilla report: file exists", os.path.isfile(result), "file not found")

        with open(result) as f:
            content = f.read()
        _assert("vanilla report: has header",
                "TORCH Upgrade Report" in content,
                "missing header")
        _assert("vanilla report: lists overworld.h",
                "include/config/overworld.h" in content,
                "missing overworld.h")
        _assert("vanilla report: lists flags.h",
                "include/constants/flags.h" in content,
                "missing flags.h")
        _assert("vanilla report: includes addition",
                "OW_FOLLOWERS_ENABLED" in content,
                "missing addition line")
        _assert("vanilla report: includes replacement",
                "REPLACED" in content,
                "missing REPLACED block")
        _assert("vanilla report: has footer",
                "2 file(s) with changes" in content,
                "missing footer")
    except Exception as e:
        _fail("vanilla report: creates file", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 42: Generate vanilla report returns None when no additions
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        manifest = UpgradeManifest()
        manifest.current_version = (1, 7, 4)
        manifest.target_version = (1, 14, 3)
        manifest.modified_vanilla_files = []

        result = _generate_vanilla_report(tmp, manifest)
        _assert("vanilla report: empty returns None", result is None, f"got {result}")

        # Also test with entries that have no additions
        manifest.modified_vanilla_files = [{
            "rel_path": "some/file.h",
            "reason": "content differs",
            "additions": [],
        }]
        result = _generate_vanilla_report(tmp, manifest)
        _assert("vanilla report: no-additions returns None", result is None, f"got {result}")
    except Exception as e:
        _fail("vanilla report: empty", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 43: Report includes backup path
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        manifest = UpgradeManifest()
        manifest.current_version = (1, 7, 4)
        manifest.target_version = (1, 14, 3)
        manifest.snapshot_path = "/home/deck/ROMHacking/TORCH/backups/pre-upgrade.zip"
        manifest.modified_vanilla_files = [{
            "rel_path": "include/constants/flags.h",
            "reason": "modified",
            "additions": [{"lines": ["#define CUSTOM 1"]}],
        }]

        result = _generate_vanilla_report(tmp, manifest)
        _assert("vanilla report: backup path in report",
                result is not None, f"got {result}")
        with open(result) as f:
            content = f.read()
        _assert("vanilla report: contains backup path",
                "pre-upgrade.zip" in content,
                "backup path not in report")
    except Exception as e:
        _fail("vanilla report: backup path", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 44: Report saves to workspace_dir when provided
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    ws = tempfile.mkdtemp(prefix="torch_upgrade_ws_")
    try:
        manifest = UpgradeManifest()
        manifest.current_version = (1, 8, 0)
        manifest.target_version = (1, 14, 3)
        manifest.modified_vanilla_files = [{
            "rel_path": "include/constants/vars.h",
            "reason": "modified",
            "additions": [{"lines": ["#define VAR_CUSTOM 0x5000"]}],
        }]

        result = _generate_vanilla_report(tmp, manifest, workspace_dir=ws)
        _assert("vanilla report: saved to workspace",
                result is not None and result.startswith(ws),
                f"got {result}")
        _assert("vanilla report: file exists in workspace",
                os.path.isfile(result), "file not found")
    except Exception as e:
        _fail("vanilla report: workspace_dir", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(ws, ignore_errors=True)

    # Test 45: Report falls back to game_path when workspace_dir is None
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        manifest = UpgradeManifest()
        manifest.current_version = (1, 7, 4)
        manifest.target_version = (1, 14, 3)
        manifest.modified_vanilla_files = [{
            "rel_path": "include/constants/flags.h",
            "reason": "modified",
            "additions": [{"lines": ["#define CUSTOM 1"]}],
        }]

        result = _generate_vanilla_report(tmp, manifest, workspace_dir=None)
        _assert("vanilla report: fallback to game_path",
                result is not None and result.startswith(tmp),
                f"got {result}")
        _assert("vanilla report: in backups/upgrade subdir",
                os.path.join("backups", "upgrade") in result,
                f"got {result}")
    except Exception as e:
        _fail("vanilla report: fallback path", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 46: Report includes auto-handled summary section
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        manifest = UpgradeManifest()
        manifest.current_version = (1, 7, 4)
        manifest.target_version = (1, 14, 3)
        manifest.custom_maps = [{"name": "CustomTown"}]
        manifest.custom_map_groups = {"gCustom": ["CustomTown"]}
        manifest.makefile_vars = {"TITLE": "POKEMON SEIH"}
        manifest.modified_vanilla_files = [{
            "rel_path": "include/constants/flags.h",
            "reason": "modified",
            "additions": [{"lines": ["#define CUSTOM 1"]}],
        }]

        result = _generate_vanilla_report(tmp, manifest)
        with open(result) as f:
            content = f.read()
        _assert("vanilla report: auto-handled section exists",
                "AUTOMATICALLY HANDLED" in content,
                "missing auto-handled section")
        _assert("vanilla report: lists re-injected maps",
                "CustomTown" in content,
                "missing map name in auto-handled")
        _assert("vanilla report: lists map_groups",
                "map_groups.json" in content,
                "missing map_groups in auto-handled")
        _assert("vanilla report: lists Makefile vars",
                "TITLE" in content,
                "missing Makefile vars in auto-handled")
    except Exception as e:
        _fail("vanilla report: auto-handled section", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 47: Report includes per-file action guidance
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        manifest = UpgradeManifest()
        manifest.current_version = (1, 7, 4)
        manifest.target_version = (1, 14, 3)
        manifest.modified_vanilla_files = [{
            "rel_path": "include/constants/flags.h",
            "reason": "modified",
            "additions": [{
                "context_before": ["#define FLAG_UNUSED_0x500"],
                "lines": ["#define FLAG_CUSTOM 0x510"],
            }],
        }]

        result = _generate_vanilla_report(tmp, manifest)
        with open(result) as f:
            content = f.read()
        _assert("vanilla report: has action guidance",
                "Action:" in content,
                "missing per-file Action guidance")
        _assert("vanilla report: action mentions filename",
                "flags.h" in content.split("Action:")[1][:80],
                "action doesn't mention the file")
    except Exception as e:
        _fail("vanilla report: action guidance", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 48: Report includes manual section header
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        manifest = UpgradeManifest()
        manifest.current_version = (1, 7, 4)
        manifest.target_version = (1, 14, 3)
        manifest.modified_vanilla_files = [{
            "rel_path": "include/constants/flags.h",
            "reason": "modified",
            "additions": [{"lines": ["#define CUSTOM 1"]}],
        }]

        result = _generate_vanilla_report(tmp, manifest)
        with open(result) as f:
            content = f.read()
        _assert("vanilla report: manual section header",
                "MANUAL RE-APPLICATION NEEDED" in content,
                "missing manual section header")
    except Exception as e:
        _fail("vanilla report: manual section header", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 49: Report uses upgrade-report-<date> filename
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        manifest = UpgradeManifest()
        manifest.current_version = (1, 7, 4)
        manifest.target_version = (1, 14, 3)
        manifest.modified_vanilla_files = [{
            "rel_path": "include/constants/flags.h",
            "reason": "modified",
            "additions": [{"lines": ["#define CUSTOM 1"]}],
        }]

        result = _generate_vanilla_report(tmp, manifest)
        _assert("vanilla report: filename format",
                os.path.basename(result).startswith("upgrade-report-"),
                f"got filename={os.path.basename(result)}")
        _assert("vanilla report: filename ends .txt",
                result.endswith(".txt"),
                f"got {result}")
    except Exception as e:
        _fail("vanilla report: filename format", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 50: Report sets vanilla_report_path on manifest
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        manifest = UpgradeManifest()
        manifest.current_version = (1, 7, 4)
        manifest.target_version = (1, 14, 3)
        manifest.modified_vanilla_files = [{
            "rel_path": "include/constants/flags.h",
            "reason": "modified",
            "additions": [{"lines": ["#define CUSTOM 1"]}],
        }]

        result = _generate_vanilla_report(tmp, manifest)
        _assert("vanilla report: sets manifest.vanilla_report_path",
                getattr(manifest, "vanilla_report_path", None) == result,
                f"got {getattr(manifest, 'vanilla_report_path', None)}")
    except Exception as e:
        _fail("vanilla report: manifest attribute", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # CUSTOM TILESET DETECTION (4 tests)
    # ================================================================

    # Test 51: Detect custom tilesets — finds custom, ignores vanilla
    tmp_user = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    tmp_base = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        # Baseline: general (primary) + petalburg (secondary)
        os.makedirs(os.path.join(tmp_base, "data", "tilesets", "primary", "general"))
        os.makedirs(os.path.join(tmp_base, "data", "tilesets", "secondary", "petalburg"))

        # User: same + custom secondary tileset
        os.makedirs(os.path.join(tmp_user, "data", "tilesets", "primary", "general"))
        os.makedirs(os.path.join(tmp_user, "data", "tilesets", "secondary", "petalburg"))
        os.makedirs(os.path.join(tmp_user, "data", "tilesets", "secondary", "my_cave"))
        # Add a tile file so the directory isn't empty
        with open(os.path.join(
                tmp_user, "data", "tilesets", "secondary", "my_cave", "tiles.png"), "w") as f:
            f.write("fake")

        result = _detect_custom_tilesets(tmp_user, tmp_base)
        _assert("tileset detect: finds custom tileset",
                len(result) == 1 and result[0]["dir_name"] == "my_cave",
                f"got {result!r}")
        _assert("tileset detect: correct kind",
                result[0]["kind"] == "secondary",
                f"got kind={result[0].get('kind')}")
        _assert("tileset detect: correct camel_name",
                result[0]["camel_name"] == "MyCave",
                f"got camel={result[0].get('camel_name')}")
        _assert("tileset detect: has path",
                result[0]["path"] == os.path.join("data", "tilesets", "secondary", "my_cave"),
                f"got path={result[0].get('path')}")
    except Exception as e:
        _fail("tileset detect: finds custom tileset", str(e))
    finally:
        shutil.rmtree(tmp_user, ignore_errors=True)
        shutil.rmtree(tmp_base, ignore_errors=True)

    # Test 52: No custom tilesets — returns empty
    tmp_user = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    tmp_base = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        os.makedirs(os.path.join(tmp_base, "data", "tilesets", "secondary", "petalburg"))
        os.makedirs(os.path.join(tmp_user, "data", "tilesets", "secondary", "petalburg"))

        result = _detect_custom_tilesets(tmp_user, tmp_base)
        _assert("tileset detect: no custom -> empty",
                result == [],
                f"got {result!r}")
    except Exception as e:
        _fail("tileset detect: no custom -> empty", str(e))
    finally:
        shutil.rmtree(tmp_user, ignore_errors=True)
        shutil.rmtree(tmp_base, ignore_errors=True)

    # Test 53: C header line extraction
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        ts_dir = os.path.join(tmp, "src", "data", "tilesets")
        os.makedirs(ts_dir)

        # Write a headers.h with a custom tileset struct
        with open(os.path.join(ts_dir, "headers.h"), "w") as f:
            f.write('const struct Tileset gTileset_General =\n')
            f.write('{\n')
            f.write('    .isCompressed = TRUE,\n')
            f.write('};\n\n')
            f.write('const struct Tileset gTileset_MyCave =\n')
            f.write('{\n')
            f.write('    .isCompressed = TRUE,\n')
            f.write('    .isSecondary = TRUE,\n')
            f.write('};\n')

        # Write a graphics.h with custom tileset INCBIN lines
        with open(os.path.join(ts_dir, "graphics.h"), "w") as f:
            f.write('const u32 gTilesetTiles_General[] = INCBIN_U32("data/tilesets/primary/general/tiles.4bpp.lz");\n')
            f.write('const u32 gTilesetTiles_MyCave[] = INCBIN_U32("data/tilesets/secondary/my_cave/tiles.4bpp.lz");\n')
            f.write('const u16 gTilesetPalettes_MyCave[][16] =\n')
            f.write('{\n')
            f.write('    INCBIN_U16("data/tilesets/secondary/my_cave/palettes/00.gbapal"),\n')
            f.write('};\n')

        # Write a metatiles.h with custom tileset INCBIN lines
        with open(os.path.join(ts_dir, "metatiles.h"), "w") as f:
            f.write('const u16 gMetatiles_General[] = INCBIN_U16("data/tilesets/primary/general/metatiles.bin");\n')
            f.write('const u16 gMetatiles_MyCave[] = INCBIN_U16("data/tilesets/secondary/my_cave/metatiles.bin");\n')
            f.write('const u16 gMetatileAttributes_MyCave[] = INCBIN_U16("data/tilesets/secondary/my_cave/metatile_attributes.bin");\n')

        result = _extract_tileset_c_lines(tmp, "MyCave")
        _assert("tileset c_lines: headers.h extracted",
                "gTileset_MyCave" in result["headers_h"]
                and "};" in result["headers_h"],
                f"got headers_h length={len(result['headers_h'])}")
        _assert("tileset c_lines: graphics.h extracted",
                "gTilesetTiles_MyCave" in result["graphics_h"]
                and "gTilesetPalettes_MyCave" in result["graphics_h"],
                f"got graphics_h length={len(result['graphics_h'])}")
        _assert("tileset c_lines: metatiles.h extracted",
                "gMetatiles_MyCave" in result["metatiles_h"]
                and "gMetatileAttributes_MyCave" in result["metatiles_h"],
                f"got metatiles_h length={len(result['metatiles_h'])}")

        # Also verify General lines are NOT included
        _assert("tileset c_lines: excludes other tilesets",
                "gTileset_General" not in result["headers_h"]
                and "gTilesetTiles_General" not in result["graphics_h"]
                and "gMetatiles_General" not in result["metatiles_h"],
                "found General lines in MyCave extraction")
    except Exception as e:
        _fail("tileset c_lines: extraction", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Test 54: C header extraction when files don't exist
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    try:
        result = _extract_tileset_c_lines(tmp, "Nonexistent")
        _assert("tileset c_lines: missing files -> empty strings",
                result["headers_h"] == ""
                and result["graphics_h"] == ""
                and result["metatiles_h"] == "",
                f"got {result!r}")
    except Exception as e:
        _fail("tileset c_lines: missing files", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ================================================================
    # TILESET PRESERVATION (_should_preserve) (3 tests)
    # ================================================================

    # Test 55: _should_preserve recognizes custom tileset paths
    try:
        ts_paths = ["data/tilesets/secondary/my_cave"]
        _assert("should_preserve: tileset dir preserved",
                _should_preserve(
                    "data/tilesets/secondary/my_cave/tiles.png",
                    set(), ts_paths) is True,
                "tileset file not preserved")
        _assert("should_preserve: tileset dir itself preserved",
                _should_preserve(
                    "data/tilesets/secondary/my_cave",
                    set(), ts_paths) is True,
                "tileset dir not preserved")
    except Exception as e:
        _fail("should_preserve: tileset paths", str(e))

    # Test 56: _should_preserve ignores vanilla tileset paths
    try:
        ts_paths = ["data/tilesets/secondary/my_cave"]
        _assert("should_preserve: vanilla tileset not preserved",
                _should_preserve(
                    "data/tilesets/secondary/petalburg/tiles.png",
                    set(), ts_paths) is False,
                "vanilla tileset was preserved")
    except Exception as e:
        _fail("should_preserve: vanilla tileset not preserved", str(e))

    # Test 57: _should_preserve with no tileset paths
    try:
        _assert("should_preserve: no tileset paths -> not preserved",
                _should_preserve(
                    "data/tilesets/secondary/my_cave/tiles.png",
                    set()) is False,
                "tileset preserved without tileset_paths")
    except Exception as e:
        _fail("should_preserve: no tileset paths", str(e))

    # ================================================================
    # TILESET RE-INJECTION (3 tests)
    # ================================================================

    # Test 58: Reinject copies tileset directory and appends C header lines
    tmp = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    staging = tempfile.mkdtemp(prefix="torch_upgrade_staging_")
    try:
        # Set up staging with a custom tileset directory
        ts_staging = os.path.join(
            staging, "data", "tilesets", "secondary", "my_cave")
        os.makedirs(ts_staging)
        with open(os.path.join(ts_staging, "tiles.png"), "w") as f:
            f.write("fake tile data")
        with open(os.path.join(ts_staging, "metatiles.bin"), "w") as f:
            f.write("fake metatile data")

        # Set up game path with target version header files (no custom entries)
        ts_hdr_dir = os.path.join(tmp, "src", "data", "tilesets")
        os.makedirs(ts_hdr_dir)
        with open(os.path.join(ts_hdr_dir, "headers.h"), "w") as f:
            f.write('const struct Tileset gTileset_General = { };\n')
        with open(os.path.join(ts_hdr_dir, "graphics.h"), "w") as f:
            f.write('const u32 gTilesetTiles_General[] = INCBIN_U32("tiles");\n')
        with open(os.path.join(ts_hdr_dir, "metatiles.h"), "w") as f:
            f.write('const u16 gMetatiles_General[] = INCBIN_U16("metatiles");\n')

        manifest = UpgradeManifest()
        manifest.staging_dir = staging
        manifest.custom_tilesets = [{
            "dir_name": "my_cave",
            "kind": "secondary",
            "path": os.path.join("data", "tilesets", "secondary", "my_cave"),
            "camel_name": "MyCave",
            "c_lines": {
                "headers_h": 'const struct Tileset gTileset_MyCave =\n{\n    .isSecondary = TRUE,\n};\n',
                "graphics_h": 'const u32 gTilesetTiles_MyCave[] = INCBIN_U32("tiles");\n',
                "metatiles_h": 'const u16 gMetatiles_MyCave[] = INCBIN_U16("metatiles");\n',
            },
        }]

        count = _reinject_custom_tilesets(tmp, manifest)
        _assert("tileset reinject: returns 1", count == 1, f"got {count}")

        # Verify tileset directory was copied
        dst_tiles = os.path.join(
            tmp, "data", "tilesets", "secondary", "my_cave", "tiles.png")
        _assert("tileset reinject: directory copied",
                os.path.isfile(dst_tiles),
                "tiles.png not found in game path")

        # Verify C header lines were appended
        with open(os.path.join(ts_hdr_dir, "headers.h")) as f:
            content = f.read()
        _assert("tileset reinject: headers.h updated",
                "gTileset_MyCave" in content,
                f"headers.h content length={len(content)}")

        with open(os.path.join(ts_hdr_dir, "graphics.h")) as f:
            content = f.read()
        _assert("tileset reinject: graphics.h updated",
                "gTilesetTiles_MyCave" in content,
                f"graphics.h content length={len(content)}")

        with open(os.path.join(ts_hdr_dir, "metatiles.h")) as f:
            content = f.read()
        _assert("tileset reinject: metatiles.h updated",
                "gMetatiles_MyCave" in content,
                f"metatiles.h content length={len(content)}")
    except Exception as e:
        _fail("tileset reinject: copy + headers", str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)

    # Test 59: Reinject with no custom tilesets is a no-op
    try:
        manifest = UpgradeManifest()
        manifest.custom_tilesets = []
        manifest.staging_dir = "/tmp"
        count = _reinject_custom_tilesets("/tmp", manifest)
        _assert("tileset reinject: empty -> 0", count == 0, f"got {count}")
    except Exception as e:
        _fail("tileset reinject: empty -> 0", str(e))

    # Test 60: Detect + reinject end-to-end (tileset survives replace_base)
    tmp_user = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    tmp_target = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    tmp_base = tempfile.mkdtemp(prefix="torch_upgrade_test_")
    staging = tempfile.mkdtemp(prefix="torch_upgrade_staging_")
    try:
        # Baseline and target: only vanilla tileset
        for d in [tmp_base, tmp_target]:
            os.makedirs(os.path.join(d, "data", "tilesets", "secondary", "petalburg"))
            ts_hdr = os.path.join(d, "src", "data", "tilesets")
            os.makedirs(ts_hdr)
            with open(os.path.join(ts_hdr, "headers.h"), "w") as f:
                f.write('const struct Tileset gTileset_Petalburg = { };\n')
            with open(os.path.join(ts_hdr, "graphics.h"), "w") as f:
                f.write('const u32 gTilesetTiles_Petalburg[] = INCBIN_U32("tiles");\n')
            with open(os.path.join(ts_hdr, "metatiles.h"), "w") as f:
                f.write('const u16 gMetatiles_Petalburg[] = INCBIN_U16("meta");\n')

        # User project: vanilla + custom tileset
        os.makedirs(os.path.join(tmp_user, "data", "tilesets", "secondary", "petalburg"))
        custom_ts = os.path.join(
            tmp_user, "data", "tilesets", "secondary", "my_cave")
        os.makedirs(custom_ts)
        with open(os.path.join(custom_ts, "tiles.png"), "w") as f:
            f.write("custom tiles")
        ts_hdr = os.path.join(tmp_user, "src", "data", "tilesets")
        os.makedirs(ts_hdr)
        with open(os.path.join(ts_hdr, "headers.h"), "w") as f:
            f.write('const struct Tileset gTileset_Petalburg = { };\n\n')
            f.write('const struct Tileset gTileset_MyCave =\n{\n    .isSecondary = TRUE,\n};\n')
        with open(os.path.join(ts_hdr, "graphics.h"), "w") as f:
            f.write('const u32 gTilesetTiles_Petalburg[] = INCBIN_U32("tiles");\n')
            f.write('const u32 gTilesetTiles_MyCave[] = INCBIN_U32("my_cave/tiles");\n')
        with open(os.path.join(ts_hdr, "metatiles.h"), "w") as f:
            f.write('const u16 gMetatiles_Petalburg[] = INCBIN_U16("meta");\n')
            f.write('const u16 gMetatiles_MyCave[] = INCBIN_U16("my_cave/meta");\n')

        # Step 1: Detect
        tilesets = _detect_custom_tilesets(tmp_user, tmp_base)
        _assert("tileset e2e: detected 1 custom",
                len(tilesets) == 1 and tilesets[0]["dir_name"] == "my_cave",
                f"got {tilesets!r}")

        # Step 2: Copy to staging
        for ts in tilesets:
            src = os.path.join(tmp_user, ts["path"])
            dst = os.path.join(staging, ts["path"])
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copytree(src, dst)

        # Step 3: Replace base (this would normally delete the custom tileset
        # but _should_preserve protects it)
        from torch.upgrade import _replace_base
        ts_paths = [ts["path"] for ts in tilesets]
        _replace_base(tmp_user, tmp_target, [], custom_tileset_paths=ts_paths)

        # Verify custom tileset dir survived
        survived = os.path.isdir(os.path.join(
            tmp_user, "data", "tilesets", "secondary", "my_cave"))
        _assert("tileset e2e: dir survives replace_base",
                survived is True,
                "custom tileset dir was deleted")

        # Step 4: Reinject C header lines
        manifest = UpgradeManifest()
        manifest.staging_dir = staging
        manifest.custom_tilesets = tilesets
        count = _reinject_custom_tilesets(tmp_user, manifest)
        _assert("tileset e2e: reinject returns 1", count == 1, f"got {count}")

        # Verify headers were re-registered
        with open(os.path.join(ts_hdr, "headers.h")) as f:
            content = f.read()
        _assert("tileset e2e: headers.h has custom entry",
                "gTileset_MyCave" in content,
                "custom tileset not in headers.h")
    except Exception as e:
        _fail("tileset e2e: detect + preserve + reinject", str(e))
    finally:
        shutil.rmtree(tmp_user, ignore_errors=True)
        shutil.rmtree(tmp_target, ignore_errors=True)
        shutil.rmtree(tmp_base, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)
