"""Build the first application on a small job and print it.

Run with ``python examples/01_first_application.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strongback.core.money import money
from strongback.core.period import monthly_schedule
from strongback.engine.context import RunContext
from strongback.engine.run import build_application
from strongback.model.contract import Contract
from strongback.model.parties import Party
from strongback.model.sov import ScheduleOfValues, SOVLine
from strongback.progress.observation import ProgressEntry, ProgressLedger
from strongback.report.g702 import application_page
from strongback.report.g703 import continuation_page
from strongback.retainage.terms import RetainageTerms


def main():
    """Build and print one application."""
    owner = Party("OWN", "Fenwick Development", "owner")
    builder = Party("GC", "Marlin Builders", "contractor")
    schedule = ScheduleOfValues(
        [
            SOVLine("01000", "General conditions", money("90000"), group="General"),
            SOVLine("03300", "Slab on grade", money("240000"), group="Structure"),
            SOVLine("09900", "Painting", money("70000"), group="Finishes"),
        ]
    )
    contract = Contract(
        "C-410",
        owner,
        builder,
        schedule,
        RetainageTerms("10%"),
        title="Fenwick Yard building B",
    )
    progress = ProgressLedger(
        [
            ProgressEntry("01000", 1, percent="25%"),
            ProgressEntry("03300", 1, percent="40%"),
        ]
    )
    context = RunContext(contract, monthly_schedule("2024-09-01", 3), progress=progress)
    result = build_application(context, 1, evaluate=False)
    print(application_page(contract, result))
    print()
    print(continuation_page(result.sheet))


if __name__ == "__main__":
    main()
