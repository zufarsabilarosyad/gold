"""The continuation sheet: every line of the schedule, with its columns.

The sheet is a list of :class:`~strongback.billing.line.ApplicationLine` rows
plus the totals across them, and the invariant that makes it auditable is that
every total is the sum of the column above it.  Nothing here computes what a
line is worth -- the progress and retainage packages did that -- so a sheet can
be built, serialised, reloaded and totalled without any of the conventions
coming back into play.
"""

from ..core.ids import code_sort_key
from ..core.money import Money, zero
from ..core.percent import Rate
from ..core.table import Column, Table
from ..errors import DataError, InputError
from .line import ApplicationLine

__all__ = ["ContinuationSheet"]


class ContinuationSheet:
    """The rows of one application, with column totals.

    >>> from ..core.money import money
    >>> sheet = ContinuationSheet()
    >>> sheet.add(ApplicationLine("01000", "General conditions", money("100000"),
    ...                           previous=money("40000"), this_period=money("10000"),
    ...                           retainage=money("5000")))
    >>> sheet.add(ApplicationLine("03300", "Concrete", money("400000"),
    ...                           this_period=money("60000"), stored=money("15000"),
    ...                           retainage=money("7500")))
    >>> str(sheet.total_scheduled())
    '$500,000.00'
    >>> str(sheet.total_completed_and_stored())
    '$125,000.00'
    >>> str(sheet.total_retainage())
    '$12,500.00'
    >>> str(sheet.percent_complete())
    '25%'
    """

    def __init__(self, lines=(), currency="USD"):
        self.currency = currency
        self.lines = []
        self._index = {}
        for line in lines:
            self.add(line)

    def add(self, line):
        """Append a row, refusing a duplicate code."""
        if not isinstance(line, ApplicationLine):
            raise InputError("expected an ApplicationLine")
        if line.code in self._index:
            raise DataError("continuation sheet has line %s twice" % (line.code,))
        self.lines.append(line)
        self._index[line.code] = line

    def get(self, code, default=None):
        """Return a row by code, or ``default``."""
        return self._index.get(str(code), default)

    def require(self, code):
        """Return a row by code, raising when it is missing."""
        line = self.get(code)
        if line is None:
            raise DataError("no continuation line %r on this sheet" % (code,))
        return line

    def ordered(self):
        """Return the rows in schedule order."""
        return list(self.lines)

    def in_code_order(self):
        """Return the rows in specification-number order."""
        return sorted(self.lines, key=lambda line: code_sort_key(line.code))

    def _sum(self, getter):
        """Sum one column across the sheet."""
        running = zero(self.currency)
        for line in self.lines:
            running = running + getter(line)
        return running

    def total_scheduled(self):
        """Return column A."""
        return self._sum(lambda line: line.scheduled_value)

    def total_previous(self):
        """Return column C."""
        return self._sum(lambda line: line.previous)

    def total_this_period(self):
        """Return column D."""
        return self._sum(lambda line: line.this_period)

    def total_stored(self):
        """Return column E."""
        return self._sum(lambda line: line.stored)

    def total_previous_stored(self):
        """Return the stored balance carried from the previous application."""
        return self._sum(lambda line: line.previous_stored)

    def total_completed_and_stored(self):
        """Return column F."""
        return self._sum(lambda line: line.completed_and_stored())

    def total_work_to_date(self):
        """Return work in place to date, stored material excluded."""
        return self._sum(lambda line: line.work_to_date())

    def total_balance(self):
        """Return column H."""
        return self._sum(lambda line: line.balance_to_finish())

    def total_retainage(self):
        """Return column I."""
        return self._sum(lambda line: line.retainage)

    def total_previous_retainage(self):
        """Return the retainage held by the previous application."""
        return self._sum(lambda line: line.previous_retainage)

    def retainage_on_work(self, rates=None):
        """Return the part of retainage attributable to work in place.

        The summary form splits retainage into a work part and a stored part,
        and the split is by base rather than by rate, so a line with both is
        apportioned in proportion to its own columns.
        """
        running = zero(self.currency)
        for line in self.lines:
            base = line.completed_and_stored()
            if base.is_zero():
                continue
            share = line.work_to_date().ratio_to(base)
            running = running + line.retainage * share
        return running

    def retainage_on_stored(self):
        """Return the part of retainage attributable to stored materials."""
        return self.total_retainage() - self.retainage_on_work()

    def percent_complete(self):
        """Return the sheet's completion, computed from the totals."""
        scheduled = self.total_scheduled()
        if scheduled.is_zero():
            raise DataError("cannot take a percentage of an empty sheet")
        return Rate(self.total_completed_and_stored().ratio_to(scheduled))

    def overbilled_lines(self):
        """Return the rows billed past their scheduled value."""
        return [line for line in self.lines if line.is_overbilled()]

    def started_lines(self):
        """Return the rows with any billing on them."""
        return [line for line in self.lines if line.is_started()]

    def validate(self, allow_overbilling=False):
        """Return every row problem, plus any cross-sheet problem."""
        problems = []
        for line in self.ordered():
            problems.extend(line.validate(allow_overbilling))
        if self.total_completed_and_stored() > self.total_scheduled() and not allow_overbilling:
            problems.append("the sheet bills more than the schedule of values")
        return problems

    def as_table(self):
        """Return the sheet as a rendered fixed-width table."""
        table = Table(
            [
                Column("code", "Item"),
                Column("description", "Description", width=28),
                Column("scheduled", "Scheduled", "right"),
                Column("previous", "Previous", "right"),
                Column("this_period", "This Period", "right"),
                Column("stored", "Stored", "right"),
                Column("total", "Completed", "right"),
                Column("percent", "%", "right"),
                Column("balance", "Balance", "right"),
                Column("retainage", "Retainage", "right"),
            ]
        )
        for line in self.ordered():
            table.add(
                {
                    "code": line.code,
                    "description": line.description,
                    "scheduled": line.scheduled_value.format(),
                    "previous": line.previous.format(),
                    "this_period": line.this_period.format(),
                    "stored": line.stored.format(),
                    "total": line.completed_and_stored().format(),
                    "percent": str(line.percent_complete()),
                    "balance": line.balance_to_finish().format(),
                    "retainage": line.retainage.format(),
                }
            )
        table.add_separator()
        table.add(
            {
                "code": "",
                "description": "Totals",
                "scheduled": self.total_scheduled().format(),
                "previous": self.total_previous().format(),
                "this_period": self.total_this_period().format(),
                "stored": self.total_stored().format(),
                "total": self.total_completed_and_stored().format(),
                "percent": str(self.percent_complete()),
                "balance": self.total_balance().format(),
                "retainage": self.total_retainage().format(),
            }
        )
        return table.render()

    def to_list(self):
        """Return the sheet as plain data."""
        return [line.to_dict() for line in self.ordered()]

    @classmethod
    def from_list(cls, data, currency="USD"):
        """Rebuild a sheet from :meth:`to_list` output."""
        return cls([ApplicationLine.from_dict(entry, currency) for entry in data], currency)

    def __len__(self):
        return len(self.lines)

    def __iter__(self):
        return iter(self.lines)

    def __getitem__(self, code):
        return self.require(code)

    def __contains__(self, code):
        return str(code) in self._index

    def __repr__(self):
        return "ContinuationSheet(%d lines, %s)" % (
            len(self.lines),
            self.total_completed_and_stored(),
        )
