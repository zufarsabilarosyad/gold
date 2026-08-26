"""Show the three conversion rules for stored materials on one delivery."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strongback.core.money import money
from strongback.core.percent import Rate
from strongback.core.table import Column, Table
from strongback.model.sov import SOVLine
from strongback.progress.stored import StoredEntry, StoredLedger, StoredOptions, stored_on_hand


def main():
    """Print what each rule bills as the line progresses."""
    line = SOVLine("26200", "Switchgear", money("250000"), stored_eligible=True)
    ledger = StoredLedger([StoredEntry("26200", 1, delivered=money("120000"))])
    table = Table(
        [
            Column("complete", "Line complete", "right"),
            Column("explicit", "explicit", "right"),
            Column("proportional", "proportional", "right"),
            Column("on_completion", "on_completion", "right"),
        ]
    )
    for percent in ("0%", "25%", "50%", "75%", "100%"):
        completion = Rate.parse(percent)
        row = {"complete": percent}
        for rule in ("explicit", "proportional", "on_completion"):
            options = StoredOptions(conversion=rule)
            row[rule] = stored_on_hand(line, ledger, 1, completion, options).rounded().format()
        table.add(row)
    print("A $120,000 delivery against a $250,000 line")
    print("===========================================")
    print()
    print(table.render())
    print()
    print(
        "Nothing was reported as installed, so the explicit rule holds the whole "
        "delivery in the stored column until the field says otherwise."
    )


if __name__ == "__main__":
    main()
