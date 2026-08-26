"""Exact money, and the two rules the rest of the package leans on.

1. Amounts are :class:`~decimal.Decimal`.  A float never enters.
2. Rounding happens at a *stage* -- a named point in the run, usually the
   production of a document line -- and not on every intermediate product.

The second rule is why :class:`Money` keeps whatever precision arithmetic gave
it.  A continuation-sheet line is a scheduled value times a percentage, and
retainage is a rate times that product.  Rounding both leaves the sheet's
retainage column disagreeing with the summary's line 5 by a cent or two, which
is exactly the discrepancy an owner's accountant writes back about.
"""

from decimal import Decimal

from ..errors import CurrencyMismatch, InputError
from .numbers import HALF_UP, allocate, decimal_from, quantize

__all__ = ["Currency", "Money", "CURRENCIES", "currency_by_code", "money", "zero", "total"]


class Currency:
    """A currency code plus the number of minor units it divides into.

    >>> Currency("usd").code
    'USD'
    >>> Currency("USD") == Currency("usd")
    True
    """

    __slots__ = ("code", "minor_units", "symbol", "name")

    def __init__(self, code, minor_units=2, symbol="", name=""):
        code = str(code).strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise InputError("a currency code is three letters, got %r" % (code,))
        minor_units = int(minor_units)
        if not 0 <= minor_units <= 4:
            raise InputError("minor units must be 0..4, got %r" % (minor_units,))
        self.code = code
        self.minor_units = minor_units
        self.symbol = str(symbol)
        self.name = str(name) or code

    def __eq__(self, other):
        return isinstance(other, Currency) and other.code == self.code

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("Currency", self.code))

    def __str__(self):
        return self.code

    def __repr__(self):
        return "Currency(%r, %d)" % (self.code, self.minor_units)


CURRENCIES = {
    entry.code: entry
    for entry in (
        Currency("USD", 2, "$", "United States dollar"),
        Currency("CAD", 2, "C$", "Canadian dollar"),
        Currency("EUR", 2, "€", "euro"),
        Currency("GBP", 2, "£", "pound sterling"),
    )
}

DEFAULT_CURRENCY = CURRENCIES["USD"]


def currency_by_code(code):
    """Look up a currency, accepting an unknown three-letter code as-is.

    >>> currency_by_code("USD").symbol
    '$'
    >>> currency_by_code("SEK").minor_units
    2
    """
    if isinstance(code, Currency):
        return code
    key = str(code).strip().upper()
    if key in CURRENCIES:
        return CURRENCIES[key]
    return Currency(key)


