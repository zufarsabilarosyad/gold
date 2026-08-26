"""Revised applications, and the ripple they send through later ones.

An application is rejected in November and resubmitted in December for less
money.  Everything after it has to move: line 7 of application 8 quoted the
November request, and now quotes something else.  A system that stores line 7
rather than deriving it silently keeps the old number and the job's billing no
longer adds up to the job.

This module models the supersession chain -- which application replaces which,
and what the effective figures are once the chain is walked -- so that a
recomputation has something to recompute *from*.
"""

from ..core.dates import format_date, parse_date
from ..core.ids import normalise_id
from ..core.money import zero
from ..errors import DataError, InputError, SequenceError

__all__ = ["Revision", "RevisionChain"]


class Revision:
    """One application superseding another.

    >>> revision = Revision("PA-007", "PA-007R1", 1, "2024-12-18", "rejected: stored materials")
    >>> revision.supersedes
    'PA-007'
    >>> revision.number
    1
    """

    __slots__ = ("supersedes", "identifier", "number", "on", "reason", "requested_by")

    def __init__(self, supersedes, identifier, number, on=None, reason="", requested_by=""):
        self.supersedes = normalise_id(supersedes, "superseded application")
        self.identifier = normalise_id(identifier, "revised application")
        if self.supersedes == self.identifier:
            raise DataError("an application cannot supersede itself")
        self.number = int(number)
        if self.number < 1:
            raise InputError("revision numbers start at 1")
        self.on = parse_date(on) if on else None
        self.reason = str(reason)
        self.requested_by = str(requested_by)

    def to_dict(self):
        """Return the revision as plain data."""
        return {
            "supersedes": self.supersedes,
            "identifier": self.identifier,
            "number": self.number,
            "on": format_date(self.on) if self.on else None,
            "reason": self.reason,
            "requested_by": self.requested_by,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild a revision from :meth:`to_dict` output."""
        return cls(
            data["supersedes"],
            data["identifier"],
            data["number"],
            data.get("on"),
            data.get("reason", ""),
            data.get("requested_by", ""),
        )

    def __repr__(self):
        return "Revision(%r -> %r)" % (self.supersedes, self.identifier)


class RevisionChain:
    """The supersession graph of a contract's applications.

    >>> chain = RevisionChain()
    >>> chain.add(Revision("PA-007", "PA-007R1", 1))
    >>> chain.add(Revision("PA-007R1", "PA-007R2", 2))
    >>> chain.current("PA-007")
    'PA-007R2'
    >>> chain.is_superseded("PA-007R1")
    True
    >>> chain.history("PA-007R2")
    ['PA-007', 'PA-007R1', 'PA-007R2']
    """

    def __init__(self, revisions=()):
        self.revisions = []
        self._forward = {}
        self._backward = {}
        for revision in revisions:
            self.add(revision)

    def add(self, revision):
        """Add a supersession, refusing a fork or a cycle."""
        if not isinstance(revision, Revision):
            raise InputError("expected a Revision")
        if revision.supersedes in self._forward:
            raise DataError(
                "application %s is already superseded by %s"
                % (revision.supersedes, self._forward[revision.supersedes])
            )
        if revision.identifier in self._backward:
            raise DataError("application %s already supersedes something" % (revision.identifier,))
        seen = revision.supersedes
        for _ in range(len(self.revisions) + 1):
            if seen == revision.identifier:
                raise SequenceError("revision chain would form a cycle at %s" % (seen,))
            seen = self._backward.get(seen)
            if seen is None:
                break
        self.revisions.append(revision)
        self._forward[revision.supersedes] = revision.identifier
        self._backward[revision.identifier] = revision.supersedes

    def current(self, identifier):
        """Return the live application at the end of a chain."""
        seen = normalise_id(identifier, "application id")
        for _ in range(len(self.revisions) + 1):
            following = self._forward.get(seen)
            if following is None:
                return seen
            seen = following
        raise SequenceError("revision chain from %r does not terminate" % (identifier,))

    def is_superseded(self, identifier):
        """Return True when a later revision replaced this application."""
        return normalise_id(identifier, "application id") in self._forward

    def original(self, identifier):
        """Return the first application in a chain."""
        seen = normalise_id(identifier, "application id")
        for _ in range(len(self.revisions) + 1):
            earlier = self._backward.get(seen)
            if earlier is None:
                return seen
            seen = earlier
        raise SequenceError("revision chain to %r does not terminate" % (identifier,))

    def history(self, identifier):
        """Return the whole chain containing an application, oldest first."""
        seen = self.original(identifier)
        chain = [seen]
        for _ in range(len(self.revisions) + 1):
            following = self._forward.get(seen)
            if following is None:
                return chain
            chain.append(following)
            seen = following
        raise SequenceError("revision chain from %r does not terminate" % (identifier,))

    def revision_number(self, identifier):
        """Return how many times an application has been revised."""
        return len(self.history(identifier)) - 1

    def live_applications(self, register):
        """Return the applications in a register that nothing supersedes."""
        return [
            application
            for application in register.ordered()
            if not self.is_superseded(application.id) and application.status != "void"
        ]

    def previous_certified(self, register, before_number, basis="certified"):
        """Return the previous-certificates figure once revisions are honoured.

        >>> from ..core.money import money
        >>> from ..core.period import BillingPeriod
        >>> from .application import ApplicationRegister, PayApplication
        >>> from .summary import ApplicationSummary
        >>> period = BillingPeriod(1, "2024-09-01", "2024-09-30")
        >>> summary = ApplicationSummary(money("100000"),
        ...     completed_and_stored=money("40000"), retainage_work=money("4000"))
        >>> first = PayApplication("PA-001", 1, period, summary=summary)
        >>> _ = first.submit("2024-10-02")
        >>> _ = first.certify("2024-10-09", money("30000"))
        >>> register = ApplicationRegister([first])
        >>> chain = RevisionChain()
        >>> str(chain.previous_certified(register, 2))
        '$30,000.00'
        """
        running = zero(register.currency)
        for application in register.previous_to(before_number):
            if self.is_superseded(application.id) or application.status == "void":
                continue
            if basis == "paid" and application.status != "paid":
                continue
            if application.certified_amount is not None:
                running = running + application.certified_amount
            elif basis != "paid" and application.summary is not None:
                running = running + application.requested_amount()
        return running

    def to_list(self):
        """Return the chain as plain data."""
        return [revision.to_dict() for revision in self.revisions]

    @classmethod
    def from_list(cls, data):
        """Rebuild a chain from :meth:`to_list` output."""
        return cls([Revision.from_dict(entry) for entry in data])

    def __len__(self):
        return len(self.revisions)

    def __iter__(self):
        return iter(self.revisions)

    def __repr__(self):
        return "RevisionChain(%d revisions)" % (len(self.revisions),)
