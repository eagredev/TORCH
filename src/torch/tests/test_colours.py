"""Tests for the shared ANSI colour palette."""
from torch.tests.harness import _begin_suite, _assert, _ok, _fail


def run_suite():
    _begin_suite("colours")

    from torch.colours import GOLD, WHITE, CYAN, GREEN, DIM, RST
    from torch.colours import RED, BOLD_RED, BLUE, DGOLD, BOLD
    from torch.colours import strip_ansi

    # Core constants are non-empty strings containing \033[
    for name, val in [("GOLD", GOLD), ("WHITE", WHITE), ("CYAN", CYAN),
                      ("GREEN", GREEN), ("DIM", DIM), ("RST", RST),
                      ("RED", RED), ("BOLD_RED", BOLD_RED), ("BLUE", BLUE),
                      ("DGOLD", DGOLD), ("BOLD", BOLD)]:
        _assert(f"{name} is non-empty ANSI",
                isinstance(val, str) and len(val) > 0 and "\033[" in val,
                f"{name} = {val!r}")

    # RST is exactly \033[0m
    _assert("RST is reset code", RST == "\033[0m", f"RST = {RST!r}")

    # strip_ansi: plain text passes through
    _assert("strip plain text", strip_ansi("hello world") == "hello world")

    # strip_ansi: coloured text returns clean
    _assert("strip coloured text",
            strip_ansi(GOLD + "hello" + RST) == "hello",
            f"got {strip_ansi(GOLD + 'hello' + RST)!r}")

    # strip_ansi: nested codes handled
    nested = f"{BOLD}{RED}error{RST}: {DIM}details{RST}"
    _assert("strip nested codes",
            strip_ansi(nested) == "error: details",
            f"got {strip_ansi(nested)!r}")

    # strip_ansi: empty string returns empty
    _assert("strip empty string", strip_ansi("") == "")

    # strip_ansi: string with no ANSI passes through unchanged
    _assert("strip no-ansi string", strip_ansi("no codes here") == "no codes here")
