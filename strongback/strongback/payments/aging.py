"""Aging: how old the money is, measured from an event people disagree about.

An aging report puts every unpaid application in a bucket.  The bucket depends
on what the clock started from, and the two candidates give different pictures
of the same job:

*from the due date* -- nothing is "aged" until it is actually late, so a job
paying exactly on net-45 shows a clean report;
*from the application date* -- everything ages from the day it was billed, so
the same job shows most of its balance in the 31-60 bucket forever.

Both are used, and a contractor's bank usually wants the second while the
contractor's project manager wants the first.
"""

from ..core.dates import days_between, parse_date
from ..core.money import zero
from ..core.table import Column, Table
from ..errors import DataError, InputError

__all__ = ["AGING_BASES", "DEFAULT_BUCKETS", "AgingBucket", "age_applications", "aging_table"]

AGING_BASES = ("due_date", "application_date", "period_end")

DEFAULT_BUCKETS = ((0, "current"), (1, "1-30"), (31, "31-60"), (61, "61-90"), (91, "over 90"))


class AgingBucket:
    """One row of an aging report.

    >>> bucket = AgingBucket("31-60")
    >>> bucket.label
    '31-60'
    >>> len(bucket)
    0
    """

    __slots__ = ("label", "items", "total")

    def __init__(self, label, currency="USD"):
        self.label = str(label)
        self.items = []
        self.total = zero(currency)

    def add(self, identifier, amount, days):
        """Add an application to this bucket."""
        self.items.append((str(identifier), amount, int(days)))
        self.total = self.total + amount

    def identifiers(self):
        """Return the applications in this bucket, in order."""
        return [identifier for identifier, _, _ in self.items]

    def to_dict(self):
        """Return the bucket as plain data."""
        return {
            "label": self.label,
            "total": str(self.total.amount),
            "items": [
                {"application": identifier, "amount": str(amount.amount), "days": days}
                for identifier, amount, days in self.items
            ],
        }

    def __len__(self):
        return len(self.items)

    def __repr__(self):
        return "AgingBucket(%r, %s)" % (self.label, self.total)


def _reference_date(application, basis, due_dates):
    """Return the date an application ages from under a basis."""
    if basis == "due_date":
        due = due_dates.get(application.id)
        if due is None:
            raise DataError("application %s has no due date to age from" % (application.id,))
        return parse_date(due)
    if basis == "application_date":
        reference = application.application_date or application.submitted_on
        if reference is None:
            raise DataError("application %s has no application date" % (application.id,))
        return parse_date(reference)
    return application.period.end


def age_applications(
    applications,
    balances,
    as_of,
    basis="due_date",
    due_dates=None,
    buckets=DEFAULT_BUCKETS,
    currency="USD",
):
    """Return the aging buckets for a set of unpaid applications.

    >>> from ..core.money import money
    >>> from ..core.period import BillingPeriod
    >>> from ..billing.application import PayApplication
    >>> from ..billing.summary import ApplicationSummary
    >>> def application(number, month):
    ...     period = BillingPeriod(number, "2024-%02d-01" % month, "2024-%02d-28" % month)
    ...     summary = ApplicationSummary(money("500000"),
    ...                                  completed_and_stored=money("50000"))
    ...     return PayApplication("PA-%03d" % number, number, period, summary=summary,
    ...                           application_date="2024-%02d-02" % (month + 1))
    >>> apps = [application(1, 9), application(2, 10)]
    >>> balances = {"PA-001": money("50000"), "PA-002": money("30000")}
    >>> rows = age_applications(apps, balances, "2024-12-15", basis="application_date")
    >>> [(row.label, str(row.total)) for row in rows if len(row)]
    [('31-60', '$30,000.00'), ('61-90', '$50,000.00')]
    """
    basis = str(basis)
    if basis not in AGING_BASES:
        raise InputError("unknown aging basis %r; known: %s" % (basis, ", ".join(AGING_BASES)))
    as_of = parse_date(as_of, "as of")
    due_dates = due_dates or {}
    edges = sorted(buckets, key=lambda entry: entry[0])
    rows = [AgingBucket(label, currency) for _, label in edges]
    for application in applications:
        balance = balances.get(application.id)
        if balance is None or balance.amount <= 0:
            continue
        reference = _reference_date(application, basis, due_dates)
        days = days_between(reference, as_of)
        index = 0
        for position, (edge, _) in enumerate(edges):
            if days >= edge:
                index = position
        rows[index].add(application.id, balance, days)
    return rows


def aging_table(rows):
    """Render aging buckets as a table.

    >>> from ..core.money import money
    >>> bucket = AgingBucket("1-30")
    >>> bucket.add("PA-004", money("12000"), 12)
    >>> print(aging_table([bucket]))
    Bucket  Applications      Amount
    ------  ------------  ----------
    1-30               1  $12,000.00
    """
    table = Table(
        [
            Column("label", "Bucket"),
            Column("count", "Applications", "right"),
            Column("total", "Amount", "right"),
        ]
    )
    for row in rows:
        table.add({"label": row.label, "count": len(row), "total": row.total.format()})
    return table.render()
