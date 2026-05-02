"""Flag Browser — build rows, apply filters, type helpers."""
import os
import sys

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("Flag Browser")

    try:
        from torch.flag_browser import (
            _build_flag_rows, _apply_filters, _type_colour, _type_label,
        )
        from torch.colours import GREEN, WHITE, DIM
    except ImportError as e:
        _skip("all tests", f"import failed: {e}")
        return

    # ==================================================================
    # _build_flag_rows (~4 tests)
    # ==================================================================

    # Build a parsed dict mimicking parse_flags_h output
    parsed = {
        "event": [
            # (name, value, comment, is_unused)
            ("FLAG_MY_CUSTOM", "0x100", "Custom quest flag", False),
            ("FLAG_UNUSED_0x101", "0x101", "", True),   # aliased target (should be skipped)
            ("FLAG_UNUSED_0x102", "0x102", "", True),   # free (not aliased)
            ("FLAG_BADGE01_GET", "0x103", "First badge", False),
            ("FLAG_MY_ALIAS", "0x104", "Alias for something", False),
        ],
        "custom_aliases": [
            ("FLAG_MY_CUSTOM", "FLAG_UNUSED_0x100"),    # custom alias -> target
            ("FLAG_MY_ALIAS", "FLAG_UNUSED_0x101"),     # alias -> FLAG_UNUSED_0x101
        ],
    }

    try:
        rows = _build_flag_rows(parsed)

        # Custom aliases get row_type "custom"
        custom_rows = [r for r in rows if r["row_type"] == "custom"]
        custom_names = {r["name"] for r in custom_rows}
        _assert("_build_flag_rows: custom aliases get row_type 'custom'",
                "FLAG_MY_CUSTOM" in custom_names and "FLAG_MY_ALIAS" in custom_names,
                f"custom names: {custom_names}")
    except Exception as e:
        _fail("_build_flag_rows: custom aliases", str(e))

    try:
        rows = _build_flag_rows(parsed)

        # Unused non-aliased get row_type "free"
        free_rows = [r for r in rows if r["row_type"] == "free"]
        free_names = {r["name"] for r in free_rows}
        _assert("_build_flag_rows: unused non-aliased get row_type 'free'",
                "FLAG_UNUSED_0x102" in free_names,
                f"free names: {free_names}")
    except Exception as e:
        _fail("_build_flag_rows: free flags", str(e))

    try:
        rows = _build_flag_rows(parsed)

        # Named events get row_type "event"
        event_rows = [r for r in rows if r["row_type"] == "event"]
        event_names = {r["name"] for r in event_rows}
        _assert("_build_flag_rows: named events get row_type 'event'",
                "FLAG_BADGE01_GET" in event_names,
                f"event names: {event_names}")
    except Exception as e:
        _fail("_build_flag_rows: event flags", str(e))

    try:
        rows = _build_flag_rows(parsed)

        # Aliased targets are skipped
        all_names = {r["name"] for r in rows}
        _assert("_build_flag_rows: aliased target FLAG_UNUSED_0x101 is skipped",
                "FLAG_UNUSED_0x101" not in all_names,
                f"all names: {all_names}")
    except Exception as e:
        _fail("_build_flag_rows: aliased targets skipped", str(e))

    # ==================================================================
    # _apply_filters (~5 tests)
    # ==================================================================

    try:
        rows = _build_flag_rows(parsed)
    except Exception as e:
        _fail("_apply_filters: setup failed", str(e))
        return

    # Filter by "custom" -> only custom rows
    try:
        result = _apply_filters(rows, "custom", "")
        all_custom = all(r["row_type"] == "custom" for r in result)
        _assert("_apply_filters: filter 'custom' -> only custom rows",
                all_custom and len(result) > 0,
                f"got {len(result)} rows, all_custom={all_custom}")
    except Exception as e:
        _fail("_apply_filters: filter 'custom'", str(e))

    # Filter by "event" -> only event rows
    try:
        result = _apply_filters(rows, "event", "")
        all_event = all(r["row_type"] == "event" for r in result)
        _assert("_apply_filters: filter 'event' -> only event rows",
                all_event and len(result) > 0,
                f"got {len(result)} rows, all_event={all_event}")
    except Exception as e:
        _fail("_apply_filters: filter 'event'", str(e))

    # Search query matching flag name
    try:
        result = _apply_filters(rows, "all", "BADGE")
        _assert("_apply_filters: search 'BADGE' finds FLAG_BADGE01_GET",
                any(r["name"] == "FLAG_BADGE01_GET" for r in result),
                f"got names: {[r['name'] for r in result]}")
    except Exception as e:
        _fail("_apply_filters: search query", str(e))

    # Combined filter + search
    try:
        result = _apply_filters(rows, "custom", "MY_CUSTOM")
        _assert("_apply_filters: custom + search 'MY_CUSTOM'",
                len(result) == 1 and result[0]["name"] == "FLAG_MY_CUSTOM",
                f"got {[r['name'] for r in result]}")
    except Exception as e:
        _fail("_apply_filters: combined filter + search", str(e))

    # "all" mode with no search -> returns all rows
    try:
        result = _apply_filters(rows, "all", "")
        _assert("_apply_filters: 'all' + no search -> returns all rows",
                len(result) == len(rows),
                f"expected {len(rows)}, got {len(result)}")
    except Exception as e:
        _fail("_apply_filters: all mode", str(e))

    # ==================================================================
    # _type_colour (~3 tests)
    # ==================================================================

    try:
        _assert("_type_colour: 'custom' -> GREEN",
                _type_colour("custom") == GREEN,
                f"got {_type_colour('custom')!r}")
    except Exception as e:
        _fail("_type_colour: custom", str(e))

    try:
        _assert("_type_colour: 'event' -> WHITE",
                _type_colour("event") == WHITE,
                f"got {_type_colour('event')!r}")
    except Exception as e:
        _fail("_type_colour: event", str(e))

    try:
        _assert("_type_colour: 'free' -> DIM",
                _type_colour("free") == DIM,
                f"got {_type_colour('free')!r}")
    except Exception as e:
        _fail("_type_colour: free", str(e))

    # ==================================================================
    # _type_label (~3 tests)
    # ==================================================================

    try:
        _assert("_type_label: 'custom' -> 'custom'",
                _type_label("custom") == "custom",
                f"got {_type_label('custom')!r}")
    except Exception as e:
        _fail("_type_label: custom", str(e))

    try:
        _assert("_type_label: 'event' -> 'event'",
                _type_label("event") == "event",
                f"got {_type_label('event')!r}")
    except Exception as e:
        _fail("_type_label: event", str(e))

    try:
        _assert("_type_label: 'free' -> 'free'",
                _type_label("free") == "free",
                f"got {_type_label('free')!r}")
    except Exception as e:
        _fail("_type_label: free", str(e))
