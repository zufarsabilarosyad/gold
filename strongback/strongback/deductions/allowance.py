"""Allowances, and the markup question that reconciling them raises.

An allowance line carries a number that everyone knows is wrong: eighty
thousand dollars for light fixtures nobody has selected.  When the fixtures are
chosen the line reconciles to the real cost, and the contract sum moves by the
difference.

The disagreement is about overhead and profit on that difference.  Three
readings, all in common use:

``included``
    The allowance already contained the contractor's markup, so the
    reconciliation is cost-only: an overrun adds cost, nothing more.
``on_difference``
    Markup applies to the difference only.  An overrun costs the owner the
    overrun plus markup on it; an underrun credits the underrun plus the
    markup that was in it.
``on_actual``
    The allowance was a bare cost figure; markup applies to the actual cost,
    which means an underrun still earns the contractor markup on what was
    actually spent.

The three give different numbers in both directions, and they are not
symmetric: ``on_difference`` credits markup back on an underrun, ``on_actual``
does not.
"""

from ..core.ids import normalise_code
from ..core.money import Money, money, zero
from ..core.percent import Rate, rate_text
from ..core.trace import NULL_TRACE
from ..errors import DataError, InputError

__all__ = ["MARKUP_RULES", "Allowance", "AllowanceRegister", "reconcile_allowance"]

MARKUP_RULES = ("included", "on_difference", "on_actual")


