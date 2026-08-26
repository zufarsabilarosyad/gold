"""Everything that reduces a payment without reducing what was earned.

Four kinds, kept apart because they behave differently at closeout: a
back-charge pays for work someone else did, an offset withholds against a risk
that may or may not resolve, tax is owed to a third party, and an allowance
reconciliation changes the contract sum itself.
"""

from .allowance import Allowance, AllowanceRegister, reconcile_allowance
from .backcharge import BackCharge, BackChargeRegister, apply_backcharges
from .offset import Offset, OffsetRegister
from .tax import TaxRule, tax_on

__all__ = [
    "Allowance",
    "AllowanceRegister",
    "reconcile_allowance",
    "BackCharge",
    "BackChargeRegister",
    "apply_backcharges",
    "Offset",
    "OffsetRegister",
    "TaxRule",
    "tax_on",
]
