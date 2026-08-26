"""One row of a continuation sheet.

The columns are the ones every construction payment form has carried since the
1960s, and their relationships are fixed:

===  ==========================================  ==================
A    scheduled value                             from the contract
D    work completed this period                  from progress
C    work completed from previous applications   from the last sheet
E    materials presently stored                  from the stored ledger
F    total completed and stored to date          C + D + E
G    percent complete                            F / A
H    balance to finish                           A - F
I    retainage                                   from the retainage rules
===  ==========================================  ==================

Two of those are worth a comment.  ``F`` is a sum, not an independent figure --
a sheet where F disagrees with C+D+E is the classic sign of a hand-edited
spreadsheet.  And ``G`` is computed from money, not from the percentage the
field reported: a line billed against a revised scheduled value shows a
different percentage from the one the superintendent wrote down, and the sheet
shows the money's version.
"""

from decimal import Decimal

from ..core.money import Money, money, zero
from ..core.percent import Rate
from ..errors import DataError, InputError

__all__ = ["ApplicationLine"]


class ApplicationLine:
    """A continuation-sheet row, with its columns kept consistent.

    >>> from ..core.money import money
    >>> row = ApplicationLine("03300", "Concrete", money("400000"),
    ...                       previous=money("100000"), this_period=money("60000"),
    ...                       stored=money("15000"), retainage=money("17500"))
    >>> str(row.completed_and_stored())
    '$175,000.00'
    >>> str(row.percent_complete())
    '43.75%'
    >>> str(row.balance_to_finish())
    '$225,000.00'
    """

    __slots__ = (
        "code",
        "description",
        "scheduled_value",
        "previous",
        "this_period",
        "stored",
        "previous_stored",
        "retainage",
        "previous_retainage",
        "rate",
        "kind",
        "group",
        "change_order",
        "note",
    )

    def __init__(
        self,
        code,
        description,
        scheduled_value,
        previous=None,
        this_period=None,
        stored=None,
        previous_stored=None,
        retainage=None,
        previous_retainage=None,
        rate=None,
        kind="lump_sum",
        group="",
        change_order="",
        note="",
    ):
        self.code = str(code)
        self.description = str(description)
        if not isinstance(scheduled_value, Money):
            raise InputError("line %s needs a Money scheduled value" % (self.code,))
        self.scheduled_value = scheduled_value
        currency = scheduled_value.currency
        self.previous = previous if previous is not None else zero(currency)
        self.this_period = this_period if this_period is not None else zero(currency)
        self.stored = stored if stored is not None else zero(currency)
        self.previous_stored = (
            previous_stored if previous_stored is not None else zero(currency)
        )
        self.retainage = retainage if retainage is not None else zero(currency)
        self.previous_retainage = (
            previous_retainage if previous_retainage is not None else zero(currency)
        )
        self.rate = Rate.parse(rate) if rate is not None else None
        self.kind = str(kind)
        self.group = str(group)
        self.change_order = str(change_order)
        self.note = str(note)

    def work_to_date(self):
        """Return work in place to date, stored material excluded."""
        return self.previous + self.this_period

    def completed_and_stored(self):
        """Return column F: everything billed to date on this line."""
        return self.work_to_date() + self.stored

    def percent_complete(self):
        """Return column G, computed from money rather than from a report."""
        if self.scheduled_value.is_zero():
            return Rate(Decimal(0))
        return Rate(self.completed_and_stored().ratio_to(self.scheduled_value))

    def balance_to_finish(self):
        """Return column H, which includes retainage still to be released."""
        return self.scheduled_value - self.completed_and_stored()

    def retainage_this_period(self):
        """Return the movement in retainage on this line this period."""
        return self.retainage - self.previous_retainage

    def net_this_period(self):
        """Return what this line adds to the current payment before deductions."""
        return self.this_period + self.stored_movement() - self.retainage_this_period()

    def stored_movement(self):
        """Return the change in stored materials this period.

        The sheet shows stored materials as a balance rather than a movement,
        which is why the previous balance is carried on the row: the payment
        this period follows the movement, not the balance.
        """
        return self.stored - self.previous_stored

    def is_overbilled(self):
        """Return True when this line is billed past its scheduled value."""
        return self.completed_and_stored() > self.scheduled_value

    def is_complete(self):
        """Return True when the line is fully billed."""
        return self.completed_and_stored() == self.scheduled_value

    def is_started(self):
        """Return True when anything has ever been billed on the line."""
        return not self.completed_and_stored().is_zero()

    def validate(self, allow_overbilling=False):
        """Return the problems with this row, empty when it is consistent.

        Billing past the scheduled value is a problem under most contracts and
        deliberate under a few -- a unit-price line whose measured quantity
        overran, for instance -- so whether it is reported is the caller's
        decision rather than this row's.
        """
        problems = []
        if self.this_period.is_negative() and self.previous.is_zero():
            problems.append("line %s bills a negative amount with no history" % (self.code,))
        if self.stored.is_negative():
            problems.append("line %s carries negative stored materials" % (self.code,))
        if self.retainage.is_negative() and not self.scheduled_value.is_negative():
            problems.append("line %s holds negative retainage" % (self.code,))
        if self.is_overbilled() and not allow_overbilling:
            problems.append(
                "line %s is billed %s against a scheduled value of %s"
                % (self.code, self.completed_and_stored(), self.scheduled_value)
            )
        return problems

    def to_dict(self):
        """Return the row as plain data."""
        return {
            "code": self.code,
            "description": self.description,
            "scheduled_value": str(self.scheduled_value.amount),
            "previous": str(self.previous.amount),
            "this_period": str(self.this_period.amount),
            "stored": str(self.stored.amount),
            "previous_stored": str(self.previous_stored.amount),
            "completed_and_stored": str(self.completed_and_stored().amount),
            "percent": str(self.percent_complete().value),
            "balance": str(self.balance_to_finish().amount),
            "retainage": str(self.retainage.amount),
            "previous_retainage": str(self.previous_retainage.amount),
            "rate": str(self.rate.value) if self.rate else None,
            "kind": self.kind,
            "group": self.group,
            "change_order": self.change_order,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild a row from :meth:`to_dict` output."""
        return cls(
            data["code"],
            data.get("description", ""),
            money(data["scheduled_value"], currency),
            money(data.get("previous", "0"), currency),
            money(data.get("this_period", "0"), currency),
            money(data.get("stored", "0"), currency),
            money(data.get("previous_stored", "0"), currency),
            money(data.get("retainage", "0"), currency),
            money(data.get("previous_retainage", "0"), currency),
            data.get("rate"),
            data.get("kind", "lump_sum"),
            data.get("group", ""),
            data.get("change_order", ""),
            data.get("note", ""),
        )

    def __eq__(self, other):
        return isinstance(other, ApplicationLine) and other.to_dict() == self.to_dict()

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("ApplicationLine", self.code, str(self.completed_and_stored().amount)))

    def __str__(self):
        return "%s %s %s of %s" % (
            self.code,
            self.description,
            self.completed_and_stored(),
            self.scheduled_value,
        )

    def __repr__(self):
        return "ApplicationLine(%r, %s)" % (self.code, self.completed_and_stored())
