"""Offsets: money withheld for a reason that is not the work itself.

Back-charges pay for work; offsets withhold against risk.  A lien filed by a
second-tier supplier, an expired insurance certificate, an unreturned hoist
deposit, liquidated damages accruing on a late milestone -- each of these
reduces a payment without reducing what was earned, and each behaves
differently at closeout.

The distinction that matters is *reversible* versus *absorbed*.  An offset
against a lien is released the day the lien is bonded off, and the money is
still owed.  Liquidated damages are gone.  A system that lumps them together
tells the payee they are owed money they will never see, or the reverse.
"""

from ..core.dates import format_date, parse_date
from ..core.ids import normalise_id
from ..core.money import Money, money, zero
from ..errors import DataError, InputError

__all__ = ["OFFSET_KINDS", "Offset", "OffsetRegister"]

OFFSET_KINDS = (
    "lien",
    "insurance",
    "liquidated_damages",
    "safety",
    "cleanup",
    "warranty",
    "deposit",
    "other",
)

_REVERSIBLE = ("lien", "insurance", "deposit", "warranty")


class Offset:
    """An amount withheld pending an event, or absorbed outright.

    >>> from ..core.money import money
    >>> offset = Offset("OF-1", "lien", money("15000"), 5, reason="second-tier lien")
    >>> offset.is_reversible()
    True
    >>> offset.is_open()
    True
    >>> _ = offset.resolve("2025-01-15")
    >>> offset.is_open()
    False
    """

    __slots__ = ("id", "kind", "amount", "period", "reason", "raised_on", "resolved_on", "note")

    def __init__(self, identifier, kind, amount, period, reason="", raised_on=None, resolved_on=None, note=""):
        self.id = normalise_id(identifier, "offset id")
        if str(kind) not in OFFSET_KINDS:
            raise InputError("unknown offset kind %r; known: %s" % (kind, ", ".join(OFFSET_KINDS)))
        self.kind = str(kind)
        if not isinstance(amount, Money):
            raise InputError("an offset needs a Money amount")
        if amount.is_negative():
            raise DataError("offset %s is negative" % (self.id,))
        self.amount = amount
        self.period = int(period)
        self.reason = str(reason)
        self.raised_on = parse_date(raised_on) if raised_on else None
        self.resolved_on = parse_date(resolved_on) if resolved_on else None
        self.note = str(note)

    def is_reversible(self):
        """Return True when resolving the underlying event releases the money."""
        return self.kind in _REVERSIBLE

    def is_open(self):
        """Return True when the offset is still being withheld."""
        return self.resolved_on is None

    def is_open_at(self, period):
        """Return True when the offset was still open in a period."""
        if self.period > int(period):
            return False
        return self.resolved_on is None

    def resolve(self, on):
        """Record the date the offset was lifted."""
        self.resolved_on = parse_date(on)
        return self

    def to_dict(self):
        """Return the offset as plain data."""
        return {
            "id": self.id,
            "kind": self.kind,
            "amount": str(self.amount.amount),
            "period": self.period,
            "reason": self.reason,
            "raised_on": format_date(self.raised_on) if self.raised_on else None,
            "resolved_on": format_date(self.resolved_on) if self.resolved_on else None,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild an offset from :meth:`to_dict` output."""
        return cls(
            data["id"],
            data["kind"],
            money(data["amount"], currency),
            data["period"],
            data.get("reason", ""),
            data.get("raised_on"),
            data.get("resolved_on"),
            data.get("note", ""),
        )

    def __eq__(self, other):
        return isinstance(other, Offset) and other.id == self.id

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("Offset", self.id))

    def __repr__(self):
        return "Offset(%r, %r, %s)" % (self.id, self.kind, self.amount)


class OffsetRegister:
    """Every offset on a contract, open and resolved.

    >>> from ..core.money import money
    >>> register = OffsetRegister()
    >>> register.add(Offset("OF-1", "lien", money("15000"), 5))
    >>> register.add(Offset("OF-2", "liquidated_damages", money("9000"), 6))
    >>> str(register.open_total(6))
    '$24,000.00'
    >>> str(register.reversible_total(6))
    '$15,000.00'
    >>> str(register.absorbed_total(6))
    '$9,000.00'
    """

    def __init__(self, offsets=(), currency="USD"):
        self.currency = currency
        self.offsets = {}
        for offset in offsets:
            self.add(offset)

    def add(self, offset):
        """Add an offset, refusing a duplicate identifier."""
        if offset.id in self.offsets:
            raise DataError("offset %s appears twice" % (offset.id,))
        self.offsets[offset.id] = offset

    def get(self, identifier, default=None):
        """Return an offset, or ``default``."""
        return self.offsets.get(normalise_id(identifier, "offset id"), default)

    def ordered(self):
        """Return the offsets in period then identifier order."""
        return sorted(self.offsets.values(), key=lambda offset: (offset.period, offset.id))

    def open_at(self, period):
        """Return the offsets still open in a period."""
        return [offset for offset in self.ordered() if offset.is_open_at(period)]

    def of_kind(self, kind):
        """Return the offsets of one kind."""
        return [offset for offset in self.ordered() if offset.kind == str(kind)]

    def open_total(self, period):
        """Return the total withheld by open offsets in a period."""
        running = zero(self.currency)
        for offset in self.open_at(period):
            running = running + offset.amount
        return running

    def reversible_total(self, period):
        """Return the open offsets that will be released on resolution."""
        running = zero(self.currency)
        for offset in self.open_at(period):
            if offset.is_reversible():
                running = running + offset.amount
        return running

    def absorbed_total(self, period):
        """Return the open offsets that will never be paid."""
        running = zero(self.currency)
        for offset in self.open_at(period):
            if not offset.is_reversible():
                running = running + offset.amount
        return running

    def resolved_in(self, period):
        """Return the offsets whose resolution should release money."""
        return [
            offset
            for offset in self.ordered()
            if offset.resolved_on is not None and offset.period <= int(period)
        ]

    def to_list(self):
        """Return the register as plain data."""
        return [offset.to_dict() for offset in self.ordered()]

    @classmethod
    def from_list(cls, data, currency="USD"):
        """Rebuild a register from :meth:`to_list` output."""
        return cls([Offset.from_dict(entry, currency) for entry in data], currency)

    def __len__(self):
        return len(self.offsets)

    def __iter__(self):
        return iter(self.ordered())

    def __repr__(self):
        return "OffsetRegister(%d offsets)" % (len(self.offsets),)
