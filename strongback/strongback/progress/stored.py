"""Stored materials: paid for, on site, and not yet part of the building.

Materials delivered but not installed are the most argued-over column on a
continuation sheet, for three reasons that this module keeps separate.

*Eligibility.*  Material on site is normally billable; material in a warehouse
two states away usually is not, unless it is bonded, insured and marked with
the owner's name.

*Ceiling.*  Many contracts cap stored materials at a share of the line's
scheduled value, so a hundred-thousand-dollar switchgear delivery against a
seventy-thousand-dollar line bills seventy.

*Conversion.*  When the material is installed it stops being stored and starts
being work in place, and the sheet has to move the value across without ever
billing it twice.  Contracts disagree about who says when that happens: an
explicit conversion reported by the field, a proportional conversion that
follows the completion percentage, or a conversion at completion of the line.
The proportional rule is the one that silently disagrees with the field, and it
is also the most common default in billing software.
"""

from decimal import Decimal

from ..core.ids import normalise_code
from ..core.money import Money, money, zero
from ..core.percent import Rate, rate_text
from ..core.trace import NULL_TRACE
from ..errors import DataError, InputError

__all__ = [
    "CONVERSION_RULES",
    "StoredEntry",
    "StoredLedger",
    "StoredOptions",
    "stored_on_hand",
]

CONVERSION_RULES = ("explicit", "proportional", "on_completion")


