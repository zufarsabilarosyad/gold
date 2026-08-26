"""Over- and under-billing, and why the sign of the number is not the story.

Earned revenue is the contract value times percent complete.  Billing is what
the applications asked for.  The difference has two names depending on which
way it falls -- costs and estimated earnings in excess of billings, or billings
in excess of costs and estimated earnings -- and the accounting profession's
names are longer than the idea.

What the report is for is the *trend*.  A line over-billed at ten percent
complete is a mobilisation charge and is fine.  The same line over-billed at
ninety percent complete has nothing left to bill against the work still to do,
and the job will finish with a loss the contractor has already spent.
"""

from ..core.money import Money, zero
from ..core.percent import Rate
from ..core.table import Column, Table
from ..errors import DataError, InputError
from .percent import earned_revenue, percent_complete

__all__ = ["OverUnder", "over_under", "portfolio_over_under", "over_under_table"]


class OverUnder:
    """One contract's billing position against its earned revenue.

    >>> from ..core.money import money
    >>> position = OverUnder("C-100", money("1200000"), money("300000"),
    ...                      money("1000000"), money("420000"))
    >>> str(position.percent_complete())
    '30%'
    >>> str(position.earned())
    '$360,000.00'
    >>> str(position.difference())
    '$60,000.00'
    >>> position.is_overbilled()
    True
    """

    __slots__ = ("contract_id", "contract_value", "incurred", "forecast", "billed", "basis")

    def __init__(self, contract_id, contract_value, incurred, forecast, billed, basis="cost"):
        self.contract_id = str(contract_id)
        for name, amount in (
            ("contract value", contract_value),
            ("incurred cost", incurred),
            ("cost forecast", forecast),
            ("billed", billed),
        ):
            if not isinstance(amount, Money):
                raise InputError("%s must be Money" % (name,))
        self.contract_value = contract_value
        self.incurred = incurred
        self.forecast = forecast
        self.billed = billed
        self.basis = str(basis)

    def percent_complete(self):
        """Return percent complete on this position's basis."""
        return percent_complete(
            self.incurred, self.forecast, self.billed, self.contract_value, self.basis
        )

    def earned(self):
        """Return the revenue earned to date."""
        return earned_revenue(self.contract_value, self.percent_complete())

    def difference(self):
        """Return billed less earned; positive means over-billed."""
        return self.billed - self.earned()

    def is_overbilled(self):
        """Return True when billing runs ahead of earned revenue."""
        return self.difference().amount > 0

    def gross_margin(self):
        """Return forecast revenue less forecast cost."""
        return self.contract_value - self.forecast

    def margin_rate(self):
        """Return the forecast margin as a share of the contract value."""
        if self.contract_value.is_zero():
            raise DataError("contract %s has no value to take a margin on" % (self.contract_id,))
        return Rate(self.gross_margin().ratio_to(self.contract_value))

    def remaining_to_bill(self):
        """Return the contract value not yet billed."""
        return self.contract_value - self.billed

    def to_dict(self):
        """Return the position as plain data."""
        return {
            "contract_id": self.contract_id,
            "contract_value": str(self.contract_value.amount),
            "incurred": str(self.incurred.amount),
            "forecast": str(self.forecast.amount),
            "billed": str(self.billed.amount),
            "basis": self.basis,
            "percent_complete": str(self.percent_complete().value),
            "earned": str(self.earned().amount),
            "difference": str(self.difference().amount),
        }

    def __repr__(self):
        return "OverUnder(%r, %s)" % (self.contract_id, self.difference())


def over_under(contract_id, contract_value, incurred, forecast, billed, basis="cost"):
    """Build an :class:`OverUnder` position.

    >>> from ..core.money import money
    >>> str(over_under("C-1", money("100000"), money("40000"), money("80000"),
    ...                money("55000")).difference())
    '$5,000.00'
    """
    return OverUnder(contract_id, contract_value, incurred, forecast, billed, basis)


def portfolio_over_under(positions):
    """Return the totals across several contracts, and the two-sided split.

    Over-billings and under-billings do not net on a balance sheet -- they are
    a liability and an asset -- so the split is reported as well as the net.

    >>> from ..core.money import money
    >>> first = over_under("C-1", money("100000"), money("40000"), money("80000"),
    ...                    money("55000"))
    >>> second = over_under("C-2", money("200000"), money("120000"), money("160000"),
    ...                     money("130000"))
    >>> totals = portfolio_over_under([first, second])
    >>> str(totals["overbilled"]), str(totals["underbilled"]), str(totals["net"])
    ('$5,000.00', '$20,000.00', '-$15,000.00')
    """
    positions = list(positions)
    if not positions:
        raise DataError("a portfolio needs at least one position")
    currency = positions[0].contract_value.currency
    over = zero(currency)
    under = zero(currency)
    for position in positions:
        difference = position.difference()
        if difference.amount > 0:
            over = over + difference
        else:
            under = under - difference
    return {"overbilled": over, "underbilled": under, "net": over - under}


def over_under_table(positions):
    """Render positions as a table.

    >>> from ..core.money import money
    >>> print(over_under_table([over_under("C-1", money("100000"), money("40000"),
    ...                                     money("80000"), money("55000"))]))
    Contract        Value  Complete      Earned      Billed  Over/(Under)
    --------  -----------  --------  ----------  ----------  ------------
    C-1       $100,000.00       50%  $50,000.00  $55,000.00     $5,000.00
    """
    table = Table(
        [
            Column("contract", "Contract"),
            Column("value", "Value", "right"),
            Column("complete", "Complete", "right"),
            Column("earned", "Earned", "right"),
            Column("billed", "Billed", "right"),
            Column("difference", "Over/(Under)", "right"),
        ]
    )
    for position in positions:
        table.add(
            {
                "contract": position.contract_id,
                "value": position.contract_value.format(),
                "complete": str(position.percent_complete()),
                "earned": position.earned().format(),
                "billed": position.billed.format(),
                "difference": position.difference().format(parens_for_negative=True),
            }
        )
    return table.render()
