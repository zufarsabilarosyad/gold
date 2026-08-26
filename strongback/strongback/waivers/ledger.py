"""The waiver log: what has been released, through when, and for how much.

The log answers one question in two directions.  Forward: is this payment
covered by the waivers on file?  Backward: what is the payer's exposure -- work
that has been paid for and not released, either because no waiver was signed or
because a conditional one is still waiting on a cheque to clear.

The second question is the one an owner's lender asks before funding a draw,
and it cannot be answered by counting documents.  A conditional waiver against
an unpaid application is a document on file that releases nothing.
"""

from ..core.dates import format_date, parse_date
from ..core.ids import normalise_id
from ..core.money import zero
from ..core.table import Column, Table
from ..errors import DataError, InputError
from .document import LienWaiver, WaiverType

__all__ = ["WaiverLedger", "coverage_gap"]


class WaiverLedger:
    """Every waiver on a contract, indexed by application and by date.

    >>> from ..core.money import money
    >>> from .document import LienWaiver
    >>> ledger = WaiverLedger()
    >>> ledger.add(LienWaiver("W-1", "conditional_progress", money("40000"),
    ...                       "2024-09-30", "2024-10-02", "PA-001"))
    >>> ledger.add(LienWaiver("W-2", "unconditional_progress", money("40000"),
    ...                       "2024-09-30", "2024-11-04", "PA-001"))
    >>> [waiver.id for waiver in ledger.for_application("PA-001")]
    ['W-1', 'W-2']
    >>> str(ledger.released_through("2024-09-30", paid_applications=["PA-001"]))
    '$80,000.00'
    >>> ledger.has_unconditional("PA-001")
    True
    """

    def __init__(self, waivers=(), currency="USD"):
        self.currency = currency
        self.waivers = {}
        for waiver in waivers:
            self.add(waiver)

    def add(self, waiver):
        """Add a waiver, refusing a duplicate identifier."""
        if not isinstance(waiver, LienWaiver):
            raise InputError("expected a LienWaiver")
        if waiver.id in self.waivers:
            raise DataError("waiver %s appears twice" % (waiver.id,))
        self.waivers[waiver.id] = waiver

    def get(self, identifier, default=None):
        """Return a waiver, or ``default``."""
        return self.waivers.get(normalise_id(identifier, "waiver id"), default)

    def ordered(self):
        """Return the waivers in through-date then identifier order."""
        return sorted(self.waivers.values(), key=lambda item: (item.through, item.id))

    def for_application(self, application_id):
        """Return the waivers naming an application."""
        return [
            waiver for waiver in self.ordered() if waiver.application_id == str(application_id)
        ]

    def of_type(self, waiver_type):
        """Return the waivers of one type."""
        waiver_type = waiver_type if isinstance(waiver_type, WaiverType) else WaiverType(waiver_type)
        return [waiver for waiver in self.ordered() if waiver.type == waiver_type]

    def has_unconditional(self, application_id):
        """Return True when an unconditional waiver is on file for a payment."""
        return any(
            not waiver.type.is_conditional() for waiver in self.for_application(application_id)
        )

    def latest_through(self, effective_only=False, paid_applications=()):
        """Return the furthest date any effective waiver reaches."""
        paid = {str(item) for item in paid_applications}
        best = None
        for waiver in self.ordered():
            if effective_only and not waiver.is_effective(waiver.application_id in paid):
                continue
            if best is None or waiver.through > best:
                best = waiver.through
        return best

    def released_through(self, day, paid_applications=()):
        """Return the value released by effective waivers reaching a date."""
        day = parse_date(day)
        paid = {str(item) for item in paid_applications}
        running = zero(self.currency)
        for waiver in self.ordered():
            if waiver.through > day:
                continue
            if not waiver.is_effective(waiver.application_id in paid):
                continue
            running = running + waiver.amount
        return running

    def pending_conditional(self, paid_applications=()):
        """Return the conditional waivers still waiting on a payment."""
        paid = {str(item) for item in paid_applications}
        return [
            waiver
            for waiver in self.ordered()
            if waiver.type.is_conditional() and waiver.application_id not in paid
        ]

    def as_table(self):
        """Render the log as a table."""
        table = Table(
            [
                Column("id", "Waiver"),
                Column("type", "Type"),
                Column("application", "Application"),
                Column("through", "Through"),
                Column("amount", "Amount", "right"),
                Column("signed", "Signed"),
            ]
        )
        for waiver in self.ordered():
            table.add(
                {
                    "id": waiver.id,
                    "type": str(waiver.type),
                    "application": waiver.application_id or "-",
                    "through": format_date(waiver.through),
                    "amount": waiver.amount.format(),
                    "signed": format_date(waiver.signed_on) if waiver.signed_on else "-",
                }
            )
        return table.render()

    def to_list(self):
        """Return the log as plain data."""
        return [waiver.to_dict() for waiver in self.ordered()]

    @classmethod
    def from_list(cls, data, currency="USD"):
        """Rebuild a log from :meth:`to_list` output."""
        return cls([LienWaiver.from_dict(entry, currency) for entry in data], currency)

    def __len__(self):
        return len(self.waivers)

    def __iter__(self):
        return iter(self.ordered())

    def __repr__(self):
        return "WaiverLedger(%d waivers)" % (len(self.waivers),)


def coverage_gap(ledger, paid_amount, paid_applications=(), as_of=None):
    """Return the value paid for and not released by an effective waiver.

    >>> from ..core.money import money
    >>> from .document import LienWaiver
    >>> ledger = WaiverLedger()
    >>> ledger.add(LienWaiver("W-1", "conditional_progress", money("40000"),
    ...                       "2024-09-30", "2024-10-02", "PA-001"))
    >>> str(coverage_gap(ledger, money("40000"), paid_applications=[]))
    '$40,000.00'
    >>> str(coverage_gap(ledger, money("40000"), paid_applications=["PA-001"]))
    '$0.00'
    """
    released = zero(paid_amount.currency)
    paid = {str(item) for item in paid_applications}
    for waiver in ledger.ordered():
        if as_of is not None and waiver.through > parse_date(as_of):
            continue
        if not waiver.is_effective(waiver.application_id in paid):
            continue
        released = released + waiver.amount
    gap = paid_amount - released
    if gap.is_negative():
        return zero(paid_amount.currency)
    return gap
