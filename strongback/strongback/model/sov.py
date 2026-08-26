"""The schedule of values: the list of lines every dollar is billed against.

The schedule is the contract's own breakdown of its price, and it is the object
every other part of this package points at.  Progress is recorded per line,
retainage is computed per line, a change order adds lines to it, and the
continuation sheet is nothing but the schedule with six more columns.

Two properties of a schedule are worth stating because so much depends on them:
the scheduled values sum to the contract sum, and a line's identity is its
code.  When a change order revises an existing line rather than adding one, the
revision is still recorded as a separate line so that the original scheduled
value stays visible; a line that quietly changes size makes every prior
application unauditable.
"""

from ..core.ids import code_sort_key, normalise_code, normalise_id
from ..core.money import Money, money, zero
from ..core.percent import Rate, rate_text
from ..core.quantity import Quantity, quantity
from ..errors import DataError, InputError, UnknownLine

__all__ = ["LineKind", "SOVLine", "ScheduleOfValues", "LINE_KINDS"]

LINE_KINDS = ("lump_sum", "unit_price", "allowance", "milestone")


class LineKind:
    """How a line's earned value is measured.

    ``lump_sum`` lines are billed on a judged percentage, ``unit_price`` lines
    on measured installed quantity, ``allowance`` lines against documented
    cost, and ``milestone`` lines all-or-nothing on an event.

    >>> LineKind("unit_price").measured_by_quantity()
    True
    """

    __slots__ = ("name",)

    def __init__(self, name):
        text = str(name).strip().lower().replace(" ", "_").replace("-", "_")
        if text not in LINE_KINDS:
            raise InputError("unknown line kind %r; known: %s" % (name, ", ".join(LINE_KINDS)))
        self.name = text

    def measured_by_quantity(self):
        """Return True when progress is a measured quantity, not a judgement."""
        return self.name == "unit_price"

    def is_all_or_nothing(self):
        """Return True when partial progress is not billable by default."""
        return self.name == "milestone"

    def __eq__(self, other):
        if isinstance(other, LineKind):
            return other.name == self.name
        if isinstance(other, str):
            return self.name == str(other).strip().lower()
        return NotImplemented

    def __ne__(self, other):
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    def __hash__(self):
        return hash(("LineKind", self.name))

    def __str__(self):
        return self.name

    def __repr__(self):
        return "LineKind(%r)" % (self.name,)


