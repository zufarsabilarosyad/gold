"""Turning observations into earned value, one line kind at a time.

This is the first place where a convention becomes a number.  The observation
says "thirty-five percent"; what that is worth depends on the kind of line, on
whether percentages above a hundred are allowed to stand, on what happens when
a line goes backwards, and -- for unit-price work -- on the overrun rule.

The options are passed in rather than read from a global, so the same ledger
can be valued twice under two conventions and the difference priced.  That is
what ``strongback compare`` does, and it only works if nothing here reaches for
a default of its own.
"""

from decimal import Decimal

from ..core.money import Money, zero
from ..core.numbers import decimal_from, quantize
from ..core.percent import Rate, rate_text
from ..core.trace import NULL_TRACE
from ..errors import DataError, InputError
from ..model.unitprice import billable_quantity
from .observation import ProgressLedger

__all__ = [
    "ProgressOptions",
    "NEGATIVE_RULES",
    "OVER_HUNDRED_RULES",
    "MILESTONE_RULES",
    "earned_to_date",
    "percent_to_date",
    "earned_for_schedule",
    "total_earned",
    "completion_fraction",
]

NEGATIVE_RULES = ("allow", "clamp")
OVER_HUNDRED_RULES = ("allow", "clamp", "error")
MILESTONE_RULES = ("event_only", "line_percent")


