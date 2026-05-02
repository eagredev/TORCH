"""TextUtils suite -- GBA text wrapping, box counting, storyboard."""
from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("TextUtils")

    try:
        from torch.textutils import wrap_gba_text, count_text_boxes, storyboard_display, GBA_LINE_LEN
    except ImportError as e:
        _skip("all textutils tests", f"import failed: {e}")
        return

    import re as _re

    # -- Test 1: short text unchanged --
    try:
        short = "Short text"
        result = wrap_gba_text(short)
        _assert(
            "wrap_gba_text: short text unchanged",
            result == short,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("wrap short text", str(e))

    # -- Test 2: long line gets wrapped --
    try:
        long_text = "This is a really long line of text that definitely exceeds the thirty-eight character limit for GBA textboxes"
        result = wrap_gba_text(long_text)
        has_break = r"\n" in result or r"\p" in result
        _assert(
            "wrap_gba_text: long line gets breaks",
            has_break,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("wrap long text", str(e))

    # -- Test 3: no line segment exceeds 38 chars --
    try:
        long_text = "This is a really long line of text that definitely exceeds the thirty-eight character limit for GBA textboxes"
        result = wrap_gba_text(long_text)
        segments = _re.split(r'\\n|\\p', result)
        max_seg = max(len(s) for s in segments) if segments else 0
        _assert(
            "wrap_gba_text: no segment > 38 chars",
            max_seg <= GBA_LINE_LEN,
            f"max segment length: {max_seg}, segments: {segments}"
        )
    except Exception as e:
        _fail("wrap line length check", str(e))

    # -- Test 4: user's \\p markers are preserved --
    try:
        text_with_p = r"Hello world\pNew box here"
        result = wrap_gba_text(text_with_p)
        _assert(
            r"wrap_gba_text: user \p markers preserved",
            r"\p" in result,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("wrap preserves \\p", str(e))

    # -- Test 5: count_text_boxes short text -> 1 --
    try:
        result = count_text_boxes("Short")
        _assert(
            "count_text_boxes: 'Short' -> 1",
            result == 1,
            f"got: {result}"
        )
    except Exception as e:
        _fail("count_text_boxes short", str(e))

    # -- Test 6: count_text_boxes with \\n and \\p --
    try:
        text = r"Line one\nLine two\pLine three\nLine four"
        result = count_text_boxes(text)
        _assert(
            r"count_text_boxes: text with \n and \p -> 2",
            result == 2,
            f"got: {result}"
        )
    except Exception as e:
        _fail("count_text_boxes with breaks", str(e))

    # -- Test 7: count_text_boxes after wrapping long text -> > 1 --
    try:
        long_text = "This is a very long piece of dialogue that will certainly need to be wrapped across multiple textboxes because it far exceeds what can fit in a single GBA textbox"
        wrapped = wrap_gba_text(long_text)
        boxes = count_text_boxes(wrapped)
        _assert(
            "count_text_boxes: wrapped long text > 1 box",
            boxes > 1,
            f"got: {boxes} boxes for wrapped text: {wrapped!r}"
        )
    except Exception as e:
        _fail("count_text_boxes long text", str(e))

    # -- Test 8: storyboard_display renders breaks --
    try:
        text = r"Hello\nWorld\pNew box"
        result = storyboard_display(text)
        _assert(
            r"storyboard_display: \n and \p rendered",
            "\n" in result and "|" in result,
            f"got: {result!r}"
        )
    except Exception as e:
        _fail("storyboard_display", str(e))
