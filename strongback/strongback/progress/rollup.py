"""Aggregating line-level progress into the groupings people report on.

The continuation sheet is per line; every conversation about it is per trade,
per division, or per cost code.  This module does that folding and nothing
else, so the report layer stays free of arithmetic and the numbers on a summary
row are provably the sum of the lines under it.
"""

from ..core.ids import code_sort_key
from ..core.money import zero
from ..core.percent import Rate
from ..errors import DataError

__all__ = ["RollupRow", "rollup_by", "group_of_line", "division_key"]


class RollupRow:
    """One aggregated row: a key, its lines, and the totals under it.

    >>> row = RollupRow("03 Concrete")
    >>> row.add("03300", zero(), zero())
    >>> len(row)
    1
    """

    __slots__ = ("key", "codes", "scheduled", "earned", "stored")

    def __init__(self, key, scheduled=None, earned=None, stored=None):
        self.key = str(key)
        self.codes = []
        self.scheduled = scheduled if scheduled is not None else zero()
        self.earned = earned if earned is not None else zero()
        self.stored = stored if stored is not None else zero()

    def add(self, code, scheduled, earned, stored=None):
        """Fold one line into this row."""
        self.codes.append(str(code))
        self.scheduled = self.scheduled + scheduled
        self.earned = self.earned + earned
        if stored is not None:
            self.stored = self.stored + stored

    def completion(self):
        """Return earned over scheduled for this row."""
        if self.scheduled.is_zero():
            raise DataError("rollup row %r has no scheduled value" % (self.key,))
        return Rate(self.earned.ratio_to(self.scheduled))

    def balance(self):
        """Return the scheduled value not yet earned."""
        return self.scheduled - self.earned

    def to_dict(self):
        """Return the row as plain data."""
        return {
            "key": self.key,
            "codes": list(self.codes),
            "scheduled": str(self.scheduled.amount),
            "earned": str(self.earned.amount),
            "stored": str(self.stored.amount),
        }

    def __len__(self):
        return len(self.codes)

    def __repr__(self):
        return "RollupRow(%r, %d lines)" % (self.key, len(self.codes))


def group_of_line(line):
    """Return a line's group label, falling back to its division number.

    >>> from ..model.sov import SOVLine
    >>> from ..core.money import money
    >>> group_of_line(SOVLine("03300", "Concrete", money("1"), group="Structure"))
    'Structure'
    >>> group_of_line(SOVLine("03300", "Concrete", money("1")))
    '03'
    """
    if line.group:
        return line.group
    return line.code[:2]


def division_key(line):
    """Return a division label for a line, with its name where known.

    >>> from ..model.sov import SOVLine
    >>> from ..core.money import money
    >>> division_key(SOVLine("03300", "Concrete", money("1")))
    '03 Concrete'
    """
    from ..model.costcode import division_of

    name = division_of(line.code)
    return ("%s %s" % (line.code[:2], name)).strip()


def rollup_by(schedule, earned, stored=None, key=group_of_line):
    """Fold a schedule and its earned values into rows under a key function.

    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> from ..core.money import money
    >>> sov = ScheduleOfValues([
    ...     SOVLine("03300", "Slab", money("100000"), group="Structure"),
    ...     SOVLine("03400", "Precast", money("60000"), group="Structure"),
    ...     SOVLine("09900", "Paint", money("40000"), group="Finishes"),
    ... ])
    >>> earned = {"03300": money("50000"), "03400": money("30000"), "09900": money("4000")}
    >>> rows = rollup_by(sov, earned)
    >>> [(row.key, str(row.earned)) for row in rows]
    [('Finishes', '$4,000.00'), ('Structure', '$80,000.00')]
    >>> str(rows[1].completion())
    '50%'
    """
    stored = stored or {}
    rows = {}
    for line in schedule.ordered():
        label = key(line)
        if label not in rows:
            rows[label] = RollupRow(label, zero(schedule.currency), zero(schedule.currency), zero(schedule.currency))
        rows[label].add(
            line.code,
            line.scheduled_value,
            earned.get(line.code, zero(schedule.currency)),
            stored.get(line.code, zero(schedule.currency)),
        )
    return [rows[label] for label in sorted(rows, key=code_sort_key_safe)]


def code_sort_key_safe(label):
    """Sort rollup labels numerically when they look like codes, else by text.

    >>> code_sort_key_safe("Structure") > code_sort_key_safe("03")
    True
    """
    text = str(label)
    head = text.split()[0] if text.split() else text
    if head[:1].isdigit():
        try:
            return (0, code_sort_key(head), text)
        except Exception:
            return (1, (), text)
    return (1, (), text)
