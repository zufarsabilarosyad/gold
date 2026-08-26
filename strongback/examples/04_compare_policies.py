"""Run the sample job under two policies and attribute the difference."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strongback.compare.attribute import attribute_difference
from strongback.compare.diff import diff_results
from strongback.compare.render import comparison_report
from strongback.dataio.samples import sample_context
from strongback.engine.run import build_application
from strongback.policy.resolve import Policy


def main():
    """Print the comparison and what each setting was worth."""
    context = sample_context(4)
    first_policy = Policy("aia_standard")
    second_policy = Policy("owner_favorable")
    first = build_application(context.with_policy(first_policy), 4, evaluate=False)
    second = build_application(context.with_policy(second_policy), 4, evaluate=False)
    differences, summary = diff_results(first, second)
    attribution = attribute_difference(context, first_policy, second_policy, 4)
    print(
        comparison_report(
            first,
            second,
            differences,
            summary,
            attribution,
            ("aia_standard", "owner_favorable"),
        )
    )


if __name__ == "__main__":
    main()