class Allowance:
    """One allowance line and the actual cost it reconciles to.

    >>> from ..core.money import money
    >>> allowance = Allowance("11400", money("80000"), markup="15%")
    >>> allowance.is_reconciled()
    False
    >>> _ = allowance.reconcile(money("92000"), "2024-11-20")
    >>> str(allowance.difference())
    '$12,000.00'
    """

    __slots__ = ("code", "amount", "actual", "markup", "markup_rule", "description", "reconciled_on")

    def __init__(
        self,
        code,
        amount,
        actual=None,
        markup=None,
        markup_rule="on_difference",
        description="",
        reconciled_on=None,
    ):
        self.code = normalise_code(code)
        if not isinstance(amount, Money):
            raise InputError("an allowance needs a Money amount")
        if amount.is_negative():
            raise DataError("allowance %s is negative" % (self.code,))
        self.amount = amount
        self.actual = actual
        if self.actual is not None and not isinstance(self.actual, Money):
            raise InputError("an allowance actual cost must be Money")
        self.markup = Rate.parse(markup) if markup is not None else None
        if str(markup_rule) not in MARKUP_RULES:
            raise InputError(
                "unknown markup rule %r; known: %s" % (markup_rule, ", ".join(MARKUP_RULES))
            )
        self.markup_rule = str(markup_rule)
        self.description = str(description)
        from ..core.dates import parse_date

        self.reconciled_on = parse_date(reconciled_on) if reconciled_on else None

    def is_reconciled(self):
        """Return True when an actual cost has been recorded."""
        return self.actual is not None

    def reconcile(self, actual, on=None):
        """Record the actual cost, and optionally the date it was fixed."""
        if not isinstance(actual, Money):
            raise InputError("an actual cost must be Money")
        if actual.is_negative():
            raise DataError("allowance %s reconciles to a negative cost" % (self.code,))
        self.actual = actual
        if on is not None:
            from ..core.dates import parse_date

            self.reconciled_on = parse_date(on)
        return self

    def difference(self):
        """Return actual less allowance, positive for an overrun."""
        if not self.is_reconciled():
            raise DataError("allowance %s has not been reconciled" % (self.code,))
        return self.actual - self.amount

    def is_overrun(self):
        """Return True when the actual cost exceeds the allowance."""
        return self.difference().amount > 0

    def to_dict(self):
        """Return the allowance as plain data."""
        from ..core.dates import format_date

        return {
            "code": self.code,
            "amount": str(self.amount.amount),
            "actual": str(self.actual.amount) if self.actual else None,
            "markup": rate_text(self.markup) if self.markup else None,
            "markup_rule": self.markup_rule,
            "description": self.description,
            "reconciled_on": format_date(self.reconciled_on) if self.reconciled_on else None,
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild an allowance from :meth:`to_dict` output."""
        return cls(
            data["code"],
            money(data["amount"], currency),
            money(data["actual"], currency) if data.get("actual") else None,
            data.get("markup"),
            data.get("markup_rule", "on_difference"),
            data.get("description", ""),
            data.get("reconciled_on"),
        )

    def __repr__(self):
        return "Allowance(%r, %s)" % (self.code, self.amount)


def reconcile_allowance(allowance, trace=NULL_TRACE):
    """Return the change-order value an allowance reconciliation produces.

    >>> from ..core.money import money
    >>> over = Allowance("11400", money("80000"), money("92000"), "15%", "on_difference")
    >>> str(reconcile_allowance(over))
    '$13,800.00'
    >>> under = Allowance("11400", money("80000"), money("70000"), "15%", "on_difference")
    >>> str(reconcile_allowance(under))
    '-$11,500.00'
    >>> included = Allowance("11400", money("80000"), money("92000"), "15%", "included")
    >>> str(reconcile_allowance(included))
    '$12,000.00'

    Under ``on_actual`` the same underrun can still move the contract sum *up*,
    because markup on the actual cost outweighs the ten thousand saved:

    >>> on_actual = Allowance("11400", money("80000"), money("70000"), "15%", "on_actual")
    >>> str(reconcile_allowance(on_actual))
    '$500.00'
    """
    difference = allowance.difference()
    if allowance.markup is None or allowance.markup_rule == "included":
        trace.record("allowance", allowance.code, "cost-only reconciliation of %s" % (difference,))
        return difference
    if allowance.markup_rule == "on_difference":
        adjusted = difference * (1 + allowance.markup.value)
    else:
        adjusted = allowance.actual * (1 + allowance.markup.value) - allowance.amount
    trace.record(
        "allowance",
        allowance.code,
        "%s reconciliation of %s with %s markup" % (allowance.markup_rule, difference, allowance.markup),
        {"adjustment": str(adjusted.amount)},
    )
    return adjusted


class AllowanceRegister:
    """The allowances on a contract.

    >>> from ..core.money import money
    >>> register = AllowanceRegister()
    >>> register.add(Allowance("11400", money("80000"), money("92000"), "15%"))
    >>> register.add(Allowance("12500", money("40000")))
    >>> [item.code for item in register.outstanding()]
    ['12500']
    >>> str(register.net_adjustment())
    '$13,800.00'
    """

    def __init__(self, allowances=(), currency="USD"):
        self.currency = currency
        self.allowances = {}
        for allowance in allowances:
            self.add(allowance)

    def add(self, allowance):
        """Add an allowance, refusing a duplicate code."""
        if allowance.code in self.allowances:
            raise DataError("allowance %s appears twice" % (allowance.code,))
        self.allowances[allowance.code] = allowance

    def get(self, code, default=None):
        """Return an allowance, or ``default``."""
        return self.allowances.get(normalise_code(code), default)

    def ordered(self):
        """Return the allowances in code order."""
        return [self.allowances[key] for key in sorted(self.allowances)]

    def outstanding(self):
        """Return the allowances not yet reconciled."""
        return [item for item in self.ordered() if not item.is_reconciled()]

    def reconciled(self):
        """Return the allowances that have been reconciled."""
        return [item for item in self.ordered() if item.is_reconciled()]

    def net_adjustment(self, trace=NULL_TRACE):
        """Return the net contract-sum change from every reconciliation."""
        running = zero(self.currency)
        for item in self.reconciled():
            running = running + reconcile_allowance(item, trace)
        return running

    def outstanding_value(self):
        """Return the unreconciled allowance value still in the contract."""
        running = zero(self.currency)
        for item in self.outstanding():
            running = running + item.amount
        return running

    def to_list(self):
        """Return the register as plain data."""
        return [item.to_dict() for item in self.ordered()]

    @classmethod
    def from_list(cls, data, currency="USD"):
        """Rebuild a register from :meth:`to_list` output."""
        return cls([Allowance.from_dict(entry, currency) for entry in data], currency)

    def __len__(self):
        return len(self.allowances)

    def __iter__(self):
        return iter(self.ordered())

    def __repr__(self):
        return "AllowanceRegister(%d allowances)" % (len(self.allowances),)
