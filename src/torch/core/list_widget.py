"""Reusable scrolling list engine for TORCH.

Encapsulates the standard TORCH scrolling list pattern: scroll state
management, input dispatch, and overflow indicators.  Callers own all
rendering and I/O -- the widget is stateless and testable.

See ui-patterns.md for the full specification.
"""
# TORCH_MODULE: List Widget
# TORCH_GROUP: Core

from torch.colours import GOLD, DIM, RST

# ---------------------------------------------------------------------------
# Scroll state
# ---------------------------------------------------------------------------


class ListState:
    """Mutable scroll state for a list widget."""
    __slots__ = ("selected", "scroll_top", "page_size", "total")

    def __init__(self, total, page_size=20, selected=0, scroll_top=0):
        self.total = total
        self.page_size = page_size
        self.selected = max(0, min(selected, max(0, total - 1)))
        self.scroll_top = scroll_top


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def guard_bounds(state):
    """Clamp selected and scroll_top to keep the cursor in the visible window.

    Mutates *state* in place.  Returns nothing.
    """
    if state.total == 0:
        state.selected = 0
        state.scroll_top = 0
        return
    state.selected = max(0, min(state.selected, state.total - 1))
    if state.selected < state.scroll_top:
        state.scroll_top = state.selected
    if state.selected >= state.scroll_top + state.page_size:
        state.scroll_top = state.selected - state.page_size + 1


def visible_range(state):
    """Return (start, end) index range for the current visible window."""
    start = state.scroll_top
    end = min(state.scroll_top + state.page_size, state.total)
    return (start, end)


# ---------------------------------------------------------------------------
# Overflow indicators
# ---------------------------------------------------------------------------


def overflow_above(state):
    """Return a formatted overflow string if items exist above the viewport, else None."""
    if state.scroll_top > 0:
        return f"  {DIM}  \u2191 {state.scroll_top} more above{RST}"
    return None


def overflow_below(state):
    """Return a formatted overflow string if items exist below the viewport, else None."""
    remaining = state.total - (state.scroll_top + state.page_size)
    if remaining > 0:
        return f"  {DIM}  \u2193 {remaining} more below{RST}"
    return None


# ---------------------------------------------------------------------------
# Marker
# ---------------------------------------------------------------------------


def marker(state, index):
    """Return the selection marker for the given index.

    Returns gold '>>' if index is selected, else two spaces.
    """
    if index == state.selected:
        return f"{GOLD}>>{RST}"
    return "  "


# ---------------------------------------------------------------------------
# Input dispatch
# ---------------------------------------------------------------------------

_DEFAULT_NAV = ("p", "u", "j", "v")


def handle_input(state, raw, nav_keys=None):
    """Dispatch raw input and update scroll state.

    Returns an action string: "scroll", "up", "down", "open",
    "jump", "jump_act", "quit", or "unknown".
    """
    if nav_keys is None:
        nav_keys = _DEFAULT_NAV
    scroll_key, up_key, down_key, open_key = nav_keys
    key = raw.strip().lower()

    # Quit
    if key == "q":
        return "quit"

    # Open
    if key == open_key:
        return "open"

    # Enter (empty string) or scroll key: wrap
    if key == "" or key == scroll_key:
        state.selected = (state.selected + 1) % state.total if state.total > 0 else 0
        guard_bounds(state)
        return "scroll"

    # Up: clamp at 0
    if key == up_key or key == "k":
        state.selected = max(0, state.selected - 1)
        guard_bounds(state)
        return "up"

    # Down: clamp at bottom
    if key == down_key:
        state.selected = min(state.total - 1, state.selected + 1) if state.total > 0 else 0
        guard_bounds(state)
        return "down"

    # Numeric jump (1-indexed)
    if key.isdigit():
        target = int(key) - 1
        target = max(0, min(target, state.total - 1)) if state.total > 0 else 0
        if target == state.selected:
            return "jump_act"
        state.selected = target
        guard_bounds(state)
        return "jump"

    return "unknown"


# ---------------------------------------------------------------------------
# Footer hint
# ---------------------------------------------------------------------------


def footer_hint(nav_keys=None, extra=""):
    """Return a formatted footer string for the command bar.

    nav_keys: (scroll_key, up_key, down_key, open_key) tuple.
    extra: additional hints to append, e.g. '  [/]search  [f]ilter'.
    """
    if nav_keys is None:
        nav_keys = _DEFAULT_NAV
    _, up_key, down_key, open_key = nav_keys
    return (f"  [#]/[{open_key}] open  Enter scroll"
            f"  [{up_key}]p  [{down_key}] down{extra}  [q] back")
