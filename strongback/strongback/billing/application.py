"""A pay application: the sheet, the summary, the dates and the status.

An application is a document with a life.  It is prepared, submitted,
certified -- possibly for less than was asked -- and paid, possibly late and
possibly in part.  Modelling only the numbers loses the two facts that most
disputes turn on: what was asked for, and what was certified.  Both are kept
here, and ``certified_amount`` is not assumed to equal ``requested_amount``
just because nobody wrote the difference down.
"""

from ..core.dates import format_date, parse_date
from ..core.ids import normalise_id
from ..core.money import Money, money, zero
from ..core.period import BillingPeriod
from ..core.trace import Trace
from ..errors import DataError, InputError, SequenceError
from .continuation import ContinuationSheet
from .summary import ApplicationSummary

__all__ = ["APPLICATION_STATUSES", "PayApplication", "ApplicationRegister"]

APPLICATION_STATUSES = ("draft", "submitted", "certified", "rejected", "paid", "void")

_ORDER = {name: index for index, name in enumerate(APPLICATION_STATUSES)}


class PayApplication:
    """One numbered application for payment.

    >>> from ..core.money import money
    >>> from ..core.period import BillingPeriod
    >>> period = BillingPeriod(3, "2024-11-01", "2024-11-30")
    >>> summary = ApplicationSummary(money("500000"),
    ...     completed_and_stored=money("175000"), retainage_work=money("17500"),
    ...     previous_certificates=money("90000"))
    >>> application = PayApplication("PA-003", 3, period, summary=summary,
    ...                              application_date="2024-12-02")
    >>> str(application.requested_amount())
    '$67,500.00'
    >>> application.status
    'draft'
    >>> _ = application.submit("2024-12-02")
    >>> _ = application.certify("2024-12-09", money("60000"))
    >>> str(application.certified_amount)
    '$60,000.00'
    >>> str(application.shortfall())
    '$7,500.00'
    """

    __slots__ = (
        "id",
        "number",
        "period",
        "sheet",
        "summary",
        "status",
        "application_date",
        "submitted_on",
        "certified_on",
        "certified_amount",
        "paid_on",
        "rejected_reason",
        "trace",
        "policy_name",
        "notes",
    )

    def __init__(
        self,
        identifier,
        number,
        period,
        sheet=None,
        summary=None,
        status="draft",
        application_date=None,
        submitted_on=None,
        certified_on=None,
        certified_amount=None,
        paid_on=None,
        rejected_reason="",
        trace=None,
        policy_name="",
        notes="",
    ):
        self.id = normalise_id(identifier, "application id")
        self.number = int(number)
        if self.number < 1:
            raise InputError("application numbers start at 1, got %r" % (number,))
        if not isinstance(period, BillingPeriod):
            raise InputError("an application needs a BillingPeriod")
        self.period = period
        self.sheet = sheet if sheet is not None else ContinuationSheet()
        self.summary = summary
        if self.summary is not None and not isinstance(self.summary, ApplicationSummary):
            raise InputError("an application summary must be an ApplicationSummary")
        if str(status) not in APPLICATION_STATUSES:
            raise InputError("unknown application status %r" % (status,))
        self.status = str(status)
        self.application_date = parse_date(application_date) if application_date else None
        self.submitted_on = parse_date(submitted_on) if submitted_on else None
        self.certified_on = parse_date(certified_on) if certified_on else None
        self.certified_amount = certified_amount
        if self.certified_amount is not None and not isinstance(self.certified_amount, Money):
            raise InputError("a certified amount must be Money")
        self.paid_on = parse_date(paid_on) if paid_on else None
        self.rejected_reason = str(rejected_reason)
        self.trace = trace if trace is not None else Trace()
        self.policy_name = str(policy_name)
        self.notes = str(notes)

    def requested_amount(self):
        """Return what the application asks for, before certification."""
        if self.summary is None:
            raise DataError("application %s has no summary" % (self.id,))
        return self.summary.net_payable()

    def payable_amount(self):
        """Return the certified amount when there is one, else the request."""
        if self.certified_amount is not None:
            return self.certified_amount
        return self.requested_amount()

    def shortfall(self):
        """Return how much less was certified than was asked for."""
        if self.certified_amount is None:
            return zero(self.requested_amount().currency)
        difference = self.requested_amount() - self.certified_amount
        if difference.is_negative():
            return zero(difference.currency)
        return difference

    def is_certified(self):
        """Return True once the application has been certified."""
        return self.status in ("certified", "paid")

    def is_open(self):
        """Return True while the application is still awaiting payment."""
        return self.status in ("draft", "submitted", "certified")

    def _transition(self, target, allowed):
        """Move to a status, refusing a move the lifecycle does not allow."""
        if self.status not in allowed:
            raise SequenceError(
                "application %s cannot go from %s to %s" % (self.id, self.status, target)
            )
        self.status = target
        return self

    def submit(self, on):
        """Mark the application submitted on a date."""
        self.submitted_on = parse_date(on)
        if self.application_date is None:
            self.application_date = self.submitted_on
        return self._transition("submitted", ("draft",))

    def certify(self, on, amount=None):
        """Certify the application, possibly for less than requested."""
        self.certified_on = parse_date(on)
        if amount is not None:
            if not isinstance(amount, Money):
                raise InputError("a certified amount must be Money")
            if amount.is_negative():
                raise DataError("cannot certify a negative amount")
            self.certified_amount = amount
        else:
            self.certified_amount = self.requested_amount()
        return self._transition("certified", ("submitted",))

    def reject(self, on, reason=""):
        """Reject the application, recording why."""
        self.certified_on = parse_date(on)
        self.rejected_reason = str(reason)
        return self._transition("rejected", ("submitted",))

    def mark_paid(self, on):
        """Mark the application paid in full on a date."""
        self.paid_on = parse_date(on)
        return self._transition("paid", ("certified",))

    def validate(self, allow_overbilling=False):
        """Return the problems with this application."""
        problems = list(self.sheet.validate(allow_overbilling))
        if self.summary is not None:
            problems.extend(self.summary.validate())
            if len(self.sheet):
                if self.sheet.total_completed_and_stored() != self.summary.completed_and_stored:
                    problems.append(
                        "sheet total %s does not match summary line 4 %s"
                        % (
                            self.sheet.total_completed_and_stored(),
                            self.summary.completed_and_stored,
                        )
                    )
                if self.sheet.total_retainage() != self.summary.total_retainage():
                    problems.append(
                        "sheet retainage %s does not match summary line 5 %s"
                        % (self.sheet.total_retainage(), self.summary.total_retainage())
                    )
        if self.certified_amount is not None and self.certified_on is None:
            problems.append("a certified amount was recorded with no certification date")
        return problems

    def to_dict(self):
        """Return the application as plain data."""
        return {
            "id": self.id,
            "number": self.number,
            "period": self.period.to_dict(),
            "status": self.status,
            "application_date": format_date(self.application_date) if self.application_date else None,
            "submitted_on": format_date(self.submitted_on) if self.submitted_on else None,
            "certified_on": format_date(self.certified_on) if self.certified_on else None,
            "certified_amount": (
                str(self.certified_amount.amount) if self.certified_amount else None
            ),
            "paid_on": format_date(self.paid_on) if self.paid_on else None,
            "rejected_reason": self.rejected_reason,
            "policy_name": self.policy_name,
            "notes": self.notes,
            "sheet": self.sheet.to_list(),
            "summary": self.summary.to_dict() if self.summary else None,
            "trace": self.trace.to_list(),
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild an application from :meth:`to_dict` output."""
        return cls(
            data["id"],
            data["number"],
            BillingPeriod.from_dict(data["period"]),
            ContinuationSheet.from_list(data.get("sheet", ()), currency),
            ApplicationSummary.from_dict(data["summary"], currency) if data.get("summary") else None,
            data.get("status", "draft"),
            data.get("application_date"),
            data.get("submitted_on"),
            data.get("certified_on"),
            money(data["certified_amount"], currency) if data.get("certified_amount") else None,
            data.get("paid_on"),
            data.get("rejected_reason", ""),
            Trace.from_list(data.get("trace", ())),
            data.get("policy_name", ""),
            data.get("notes", ""),
        )

    def __eq__(self, other):
        return isinstance(other, PayApplication) and other.id == self.id

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("PayApplication", self.id))

    def __str__(self):
        return "%s (#%d, %s) %s" % (self.id, self.number, self.status, self.payable_amount())

    def __repr__(self):
        return "PayApplication(%r, #%d)" % (self.id, self.number)


class ApplicationRegister:
    """Every application on a contract, in number order.

    >>> from ..core.money import money
    >>> from ..core.period import monthly_schedule
    >>> schedule = monthly_schedule("2024-09-01", 3)
    >>> register = ApplicationRegister()
    >>> for number, period in enumerate(schedule, start=1):
    ...     summary = ApplicationSummary(money("500000"),
    ...         completed_and_stored=money(str(number * 100000)),
    ...         retainage_work=money(str(number * 10000)))
    ...     register.add(PayApplication("PA-%03d" % number, number, period, summary=summary))
    >>> len(register)
    3
    >>> str(register.latest().id)
    'PA-003'
    >>> str(register.certified_to_date(2))
    '$0.00'
    """

    def __init__(self, applications=(), currency="USD"):
        self.currency = currency
        self.applications = {}
        for application in applications:
            self.add(application)

    def add(self, application):
        """Add an application, refusing a duplicate number."""
        if application.id in self.applications:
            raise DataError("application %s appears twice" % (application.id,))
        for existing in self.applications.values():
            if existing.number == application.number and existing.status != "void":
                raise DataError(
                    "applications %s and %s share number %d"
                    % (existing.id, application.id, application.number)
                )
        self.applications[application.id] = application

    def get(self, identifier, default=None):
        """Return an application, or ``default``."""
        return self.applications.get(normalise_id(identifier, "application id"), default)

    def require(self, identifier):
        """Return an application, raising when it is missing."""
        application = self.get(identifier)
        if application is None:
            raise DataError("no application %r on this contract" % (identifier,))
        return application

    def ordered(self):
        """Return the applications in number order."""
        return sorted(self.applications.values(), key=lambda item: (item.number, item.id))

    def numbered(self, number):
        """Return the live application with a number."""
        for application in self.ordered():
            if application.number == int(number) and application.status != "void":
                return application
        raise DataError("no application numbered %r" % (number,))

    def latest(self):
        """Return the highest-numbered application."""
        applications = self.ordered()
        if not applications:
            raise DataError("no applications yet")
        return applications[-1]

    def through(self, number):
        """Return the applications numbered up to and including ``number``."""
        return [item for item in self.ordered() if item.number <= int(number)]

    def previous_to(self, number):
        """Return the applications before a number."""
        return [item for item in self.ordered() if item.number < int(number)]

    def certified_to_date(self, before_number):
        """Return the total certified on earlier applications."""
        running = zero(self.currency)
        for application in self.previous_to(before_number):
            if application.certified_amount is not None:
                running = running + application.certified_amount
        return running

    def requested_to_date(self, before_number):
        """Return the total requested on earlier applications."""
        running = zero(self.currency)
        for application in self.previous_to(before_number):
            if application.summary is not None:
                running = running + application.requested_amount()
        return running

    def open_applications(self):
        """Return the applications not yet paid or closed."""
        return [item for item in self.ordered() if item.is_open()]

    def to_list(self):
        """Return the register as plain data."""
        return [application.to_dict() for application in self.ordered()]

    @classmethod
    def from_list(cls, data, currency="USD"):
        """Rebuild a register from :meth:`to_list` output."""
        return cls([PayApplication.from_dict(entry, currency) for entry in data], currency)

    def __len__(self):
        return len(self.applications)

    def __iter__(self):
        return iter(self.ordered())

    def __getitem__(self, identifier):
        return self.require(identifier)

    def __repr__(self):
        return "ApplicationRegister(%d applications)" % (len(self.applications),)
