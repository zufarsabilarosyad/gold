"""Everything a run needs, gathered in one object.

A run is a pure function of its context: the same context produces the same
application, byte for byte, every time.  Nothing here reads a clock, a file or
an environment variable, and the context carries no mutable state that a run
writes back into -- results come out as new objects.

The context is assembled once and then handed to the stages.  That is why it
holds ledgers rather than paths: loading is somebody else's job, and the
``dataio`` package does it.
"""

from ..billing.application import ApplicationRegister
from ..billing.revision import RevisionChain
from ..core.period import PeriodSchedule
from ..core.trace import Trace
from ..deductions.backcharge import BackChargeRegister
from ..deductions.offset import OffsetRegister
from ..errors import DataError, InputError
from ..model.contract import Contract
from ..policy.resolve import Policy
from ..progress.costtocost import CostLedger
from ..progress.observation import ProgressLedger
from ..progress.stored import StoredLedger
from ..retainage.ledger import RetainageLedger
from ..waivers.ledger import WaiverLedger

__all__ = ["RunContext"]


class RunContext:
    """The inputs of one billing run.

    >>> from ..core.money import money
    >>> from ..core.period import monthly_schedule
    >>> from ..model.contract import Contract
    >>> from ..model.parties import Party
    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> owner = Party("OWN", "Harbor Point Holdings", "owner")
    >>> builder = Party("GC", "Keel & Sons", "contractor")
    >>> sov = ScheduleOfValues([SOVLine("03300", "Concrete", money("400000"))])
    >>> contract = Contract("C-100", owner, builder, sov)
    >>> context = RunContext(contract, monthly_schedule("2024-09-01", 3))
    >>> context.policy.name
    'default'
    >>> len(context.periods)
    3
    """

    def __init__(
        self,
        contract,
        periods,
        policy=None,
        progress=None,
        stored=None,
        costs=None,
        backcharges=None,
        offsets=None,
        tax_rule=None,
        waivers=None,
        insurance=None,
        insurance_requirements=None,
        notices=None,
        notice_events=None,
        applications=None,
        revisions=None,
        retainage_ledger=None,
        punchlist_value=None,
        trace=None,
    ):
        if not isinstance(contract, Contract):
            raise InputError("a run needs a Contract")
        self.contract = contract
        if not isinstance(periods, PeriodSchedule):
            raise InputError("a run needs a PeriodSchedule")
        self.periods = periods
        self.policy = policy if policy is not None else Policy()
        if not isinstance(self.policy, Policy):
            raise InputError("a run needs a Policy")
        currency = contract.currency
        self.progress = progress if progress is not None else ProgressLedger([], currency)
        self.stored = stored if stored is not None else StoredLedger([], currency)
        self.costs = costs if costs is not None else CostLedger([], currency)
        self.backcharges = (
            backcharges if backcharges is not None else BackChargeRegister([], currency)
        )
        self.offsets = offsets if offsets is not None else OffsetRegister([], currency)
        self.tax_rule = tax_rule
        self.waivers = waivers if waivers is not None else WaiverLedger([], currency)
        self.insurance = insurance
        self.insurance_requirements = dict(insurance_requirements or {})
        self.notices = notices
        self.notice_events = dict(notice_events or {})
        self.applications = (
            applications if applications is not None else ApplicationRegister([], currency)
        )
        self.revisions = revisions if revisions is not None else RevisionChain()
        self.retainage_ledger = (
            retainage_ledger if retainage_ledger is not None else RetainageLedger([], currency)
        )
        self.punchlist_value = punchlist_value
        self.trace = trace if trace is not None else Trace()

    @property
    def currency(self):
        """Return the currency every amount in this run is in."""
        return self.contract.currency

    def period(self, number):
        """Return one billing period by number."""
        return self.periods.period(number)

    def schedule_for(self, number):
        """Return the billing schedule as it stands in a period.

        Change orders enter the schedule when they become billable under the
        policy threshold, measured at the period's end date.
        """
        period = self.period(number)
        return self.contract.billing_schedule(
            period.end, self.policy.get("change_order_threshold")
        )

    def contract_sum_at(self, number):
        """Return the contract sum as it stands in a period."""
        period = self.period(number)
        return self.contract.contract_sum(
            period.end, self.policy.get("change_order_threshold")
        )

    def previous_application(self, number):
        """Return the live application before a period, or ``None``."""
        earlier = [
            application
            for application in self.applications.previous_to(number)
            if not self.revisions.is_superseded(application.id)
            and application.status != "void"
        ]
        if not earlier:
            return None
        return earlier[-1]

    def with_policy(self, policy):
        """Return a copy of the context under a different policy.

        Used by ``compare``: the same documents, two readings.
        """
        return RunContext(
            self.contract,
            self.periods,
            policy,
            self.progress,
            self.stored,
            self.costs,
            self.backcharges,
            self.offsets,
            self.tax_rule,
            self.waivers,
            self.insurance,
            self.insurance_requirements,
            self.notices,
            self.notice_events,
            self.applications,
            self.revisions,
            self.retainage_ledger,
            self.punchlist_value,
            Trace(),
        )

    def validate(self):
        """Return the problems with the inputs, empty when they are usable."""
        problems = list(self.contract.validate())
        codes = set(self.contract.schedule.codes())
        for entry in self.progress:
            schedule = self.schedule_for(min(entry.period, len(self.periods)))
            if entry.code not in schedule:
                problems.append(
                    "progress reported on line %s, which is not in the schedule"
                    % (entry.code,)
                )
        for entry in self.stored:
            if entry.code not in codes:
                schedule = self.schedule_for(len(self.periods))
                if entry.code not in schedule:
                    problems.append(
                        "stored materials on line %s, which is not in the schedule"
                        % (entry.code,)
                    )
        for entry in self.progress:
            if entry.period > len(self.periods):
                problems.append(
                    "progress reported in period %d but the schedule has %d"
                    % (entry.period, len(self.periods))
                )
        return problems

    def __repr__(self):
        return "RunContext(%r, %d periods, policy %r)" % (
            self.contract.id,
            len(self.periods),
            self.policy.name,
        )