class Money:
    """An amount in a currency, with arithmetic that refuses to mix codes.

    >>> money("1000.00") + money("250.50")
    Money('1250.50', 'USD')
    >>> money("1000.00") * "0.10"
    Money('100.0000', 'USD')
    >>> money("1000") - money("1000")
    Money('0', 'USD')
    """

    __slots__ = ("amount", "currency")

    def __init__(self, amount, currency=DEFAULT_CURRENCY):
        self.amount = decimal_from(amount, "amount")
        self.currency = currency_by_code(currency)

    @classmethod
    def zero(cls, currency=DEFAULT_CURRENCY):
        """Return a zero amount in the given currency."""
        return cls(Decimal(0), currency)

    @classmethod
    def parse(cls, text, currency=DEFAULT_CURRENCY):
        """Read ``'$1,250.50'`` or ``'(300)'`` into money.

        >>> Money.parse("$1,250.50")
        Money('1250.50', 'USD')
        >>> Money.parse("(300)")
        Money('-300', 'USD')
        """
        cleaned = str(text).strip()
        for symbol in ("$", "C$", "€", "£"):
            if cleaned.startswith(symbol):
                cleaned = cleaned[len(symbol):]
                break
        return cls(decimal_from(cleaned, "money"), currency)

    def _same(self, other, operation):
        if not isinstance(other, Money):
            raise InputError("cannot %s %r and money" % (operation, other))
        if other.currency != self.currency:
            raise CurrencyMismatch(
                "cannot %s %s and %s" % (operation, self.currency, other.currency)
            )
        return other

    def __add__(self, other):
        other = self._same(other, "add")
        return Money(self.amount + other.amount, self.currency)

    def __radd__(self, other):
        if other == 0:
            return self
        return self.__add__(other)

    def __sub__(self, other):
        other = self._same(other, "subtract")
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor):
        return Money(self.amount * decimal_from(factor, "factor"), self.currency)

    __rmul__ = __mul__

    def __truediv__(self, divisor):
        if isinstance(divisor, Money):
            self._same(divisor, "divide")
            if divisor.amount == 0:
                raise InputError("cannot divide by zero money")
            return self.amount / divisor.amount
        divisor = decimal_from(divisor, "divisor")
        if divisor == 0:
            raise InputError("cannot divide money by zero")
        return Money(self.amount / divisor, self.currency)

    def __neg__(self):
        return Money(-self.amount, self.currency)

    def __abs__(self):
        return Money(abs(self.amount), self.currency)

    def __eq__(self, other):
        if not isinstance(other, Money):
            return NotImplemented
        return self.currency == other.currency and self.amount == other.amount

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __lt__(self, other):
        self._same(other, "compare")
        return self.amount < other.amount

    def __le__(self, other):
        self._same(other, "compare")
        return self.amount <= other.amount

    def __gt__(self, other):
        self._same(other, "compare")
        return self.amount > other.amount

    def __ge__(self, other):
        self._same(other, "compare")
        return self.amount >= other.amount

    def __hash__(self):
        return hash(("Money", self.currency.code, self.amount))

    def __bool__(self):
        return self.amount != 0

    def is_zero(self):
        """Return True when the amount is zero at any exponent."""
        return self.amount == 0

    def is_negative(self):
        """Return True when the amount is below zero."""
        return self.amount < 0

    def rounded(self, places=None, mode=HALF_UP):
        """Return this amount quantized to the currency's minor units.

        >>> money("10.005").rounded()
        Money('10.01', 'USD')
        """
        if places is None:
            places = self.currency.minor_units
        return Money(quantize(self.amount, places, mode), self.currency)

    def split(self, weights, places=None):
        """Split this amount across weights so the parts sum back exactly.

        >>> [str(part) for part in money("100.00").split([1, 1, 1])]
        ['$33.34', '$33.33', '$33.33']
        """
        if places is None:
            places = self.currency.minor_units
        parts = allocate(self.amount, weights, places)
        return [Money(part, self.currency) for part in parts]

    def ratio_to(self, other, default=None):
        """Return this amount divided by another as a plain Decimal."""
        other = self._same(other, "compare")
        if other.amount == 0:
            if default is None:
                raise InputError("cannot take a ratio to zero money")
            return decimal_from(default, "default")
        return self.amount / other.amount

    def format(self, places=None, with_symbol=True, parens_for_negative=False):
        """Render the amount for a report column.

        >>> money("-1234.5").format(parens_for_negative=True)
        '($1,234.50)'
        """
        if places is None:
            places = self.currency.minor_units
        value = quantize(self.amount, places)
        negative = value < 0
        digits = "{:,.{places}f}".format(abs(value), places=places)
        symbol = self.currency.symbol if with_symbol else ""
        if negative and parens_for_negative:
            return "(%s%s)" % (symbol, digits)
        return "%s%s%s" % ("-" if negative else "", symbol, digits)

    def __str__(self):
        return self.format()

    def __repr__(self):
        return "Money(%r, %r)" % (str(self.amount), self.currency.code)


def money(amount, currency=DEFAULT_CURRENCY):
    """Shorthand constructor used all over the package and its tests.

    >>> money("5")
    Money('5', 'USD')
    """
    return Money(amount, currency)


def zero(currency=DEFAULT_CURRENCY):
    """Shorthand for a zero amount."""
    return Money.zero(currency)


def total(amounts, currency=DEFAULT_CURRENCY):
    """Sum an iterable of money, returning zero for an empty one.

    >>> total([money("1.10"), money("2.20")])
    Money('3.30', 'USD')
    """
    running = Money.zero(currency)
    for amount in amounts:
        running = running + amount
    return running
