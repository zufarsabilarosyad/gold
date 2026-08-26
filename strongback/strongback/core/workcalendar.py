"""Working calendars: which days count when a contract says "days".

Payment terms are written in days, and the word means at least three different
things depending on who drafted the clause: calendar days, business days, or
business days on a calendar that includes the owner's holiday shutdown.  A
:class:`WorkCalendar` makes the choice explicit and reusable, and the day-count
basis that selects between them lives in policy, not in the arithmetic.
"""

import datetime

from ..errors import InputError
from .dates import (
    add_days,
    format_date,
    last_weekday_of_month,
    nth_weekday_of_month,
    parse_date,
)

__all__ = [
    "WorkCalendar",
    "federal_holidays",
    "STANDARD_WEEKEND",
    "SIX_DAY_WEEK",
    "calendar_named",
]

STANDARD_WEEKEND = (5, 6)
SIX_DAY_WEEK = (6,)


def _observed(day):
    """Shift a holiday off a weekend the way a payroll office would."""
    if day.weekday() == 5:
        return day - datetime.timedelta(days=1)
    if day.weekday() == 6:
        return day + datetime.timedelta(days=1)
    return day


def federal_holidays(year, observed=True):
    """Return the eleven United States federal holidays for a year.

    The set is computed, never looked up, so any year works and no data file
    can drift.

    >>> holidays = federal_holidays(2024)
    >>> format_date(min(holidays))
    '2024-01-01'
    >>> len(holidays)
    11
    """
    year = int(year)
    days = [
        datetime.date(year, 1, 1),
        nth_weekday_of_month(year, 1, 0, 3),
        nth_weekday_of_month(year, 2, 0, 3),
        last_weekday_of_month(year, 5, 0),
        datetime.date(year, 6, 19),
        datetime.date(year, 7, 4),
        nth_weekday_of_month(year, 9, 0, 1),
        nth_weekday_of_month(year, 10, 0, 2),
        datetime.date(year, 11, 11),
        nth_weekday_of_month(year, 11, 3, 4),
        datetime.date(year, 12, 25),
    ]
    if observed:
        days = [_observed(day) for day in days]
    return frozenset(days)


class WorkCalendar:
    """A weekend mask plus a holiday set, with business-day arithmetic.

    >>> work = WorkCalendar("us", holidays=["2024-11-28"])
    >>> work.is_workday("2024-11-28")
    False
    >>> format_date(work.add_business_days("2024-11-27", 1))
    '2024-11-29'
    >>> work.business_days_between("2024-11-25", "2024-12-02")
    4
    """

    __slots__ = ("name", "weekend", "holidays", "auto_federal")

    def __init__(self, name="calendar", weekend=STANDARD_WEEKEND, holidays=(), auto_federal=False):
        self.name = str(name)
        weekend = tuple(sorted({int(day) for day in weekend}))
        for day in weekend:
            if not 0 <= day <= 6:
                raise InputError("weekend days are 0..6, got %r" % (day,))
        self.weekend = weekend
        self.holidays = frozenset(parse_date(day, "holiday") for day in holidays)
        self.auto_federal = bool(auto_federal)

    def holidays_for_year(self, year):
        """Return every holiday observed in a year, computed and explicit."""
        days = set(day for day in self.holidays if day.year == int(year))
        if self.auto_federal:
            days |= set(federal_holidays(year))
        return frozenset(days)

    def is_holiday(self, day):
        """Return True when the date is a holiday on this calendar."""
        day = parse_date(day)
        if day in self.holidays:
            return True
        return self.auto_federal and day in federal_holidays(day.year)

    def is_weekend(self, day):
        """Return True when the date falls on this calendar's weekend."""
        return parse_date(day).weekday() in self.weekend

    def is_workday(self, day):
        """Return True when work is expected on the date."""
        day = parse_date(day)
        return not self.is_weekend(day) and not self.is_holiday(day)

    def next_workday(self, day, include_self=False):
        """Return the first workday on or after ``day``."""
        current = parse_date(day)
        if not include_self:
            current = add_days(current, 1)
        for _ in range(400):
            if self.is_workday(current):
                return current
            current = add_days(current, 1)
        raise InputError("no workday found within a year of %s" % (format_date(day),))

    def previous_workday(self, day, include_self=False):
        """Return the last workday on or before ``day``."""
        current = parse_date(day)
        if not include_self:
            current = add_days(current, -1)
        for _ in range(400):
            if self.is_workday(current):
                return current
            current = add_days(current, -1)
        raise InputError("no workday found within a year before %s" % (format_date(day),))

    def add_business_days(self, day, count):
        """Return the date ``count`` business days from ``day``.

        Zero returns the same date whether or not it is a workday; the caller
        decides whether to roll it first.
        """
        current = parse_date(day)
        count = int(count)
        step = 1 if count >= 0 else -1
        remaining = abs(count)
        while remaining:
            current = add_days(current, step)
            if self.is_workday(current):
                remaining -= 1
        return current

    def business_days_between(self, start, end):
        """Count workdays after ``start`` up to and including ``end``."""
        start = parse_date(start, "start")
        end = parse_date(end, "end")
        if end < start:
            return -self.business_days_between(end, start)
        count = 0
        current = add_days(start, 1)
        while current <= end:
            if self.is_workday(current):
                count += 1
            current = add_days(current, 1)
        return count

    def workdays_in(self, start, end):
        """Return the list of workdays in an inclusive window."""
        start = parse_date(start, "start")
        end = parse_date(end, "end")
        days = []
        current = start
        while current <= end:
            if self.is_workday(current):
                days.append(current)
            current = add_days(current, 1)
        return days

    def describe(self):
        """Return a one-line description for a report header."""
        weekend = "/".join(str(day) for day in self.weekend) or "none"
        listed = "%d listed" % (len(self.holidays),)
        source = "federal + " + listed if self.auto_federal else listed
        return "%s (weekend %s, holidays %s)" % (self.name, weekend, source)

    def __eq__(self, other):
        return (
            isinstance(other, WorkCalendar)
            and other.weekend == self.weekend
            and other.holidays == self.holidays
            and other.auto_federal == self.auto_federal
        )

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("WorkCalendar", self.weekend, self.holidays, self.auto_federal))

    def __repr__(self):
        return "WorkCalendar(%r, holidays=%d)" % (self.name, len(self.holidays))


def calendar_named(name):
    """Return one of the built-in calendars by name.

    >>> calendar_named("us-federal").auto_federal
    True
    >>> calendar_named("seven-day").is_workday("2024-09-15")
    True
    """
    key = str(name).strip().lower()
    if key in ("us", "us-federal", "federal"):
        return WorkCalendar("us-federal", STANDARD_WEEKEND, (), auto_federal=True)
    if key in ("five-day", "weekdays"):
        return WorkCalendar("five-day", STANDARD_WEEKEND, ())
    if key in ("six-day",):
        return WorkCalendar("six-day", SIX_DAY_WEEK, ())
    if key in ("seven-day", "calendar", "all"):
        return WorkCalendar("seven-day", (), ())
    raise InputError("unknown calendar %r" % (name,))
