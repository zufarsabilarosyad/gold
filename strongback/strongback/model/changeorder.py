"""Change orders, and the four states a change can be in while it is billed.

The disagreement this module exists to model is simple to state and expensive
to get wrong.  Work directed by the owner but not yet executed as a change
order has been *done*; whether it may appear on a pay application depends on
the contract, and reasonable forms answer differently:

* executed only -- nothing bills until both signatures are on the document;
* approved -- an owner's written approval is enough, execution is paperwork;
* directed -- a construction change directive bills at the directive's value,
  which is usually less than the contractor's proposal;
* proposed -- the contractor's number bills and is trued up later.

Each of those is defensible.  None of them is the default everywhere.  The
status lives on the change order; which statuses are billable lives in policy.
"""

from ..core.dates import format_date, parse_date
from ..core.ids import normalise_id
from ..core.money import Money, money, zero
from ..core.percent import Rate, rate_text
from ..errors import DataError, InputError, SequenceError
from .sov import SOVLine

__all__ = ["ChangeStatus", "ChangeOrder", "ChangeOrderLog", "CHANGE_STATUSES", "BILLABLE_SETS"]

CHANGE_STATUSES = ("proposed", "directed", "approved", "executed", "rejected", "void")

BILLABLE_SETS = {
    "executed_only": ("executed",),
    "approved": ("executed", "approved"),
    "directed": ("executed", "approved", "directed"),
    "proposed": ("executed", "approved", "directed", "proposed"),
}

_ORDER = {name: index for index, name in enumerate(CHANGE_STATUSES)}


class ChangeStatus:
    """Where a change order sits in its lifecycle.

    >>> ChangeStatus("executed").is_billable_under("approved")
    True
    >>> ChangeStatus("proposed").is_billable_under("approved")
    False
    """

    __slots__ = ("name",)

    def __init__(self, name):
        text = str(name).strip().lower().replace(" ", "_").replace("-", "_")
        if text not in CHANGE_STATUSES:
            raise InputError(
                "unknown change status %r; known: %s" % (name, ", ".join(CHANGE_STATUSES))
            )
        self.name = text

    def is_dead(self):
        """Return True for statuses that never bill."""
        return self.name in ("rejected", "void")

    def is_billable_under(self, threshold):
        """Return True when this status bills under a named threshold."""
        key = str(threshold).strip().lower()
        if key not in BILLABLE_SETS:
            raise InputError(
                "unknown billable threshold %r; known: %s"
                % (threshold, ", ".join(sorted(BILLABLE_SETS)))
            )
        return self.name in BILLABLE_SETS[key]

    def can_become(self, other):
        """Return True when a transition to another status is allowed."""
        other = ChangeStatus(other) if not isinstance(other, ChangeStatus) else other
        if self.is_dead():
            return False
        if other.is_dead():
            return True
        return _ORDER[other.name] >= _ORDER[self.name]

    def __eq__(self, other):
        if isinstance(other, ChangeStatus):
            return other.name == self.name
        if isinstance(other, str):
            return self.name == str(other).strip().lower()
        return NotImplemented

    def __ne__(self, other):
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    def __hash__(self):
        return hash(("ChangeStatus", self.name))

    def __str__(self):
        return self.name

    def __repr__(self):
        return "ChangeStatus(%r)" % (self.name,)


