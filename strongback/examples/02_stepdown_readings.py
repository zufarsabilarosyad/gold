"""Price the two readings of a retainage step-down.

"Retainage shall be reduced to five percent at fifty percent completion" is
read prospectively by one side and retroactively by the other.  This example
runs the same job both ways and prints the difference.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strongback.core.money import money
from strongback.core.period import monthly_schedule
from strongback.core.table import Column, Table
from strongback.engine.context import RunContext
from strongback.engine.run import run_contract
from strongback.model.contract import Contract
from strongback.model.parties import Party
from strongback.model.sov import ScheduleOfValues, SOVLine
from strongback.progress.observation import ProgressEntry, ProgressLedger
from strongback.retainage.terms import RetainageTerms, Stepdown


def job(mode):
    """Return the run results for one reading of the step-down."""
    owner = Party("OWN", "Fenwick Development", "owner")
    builder = Party("GC", "Marlin Builders", "contractor")
    schedule = ScheduleOfValues([SOVLine("03300", "Structure", money("2000000"))])
    terms = RetainageTerms(
        "10%", stepdowns=[Stepdown("50%", "5%")], stepdown_mode=mode
    )
    contract = Contract("C-500", owner, builder, schedule, terms)
    progress = ProgressLedger(
        [
            ProgressEntry("03300", 1, percent="20%"),
            ProgressEntry("03300", 2, percent="45%"),
            ProgressEntry("03300", 3, percent="65%"),
            ProgressEntry("03300", 4, percent="85%"),
        ]
    )
    context = RunContext(contract, monthly_schedule("2024-09-01", 4), progress=progress)
    return run_contract(context)


def main():
    """Print both readings side by side."""
    prospective = job("prospective")
    retroactive = job("retroactive")
    table = Table(
        [
            Column("period", "Period", "right"),
            Column("complete", "Complete", "right"),
            Column("prospective", "Prospective held", "right"),
            Column("retroactive", "Retroactive held", "right"),
            Column("difference", "Difference", "right"),
        ]
    )
    for first, second in zip(prospective, retroactive):
        held = first.summary.total_retainage()
        other = second.summary.total_retainage()
        table.add(
            {
                "period": first.application.number,
                "complete": str(first.summary.percent_complete()),
                "prospective": held.format(),
                "retroactive": other.format(),
                "difference": (held - other).format(parens_for_negative=True),
            }
        )
    print("A step-down at fifty percent completion, read two ways")
    print("=====================================================")
    print()
    print(table.render())
    print()
    print(
        "The threshold is crossed in period 3.  Under the retroactive reading the "
        "balance is re-rated and the difference comes back that month."
    )


if __name__ == "__main__":
    main()
