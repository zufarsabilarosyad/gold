"""Applying a payment to applications, which is a convention, not arithmetic.

A cheque arrives for less than the open balance.  What does it pay?

``oldest_first``
    The classic: clear the earliest application, then the next.  Simple, and it
    keeps the aging report honest.
``newest_first``
    Used by payers who want the current application clear and the dispute
    isolated on the old one.
``pro_rata``
    Every open application is credited in proportion.  Nothing ages, and
    nothing clears.
``specified``
    The remittance advice says which application the money is for, and the
    allocation follows it -- including when it makes no sense.

The choice changes the aging report, the interest calculation, and which
application a lien waiver has to cover.  It does not change the total owed,
which is why it is so easy to get wrong for a long time without noticing.
"""

from ..core.money import Money, zero
from ..core.numbers import allocate
from ..core.trace import NULL_TRACE
from ..errors import DataError, InputError

__all__ = ["ALLOCATION_ORDERS", "Allocation", "allocate_receipt", "open_balances"]

ALLOCATION_ORDERS = ("oldest_first", "newest_first", "pro_rata", "specified")


class Allocation:
    """How much of one receipt paid one application.

    >>> from ..core.money import money
    >>> allocation = Allocation("R-1", "PA-003", money("40000"))
    >>> str(allocation.amount)
    '$40,000.00'
    """

    __slots__ = ("receipt_id", "application_id", "amount", "note")

    def __init__(self, receipt_id, application_id, amount, note=""):
        self.receipt_id = str(receipt_id)
        self.application_id = str(application_id)
        if not isinstance(amount, Money):
            raise InputError("an allocation needs a Money amount")
        if amount.is_negative():
            raise DataError("allocation of %s to %s is negative" % (receipt_id, application_id))
        self.amount = amount
        self.note = str(note)

    def to_dict(self):
        """Return the allocation as plain data."""
        return {
            "receipt_id": self.receipt_id,
            "application_id": self.application_id,
            "amount": str(self.amount.amount),
            "note": self.note,
        }

    def __repr__(self):
        return "Allocation(%r -> %r, %s)" % (self.receipt_id, self.application_id, self.amount)


def open_balances(applications, allocations, currency="USD"):
    """Return each application's unpaid balance, in application order.

    >>> from ..core.money import money
    >>> from ..core.period import BillingPeriod
    >>> from ..billing.application import PayApplication
    >>> from ..billing.summary import ApplicationSummary
    >>> period = BillingPeriod(1, "2024-09-01", "2024-09-30")
    >>> summary = ApplicationSummary(money("100000"),
    ...     completed_and_stored=money("50000"), retainage_work=money("5000"))
    >>> application = PayApplication("PA-001", 1, period, summary=summary)
    >>> balances = open_balances([application], [])
    >>> str(balances["PA-001"])
    '$45,000.00'
    """
    paid = {}
    for allocation in allocations:
        paid[allocation.application_id] = (
            paid.get(allocation.application_id, zero(currency)) + allocation.amount
        )
    balances = {}
    for application in applications:
        owed = application.payable_amount()
        balances[application.id] = owed - paid.get(application.id, zero(owed.currency))
    return balances


def allocate_receipt(receipt, applications, allocations=(), order="oldest_first", specified=None, trace=NULL_TRACE):
    """Return the allocations one receipt produces under an ordering rule.

    >>> from ..core.money import money
    >>> from ..core.period import BillingPeriod
    >>> from ..billing.application import PayApplication
    >>> from ..billing.summary import ApplicationSummary
    >>> from .receipt import Receipt
    >>> def application(number, due):
    ...     period = BillingPeriod(number, "2024-%02d-01" % (8 + number,),
    ...                            "2024-%02d-28" % (8 + number,))
    ...     summary = ApplicationSummary(money("500000"),
    ...         completed_and_stored=money(due), retainage_work=money("0"))
    ...     return PayApplication("PA-%03d" % number, number, period, summary=summary)
    >>> first, second = application(1, "40000"), application(2, "30000")
    >>> receipt = Receipt("R-1", money("55000"), "2024-11-20")
    >>> [(item.application_id, str(item.amount))
    ...  for item in allocate_receipt(receipt, [first, second])]
    [('PA-001', '$40,000.00'), ('PA-002', '$15,000.00')]

    Pro-rata credits everything at once instead:

    >>> [(item.application_id, str(item.amount))
    ...  for item in allocate_receipt(receipt, [first, second], order="pro_rata")]
    [('PA-001', '$31,428.57'), ('PA-002', '$23,571.43')]
    """
    order = str(order)
    if order not in ALLOCATION_ORDERS:
        raise InputError(
            "unknown allocation order %r; known: %s" % (order, ", ".join(ALLOCATION_ORDERS))
        )
    currency = receipt.amount.currency
    balances = open_balances(applications, allocations, currency)
    open_items = [
        application
        for application in applications
        if balances.get(application.id, zero(currency)).amount > 0
    ]
    if order == "newest_first":
        open_items = sorted(open_items, key=lambda item: -item.number)
    elif order == "specified":
        if not specified:
            raise InputError("specified allocation needs a mapping of application to amount")
        results = []
        remaining = receipt.amount
        for application_id in sorted(specified):
            amount = specified[application_id]
            if amount > remaining:
                raise DataError(
                    "remittance advice allocates %s but the receipt is %s"
                    % (amount, receipt.amount)
                )
            results.append(Allocation(receipt.id, application_id, amount, "per remittance"))
            remaining = remaining - amount
        if remaining.amount > 0:
            trace.record(
                "allocation",
                receipt.id,
                "%s unallocated after the remittance advice" % (remaining,),
            )
        return results
    else:
        open_items = sorted(open_items, key=lambda item: item.number)
    if order == "pro_rata":
        weights = [balances[item.id].amount for item in open_items]
        if not weights:
            return []
        parts = allocate(receipt.amount.amount, weights)
        return [
            Allocation(receipt.id, item.id, Money(part, currency), "pro rata")
            for item, part in zip(open_items, parts)
            if part != 0
        ]
    results = []
    remaining = receipt.amount
    for item in open_items:
        if remaining.amount <= 0:
            break
        balance = balances[item.id]
        applied = balance if balance <= remaining else remaining
        results.append(Allocation(receipt.id, item.id, applied, order))
        trace.record("allocation", item.id, "%s applied from %s" % (applied, receipt.id))
        remaining = remaining - applied
    if remaining.amount > 0:
        trace.record("allocation", receipt.id, "%s remains unapplied" % (remaining,))
    return results