class SOVLine:
    """One line of the schedule of values.

    >>> line = SOVLine("03300", "Slab on grade", money("120000"), cost_code="03300")
    >>> line.scheduled_value
    Money('120000', 'USD')
    >>> line.is_change_order()
    False
    >>> unit = SOVLine("31200", "Excavation", money("50000"), kind="unit_price",
    ...                unit_quantity=quantity("2500", "cy"), unit_rate=money("20"))
    >>> unit.value_of(quantity("1000", "cy"))
    Money('20000', 'USD')
    """

    __slots__ = (
        "code",
        "description",
        "scheduled_value",
        "cost_code",
        "kind",
        "unit_quantity",
        "unit_rate",
        "stored_eligible",
        "retainage_rate",
        "origin",
        "change_order",
        "group",
        "sequence",
        "notes",
    )

    def __init__(
        self,
        code,
        description,
        scheduled_value,
        cost_code="",
        kind="lump_sum",
        unit_quantity=None,
        unit_rate=None,
        stored_eligible=False,
        retainage_rate=None,
        origin="base",
        change_order="",
        group="",
        sequence=0,
        notes="",
    ):
        self.code = normalise_code(code)
        self.description = str(description).strip()
        if not isinstance(scheduled_value, Money):
            raise InputError("line %s scheduled value must be Money" % (self.code,))
        self.scheduled_value = scheduled_value
        self.cost_code = normalise_code(cost_code) if cost_code else ""
        self.kind = kind if isinstance(kind, LineKind) else LineKind(kind)
        self.unit_quantity = quantity(unit_quantity) if unit_quantity is not None else None
        self.unit_rate = unit_rate
        if self.unit_rate is not None and not isinstance(self.unit_rate, Money):
            raise InputError("line %s unit rate must be Money" % (self.code,))
        if self.kind.measured_by_quantity():
            if self.unit_quantity is None or self.unit_rate is None:
                raise DataError(
                    "unit-price line %s needs both a quantity and a rate" % (self.code,)
                )
        self.stored_eligible = bool(stored_eligible)
        self.retainage_rate = Rate.parse(retainage_rate) if retainage_rate is not None else None
        self.origin = normalise_id(origin, "origin") if origin else "base"
        self.change_order = normalise_id(change_order, "change order") if change_order else ""
        self.group = str(group)
        self.sequence = int(sequence)
        self.notes = str(notes)

    def is_change_order(self):
        """Return True when the line came from a change order."""
        return self.origin != "base"

    def is_credit(self):
        """Return True when the line reduces the contract sum."""
        return self.scheduled_value.is_negative()

    def value_of(self, measured):
        """Return the value of a measured quantity on a unit-price line."""
        if not self.kind.measured_by_quantity():
            raise DataError("line %s is not a unit-price line" % (self.code,))
        measured = quantity(measured)
        if measured.unit != self.unit_quantity.unit:
            raise DataError(
                "line %s is measured in %s, not %s"
                % (self.code, self.unit_quantity.unit, measured.unit)
            )
        return self.unit_rate * measured.amount

    def full_quantity_value(self):
        """Return the scheduled value implied by quantity times rate."""
        if not self.kind.measured_by_quantity():
            return self.scheduled_value
        return self.unit_rate * self.unit_quantity.amount

    def effective_retainage_rate(self, default):
        """Return this line's retainage rate, falling back to the default."""
        if self.retainage_rate is not None:
            return self.retainage_rate
        return Rate.parse(default)

    def with_scheduled_value(self, value):
        """Return a copy of the line at a different scheduled value."""
        clone = self.copy()
        clone.scheduled_value = value
        return clone

    def copy(self):
        """Return an independent copy of the line."""
        return SOVLine(
            self.code,
            self.description,
            self.scheduled_value,
            self.cost_code,
            self.kind,
            self.unit_quantity,
            self.unit_rate,
            self.stored_eligible,
            self.retainage_rate,
            self.origin,
            self.change_order,
            self.group,
            self.sequence,
            self.notes,
        )

    def to_dict(self):
        """Return the line as plain data."""
        data = {
            "code": self.code,
            "description": self.description,
            "scheduled_value": str(self.scheduled_value.amount),
            "cost_code": self.cost_code,
            "kind": str(self.kind),
            "stored_eligible": self.stored_eligible,
            "origin": self.origin,
            "change_order": self.change_order,
            "group": self.group,
            "sequence": self.sequence,
            "notes": self.notes,
        }
        if self.unit_quantity is not None:
            data["unit_quantity"] = str(self.unit_quantity.amount)
            data["unit"] = str(self.unit_quantity.unit)
        if self.unit_rate is not None:
            data["unit_rate"] = str(self.unit_rate.amount)
        if self.retainage_rate is not None:
            data["retainage_rate"] = rate_text(self.retainage_rate)
        return data

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild a line from :meth:`to_dict` output."""
        unit_quantity = None
        if data.get("unit_quantity") is not None:
            unit_quantity = Quantity(data["unit_quantity"], data.get("unit", "ea"))
        unit_rate = money(data["unit_rate"], currency) if data.get("unit_rate") is not None else None
        return cls(
            data["code"],
            data.get("description", ""),
            money(data["scheduled_value"], currency),
            data.get("cost_code", ""),
            data.get("kind", "lump_sum"),
            unit_quantity,
            unit_rate,
            data.get("stored_eligible", False),
            data.get("retainage_rate"),
            data.get("origin", "base"),
            data.get("change_order", ""),
            data.get("group", ""),
            data.get("sequence", 0),
            data.get("notes", ""),
        )

    def __eq__(self, other):
        return isinstance(other, SOVLine) and other.code == self.code

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("SOVLine", self.code))

    def __str__(self):
        return "%s %s %s" % (self.code, self.description, self.scheduled_value)

    def __repr__(self):
        return "SOVLine(%r, %r)" % (self.code, str(self.scheduled_value.amount))


class ScheduleOfValues:
    """The ordered set of lines a contract is billed against.

    >>> sov = ScheduleOfValues([
    ...     SOVLine("01000", "General conditions", money("60000")),
    ...     SOVLine("03300", "Concrete", money("240000")),
    ... ])
    >>> str(sov.total())
    '$300,000.00'
    >>> sov.require("03300").description
    'Concrete'
    >>> len(sov.add(SOVLine("09900", "Paint", money("10000"))))
    3
    """

    def __init__(self, lines=(), currency="USD"):
        self.currency = currency
        self.lines = []
        self._index = {}
        for line in lines:
            self.add(line)

    def add(self, line):
        """Add a line, refusing a duplicate code, and return the schedule."""
        if line.code in self._index:
            raise DataError("schedule of values has line %s twice" % (line.code,))
        if not line.sequence:
            line.sequence = len(self.lines) + 1
        self.lines.append(line)
        self._index[line.code] = line
        return self

    def get(self, code, default=None):
        """Return a line by code, or ``default``."""
        return self._index.get(normalise_code(code), default)

    def require(self, code):
        """Return a line by code, raising :class:`UnknownLine` when missing."""
        line = self.get(code)
        if line is None:
            raise UnknownLine("no schedule-of-values line %r" % (code,))
        return line

    def codes(self):
        """Return every line code in schedule order."""
        return [line.code for line in self.ordered()]

    def ordered(self):
        """Return the lines in sequence order, ties broken by code."""
        return sorted(self.lines, key=lambda line: (line.sequence, code_sort_key(line.code)))

    def in_code_order(self):
        """Return the lines in specification-number order."""
        return sorted(self.lines, key=lambda line: code_sort_key(line.code))

    def total(self):
        """Return the sum of every scheduled value."""
        running = zero(self.currency)
        for line in self.lines:
            running = running + line.scheduled_value
        return running

    def base_total(self):
        """Return the sum of the original, pre-change-order lines."""
        running = zero(self.currency)
        for line in self.lines:
            if not line.is_change_order():
                running = running + line.scheduled_value
        return running

    def change_order_total(self):
        """Return the sum of the lines added by change orders."""
        running = zero(self.currency)
        for line in self.lines:
            if line.is_change_order():
                running = running + line.scheduled_value
        return running

    def of_kind(self, kind):
        """Return the lines of one kind."""
        kind = kind if isinstance(kind, LineKind) else LineKind(kind)
        return [line for line in self.ordered() if line.kind == kind]

    def for_cost_code(self, code):
        """Return the lines mapped to a cost code."""
        code = normalise_code(code)
        return [line for line in self.ordered() if line.cost_code == code]

    def from_change_order(self, identifier):
        """Return the lines added by one change order."""
        identifier = normalise_id(identifier, "change order")
        return [line for line in self.ordered() if line.change_order == identifier]

    def groups(self):
        """Return the distinct group labels in schedule order."""
        seen = []
        for line in self.ordered():
            if line.group and line.group not in seen:
                seen.append(line.group)
        return seen

    def stored_eligible_lines(self):
        """Return the lines that may carry stored materials."""
        return [line for line in self.ordered() if line.stored_eligible]

    def validate(self):
        """Return a list of problems with the schedule, empty when sound."""
        problems = []
        for line in self.ordered():
            if line.scheduled_value.currency != self.lines[0].scheduled_value.currency:
                problems.append("line %s uses a different currency" % (line.code,))
            if line.kind.measured_by_quantity():
                implied = line.full_quantity_value()
                if implied != line.scheduled_value:
                    problems.append(
                        "line %s: quantity times rate is %s but the scheduled value is %s"
                        % (line.code, implied, line.scheduled_value)
                    )
            if not line.description:
                problems.append("line %s has no description" % (line.code,))
        return problems

    def copy(self):
        """Return an independent copy of the schedule."""
        return ScheduleOfValues([line.copy() for line in self.lines], self.currency)

    def with_lines(self, lines):
        """Return a copy with more lines appended."""
        clone = self.copy()
        for line in lines:
            clone.add(line.copy())
        return clone

    def to_list(self):
        """Return the schedule as plain data."""
        return [line.to_dict() for line in self.ordered()]

    @classmethod
    def from_list(cls, data, currency="USD"):
        """Rebuild a schedule from :meth:`to_list` output."""
        return cls([SOVLine.from_dict(entry, currency) for entry in data], currency)

    def __len__(self):
        return len(self.lines)

    def __iter__(self):
        return iter(self.ordered())

    def __contains__(self, code):
        return normalise_code(code) in self._index

    def __getitem__(self, code):
        return self.require(code)

    def __repr__(self):
        return "ScheduleOfValues(%d lines, %s)" % (len(self.lines), self.total())
