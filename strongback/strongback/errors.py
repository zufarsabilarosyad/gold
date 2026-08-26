"""Every exception the package raises.

The rule is that a caller can catch :class:`StrongbackError` and be sure it has
caught everything this package throws deliberately.  Anything else escaping is
a bug, not a condition.

The distinctions matter because they land in different places.  An
:class:`InputError` is a bad argument and is the caller's fault.  A
:class:`DataError` is a well-formed document that says something impossible --
a continuation line billing more than its scheduled value, a waiver dated
before the work it covers -- and is the *project's* fault.  A
:class:`PolicyError` means the knobs disagree with each other and no run can be
made until someone chooses.
"""

__all__ = [
    "StrongbackError",
    "InputError",
    "ParseError",
    "DataError",
    "PolicyError",
    "CurrencyMismatch",
    "UnknownLine",
    "PeriodError",
    "SequenceError",
    "GateError",
    "NotSupported",
]


class StrongbackError(Exception):
    """Base class for everything this package raises on purpose."""


class InputError(StrongbackError, ValueError):
    """An argument was the wrong shape, sign, or type."""


class ParseError(InputError):
    """A string could not be read as the value it was supposed to hold."""


class DataError(StrongbackError):
    """A document is internally consistent to parse but impossible in fact."""


class PolicyError(StrongbackError):
    """Two policy knobs cannot both be honoured."""


class CurrencyMismatch(InputError):
    """Two amounts in different currencies met in an arithmetic expression."""


class UnknownLine(DataError):
    """A reference names a schedule-of-values line that does not exist."""


class PeriodError(DataError):
    """A billing period is out of order, overlapping, or missing."""


class SequenceError(DataError):
    """Applications, payments or waivers arrived out of their required order."""


class GateError(StrongbackError):
    """A payment is blocked by a compliance requirement rather than by money."""


class NotSupported(StrongbackError, NotImplementedError):
    """A named convention exists in the vocabulary but is not implemented."""
