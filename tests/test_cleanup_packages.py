"""Cleanup Packages suite -- tests SCORCH package discovery pure-logic functions."""

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Cleanup Packages")

    try:
        from torch.cleanup_packages import (
            Package, ALL_SAFE, PARTIAL, PKG_BLOCKED,
            _extract_grouping_prefix, _make_display_name, _make_slug,
            _merge_adjacency, _expand_via_bfs, compute_cross_package_deps,
        )
    except ImportError as e:
        _skip("all cleanup_packages tests", f"import failed: {e}")
        return

    # ==================================================================
    # A. Package class — 3 assertions
    # ==================================================================

    # A1: fields set correctly
    pkg = Package("petalburg", "Petalburg City", "PetalburgCity",
                  ["PetalburgCity", "PetalburgCity_House1"])
    _assert(
        "Package: fields set correctly",
        (pkg.name == "petalburg" and
         pkg.display_name == "Petalburg City" and
         pkg.anchor == "PetalburgCity" and
         pkg.maps == ["PetalburgCity", "PetalburgCity_House1"]),
        f"name={pkg.name!r}, display={pkg.display_name!r}, "
        f"anchor={pkg.anchor!r}, maps={pkg.maps!r}"
    )

    # A2: depends_on / depended_by default to empty sets
    _assert(
        "Package: depends_on/depended_by default empty",
        pkg.depends_on == set() and pkg.depended_by == set(),
        f"depends_on={pkg.depends_on!r}, depended_by={pkg.depended_by!r}"
    )

    # A3: status defaults to ALL_SAFE
    _assert(
        "Package: status defaults to ALL_SAFE",
        pkg.status == ALL_SAFE,
        f"status={pkg.status!r}, expected={ALL_SAFE!r}"
    )

    # ==================================================================
    # B. _extract_grouping_prefix — 4 assertions
    # ==================================================================

    # B1: underscore map -> prefix before underscore
    _assert(
        "grouping_prefix: PetalburgCity_House1 -> PetalburgCity",
        _extract_grouping_prefix("PetalburgCity_House1") == "PetalburgCity",
        f"got: {_extract_grouping_prefix('PetalburgCity_House1')!r}"
    )

    # B2: trailing digits stripped
    _assert(
        "grouping_prefix: Route104 -> Route",
        _extract_grouping_prefix("Route104") == "Route",
        f"got: {_extract_grouping_prefix('Route104')!r}"
    )

    # B3: no underscore, no trailing digits -> as-is
    _assert(
        "grouping_prefix: SSTidalRooms -> SSTidalRooms (no split)",
        _extract_grouping_prefix("SSTidalRooms") == "SSTidalRooms",
        f"got: {_extract_grouping_prefix('SSTidalRooms')!r}"
    )

    # B4: single name, no digits -> as-is
    _assert(
        "grouping_prefix: SingleName -> SingleName",
        _extract_grouping_prefix("SingleName") == "SingleName",
        f"got: {_extract_grouping_prefix('SingleName')!r}"
    )

    # ==================================================================
    # C. _make_display_name — 3 assertions
    # ==================================================================

    _assert(
        "display_name: PetalburgCity -> Petalburg City",
        _make_display_name("PetalburgCity") == "Petalburg City",
        f"got: {_make_display_name('PetalburgCity')!r}"
    )

    _assert(
        "display_name: Route104 -> Route 104",
        _make_display_name("Route104") == "Route 104",
        f"got: {_make_display_name('Route104')!r}"
    )

    _assert(
        "display_name: LakeElixSouth -> Lake Elix South",
        _make_display_name("LakeElixSouth") == "Lake Elix South",
        f"got: {_make_display_name('LakeElixSouth')!r}"
    )

    # ==================================================================
    # D. _make_slug — 3 assertions
    # ==================================================================

    _assert(
        "slug: PetalburgCity -> petalburg",
        _make_slug("PetalburgCity") == "petalburg",
        f"got: {_make_slug('PetalburgCity')!r}"
    )

    _assert(
        "slug: Route104 -> route104",
        _make_slug("Route104") == "route104",
        f"got: {_make_slug('Route104')!r}"
    )

    _assert(
        "slug: LakeElixSouth -> lakeelixsouth",
        _make_slug("LakeElixSouth") == "lakeelixsouth",
        f"got: {_make_slug('LakeElixSouth')!r}"
    )

    # ==================================================================
    # E. _merge_adjacency — 2 assertions
    # ==================================================================

    warp_idx = {"MapA": {"MapB"}, "MapB": {"MapA", "MapC"}}
    conn_idx = {"MapC": {"MapD"}}
    merged = _merge_adjacency(warp_idx, conn_idx)

    # E1: all four maps present as keys
    _assert(
        "merge_adjacency: all 4 maps present as keys",
        set(merged.keys()) == {"MapA", "MapB", "MapC", "MapD"},
        f"keys: {sorted(merged.keys())}"
    )

    # E2: adjacency is symmetric
    symmetric = True
    for src, dests in merged.items():
        for d in dests:
            if src not in merged.get(d, set()):
                symmetric = False
                break
    _assert(
        "merge_adjacency: symmetric (A->B implies B->A)",
        symmetric,
        "found asymmetric edge"
    )

    # ==================================================================
    # F. _expand_via_bfs — 3 assertions
    # ==================================================================

    bfs_warp = {
        "TownCenter": {"TownHouse1", "TownHouse2"},
        "TownHouse1": {"TownCenter"},
        "TownHouse2": {"TownCenter", "OtherTown"},
        "OtherTown":  {"TownHouse2"},
    }
    vanilla = {"TownCenter", "TownHouse1", "TownHouse2", "OtherTown"}

    # F1: BFS from TownCenter claims the three town maps
    result = _expand_via_bfs(
        "TownCenter", {"TownCenter"}, bfs_warp, set(), vanilla,
        all_anchors={"TownCenter", "OtherTown"})
    _assert(
        "BFS: claims TownCenter + both houses",
        {"TownCenter", "TownHouse1", "TownHouse2"} <= result,
        f"got: {sorted(result)}"
    )

    # F2: BFS stops at other anchor
    _assert(
        "BFS: does NOT claim OtherTown (different anchor)",
        "OtherTown" not in result,
        f"got: {sorted(result)}"
    )

    # F3: BFS respects claimed set
    pre_claimed = {"TownHouse1"}
    result2 = _expand_via_bfs(
        "TownCenter", {"TownCenter"}, bfs_warp, pre_claimed, vanilla,
        all_anchors={"TownCenter", "OtherTown"})
    _assert(
        "BFS: respects claimed set (skips TownHouse1)",
        "TownHouse1" not in result2,
        f"got: {sorted(result2)}"
    )

    # ==================================================================
    # G. compute_cross_package_deps — 2 assertions
    # ==================================================================

    pkg1 = Package("town1", "Town 1", "Town1",
                   ["Town1", "Town1_House"])
    pkg2 = Package("town2", "Town 2", "Town2", ["Town2"])

    dep_warp = {
        "Town1": {"Town2"},
        "Town2": {"Town1"},
    }

    compute_cross_package_deps([pkg1, pkg2], dep_warp, {})

    _assert(
        "cross_deps: pkg1.depends_on contains 'town2'",
        "town2" in pkg1.depends_on,
        f"pkg1.depends_on={pkg1.depends_on!r}"
    )

    _assert(
        "cross_deps: pkg2.depended_by contains 'town1'",
        "town1" in pkg2.depended_by,
        f"pkg2.depended_by={pkg2.depended_by!r}"
    )
