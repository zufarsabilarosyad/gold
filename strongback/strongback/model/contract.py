"""A contract: two parties, a schedule of values, and the clauses that bill it.

This is the object every run is about.  It owns the schedule of values, the
change order log, the retainage clause, the payment terms and the completion
dates, and it can answer the three questions that head a pay application: what
was the original sum, what have change orders done to it, and what is the
contract sum today.

Note what the contract does *not* own: progress, applications, payments and
waivers all live in their own ledgers.  A contract is a statement of the deal,
not a record of the job.
"""

from ..core.dates import format_date, parse_date
from ..core.ids import normalise_id
from ..core.money import Money, money, zero
from ..core.workcalendar import WorkCalendar, calendar_named
from ..errors import DataError, InputError
from ..retainage.terms import RetainageTerms, standard_terms
from .changeorder import ChangeOrderLog
from .milestone import MilestoneSet
from .parties import Party
from .sov import ScheduleOfValues, SOVLine
from .terms import CompletionDates, LiquidatedDamages, PaymentTerms

__all__ = ["Contract"]


class Contract:
    """One payer-to-payee agreement with its billing clauses attached.

    >>> from .parties import Party
    >>> owner = Party("OWN", "Harbor Point Holdings", "owner")
    >>> builder = Party("GC", "Keel & Sons", "contractor")
    >>> sov = ScheduleOfValues([SOVLine("01000", "General conditions", money("100000")),
    ...                         SOVLine("03300", "Concrete", money("400000"))])
    >>> contract = Contract("C-100", owner, builder, sov)
    >>> str(contract.original_sum())
    '$500,000.00'
    >>> str(contract.contract_sum("2024-12-01"))
    '$500,000.00'
    """

    def __init__(
        self,
        identifier,
        payer,
        payee,
        schedule=None,
        retainage=None,
        payment_terms=None,
        completion=None,
        change_orders=None,
        milestones=None,
        liquidated_damages=None,
        calendar=None,
        currency="USD",
        title="",
        signed_on=None,
        billable_threshold="executed_only",
    ):
        self.id = normalise_id(identifier, "contract id")
        if not isinstance(payer, Party) or not isinstance(payee, Party):
            raise InputError("a contract needs two Party objects")
        if payer.id == payee.id:
            raise DataError("contract %s has the same party on both sides" % (self.id,))
        self.payer = payer
        self.payee = payee
        self.currency = currency
        self.schedule = schedule if schedule is not None else ScheduleOfValues([], currency)
        self.retainage = retainage if retainage is not None else standard_terms()
        if not isinstance(self.retainage, RetainageTerms):
            raise InputError("contract %s needs RetainageTerms" % (self.id,))
        self.payment_terms = payment_terms if payment_terms is not None else PaymentTerms()
        self.completion = completion if completion is not None else CompletionDates()
        self.change_orders = change_orders if change_orders is not None else ChangeOrderLog([], currency)
        self.milestones = milestones if milestones is not None else MilestoneSet([], currency)
        self.liquidated_damages = liquidated_damages
        if self.liquidated_damages is not None and not isinstance(
            self.liquidated_damages, LiquidatedDamages
        ):
            raise InputError("liquidated damages must be a LiquidatedDamages")
        if calendar is None:
            self.calendar = calendar_named("us-federal")
        elif isinstance(calendar, WorkCalendar):
            self.calendar = calendar
        else:
            self.calendar = calendar_named(calendar)
        self.title = str(title)
        self.signed_on = parse_date(signed_on) if signed_on else None
        self.billable_threshold = str(billable_threshold)

    def original_sum(self):
        """Return the sum of the base schedule of values."""
        return self.schedule.base_total()

    def change_order_sum(self, as_of=None, threshold=None):
        """Return the net value of change orders billable at a date."""
        return self.change_orders.value_under(threshold or self.billable_threshold, as_of)

    def contract_sum(self, as_of=None, threshold=None):
        """Return the original sum plus billable change orders."""
        return self.original_sum() + self.change_order_sum(as_of, threshold)

    def pending_change_orders(self, as_of=None, threshold=None):
        """Return the value of live change orders that cannot yet be billed."""
        return self.change_orders.pending_value(threshold or self.billable_threshold, as_of)

    def billing_schedule(self, as_of=None, threshold=None):
        """Return the schedule of values including billable change-order lines.

        The returned schedule is a copy; the contract's own schedule keeps only
        the base lines so that the original scheduled values stay visible after
        any number of changes.
        """
        lines = self.change_orders.lines_for(threshold or self.billable_threshold, as_of)
        return self.schedule.with_lines(lines)

    def line(self, code, as_of=None):
        """Return a line from the billing schedule at a date."""
        return self.billing_schedule(as_of).require(code)

    def retainage_rate_for(self, code, completion=None, as_of=None):
        """Return the retainage rate applying to one line."""
        line = self.line(code, as_of)
        return self.retainage.rate_for_line(line, completion)

    def add_change_order(self, order):
        """Attach a change order to the contract."""
        self.change_orders.add(order)
        return order

    def completion_days_extended(self, as_of=None, threshold=None):
        """Return the contract completion dates with change-order time added."""
        days = self.change_orders.time_extension(threshold or self.billable_threshold, as_of)
        return self.completion.extended_by(days)

    def liquidated_damages_at(self, as_of, threshold=None):
        """Return the liquidated damages assessed at a date, or zero."""
        if self.liquidated_damages is None:
            return zero(self.currency)
        dates = self.completion_days_extended(as_of, threshold)
        return self.liquidated_damages.assess(dates.days_late(as_of))

    def validate(self):
        """Return a list of problems with the contract, empty when sound."""
        problems = list(self.schedule.validate())
        if self.schedule.total().is_zero():
            problems.append("contract %s has an empty schedule of values" % (self.id,))
        if self.milestones and self.milestones.total_value() > self.contract_sum():
            problems.append("milestone values exceed the contract sum")
        if self.payer.role == self.payee.role:
            problems.append("payer and payee hold the same role")
        for order in self.change_orders:
            if order.status == "executed" and order.date_executed is None:
                problems.append("change order %s is executed with no date" % (order.id,))
        return problems

    def describe(self):
        """Return a short block describing the deal."""
        return "\n".join(
            [
                "Contract %s%s" % (self.id, ": " + self.title if self.title else ""),
                "  payer      %s" % (self.payer.name,),
                "  payee      %s" % (self.payee.name,),
                "  original   %s" % (self.original_sum(),),
                "  retainage  %s" % (self.retainage.describe(),),
                "  payment    %s" % (self.payment_terms.describe(),),
            ]
        )

    def to_dict(self):
        """Return the contract as plain data."""
        return {
            "id": self.id,
            "title": self.title,
            "currency": self.currency,
            "payer": self.payer.to_dict(),
            "payee": self.payee.to_dict(),
            "signed_on": format_date(self.signed_on) if self.signed_on else None,
            "billable_threshold": self.billable_threshold,
            "schedule": self.schedule.to_list(),
            "retainage": self.retainage.to_dict(),
            "payment_terms": self.payment_terms.to_dict(),
            "completion": self.completion.to_dict(),
            "change_orders": self.change_orders.to_list(),
            "milestones": self.milestones.to_list(),
            "liquidated_damages": (
                self.liquidated_damages.to_dict() if self.liquidated_damages else None
            ),
            "calendar": self.calendar.name,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild a contract from :meth:`to_dict` output."""
        currency = data.get("currency", "USD")
        damages = data.get("liquidated_damages")
        return cls(
            data["id"],
            Party.from_dict(data["payer"]),
            Party.from_dict(data["payee"]),
            ScheduleOfValues.from_list(data.get("schedule", ()), currency),
            RetainageTerms.from_dict(data.get("retainage", {})),
            PaymentTerms.from_dict(data.get("payment_terms", {})),
            CompletionDates.from_dict(data.get("completion", {})),
            ChangeOrderLog.from_list(data.get("change_orders", ()), currency),
            MilestoneSet.from_list(data.get("milestones", ()), currency),
            LiquidatedDamages.from_dict(damages, currency) if damages else None,
            data.get("calendar"),
            currency,
            data.get("title", ""),
            data.get("signed_on"),
            data.get("billable_threshold", "executed_only"),
        )

    def __eq__(self, other):
        return isinstance(other, Contract) and other.id == self.id

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("Contract", self.id))

    def __str__(self):
        return "%s %s -> %s (%s)" % (self.id, self.payer.name, self.payee.name, self.original_sum())

    def __repr__(self):
        return "Contract(%r, %s)" % (self.id, self.original_sum())
