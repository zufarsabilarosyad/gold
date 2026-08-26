"""Payment terms, completion dates and liquidated damages.

The word "days" in a payment clause is ambiguous three ways at once -- how many
days, counted on which calendar, from which event -- and the three combine.
"Net thirty from receipt of a properly submitted application" and "thirty days
after certification" differ by however long the architect took, which is the
whole argument in most late-payment disputes.

:class:`PaymentTerms` records all three choices, and the payments package does
the arithmetic against a :class:`~strongback.core.workcalendar.WorkCalendar`.
"""

from ..core.dates import format_date, parse_date
from ..core.money import Money, money, zero
from ..core.percent import Rate, rate_text
from ..errors import DataError, InputError

__all__ = [
    "PaymentTerms",
    "CompletionDates",
    "LiquidatedDamages",
    "START_EVENTS",
    "DAY_BASES",
    "PAY_CHAIN_RULES",
]

START_EVENTS = ("application_date", "receipt_date", "certification_date", "period_end")
DAY_BASES = ("calendar", "business")
PAY_CHAIN_RULES = ("independent", "pay_when_paid", "pay_if_paid")


class PaymentTerms:
    """When a certified application becomes due, and what conditions it.

    >>> terms = PaymentTerms(net_days=30)
    >>> terms.describe()
    'net 30 calendar days from certification_date'
    >>> PaymentTerms(net_days=7, day_basis="business", start_event="receipt_date").day_basis
    'business'
    """

    __slots__ = (
        "net_days",
        "day_basis",
        "start_event",
        "certification_days",
        "chain_rule",
        "chain_days",
        "discount_rate",
        "discount_days",
        "note",
    )

    def __init__(
        self,
        net_days=30,
        day_basis="calendar",
        start_event="certification_date",
        certification_days=7,
        chain_rule="independent",
        chain_days=0,
        discount_rate=None,
        discount_days=0,
        note="",
    ):
        self.net_days = int(net_days)
        if self.net_days < 0:
            raise InputError("net days cannot be negative: %r" % (net_days,))
        if str(day_basis) not in DAY_BASES:
            raise InputError("unknown day basis %r; known: %s" % (day_basis, ", ".join(DAY_BASES)))
        self.day_basis = str(day_basis)
        if str(start_event) not in START_EVENTS:
            raise InputError(
                "unknown start event %r; known: %s" % (start_event, ", ".join(START_EVENTS))
            )
        self.start_event = str(start_event)
        self.certification_days = int(certification_days)
        if str(chain_rule) not in PAY_CHAIN_RULES:
            raise InputError("unknown chain rule %r" % (chain_rule,))
        self.chain_rule = str(chain_rule)
        self.chain_days = int(chain_days)
        self.discount_rate = Rate.parse(discount_rate) if discount_rate is not None else None
        self.discount_days = int(discount_days)
        if self.discount_rate is not None and self.discount_days <= 0:
            raise InputError("a prompt-payment discount needs a discount window")
        self.note = str(note)

    def is_conditioned_on_upstream(self):
        """Return True when payment waits on the payer being paid."""
        return self.chain_rule in ("pay_when_paid", "pay_if_paid")

    def shifts_risk_upstream(self):
        """Return True when non-payment upstream extinguishes the obligation."""
        return self.chain_rule == "pay_if_paid"

    def describe(self):
        """Return a one-line summary of the terms."""
        text = "net %d %s days from %s" % (self.net_days, self.day_basis, self.start_event)
        if self.chain_rule != "independent":
            text += " (%s)" % (self.chain_rule.replace("_", "-"),)
        if self.discount_rate is not None:
            text += ", %s within %d days" % (self.discount_rate, self.discount_days)
        return text

    def to_dict(self):
        """Return the terms as plain data."""
        return {
            "net_days": self.net_days,
            "day_basis": self.day_basis,
            "start_event": self.start_event,
            "certification_days": self.certification_days,
            "chain_rule": self.chain_rule,
            "chain_days": self.chain_days,
            "discount_rate": rate_text(self.discount_rate) if self.discount_rate else None,
            "discount_days": self.discount_days,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild terms from :meth:`to_dict` output."""
        return cls(
            data.get("net_days", 30),
            data.get("day_basis", "calendar"),
            data.get("start_event", "certification_date"),
            data.get("certification_days", 7),
            data.get("chain_rule", "independent"),
            data.get("chain_days", 0),
            data.get("discount_rate"),
            data.get("discount_days", 0),
            data.get("note", ""),
        )

    def __eq__(self, other):
        return isinstance(other, PaymentTerms) and other.to_dict() == self.to_dict()

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("PaymentTerms", self.net_days, self.day_basis, self.start_event))

    def __str__(self):
        return self.describe()

    def __repr__(self):
        return "PaymentTerms(net_days=%d, %r)" % (self.net_days, self.day_basis)


class CompletionDates:
    """The dates a schedule is measured against.

    >>> dates = CompletionDates(notice_to_proceed="2024-09-16",
    ...                         contract_completion="2025-06-30")
    >>> dates.contract_days()
    287
    >>> dates.is_substantially_complete("2024-12-01")
    False
    """

    __slots__ = (
        "notice_to_proceed",
        "contract_completion",
        "substantial_completion",
        "final_completion",
        "punchlist_complete",
        "closeout_submitted",
    )

    def __init__(
        self,
        notice_to_proceed=None,
        contract_completion=None,
        substantial_completion=None,
        final_completion=None,
        punchlist_complete=None,
        closeout_submitted=None,
    ):
        self.notice_to_proceed = parse_date(notice_to_proceed) if notice_to_proceed else None
        self.contract_completion = parse_date(contract_completion) if contract_completion else None
        self.substantial_completion = (
            parse_date(substantial_completion) if substantial_completion else None
        )
        self.final_completion = parse_date(final_completion) if final_completion else None
        self.punchlist_complete = parse_date(punchlist_complete) if punchlist_complete else None
        self.closeout_submitted = parse_date(closeout_submitted) if closeout_submitted else None
        if (
            self.substantial_completion
            and self.final_completion
            and self.final_completion < self.substantial_completion
        ):
            raise DataError("final completion cannot precede substantial completion")

    def contract_days(self):
        """Return the contract duration in calendar days, or ``None``."""
        if not (self.notice_to_proceed and self.contract_completion):
            return None
        return (self.contract_completion - self.notice_to_proceed).days

    def is_substantially_complete(self, as_of):
        """Return True when substantial completion had been reached."""
        if self.substantial_completion is None:
            return False
        return parse_date(as_of) >= self.substantial_completion

    def is_finally_complete(self, as_of):
        """Return True when final completion had been reached."""
        if self.final_completion is None:
            return False
        return parse_date(as_of) >= self.final_completion

    def days_late(self, as_of=None):
        """Return days past the contract completion date, never below zero."""
        if self.contract_completion is None:
            return 0
        reference = self.substantial_completion or (parse_date(as_of) if as_of else None)
        if reference is None:
            return 0
        late = (reference - self.contract_completion).days
        return late if late > 0 else 0

    def extended_by(self, days):
        """Return a copy with the contract completion date pushed out."""
        clone = CompletionDates(
            self.notice_to_proceed,
            self.contract_completion,
            self.substantial_completion,
            self.final_completion,
            self.punchlist_complete,
            self.closeout_submitted,
        )
        if clone.contract_completion is not None and days:
            from ..core.dates import add_days

            clone.contract_completion = add_days(clone.contract_completion, int(days))
        return clone

    def to_dict(self):
        """Return the dates as plain data."""
        return {
            "notice_to_proceed": format_date(self.notice_to_proceed) if self.notice_to_proceed else None,
            "contract_completion": (
                format_date(self.contract_completion) if self.contract_completion else None
            ),
            "substantial_completion": (
                format_date(self.substantial_completion) if self.substantial_completion else None
            ),
            "final_completion": format_date(self.final_completion) if self.final_completion else None,
            "punchlist_complete": (
                format_date(self.punchlist_complete) if self.punchlist_complete else None
            ),
            "closeout_submitted": (
                format_date(self.closeout_submitted) if self.closeout_submitted else None
            ),
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild dates from :meth:`to_dict` output."""
        return cls(
            data.get("notice_to_proceed"),
            data.get("contract_completion"),
            data.get("substantial_completion"),
            data.get("final_completion"),
            data.get("punchlist_complete"),
            data.get("closeout_submitted"),
        )

    def __repr__(self):
        return "CompletionDates(substantial=%r)" % (
            format_date(self.substantial_completion) if self.substantial_completion else None,
        )


class LiquidatedDamages:
    """A per-day amount assessed for finishing late, with an optional cap.

    >>> damages = LiquidatedDamages(money("1500"), cap=money("45000"))
    >>> str(damages.assess(40))
    '$45,000.00'
    >>> str(damages.assess(10))
    '$15,000.00'
    """

    __slots__ = ("per_day", "cap", "grace_days", "basis", "note")

    def __init__(self, per_day, cap=None, grace_days=0, basis="calendar", note=""):
        if not isinstance(per_day, Money):
            raise InputError("liquidated damages need a Money per-day amount")
        if per_day.is_negative():
            raise DataError("liquidated damages cannot be negative")
        self.per_day = per_day
        self.cap = cap
        if self.cap is not None and not isinstance(self.cap, Money):
            raise InputError("a liquidated damages cap must be Money")
        self.grace_days = int(grace_days)
        if str(basis) not in DAY_BASES:
            raise InputError("unknown day basis %r" % (basis,))
        self.basis = str(basis)
        self.note = str(note)

    def assess(self, days_late):
        """Return the damages for a number of late days, after grace and cap."""
        days = max(0, int(days_late) - self.grace_days)
        amount = self.per_day * days
        if self.cap is not None and amount > self.cap:
            return self.cap
        return amount

    def is_capped_at(self, days_late):
        """Return True when the cap binds at this number of late days."""
        if self.cap is None:
            return False
        days = max(0, int(days_late) - self.grace_days)
        return self.per_day * days > self.cap

    def to_dict(self):
        """Return the clause as plain data."""
        return {
            "per_day": str(self.per_day.amount),
            "cap": str(self.cap.amount) if self.cap else None,
            "grace_days": self.grace_days,
            "basis": self.basis,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild a clause from :meth:`to_dict` output."""
        return cls(
            money(data["per_day"], currency),
            money(data["cap"], currency) if data.get("cap") else None,
            data.get("grace_days", 0),
            data.get("basis", "calendar"),
            data.get("note", ""),
        )

    def __repr__(self):
        return "LiquidatedDamages(%r/day)" % (str(self.per_day.amount),)
