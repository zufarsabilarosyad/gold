"""Accruing retainage line by line, period by period.

Retainage cannot be computed from a single period in isolation once a contract
has a step-down in it, because the prospective reading needs to know what was
held before.  So the unit of work here is a *series*: one entry per period,
each carrying the earned value, the stored value and the contract-level
completion that the step-down keys off.

Everything is computed from the series each time rather than read from a stored
balance.  That is deliberate.  A stored balance drifts the moment a prior
period is revised, and revising a prior period is normal -- an owner rejects
application 4, the contractor resubmits it, and applications 5 onward have to
follow.  Recomputing from the series makes the correction propagate.
"""

from ..core.money import Money, money, zero
from ..core.numbers import quantize
from ..core.percent import Rate
from ..core.trace import NULL_TRACE
from ..errors import DataError, InputError
from .basis import retainage_base
from .stepdown import effective_rate, prospective_retainage, retroactive_retainage, stepdown_release

__all__ = [
    "PeriodValue",
    "LineRetainage",
    "RetainageOptions",
    "accrue_line",
    "accrue_schedule",
    "apply_cap",
]


class PeriodValue:
    """One period's inputs for one line.

    >>> from ..core.money import money
    >>> value = PeriodValue(1, money("50000"), money("10000"), Rate("0.2"))
    >>> value.period
    1
    """

    __slots__ = ("period", "earned", "stored", "completion", "certified")

    def __init__(self, period, earned, stored=None, completion=None, certified=True):
        self.period = int(period)
        if not isinstance(earned, Money):
            raise InputError("earned value must be Money")
        self.earned = earned
        self.stored = stored if stored is not None else zero(earned.currency)
        if completion is None:
            self.completion = Rate(0)
        elif isinstance(completion, Rate):
            self.completion = completion
        else:
            self.completion = Rate.parse(completion)
        self.certified = bool(certified)

    def __repr__(self):
        return "PeriodValue(%d, %s)" % (self.period, self.earned)


class LineRetainage:
    """What one line had retained against it in one period.

    >>> from ..core.money import money
    >>> held = LineRetainage("03300", 2, money("120000"), Rate("0.1"), money("12000"),
    ...                      money("4000"), "prospective", money("0"))
    >>> str(held.retained_to_date)
    '$12,000.00'
    """

    __slots__ = (
        "code",
        "period",
        "base",
        "rate",
        "retained_to_date",
        "retained_this_period",
        "mode",
        "release",
    )

    def __init__(self, code, period, base, rate, retained_to_date, retained_this_period, mode, release):
        self.code = str(code)
        self.period = int(period)
        self.base = base
        self.rate = rate
        self.retained_to_date = retained_to_date
        self.retained_this_period = retained_this_period
        self.mode = str(mode)
        self.release = release

    def to_dict(self):
        """Return the result as plain data."""
        return {
            "code": self.code,
            "period": self.period,
            "base": str(self.base.amount),
            "rate": str(self.rate.value),
            "retained_to_date": str(self.retained_to_date.amount),
            "retained_this_period": str(self.retained_this_period.amount),
            "mode": self.mode,
            "release": str(self.release.amount),
        }

    def __repr__(self):
        return "LineRetainage(%r, period=%d, %s)" % (self.code, self.period, self.retained_to_date)


