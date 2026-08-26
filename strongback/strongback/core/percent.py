"""Rates and percentages, kept as exact fractions rather than as percents.

A retainage rate is written ``10%`` on a contract and stored as ``0.10`` here.
The distinction earns its keep at the boundaries: ``Rate.parse("10%")`` and
``Rate("0.10")`` are the same rate, ``Rate(10)`` is refused as an obvious
mistake, and every report that prints a rate does the multiplication by a
hundred in exactly one place.
"""

from decimal import Decimal

from ..errors import InputError
from .numbers import decimal_from, quantize

__all__ = ["Rate", "rate", "rate_text", "ZERO_RATE", "FULL_RATE", "complement"]


class Rate:
    """An exact fraction, usually a retainage or interest rate.

    >>> Rate.parse("10%").as_percent()
    Decimal('10.00')
    >>> Rate("0.05") * 200
    Decimal('10.00')
    >>> Rate("0.10").complement()
    Rate('0.90')

    Progress above a hundred percent is a real reported figure, so it is
    representable; whether it may be billed is a policy question answered
    elsewhere.

    >>> str(Rate.parse("120%"))
    '120%'
    """

    __slots__ = ("value",)

    def __init__(self, value):
        value = decimal_from(value, "rate")
        if value < -10 or value > 10:
            raise InputError(
                "a rate is a fraction, not a percent: %s is out of range, and %s%% "
                "would be written Rate.parse(%r)" % (value, value, str(value) + "%")
            )
        self.value = value

    @classmethod
    def parse(cls, text):
        """Read ``'10%'``, ``'10'`` (with a percent sign implied) or ``'0.10'``.

        A bare number below one is read as a fraction; at or above one it is
        read as a percent, because nobody writes a hundred percent retainage.

        >>> Rate.parse("7.5%")
        Rate('0.075')
        >>> Rate.parse("0.075")
        Rate('0.075')
        """
        if isinstance(text, Rate):
            return text
        raw = str(text).strip()
        explicit_percent = raw.endswith("%")
        value = decimal_from(raw, "rate")
        if explicit_percent or abs(value) >= 1:
            value = value / Decimal(100)
        return cls(value)

    @classmethod
    def share(cls, value):
        """Read a share, where a bare number is always a fraction.

        :meth:`parse` guesses -- ``"10"`` means ten percent because nobody
        writes a rate of ten.  A share is different: ``1`` means the whole
        line, and guessing there would turn a wholly-let scope into one
        percent of it.  Only an explicit percent sign means percent.

        >>> Rate.share("1.0")
        Rate('1.0')
        >>> Rate.share("50%")
        Rate('0.5')
        """
        if isinstance(value, Rate):
            return value
        raw = str(value).strip()
        if raw.endswith("%"):
            return cls(decimal_from(raw, "share") / Decimal(100))
        return cls(decimal_from(raw, "share"))

    @classmethod
    def from_percent(cls, percent):
        """Build a rate from a percent figure.

        >>> Rate.from_percent(5)
        Rate('0.05')
        """
        return cls(decimal_from(percent, "percent") / Decimal(100))

    def as_percent(self, places=2):
        """Return the rate as a percent figure, for printing.

        >>> Rate("0.0725").as_percent()
        Decimal('7.25')
        """
        return quantize(self.value * Decimal(100), places)

    def complement(self):
        """Return ``1 - rate``, the share left after this one is withheld."""
        return Rate(Decimal(1) - self.value)

    def is_zero(self):
        """Return True for a zero rate."""
        return self.value == 0

    def __mul__(self, other):
        if hasattr(other, "amount"):
            return other * self.value
        return decimal_from(other, "operand") * self.value

    __rmul__ = __mul__

    def __eq__(self, other):
        if isinstance(other, Rate):
            return self.value == other.value
        if isinstance(other, (int, str, Decimal)):
            return self.value == decimal_from(other)
        return NotImplemented

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __lt__(self, other):
        return self.value < Rate.parse(other).value if not isinstance(other, Rate) else self.value < other.value

    def __gt__(self, other):
        return self.value > Rate.parse(other).value if not isinstance(other, Rate) else self.value > other.value

    def __le__(self, other):
        return not self.__gt__(other)

    def __ge__(self, other):
        return not self.__lt__(other)

    def __hash__(self):
        return hash(("Rate", self.value))

    def __bool__(self):
        return self.value != 0

    def __str__(self):
        text = str(self.as_percent())
        if text.endswith(".00"):
            text = text[:-3]
        return text + "%"

    def __repr__(self):
        return "Rate(%r)" % (str(self.value),)


ZERO_RATE = Rate(0)
FULL_RATE = Rate(1)


def rate(value):
    """Shorthand for :meth:`Rate.parse`.

    >>> rate("5%")
    Rate('0.05')
    """
    return Rate.parse(value)


def rate_text(value):
    """Return a rate as an exact percent string, for serialisation.

    Writing a rate as a bare fraction and reading it back through
    :meth:`Rate.parse` is not a round trip: ``1`` written for a hundred
    percent comes back as one percent, because parse has to guess what a bare
    number means.  An explicit percent sign removes the guess, and the
    multiplication by a hundred is exact in decimal, so nothing is lost.

    >>> rate_text(Rate("0.075"))
    '7.500%'
    >>> Rate.parse(rate_text(Rate("1"))) == Rate("1")
    True
    """
    value = value if isinstance(value, Rate) else Rate.parse(value)
    return "%s%%" % (value.value * Decimal(100),)


def complement(value):
    """Return the complement of a rate-like value.

    >>> complement("10%")
    Rate('0.9')
    """
    return rate(value).complement()
