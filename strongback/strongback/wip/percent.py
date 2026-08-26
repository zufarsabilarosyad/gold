"""Percent complete for the work-in-progress report, which is not the
percentage on the application.

The continuation sheet's percentage is billing: what has been invoiced against
what the contract says the work is worth.  The WIP report's percentage is
production: cost incurred against cost forecast.  They agree only on a job
where the estimate was right, which is to say never.

The gap between them is the whole point of the report.  Billing ahead of
production is over-billing -- cash today, revenue not yet earned -- and it is
normal early in a job and dangerous late in one.  Production ahead of billing
is under-billing, which is a financing cost the contractor is carrying without
being asked.
"""

from decimal import Decimal

from ..core.money import Money, zero
from ..core.percent import Rate
from ..errors import DataError, InputError

__all__ = ["percent_complete", "earned_revenue", "PERCENT_BASES"]

PERCENT_BASES = ("cost", "billing")


def percent_complete(incurred, forecast, billed=None, contract_value=None, basis="cost"):
    """Return percent complete on one of the two bases.

    >>> from ..core.money import money
    >>> str(percent_complete(money("300000"), money("1000000")))
    '30%'
    >>> str(percent_complete(money("300000"), money("1000000"),
    ...                      money("420000"), money("1200000"), basis="billing"))
    '35%'
    """
    basis = str(basis)
    if basis not in PERCENT_BASES:
        raise InputError("unknown percent basis %r; known: %s" % (basis, ", ".join(PERCENT_BASES)))
    if basis == "cost":
        if not isinstance(incurred, Money) or not isinstance(forecast, Money):
            raise InputError("cost-based percent complete needs Money amounts")
        if forecast.is_zero():
            raise DataError("cannot measure progress against a zero cost forecast")
        fraction = incurred.ratio_to(forecast)
    else:
        if billed is None or contract_value is None:
            raise InputError("billing-based percent complete needs billed and contract values")
        if contract_value.is_zero():
            raise DataError("cannot measure progress against a zero contract value")
        fraction = billed.ratio_to(contract_value)
    if fraction < 0:
        return Rate(Decimal(0))
    if fraction > 1:
        return Rate(Decimal(1))
    return Rate(fraction)


def earned_revenue(contract_value, complete):
    """Return the revenue earned at a completion fraction.

    >>> from ..core.money import money
    >>> str(earned_revenue(money("1200000"), Rate("0.3")))
    '$360,000.00'
    """
    if not isinstance(contract_value, Money):
        raise InputError("earned revenue needs a Money contract value")
    fraction = complete.value if isinstance(complete, Rate) else Rate.parse(complete).value
    return contract_value * fraction


def cost_to_complete(forecast, incurred):
    """Return the forecast cost still to be spent, never below zero.

    >>> from ..core.money import money
    >>> str(cost_to_complete(money("1000000"), money("300000")))
    '$700,000.00'
    >>> str(cost_to_complete(money("1000000"), money("1100000")))
    '$0.00'
    """
    remaining = forecast - incurred
    if remaining.is_negative():
        return zero(forecast.currency)
    return remaining
