"""Text helpers for the report layer, and nothing else.

Everything here is pure string work.  It lives in ``core`` because both the
report modules and the CLI need it and neither should import the other.
"""

from ..errors import InputError

__all__ = [
    "pad",
    "truncate",
    "wrap",
    "underline",
    "indent",
    "join_lines",
    "title_case",
    "plural",
    "yes_no",
    "bullet_list",
]


def pad(text, width, align="left", fill=" "):
    """Pad text to a width, left, right or centred.

    >>> pad("ab", 5)
    'ab   '
    >>> pad("ab", 5, "right")
    '   ab'
    >>> pad("ab", 5, "center")
    ' ab  '
    """
    text = "" if text is None else str(text)
    width = int(width)
    if len(text) >= width:
        return text
    gap = width - len(text)
    if align == "left":
        return text + fill * gap
    if align == "right":
        return fill * gap + text
    if align in ("center", "centre"):
        left = gap // 2
        return fill * left + text + fill * (gap - left)
    raise InputError("unknown alignment %r" % (align,))


def truncate(text, width, marker="..."):
    """Shorten text to a width, marking that it was cut.

    >>> truncate("concrete slab on grade", 12)
    'concrete...'
    """
    text = "" if text is None else str(text)
    width = int(width)
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= len(marker):
        return text[:width]
    return text[: width - len(marker)].rstrip() + marker


def wrap(text, width):
    """Wrap text on spaces into lines no longer than ``width``.

    >>> wrap("one two three four", 9)
    ['one two', 'three', 'four']
    """
    words = str(text).split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= int(width):
            current = current + " " + word
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def underline(text, character="="):
    """Return the text with a rule under it.

    >>> underline("Title", "-")
    'Title\\n-----'
    """
    text = str(text)
    return text + "\n" + character * len(text)


def indent(text, spaces=2):
    """Indent every line of a block, leaving blank lines blank.

    >>> indent("a\\n\\nb")
    '  a\\n\\n  b'
    """
    prefix = " " * int(spaces)
    return "\n".join(prefix + line if line.strip() else line for line in str(text).split("\n"))


def join_lines(*blocks):
    """Join non-empty blocks with a blank line between them."""
    present = [str(block).rstrip() for block in blocks if str(block).strip()]
    return "\n\n".join(present)


def title_case(text):
    """Capitalise words, leaving small joining words alone.

    >>> title_case("schedule of values")
    'Schedule of Values'
    """
    small = {"of", "and", "the", "to", "for", "in", "on", "a", "an", "less", "per"}
    words = str(text).split()
    out = []
    for index, word in enumerate(words):
        if index and word.lower() in small:
            out.append(word.lower())
        else:
            out.append(word[:1].upper() + word[1:])
    return " ".join(out)


def plural(count, singular, plural_form=None):
    """Return ``'1 line'`` or ``'2 lines'``.

    >>> plural(1, "line")
    '1 line'
    >>> plural(0, "line")
    '0 lines'
    """
    count = int(count)
    if count == 1:
        return "1 %s" % (singular,)
    return "%d %s" % (count, plural_form or singular + "s")


def yes_no(flag):
    """Render a boolean the way a report column does.

    >>> yes_no(True), yes_no(False)
    ('yes', 'no')
    """
    return "yes" if flag else "no"


def bullet_list(items, marker="-"):
    """Render an iterable as a bullet list, or a dash when empty.

    >>> bullet_list(["a", "b"])
    '- a\\n- b'
    >>> bullet_list([])
    '(none)'
    """
    items = [str(item) for item in items]
    if not items:
        return "(none)"
    return "\n".join("%s %s" % (marker, item) for item in items)
