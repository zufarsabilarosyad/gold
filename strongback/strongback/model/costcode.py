"""Cost codes: the accounting spine a schedule of values hangs off.

A schedule-of-values line is what the owner sees; a cost code is what the
contractor's accounting sees.  They are usually not one-to-one -- a single
billing line for "concrete" covers formwork, reinforcing, placement and
finishing codes -- and the work-in-progress report needs the mapping to say
what percentage complete a line really is by cost.
"""

from ..core.ids import code_sort_key, normalise_code
from ..core.money import Money, money, zero
from ..errors import DataError, InputError

__all__ = ["CostCode", "CostCodeTable", "DIVISIONS", "division_of"]

DIVISIONS = {
    "01": "General Requirements",
    "02": "Existing Conditions",
    "03": "Concrete",
    "04": "Masonry",
    "05": "Metals",
    "06": "Wood, Plastics and Composites",
    "07": "Thermal and Moisture Protection",
    "08": "Openings",
    "09": "Finishes",
    "10": "Specialties",
    "11": "Equipment",
    "12": "Furnishings",
    "13": "Special Construction",
    "14": "Conveying Equipment",
    "21": "Fire Suppression",
    "22": "Plumbing",
    "23": "Heating, Ventilating and Air Conditioning",
    "26": "Electrical",
    "27": "Communications",
    "31": "Earthwork",
    "32": "Exterior Improvements",
    "33": "Utilities",
}


def division_of(code):
    """Return the division name for a code, or an empty string.

    >>> division_of("03300")
    'Concrete'
    >>> division_of("99999")
    ''
    """
    text = normalise_code(code)
    return DIVISIONS.get(text[:2], "")


class CostCode:
    """A budget line: a code, a description, and the money budgeted to it.

    >>> code = CostCode("03300", "Cast-in-place concrete", money("250000"))
    >>> code.division
    'Concrete'
    >>> code.committed_ratio(money("125000"))
    Decimal('0.5')
    """

    __slots__ = ("code", "description", "budget", "category", "labor_budget")

    def __init__(self, code, description="", budget=None, category="", labor_budget=None):
        self.code = normalise_code(code)
        self.description = str(description)
        self.budget = budget if budget is not None else zero()
        if not isinstance(self.budget, Money):
            raise InputError("cost code %s budget must be Money" % (self.code,))
        if self.budget.is_negative():
            raise DataError("cost code %s has a negative budget" % (self.code,))
        self.category = str(category)
        self.labor_budget = labor_budget if labor_budget is not None else zero(self.budget.currency)

    @property
    def division(self):
        """Return the division name this code falls in."""
        return division_of(self.code)

    def committed_ratio(self, committed):
        """Return committed cost over budget as a decimal fraction."""
        if self.budget.is_zero():
            raise DataError("cost code %s has no budget to compare against" % (self.code,))
        return committed.ratio_to(self.budget)

    def to_dict(self):
        """Return the cost code as plain data."""
        return {
            "code": self.code,
            "description": self.description,
            "budget": str(self.budget.amount),
            "category": self.category,
            "labor_budget": str(self.labor_budget.amount),
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild a cost code from :meth:`to_dict` output."""
        return cls(
            data["code"],
            data.get("description", ""),
            money(data.get("budget", "0"), currency),
            data.get("category", ""),
            money(data.get("labor_budget", "0"), currency),
        )

    def __eq__(self, other):
        return isinstance(other, CostCode) and other.code == self.code

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("CostCode", self.code))

    def __str__(self):
        return "%s %s" % (self.code, self.description)

    def __repr__(self):
        return "CostCode(%r)" % (self.code,)


class CostCodeTable:
    """The project's cost codes, in specification order.

    >>> table = CostCodeTable()
    >>> table.add(CostCode("09900", "Painting", money("40000")))
    >>> table.add(CostCode("03300", "Concrete", money("250000")))
    >>> [code.code for code in table]
    ['03300', '09900']
    >>> str(table.total_budget())
    '$290,000.00'
    """

    def __init__(self, codes=()):
        self.codes = {}
        for code in codes:
            self.add(code)

    def add(self, code):
        """Add a cost code, refusing a duplicate."""
        if code.code in self.codes:
            raise DataError("cost code %s appears twice" % (code.code,))
        self.codes[code.code] = code

    def get(self, code, default=None):
        """Return a cost code, or ``default``."""
        return self.codes.get(normalise_code(code), default)

    def require(self, code):
        """Return a cost code, raising when it is missing."""
        found = self.get(code)
        if found is None:
            raise DataError("no cost code %r in this table" % (code,))
        return found

    def ordered(self):
        """Return the codes in specification order."""
        return [self.codes[key] for key in sorted(self.codes, key=code_sort_key)]

    def in_division(self, prefix):
        """Return the codes whose number starts with a prefix."""
        prefix = normalise_code(prefix)
        return [code for code in self.ordered() if code.code.startswith(prefix)]

    def total_budget(self):
        """Return the sum of every budget in the table."""
        running = zero()
        for code in self.ordered():
            running = running + code.budget
        return running

    def to_list(self):
        """Return the table as plain data."""
        return [code.to_dict() for code in self.ordered()]

    @classmethod
    def from_list(cls, data, currency="USD"):
        """Rebuild a table from :meth:`to_list` output."""
        return cls([CostCode.from_dict(entry, currency) for entry in data])

    def __len__(self):
        return len(self.codes)

    def __iter__(self):
        return iter(self.ordered())

    def __contains__(self, code):
        return normalise_code(code) in self.codes

    def __getitem__(self, code):
        return self.require(code)

    def __repr__(self):
        return "CostCodeTable(%d codes)" % (len(self.codes),)
