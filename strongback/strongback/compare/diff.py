"""Diffing two applications built from the same documents.

The comparison is between *readings*, not between versions.  Both runs use the
same contract, the same field reports and the same stored-materials ledger; the
only thing that differs is the policy.  So every difference in the output is
caused by a convention, and the interesting output is not the diff but the
attribution -- which is the next module.

A line appears in the diff when any of its columns differ.  Lines present in
one run and not the other are reported as additions or removals, which happens
whenever the two policies disagree about which change orders may be billed.
"""

from ..core.money import zero
from ..errors import InputError

__all__ = ["LineDifference", "SummaryDifference", "diff_results", "total_difference"]


class LineDifference:
    """How one line differs between two runs.

    >>> from ..core.money import money
    >>> difference = LineDifference("03300", money("100000"), money("90000"),
    ...                             money("10000"), money("4500"))
    >>> str(difference.billed_delta())
    '-$10,000.00'
    >>> difference.is_material()
    True
    """

    __slots__ = ("code", "first_billed", "second_billed", "first_retainage", "second_retainage", "state")

    def __init__(self, code, first_billed, second_billed, first_retainage, second_retainage, state="changed"):
        self.code = str(code)
        self.first_billed = first_billed
        self.second_billed = second_billed
        self.first_retainage = first_retainage
        self.second_retainage = second_retainage
        self.state = str(state)

    def billed_delta(self):
        """Return the second run's billing less the first's."""
        return self.second_billed - self.first_billed

    def retainage_delta(self):
        """Return the second run's retainage less the first's."""
        return self.second_retainage - self.first_retainage

    def payment_delta(self):
        """Return the effect on the payment: more billed, less retained."""
        return self.billed_delta() - self.retainage_delta()

    def is_material(self):
        """Return True when anything about the line actually moved."""
        return not (self.billed_delta().is_zero() and self.retainage_delta().is_zero())

    def to_dict(self):
        """Return the difference as plain data."""
        return {
            "code": self.code,
            "state": self.state,
            "first_billed": str(self.first_billed.amount),
            "second_billed": str(self.second_billed.amount),
            "billed_delta": str(self.billed_delta().amount),
            "first_retainage": str(self.first_retainage.amount),
            "second_retainage": str(self.second_retainage.amount),
            "retainage_delta": str(self.retainage_delta().amount),
            "payment_delta": str(self.payment_delta().amount),
        }

    def __repr__(self):
        return "LineDifference(%r, %s)" % (self.code, self.payment_delta())


class SummaryDifference:
    """How the summary pages of two runs differ.

    >>> from ..core.money import money
    >>> difference = SummaryDifference({"current_payment_due": (money("100"), money("120"))})
    >>> str(difference.delta("current_payment_due"))
    '$20.00'
    >>> difference.fields()
    ['current_payment_due']
    """

    __slots__ = ("values",)

    def __init__(self, values):
        self.values = dict(values)

    def fields(self):
        """Return the summary fields that differ, in name order."""
        return sorted(self.values)

    def delta(self, field):
        """Return the movement in one field."""
        first, second = self.values[str(field)]
        return second - first

    def to_dict(self):
        """Return the differences as plain data."""
        return {
            field: {
                "first": str(pair[0].amount),
                "second": str(pair[1].amount),
                "delta": str((pair[1] - pair[0]).amount),
            }
            for field, pair in sorted(self.values.items())
        }

    def __len__(self):
        return len(self.values)

    def __repr__(self):
        return "SummaryDifference(%d fields)" % (len(self.values),)


_SUMMARY_FIELDS = (
    "completed_and_stored",
    "retainage_work",
    "retainage_stored",
    "previous_certificates",
    "deductions",
    "tax",
)


def diff_results(first, second):
    """Return the line and summary differences between two runs.

    >>> from ..core.money import money
    >>> from ..core.period import monthly_schedule
    >>> from ..engine.context import RunContext
    >>> from ..engine.run import build_application
    >>> from ..model.contract import Contract
    >>> from ..model.parties import Party
    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> from ..policy.resolve import Policy
    >>> from ..progress.observation import ProgressEntry, ProgressLedger
    >>> from ..progress.stored import StoredEntry, StoredLedger
    >>> owner, builder = Party("O", "Owner", "owner"), Party("G", "Builder", "contractor")
    >>> sov = ScheduleOfValues([SOVLine("26200", "Switchgear", money("200000"),
    ...                                 stored_eligible=True)])
    >>> progress = ProgressLedger([ProgressEntry("26200", 1, percent="20%")])
    >>> stored = StoredLedger([StoredEntry("26200", 1, delivered=money("60000"))])
    >>> context = RunContext(Contract("C-1", owner, builder, sov),
    ...                      monthly_schedule("2024-09-01", 2), progress=progress,
    ...                      stored=stored)
    >>> first_run = build_application(context, 1, evaluate=False)
    >>> other = context.with_policy(Policy("owner_favorable"))
    >>> second_run = build_application(other, 1, evaluate=False)
    >>> lines, summary = diff_results(first_run, second_run)
    >>> [str(line.billed_delta()) for line in lines]
    ['-$12,000.00']
    """
    if first.application.number != second.application.number:
        raise InputError("only applications for the same period can be compared")
    currency = first.summary.original.currency
    codes = []
    for row in first.sheet:
        codes.append(row.code)
    for row in second.sheet:
        if row.code not in codes:
            codes.append(row.code)
    differences = []
    for code in codes:
        left = first.sheet.get(code)
        right = second.sheet.get(code)
        state = "changed"
        if left is None:
            state = "added"
        elif right is None:
            state = "removed"
        difference = LineDifference(
            code,
            left.completed_and_stored() if left else zero(currency),
            right.completed_and_stored() if right else zero(currency),
            left.retainage if left else zero(currency),
            right.retainage if right else zero(currency),
            state,
        )
        if difference.is_material() or state != "changed":
            differences.append(difference)
    values = {}
    for field in _SUMMARY_FIELDS:
        left = getattr(first.summary, field)
        right = getattr(second.summary, field)
        if left != right:
            values[field] = (left, right)
    payment = (first.summary.current_payment_due(), second.summary.current_payment_due())
    if payment[0] != payment[1]:
        values["current_payment_due"] = payment
    return differences, SummaryDifference(values)


def total_difference(first, second):
    """Return the movement in the payment between two runs.

    >>> from ..core.money import money
    >>> from ..core.period import BillingPeriod
    >>> from ..billing.application import PayApplication
    >>> from ..billing.summary import ApplicationSummary
    >>> from ..engine.result import RunResult
    >>> period = BillingPeriod(1, "2024-09-01", "2024-09-30")
    >>> def result(due):
    ...     summary = ApplicationSummary(money("100000"),
    ...                                  completed_and_stored=money(due))
    ...     return RunResult(PayApplication("PA-001", 1, period, summary=summary))
    >>> str(total_difference(result("40000"), result("45000")))
    '$5,000.00'
    """
    return second.summary.current_payment_due() - first.summary.current_payment_due()