class ChangeOrder:
    """A priced change to the contract, with the lines it adds.

    >>> change = ChangeOrder("CO-001", 1, "Added storefront", status="executed",
    ...                      date_priced="2024-10-04", date_executed="2024-10-18")
    >>> _ = change.add_line(SOVLine("08400", "Storefront", money("42000")))
    >>> str(change.value())
    '$42,000.00'
    >>> change.is_effective_on("2024-10-20")
    True
    >>> change.is_effective_on("2024-10-05")
    False
    """

    __slots__ = (
        "id",
        "number",
        "description",
        "status",
        "lines",
        "date_proposed",
        "date_priced",
        "date_directed",
        "date_approved",
        "date_executed",
        "retainage_rate",
        "time_extension_days",
        "reason",
        "reference",
    )

    def __init__(
        self,
        identifier,
        number,
        description="",
        status="proposed",
        lines=(),
        date_proposed=None,
        date_priced=None,
        date_directed=None,
        date_approved=None,
        date_executed=None,
        retainage_rate=None,
        time_extension_days=0,
        reason="",
        reference="",
    ):
        self.id = normalise_id(identifier, "change order id")
        self.number = int(number)
        self.description = str(description)
        self.status = status if isinstance(status, ChangeStatus) else ChangeStatus(status)
        self.lines = []
        self.date_proposed = parse_date(date_proposed) if date_proposed else None
        self.date_priced = parse_date(date_priced) if date_priced else None
        self.date_directed = parse_date(date_directed) if date_directed else None
        self.date_approved = parse_date(date_approved) if date_approved else None
        self.date_executed = parse_date(date_executed) if date_executed else None
        self.retainage_rate = Rate.parse(retainage_rate) if retainage_rate is not None else None
        self.time_extension_days = int(time_extension_days)
        self.reason = str(reason)
        self.reference = str(reference)
        for line in lines:
            self.add_line(line)

    def add_line(self, line):
        """Attach a schedule-of-values line to this change order."""
        line = line.copy()
        line.origin = self.id
        line.change_order = self.id
        if self.retainage_rate is not None and line.retainage_rate is None:
            line.retainage_rate = self.retainage_rate
        self.lines.append(line)
        return line

    def value(self, currency="USD"):
        """Return the net value of the change order."""
        running = zero(currency)
        for line in self.lines:
            running = running + line.scheduled_value
        return running

    def is_credit(self):
        """Return True when the change order reduces the contract sum."""
        return self.value().is_negative()

    def effective_date(self):
        """Return the date the change became effective, or ``None``.

        The effective date is the date matching the current status: executed
        orders take their execution date, approved ones their approval date,
        and a directive its direction date.
        """
        if self.status == "executed":
            return self.date_executed or self.date_approved or self.date_directed
        if self.status == "approved":
            return self.date_approved or self.date_directed
        if self.status == "directed":
            return self.date_directed
        if self.status == "proposed":
            return self.date_priced or self.date_proposed
        return None

    def is_effective_on(self, day):
        """Return True when the change had taken effect by a date."""
        effective = self.effective_date()
        if effective is None:
            return False
        return parse_date(day) >= effective

    def bills_under(self, threshold, as_of=None):
        """Return True when this order may be billed under a policy threshold."""
        if self.status.is_dead():
            return False
        if not self.status.is_billable_under(threshold):
            return False
        if as_of is None:
            return True
        return self.is_effective_on(as_of)

    def transition(self, status, on=None):
        """Move the change order to a new status, recording the date."""
        target = status if isinstance(status, ChangeStatus) else ChangeStatus(status)
        if not self.status.can_become(target):
            raise SequenceError(
                "change order %s cannot go from %s to %s" % (self.id, self.status, target)
            )
        self.status = target
        if on is not None:
            day = parse_date(on)
            if target == "directed":
                self.date_directed = day
            elif target == "approved":
                self.date_approved = day
            elif target == "executed":
                self.date_executed = day
        return self

    def to_dict(self):
        """Return the change order as plain data."""
        return {
            "id": self.id,
            "number": self.number,
            "description": self.description,
            "status": str(self.status),
            "lines": [line.to_dict() for line in self.lines],
            "date_proposed": format_date(self.date_proposed) if self.date_proposed else None,
            "date_priced": format_date(self.date_priced) if self.date_priced else None,
            "date_directed": format_date(self.date_directed) if self.date_directed else None,
            "date_approved": format_date(self.date_approved) if self.date_approved else None,
            "date_executed": format_date(self.date_executed) if self.date_executed else None,
            "retainage_rate": rate_text(self.retainage_rate) if self.retainage_rate else None,
            "time_extension_days": self.time_extension_days,
            "reason": self.reason,
            "reference": self.reference,
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild a change order from :meth:`to_dict` output."""
        order = cls(
            data["id"],
            data["number"],
            data.get("description", ""),
            data.get("status", "proposed"),
            (),
            data.get("date_proposed"),
            data.get("date_priced"),
            data.get("date_directed"),
            data.get("date_approved"),
            data.get("date_executed"),
            data.get("retainage_rate"),
            data.get("time_extension_days", 0),
            data.get("reason", ""),
            data.get("reference", ""),
        )
        for entry in data.get("lines", ()):
            order.add_line(SOVLine.from_dict(entry, currency))
        return order

    def __eq__(self, other):
        return isinstance(other, ChangeOrder) and other.id == self.id

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("ChangeOrder", self.id))

    def __str__(self):
        return "%s (%s) %s" % (self.id, self.status, self.value())

    def __repr__(self):
        return "ChangeOrder(%r, %r)" % (self.id, str(self.status))


class ChangeOrderLog:
    """Every change order on a contract, in number order.

    >>> log = ChangeOrderLog()
    >>> first = ChangeOrder("CO-001", 1, status="executed", date_executed="2024-10-01")
    >>> _ = first.add_line(SOVLine("08400", "Storefront", money("42000")))
    >>> log.add(first)
    >>> second = ChangeOrder("CO-002", 2, status="proposed", date_priced="2024-11-02")
    >>> _ = second.add_line(SOVLine("09900", "Extra paint", money("8000")))
    >>> log.add(second)
    >>> str(log.value_under("executed_only", "2024-11-30"))
    '$42,000.00'
    >>> str(log.value_under("proposed", "2024-11-30"))
    '$50,000.00'
    """

    def __init__(self, orders=(), currency="USD"):
        self.currency = currency
        self.orders = {}
        for order in orders:
            self.add(order)

    def add(self, order):
        """Add a change order, refusing a duplicate identifier or number."""
        if order.id in self.orders:
            raise DataError("change order %s appears twice" % (order.id,))
        for existing in self.orders.values():
            if existing.number == order.number:
                raise DataError(
                    "change orders %s and %s share number %d"
                    % (existing.id, order.id, order.number)
                )
        self.orders[order.id] = order

    def get(self, identifier, default=None):
        """Return a change order, or ``default``."""
        return self.orders.get(normalise_id(identifier, "change order id"), default)

    def require(self, identifier):
        """Return a change order, raising when it is missing."""
        order = self.get(identifier)
        if order is None:
            raise DataError("no change order %r on this contract" % (identifier,))
        return order

    def ordered(self):
        """Return the change orders in number order."""
        return sorted(self.orders.values(), key=lambda order: (order.number, order.id))

    def with_status(self, status):
        """Return the change orders in one status."""
        status = status if isinstance(status, ChangeStatus) else ChangeStatus(status)
        return [order for order in self.ordered() if order.status == status]

    def billable(self, threshold, as_of=None):
        """Return the change orders billable under a threshold, in order."""
        return [order for order in self.ordered() if order.bills_under(threshold, as_of)]

    def value_under(self, threshold, as_of=None):
        """Return the net value of every billable change order."""
        running = zero(self.currency)
        for order in self.billable(threshold, as_of):
            running = running + order.value(self.currency)
        return running

    def pending_value(self, threshold, as_of=None):
        """Return the value of live change orders that are not yet billable."""
        running = zero(self.currency)
        for order in self.ordered():
            if order.status.is_dead():
                continue
            if not order.bills_under(threshold, as_of):
                running = running + order.value(self.currency)
        return running

    def lines_for(self, threshold, as_of=None):
        """Return the schedule-of-values lines of every billable change order."""
        lines = []
        for order in self.billable(threshold, as_of):
            lines.extend(line.copy() for line in order.lines)
        return lines

    def time_extension(self, threshold, as_of=None):
        """Return the total contract-time extension in days."""
        return sum(order.time_extension_days for order in self.billable(threshold, as_of))

    def to_list(self):
        """Return the log as plain data."""
        return [order.to_dict() for order in self.ordered()]

    @classmethod
    def from_list(cls, data, currency="USD"):
        """Rebuild a log from :meth:`to_list` output."""
        return cls([ChangeOrder.from_dict(entry, currency) for entry in data], currency)

    def __len__(self):
        return len(self.orders)

    def __iter__(self):
        return iter(self.ordered())

    def __contains__(self, identifier):
        return normalise_id(identifier, "change order id") in self.orders

    def __getitem__(self, identifier):
        return self.require(identifier)

    def __repr__(self):
        return "ChangeOrderLog(%d orders)" % (len(self.orders),)
