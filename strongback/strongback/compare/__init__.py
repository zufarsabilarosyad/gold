"""Running the same job twice and pricing the disagreement.

This is the package the rest of the design exists to make possible.  Because
no computing module reaches for a default, a context can be re-run under a
second policy and every difference in the output is caused by a convention that
can be named -- and, one knob at a time, priced.
"""

from .attribute import Attribution, attribute_difference
from .diff import LineDifference, SummaryDifference, diff_results, total_difference
from .render import attribution_table, comparison_report, difference_table

__all__ = [
    "Attribution",
    "attribute_difference",
    "LineDifference",
    "SummaryDifference",
    "diff_results",
    "total_difference",
    "attribution_table",
    "comparison_report",
    "difference_table",
]
