"""What the field reported, before any policy is applied to it.

A progress observation is a claim: this line is thirty-five percent complete,
or four hundred cubic yards were placed, or eighty thousand dollars of work was
done this period.  The claim is recorded exactly as it was made, including
*which* of those three shapes it came in and whether the figure is cumulative
or incremental, because converting too early destroys the only evidence of what
was actually reported.

The distinction that costs money is cumulative versus incremental.  A
superintendent who writes "45" in the percent column of a line already billed
to forty means one of two things -- forty-five percent complete, or five percent
more -- and a system that assumes the wrong one bills the job to a hundred and
forty percent by the end.
"""

from decimal import Decimal

from ..core.ids import normalise_code
from ..core.money import Money, money, zero
from ..core.numbers import decimal_from
from ..core.percent import Rate, rate_text
from ..core.quantity import Quantity, quantity
from ..errors import DataError, InputError, SequenceError

__all__ = ["OBSERVATION_SHAPES", "BASES", "ProgressEntry", "ProgressLedger"]

OBSERVATION_SHAPES = ("percent", "value", "quantity", "milestone")
BASES = ("to_date", "this_period")


class ProgressEntry:
    """One reported observation about one line in one period.

    >>> entry = ProgressEntry("03300", 2, percent="35%")
    >>> str(entry.percent)
    '35%'
    >>> entry.basis
    'to_date'
    >>> ProgressEntry("03300", 3, value=money("12000"), basis="this_period").shape
    'value'
    """

    __slots__ = (
        "code",
        "period",
        "shape",
        "basis",
        "percent",
        "value",
        "installed",
        "achieved",
        "reported_by",
        "reference",
        "note",
    )

    def __init__(
        self,
        code,
        period,
        percent=None,
        value=None,
        installed=None,
        achieved=None,
        basis="to_date",
        reported_by="",
        reference="",
        note="",
    ):
        self.code = normalise_code(code)
        self.period = int(period)
        if self.period < 1:
            raise InputError("period numbers start at 1, got %r" % (period,))
        given = [name for name, item in (
            ("percent", percent),
            ("value", value),
            ("quantity", installed),
            ("milestone", achieved),
        ) if item is not None]
        if len(given) != 1:
            raise InputError(
                "a progress entry reports exactly one of percent, value, quantity or "
                "milestone; line %s period %d gave %d" % (self.code, self.period, len(given))
            )
        self.shape = given[0]
        if str(basis) not in BASES:
            raise InputError("unknown basis %r; known: %s" % (basis, ", ".join(BASES)))
        self.basis = str(basis)
        self.percent = Rate.parse(percent) if percent is not None else None
        if value is not None and not isinstance(value, Money):
            raise InputError("a value observation must be Money")
        self.value = value
        self.installed = quantity(installed) if installed is not None else None
        self.achieved = bool(achieved) if achieved is not None else None
        if self.shape == "milestone":
            self.basis = "to_date"
        self.reported_by = str(reported_by)
        self.reference = str(reference)
        self.note = str(note)
        if self.percent is not None and self.percent.value < 0 and self.is_cumulative():
            raise DataError(
                "line %s reports negative progress to date; a correction is reported "
                "as a negative figure on a this_period basis" % (self.code,)
            )
        if self.installed is not None and self.installed.amount < 0 and self.is_cumulative():
            raise DataError("line %s reports a negative quantity to date" % (self.code,))

    def is_cumulative(self):
        """Return True when the figure is a to-date figure."""
        return self.basis == "to_date"

    def to_dict(self):
        """Return the entry as plain data."""
        data = {
            "code": self.code,
            "period": self.period,
            "shape": self.shape,
            "basis": self.basis,
            "reported_by": self.reported_by,
            "reference": self.reference,
            "note": self.note,
        }
        if self.percent is not None:
            data["percent"] = rate_text(self.percent)
        if self.value is not None:
            data["value"] = str(self.value.amount)
        if self.installed is not None:
            data["installed"] = str(self.installed.amount)
            data["unit"] = str(self.installed.unit)
        if self.achieved is not None:
            data["achieved"] = self.achieved
        return data

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild an entry from :meth:`to_dict` output."""
        installed = None
        if data.get("installed") is not None:
            installed = Quantity(data["installed"], data.get("unit", "ea"))
        return cls(
            data["code"],
            data["period"],
            data.get("percent"),
            money(data["value"], currency) if data.get("value") is not None else None,
            installed,
            data.get("achieved"),
            data.get("basis", "to_date"),
            data.get("reported_by", ""),
            data.get("reference", ""),
            data.get("note", ""),
        )

    def __eq__(self, other):
        return (
            isinstance(other, ProgressEntry)
            and other.code == self.code
            and other.period == self.period
            and other.to_dict() == self.to_dict()
        )

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("ProgressEntry", self.code, self.period, self.shape))

    def __str__(self):
        if self.shape == "percent":
            reported = str(self.percent)
        elif self.shape == "value":
            reported = str(self.value)
        elif self.shape == "quantity":
            reported = str(self.installed)
        else:
            reported = "achieved" if self.achieved else "not achieved"
        return "%s period %d: %s (%s)" % (self.code, self.period, reported, self.basis)

    def __repr__(self):
        return "ProgressEntry(%r, %d, %r)" % (self.code, self.period, self.shape)


class ProgressLedger:
    """Every observation on a contract, addressable by line and period.

    >>> ledger = ProgressLedger()
    >>> ledger.record(ProgressEntry("03300", 1, percent="20%"))
    >>> ledger.record(ProgressEntry("03300", 2, percent="55%"))
    >>> str(ledger.latest_percent("03300", 2))
    '55%'
    >>> str(ledger.latest_percent("03300", 1))
    '20%'
    >>> [entry.period for entry in ledger.for_line("03300")]
    [1, 2]
    """

    def __init__(self, entries=(), currency="USD"):
        self.currency = currency
        self.entries = []
        self._index = {}
        for entry in entries:
            self.record(entry)

    def record(self, entry):
        """Add an observation, refusing a second one for the same line-period."""
        key = (entry.code, entry.period)
        if key in self._index:
            raise DataError(
                "line %s already has an observation in period %d" % entry_key(key)
            )
        self.entries.append(entry)
        self._index[key] = entry

    def replace(self, entry):
        """Replace an observation, which a revised application legitimately does."""
        key = (entry.code, entry.period)
        if key in self._index:
            self.entries = [item for item in self.entries if (item.code, item.period) != key]
        self.entries.append(entry)
        self._index[key] = entry

    def get(self, code, period, default=None):
        """Return the observation for a line and period, or ``default``."""
        return self._index.get((normalise_code(code), int(period)), default)

    def require(self, code, period):
        """Return the observation for a line and period, raising when missing."""
        entry = self.get(code, period)
        if entry is None:
            raise DataError("no observation for line %s in period %d" % (code, int(period)))
        return entry

    def for_line(self, code, through_period=None):
        """Return a line's observations in period order."""
        code = normalise_code(code)
        entries = [entry for entry in self.entries if entry.code == code]
        if through_period is not None:
            entries = [entry for entry in entries if entry.period <= int(through_period)]
        return sorted(entries, key=lambda entry: entry.period)

    def for_period(self, period):
        """Return a period's observations in line order."""
        period = int(period)
        return sorted(
            (entry for entry in self.entries if entry.period == period),
            key=lambda entry: entry.code,
        )

    def codes(self):
        """Return the distinct line codes observed, in code order."""
        return sorted({entry.code for entry in self.entries})

    def periods(self):
        """Return the distinct periods observed, in order."""
        return sorted({entry.period for entry in self.entries})

    def latest_percent(self, code, through_period):
        """Return the to-date percentage implied by a line's observations.

        Cumulative entries replace the running figure; incremental ones add to
        it.  Mixing the two on one line is allowed and is exactly why the
        running figure is computed rather than read off the last entry.
        """
        running = Rate(Decimal(0))
        for entry in self.for_line(code, through_period):
            if entry.shape != "percent":
                continue
            if entry.is_cumulative():
                running = entry.percent
            else:
                running = Rate(running.value + entry.percent.value)
        return running

    def cumulative_value(self, code, through_period):
        """Return the to-date value implied by value-shaped observations."""
        running = zero(self.currency)
        for entry in self.for_line(code, through_period):
            if entry.shape != "value":
                continue
            if entry.is_cumulative():
                running = entry.value
            else:
                running = running + entry.value
        return running

    def cumulative_quantity(self, code, through_period):
        """Return the to-date measured quantity for a unit-price line."""
        running = None
        for entry in self.for_line(code, through_period):
            if entry.shape != "quantity":
                continue
            if entry.is_cumulative() or running is None:
                running = entry.installed
            else:
                running = running + entry.installed
        if running is None:
            raise DataError("line %s has no measured quantity" % (normalise_code(code),))
        return running

    def milestone_achieved(self, code, through_period):
        """Return True when a milestone observation says the event happened."""
        achieved = False
        for entry in self.for_line(code, through_period):
            if entry.shape == "milestone":
                achieved = bool(entry.achieved)
        return achieved

    def check_monotonic(self, code):
        """Raise when a line's cumulative percentages go backwards.

        Progress does go backwards in practice -- a line over-billed in one
        period is corrected in the next -- so this is a check a caller asks
        for, not one the ledger enforces.
        """
        previous = None
        for entry in self.for_line(code):
            if entry.shape != "percent" or not entry.is_cumulative():
                continue
            if previous is not None and entry.percent.value < previous.value:
                raise SequenceError(
                    "line %s falls from %s to %s at period %d"
                    % (entry.code, previous, entry.percent, entry.period)
                )
            previous = entry.percent

    def to_list(self):
        """Return the ledger as plain data, ordered by period then line."""
        return [
            entry.to_dict()
            for entry in sorted(self.entries, key=lambda item: (item.period, item.code))
        ]

    @classmethod
    def from_list(cls, data, currency="USD"):
        """Rebuild a ledger from :meth:`to_list` output."""
        return cls([ProgressEntry.from_dict(entry, currency) for entry in data], currency)

    def __len__(self):
        return len(self.entries)

    def __iter__(self):
        return iter(sorted(self.entries, key=lambda item: (item.period, item.code)))

    def __repr__(self):
        return "ProgressLedger(%d entries)" % (len(self.entries),)


def entry_key(key):
    """Return a printable form of a ledger key, used in error messages.

    >>> entry_key(("03300", 2))
    ('03300', 2)
    """
    return (key[0], key[1])
