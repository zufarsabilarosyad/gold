"""Statutory notices, whose deadlines run from events, not from invoices.

Preliminary notice, notice of intent to lien, and the lien itself all have
deadlines counted in days from an event -- first furnishing, last furnishing,
completion, or recording of a notice of completion.  The counting is where the
mistakes live:

* the event is not the invoice date, and on a job where a supplier delivered in
  September and billed in November the difference is fatal;
* some deadlines run from *last* furnishing, so they move every time more work
  is done, and a punchlist visit can revive one;
* a deadline landing on a weekend usually rolls forward, but a *recording*
  deadline may not, because the recorder's office simply is not open.

This module computes deadlines from events on a working calendar.  It does not
know any jurisdiction's rules; the day counts are inputs.
"""

from ..core.dates import add_days, format_date, parse_date
from ..core.ids import normalise_id
from ..core.workcalendar import WorkCalendar, calendar_named
from ..errors import DataError, InputError

__all__ = ["NOTICE_KINDS", "TRIGGERS", "NoticeRule", "Notice", "NoticeRegister", "deadline_for"]

NOTICE_KINDS = ("preliminary", "intent_to_lien", "lien", "bond_claim", "stop_notice")
TRIGGERS = ("first_furnishing", "last_furnishing", "completion", "notice_of_completion")


