"""Billing periods, and the through-date that is not the same as the end date.

A pay application covers a period, but the work it certifies is measured
*through* a date that is often earlier -- the twenty-fifth of the month is a
common cutoff on a period that ends on the thirtieth, so the application can
reach the owner before month end.  Confusing the two is how work gets billed
twice: once in the tail of one period and again at the head of the next.
"""

from .dates import (
    add_days,
    add_months,
    days_between,
    format_date,
    month_end,
    month_start,
    parse_date,
)
from ..errors import InputError, PeriodError

__all__ = ["BillingPeriod", "PeriodSchedule", "monthly_schedule"]


class BillingPeriod:
    """One numbered application period, with a cutoff for measured work.

    >>> period = BillingPeriod(1, "2024-09-01", "2024-09-30")
    >>> period.through
    datetime.date(2024, 9, 30)
    >>> BillingPeriod(2, "2024-10-01", "2024-10-31", through="2024-10-25").length_days
    31
    """

    __slots__ = ("number", "start", "end", "through", "label")

    def __init__(self, number, start, end, through=None, label=""):
        self.number = int(number)
        if self.number < 1:
            raise InputError("period numbers start at 1, got %r" % (number,))
        self.start = parse_date(start, "period start")
        self.end = parse_date(end, "period end")
        if self.end < self.start:
            raise PeriodError(
                "period %d ends %s before it starts %s"
                % (self.number, format_date(self.end), format_date(self.start))
            )
        self.through = parse_date(through, "through") if through is not None else self.end
        if self.through < self.start or self.through > self.end:
            raise PeriodError(
                "period %d through date %s falls outside %s..%s"
                % (
                    self.number,
                    format_date(self.through),
                    format_date(self.start),
                    format_date(self.end),
                )
            )
        self.label = str(label) or "Application %d" % (self.number,)

    @property
    def length_days(self):
        """Return the inclusive length of the period in calendar days."""
        return days_between(self.start, self.end, inclusive=True)

    @property
    def measured_days(self):
        """Return the inclusive days from the start to the through date."""
        return days_between(self.start, self.through, inclusive=True)

    def contains(self, day):
        """Return True when a date falls inside the period, ends included."""
        day = parse_date(day)
        return self.start <= day <= self.end

    def covers_work_on(self, day):
        """Return True when work done on ``day`` belongs to this period.

        Work after the through date belongs to the next application even
        though the calendar period has not closed.
        """
        day = parse_date(day)
        return self.start <= day <= self.through

    def with_through(self, through):
        """Return a copy with a different measurement cutoff."""
        return BillingPeriod(self.number, self.start, self.end, through, self.label)

    def to_dict(self):
        """Return the period as plain data for export."""
        return {
            "number": self.number,
            "start": format_date(self.start),
            "end": format_date(self.end),
            "through": format_date(self.through),
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild a period from :meth:`to_dict` output."""
        return cls(
            data["number"],
            data["start"],
            data["end"],
            data.get("through"),
            data.get("label", ""),
        )

    def __eq__(self, other):
        return (
            isinstance(other, BillingPeriod)
            and other.number == self.number
            and other.start == self.start
            and other.end == self.end
            and other.through == self.through
        )

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("BillingPeriod", self.number, self.start, self.end, self.through))

    def __lt__(self, other):
        return (self.number, self.start) < (other.number, other.start)

    def __str__(self):
        return "#%d %s..%s" % (self.number, format_date(self.start), format_date(self.end))

    def __repr__(self):
        return "BillingPeriod(%d, %r, %r)" % (
            self.number,
            format_date(self.start),
            format_date(self.end),
        )


class PeriodSchedule:
    """An ordered, gapless run of billing periods.

    >>> schedule = monthly_schedule("2024-09-01", 3)
    >>> len(schedule)
    3
    >>> str(schedule.period(2))
    '#2 2024-10-01..2024-10-31'
    >>> schedule.period_covering("2024-11-04").number
    3
    """

    __slots__ = ("periods",)

    def __init__(self, periods):
        ordered = sorted(periods, key=lambda item: (item.number, item.start))
        if not ordered:
            raise PeriodError("a schedule needs at least one period")
        for index, period in enumerate(ordered, start=1):
            if period.number != index:
                raise PeriodError(
                    "period numbers must run 1..n without gaps; found %d at position %d"
                    % (period.number, index)
                )
        for earlier, later in zip(ordered, ordered[1:]):
            if later.start <= earlier.end:
                raise PeriodError(
                    "period %d starts %s before period %d ends %s"
                    % (
                        later.number,
                        format_date(later.start),
                        earlier.number,
                        format_date(earlier.end),
                    )
                )
        self.periods = tuple(ordered)

    def __len__(self):
        return len(self.periods)

    def __iter__(self):
        return iter(self.periods)

    def __getitem__(self, index):
        return self.periods[index]

    def period(self, number):
        """Return the period with the given number."""
        for period in self.periods:
            if period.number == int(number):
                return period
        raise PeriodError("no period numbered %r in this schedule" % (number,))

    def period_covering(self, day):
        """Return the period containing a date, or raise if none does."""
        day = parse_date(day)
        for period in self.periods:
            if period.contains(day):
                return period
        raise PeriodError("no period covers %s" % (format_date(day),))

    def through(self, number):
        """Return the periods numbered 1..``number`` inclusive."""
        return tuple(period for period in self.periods if period.number <= int(number))

    def previous(self, number):
        """Return the period before ``number``, or None for the first."""
        number = int(number)
        if number <= 1:
            return None
        return self.period(number - 1)

    def extend(self, count=1):
        """Return a longer schedule, adding months after the final period."""
        periods = list(self.periods)
        for _ in range(int(count)):
            last = periods[-1]
            start = add_days(last.end, 1)
            periods.append(BillingPeriod(last.number + 1, start, month_end(start)))
        return PeriodSchedule(periods)

    def to_list(self):
        """Return the schedule as plain data."""
        return [period.to_dict() for period in self.periods]

    @classmethod
    def from_list(cls, data):
        """Rebuild a schedule from :meth:`to_list` output."""
        return cls([BillingPeriod.from_dict(entry) for entry in data])

    def __repr__(self):
        return "PeriodSchedule(%d periods, %s..%s)" % (
            len(self.periods),
            format_date(self.periods[0].start),
            format_date(self.periods[-1].end),
        )


def monthly_schedule(first_start, count, through_day=None):
    """Build ``count`` consecutive calendar-month periods.

    ``through_day`` sets a measurement cutoff, clamped to the month's length,
    so a cutoff of 25 on February gives the twenty-fifth and one of 31 gives
    the twenty-eighth or ninth.

    >>> schedule = monthly_schedule("2024-09-01", 2, through_day=25)
    >>> format_date(schedule.period(1).through)
    '2024-09-25'
    """
    start = month_start(parse_date(first_start, "first start"))
    periods = []
    for index in range(int(count)):
        period_start = add_months(start, index)
        period_end = month_end(period_start)
        through = period_end
        if through_day is not None:
            day = min(int(through_day), period_end.day)
            through = period_end.replace(day=day)
        periods.append(BillingPeriod(index + 1, period_start, period_end, through))
    return PeriodSchedule(periods)
