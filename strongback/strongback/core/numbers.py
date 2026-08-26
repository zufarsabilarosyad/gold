"""Decimal helpers shared by every money-shaped type in the package.

Nothing here knows about construction.  It exists so that the rest of the
package can say *what* it wants rounded and *when*, and never has to think
about :mod:`decimal` contexts again.
"""

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_DOWN
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP

from ..errors import InputError, ParseError

__all__ = [
    "HALF_UP",
    "HALF_EVEN",
    "DOWN",
    "UP",
    "CEILING",
    "FLOOR",
    "ROUNDING_MODES",
    "rounding_mode",
    "decimal_from",
    "quantize",
    "exponent_for",
    "allocate",
    "clamp",
    "is_zero",
    "sign_of",
    "safe_divide",
]

HALF_UP = "half_up"
HALF_EVEN = "half_even"
DOWN = "down"
UP = "up"
CEILING = "ceiling"
FLOOR = "floor"

ROUNDING_MODES = {
    HALF_UP: ROUND_HALF_UP,
    HALF_EVEN: ROUND_HALF_EVEN,
    DOWN: ROUND_DOWN,
    UP: ROUND_UP,
    CEILING: ROUND_CEILING,
    FLOOR: ROUND_FLOOR,
}


def rounding_mode(name):
    """Translate one of this package's rounding names into a decimal constant.

    >>> rounding_mode("half_up") == ROUND_HALF_UP
    True
    """
    try:
        return ROUNDING_MODES[str(name)]
    except KeyError:
        known = ", ".join(sorted(ROUNDING_MODES))
        raise InputError("unknown rounding mode %r; known: %s" % (name, known))


def decimal_from(value, what="value"):
    """Coerce ints, strings and Decimals to Decimal; reject floats outright.

    A float is refused rather than converted because ``0.1`` is not one tenth
    and a schedule of values that silently loses a cent per line is worse than
    one that refuses to load.

    >>> decimal_from("12.50")
    Decimal('12.50')
    >>> decimal_from(3)
    Decimal('3')
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise InputError("%s cannot be a boolean" % (what,))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        raise InputError(
            "%s must not be a float (%r); pass a string or Decimal" % (what, value)
        )
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if text.startswith("(") and text.endswith(")"):
            text = "-" + text[1:-1]
        if text.endswith("%"):
            text = text[:-1]
        if not text:
            raise ParseError("%s is empty" % (what,))
        try:
            return Decimal(text)
        except InvalidOperation:
            raise ParseError("%s is not a number: %r" % (what, value))
    raise InputError("%s has unusable type %s" % (what, type(value).__name__))


def exponent_for(places):
    """Return the Decimal exponent that quantizes to ``places`` decimals.

    >>> exponent_for(2)
    Decimal('0.01')
    >>> exponent_for(0)
    Decimal('1')
    """
    places = int(places)
    if places < 0:
        raise InputError("decimal places cannot be negative: %r" % (places,))
    if places == 0:
        return Decimal(1)
    return Decimal(1).scaleb(-places)


def quantize(value, places=2, mode=HALF_UP):
    """Round ``value`` to ``places`` decimals with a named rounding mode.

    >>> quantize(Decimal("1.005"))
    Decimal('1.01')
    >>> quantize(Decimal("1.005"), mode="half_even")
    Decimal('1.00')
    """
    return decimal_from(value).quantize(exponent_for(places), rounding=rounding_mode(mode))


def allocate(total, weights, places=2):
    """Split ``total`` across ``weights`` so the parts sum to exactly ``total``.

    The largest-remainder rule decides who absorbs the odd cents, and ties go
    to the earlier position so the answer does not depend on sort stability.

    >>> allocate(Decimal("100.00"), [Decimal(1), Decimal(1), Decimal(1)])
    [Decimal('33.34'), Decimal('33.33'), Decimal('33.33')]
    """
    total = decimal_from(total, "total")
    weights = [decimal_from(weight, "weight") for weight in weights]
    if not weights:
        if total != 0:
            raise InputError("cannot allocate %s across no weights" % (total,))
        return []
    weight_sum = sum(weights)
    step = exponent_for(places)
    if weight_sum == 0:
        parts = [Decimal(0) for _ in weights]
        parts[0] = quantize(total, places)
        return parts
    exact = [total * weight / weight_sum for weight in weights]
    floored = [value.quantize(step, rounding=ROUND_DOWN) for value in exact]
    shortfall = int(((quantize(total, places) - sum(floored)) / step).to_integral_value())
    order = sorted(
        range(len(weights)),
        key=lambda index: (-(exact[index] - floored[index]), index),
    )
    bump = step if shortfall >= 0 else -step
    for position in range(abs(shortfall)):
        floored[order[position % len(order)]] += bump
    return floored


def clamp(value, low=None, high=None):
    """Constrain a decimal to a range, ignoring bounds that are ``None``.

    >>> clamp(Decimal(5), Decimal(0), Decimal(3))
    Decimal('3')
    """
    value = decimal_from(value)
    if low is not None and value < decimal_from(low, "low"):
        return decimal_from(low, "low")
    if high is not None and value > decimal_from(high, "high"):
        return decimal_from(high, "high")
    return value


def is_zero(value):
    """Return True when the decimal is zero regardless of its exponent.

    >>> is_zero(Decimal("0.000"))
    True
    """
    return decimal_from(value) == 0


def sign_of(value):
    """Return -1, 0 or 1 for a decimal.

    >>> sign_of(Decimal("-2"))
    -1
    """
    value = decimal_from(value)
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def safe_divide(numerator, denominator, default=None):
    """Divide, returning ``default`` instead of raising on a zero denominator.

    >>> safe_divide(Decimal(1), Decimal(0), Decimal(0))
    Decimal('0')
    """
    numerator = decimal_from(numerator, "numerator")
    denominator = decimal_from(denominator, "denominator")
    if denominator == 0:
        if default is None:
            raise InputError("division by zero and no default was supplied")
        return decimal_from(default, "default")
    return numerator / denominator
