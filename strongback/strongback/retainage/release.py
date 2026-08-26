"""Releasing retainage: at substantial completion, at closeout, and early.

Holding retainage is arithmetic; releasing it is a sequence of conditional
events, and the conditions are what contracts differ on.

At substantial completion the usual clause releases most of what is held and
keeps a punchlist holdback -- commonly one and a half or two times the value of
the remaining work.  Two things about that are easy to get wrong.  The holdback
is a multiple of the *punchlist* value, not of the retainage, so on a small
punchlist it can be far less than what is held and on a bad one far more.  And
a holdback larger than the retainage held cannot release anything, but neither
does it entitle the payer to hold *more*; the release is simply zero.

Early release -- paying out a finished trade's retainage before the job is
complete -- is separate, discretionary, and applied per line.  It is the
mechanism behind "we'll release the excavator, they finished in October".
"""

from decimal import Decimal

from ..core.dates import format_date, parse_date
from ..core.money import Money, money, zero
from ..core.percent import Rate
from ..core.trace import NULL_TRACE
from ..errors import DataError, InputError

__all__ = [
    "ReleaseEvent",
    "substantial_completion_release",
    "punchlist_holdback",
    "final_release",
    "early_release",
    "RELEASE_KINDS",
]

RELEASE_KINDS = ("substantial", "final", "early", "stepdown", "adjustment")


