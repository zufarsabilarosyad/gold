"""The retainage account: what is held, what was released, and against what.

Every other module computes retainage; this one remembers it.  The ledger is
the answer to the two questions asked at closeout -- how much is still held,
and which lines is it held against -- and it is the object a subcontractor's
office manager reconciles against their own books.

The ledger is deliberately event-shaped rather than balance-shaped.  A balance
that is written down cannot explain itself; a list of accruals and releases
can, and re-running the job produces the same list.
"""

from ..core.dates import format_date, parse_date
from ..core.ids import normalise_code
from ..core.money import Money, money, zero
from ..errors import DataError, InputError
from .release import ReleaseEvent

__all__ = ["RetainageEntry", "RetainageLedger"]


class RetainageEntry:
    """One movement in the retainage account.

    >>> from ..core.money import money
    >>> entry = RetainageEntry("03300", 3, money("4000"))
    >>> str(entry.held)
    '$4,000.00'
    >>> RetainageEntry("03300", 4, money("-1500")).is_release()
    True
    """

    __slots__ = ("code", "period", "held", "reason", "on")

    def __init__(self, code, period, held, reason="", on=None):
        self.code = normalise_code(code) if code else ""
        self.period = int(period)
        if not isinstance(held, Money):
            raise InputError("a retainage movement must be Money")
        self.held = held
        self.reason = str(reason)
        self.on = parse_date(on) if on else None

    def is_release(self):
        """Return True when the movement gives retainage back."""
        return self.held.is_negative()

    def to_dict(self):
        """Return the entry as plain data."""
        return {
            "code": self.code,
            "period": self.period,
            "held": str(self.held.amount),
            "reason": self.reason,
            "on": format_date(self.on) if self.on else None,
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild an entry from :meth:`to_dict` output."""
        return cls(
            data.get("code", ""),
            data["period"],
            money(data["held"], currency),
            data.get("reason", ""),
            data.get("on"),
        )

    def __repr__(self):
        return "RetainageEntry(%r, period=%d, %s)" % (self.code, self.period, self.held)


class RetainageLedger:
    """Accruals and releases, with balances by line and by period.

    >>> from ..core.money import money
    >>> ledger = RetainageLedger()
    >>> ledger.accrue("03300", 1, money("4000"))
    >>> ledger.accrue("03300", 2, money("3000"))
    >>> ledger.release("03300", 3, money("2000"), "early release")
    >>> str(ledger.balance())
    '$5,000.00'
    >>> str(ledger.balance_for_line("03300"))
    '$5,000.00'
    >>> str(ledger.held_in_period(2))
    '$3,000.00'
    """

    def __init__(self, entries=(), currency="USD"):
        self.currency = currency
        self.entries = []
        for entry in entries:
            self.record(entry)

    def record(self, entry):
        """Append a movement."""
        if not isinstance(entry, RetainageEntry):
            raise InputError("expected a RetainageEntry")
        self.entries.append(entry)

    def accrue(self, code, period, amount, reason="", on=None):
        """Record retainage withheld."""
        if amount.is_negative():
            raise DataError("an accrual cannot be negative; use release()")
        self.record(RetainageEntry(code, period, amount, reason or "withheld", on))

    def release(self, code, period, amount, reason="", on=None):
        """Record retainage handed back."""
        if amount.is_negative():
            raise DataError("a release takes a positive amount")
        self.record(RetainageEntry(code, period, -amount, reason or "released", on))

    def apply_event(self, event):
        """Record a :class:`~strongback.retainage.release.ReleaseEvent`."""
        if not isinstance(event, ReleaseEvent):
            raise InputError("expected a ReleaseEvent")
        self.release(event.code, event.period, event.amount, event.kind, event.on)

    def for_line(self, code, through_period=None):
        """Return a line's movements in period order."""
        code = normalise_code(code)
        entries = [entry for entry in self.entries if entry.code == code]
        if through_period is not None:
            entries = [entry for entry in entries if entry.period <= int(through_period)]
        return sorted(entries, key=lambda entry: entry.period)

    def for_period(self, period):
        """Return one period's movements in line order."""
        period = int(period)
        return sorted(
            (entry for entry in self.entries if entry.period == period),
            key=lambda entry: entry.code,
        )

    def codes(self):
        """Return the lines with movements, in code order."""
        return sorted({entry.code for entry in self.entries if entry.code})

    def periods(self):
        """Return the periods with movements, in order."""
        return sorted({entry.period for entry in self.entries})

    def balance(self, through_period=None):
        """Return the total retainage still held."""
        running = zero(self.currency)
        for entry in self.entries:
            if through_period is not None and entry.period > int(through_period):
                continue
            running = running + entry.held
        return running

    def balance_for_line(self, code, through_period=None):
        """Return the retainage still held against one line."""
        running = zero(self.currency)
        for entry in self.for_line(code, through_period):
            running = running + entry.held
        return running

    def line_balances(self, through_period=None):
        """Return a mapping of line code to balance held."""
        return {
            code: self.balance_for_line(code, through_period) for code in self.codes()
        }

    def held_in_period(self, period):
        """Return the retainage withheld in one period, releases excluded."""
        running = zero(self.currency)
        for entry in self.for_period(period):
            if not entry.is_release():
                running = running + entry.held
        return running

    def released_in_period(self, period):
        """Return the retainage released in one period."""
        running = zero(self.currency)
        for entry in self.for_period(period):
            if entry.is_release():
                running = running - entry.held
        return running

    def released_to_date(self, through_period=None):
        """Return the total retainage released so far."""
        running = zero(self.currency)
        for entry in self.entries:
            if through_period is not None and entry.period > int(through_period):
                continue
            if entry.is_release():
                running = running - entry.held
        return running

    def accrued_to_date(self, through_period=None):
        """Return the total retainage ever withheld."""
        running = zero(self.currency)
        for entry in self.entries:
            if through_period is not None and entry.period > int(through_period):
                continue
            if not entry.is_release():
                running = running + entry.held
        return running

    def check_no_overdraw(self):
        """Raise when a release ever took a balance below zero.

        Releasing more than is held is not a rounding artefact; it means two
        releases were computed against the same accrual.  The check is per
        line as well as overall, because a line released twice can hide inside
        a healthy contract balance -- and it is the line the subcontractor
        reconciles, not the contract.
        """
        running = zero(self.currency)
        by_line = {}
        for entry in sorted(self.entries, key=lambda item: (item.period, item.code)):
            running = running + entry.held
            if entry.code:
                by_line[entry.code] = by_line.get(entry.code, zero(self.currency)) + entry.held
                if by_line[entry.code].is_negative():
                    raise DataError(
                        "retainage on line %s goes negative in period %d after %s"
                        % (entry.code, entry.period, entry.reason or "a release")
                    )
            if running.is_negative():
                raise DataError(
                    "retainage balance goes negative in period %d after %s"
                    % (entry.period, entry.reason or "a release")
                )

    def to_list(self):
        """Return the ledger as plain data."""
        return [
            entry.to_dict()
            for entry in sorted(self.entries, key=lambda item: (item.period, item.code))
        ]

    @classmethod
    def from_list(cls, data, currency="USD"):
        """Rebuild a ledger from :meth:`to_list` output."""
        return cls([RetainageEntry.from_dict(entry, currency) for entry in data], currency)

    def __len__(self):
        return len(self.entries)

    def __iter__(self):
        return iter(sorted(self.entries, key=lambda item: (item.period, item.code)))

    def __repr__(self):
        return "RetainageLedger(%d entries, %s held)" % (len(self.entries), self.balance())
