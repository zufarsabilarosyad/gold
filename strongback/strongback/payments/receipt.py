"""Payments received, and the fact that they rarely match what was certified.

A payment arrives for an amount that is neither the request nor the
certification: the payer took a back-charge nobody told the payee about, or
rounded, or paid two applications with one cheque.  The receipt records what
actually arrived, and the allocation module decides what it pays for.

Nothing in this module changes an application's status.  Marking an application
paid is a conclusion drawn from allocations, and drawing it in one place keeps
the conclusion consistent.
"""

from ..core.dates import format_date, parse_date
from ..core.ids import normalise_id
from ..core.money import Money, money, zero
from ..errors import DataError, InputError

__all__ = ["PAYMENT_METHODS", "Receipt", "ReceiptLedger"]

PAYMENT_METHODS = ("check", "ach", "wire", "joint_check", "credit", "offset")


class Receipt:
    """One payment received by the payee.

    >>> from ..core.money import money
    >>> receipt = Receipt("R-1", money("60000"), "2024-12-20", method="ach",
    ...                   reference="ACH 8891")
    >>> str(receipt.amount)
    '$60,000.00'
    >>> receipt.method
    'ach'
    """

    __slots__ = ("id", "amount", "received_on", "method", "reference", "payer", "note", "joint_payees")

    def __init__(
        self,
        identifier,
        amount,
        received_on,
        method="check",
        reference="",
        payer="",
        note="",
        joint_payees=(),
    ):
        self.id = normalise_id(identifier, "receipt id")
        if not isinstance(amount, Money):
            raise InputError("a receipt needs a Money amount")
        if amount.is_negative():
            raise DataError("receipt %s is negative" % (self.id,))
        self.amount = amount
        self.received_on = parse_date(received_on, "receipt date")
        if str(method) not in PAYMENT_METHODS:
            raise InputError(
                "unknown payment method %r; known: %s" % (method, ", ".join(PAYMENT_METHODS))
            )
        self.method = str(method)
        self.reference = str(reference)
        self.payer = str(payer)
        self.note = str(note)
        self.joint_payees = tuple(str(name) for name in joint_payees)
        if self.method == "joint_check" and not self.joint_payees:
            raise DataError("joint cheque %s names no joint payee" % (self.id,))

    def is_joint(self):
        """Return True when the payment names more than one payee."""
        return bool(self.joint_payees)

    def to_dict(self):
        """Return the receipt as plain data."""
        return {
            "id": self.id,
            "amount": str(self.amount.amount),
            "received_on": format_date(self.received_on),
            "method": self.method,
            "reference": self.reference,
            "payer": self.payer,
            "note": self.note,
            "joint_payees": list(self.joint_payees),
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild a receipt from :meth:`to_dict` output."""
        return cls(
            data["id"],
            money(data["amount"], currency),
            data["received_on"],
            data.get("method", "check"),
            data.get("reference", ""),
            data.get("payer", ""),
            data.get("note", ""),
            data.get("joint_payees", ()),
        )

    def __eq__(self, other):
        return isinstance(other, Receipt) and other.id == self.id

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("Receipt", self.id))

    def __str__(self):
        return "%s %s on %s" % (self.id, self.amount, format_date(self.received_on))

    def __repr__(self):
        return "Receipt(%r, %s)" % (self.id, self.amount)


class ReceiptLedger:
    """Every payment received on a contract, in date order.

    >>> from ..core.money import money
    >>> ledger = ReceiptLedger()
    >>> ledger.add(Receipt("R-1", money("60000"), "2024-11-15"))
    >>> ledger.add(Receipt("R-2", money("42000"), "2024-12-18"))
    >>> str(ledger.total())
    '$102,000.00'
    >>> str(ledger.total_through("2024-11-30"))
    '$60,000.00'
    >>> [receipt.id for receipt in ledger.between("2024-12-01", "2024-12-31")]
    ['R-2']
    """

    def __init__(self, receipts=(), currency="USD"):
        self.currency = currency
        self.receipts = {}
        for receipt in receipts:
            self.add(receipt)

    def add(self, receipt):
        """Add a receipt, refusing a duplicate identifier."""
        if receipt.id in self.receipts:
            raise DataError("receipt %s appears twice" % (receipt.id,))
        self.receipts[receipt.id] = receipt

    def get(self, identifier, default=None):
        """Return a receipt, or ``default``."""
        return self.receipts.get(normalise_id(identifier, "receipt id"), default)

    def require(self, identifier):
        """Return a receipt, raising when it is missing."""
        receipt = self.get(identifier)
        if receipt is None:
            raise DataError("no receipt %r on this contract" % (identifier,))
        return receipt

    def ordered(self):
        """Return the receipts in date then identifier order."""
        return sorted(self.receipts.values(), key=lambda item: (item.received_on, item.id))

    def between(self, start, end):
        """Return the receipts in a date window, ends included."""
        start = parse_date(start, "start")
        end = parse_date(end, "end")
        return [
            receipt for receipt in self.ordered() if start <= receipt.received_on <= end
        ]

    def total(self):
        """Return everything received."""
        running = zero(self.currency)
        for receipt in self.ordered():
            running = running + receipt.amount
        return running

    def total_through(self, day):
        """Return everything received on or before a date."""
        day = parse_date(day)
        running = zero(self.currency)
        for receipt in self.ordered():
            if receipt.received_on <= day:
                running = running + receipt.amount
        return running

    def joint_checks(self):
        """Return the receipts that named a joint payee."""
        return [receipt for receipt in self.ordered() if receipt.is_joint()]

    def to_list(self):
        """Return the ledger as plain data."""
        return [receipt.to_dict() for receipt in self.ordered()]

    @classmethod
    def from_list(cls, data, currency="USD"):
        """Rebuild a ledger from :meth:`to_list` output."""
        return cls([Receipt.from_dict(entry, currency) for entry in data], currency)

    def __len__(self):
        return len(self.receipts)

    def __iter__(self):
        return iter(self.ordered())

    def __getitem__(self, identifier):
        return self.require(identifier)

    def __repr__(self):
        return "ReceiptLedger(%d receipts, %s)" % (len(self.receipts), self.total())