class NoticeRule:
    """A deadline: so many days from a named event, rolled a stated way.

    >>> rule = NoticeRule("preliminary", "first_furnishing", 20)
    >>> rule.days
    20
    >>> format_date(rule.deadline({"first_furnishing": "2024-09-16"}))
    '2024-10-07'
    """

    __slots__ = ("kind", "trigger", "days", "roll", "basis", "note")

    def __init__(self, kind, trigger, days, roll="forward", basis="calendar", note=""):
        if str(kind) not in NOTICE_KINDS:
            raise InputError("unknown notice kind %r; known: %s" % (kind, ", ".join(NOTICE_KINDS)))
        self.kind = str(kind)
        if str(trigger) not in TRIGGERS:
            raise InputError("unknown trigger %r; known: %s" % (trigger, ", ".join(TRIGGERS)))
        self.trigger = str(trigger)
        self.days = int(days)
        if str(roll) not in ("none", "forward", "backward"):
            raise InputError("unknown roll rule %r" % (roll,))
        self.roll = str(roll)
        if str(basis) not in ("calendar", "business"):
            raise InputError("unknown day basis %r" % (basis,))
        self.basis = str(basis)
        self.note = str(note)

    def deadline(self, events, calendar=None):
        """Return the deadline given a mapping of trigger name to date."""
        event = events.get(self.trigger)
        if event is None:
            raise DataError(
                "cannot compute the %s deadline without a %s date"
                % (self.kind, self.trigger.replace("_", " "))
            )
        work = calendar if isinstance(calendar, WorkCalendar) else calendar_named(calendar or "us-federal")
        start = parse_date(event)
        if self.basis == "business":
            due = work.add_business_days(start, self.days)
        else:
            due = add_days(start, self.days)
        if self.roll == "forward":
            return work.next_workday(due, include_self=True)
        if self.roll == "backward":
            return work.previous_workday(due, include_self=True)
        return due

    def to_dict(self):
        """Return the rule as plain data."""
        return {
            "kind": self.kind,
            "trigger": self.trigger,
            "days": self.days,
            "roll": self.roll,
            "basis": self.basis,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild a rule from :meth:`to_dict` output."""
        return cls(
            data["kind"],
            data["trigger"],
            data["days"],
            data.get("roll", "forward"),
            data.get("basis", "calendar"),
            data.get("note", ""),
        )

    def __repr__(self):
        return "NoticeRule(%r, %d days from %s)" % (self.kind, self.days, self.trigger)


class Notice:
    """A notice that was actually served.

    >>> notice = Notice("N-1", "preliminary", "2024-09-25", served_on="2024-09-26")
    >>> notice.kind
    'preliminary'
    """

    __slots__ = ("id", "kind", "dated", "served_on", "method", "recipients", "reference")

    def __init__(
        self,
        identifier,
        kind,
        dated,
        served_on=None,
        method="certified_mail",
        recipients=(),
        reference="",
    ):
        self.id = normalise_id(identifier, "notice id")
        if str(kind) not in NOTICE_KINDS:
            raise InputError("unknown notice kind %r" % (kind,))
        self.kind = str(kind)
        self.dated = parse_date(dated, "notice date")
        self.served_on = parse_date(served_on) if served_on else None
        self.method = str(method)
        self.recipients = tuple(str(name) for name in recipients)
        self.reference = str(reference)

    def effective_date(self):
        """Return the date the notice counts as given."""
        return self.served_on or self.dated

    def to_dict(self):
        """Return the notice as plain data."""
        return {
            "id": self.id,
            "kind": self.kind,
            "dated": format_date(self.dated),
            "served_on": format_date(self.served_on) if self.served_on else None,
            "method": self.method,
            "recipients": list(self.recipients),
            "reference": self.reference,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild a notice from :meth:`to_dict` output."""
        return cls(
            data["id"],
            data["kind"],
            data["dated"],
            data.get("served_on"),
            data.get("method", "certified_mail"),
            data.get("recipients", ()),
            data.get("reference", ""),
        )

    def __repr__(self):
        return "Notice(%r, %r)" % (self.id, self.kind)


class NoticeRegister:
    """The notices served on a job, and whether they were timely.

    >>> register = NoticeRegister([NoticeRule("preliminary", "first_furnishing", 20)])
    >>> register.serve(Notice("N-1", "preliminary", "2024-10-01"))
    >>> events = {"first_furnishing": "2024-09-16"}
    >>> register.is_timely("preliminary", events)
    True
    >>> register.missing(events)
    []
    >>> late = NoticeRegister([NoticeRule("preliminary", "first_furnishing", 20)])
    >>> late.serve(Notice("N-9", "preliminary", "2024-11-01"))
    >>> late.is_timely("preliminary", events)
    False
    """

    def __init__(self, rules=(), notices=()):
        self.rules = list(rules)
        self.notices = {}
        for notice in notices:
            self.serve(notice)

    def serve(self, notice):
        """Record a notice as served."""
        if notice.id in self.notices:
            raise DataError("notice %s appears twice" % (notice.id,))
        self.notices[notice.id] = notice

    def rule_for(self, kind):
        """Return the rule for a notice kind, or ``None``."""
        for rule in self.rules:
            if rule.kind == str(kind):
                return rule
        return None

    def served(self, kind):
        """Return the notices of a kind, earliest first."""
        return sorted(
            (notice for notice in self.notices.values() if notice.kind == str(kind)),
            key=lambda notice: notice.effective_date(),
        )

    def deadline(self, kind, events, calendar=None):
        """Return the deadline for a notice kind."""
        rule = self.rule_for(kind)
        if rule is None:
            raise DataError("no rule for a %s notice" % (kind,))
        return rule.deadline(events, calendar)

    def is_timely(self, kind, events, calendar=None):
        """Return True when a notice of this kind was served in time."""
        deadline = self.deadline(kind, events, calendar)
        for notice in self.served(kind):
            if notice.effective_date() <= deadline:
                return True
        return False

    def missing(self, events, calendar=None):
        """Return the notice kinds required by a rule and not served in time."""
        return [
            rule.kind
            for rule in self.rules
            if not self.is_timely(rule.kind, events, calendar)
        ]

    def to_dict(self):
        """Return the register as plain data."""
        return {
            "rules": [rule.to_dict() for rule in self.rules],
            "notices": [
                notice.to_dict()
                for notice in sorted(self.notices.values(), key=lambda item: item.id)
            ],
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild a register from :meth:`to_dict` output."""
        return cls(
            [NoticeRule.from_dict(entry) for entry in data.get("rules", ())],
            [Notice.from_dict(entry) for entry in data.get("notices", ())],
        )

    def __len__(self):
        return len(self.notices)

    def __repr__(self):
        return "NoticeRegister(%d rules, %d notices)" % (len(self.rules), len(self.notices))


def deadline_for(kind, trigger_date, days, calendar=None, basis="calendar", roll="forward"):
    """Return a single deadline without building a register.

    >>> format_date(deadline_for("lien", "2024-12-20", 90))
    '2025-03-20'
    """
    rule = NoticeRule(kind, "first_furnishing", days, roll, basis)
    return rule.deadline({"first_furnishing": trigger_date}, calendar)
