"""strongback -- construction progress billing, retainage and payment applications.

The package answers one question repeatedly: given a contract, a schedule of
values and what the field reported, what may be billed this month and how much
of it is held back?  Every part of that answer is a convention somebody wrote
into a contract, so the conventions are data here rather than assumptions, and
two readings of the same job can be run side by side and their difference
priced line by line.

The layering runs one way::

    core        exact money, rates, quantities, dates, the trace
    model       parties, contracts, schedules of values, change orders
    progress    what was built, measured three ways
    retainage   what is held back, and when it is released
    deductions  what reduces a payment without reducing what was earned
    billing     the continuation sheet and the summary page
    payments    when it is due, what arrived, and how late
    waivers     the documents traded for payment
    compliance  the conditions that gate a cheque
    wip         earned revenue against billing
    policy      the forty-odd decisions the rest of this list needs made
    engine      the order the work happens in
    explain     why a number is what it is
    compare     the same job under two policies, priced
    dataio      reading and writing runs
    report      plain text for people
    cli         an argument surface over all of it

Nothing below ``policy`` imports it, which is what makes a comparison run
possible: the computing modules take their conventions as arguments and have no
defaults of their own to fall back on.
"""

from .core.money import Money, money
from .core.percent import Rate, rate
from .core.period import BillingPeriod, monthly_schedule
from .engine.context import RunContext
from .engine.run import build_application, run_contract
from .errors import DataError, InputError, PolicyError, StrongbackError
from .model.contract import Contract
from .model.sov import ScheduleOfValues, SOVLine
from .policy.resolve import Policy
from .retainage.terms import RetainageTerms, Stepdown
from .version import VERSION, version_string

__all__ = [
    "Money",
    "money",
    "Rate",
    "rate",
    "BillingPeriod",
    "monthly_schedule",
    "RunContext",
    "build_application",
    "run_contract",
    "StrongbackError",
    "DataError",
    "InputError",
    "PolicyError",
    "Contract",
    "ScheduleOfValues",
    "SOVLine",
    "Policy",
    "RetainageTerms",
    "Stepdown",
    "VERSION",
    "version_string",
]
