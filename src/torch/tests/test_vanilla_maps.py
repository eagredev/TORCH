"""Vanilla Maps — frozen set of known vanilla map folder names."""
from torch.tests.harness import _begin_suite, _assert, _skip


def run_suite():
    _begin_suite("Vanilla Maps  (frozen name set)")

    try:
        from torch.vanilla_maps import (
            _VANILLA_BASE, _VERSION_ADDITIONS, get_vanilla_map_names,
        )
    except ImportError as e:
        _skip("all vanilla_maps tests", f"import failed: {e}")
        return

    # ---- base set size ----
    _assert(
        "base set has 518 entries",
        len(_VANILLA_BASE) == 518,
        f"expected 518, got {len(_VANILLA_BASE)}"
    )

    # ---- known members ----
    _assert(
        "PetalburgCity is vanilla",
        "PetalburgCity" in _VANILLA_BASE,
    )
    _assert(
        "Route101 is vanilla",
        "Route101" in _VANILLA_BASE,
    )
    _assert(
        "InsideOfTruck is vanilla",
        "InsideOfTruck" in _VANILLA_BASE,
    )
    _assert(
        "LittlerootTown is vanilla",
        "LittlerootTown" in _VANILLA_BASE,
    )
    _assert(
        "BattleFrontier_OutsideEast is vanilla",
        "BattleFrontier_OutsideEast" in _VANILLA_BASE,
    )

    # ---- known non-members ----
    _assert(
        "ShirubeTown is NOT vanilla",
        "ShirubeTown" not in _VANILLA_BASE,
    )
    _assert(
        "LakeElixSouth is NOT vanilla",
        "LakeElixSouth" not in _VANILLA_BASE,
    )
    _assert(
        "CustomTown is NOT vanilla",
        "CustomTown" not in _VANILLA_BASE,
    )
    # Project-specific maps should not be in the universal set
    _assert(
        "MountainPass is NOT vanilla (project-specific)",
        "MountainPass" not in _VANILLA_BASE,
    )
    _assert(
        "ResearchOutpost is NOT vanilla (project-specific)",
        "ResearchOutpost" not in _VANILLA_BASE,
    )

    # ---- get_vanilla_map_names(None) returns base ----
    result_none = get_vanilla_map_names(None)
    _assert(
        "get_vanilla_map_names(None) returns base set",
        result_none is _VANILLA_BASE,
        f"expected same object, got len={len(result_none)}"
    )

    # ---- get_vanilla_map_names with current version returns base ----
    result_v114 = get_vanilla_map_names((1, 14, 4))
    _assert(
        "get_vanilla_map_names(1.14.4) returns base set (no additions yet)",
        result_v114 is _VANILLA_BASE,
        f"expected same object, got len={len(result_v114)}"
    )

    # ---- version gating works when additions exist ----
    # Temporarily inject a test addition
    test_addition = frozenset({"TestKantoMap1", "TestKantoMap2"})
    original_additions = list(_VERSION_ADDITIONS)
    try:
        _VERSION_ADDITIONS.append(((1, 15, 0), test_addition))

        # Version below threshold: no additions
        result_old = get_vanilla_map_names((1, 14, 4))
        _assert(
            "version gating: v1.14 does not include v1.15 additions",
            "TestKantoMap1" not in result_old,
            f"TestKantoMap1 found in result for v1.14"
        )

        # Version at threshold: includes additions
        result_new = get_vanilla_map_names((1, 15, 0))
        _assert(
            "version gating: v1.15 includes additions",
            "TestKantoMap1" in result_new and "TestKantoMap2" in result_new,
            f"missing test maps in result for v1.15"
        )
        _assert(
            "version gating: v1.15 result is union (has base + additions)",
            "PetalburgCity" in result_new and "TestKantoMap1" in result_new,
        )

        # Version above threshold: also includes additions
        result_above = get_vanilla_map_names((2, 0, 0))
        _assert(
            "version gating: v2.0 includes additions",
            "TestKantoMap1" in result_above,
        )
    finally:
        # Restore original state
        _VERSION_ADDITIONS.clear()
        _VERSION_ADDITIONS.extend(original_additions)

    # ---- frozenset is immutable ----
    _assert(
        "base set is a frozenset",
        isinstance(_VANILLA_BASE, frozenset),
    )
