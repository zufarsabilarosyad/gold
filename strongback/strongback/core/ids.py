"""Identifier normalisation and the sort order documents are printed in.

Schedule-of-values codes are written by humans and arrive as ``03300``,
``3300``, ``03-300`` and ``03300.1``.  They have to compare equal when they
mean the same line and sort the way a spec section sorts, which is not the way
strings sort.
"""

import re

from ..errors import InputError

__all__ = [
    "normalise_code",
    "code_sort_key",
    "normalise_id",
    "slugify",
    "is_valid_code",
    "next_sequence",
    "format_number",
]

_CODE_CLEAN = re.compile(r"[^0-9A-Za-z.]+")
_SEGMENT = re.compile(r"(\d+|[A-Za-z]+)")


def normalise_code(code):
    """Normalise a schedule-of-values or cost code for comparison.

    >>> normalise_code(" 03-300 ")
    '03300'
    >>> normalise_code("03300.1")
    '03300.1'
    """
    text = _CODE_CLEAN.sub("", str(code).strip())
    if not text:
        raise InputError("a code cannot be empty: %r" % (code,))
    return text.upper()


def is_valid_code(code):
    """Return True when a string can be used as a code.

    >>> is_valid_code("02-100")
    True
    >>> is_valid_code("   ")
    False
    """
    try:
        normalise_code(code)
    except InputError:
        return False
    return True


def code_sort_key(code):
    """Return a key that sorts codes numerically segment by segment.

    >>> sorted(["10", "9", "9.1"], key=code_sort_key)
    ['9', '9.1', '10']
    """
    parts = []
    for chunk in normalise_code(code).split("."):
        for segment in _SEGMENT.findall(chunk):
            if segment.isdigit():
                parts.append((0, int(segment), ""))
            else:
                parts.append((1, 0, segment))
        parts.append((2, 0, ""))
    return tuple(parts)


def normalise_id(value, what="identifier"):
    """Normalise a document identifier, keeping case but trimming space.

    >>> normalise_id("  CO-014 ")
    'CO-014'
    """
    text = str(value).strip()
    if not text:
        raise InputError("%s cannot be empty" % (what,))
    return " ".join(text.split())


def slugify(value):
    """Reduce a label to a filename-safe slug.

    >>> slugify("Concrete -- Slab on Grade")
    'concrete-slab-on-grade'
    """
    text = re.sub(r"[^0-9A-Za-z]+", "-", str(value).strip().lower())
    return text.strip("-") or "item"


def next_sequence(existing, prefix="", width=3):
    """Return the next identifier in a numbered series.

    >>> next_sequence(["CO-001", "CO-002"], prefix="CO-")
    'CO-003'
    >>> next_sequence([], prefix="PA-", width=2)
    'PA-01'
    """
    highest = 0
    for item in existing:
        text = normalise_id(item)
        if prefix and not text.upper().startswith(prefix.upper()):
            continue
        tail = text[len(prefix):] if prefix else text
        digits = "".join(character for character in tail if character.isdigit())
        if digits:
            highest = max(highest, int(digits))
    return "%s%0*d" % (prefix, int(width), highest + 1)


def format_number(value, width=3):
    """Zero-pad an integer for a document number.

    >>> format_number(7)
    '007'
    """
    return "%0*d" % (int(width), int(value))
