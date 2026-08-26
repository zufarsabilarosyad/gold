"""Retainage: the money held back, and the four decisions that size it.

The rate is the least interesting of them.  What separates two systems billing
the same job is the base the rate applies to, whether a step-down reaches back
over work already retained, where the ceiling sits, and what is released when
the building is usable but not finished.  Each of those has its own module
here, and none of them has a default that is not stated in a contract object.
"""

from .accrual import LineRetainage, PeriodValue, RetainageOptions, accrue_line, accrue_schedule
from .basis import retainage_base
from .ledger import RetainageEntry, RetainageLedger
from .release import ReleaseEvent, final_release, substantial_completion_release
from .stepdown import effective_rate, prospective_retainage, retroactive_retainage
from .terms import RetainageTerms, Stepdown, standard_terms

__all__ = [
    "LineRetainage",
    "PeriodValue",
    "RetainageOptions",
    "accrue_line",
    "accrue_schedule",
    "retainage_base",
    "RetainageEntry",
    "RetainageLedger",
    "ReleaseEvent",
    "final_release",
    "substantial_completion_release",
    "effective_rate",
    "prospective_retainage",
    "retroactive_retainage",
    "RetainageTerms",
    "Stepdown",
    "standard_terms",
]