class ProgressOptions:
    """The conventions that turn an observation into money.

    >>> options = ProgressOptions()
    >>> options.over_hundred
    'clamp'
    >>> ProgressOptions(over_hundred="allow").over_hundred
    'allow'
    """

    __slots__ = (
        "over_hundred",
        "negative",
        "milestone_rule",
        "overrun_rule",
        "overrun_threshold",
        "percent_places",
        "value_places",
    )

    def __init__(
        self,
        over_hundred="clamp",
        negative="clamp",
        milestone_rule="event_only",
        overrun_rule="rate",
        overrun_threshold=None,
        percent_places=4,
        value_places=2,
    ):
        if str(over_hundred) not in OVER_HUNDRED_RULES:
            raise InputError("unknown over-hundred rule %r" % (over_hundred,))
        self.over_hundred = str(over_hundred)
        if str(negative) not in NEGATIVE_RULES:
            raise InputError("unknown negative-progress rule %r" % (negative,))
        self.negative = str(negative)
        if str(milestone_rule) not in MILESTONE_RULES:
            raise InputError("unknown milestone rule %r" % (milestone_rule,))
        self.milestone_rule = str(milestone_rule)
        self.overrun_rule = str(overrun_rule)
        self.overrun_threshold = (
            Rate.parse(overrun_threshold) if overrun_threshold is not None else None
        )
        self.percent_places = int(percent_places)
        self.value_places = int(value_places)

    def to_dict(self):
        """Return the options as plain data."""
        return {
            "over_hundred": self.over_hundred,
            "negative": self.negative,
            "milestone_rule": self.milestone_rule,
            "overrun_rule": self.overrun_rule,
            "overrun_threshold": (
                rate_text(self.overrun_threshold) if self.overrun_threshold else None
            ),
            "percent_places": self.percent_places,
            "value_places": self.value_places,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild options from :meth:`to_dict` output."""
        return cls(
            data.get("over_hundred", "clamp"),
            data.get("negative", "clamp"),
            data.get("milestone_rule", "event_only"),
            data.get("overrun_rule", "rate"),
            data.get("overrun_threshold"),
            data.get("percent_places", 4),
            data.get("value_places", 2),
        )

    def __repr__(self):
        return "ProgressOptions(over_hundred=%r, overrun_rule=%r)" % (
            self.over_hundred,
            self.overrun_rule,
        )


def _apply_bounds(fraction, code, options):
    """Clamp or reject a completion fraction under the option rules."""
    if fraction < 0:
        if options.negative == "clamp":
            return Decimal(0)
        return fraction
    if fraction > 1:
        if options.over_hundred == "clamp":
            return Decimal(1)
        if options.over_hundred == "error":
            raise DataError(
                "line %s reports %s%% complete, which the contract does not allow"
                % (code, quantize(fraction * 100, 2))
            )
    return fraction


def percent_to_date(line, ledger, period, options=None, trace=NULL_TRACE):
    """Return a line's completion fraction through a period.

    >>> from ..model.sov import SOVLine
    >>> from ..core.money import money
    >>> from .observation import ProgressEntry
    >>> ledger = ProgressLedger()
    >>> ledger.record(ProgressEntry("03300", 1, percent="120%"))
    >>> line = SOVLine("03300", "Concrete", money("100000"))
    >>> str(percent_to_date(line, ledger, 1))
    '100%'
    >>> str(percent_to_date(line, ledger, 1, ProgressOptions(over_hundred="allow")))
    '120%'
    """
    options = options or ProgressOptions()
    if line.kind == "unit_price":
        try:
            measured = ledger.cumulative_quantity(line.code, period)
        except DataError:
            return Rate(Decimal(0))
        billable = billable_quantity(
            measured, line.unit_quantity, options.overrun_rule, options.overrun_threshold
        )
        if line.unit_quantity.amount == 0:
            raise DataError("unit-price line %s has a zero estimate" % (line.code,))
        fraction = billable.amount / line.unit_quantity.amount
    elif line.kind == "milestone":
        achieved = ledger.milestone_achieved(line.code, period)
        if achieved:
            fraction = Decimal(1)
        elif options.milestone_rule == "line_percent":
            fraction = ledger.latest_percent(line.code, period).value
        else:
            fraction = Decimal(0)
    else:
        entries = ledger.for_line(line.code, period)
        shapes = {entry.shape for entry in entries}
        if "value" in shapes and "percent" not in shapes:
            if line.scheduled_value.is_zero():
                raise DataError("line %s has a zero scheduled value" % (line.code,))
            fraction = ledger.cumulative_value(line.code, period).ratio_to(line.scheduled_value)
        else:
            fraction = ledger.latest_percent(line.code, period).value
    fraction = _apply_bounds(fraction, line.code, options)
    trace.record(
        "progress",
        line.code,
        "%s complete through period %d" % (Rate(fraction), int(period)),
        {"kind": str(line.kind)},
    )
    return Rate(fraction)


def earned_to_date(line, ledger, period, options=None, trace=NULL_TRACE):
    """Return the value of the work in place on a line through a period.

    >>> from ..model.sov import SOVLine
    >>> from ..core.money import money
    >>> from .observation import ProgressEntry
    >>> ledger = ProgressLedger()
    >>> ledger.record(ProgressEntry("03300", 1, percent="25%"))
    >>> line = SOVLine("03300", "Concrete", money("400000"))
    >>> str(earned_to_date(line, ledger, 1))
    '$100,000.00'
    """
    options = options or ProgressOptions()
    if line.kind == "unit_price":
        try:
            measured = ledger.cumulative_quantity(line.code, period)
        except DataError:
            return zero(line.scheduled_value.currency)
        billable = billable_quantity(
            measured, line.unit_quantity, options.overrun_rule, options.overrun_threshold
        )
        earned = line.unit_rate * billable.amount
        trace.record(
            "progress",
            line.code,
            "measured %s billable %s at %s" % (measured, billable, line.unit_rate),
        )
        return earned
    entries = ledger.for_line(line.code, period)
    shapes = {entry.shape for entry in entries}
    if "value" in shapes and "percent" not in shapes and line.kind != "milestone":
        earned = ledger.cumulative_value(line.code, period)
        if not line.scheduled_value.is_zero():
            fraction = _apply_bounds(
                earned.ratio_to(line.scheduled_value), line.code, options
            )
            earned = line.scheduled_value * fraction
        trace.record("progress", line.code, "valued directly at %s" % (earned,))
        return earned
    fraction = percent_to_date(line, ledger, period, options, trace).value
    return line.scheduled_value * fraction


def earned_for_schedule(schedule, ledger, period, options=None, trace=NULL_TRACE):
    """Return a mapping of line code to earned value through a period.

    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> from ..core.money import money
    >>> from .observation import ProgressEntry
    >>> sov = ScheduleOfValues([SOVLine("01000", "General", money("100000")),
    ...                         SOVLine("03300", "Concrete", money("400000"))])
    >>> ledger = ProgressLedger()
    >>> ledger.record(ProgressEntry("01000", 1, percent="50%"))
    >>> ledger.record(ProgressEntry("03300", 1, percent="25%"))
    >>> earned = earned_for_schedule(sov, ledger, 1)
    >>> str(earned["01000"]), str(earned["03300"])
    ('$50,000.00', '$100,000.00')
    """
    options = options or ProgressOptions()
    earned = {}
    for line in schedule.ordered():
        earned[line.code] = earned_to_date(line, ledger, period, options, trace)
    return earned


def total_earned(schedule, ledger, period, options=None, trace=NULL_TRACE):
    """Return the total earned value across a schedule through a period.

    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> from ..core.money import money
    >>> from .observation import ProgressEntry
    >>> sov = ScheduleOfValues([SOVLine("01000", "General", money("100000"))])
    >>> ledger = ProgressLedger()
    >>> ledger.record(ProgressEntry("01000", 1, percent="50%"))
    >>> str(total_earned(sov, ledger, 1))
    '$50,000.00'
    """
    values = earned_for_schedule(schedule, ledger, period, options, trace)
    running = zero(schedule.currency)
    for line in schedule.ordered():
        running = running + values[line.code]
    return running


def completion_fraction(schedule, ledger, period, options=None, trace=NULL_TRACE):
    """Return earned value over scheduled value for a whole schedule.

    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> from ..core.money import money
    >>> from .observation import ProgressEntry
    >>> sov = ScheduleOfValues([SOVLine("01000", "General", money("100000"))])
    >>> ledger = ProgressLedger()
    >>> ledger.record(ProgressEntry("01000", 1, percent="40%"))
    >>> str(completion_fraction(sov, ledger, 1))
    '40%'
    """
    total = schedule.total()
    if total.is_zero():
        raise DataError("cannot take a completion fraction of an empty schedule")
    earned = total_earned(schedule, ledger, period, options, trace)
    return Rate(earned.ratio_to(total))
