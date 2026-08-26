"""Milestone lines: value that is earned by an event, not by a percentage.

Milestone billing is the simplest thing in the schedule and the one most often
modelled wrongly, because the interesting case is the milestone that is nearly
done.  A structure topped out on the twenty-eighth of a month whose milestone
is "structure complete and surveyed" earns nothing that month, and the
superintendent who bills eighty percent of it is not wrong about the work --
only about the contract.

This module therefore keeps two separate ideas apart: whether the event has
occurred, and how much value the line has earned.  Policy may allow partial
credit against a milestone; the milestone itself never claims any.
"""

from ..core.dates import format_date, parse_date
from ..core.ids import normalise_id
from ..core.money import Money, money, zero
from ..core.percent import Rate, rate_text
from ..errors import DataError, InputError

__all__ = ["Milestone", "MilestoneSet", "PARTIAL_RULES"]

PARTIAL_RULES = ("none", "stated", "proportional")


class Milestone:
    """An event that earns a stated value when it happens.

    >>> stone = Milestone("MS-2", "Structure topped out", money("150000"))
    >>> stone.achieved
    False
    >>> _ = stone.achieve("2024-11-08")
    >>> str(stone.earned_value())
    '$150,000.00'
    """

    __slots__ = (
        "code",
        "description",
        "value",
        "achieved_on",
        "target_date",
        "partial_rule",
        "partial_share",
        "predecessors",
        "evidence",
    )

    def __init__(
        self,
        code,
        description,
        value,
        achieved_on=None,
        target_date=None,
        partial_rule="none",
        partial_share=None,
        predecessors=(),
        evidence="",
    ):
        self.code = normalise_id(code, "milestone code")
        self.description = str(description)
        if not isinstance(value, Money):
            raise InputError("milestone %s needs a Money value" % (self.code,))
        if value.is_negative():
            raise DataError("milestone %s has a negative value" % (self.code,))
        self.value = value
        self.achieved_on = parse_date(achieved_on) if achieved_on else None
        self.target_date = parse_date(target_date) if target_date else None
        rule = str(partial_rule).strip().lower()
        if rule not in PARTIAL_RULES:
            raise InputError("unknown partial rule %r" % (partial_rule,))
        self.partial_rule = rule
        self.partial_share = Rate.parse(partial_share) if partial_share is not None else None
        if self.partial_rule == "stated" and self.partial_share is None:
            raise InputError("milestone %s states partial credit without a share" % (self.code,))
        self.predecessors = tuple(normalise_id(item, "predecessor") for item in predecessors)
        self.evidence = str(evidence)

    @property
    def achieved(self):
        """Return True when the milestone event has happened."""
        return self.achieved_on is not None

    def achieved_by(self, day):
        """Return True when the event happened on or before a date."""
        if self.achieved_on is None:
            return False
        return self.achieved_on <= parse_date(day)

    def achieve(self, day, evidence=""):
        """Record the event date, refusing to move an existing one silently."""
        day = parse_date(day)
        if self.achieved_on is not None and self.achieved_on != day:
            raise DataError(
                "milestone %s was already achieved on %s"
                % (self.code, format_date(self.achieved_on))
            )
        self.achieved_on = day
        if evidence:
            self.evidence = str(evidence)
        return self

    def earned_value(self, as_of=None, progress=None):
        """Return the value earned, honouring the partial-credit rule.

        ``progress`` is a decimal fraction of physical completion and is only
        consulted when the milestone allows proportional partial credit.
        """
        if as_of is None:
            achieved = self.achieved
        else:
            achieved = self.achieved_by(as_of)
        if achieved:
            return self.value
        if self.partial_rule == "none" or progress is None:
            return zero(self.value.currency)
        if self.partial_rule == "stated":
            return self.value * self.partial_share.value
        return self.value * progress

    def is_late(self, as_of):
        """Return True when the target date has passed unachieved."""
        if self.target_date is None:
            return False
        as_of = parse_date(as_of)
        if self.achieved_on is not None:
            return self.achieved_on > self.target_date
        return as_of > self.target_date

    def to_dict(self):
        """Return the milestone as plain data."""
        return {
            "code": self.code,
            "description": self.description,
            "value": str(self.value.amount),
            "achieved_on": format_date(self.achieved_on) if self.achieved_on else None,
            "target_date": format_date(self.target_date) if self.target_date else None,
            "partial_rule": self.partial_rule,
            "partial_share": rate_text(self.partial_share) if self.partial_share else None,
            "predecessors": list(self.predecessors),
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild a milestone from :meth:`to_dict` output."""
        return cls(
            data["code"],
            data.get("description", ""),
            money(data["value"], currency),
            data.get("achieved_on"),
            data.get("target_date"),
            data.get("partial_rule", "none"),
            data.get("partial_share"),
            data.get("predecessors", ()),
            data.get("evidence", ""),
        )

    def __eq__(self, other):
        return isinstance(other, Milestone) and other.code == self.code

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("Milestone", self.code))

    def __str__(self):
        state = format_date(self.achieved_on) if self.achieved else "open"
        return "%s %s (%s)" % (self.code, self.description, state)

    def __repr__(self):
        return "Milestone(%r)" % (self.code,)


class MilestoneSet:
    """The milestones on a contract, with their dependency order.

    >>> stones = MilestoneSet([
    ...     Milestone("MS-1", "Foundations", money("100000")),
    ...     Milestone("MS-2", "Structure", money("150000"), predecessors=["MS-1"]),
    ... ])
    >>> _ = stones["MS-1"].achieve("2024-10-04")
    >>> [stone.code for stone in stones.achieved_by("2024-10-31")]
    ['MS-1']
    >>> stones.blocked("MS-2")
    False
    >>> str(stones.earned_value("2024-10-31"))
    '$100,000.00'
    """

    def __init__(self, milestones=(), currency="USD"):
        self.currency = currency
        self.milestones = {}
        for milestone in milestones:
            self.add(milestone)

    def add(self, milestone):
        """Add a milestone, refusing a duplicate code."""
        if milestone.code in self.milestones:
            raise DataError("milestone %s appears twice" % (milestone.code,))
        self.milestones[milestone.code] = milestone

    def get(self, code, default=None):
        """Return a milestone, or ``default``."""
        return self.milestones.get(normalise_id(code, "milestone code"), default)

    def require(self, code):
        """Return a milestone, raising when it is missing."""
        found = self.get(code)
        if found is None:
            raise DataError("no milestone %r on this contract" % (code,))
        return found

    def ordered(self):
        """Return the milestones in code order."""
        return [self.milestones[key] for key in sorted(self.milestones)]

    def achieved_by(self, day):
        """Return the milestones achieved on or before a date."""
        return [stone for stone in self.ordered() if stone.achieved_by(day)]

    def open_at(self, day):
        """Return the milestones still open at a date."""
        return [stone for stone in self.ordered() if not stone.achieved_by(day)]

    def blocked(self, code):
        """Return True when a milestone has an unachieved predecessor."""
        stone = self.require(code)
        for predecessor in stone.predecessors:
            if not self.require(predecessor).achieved:
                return True
        return False

    def earned_value(self, as_of=None, progress=None):
        """Return the total value earned by the achieved milestones."""
        running = zero(self.currency)
        progress = progress or {}
        for stone in self.ordered():
            running = running + stone.earned_value(as_of, progress.get(stone.code))
        return running

    def total_value(self):
        """Return the total value of every milestone."""
        running = zero(self.currency)
        for stone in self.ordered():
            running = running + stone.value
        return running

    def late(self, as_of):
        """Return the milestones that have missed their target date."""
        return [stone for stone in self.ordered() if stone.is_late(as_of)]

    def to_list(self):
        """Return the set as plain data."""
        return [stone.to_dict() for stone in self.ordered()]

    @classmethod
    def from_list(cls, data, currency="USD"):
        """Rebuild a set from :meth:`to_list` output."""
        return cls([Milestone.from_dict(entry, currency) for entry in data], currency)

    def __len__(self):
        return len(self.milestones)

    def __iter__(self):
        return iter(self.ordered())

    def __getitem__(self, code):
        return self.require(code)

    def __contains__(self, code):
        return normalise_id(code, "milestone code") in self.milestones

    def __repr__(self):
        return "MilestoneSet(%d milestones)" % (len(self.milestones),)
