"""Payment reports: what is open, how old it is, and what it has cost.

The aging table comes from the payments package; this module is the reporting
layer around it, plus the interest schedule, which is the part a contractor
sends with a demand letter.
"""

from ..core.dates import format_date
from ..core.money import zero
from ..core.table import Column, Table, key_value_block
from ..core.text import underline
from ..payments.aging import age_applications, aging_table
from ..payments.due import days_late, due_date
from ..payments.interest import accrue_interest

__all__ = ["open_items_table", "interest_schedule", "payments_report"]


def open_items_table(applications, balances, due_dates=None, as_of=None):
    """Render the open applications with their balances and due dates.

    >>> from ..core.money import money
    >>> from ..core.period import BillingPeriod
    >>> from ..billing.application import PayApplication
    >>> from ..billing.summary import ApplicationSummary
    >>> period = BillingPeriod(1, "2024-09-01", "2024-09-30")
    >>> summary = ApplicationSummary(money("500000"),
    ...     completed_and_stored=money("100000"), retainage_work=money("10000"))
    >>> application = PayApplication("PA-001", 1, period, summary=summary,
    ...                              application_date="2024-10-02")
    >>> print(open_items_table([application], {"PA-001": money("90000")},
    ...                        {"PA-001": "2024-11-12"}, "2024-12-01"))
    Application  Dated       Due            Balance  Days late
    -----------  ----------  ----------  ----------  ---------
    PA-001       2024-10-02  2024-11-12  $90,000.00         19
    """
    due_dates = due_dates or {}
    table = Table(
        [
            Column("id", "Application"),
            Column("dated", "Dated"),
            Column("due", "Due"),
            Column("balance", "Balance", "right"),
            Column("late", "Days late", "right"),
        ]
    )
    for application in applications:
        balance = balances.get(application.id)
        if balance is None or balance.amount <= 0:
            continue
        due = due_dates.get(application.id)
        late = ""
        if due is not None and as_of is not None:
            late = days_late(due, as_of)
        table.add(
            {
                "id": application.id,
                "dated": format_date(application.application_date)
                if application.application_date
                else "-",
                "due": format_date(due) if due else "-",
                "balance": balance.format(),
                "late": late,
            }
        )
    return table.render()


def interest_schedule(balances, due_dates, terms, as_of):
    """Render the interest accrued on each late application.

    >>> from ..core.money import money
    >>> from ..payments.interest import InterestTerms
    >>> print(interest_schedule({"PA-001": money("90000")},
    ...                         {"PA-001": "2024-11-12"},
    ...                         InterestTerms("12%"), "2024-12-12"))
    Application     Balance  Due         Days  Interest
    -----------  ----------  ----------  ----  --------
    PA-001       $90,000.00  2024-11-12    30   $887.67
    """
    table = Table(
        [
            Column("id", "Application"),
            Column("balance", "Balance", "right"),
            Column("due", "Due"),
            Column("days", "Days", "right"),
            Column("interest", "Interest", "right"),
        ]
    )
    for identifier in sorted(balances):
        balance = balances[identifier]
        due = due_dates.get(identifier)
        if due is None or balance.amount <= 0:
            continue
        late = days_late(due, as_of)
        if late <= 0:
            continue
        interest = accrue_interest(balance, due, as_of, terms, subject=identifier)
        table.add(
            {
                "id": identifier,
                "balance": balance.format(),
                "due": format_date(due),
                "days": late,
                "interest": interest.rounded().format(),
            }
        )
    return table.render()


def payments_report(applications, balances, due_dates, as_of, basis="due_date", terms=None):
    """Render the whole payments report.

    >>> from ..core.money import money
    >>> from ..core.period import BillingPeriod
    >>> from ..billing.application import PayApplication
    >>> from ..billing.summary import ApplicationSummary
    >>> period = BillingPeriod(1, "2024-09-01", "2024-09-30")
    >>> summary = ApplicationSummary(money("500000"),
    ...     completed_and_stored=money("100000"), retainage_work=money("10000"))
    >>> application = PayApplication("PA-001", 1, period, summary=summary,
    ...                              application_date="2024-10-02")
    >>> report = payments_report([application], {"PA-001": money("90000")},
    ...                          {"PA-001": "2024-11-12"}, "2024-12-01")
    >>> report.splitlines()[0]
    'Payments'
    """
    currency = next(iter(balances.values())).currency if balances else "USD"
    total = zero(currency)
    for balance in balances.values():
        total = total + balance
    blocks = [
        underline("Payments", "="),
        key_value_block(
            [
                ("As of", format_date(as_of)),
                ("Open applications", len([item for item in balances.values() if item.amount > 0])),
                ("Balance outstanding", total.format()),
            ],
            width=20,
        ),
        underline("Open items", "-")
        + "\n"
        + open_items_table(applications, balances, due_dates, as_of),
        underline("Aging", "-")
        + "\n"
        + aging_table(
            age_applications(applications, balances, as_of, basis, due_dates, currency=currency)
        ),
    ]
    if terms is not None:
        blocks.append(
            underline("Interest", "-")
            + "\n"
            + interest_schedule(balances, due_dates, terms, as_of)
        )
    return "\n\n".join(blocks)
