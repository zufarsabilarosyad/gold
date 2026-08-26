"""Interest on a late payment, under a statute or under the contract.

Prompt-payment statutes state a rate and a grace period, and then leave three
things to be argued about:

*The day count.*  A year is 365 days, or 360, or the actual days in the actual
year.  On a hundred-thousand-dollar payment thirty days late at twelve percent,
the difference between 360 and 365 is about fourteen dollars -- small, and
exactly the kind of small that appears on every application for two years.

*Compounding.*  Simple interest on the principal, or monthly compounding on the
running balance.  Statutes usually say simple; contracts sometimes do not.

*What it accrues on.*  Interest on the unpaid amount is uncontroversial.
Interest on retainage held past the release date is the fight, and it turns on
whether the retainage was *due* -- which is a question about the release
conditions, not about interest.
"""

from decimal import Decimal

from ..core.dates import days_between, parse_date
from ..core.money import Money, zero
from ..core.percent import Rate, rate_text
from ..core.trace import NULL_TRACE
from ..errors import DataError, InputError

__all__ = [
    "DAY_COUNTS",
    "COMPOUNDING",
    "InterestTerms",
    "accrue_interest",
    "day_count_fraction",
]

DAY_COUNTS = ("actual_365", "actual_360", "thirty_360")
COMPOUNDING = ("simple", "monthly")


def day_count_fraction(start, end, basis="actual_365"):
    """Return the year fraction between two dates under a day-count basis.

    >>> str(day_count_fraction("2024-11-01", "2024-12-01", "actual_365"))
    '0.08219178082191780821917808219'
    >>> str(day_count_fraction("2024-11-01", "2024-12-01", "thirty_360"))
    '0.08333333333333333333333333333'
    """
    basis = str(basis)
    if basis not in DAY_COUNTS:
        raise InputError("unknown day count %r; known: %s" % (basis, ", ".join(DAY_COUNTS)))
    start = parse_date(start, "start")
    end = parse_date(end, "end")
    if end < start:
        raise DataError("interest cannot run backwards")
    if basis == "thirty_360":
        days = (
            (end.year - start.year) * 360
            + (end.month - start.month) * 30
            + (min(end.day, 30) - min(start.day, 30))
        )
        return Decimal(days) / Decimal(360)
    days = Decimal(days_between(start, end))
    return days / (Decimal(365) if basis == "actual_365" else Decimal(360))


class InterestTerms:
    """A rate, a grace period and the three conventions around them.

    >>> terms = InterestTerms("12%", grace_days=7)
    >>> str(terms.rate)
    '12%'
    >>> terms.day_count
    'actual_365'
    """

    __slots__ = ("rate", "grace_days", "day_count", "compounding", "on_retainage", "statute")

    def __init__(
        self,
        rate,
        grace_days=0,
        day_count="actual_365",
        compounding="simple",
        on_retainage=False,
        statute="",
    ):
        self.rate = Rate.parse(rate)
        self.grace_days = int(grace_days)
        if str(day_count) not in DAY_COUNTS:
            raise InputError("unknown day count %r" % (day_count,))
        self.day_count = str(day_count)
        if str(compounding) not in COMPOUNDING:
            raise InputError("unknown compounding %r" % (compounding,))
        self.compounding = str(compounding)
        self.on_retainage = bool(on_retainage)
        self.statute = str(statute)

    def to_dict(self):
        """Return the terms as plain data."""
        return {
            "rate": rate_text(self.rate),
            "grace_days": self.grace_days,
            "day_count": self.day_count,
            "compounding": self.compounding,
            "on_retainage": self.on_retainage,
            "statute": self.statute,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild terms from :meth:`to_dict` output."""
        return cls(
            data.get("rate", "0"),
            data.get("grace_days", 0),
            data.get("day_count", "actual_365"),
            data.get("compounding", "simple"),
            data.get("on_retainage", False),
            data.get("statute", ""),
        )

    def __repr__(self):
        return "InterestTerms(%r, grace=%d)" % (str(self.rate), self.grace_days)


def accrue_interest(principal, due, paid_on, terms, trace=NULL_TRACE, subject=""):
    """Return the interest owed on a payment that landed late.

    >>> from ..core.money import money
    >>> terms = InterestTerms("12%")
    >>> str(accrue_interest(money("100000"), "2024-11-12", "2024-12-12", terms).rounded())
    '$986.30'
    >>> str(accrue_interest(money("100000"), "2024-11-12", "2024-11-12", terms))
    '$0.00'

    The grace period suppresses interest entirely rather than shortening it,
    which is what "no interest accrues if paid within seven days" means:

    >>> graced = InterestTerms("12%", grace_days=7)
    >>> str(accrue_interest(money("100000"), "2024-11-12", "2024-11-18", graced))
    '$0.00'
    >>> str(accrue_interest(money("100000"), "2024-11-12", "2024-11-25", graced).rounded())
    '$427.40'
    """
    if not isinstance(principal, Money):
        raise InputError("interest needs a Money principal")
    due = parse_date(due, "due date")
    paid_on = parse_date(paid_on, "payment date")
    if paid_on <= due:
        return zero(principal.currency)
    late_days = (paid_on - due).days
    if late_days <= terms.grace_days:
        trace.record("interest", subject, "within the %d-day grace period" % (terms.grace_days,))
        return zero(principal.currency)
    fraction = day_count_fraction(due, paid_on, terms.day_count)
    if terms.compounding == "simple":
        interest = principal * (terms.rate.value * fraction)
    else:
        months = Decimal(late_days) / Decimal(30)
        monthly = terms.rate.value / Decimal(12)
        factor = (Decimal(1) + monthly) ** int(months)
        interest = principal * (factor - Decimal(1))
    trace.record(
        "interest",
        subject,
        "%s over %d days at %s" % (interest.rounded(), late_days, terms.rate),
        {"basis": terms.day_count, "compounding": terms.compounding},
    )
    return interest
