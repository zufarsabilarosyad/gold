"""Unit-price lines, and what happens when the measured quantity overruns.

A unit-price line prices work per unit against an estimated quantity.  When the
field measures more than the estimate, three conventions are in common use and
they produce visibly different applications:

``rate``
    Everything installed bills at the contract unit rate.  The estimate was
    only ever an estimate.
``capped``
    Billing stops at the estimated quantity; the overrun waits for a change
    order.  The work is done and not billed, which is what a public-works
    contract usually says.
``threshold``
    Overrun bills at the rate up to a stated variance -- fifteen percent is
    common -- and is capped after that.

The overrun rule belongs to the line where a contract states it per item, and
to policy otherwise.  Note that the *underrun* case is not symmetric: nobody
pays for excavation that was not excavated, so an underrun simply bills less
and leaves the difference in the balance to finish.
"""

from decimal import Decimal

from ..core.money import Money, money, zero
from ..core.numbers import decimal_from
from ..core.percent import Rate, rate_text
from ..core.quantity import Quantity, quantity
from ..errors import DataError, InputError

__all__ = [
    "OVERRUN_RULES",
    "UnitPriceItem",
    "billable_quantity",
    "overrun_quantity",
    "UnitPriceMeasurement",
    "cumulative_measured",
]

OVERRUN_RULES = ("rate", "capped", "threshold")


def billable_quantity(measured, estimated, rule="rate", threshold=None):
    """Return the quantity that may be billed under an overrun rule.

    >>> str(billable_quantity(quantity("110", "cy"), quantity("100", "cy"), "capped"))
    '100.00 cy'
    >>> str(billable_quantity(quantity("110", "cy"), quantity("100", "cy"), "rate"))
    '110.00 cy'
    >>> str(billable_quantity(quantity("120", "cy"), quantity("100", "cy"),
    ...                       "threshold", Rate("0.15")))
    '115.00 cy'
    """
    measured = quantity(measured)
    estimated = quantity(estimated)
    if measured.unit != estimated.unit:
        raise DataError("cannot compare %s with %s" % (measured.unit, estimated.unit))
    rule = str(rule).strip().lower()
    if rule not in OVERRUN_RULES:
        raise InputError(
            "unknown overrun rule %r; known: %s" % (rule, ", ".join(OVERRUN_RULES))
        )
    if measured <= estimated or rule == "rate":
        return measured
    if rule == "capped":
        return estimated
    if threshold is None:
        raise InputError("the threshold rule needs a threshold rate")
    allowance = Rate.parse(threshold)
    ceiling = estimated.amount * (Decimal(1) + allowance.value)
    return Quantity(min(measured.amount, ceiling), measured.unit)


def overrun_quantity(measured, estimated):
    """Return how much the measurement exceeds the estimate, never below zero.

    >>> str(overrun_quantity(quantity("110", "cy"), quantity("100", "cy")))
    '10.00 cy'
    >>> str(overrun_quantity(quantity("90", "cy"), quantity("100", "cy")))
    '0.00 cy'
    """
    measured = quantity(measured)
    estimated = quantity(estimated)
    if measured <= estimated:
        return Quantity(Decimal(0), measured.unit)
    return measured - estimated


