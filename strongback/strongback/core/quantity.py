"""Quantities with units, for the unit-price lines of a schedule of values.

Unit-price work -- cubic yards of excavation, linear feet of curb -- is billed
on measured installed quantity rather than on a percentage judgement, and the
two do not mix.  A :class:`Quantity` carries its unit so that a line measured
in tons cannot be added to one measured in loads without somebody noticing.
"""

from decimal import Decimal

from ..errors import InputError
from .numbers import decimal_from, quantize

__all__ = ["Unit", "Quantity", "quantity", "UNITS"]

UNITS = {
    "ea": "each",
    "ls": "lump sum",
    "lf": "linear foot",
    "sf": "square foot",
    "sy": "square yard",
    "cy": "cubic yard",
    "cf": "cubic foot",
    "ton": "ton",
    "hr": "hour",
    "day": "day",
    "gal": "gallon",
    "mbf": "thousand board feet",
}


class Unit:
    """A unit of measure, normalised to a short lowercase code.

    >>> Unit("CY").name
    'cubic yard'
    >>> Unit("cy") == Unit("CY")
    True
    """

    __slots__ = ("code", "name")

    def __init__(self, code, name=""):
        code = str(code).strip().lower()
        if not code:
            raise InputError("a unit needs a code")
        if not code.replace("-", "").isalnum():
            raise InputError("a unit code is alphanumeric, got %r" % (code,))
        self.code = code
        self.name = str(name) or UNITS.get(code, code)

    def __eq__(self, other):
        return isinstance(other, Unit) and other.code == self.code

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("Unit", self.code))

    def __str__(self):
        return self.code

    def __repr__(self):
        return "Unit(%r)" % (self.code,)


class Quantity:
    """A decimal amount of a unit.

    >>> quantity("120.5", "cy") + quantity("9.5", "CY")
    Quantity('130.0', 'cy')
    >>> quantity("10", "ton").is_zero()
    False
    """

    __slots__ = ("amount", "unit")

    def __init__(self, amount, unit="ea"):
        self.amount = decimal_from(amount, "quantity")
        self.unit = unit if isinstance(unit, Unit) else Unit(unit)

    def _same(self, other, operation):
        if not isinstance(other, Quantity):
            raise InputError("cannot %s %r and a quantity" % (operation, other))
        if other.unit != self.unit:
            raise InputError(
                "cannot %s %s and %s" % (operation, self.unit, other.unit)
            )
        return other

    def __add__(self, other):
        other = self._same(other, "add")
        return Quantity(self.amount + other.amount, self.unit)

    def __radd__(self, other):
        if other == 0:
            return self
        return self.__add__(other)

    def __sub__(self, other):
        other = self._same(other, "subtract")
        return Quantity(self.amount - other.amount, self.unit)

    def __mul__(self, factor):
        return Quantity(self.amount * decimal_from(factor, "factor"), self.unit)

    __rmul__ = __mul__

    def __eq__(self, other):
        if not isinstance(other, Quantity):
            return NotImplemented
        return self.unit == other.unit and self.amount == other.amount

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __lt__(self, other):
        return self.amount < self._same(other, "compare").amount

    def __le__(self, other):
        return self.amount <= self._same(other, "compare").amount

    def __gt__(self, other):
        return self.amount > self._same(other, "compare").amount

    def __ge__(self, other):
        return self.amount >= self._same(other, "compare").amount

    def __hash__(self):
        return hash(("Quantity", self.unit.code, self.amount))

    def __bool__(self):
        return self.amount != 0

    def is_zero(self):
        """Return True when the amount is zero."""
        return self.amount == 0

    def rounded(self, places=3):
        """Return the quantity rounded for a measurement sheet."""
        return Quantity(quantize(self.amount, places), self.unit)

    def ratio_to(self, other):
        """Return this quantity over another of the same unit, as a Decimal.

        >>> quantity("50", "cy").ratio_to(quantity("200", "cy"))
        Decimal('0.25')
        """
        other = self._same(other, "compare")
        if other.amount == 0:
            raise InputError("cannot take a ratio to a zero quantity")
        return self.amount / other.amount

    def format(self, places=2):
        """Render the quantity with its unit code.

        >>> quantity("1250.5", "lf").format()
        '1,250.50 lf'
        """
        value = quantize(self.amount, places)
        return "{:,.{places}f} {unit}".format(value, places=places, unit=self.unit.code)

    def __str__(self):
        return self.format()

    def __repr__(self):
        return "Quantity(%r, %r)" % (str(self.amount), self.unit.code)


def quantity(amount, unit="ea"):
    """Shorthand constructor.

    >>> quantity(3)
    Quantity('3', 'ea')
    """
    if isinstance(amount, Quantity):
        return amount
    return Quantity(amount if not isinstance(amount, Decimal) else amount, unit)
