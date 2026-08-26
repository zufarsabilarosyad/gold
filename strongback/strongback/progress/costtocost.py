"""Cost-to-cost progress: percent complete measured by money spent.

A superintendent's percentage is a judgement.  Cost-to-cost is an arithmetic
alternative -- cost incurred over cost forecast -- and it is what the
work-in-progress report and most revenue recognition use.  The two disagree
routinely, and the disagreement is informative rather than a mistake: a line
eighty percent spent and sixty percent built is a line in trouble.

Nothing in this module bills anything.  It exists so the WIP package can say
what the job has really earned, against what has been billed for it.
"""

from ..core.ids import normalise_code
from ..core.money import Money, money, zero
from ..core.percent import Rate
from ..errors import DataError, InputError

__all__ = ["CostEntry", "CostLedger", "COST_CATEGORIES", "percent_by_cost"]

COST_CATEGORIES = ("labor", "material", "equipment", "subcontract", "other")


class CostEntry:
    """One posting of incurred cost against a cost code.

    >>> entry = CostEntry("03300", 2, money("18400"), "labor")
    >>> entry.category
    'labor'
    """

    __slots__ = ("code", "period", "amount", "category", "reference", "committed")

    def __init__(self, code, period, amount, category="other", reference="", committed=False):
        self.code = normalise_code(code)
        self.period = int(period)
        if not isinstance(amount, Money):
            raise InputError("a cost entry needs a Money amount")
        self.amount = amount
        category = str(category).strip().lower()
        if category not in COST_CATEGORIES:
            raise InputError(
                "unknown cost category %r; known: %s" % (category, ", ".join(COST_CATEGORIES))
            )
        self.category = category
        self.reference = str(reference)
        self.committed = bool(committed)

    def to_dict(self):
        """Return the entry as plain data."""
        return {
            "code": self.code,
            "period": self.period,
            "amount": str(self.amount.amount),
            "category": self.category,
            "reference": self.reference,
            "committed": self.committed,
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild an entry from :meth:`to_dict` output."""
        return cls(
            data["code"],
            data["period"],
            money(data["amount"], currency),
            data.get("category", "other"),
            data.get("reference", ""),
            data.get("committed", False),
        )

    def __repr__(self):
        return "CostEntry(%r, period=%d, %s)" % (self.code, self.period, self.amount)


class CostLedger:
    """Incurred and committed cost by code and period.

    >>> ledger = CostLedger()
    >>> ledger.record(CostEntry("03300", 1, money("40000"), "labor"))
    >>> ledger.record(CostEntry("03300", 2, money("35000"), "material"))
    >>> str(ledger.incurred_to_date("03300", 2))
    '$75,000.00'
    >>> str(ledger.incurred_to_date("03300", 1))
    '$40,000.00'
    >>> str(ledger.by_category("03300", 2)["labor"])
    '$40,000.00'
    """

    def __init__(self, entries=(), currency="USD"):
        self.currency = currency
        self.entries = []
        for entry in entries:
            self.record(entry)

    def record(self, entry):
        """Add a cost posting."""
        if not isinstance(entry, CostEntry):
            raise InputError("expected a CostEntry")
        self.entries.append(entry)

    def for_code(self, code, through_period=None, include_committed=False):
        """Return the postings on a code in period order."""
        code = normalise_code(code)
        entries = [entry for entry in self.entries if entry.code == code]
        if through_period is not None:
            entries = [entry for entry in entries if entry.period <= int(through_period)]
        if not include_committed:
            entries = [entry for entry in entries if not entry.committed]
        return sorted(entries, key=lambda entry: (entry.period, entry.category))

    def codes(self):
        """Return the cost codes posted to, in code order."""
        return sorted({entry.code for entry in self.entries})

    def incurred_to_date(self, code, through_period=None):
        """Return actual cost incurred on a code through a period."""
        running = zero(self.currency)
        for entry in self.for_code(code, through_period):
            running = running + entry.amount
        return running

    def committed_to_date(self, code, through_period=None):
        """Return incurred plus committed cost on a code."""
        running = zero(self.currency)
        for entry in self.for_code(code, through_period, include_committed=True):
            running = running + entry.amount
        return running

    def by_category(self, code, through_period=None):
        """Return a mapping of category to incurred cost."""
        totals = {category: zero(self.currency) for category in COST_CATEGORIES}
        for entry in self.for_code(code, through_period):
            totals[entry.category] = totals[entry.category] + entry.amount
        return totals

    def total_incurred(self, through_period=None):
        """Return the total incurred cost across every code."""
        running = zero(self.currency)
        for code in self.codes():
            running = running + self.incurred_to_date(code, through_period)
        return running

    def to_list(self):
        """Return the ledger as plain data."""
        return [
            entry.to_dict()
            for entry in sorted(self.entries, key=lambda item: (item.period, item.code, item.category))
        ]

    @classmethod
    def from_list(cls, data, currency="USD"):
        """Rebuild a ledger from :meth:`to_list` output."""
        return cls([CostEntry.from_dict(entry, currency) for entry in data], currency)

    def __len__(self):
        return len(self.entries)

    def __iter__(self):
        return iter(sorted(self.entries, key=lambda item: (item.period, item.code)))

    def __repr__(self):
        return "CostLedger(%d entries)" % (len(self.entries),)


def percent_by_cost(incurred, forecast):
    """Return incurred over forecast cost as a rate, capped at a hundred.

    A forecast that has been overrun does not make a line more than complete;
    it makes the forecast wrong.  The uncapped figure is available by dividing
    directly when a report wants to show the overrun.

    >>> str(percent_by_cost(money("75000"), money("100000")))
    '75%'
    >>> str(percent_by_cost(money("120000"), money("100000")))
    '100%'
    """
    if not isinstance(incurred, Money) or not isinstance(forecast, Money):
        raise InputError("percent by cost needs two Money amounts")
    if forecast.is_zero():
        raise DataError("cannot measure progress against a zero cost forecast")
    fraction = incurred.ratio_to(forecast)
    if fraction > 1:
        return Rate(1)
    if fraction < 0:
        return Rate(0)
    return Rate(fraction)