class UnitPriceItem:
    """A unit-price line's pricing rule, held apart from the schedule line.

    >>> item = UnitPriceItem("31200", quantity("2500", "cy"), money("20"),
    ...                      overrun_rule="threshold", overrun_threshold="15%")
    >>> str(item.scheduled_value())
    '$50,000.00'
    >>> str(item.value_of(quantity("3000", "cy")))
    '$57,500.00'
    >>> str(item.unbilled_overrun(quantity("3000", "cy")))
    '$2,500.00'
    """

    __slots__ = ("code", "estimated", "rate", "overrun_rule", "overrun_threshold", "notes")

    def __init__(self, code, estimated, rate, overrun_rule="rate", overrun_threshold=None, notes=""):
        self.code = str(code)
        self.estimated = quantity(estimated)
        if not isinstance(rate, Money):
            raise InputError("unit-price item %s needs a Money rate" % (self.code,))
        if rate.is_negative():
            raise DataError("unit-price item %s has a negative rate" % (self.code,))
        self.rate = rate
        rule = str(overrun_rule).strip().lower()
        if rule not in OVERRUN_RULES:
            raise InputError("unknown overrun rule %r" % (overrun_rule,))
        self.overrun_rule = rule
        self.overrun_threshold = (
            Rate.parse(overrun_threshold) if overrun_threshold is not None else None
        )
        if self.overrun_rule == "threshold" and self.overrun_threshold is None:
            raise InputError("unit-price item %s needs a threshold" % (self.code,))
        self.notes = str(notes)

    def scheduled_value(self):
        """Return the estimated quantity times the rate."""
        return self.rate * self.estimated.amount

    def billable(self, measured):
        """Return the billable quantity for a measurement."""
        return billable_quantity(
            measured, self.estimated, self.overrun_rule, self.overrun_threshold
        )

    def value_of(self, measured):
        """Return the billable value of a measurement."""
        return self.rate * self.billable(measured).amount

    def unbilled_overrun(self, measured):
        """Return the value of work measured but not billable under the rule."""
        measured = quantity(measured)
        difference = measured.amount - self.billable(measured).amount
        if difference <= 0:
            return zero(self.rate.currency)
        return self.rate * difference

    def percent_of_estimate(self, measured):
        """Return measured over estimated as a decimal fraction."""
        measured = quantity(measured)
        if self.estimated.amount == 0:
            raise DataError("unit-price item %s has a zero estimate" % (self.code,))
        return measured.amount / self.estimated.amount

    def to_dict(self):
        """Return the item as plain data."""
        return {
            "code": self.code,
            "estimated": str(self.estimated.amount),
            "unit": str(self.estimated.unit),
            "rate": str(self.rate.amount),
            "overrun_rule": self.overrun_rule,
            "overrun_threshold": (
                rate_text(self.overrun_threshold) if self.overrun_threshold else None
            ),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild an item from :meth:`to_dict` output."""
        return cls(
            data["code"],
            Quantity(data["estimated"], data.get("unit", "ea")),
            money(data["rate"], currency),
            data.get("overrun_rule", "rate"),
            data.get("overrun_threshold"),
            data.get("notes", ""),
        )

    def __repr__(self):
        return "UnitPriceItem(%r, %s)" % (self.code, self.estimated)


class UnitPriceMeasurement:
    """A field measurement for one unit-price line in one period.

    >>> measure = UnitPriceMeasurement("31200", 3, quantity("400", "cy"), "field book 12")
    >>> str(measure.installed)
    '400.00 cy'
    """

    __slots__ = ("code", "period", "installed", "reference", "measured_by")

    def __init__(self, code, period, installed, reference="", measured_by=""):
        self.code = str(code)
        self.period = int(period)
        self.installed = quantity(installed)
        if self.installed.amount < 0:
            raise DataError(
                "measurement for %s in period %d is negative" % (self.code, self.period)
            )
        self.reference = str(reference)
        self.measured_by = str(measured_by)

    def to_dict(self):
        """Return the measurement as plain data."""
        return {
            "code": self.code,
            "period": self.period,
            "installed": str(self.installed.amount),
            "unit": str(self.installed.unit),
            "reference": self.reference,
            "measured_by": self.measured_by,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild a measurement from :meth:`to_dict` output."""
        return cls(
            data["code"],
            data["period"],
            Quantity(data["installed"], data.get("unit", "ea")),
            data.get("reference", ""),
            data.get("measured_by", ""),
        )

    def __repr__(self):
        return "UnitPriceMeasurement(%r, period=%d)" % (self.code, self.period)


def cumulative_measured(measurements, code, through_period=None):
    """Return the total measured quantity for a line through a period.

    >>> entries = [UnitPriceMeasurement("31200", 1, quantity("100", "cy")),
    ...            UnitPriceMeasurement("31200", 2, quantity("150", "cy"))]
    >>> str(cumulative_measured(entries, "31200", 1))
    '100.00 cy'
    >>> str(cumulative_measured(entries, "31200"))
    '250.00 cy'
    """
    running = None
    for entry in measurements:
        if entry.code != str(code):
            continue
        if through_period is not None and entry.period > int(through_period):
            continue
        running = entry.installed if running is None else running + entry.installed
    if running is None:
        raise DataError("no measurements recorded for %r" % (code,))
    return running
