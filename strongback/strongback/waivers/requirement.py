"""What waiver a payment requires, and what it has to cover.

Contracts state the exchange in one of three ways, and the third is the one
that catches people out.

``with_application``
    A conditional waiver for this application accompanies it, and the
    unconditional waiver for the *previous* payment comes with it too.  This is
    the standard exchange and it always runs one payment behind.
``before_payment``
    An unconditional waiver for this application is required before the cheque
    is cut, which asks the payee to release rights against money they have not
    received.
``after_payment``
    The unconditional waiver follows the cheque, so the payer carries the gap.

The through date is the other half of the requirement.  ``period_end`` asks the
waiver to reach the end of the billing period; ``application_through`` asks only
for the measurement cutoff, which is earlier and leaves the tail of the month
unwaived.
"""

from ..core.dates import format_date, parse_date
from ..errors import DataError, InputError
from .document import WaiverType

__all__ = ["EXCHANGE_RULES", "THROUGH_RULES", "WaiverRequirement", "required_through"]

EXCHANGE_RULES = ("with_application", "before_payment", "after_payment", "none")
THROUGH_RULES = ("period_end", "application_through", "payment_date")


class WaiverRequirement:
    """The waiver policy of one contract.

    >>> requirement = WaiverRequirement()
    >>> requirement.exchange
    'with_application'
    >>> str(requirement.type_for_current())
    'conditional_progress'
    >>> str(requirement.type_for_previous())
    'unconditional_progress'
    """

    __slots__ = ("exchange", "through_rule", "require_notarised", "allow_exceptions", "final_required")

    def __init__(
        self,
        exchange="with_application",
        through_rule="period_end",
        require_notarised=False,
        allow_exceptions=False,
        final_required=True,
    ):
        if str(exchange) not in EXCHANGE_RULES:
            raise InputError(
                "unknown waiver exchange %r; known: %s" % (exchange, ", ".join(EXCHANGE_RULES))
            )
        self.exchange = str(exchange)
        if str(through_rule) not in THROUGH_RULES:
            raise InputError("unknown through rule %r" % (through_rule,))
        self.through_rule = str(through_rule)
        self.require_notarised = bool(require_notarised)
        self.allow_exceptions = bool(allow_exceptions)
        self.final_required = bool(final_required)

    def gates_payment(self):
        """Return True when a missing waiver stops the payment."""
        return self.exchange in ("with_application", "before_payment")

    def type_for_current(self):
        """Return the waiver type this application must carry."""
        if self.exchange == "before_payment":
            return WaiverType("unconditional_progress")
        return WaiverType("conditional_progress")

    def type_for_previous(self):
        """Return the waiver type required for the previous payment."""
        return WaiverType("unconditional_progress")

    def accepts(self, waiver, required_type=None):
        """Return the problems with a waiver, empty when it is acceptable.

        >>> from ..core.money import money
        >>> from .document import LienWaiver
        >>> requirement = WaiverRequirement(require_notarised=True)
        >>> waiver = LienWaiver("W-1", "conditional_progress", money("1000"),
        ...                     "2024-11-30", signed_on="2024-12-01")
        >>> requirement.accepts(waiver)
        ['waiver W-1 is not notarised']
        """
        problems = []
        expected = required_type or self.type_for_current()
        if waiver.type != expected:
            problems.append(
                "waiver %s is a %s where a %s is required" % (waiver.id, waiver.type, expected)
            )
        if self.require_notarised and not waiver.notarised:
            problems.append("waiver %s is not notarised" % (waiver.id,))
        if waiver.has_exceptions() and not self.allow_exceptions:
            problems.append(
                "waiver %s excepts %s from the release"
                % (waiver.id, ", ".join(waiver.exceptions))
            )
        if waiver.signed_on is None:
            problems.append("waiver %s is unsigned" % (waiver.id,))
        return problems

    def to_dict(self):
        """Return the requirement as plain data."""
        return {
            "exchange": self.exchange,
            "through_rule": self.through_rule,
            "require_notarised": self.require_notarised,
            "allow_exceptions": self.allow_exceptions,
            "final_required": self.final_required,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild a requirement from :meth:`to_dict` output."""
        return cls(
            data.get("exchange", "with_application"),
            data.get("through_rule", "period_end"),
            data.get("require_notarised", False),
            data.get("allow_exceptions", False),
            data.get("final_required", True),
        )

    def __repr__(self):
        return "WaiverRequirement(%r, %r)" % (self.exchange, self.through_rule)


def required_through(requirement, period, payment_date=None):
    """Return the date a waiver has to reach for one application.

    >>> from ..core.period import BillingPeriod
    >>> period = BillingPeriod(3, "2024-11-01", "2024-11-30", through="2024-11-25")
    >>> format_date(required_through(WaiverRequirement(), period))
    '2024-11-30'
    >>> format_date(required_through(WaiverRequirement(through_rule="application_through"),
    ...                              period))
    '2024-11-25'
    >>> format_date(required_through(WaiverRequirement(through_rule="payment_date"),
    ...                              period, "2024-12-20"))
    '2024-12-20'
    """
    if requirement.through_rule == "application_through":
        return period.through
    if requirement.through_rule == "payment_date":
        if payment_date is None:
            raise DataError("this waiver rule needs the payment date")
        return parse_date(payment_date)
    return period.end
