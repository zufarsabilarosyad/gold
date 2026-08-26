"""Application numbers, and why they are not just a counter.

Numbering looks trivial until an application is rejected.  Does the resubmitted
one keep the number, take the next one, or become ``7R1``?  All three are used,
and the choice is visible for the rest of the job: under one scheme application
8 follows application 7, under another it follows 7R1, and a lender's draw
schedule that expects consecutive numbers rejects the third.

The schemes are named here and applied by the builder, so a contract can state
one and the run can prove it followed it.
"""

from ..core.ids import format_number, normalise_id
from ..errors import DataError, InputError

__all__ = ["SCHEMES", "next_number", "format_application_id", "find_gaps", "revision_id"]

SCHEMES = ("sequential", "period", "prefixed")


def next_number(existing, scheme="sequential", period=None):
    """Return the next application number under a scheme.

    >>> next_number([1, 2, 3])
    4
    >>> next_number([], scheme="period", period=7)
    7
    >>> next_number([1, 2], scheme="period", period=5)
    5
    """
    scheme = str(scheme)
    if scheme not in SCHEMES:
        raise InputError("unknown numbering scheme %r; known: %s" % (scheme, ", ".join(SCHEMES)))
    numbers = [int(number) for number in existing]
    if scheme == "period":
        if period is None:
            raise InputError("period numbering needs a period")
        return int(period)
    if not numbers:
        return 1
    return max(numbers) + 1


def format_application_id(number, prefix="PA-", width=3):
    """Return the document identifier for an application number.

    >>> format_application_id(7)
    'PA-007'
    >>> format_application_id(12, prefix="APP", width=2)
    'APP12'
    """
    return "%s%s" % (prefix, format_number(number, width))


def revision_id(identifier, revision):
    """Return the identifier of a revised application.

    >>> revision_id("PA-007", 1)
    'PA-007R1'
    >>> revision_id("PA-007R1", 2)
    'PA-007R2'
    """
    text = normalise_id(identifier, "application id")
    revision = int(revision)
    if revision < 1:
        raise InputError("revision numbers start at 1, got %r" % (revision,))
    base = text.split("R")[0] if "R" in text[3:] else text
    return "%sR%d" % (base, revision)


def find_gaps(numbers):
    """Return the missing numbers in a run of applications.

    >>> find_gaps([1, 2, 4, 6])
    [3, 5]
    >>> find_gaps([])
    []
    """
    numbers = sorted({int(number) for number in numbers})
    if not numbers:
        return []
    return [
        number
        for number in range(numbers[0], numbers[-1] + 1)
        if number not in set(numbers)
    ]


def check_consecutive(numbers):
    """Raise when a run of application numbers has a hole in it.

    >>> check_consecutive([1, 2, 3])
    >>> check_consecutive([1, 3])
    Traceback (most recent call last):
        ...
    strongback.errors.DataError: applications are not consecutive; missing 2
    """
    gaps = find_gaps(numbers)
    if gaps:
        raise DataError(
            "applications are not consecutive; missing %s"
            % (", ".join(str(gap) for gap in gaps),)
        )
