"""Tests for the reusable scrolling list widget."""
from torch.tests.harness import _begin_suite, _assert, _ok, _fail


def run_suite():
    _begin_suite("list_widget")

    from torch.list_widget import (
        ListState, guard_bounds, visible_range,
        overflow_above, overflow_below, marker,
        handle_input, footer_hint,
    )
    from torch.colours import GOLD, DIM, RST

    # ------------------------------------------------------------------
    # ListState and guard_bounds
    # ------------------------------------------------------------------

    # 1. Constructor clamps selected to valid range
    s = ListState(total=5, selected=10)
    _assert("constructor clamps selected above total",
            s.selected == 4, f"selected={s.selected}")

    # 2. Constructor handles total=0
    s = ListState(total=0)
    _assert("constructor handles total=0",
            s.selected == 0 and s.total == 0,
            f"selected={s.selected}, total={s.total}")

    # 3. guard_bounds: selected above total gets clamped
    s = ListState(total=5)
    s.selected = 10
    guard_bounds(s)
    _assert("guard_bounds clamps selected above total",
            s.selected == 4, f"selected={s.selected}")

    # 4. guard_bounds: scroll_top adjusts when selected scrolls above viewport
    s = ListState(total=20, page_size=5, scroll_top=5)
    s.selected = 3
    guard_bounds(s)
    _assert("guard_bounds adjusts scroll_top when selected above viewport",
            s.scroll_top == 3, f"scroll_top={s.scroll_top}")

    # 5. guard_bounds: scroll_top adjusts when selected scrolls below viewport
    s = ListState(total=20, page_size=5, scroll_top=0)
    s.selected = 8
    guard_bounds(s)
    _assert("guard_bounds adjusts scroll_top when selected below viewport",
            s.scroll_top == 4, f"scroll_top={s.scroll_top}")

    # 6. guard_bounds: total=0 sets both to 0
    s = ListState(total=0)
    s.selected = 5
    s.scroll_top = 3
    guard_bounds(s)
    _assert("guard_bounds total=0 sets both to 0",
            s.selected == 0 and s.scroll_top == 0,
            f"selected={s.selected}, scroll_top={s.scroll_top}")

    # ------------------------------------------------------------------
    # visible_range
    # ------------------------------------------------------------------

    # 7. Correct start/end for a middle page
    s = ListState(total=50, page_size=10, scroll_top=10)
    s.selected = 15
    _assert("visible_range middle page",
            visible_range(s) == (10, 20),
            f"got {visible_range(s)}")

    # 8. Correct end when near bottom (partial page)
    s = ListState(total=23, page_size=10, scroll_top=20)
    s.selected = 22
    _assert("visible_range partial page at bottom",
            visible_range(s) == (20, 23),
            f"got {visible_range(s)}")

    # 9. Returns (0, 0) when total=0
    s = ListState(total=0)
    _assert("visible_range total=0",
            visible_range(s) == (0, 0),
            f"got {visible_range(s)}")

    # ------------------------------------------------------------------
    # overflow_above / overflow_below
    # ------------------------------------------------------------------

    # 10. overflow_above returns None when no overflow
    s = ListState(total=10, page_size=10, scroll_top=0)
    _assert("overflow_above None when no overflow",
            overflow_above(s) is None)

    # 11. overflow_above returns formatted string when overflow exists
    s = ListState(total=20, page_size=10, scroll_top=5)
    s.selected = 5
    result = overflow_above(s)
    _assert("overflow_above returns formatted string",
            result is not None and "5 more above" in result and "\u2191" in result,
            f"got {result!r}")

    # 12. overflow_below returns None when no overflow
    s = ListState(total=10, page_size=10, scroll_top=0)
    _assert("overflow_below None when no overflow",
            overflow_below(s) is None)

    # 13. overflow_below returns formatted string when overflow exists
    s = ListState(total=30, page_size=10, scroll_top=0)
    result = overflow_below(s)
    _assert("overflow_below returns formatted string",
            result is not None and "20 more below" in result and "\u2193" in result,
            f"got {result!r}")

    # 14. Both return None when list fits in one page
    s = ListState(total=5, page_size=10, scroll_top=0)
    _assert("no overflow when list fits in page",
            overflow_above(s) is None and overflow_below(s) is None)

    # ------------------------------------------------------------------
    # marker
    # ------------------------------------------------------------------

    # 15. Returns gold >> for selected index
    s = ListState(total=5, selected=2)
    m = marker(s, 2)
    _assert("marker returns gold >> for selected",
            GOLD in m and ">>" in m,
            f"got {m!r}")

    # 16. Returns spaces for non-selected index
    s = ListState(total=5, selected=2)
    m = marker(s, 0)
    _assert("marker returns spaces for non-selected",
            m == "  ", f"got {m!r}")

    # ------------------------------------------------------------------
    # handle_input
    # ------------------------------------------------------------------

    # 17. Enter scrolls down with wrap (at last item, wraps to 0)
    s = ListState(total=5, selected=4)
    action = handle_input(s, "")
    _assert("Enter wraps to 0 from last",
            action == "scroll" and s.selected == 0,
            f"action={action}, selected={s.selected}")

    # 18. Enter on empty list returns scroll with selected=0
    s = ListState(total=0)
    action = handle_input(s, "")
    _assert("Enter on empty list",
            action == "scroll" and s.selected == 0,
            f"action={action}, selected={s.selected}")

    # 19. Up key clamps at 0 (doesn't wrap)
    s = ListState(total=5, selected=0)
    action = handle_input(s, "u")
    _assert("up clamps at 0",
            action == "up" and s.selected == 0,
            f"action={action}, selected={s.selected}")

    # 20. Down key clamps at total-1
    s = ListState(total=5, selected=4)
    action = handle_input(s, "j")
    _assert("down clamps at total-1",
            action == "down" and s.selected == 4,
            f"action={action}, selected={s.selected}")

    # 21. Numeric jump: "3" jumps to index 2
    s = ListState(total=10, selected=0)
    action = handle_input(s, "3")
    _assert("numeric jump '3' -> index 2",
            action == "jump" and s.selected == 2,
            f"action={action}, selected={s.selected}")

    # 22. Numeric jump to current position returns jump_act
    s = ListState(total=10, selected=4)
    action = handle_input(s, "5")
    _assert("numeric jump to current returns jump_act",
            action == "jump_act" and s.selected == 4,
            f"action={action}, selected={s.selected}")

    # 23. Numeric jump out of range gets clamped
    s = ListState(total=5, selected=0)
    action = handle_input(s, "99")
    _assert("numeric jump out of range clamped",
            action == "jump" and s.selected == 4,
            f"action={action}, selected={s.selected}")

    # 24. Open key returns open without changing state
    s = ListState(total=5, selected=2)
    action = handle_input(s, "v")
    _assert("open key returns open, no state change",
            action == "open" and s.selected == 2,
            f"action={action}, selected={s.selected}")

    # 25. q returns quit
    s = ListState(total=5, selected=2)
    action = handle_input(s, "q")
    _assert("q returns quit",
            action == "quit" and s.selected == 2,
            f"action={action}, selected={s.selected}")

    # 26. Unknown input returns unknown
    s = ListState(total=5, selected=2)
    action = handle_input(s, "z")
    _assert("unknown input returns unknown",
            action == "unknown" and s.selected == 2,
            f"action={action}, selected={s.selected}")

    # 27. Custom nav_keys: uses provided keys instead of defaults
    custom = ("s", "w", "d", "o")
    s = ListState(total=5, selected=0)
    action = handle_input(s, "w", nav_keys=custom)
    _assert("custom nav_keys: up with 'w'",
            action == "up",
            f"action={action}")
    s = ListState(total=5, selected=0)
    action = handle_input(s, "d", nav_keys=custom)
    _assert("custom nav_keys: down with 'd'",
            action == "down",
            f"action={action}")
    s = ListState(total=5, selected=0)
    action = handle_input(s, "o", nav_keys=custom)
    _assert("custom nav_keys: open with 'o'",
            action == "open",
            f"action={action}")

    # ------------------------------------------------------------------
    # footer_hint
    # ------------------------------------------------------------------

    # 28. Default keys produce correct format
    hint = footer_hint()
    _assert("footer_hint default keys",
            "[v] open" in hint and "[u]p" in hint and "[j] down" in hint and "[q] back" in hint,
            f"got {hint!r}")

    # 29. Custom keys appear in output
    hint = footer_hint(nav_keys=("s", "w", "d", "o"))
    _assert("footer_hint custom keys",
            "[o] open" in hint and "[w]p" in hint and "[d] down" in hint,
            f"got {hint!r}")

    # 30. Extra text is appended
    hint = footer_hint(extra="  [/]search  [f]ilter")
    _assert("footer_hint extra text",
            "[/]search" in hint and "[f]ilter" in hint,
            f"got {hint!r}")
