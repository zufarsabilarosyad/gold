"""Step-downs: the sentence that means two different cheques.

    *Retainage shall be reduced to five percent upon fifty percent completion
    of the work.*

Read prospectively, the reduction applies to work billed after the threshold is
crossed; everything retained before it stays retained.  Read retroactively, the
total retainage becomes five percent of all work to date, so crossing the
threshold triggers a release of half of what is already held.

On a five hundred thousand dollar contract at fifty percent complete, the first
reading holds twenty-five thousand and the second twelve and a half.  The
difference is not a rounding artefact; it is the whole point of the clause, and
which reading applies is a property of the contract, not of the software.

This module implements both, plus the "certification required" variant in which
the step-down only takes effect once the architect has certified satisfactory
progress -- a condition that can be met in a later period than the one where
the threshold was crossed.
"""

from decimal import Decimal

from ..core.money import Money, zero
from ..core.percent import Rate
from ..core.trace import NULL_TRACE
from ..errors import DataError, InputError

__all__ = [
    "effective_rate",
    "prospective_retainage",
    "retroactive_retainage",
    "stepdown_release",
    "rate_history",
]


def effective_rate(terms, completion, line=None, certified=True):
    """Return the rate in force at a completion level.

    ``certified`` answers the certification condition for any step-down that
    requires one; an uncertified step-down does not take effect.

    >>> from .terms import RetainageTerms, Stepdown
    >>> terms = RetainageTerms("10%", stepdowns=[Stepdown("50%", "5%")])
    >>> str(effective_rate(terms, Rate("0.4")))
    '10%'
    >>> str(effective_rate(terms, Rate("0.6")))
    '5%'
    >>> gated = RetainageTerms("10%", stepdowns=[Stepdown("50%", "5%",
    ...                        requires_certification=True)])
    >>> str(effective_rate(gated, Rate("0.6"), certified=False))
    '10%'
    """
    if line is not None and getattr(line, "retainage_rate", None) is not None:
        return line.retainage_rate
    if line is not None and line.is_change_order() and terms.change_order_rate is not None:
        return terms.change_order_rate
    rate = terms.base_rate
    for step in terms.stepdowns:
        if not step.applies_at(completion):
            continue
        if step.requires_certification and not certified:
            continue
        rate = step.rate
    return rate


def rate_history(terms, completions, certified=True):
    """Return the rate in force in each period of a completion series.

    >>> from .terms import RetainageTerms, Stepdown
    >>> terms = RetainageTerms("10%", stepdowns=[Stepdown("50%", "5%")])
    >>> [str(rate) for rate in rate_history(terms, [Rate("0.2"), Rate("0.5"), Rate("0.8")])]
    ['10%', '5%', '5%']
    """
    return [effective_rate(terms, completion, None, certified) for completion in completions]


def prospective_retainage(previous_retained, previous_base, base, rate, trace=NULL_TRACE, subject=""):
    """Return retainage to date when a step-down applies only to later work.

    The retainage already held is untouched; the new rate applies to the
    increment in the base.

    >>> from ..core.money import money
    >>> str(prospective_retainage(money("25000"), money("250000"), money("300000"),
    ...                           Rate("0.05")))
    '$27,500.00'

    A base that falls -- a corrected over-billing -- gives back retainage at
    the current rate rather than at the rate it was taken at, which is the
    behaviour every continuation sheet in the field shows.

    >>> str(prospective_retainage(money("27500"), money("300000"), money("290000"),
    ...                           Rate("0.05")))
    '$27,000.00'
    """
    for name, amount in (
        ("previous retainage", previous_retained),
        ("previous base", previous_base),
        ("base", base),
    ):
        if not isinstance(amount, Money):
            raise InputError("%s must be Money" % (name,))
    increment = base - previous_base
    retained = previous_retained + increment * rate.value
    trace.record(
        "retainage-stepdown",
        subject,
        "prospective: %s held plus %s at %s" % (previous_retained, increment, rate),
        {"retained": str(retained.amount)},
    )
    return retained


def retroactive_retainage(base, rate, trace=NULL_TRACE, subject=""):
    """Return retainage to date when the current rate applies to all work.

    >>> from ..core.money import money
    >>> str(retroactive_retainage(money("300000"), Rate("0.05")))
    '$15,000.00'
    """
    if not isinstance(base, Money):
        raise InputError("base must be Money")
    retained = base * rate.value
    trace.record(
        "retainage-stepdown",
        subject,
        "retroactive: %s of %s" % (rate, base),
        {"retained": str(retained.amount)},
    )
    return retained


def stepdown_release(previous_retained, base, rate):
    """Return the one-off release a retroactive step-down produces.

    Positive means money goes back to the payee this period.  Zero means the
    step-down is not retroactive in effect -- the arithmetic already agrees.

    >>> from ..core.money import money
    >>> str(stepdown_release(money("25000"), money("250000"), Rate("0.05")))
    '$12,500.00'
    >>> str(stepdown_release(money("12500"), money("250000"), Rate("0.05")))
    '$0.00'
    """
    if not isinstance(previous_retained, Money) or not isinstance(base, Money):
        raise InputError("a step-down release needs Money amounts")
    target = base * rate.value
    difference = previous_retained - target
    if difference.is_negative():
        return zero(base.currency)
    return difference
