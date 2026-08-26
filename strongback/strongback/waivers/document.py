"""Lien waivers: four documents that are routinely treated as one.

The two axes are independent and both matter.

*Conditional or unconditional.*  A conditional waiver takes effect only when
the payment it names actually clears.  An unconditional waiver takes effect on
signature, whether or not the cheque is good.  Signing an unconditional waiver
against a cheque that has not cleared is the single most common way a
subcontractor loses lien rights, and it happens because the two documents look
almost identical.

*Progress or final.*  A progress waiver releases rights through a stated date
for a stated amount.  A final waiver releases everything, including retainage
and claims -- which is why the through date on a final waiver is not the point;
the word "final" is.

The through date is the other trap.  A waiver "through 30 November" does not
cover work done on 1 December, and a payment covering a December application
against a November waiver leaves the payer unprotected for the gap.
"""

from ..core.dates import format_date, parse_date
from ..core.ids import normalise_id
from ..core.money import Money, money, zero
from ..errors import DataError, InputError

__all__ = ["WAIVER_TYPES", "WaiverType", "LienWaiver"]

WAIVER_TYPES = (
    "conditional_progress",
    "unconditional_progress",
    "conditional_final",
    "unconditional_final",
)


class WaiverType:
    """One of the four waiver documents.

    >>> WaiverType("conditional_progress").is_conditional()
    True
    >>> WaiverType("unconditional_final").is_final()
    True
    >>> WaiverType("conditional_final").releases_retainage()
    True
    """

    __slots__ = ("name",)

    def __init__(self, name):
        text = str(name).strip().lower().replace(" ", "_").replace("-", "_")
        if text not in WAIVER_TYPES:
            raise InputError("unknown waiver type %r; known: %s" % (name, ", ".join(WAIVER_TYPES)))
        self.name = text

    def is_conditional(self):
        """Return True when the release depends on the payment clearing."""
        return self.name.startswith("conditional")

    def is_final(self):
        """Return True when the waiver releases everything, not a period."""
        return self.name.endswith("final")

    def releases_retainage(self):
        """Return True when the document releases retainage as well as work."""
        return self.is_final()

    def counterpart(self):
        """Return the matching document on the other side of the conditional axis.

        >>> WaiverType("conditional_progress").counterpart()
        WaiverType('unconditional_progress')
        """
        if self.is_conditional():
            return WaiverType(self.name.replace("conditional", "unconditional", 1))
        return WaiverType("conditional" + self.name[len("unconditional"):])

    def __eq__(self, other):
        if isinstance(other, WaiverType):
            return other.name == self.name
        if isinstance(other, str):
            return self.name == str(other).strip().lower()
        return NotImplemented

    def __ne__(self, other):
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    def __hash__(self):
        return hash(("WaiverType", self.name))

    def __str__(self):
        return self.name

    def __repr__(self):
        return "WaiverType(%r)" % (self.name,)


class LienWaiver:
    """One signed waiver.

    >>> from ..core.money import money
    >>> waiver = LienWaiver("W-004", "conditional_progress", money("67500"),
    ...                     "2024-11-30", signed_on="2024-12-02",
    ...                     application_id="PA-003")
    >>> waiver.covers_through("2024-11-30")
    True
    >>> waiver.covers_through("2024-12-01")
    False
    >>> waiver.is_effective(paid=False)
    False
    >>> waiver.is_effective(paid=True)
    True
    """

    __slots__ = (
        "id",
        "type",
        "amount",
        "through",
        "signed_on",
        "application_id",
        "signer",
        "notarised",
        "exceptions",
        "note",
    )

    def __init__(
        self,
        identifier,
        waiver_type,
        amount,
        through,
        signed_on=None,
        application_id="",
        signer="",
        notarised=False,
        exceptions=(),
        note="",
    ):
        self.id = normalise_id(identifier, "waiver id")
        self.type = waiver_type if isinstance(waiver_type, WaiverType) else WaiverType(waiver_type)
        if not isinstance(amount, Money):
            raise InputError("a waiver needs a Money amount")
        if amount.is_negative():
            raise DataError("waiver %s is for a negative amount" % (self.id,))
        self.amount = amount
        self.through = parse_date(through, "through date")
        self.signed_on = parse_date(signed_on) if signed_on else None
        if self.signed_on is not None and self.signed_on < self.through and not self.type.is_final():
            raise DataError(
                "waiver %s is signed %s but covers through %s"
                % (self.id, format_date(self.signed_on), format_date(self.through))
            )
        self.application_id = str(application_id)
        self.signer = str(signer)
        self.notarised = bool(notarised)
        self.exceptions = tuple(str(item) for item in exceptions)
        self.note = str(note)

    def covers_through(self, day):
        """Return True when the waiver reaches a date."""
        return self.through >= parse_date(day)

    def covers_amount(self, amount):
        """Return True when the waiver's amount reaches a figure."""
        return self.amount >= amount

    def is_effective(self, paid=False):
        """Return True when the waiver has actually released anything."""
        if self.type.is_conditional():
            return bool(paid)
        return True

    def has_exceptions(self):
        """Return True when the signer excepted claims from the release."""
        return bool(self.exceptions)

    def to_dict(self):
        """Return the waiver as plain data."""
        return {
            "id": self.id,
            "type": str(self.type),
            "amount": str(self.amount.amount),
            "through": format_date(self.through),
            "signed_on": format_date(self.signed_on) if self.signed_on else None,
            "application_id": self.application_id,
            "signer": self.signer,
            "notarised": self.notarised,
            "exceptions": list(self.exceptions),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild a waiver from :meth:`to_dict` output."""
        return cls(
            data["id"],
            data["type"],
            money(data["amount"], currency),
            data["through"],
            data.get("signed_on"),
            data.get("application_id", ""),
            data.get("signer", ""),
            data.get("notarised", False),
            data.get("exceptions", ()),
            data.get("note", ""),
        )

    def __eq__(self, other):
        return isinstance(other, LienWaiver) and other.id == self.id

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("LienWaiver", self.id))

    def __str__(self):
        return "%s %s %s through %s" % (
            self.id,
            self.type,
            self.amount,
            format_date(self.through),
        )

    def __repr__(self):
        return "LienWaiver(%r, %r)" % (self.id, str(self.type))
