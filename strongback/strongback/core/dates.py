"""Calendar arithmetic, with no clock in it.

Nothing in this package reads the current date.  Every run is a function of the
documents it is given, so a pay application built today and rebuilt next year
produces byte-identical output.  Where a real system would call ``today()``,
this one takes an ``as_of`` argument and makes the caller say what day it is.
"""

import datetime

from ..errors import InputError, ParseError

__all__ = [
    "parse_date",
    "format_date",
    "add_days",
    "add_months",
    "month_start",
    "month_end",
    "days_in_month",
    "days_between",
    "date_range",
    "clamp_date",
    "min_date",
    "max_date",
    "is_weekend",
    "day_name",
    "MONTH_NAMES",
    "last_weekday_of_month",
    "nth_weekday_of_month",
]

MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

DAY_NAMES = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)


def parse_date(value, what="date"):
    """Read an ISO date string, a date, or a datetime into a date.

    >>> parse_date("2024-10-31")
    datetime.date(2024, 10, 31)
    """
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            return datetime.date(*(int(part) for part in text.split("-")))
        except (TypeError, ValueError):
            raise ParseError("%s is not an ISO date: %r" % (what, value))
    raise InputError("%s has unusable type %s" % (what, type(value).__name__))


def format_date(value):
    """Render a date as ISO, which is the only format this package emits.

    >>> format_date(datetime.date(2024, 9, 30))
    '2024-09-30'
    """
    return parse_date(value).isoformat()


def add_days(value, count):
    """Return the date ``count`` calendar days later.

    >>> add_days("2024-10-31", 1)
    datetime.date(2024, 11, 1)
    """
    return parse_date(value) + datetime.timedelta(days=int(count))


def add_months(value, count):
    """Return the same day-of-month ``count`` months later, clamped to the end.

    >>> add_months("2024-01-31", 1)
    datetime.date(2024, 2, 29)
    """
    value = parse_date(value)
    total_month = value.year * 12 + (value.month - 1) + int(count)
    year, month = divmod(total_month, 12)
    month += 1
    day = min(value.day, days_in_month(year, month))
    return datetime.date(year, month, day)


def days_in_month(year, month):
    """Return the number of days in a month.

    >>> days_in_month(2024, 2)
    29
    """
    year = int(year)
    month = int(month)
    if not 1 <= month <= 12:
        raise InputError("month must be 1..12, got %r" % (month,))
    if month == 12:
        following = datetime.date(year + 1, 1, 1)
    else:
        following = datetime.date(year, month + 1, 1)
    return (following - datetime.date(year, month, 1)).days


def month_start(value):
    """Return the first day of the month containing ``value``.

    >>> month_start("2024-11-14")
    datetime.date(2024, 11, 1)
    """
    value = parse_date(value)
    return datetime.date(value.year, value.month, 1)


def month_end(value):
    """Return the last day of the month containing ``value``.

    >>> month_end("2024-11-14")
    datetime.date(2024, 11, 30)
    """
    value = parse_date(value)
    return datetime.date(value.year, value.month, days_in_month(value.year, value.month))


def days_between(start, end, inclusive=False):
    """Return the count of calendar days from ``start`` to ``end``.

    >>> days_between("2024-09-01", "2024-09-30")
    29
    >>> days_between("2024-09-01", "2024-09-30", inclusive=True)
    30
    """
    span = (parse_date(end, "end") - parse_date(start, "start")).days
    return span + 1 if inclusive else span


def date_range(start, end, step=1):
    """Yield dates from ``start`` through ``end`` inclusive.

    >>> [format_date(day) for day in date_range("2024-09-01", "2024-09-03")]
    ['2024-09-01', '2024-09-02', '2024-09-03']
    """
    start = parse_date(start, "start")
    end = parse_date(end, "end")
    step = int(step)
    if step <= 0:
        raise InputError("step must be positive, got %r" % (step,))
    current = start
    while current <= end:
        yield current
        current = current + datetime.timedelta(days=step)


def clamp_date(value, low=None, high=None):
    """Constrain a date to a window, ignoring bounds that are ``None``."""
    value = parse_date(value)
    if low is not None and value < parse_date(low, "low"):
        return parse_date(low, "low")
    if high is not None and value > parse_date(high, "high"):
        return parse_date(high, "high")
    return value


def min_date(*values):
    """Return the earliest of the given dates, ignoring ``None``."""
    present = [parse_date(value) for value in values if value is not None]
    if not present:
        return None
    return min(present)


def max_date(*values):
    """Return the latest of the given dates, ignoring ``None``."""
    present = [parse_date(value) for value in values if value is not None]
    if not present:
        return None
    return max(present)


def is_weekend(value, weekend=(5, 6)):
    """Return True when the date falls on a weekend day.

    >>> is_weekend("2024-09-14")
    True
    """
    return parse_date(value).weekday() in tuple(weekend)


def day_name(value):
    """Return the English weekday name.

    >>> day_name("2024-09-16")
    'Monday'
    """
    return DAY_NAMES[parse_date(value).weekday()]


def nth_weekday_of_month(year, month, weekday, occurrence):
    """Return, say, the third Monday of a month.

    >>> nth_weekday_of_month(2024, 1, 0, 3)
    datetime.date(2024, 1, 15)
    """
    first = datetime.date(int(year), int(month), 1)
    offset = (int(weekday) - first.weekday()) % 7
    day = 1 + offset + (int(occurrence) - 1) * 7
    if day > days_in_month(year, month):
        raise InputError(
            "month %d/%d has no occurrence %d of weekday %d"
            % (month, year, occurrence, weekday)
        )
    return datetime.date(int(year), int(month), day)


def last_weekday_of_month(year, month, weekday):
    """Return the last given weekday of a month.

    >>> last_weekday_of_month(2024, 5, 0)
    datetime.date(2024, 5, 27)
    """
    last = datetime.date(int(year), int(month), days_in_month(year, month))
    offset = (last.weekday() - int(weekday)) % 7
    return last - datetime.timedelta(days=offset)
