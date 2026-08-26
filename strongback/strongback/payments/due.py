"""When a payment is due, which is three questions rather than one.

*From what event.*  The clock starts at submission, at receipt, at
certification, or at the end of the period the application covers.  On a job
where the architect takes three weeks, "thirty days from certification" and
"thirty days from receipt" are three weeks apart.

*On what calendar.*  Thirty calendar days and thirty business days differ by
about twelve days, and a statutory prompt-payment act may impose one while the
contract says the other.

*Rolled how.*  A due date landing on a Sunday moves -- forward on most
contracts, back under a few, and not at all where the contract is silent and
the payer's bank runs on Saturdays anyway.
"""

from ..core.dates import add_days, format_date, parse_date
from ..core.workcalendar import WorkCalendar, calendar_named
from ..errors import DataError, InputError

__all__ = ["ROLL_RULES", "due_date", "start_date_for", "days_late", "is_late"]

ROLL_RULES = ("none", "forward", "backward")


def start_date_for(terms, application):
    """Return the date the payment clock starts for an application.

    >>> from ..model.terms import PaymentTerms
    >>> from ..core.period import BillingPeriod
    >>> from ..billing.application import PayApplication
    >>> period = BillingPeriod(1, "2024-09-01", "2024-09-30")
    >>> application = PayApplication("PA-001", 1, period,
    ...                              application_date="2024-10-02",
    ...                              submitted_on="2024-10-03",
    ...                              certified_on="2024-10-11")
    >>> format_date(start_date_for(PaymentTerms(start_event="certification_date"), application))
    '2024-10-11'
    >>> format_date(start_date_for(PaymentTerms(start_event="receipt_date"), application))
    '2024-10-03'
    >>> format_date(start_date_for(PaymentTerms(start_event="period_end"), application))
    '2024-09-30'
    """
    event = terms.start_event
    if event == "application_date":
        start = application.application_date or application.submitted_on
    elif event == "receipt_date":
        start = application.submitted_on or application.application_date
    elif event == "certification_date":
        start = application.certified_on
        if start is None:
            fallback = application.submitted_on or application.application_date
            if fallback is None:
                raise DataError(
                    "application %s has no date to run the payment clock from"
                    % (application.id,)
                )
            start = add_days(fallback, terms.certification_days)
    else:
        start = application.period.end
    if start is None:
        raise DataError("application %s has no %s" % (application.id, event))
    return parse_date(start)


def due_date(terms, application, calendar=None, roll="forward"):
    """Return the date a certified application becomes payable.

    >>> from ..model.terms import PaymentTerms
    >>> from ..core.period import BillingPeriod
    >>> from ..billing.application import PayApplication
    >>> period = BillingPeriod(1, "2024-09-01", "2024-09-30")
    >>> application = PayApplication("PA-001", 1, period, submitted_on="2024-10-03",
    ...                              certified_on="2024-10-11")
    >>> format_date(due_date(PaymentTerms(net_days=30), application))
    '2024-11-12'
    >>> format_date(due_date(PaymentTerms(net_days=10, day_basis="business"), application))
    '2024-10-28'
    """
    if str(roll) not in ROLL_RULES:
        raise InputError("unknown roll rule %r; known: %s" % (roll, ", ".join(ROLL_RULES)))
    if calendar is None:
        work = calendar_named("us-federal")
    elif isinstance(calendar, WorkCalendar):
        work = calendar
    else:
        work = calendar_named(calendar)
    start = start_date_for(terms, application)
    if terms.day_basis == "business":
        due = work.add_business_days(start, terms.net_days)
    else:
        due = add_days(start, terms.net_days)
    if roll == "forward":
        return work.next_workday(due, include_self=True)
    if roll == "backward":
        return work.previous_workday(due, include_self=True)
    return due


def days_late(due, paid_on, calendar=None, basis="calendar"):
    """Return how many days after the due date a payment landed.

    >>> days_late("2024-11-12", "2024-11-20")
    8
    >>> days_late("2024-11-12", "2024-11-01")
    0
    >>> days_late("2024-11-12", "2024-11-20", basis="business")
    6
    """
    due = parse_date(due, "due date")
    paid_on = parse_date(paid_on, "payment date")
    if paid_on <= due:
        return 0
    if basis == "business":
        work = calendar if isinstance(calendar, WorkCalendar) else calendar_named(calendar or "us-federal")
        return work.business_days_between(due, paid_on)
    return (paid_on - due).days


def is_late(due, paid_on=None, as_of=None):
    """Return True when a payment is late, or overdue as of a date.

    >>> is_late("2024-11-12", "2024-11-20")
    True
    >>> is_late("2024-11-12", as_of="2024-11-30")
    True
    >>> is_late("2024-11-12", as_of="2024-11-01")
    False
    """
    due = parse_date(due, "due date")
    if paid_on is not None:
        return parse_date(paid_on) > due
    if as_of is None:
        raise InputError("an unpaid application needs an as-of date to age against")
    return parse_date(as_of) > due