class StoredOptions:
    """The conventions that govern the stored-materials column.

    >>> options = StoredOptions(cap="80%", allow_offsite=False)
    >>> options.conversion
    'explicit'
    >>> str(options.cap)
    '80%'
    """

    __slots__ = ("conversion", "cap", "allow_offsite", "require_insurance", "retained")

    def __init__(
        self,
        conversion="explicit",
        cap=None,
        allow_offsite=False,
        require_insurance=True,
        retained=True,
    ):
        if str(conversion) not in CONVERSION_RULES:
            raise InputError(
                "unknown conversion rule %r; known: %s"
                % (conversion, ", ".join(CONVERSION_RULES))
            )
        self.conversion = str(conversion)
        self.cap = Rate.parse(cap) if cap is not None else None
        self.allow_offsite = bool(allow_offsite)
        self.require_insurance = bool(require_insurance)
        self.retained = bool(retained)

    def to_dict(self):
        """Return the options as plain data."""
        return {
            "conversion": self.conversion,
            "cap": rate_text(self.cap) if self.cap else None,
            "allow_offsite": self.allow_offsite,
            "require_insurance": self.require_insurance,
            "retained": self.retained,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild options from :meth:`to_dict` output."""
        return cls(
            data.get("conversion", "explicit"),
            data.get("cap"),
            data.get("allow_offsite", False),
            data.get("require_insurance", True),
            data.get("retained", True),
        )

    def __repr__(self):
        return "StoredOptions(%r)" % (self.conversion,)


class StoredEntry:
    """A delivery to, or a conversion out of, the stored-materials column.

    >>> entry = StoredEntry("26200", 2, delivered=money("48000"), invoice="SG-1188")
    >>> str(entry.delivered)
    '$48,000.00'
    >>> entry.offsite
    False
    """

    __slots__ = (
        "code",
        "period",
        "delivered",
        "converted",
        "offsite",
        "insured",
        "bonded",
        "invoice",
        "description",
    )

    def __init__(
        self,
        code,
        period,
        delivered=None,
        converted=None,
        offsite=False,
        insured=True,
        bonded=False,
        invoice="",
        description="",
    ):
        self.code = normalise_code(code)
        self.period = int(period)
        if delivered is None and converted is None:
            raise InputError(
                "stored entry for %s period %d reports neither a delivery nor a conversion"
                % (self.code, self.period)
            )
        for name, amount in (("delivered", delivered), ("converted", converted)):
            if amount is not None and not isinstance(amount, Money):
                raise InputError("stored %s must be Money" % (name,))
            if amount is not None and amount.is_negative():
                raise DataError(
                    "stored %s for %s period %d is negative" % (name, self.code, self.period)
                )
        self.delivered = delivered
        self.converted = converted
        self.offsite = bool(offsite)
        self.insured = bool(insured)
        self.bonded = bool(bonded)
        self.invoice = str(invoice)
        self.description = str(description)

    def is_eligible(self, options):
        """Return True when the delivery may be billed under the options."""
        if self.offsite and not options.allow_offsite:
            return False
        if options.require_insurance and not self.insured:
            return False
        return True

    def to_dict(self):
        """Return the entry as plain data."""
        return {
            "code": self.code,
            "period": self.period,
            "delivered": str(self.delivered.amount) if self.delivered else None,
            "converted": str(self.converted.amount) if self.converted else None,
            "offsite": self.offsite,
            "insured": self.insured,
            "bonded": self.bonded,
            "invoice": self.invoice,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild an entry from :meth:`to_dict` output."""
        return cls(
            data["code"],
            data["period"],
            money(data["delivered"], currency) if data.get("delivered") else None,
            money(data["converted"], currency) if data.get("converted") else None,
            data.get("offsite", False),
            data.get("insured", True),
            data.get("bonded", False),
            data.get("invoice", ""),
            data.get("description", ""),
        )

    def __repr__(self):
        return "StoredEntry(%r, period=%d)" % (self.code, self.period)


class StoredLedger:
    """Every stored-materials movement on a contract.

    >>> ledger = StoredLedger()
    >>> ledger.record(StoredEntry("26200", 1, delivered=money("48000")))
    >>> ledger.record(StoredEntry("26200", 2, converted=money("18000")))
    >>> str(ledger.delivered_to_date("26200", 2))
    '$48,000.00'
    >>> str(ledger.converted_to_date("26200", 2))
    '$18,000.00'
    """

    def __init__(self, entries=(), currency="USD"):
        self.currency = currency
        self.entries = []
        for entry in entries:
            self.record(entry)

    def record(self, entry):
        """Add a movement."""
        if not isinstance(entry, StoredEntry):
            raise InputError("expected a StoredEntry")
        self.entries.append(entry)

    def for_line(self, code, through_period=None):
        """Return a line's movements in period order."""
        code = normalise_code(code)
        entries = [entry for entry in self.entries if entry.code == code]
        if through_period is not None:
            entries = [entry for entry in entries if entry.period <= int(through_period)]
        return sorted(entries, key=lambda entry: entry.period)

    def codes(self):
        """Return the lines with stored movements, in code order."""
        return sorted({entry.code for entry in self.entries})

    def delivered_to_date(self, code, through_period, options=None):
        """Return the eligible deliveries to date on a line."""
        options = options or StoredOptions()
        running = zero(self.currency)
        for entry in self.for_line(code, through_period):
            if entry.delivered is None:
                continue
            if not entry.is_eligible(options):
                continue
            running = running + entry.delivered
        return running

    def ineligible_to_date(self, code, through_period, options=None):
        """Return the deliveries excluded by the eligibility rules."""
        options = options or StoredOptions()
        running = zero(self.currency)
        for entry in self.for_line(code, through_period):
            if entry.delivered is None or entry.is_eligible(options):
                continue
            running = running + entry.delivered
        return running

    def converted_to_date(self, code, through_period):
        """Return the value explicitly converted into work in place."""
        running = zero(self.currency)
        for entry in self.for_line(code, through_period):
            if entry.converted is None:
                continue
            running = running + entry.converted
        return running

    def to_list(self):
        """Return the ledger as plain data."""
        return [
            entry.to_dict()
            for entry in sorted(self.entries, key=lambda item: (item.period, item.code))
        ]

    @classmethod
    def from_list(cls, data, currency="USD"):
        """Rebuild a ledger from :meth:`to_list` output."""
        return cls([StoredEntry.from_dict(entry, currency) for entry in data], currency)

    def __len__(self):
        return len(self.entries)

    def __iter__(self):
        return iter(sorted(self.entries, key=lambda item: (item.period, item.code)))

    def __repr__(self):
        return "StoredLedger(%d entries)" % (len(self.entries),)


def stored_on_hand(line, ledger, period, completion, options=None, trace=NULL_TRACE):
    """Return the stored-materials value billable on a line this period.

    The conversion rule decides how much of what was delivered has already
    become work in place:

    >>> from ..model.sov import SOVLine
    >>> line = SOVLine("26200", "Switchgear", money("70000"), stored_eligible=True)
    >>> ledger = StoredLedger()
    >>> ledger.record(StoredEntry("26200", 1, delivered=money("48000")))
    >>> str(stored_on_hand(line, ledger, 1, Rate("0.25")))
    '$48,000.00'
    >>> options = StoredOptions(conversion="proportional")
    >>> str(stored_on_hand(line, ledger, 1, Rate("0.25"), options))
    '$36,000.00'

    A cap is applied against the line's scheduled value after conversion:

    >>> capped = StoredOptions(cap="50%")
    >>> str(stored_on_hand(line, ledger, 1, Rate("0"), capped))
    '$35,000.00'
    """
    options = options or StoredOptions()
    currency = line.scheduled_value.currency
    if not line.stored_eligible:
        return zero(currency)
    delivered = ledger.delivered_to_date(line.code, period, options)
    if delivered.is_zero():
        return zero(currency)
    if options.conversion == "explicit":
        converted = ledger.converted_to_date(line.code, period)
    elif options.conversion == "proportional":
        fraction = completion.value if isinstance(completion, Rate) else Decimal(str(completion))
        converted = delivered * min(Decimal(1), max(Decimal(0), fraction))
    else:
        fraction = completion.value if isinstance(completion, Rate) else Decimal(str(completion))
        converted = delivered if fraction >= 1 else zero(currency)
    on_hand = delivered - converted
    if on_hand.is_negative():
        raise DataError(
            "line %s has converted more stored material than was delivered" % (line.code,)
        )
    if options.cap is not None:
        ceiling = line.scheduled_value * options.cap.value
        if on_hand > ceiling:
            trace.record(
                "stored",
                line.code,
                "capped at %s of the scheduled value" % (options.cap,),
                {"on_hand": str(on_hand.amount), "cap": str(ceiling.amount)},
            )
            return ceiling
    trace.record(
        "stored",
        line.code,
        "%s on hand under the %s rule" % (on_hand, options.conversion),
        {"delivered": str(delivered.amount), "converted": str(converted.amount)},
    )
    return on_hand
