"""Back-charges: work one party did that another party was supposed to do.

A back-charge is a deduction from a payee's application for costs the payer
incurred on their behalf -- final cleaning the sub never did, a hoist the sub
used and did not pay for, damage repaired by others.  The amount is rarely the
argument.  The argument is *where in the application it lands*, and there are
three defensible answers:

``gross``
    Deduct before retainage is computed, so the payee is not retained on work
    they are being charged for.  The deduction effectively costs the payee the
    back-charge less the retainage rate on it.
``net``
    Deduct after retainage, from the amount payable.  The payee is retained on
    the full billed value and pays the back-charge in full this period.
``retainage``
    Take the back-charge out of retainage held rather than out of the current
    payment, which delays the impact to closeout.

The three differ by exactly the retainage rate times the back-charge, and every
one of them appears in real subcontracts.
"""

from ..core.dates import format_date, parse_date
from ..core.ids import normalise_code, normalise_id
from ..core.money import Money, money, zero
from ..core.trace import NULL_TRACE
from ..errors import DataError, InputError

__all__ = ["BACKCHARGE_STAGES", "BackCharge", "BackChargeRegister", "apply_backcharges"]

BACKCHARGE_STAGES = ("gross", "net", "retainage")


class BackCharge:
    """A cost charged back to the payee.

    >>> from ..core.money import money
    >>> charge = BackCharge("BC-1", money("3200"), 4, reason="final clean",
    ...                     stage="gross", code="01700")
    >>> str(charge.amount)
    '$3,200.00'
    >>> charge.stage
    'gross'
    """

    __slots__ = (
        "id",
        "amount",
        "period",
        "stage",
        "code",
        "reason",
        "issued_on",
        "disputed",
        "approved_by",
        "supporting_document",
    )

    def __init__(
        self,
        identifier,
        amount,
        period,
        stage="net",
        code="",
        reason="",
        issued_on=None,
        disputed=False,
        approved_by="",
        supporting_document="",
    ):
        self.id = normalise_id(identifier, "back-charge id")
        if not isinstance(amount, Money):
            raise InputError("a back-charge needs a Money amount")
        if amount.is_negative():
            raise DataError("back-charge %s is negative" % (self.id,))
        self.amount = amount
        self.period = int(period)
        if str(stage) not in BACKCHARGE_STAGES:
            raise InputError(
                "unknown back-charge stage %r; known: %s" % (stage, ", ".join(BACKCHARGE_STAGES))
            )
        self.stage = str(stage)
        self.code = normalise_code(code) if code else ""
        self.reason = str(reason)
        self.issued_on = parse_date(issued_on) if issued_on else None
        self.disputed = bool(disputed)
        self.approved_by = str(approved_by)
        self.supporting_document = str(supporting_document)

    def is_deductible(self, allow_disputed=False):
        """Return True when the charge may be taken this period."""
        if self.disputed and not allow_disputed:
            return False
        return True

    def to_dict(self):
        """Return the back-charge as plain data."""
        return {
            "id": self.id,
            "amount": str(self.amount.amount),
            "period": self.period,
            "stage": self.stage,
            "code": self.code,
            "reason": self.reason,
            "issued_on": format_date(self.issued_on) if self.issued_on else None,
            "disputed": self.disputed,
            "approved_by": self.approved_by,
            "supporting_document": self.supporting_document,
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild a back-charge from :meth:`to_dict` output."""
        return cls(
            data["id"],
            money(data["amount"], currency),
            data["period"],
            data.get("stage", "net"),
            data.get("code", ""),
            data.get("reason", ""),
            data.get("issued_on"),
            data.get("disputed", False),
            data.get("approved_by", ""),
            data.get("supporting_document", ""),
        )

    def __eq__(self, other):
        return isinstance(other, BackCharge) and other.id == self.id

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("BackCharge", self.id))

    def __str__(self):
        return "%s %s (%s)" % (self.id, self.amount, self.reason or self.stage)

    def __repr__(self):
        return "BackCharge(%r, %s)" % (self.id, self.amount)


class BackChargeRegister:
    """Every back-charge on a contract.

    >>> from ..core.money import money
    >>> register = BackChargeRegister()
    >>> register.add(BackCharge("BC-1", money("3200"), 4, stage="gross"))
    >>> register.add(BackCharge("BC-2", money("900"), 4, stage="net", disputed=True))
    >>> str(register.total_for_period(4))
    '$3,200.00'
    >>> str(register.total_for_period(4, allow_disputed=True))
    '$4,100.00'
    """

    def __init__(self, charges=(), currency="USD"):
        self.currency = currency
        self.charges = {}
        for charge in charges:
            self.add(charge)

    def add(self, charge):
        """Add a back-charge, refusing a duplicate identifier."""
        if charge.id in self.charges:
            raise DataError("back-charge %s appears twice" % (charge.id,))
        self.charges[charge.id] = charge

    def get(self, identifier, default=None):
        """Return a back-charge, or ``default``."""
        return self.charges.get(normalise_id(identifier, "back-charge id"), default)

    def ordered(self):
        """Return the back-charges in period then identifier order."""
        return sorted(self.charges.values(), key=lambda charge: (charge.period, charge.id))

    def for_period(self, period, stage=None, allow_disputed=False):
        """Return the deductible back-charges in a period."""
        period = int(period)
        found = []
        for charge in self.ordered():
            if charge.period != period:
                continue
            if stage is not None and charge.stage != str(stage):
                continue
            if not charge.is_deductible(allow_disputed):
                continue
            found.append(charge)
        return found

    def total_for_period(self, period, stage=None, allow_disputed=False):
        """Return the total deductible in a period, optionally by stage."""
        running = zero(self.currency)
        for charge in self.for_period(period, stage, allow_disputed):
            running = running + charge.amount
        return running

    def to_date(self, through_period, stage=None, allow_disputed=False):
        """Return the total deducted through a period."""
        running = zero(self.currency)
        for period in range(1, int(through_period) + 1):
            running = running + self.total_for_period(period, stage, allow_disputed)
        return running

    def disputed(self):
        """Return the disputed back-charges."""
        return [charge for charge in self.ordered() if charge.disputed]

    def to_list(self):
        """Return the register as plain data."""
        return [charge.to_dict() for charge in self.ordered()]

    @classmethod
    def from_list(cls, data, currency="USD"):
        """Rebuild a register from :meth:`to_list` output."""
        return cls([BackCharge.from_dict(entry, currency) for entry in data], currency)

    def __len__(self):
        return len(self.charges)

    def __iter__(self):
        return iter(self.ordered())

    def __repr__(self):
        return "BackChargeRegister(%d charges)" % (len(self.charges),)


def apply_backcharges(gross, retainage, register, period, allow_disputed=False, trace=NULL_TRACE):
    """Return the amounts after back-charges land at their stated stages.

    Returns a triple of the adjusted gross billing, the adjusted retainage
    base effect, and the deduction to take from the net payment.

    >>> from ..core.money import money
    >>> register = BackChargeRegister()
    >>> register.add(BackCharge("BC-1", money("10000"), 4, stage="gross"))
    >>> register.add(BackCharge("BC-2", money("5000"), 4, stage="net"))
    >>> gross, retainage_reduction, net_deduction = apply_backcharges(
    ...     money("200000"), money("20000"), register, 4)
    >>> str(gross), str(net_deduction)
    ('$190,000.00', '$5,000.00')
    >>> str(retainage_reduction)
    '$0.00'
    """
    currency = gross.currency
    gross_charges = register.total_for_period(period, "gross", allow_disputed)
    net_charges = register.total_for_period(period, "net", allow_disputed)
    retainage_charges = register.total_for_period(period, "retainage", allow_disputed)
    adjusted_gross = gross - gross_charges
    if gross_charges:
        trace.record(
            "back-charge",
            "contract",
            "%s deducted before retainage" % (gross_charges,),
            {"gross": str(adjusted_gross.amount)},
        )
    if net_charges:
        trace.record("back-charge", "contract", "%s deducted from the payment" % (net_charges,))
    if retainage_charges:
        trace.record(
            "back-charge", "contract", "%s taken out of retainage held" % (retainage_charges,)
        )
    return adjusted_gross, retainage_charges, net_charges
