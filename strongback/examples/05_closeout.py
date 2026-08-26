"""Take the sample job to closeout and print what is still open."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strongback.core.money import money
from strongback.dataio.samples import sample_context
from strongback.engine.run import run_contract
from strongback.report.closeout import closeout_report
from strongback.report.retainage import release_schedule
from strongback.report.waivers import waiver_report


def main():
    """Print the closeout position of the sample job."""
    context = sample_context(4)
    results = run_contract(context)
    held = results[-1].summary.total_retainage()
    paid = ["PA-001", "PA-002"]
    print(closeout_report(context, held, context.punchlist_value, money("6500"), paid))
    print()
    print(release_schedule(context.contract, held, context.punchlist_value))
    print()
    print(waiver_report(context.waivers, results[-1].summary.earned_less_retainage(), paid))


if __name__ == "__main__":
    main()