class ReleaseEvent:
    """A decision to hand back some of what is held.

    >>> from ..core.money import money
    >>> event = ReleaseEvent("substantial", money("40000"), 8, "2025-03-14")
    >>> str(event.amount)
    '$40,000.00'
    >>> event.kind
    'substantial'
    """

    __slots__ = ("kind", "amount", "period", "on", "code", "reason", "approved_by")

    def __init__(self, kind, amount, period, on=None, code="", reason="", approved_by=""):
        if str(kind) not in RELEASE_KINDS:
            raise InputError(
                "unknown release kind %r; known: %s" % (kind, ", ".join(RELEASE_KINDS))
            )
        self.kind = str(kind)
        if not isinstance(amount, Money):
            raise InputError("a release needs a Money amount")
        if amount.is_negative():
            raise DataError("a release cannot be negative: %s" % (amount,))
        self.amount = amount
        self.period = int(period)
        self.on = parse_date(on) if on else None
        self.code = str(code)
        self.reason = str(reason)
        self.approved_by = str(approved_by)

    def is_line_level(self):
        """Return True when the release applies to one schedule line."""
        return bool(self.code)

    def to_dict(self):
        """Return the event as plain data."""
        return {
            "kind": self.kind,
            "amount": str(self.amount.amount),
            "period": self.period,
            "on": format_date(self.on) if self.on else None,
            "code": self.code,
            "reason": self.reason,
            "approved_by": self.approved_by,
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild an event from :meth:`to_dict` output."""
        return cls(
            data["kind"],
            money(data["amount"], currency),
            data["period"],
            data.get("on"),
            data.get("code", ""),
            data.get("reason", ""),
            data.get("approved_by", ""),
        )

    def __repr__(self):
        return "ReleaseEvent(%r, %s, period=%d)" % (self.kind, self.amount, self.period)


def punchlist_holdback(punchlist_value, terms):
    """Return the amount kept back against the remaining punchlist.

    >>> from ..core.money import money
    >>> from .terms import RetainageTerms
    >>> terms = RetainageTerms("10%", punchlist_multiple="1.5")
    >>> str(punchlist_holdback(money("30000"), terms))
    '$45,000.00'
    >>> str(punchlist_holdback(money("30000"), RetainageTerms("10%")))
    '$0.00'
    """
    if not isinstance(punchlist_value, Money):
        raise InputError("a punchlist value must be Money")
    if terms.punchlist_multiple is None:
        return zero(punchlist_value.currency)
    multiple = terms.punchlist_multiple
    if isinstance(multiple, Rate):
        multiple = multiple.value
    return punchlist_value * Decimal(str(multiple))


def substantial_completion_release(held, terms, punchlist_value=None, trace=NULL_TRACE):
    """Return the release due at substantial completion, and what stays held.

    The clause may state a share to release, a punchlist multiple to hold, or
    both -- in which case the larger holdback governs, because a contract that
    says "release ninety percent but hold twice the punchlist" means both.

    >>> from ..core.money import money
    >>> from .terms import RetainageTerms
    >>> terms = RetainageTerms("10%", release_at_substantial="90%")
    >>> released, remaining = substantial_completion_release(money("100000"), terms)
    >>> str(released), str(remaining)
    ('$90,000.00', '$10,000.00')

    >>> both = RetainageTerms("10%", release_at_substantial="90%",
    ...                       punchlist_multiple="2")
    >>> released, remaining = substantial_completion_release(money("100000"), both,
    ...                                                      money("20000"))
    >>> str(released), str(remaining)
    ('$60,000.00', '$40,000.00')

    A punchlist worth more than the retainage held releases nothing, and never
    creates an obligation to hold more:

    >>> released, remaining = substantial_completion_release(money("30000"), both,
    ...                                                      money("40000"))
    >>> str(released), str(remaining)
    ('$0.00', '$30,000.00')
    """
    if not isinstance(held, Money):
        raise InputError("held retainage must be Money")
    if held.is_negative():
        raise DataError("cannot release from a negative retainage balance")
    currency = held.currency
    keep_by_share = zero(currency)
    if terms.release_at_substantial is not None:
        keep_by_share = held * terms.release_at_substantial.complement().value
    keep_by_punchlist = zero(currency)
    if punchlist_value is not None:
        keep_by_punchlist = punchlist_holdback(punchlist_value, terms)
    if terms.release_at_substantial is None and punchlist_value is None:
        return zero(currency), held
    keep = keep_by_share if keep_by_share > keep_by_punchlist else keep_by_punchlist
    if keep > held:
        keep = held
    released = held - keep
    trace.record(
        "retainage-release",
        "contract",
        "substantial completion: release %s, hold %s" % (released, keep),
        {"held": str(held.amount)},
    )
    return released, keep


def final_release(held, deductions=None, trace=NULL_TRACE):
    """Return what is released at final completion after any deductions.

    >>> from ..core.money import money
    >>> str(final_release(money("40000"))[0])
    '$40,000.00'
    >>> released, withheld = final_release(money("40000"), money("6500"))
    >>> str(released), str(withheld)
    ('$33,500.00', '$6,500.00')
    >>> released, withheld = final_release(money("4000"), money("6500"))
    >>> str(released), str(withheld)
    ('$0.00', '$4,000.00')
    """
    if not isinstance(held, Money):
        raise InputError("held retainage must be Money")
    currency = held.currency
    deductions = deductions if deductions is not None else zero(currency)
    if deductions.is_negative():
        raise DataError("a final deduction cannot be negative")
    if deductions > held:
        trace.record(
            "retainage-release",
            "contract",
            "final deductions exceed the balance held",
            {"held": str(held.amount), "deductions": str(deductions.amount)},
        )
        return zero(currency), held
    released = held - deductions
    trace.record(
        "retainage-release",
        "contract",
        "final release of %s after %s in deductions" % (released, deductions),
    )
    return released, deductions


def early_release(line_balances, codes, trace=NULL_TRACE):
    """Return the total released by closing out named lines early.

    >>> from ..core.money import money
    >>> balances = {"31200": money("5000"), "03300": money("12000")}
    >>> str(early_release(balances, ["31200"]))
    '$5,000.00'
    >>> str(early_release(balances, ["31200", "09900"]))
    '$5,000.00'
    """
    running = None
    for code in codes:
        balance = line_balances.get(str(code))
        if balance is None:
            continue
        running = balance if running is None else running + balance
        trace.record("retainage-release", str(code), "early release of %s" % (balance,))
    if running is None:
        first = next(iter(line_balances.values()), None)
        return zero(first.currency if first is not None else "USD")
    return running
