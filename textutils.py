"""GBA text utilities: wrapping, box-counting, preview, storyboard display.

All functions are pure stdlib — no imports from any other torch module.
This eliminates the circular lazy-import that existed between ui.py and
battle_wizard.py (_dialogue_prompt importing _wrap_dialogue at call time).
"""
# TORCH_MODULE: Text Utilities
# TORCH_GROUP: Core
import re

TEXTUTILS_VERSION = "1.0"

GBA_LINE_LEN = 38
GBA_LINES_PER_BOX = 2


def wrap_gba_text(text, line_len=GBA_LINE_LEN):
    """Wrap text into GBA textbox format.

    Preserves user's \\n and \\p markers.  Word-wraps each plain-text
    segment at line_len.  Upgrades every 2nd \\n in a box to \\p.
    Returns the formatted string (without trailing $).
    """
    # Split on existing \\n and \\p, keeping the delimiters
    segments = re.split(r'(\\n|\\p)', text)

    # Rebuild: process each plain-text segment, wrapping at line_len
    result_tokens = []  # list of strings/markers
    for seg in segments:
        if seg in (r'\n', r'\p'):
            result_tokens.append(seg)
            continue
        # Word-wrap this segment into lines of max line_len chars
        words = seg.split(' ')
        line = ''
        for word in words:
            if not word:
                continue
            if not line:
                line = word
            elif len(line) + 1 + len(word) <= line_len:
                line += ' ' + word
            else:
                result_tokens.append(line)
                result_tokens.append(r'\n')
                line = word
        if line:
            result_tokens.append(line)

    # Now walk result_tokens, which are interleaved text and \n/\p markers.
    # \n markers come from word-wrap overflow OR user's own \n.
    # \p markers come only from the user.
    # Rule: upgrade every 2nd \n in a sequence to \p (2 lines per box).
    out = ''
    lines_in_box = 0  # how many lines have been written in the current box

    for tok in result_tokens:
        if tok == r'\p':
            # User explicitly started a new box
            out += r'\p'
            lines_in_box = 0
        elif tok == r'\n':
            # A line break — either word-wrap generated or user's \n
            lines_in_box += 1
            if lines_in_box >= 2:
                # Box is full; upgrade to \p and reset
                out += r'\p'
                lines_in_box = 0
            else:
                out += r'\n'
        else:
            # Plain text line
            out += tok

    return out


def count_text_boxes(text):
    """Count how many textboxes the text will need (1 box = 2 lines)."""
    lines_in_box = 0
    boxes = 1
    for tok in re.split(r'(\\n|\\p)', text):
        if tok == r'\p':
            boxes += 1
            lines_in_box = 0
        elif tok == r'\n':
            lines_in_box += 1
            if lines_in_box >= 2:
                boxes += 1
                lines_in_box = 0
    return boxes


def textbox_preview(text, textbox_warning=3):
    """Show a GBA textbox preview of dialogue text with box markers and char counts.

    Prints a visual preview to stdout.
    Returns (display_text, was_wrapped) where display_text is the (possibly
    auto-wrapped) text and was_wrapped is True if wrapping was applied.
    """
    line_len = GBA_LINE_LEN

    # Check if wrapping is needed
    segments = re.split(r'\\n|\\p', text)
    needs_wrap = any(len(s) > line_len for s in segments)
    display_text = wrap_gba_text(text) if needs_wrap else text

    box_count = count_text_boxes(display_text)

    # Render preview
    print("  " + "\u2500" * 40)

    # Split into visual lines at \n and \p markers
    current_line = ""
    lines_in_box = 0
    box_num = 1

    tokens = re.split(r'(\\n|\\p)', display_text)
    for tok in tokens:
        if tok == r'\p':
            # Print current line
            if current_line:
                count = len(current_line)
                warn = " !" if count > line_len else ""
                print(f"  {current_line:<{line_len}}  ({count}{warn})")
                current_line = ""
            print(f"  {'--- box ' + str(box_num + 1) + ' ---':^{line_len}}")
            box_num += 1
            lines_in_box = 0
        elif tok == r'\n':
            if current_line:
                count = len(current_line)
                warn = " !" if count > line_len else ""
                print(f"  {current_line:<{line_len}}  ({count}{warn})")
                current_line = ""
            lines_in_box += 1
        else:
            current_line += tok

    # Print last line
    if current_line:
        count = len(current_line)
        warn = " !" if count > line_len else ""
        print(f"  {current_line:<{line_len}}  ({count}{warn})")

    print("  " + "\u2500" * 40)
    print(f"  {box_count} textbox{'es' if box_count != 1 else ''}", end="")
    if box_count > textbox_warning:
        print(f"  (warning: aim for {textbox_warning} or fewer)")
    else:
        print()

    if needs_wrap:
        print("  (auto-wrapped to fit GBA textbox)")

    return display_text, needs_wrap


def storyboard_display(text, max_len=68):
    """Format dialogue for storyboard — render \\n as line breaks, \\p as box markers."""
    display = text.replace("\\p", "\n         |\n         ")
    display = display.replace("\\n", "\n         ")
    lines = display.split("\n")
    if len(lines) > 6:
        lines = lines[:5] + ["         ..."]
        display = "\n".join(lines)
    return display


def dialogue_prompt(label, is_double=False, textbox_warning=3):
    """Prompt for dialogue text with auto-wrap preview and length check.

    Returns the final formatted text (ready for Poryscript, no trailing $).
    GBA textbox: 38 chars per line, 2 lines per box.

    is_double is accepted for backward compatibility but unused.
    """
    MAX_BOXES = textbox_warning
    line_len = GBA_LINE_LEN

    while True:
        print(f"  {label}")
        print(f"  (Max {line_len} characters per line. Aim for 1-2 textboxes.)")
        raw = input("  > ").strip()
        if not raw:
            print("  This field is required.")
            print()
            continue

        # Check if any individual segment is too long to fit on one line
        segments = re.split(r'\\n|\\p', raw)
        needs_wrap = any(len(s) > line_len for s in segments)

        if needs_wrap:
            wrapped = wrap_gba_text(raw)
        else:
            wrapped = raw

        # Count boxes
        box_count = count_text_boxes(wrapped)
        if box_count > MAX_BOXES:
            print()
            print(f"  Warning: This text needs {box_count} textboxes. Aim for {MAX_BOXES} or fewer.")
            print(f"  Very long dialogue can feel slow to read and may cause display issues.")
            yn = input("  Use it anyway? [y/N] > ").strip().lower()
            if yn != "y":
                print()
                continue

        if not needs_wrap:
            # Already fits — no confirmation needed
            return raw

        # Show wrap preview
        print()
        print("  Auto-wrapped preview:")
        print("  " + "-" * 40)
        display = wrapped.replace(r'\p', '  [new box]\n').replace(r'\n', '\n  ')
        for line in display.split('\n'):
            print(f"  {line}")
        print("  " + "-" * 40)
        print()
        yn = input("  Use this? [Y/re-type] > ").strip().lower()
        if yn in ("", "y", "yes"):
            return wrapped
        print()
        continue