class RetainageOptions:
    """Rounding and ceiling choices that sit outside the contract clause.

    ``round_stage`` is the one worth thinking about.  Rounding each line's
    retainage to the cent and summing gives a different total from rounding the
    sum, and the difference shows up as a one- or two-cent discrepancy between
    the continuation sheet's retainage column and line 5 of the summary.

    >>> RetainageOptions().round_stage
    'line'
    """

    __slots__ = ("places", "rounding", "round_stage", "apply_cap", "certified_stepdowns")

    def __init__(self, places=2, rounding="half_up", round_stage="line", apply_cap=True, certified_stepdowns=True):
        self.places = int(places)
        self.rounding = str(rounding)
        if str(round_stage) not in ("line", "summary", "none"):
            raise InputError("unknown rounding stage %r" % (round_stage,))
        self.round_stage = str(round_stage)
        self.apply_cap = bool(apply_cap)
        self.certified_stepdowns = bool(certified_stepdowns)

    def round_line(self, amount):
        """Round a per-line figure when the stage says to."""
        if self.round_stage != "line":
            return amount
        return amount.rounded(self.places, self.rounding)

    def round_summary(self, amount):
        """Round a summary figure when the stage says to."""
        if self.round_stage == "none":
            return amount
        return amount.rounded(self.places, self.rounding)

    def to_dict(self):
        """Return the options as plain data."""
        return {
            "places": self.places,
            "rounding": self.rounding,
            "round_stage": self.round_stage,
            "apply_cap": self.apply_cap,
            "certified_stepdowns": self.certified_stepdowns,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild options from :meth:`to_dict` output."""
        return cls(
            data.get("places", 2),
            data.get("rounding", "half_up"),
            data.get("round_stage", "line"),
            data.get("apply_cap", True),
            data.get("certified_stepdowns", True),
        )

    def __repr__(self):
        return "RetainageOptions(round_stage=%r)" % (self.round_stage,)


def accrue_line(line, series, terms, options=None, trace=NULL_TRACE):
    """Return the retainage held against one line in each period of a series.

    The prospective reading, where crossing the threshold changes only the
    treatment of later work:

    >>> from ..model.sov import SOVLine
    >>> from ..core.money import money
    >>> from .terms import RetainageTerms, Stepdown
    >>> line = SOVLine("03300", "Concrete", money("500000"))
    >>> series = [PeriodValue(1, money("200000"), None, Rate("0.4")),
    ...           PeriodValue(2, money("300000"), None, Rate("0.6"))]
    >>> terms = RetainageTerms("10%", stepdowns=[Stepdown("50%", "5%")])
    >>> [str(step.retained_to_date) for step in accrue_line(line, series, terms)]
    ['$20,000.00', '$25,000.00']

    The retroactive reading, where crossing it re-rates everything already
    billed and releases the difference:

    >>> retro = RetainageTerms("10%", stepdowns=[Stepdown("50%", "5%")],
    ...                        stepdown_mode="retroactive")
    >>> [str(step.retained_to_date) for step in accrue_line(line, series, retro)]
    ['$20,000.00', '$15,000.00']
    >>> str(accrue_line(line, series, retro)[1].release)
    '$5,000.00'
    """
    options = options or RetainageOptions()
    results = []
    previous_retained = None
    previous_base = None
    for value in sorted(series, key=lambda item: item.period):
        currency = value.earned.currency
        if previous_retained is None:
            previous_retained = zero(currency)
            previous_base = zero(currency)
        base = retainage_base(line, value.earned, value.stored, terms, trace)
        certified = value.certified and options.certified_stepdowns
        rate = effective_rate(terms, value.completion, line, certified)
        step = terms.stepdown_reached(value.completion)
        mode = terms.mode_for(step) if step is not None else terms.stepdown_mode
        if mode == "retroactive":
            retained = retroactive_retainage(base, rate, trace, line.code)
            release = stepdown_release(previous_retained, base, rate)
        else:
            retained = prospective_retainage(
                previous_retained, previous_base, base, rate, trace, line.code
            )
            release = zero(currency)
        retained = options.round_line(retained)
        this_period = retained - previous_retained
        results.append(
            LineRetainage(
                line.code,
                value.period,
                base,
                rate,
                retained,
                this_period,
                mode,
                release,
            )
        )
        previous_retained = retained
        previous_base = base
    return results


def accrue_schedule(schedule, series_by_code, terms, options=None, trace=NULL_TRACE):
    """Return a mapping of line code to its accrual series.

    Lines with no series -- nothing billed yet -- are absent rather than
    present with zeros, so a caller can tell "not started" from "started and
    worth nothing".

    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> from ..core.money import money
    >>> from .terms import RetainageTerms
    >>> sov = ScheduleOfValues([SOVLine("03300", "Concrete", money("100000"))])
    >>> series = {"03300": [PeriodValue(1, money("40000"))]}
    >>> accrued = accrue_schedule(sov, series, RetainageTerms("10%"))
    >>> str(accrued["03300"][0].retained_to_date)
    '$4,000.00'
    """
    options = options or RetainageOptions()
    accrued = {}
    for line in schedule.ordered():
        series = series_by_code.get(line.code)
        if not series:
            continue
        accrued[line.code] = accrue_line(line, series, terms, options, trace)
    return accrued


def apply_cap(retained, contract_sum, work_completed, terms, trace=NULL_TRACE):
    """Return retainage after any contract ceiling, and whether it bound.

    >>> from ..core.money import money
    >>> from .terms import RetainageTerms
    >>> terms = RetainageTerms("10%", cap_rate="5%", cap_basis="contract_sum")
    >>> held, bound = apply_cap(money("60000"), money("1000000"), money("600000"), terms)
    >>> str(held), bound
    ('$50,000.00', True)
    >>> held, bound = apply_cap(money("40000"), money("1000000"), money("400000"), terms)
    >>> str(held), bound
    ('$40,000.00', False)
    """
    ceiling = terms.cap_amount(contract_sum, work_completed)
    if ceiling is None or retained <= ceiling:
        return retained, False
    trace.record(
        "retainage-cap",
        "contract",
        "capped at %s of %s" % (terms.cap_rate, terms.cap_basis.replace("_", " ")),
        {"uncapped": str(retained.amount), "cap": str(ceiling.amount)},
    )
    return ceiling, True
