"""Pay-when-paid and pay-if-paid: the clause that moves a due date, and the
clause that removes an obligation.

These two are one word apart in a contract and worlds apart in effect.

*Pay-when-paid* is a timing clause.  The subcontractor is owed the money; the
general contractor may wait until the owner pays before handing it over, but
after a reasonable time the obligation matures anyway.  Modelled here as a due
date that is the later of the ordinary due date and a number of days after the
upstream receipt, with a long-stop that fires regardless.

*Pay-if-paid* is a condition precedent.  If the owner never pays, the
subcontractor is never owed.  Modelled as an obligation that can be
extinguished -- which is why it is a separate state rather than a very long
delay.

Many jurisdictions will not enforce the second, and this package does not know
which; that is what ``enforceable`` is for.
"""

from ..core.dates import add_days, format_date, max_date, parse_date
from ..core.money import zero
from ..core.workcalendar import WorkCalendar, calendar_named
from ..errors import DataError, InputError

__all__ = ["ChainOutcome", "chain_due_date", "chain_status", "STATUSES"]

STATUSES = ("due", "waiting_upstream", "extinguished")


class ChainOutcome:
    """What a pay-chain clause does to one downstream payment.

    >>> outcome = ChainOutcome("waiting_upstream", "2024-12-20", "owner has not paid")
    >>> outcome.status
    'waiting_upstream'
    >>> outcome.is_payable()
    False
    """

    __slots__ = ("status", "due", "reason")

    def __init__(self, status, due=None, reason=""):
        if str(status) not in STATUSES:
            raise InputError("unknown chain status %r; known: %s" % (status, ", ".join(STATUSES)))
        self.status = str(status)
        self.due = parse_date(due) if due else None
        self.reason = str(reason)

    def is_payable(self):
        """Return True when the downstream payment is actually owed now."""
        return self.status == "due"

    def to_dict(self):
        """Return the outcome as plain data."""
        return {
            "status": self.status,
            "due": format_date(self.due) if self.due else None,
            "reason": self.reason,
        }

    def __repr__(self):
        return "ChainOutcome(%r, %r)" % (self.status, format_date(self.due) if self.due else None)


def chain_due_date(ordinary_due, upstream_paid_on, terms, calendar=None):
    """Return the due date once a pay-when-paid clause is applied.

    >>> from ..model.terms import PaymentTerms
    >>> terms = PaymentTerms(net_days=30, chain_rule="pay_when_paid", chain_days=7)
    >>> format_date(chain_due_date("2024-12-05", "2024-12-10", terms))
    '2024-12-17'
    >>> format_date(chain_due_date("2024-12-05", "2024-11-01", terms))
    '2024-12-05'
    """
    ordinary_due = parse_date(ordinary_due, "ordinary due date")
    if not terms.is_conditioned_on_upstream():
        return ordinary_due
    if upstream_paid_on is None:
        raise DataError("a pay-chain due date needs the upstream payment date")
    work = calendar if isinstance(calendar, WorkCalendar) else calendar_named(calendar or "us-federal")
    if terms.day_basis == "business":
        conditioned = work.add_business_days(upstream_paid_on, terms.chain_days)
    else:
        conditioned = add_days(upstream_paid_on, terms.chain_days)
    return max_date(ordinary_due, conditioned)


def chain_status(ordinary_due, upstream_paid_on, terms, as_of, longstop_days=90, enforceable=True, calendar=None):
    """Return what a pay-chain clause does to a payment as of a date.

    A pay-when-paid clause defers:

    >>> from ..model.terms import PaymentTerms
    >>> when = PaymentTerms(net_days=30, chain_rule="pay_when_paid", chain_days=7)
    >>> chain_status("2024-12-05", None, when, "2024-12-10").status
    'waiting_upstream'

    ...but not past the long-stop, after which the obligation matures whether
    or not the owner has paid:

    >>> chain_status("2024-09-05", None, when, "2024-12-20", longstop_days=90).status
    'due'

    A pay-if-paid clause extinguishes instead -- unless the jurisdiction
    refuses to enforce it, in which case it behaves like pay-when-paid:

    >>> ifpaid = PaymentTerms(net_days=30, chain_rule="pay_if_paid")
    >>> chain_status("2024-12-05", None, ifpaid, "2025-06-01").status
    'extinguished'
    >>> chain_status("2024-12-05", None, ifpaid, "2025-06-01", enforceable=False).status
    'due'
    """
    ordinary_due = parse_date(ordinary_due, "ordinary due date")
    as_of = parse_date(as_of, "as of")
    if not terms.is_conditioned_on_upstream():
        return ChainOutcome("due", ordinary_due, "no pay-chain clause")
    if upstream_paid_on is not None:
        due = chain_due_date(ordinary_due, upstream_paid_on, terms, calendar)
        return ChainOutcome("due", due, "upstream paid")
    longstop = add_days(ordinary_due, int(longstop_days))
    if as_of >= longstop:
        if terms.shifts_risk_upstream() and enforceable:
            return ChainOutcome("extinguished", None, "pay-if-paid: upstream never paid")
        return ChainOutcome("due", longstop, "long-stop reached without upstream payment")
    if terms.shifts_risk_upstream() and not enforceable:
        return ChainOutcome("due", ordinary_due, "pay-if-paid unenforceable here")
    return ChainOutcome("waiting_upstream", None, "upstream has not paid")
