"""What retainage is charged on, before any rate is applied to it.

The base is not simply "the money billed".  Three questions decide it, and a
contract answers them independently:

* are stored materials retained, or paid in full?
* is change-order work retained at all?
* is a credit line -- a deduct change order -- retained, which would mean
  handing back less than the deduct?

The last one is the one that produces a negative retainage figure and an
argument.  Here a credit reduces the base like anything else, so retainage on a
line that goes negative is negative, and it nets against the rest.  Contracts
that intend otherwise say ``work_less_change_orders``, which takes change-order
lines out of the base entirely.
"""

from ..core.money import Money, zero
from ..core.trace import NULL_TRACE
from ..errors import InputError

__all__ = ["retainage_base", "base_components", "is_retained"]


def is_retained(line, terms):
    """Return True when a line's work is subject to retainage at all.

    >>> from ..model.sov import SOVLine
    >>> from ..core.money import money
    >>> from .terms import RetainageTerms
    >>> base_line = SOVLine("03300", "Concrete", money("100000"))
    >>> change_line = SOVLine("08400", "Storefront", money("42000"), origin="CO-001")
    >>> terms = RetainageTerms("10%", basis="work_less_change_orders")
    >>> is_retained(base_line, terms), is_retained(change_line, terms)
    (True, False)
    """
    if terms.basis == "work_less_change_orders" and line.is_change_order():
        return False
    return True


def base_components(line, earned, stored, terms):
    """Return the work and stored parts of the base, before they are summed.

    >>> from ..model.sov import SOVLine
    >>> from ..core.money import money
    >>> from .terms import RetainageTerms
    >>> line = SOVLine("26200", "Switchgear", money("70000"), stored_eligible=True)
    >>> work, held_stored = base_components(line, money("30000"), money("18000"),
    ...                                     RetainageTerms("10%"))
    >>> str(work), str(held_stored)
    ('$30,000.00', '$18,000.00')
    >>> work, held_stored = base_components(line, money("30000"), money("18000"),
    ...                                     RetainageTerms("10%", basis="work_only"))
    >>> str(work), str(held_stored)
    ('$30,000.00', '$0.00')
    """
    if not isinstance(earned, Money):
        raise InputError("earned value must be Money")
    stored = stored if stored is not None else zero(earned.currency)
    if not is_retained(line, terms):
        return zero(earned.currency), zero(earned.currency)
    if terms.basis == "work_only" or not terms.retains_stored():
        return earned, zero(earned.currency)
    return earned, stored


def retainage_base(line, earned, stored, terms, trace=NULL_TRACE):
    """Return the amount retainage is charged on for one line.

    >>> from ..model.sov import SOVLine
    >>> from ..core.money import money
    >>> from .terms import RetainageTerms
    >>> line = SOVLine("26200", "Switchgear", money("70000"), stored_eligible=True)
    >>> str(retainage_base(line, money("30000"), money("18000"), RetainageTerms("10%")))
    '$48,000.00'
    >>> str(retainage_base(line, money("30000"), money("18000"),
    ...                    RetainageTerms("10%", stored_materials_retained=False)))
    '$30,000.00'
    """
    work, held_stored = base_components(line, earned, stored, terms)
    total = work + held_stored
    trace.record(
        "retainage-base",
        line.code,
        "base %s under %s" % (total, terms.basis),
        {"work": str(work.amount), "stored": str(held_stored.amount)},
    )
    return total
