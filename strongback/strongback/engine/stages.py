"""The stages of a run, in the order they have to happen.

Each stage is a function of the context and the stages before it, and each one
records what it decided in the trace.  The order is not arbitrary:

1. *value* -- what is the work in place worth, per line, in every period up to
   this one?  Every period, because retainage under a prospective step-down
   depends on the history and not just on today.
2. *store* -- what stored material is billable, given how much of it has become
   work in place?
3. *retain* -- accrue retainage over the series, honouring the step-down mode.
4. *assemble* -- turn the to-date figures into continuation rows, where "this
   period" is the difference between two to-date figures.
5. *deduct* -- back-charges, offsets and tax, each at its stated stage.
6. *summarise* -- the nine lines, from the sheet and the previous application.

Stage 4 is worth dwelling on.  Nothing in this package computes a "this period"
figure directly; it is always a difference of two cumulative figures.  That is
what makes a corrected prior period flow through instead of double-counting.
"""

from decimal import Decimal

from ..billing.line import ApplicationLine
from ..billing.continuation import ContinuationSheet
from ..billing.summary import ApplicationSummary
from ..core.money import zero
from ..core.percent import Rate
from ..deductions.backcharge import apply_backcharges
from ..deductions.tax import tax_on
from ..errors import DataError
from ..progress.method import earned_to_date
from ..progress.stored import stored_on_hand
from ..retainage.accrual import PeriodValue, accrue_line, apply_cap
from ..retainage.release import substantial_completion_release

__all__ = [
    "value_periods",
    "accrue_retainage",
    "assemble_sheet",
    "compute_deductions",
    "build_summary",
]


def value_periods(context, through):
    """Return, for every period up to ``through``, the earned and stored values.

    The result is ``{code: [PeriodValue, ...]}`` with one entry per period the
    line existed in, plus the contract-level completion in each period, which
    is what a retainage step-down keys off.

    >>> from ..core.money import money
    >>> from ..core.period import monthly_schedule
    >>> from ..model.contract import Contract
    >>> from ..model.parties import Party
    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> from ..progress.observation import ProgressEntry, ProgressLedger
    >>> from .context import RunContext
    >>> owner = Party("OWN", "Owner", "owner")
    >>> builder = Party("GC", "Builder", "contractor")
    >>> sov = ScheduleOfValues([SOVLine("03300", "Concrete", money("400000"))])
    >>> progress = ProgressLedger([ProgressEntry("03300", 1, percent="25%"),
    ...                            ProgressEntry("03300", 2, percent="60%")])
    >>> context = RunContext(Contract("C-1", owner, builder, sov),
    ...                      monthly_schedule("2024-09-01", 3), progress=progress)
    >>> series = value_periods(context, 2)
    >>> [str(value.earned) for value in series["03300"]]
    ['$100,000.00', '$240,000.00']
    >>> str(series["03300"][1].completion)
    '60%'
    """
    policy = context.policy
    progress_options = policy.progress_options()
    stored_options = policy.stored_options()
    series = {}
    for number in range(1, int(through) + 1):
        schedule = context.schedule_for(number)
        contract_sum = context.contract_sum_at(number)
        earned_this_period = {}
        for line in schedule.ordered():
            earned_this_period[line.code] = earned_to_date(
                line, context.progress, number, progress_options, context.trace
            )
        total_earned = zero(context.currency)
        for value in earned_this_period.values():
            total_earned = total_earned + value
        completion = (
            Rate(total_earned.ratio_to(contract_sum))
            if not contract_sum.is_zero()
            else Rate(Decimal(0))
        )
        for line in schedule.ordered():
            earned = earned_this_period[line.code]
            line_completion = (
                Rate(earned.ratio_to(line.scheduled_value))
                if not line.scheduled_value.is_zero()
                else Rate(Decimal(0))
            )
            stored = stored_on_hand(
                line, context.stored, number, line_completion, stored_options, context.trace
            )
            series.setdefault(line.code, []).append(
                PeriodValue(number, earned, stored, completion)
            )
    return series


def accrue_retainage(context, series, through):
    """Return the retainage accrual series for every line.

    >>> from ..core.money import money
    >>> from ..core.period import monthly_schedule
    >>> from ..model.contract import Contract
    >>> from ..model.parties import Party
    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> from ..progress.observation import ProgressEntry, ProgressLedger
    >>> from .context import RunContext
    >>> owner = Party("OWN", "Owner", "owner")
    >>> builder = Party("GC", "Builder", "contractor")
    >>> sov = ScheduleOfValues([SOVLine("03300", "Concrete", money("400000"))])
    >>> progress = ProgressLedger([ProgressEntry("03300", 1, percent="25%")])
    >>> context = RunContext(Contract("C-1", owner, builder, sov),
    ...                      monthly_schedule("2024-09-01", 2), progress=progress)
    >>> accrued = accrue_retainage(context, value_periods(context, 1), 1)
    >>> str(accrued["03300"][0].retained_to_date)
    '$10,000.00'
    """
    options = context.policy.retainage_options()
    terms = context.contract.retainage
    schedule = context.schedule_for(through)
    accrued = {}
    for code, values in series.items():
        line = schedule.get(code)
        if line is None:
            continue
        accrued[code] = accrue_line(line, values, terms, options, context.trace)
    return accrued


def assemble_sheet(context, series, accrued, number):
    """Turn to-date figures into a continuation sheet for one period.

    >>> from ..core.money import money
    >>> from ..core.period import monthly_schedule
    >>> from ..model.contract import Contract
    >>> from ..model.parties import Party
    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> from ..progress.observation import ProgressEntry, ProgressLedger
    >>> from .context import RunContext
    >>> owner = Party("OWN", "Owner", "owner")
    >>> builder = Party("GC", "Builder", "contractor")
    >>> sov = ScheduleOfValues([SOVLine("03300", "Concrete", money("400000"))])
    >>> progress = ProgressLedger([ProgressEntry("03300", 1, percent="25%"),
    ...                            ProgressEntry("03300", 2, percent="60%")])
    >>> context = RunContext(Contract("C-1", owner, builder, sov),
    ...                      monthly_schedule("2024-09-01", 3), progress=progress)
    >>> series = value_periods(context, 2)
    >>> accrued = accrue_retainage(context, series, 2)
    >>> sheet = assemble_sheet(context, series, accrued, 2)
    >>> row = sheet["03300"]
    >>> str(row.previous), str(row.this_period), str(row.retainage)
    ('$100,000.00', '$140,000.00', '$24,000.00')
    """
    schedule = context.schedule_for(number)
    sheet = ContinuationSheet([], context.currency)
    for line in schedule.ordered():
        values = series.get(line.code, [])
        current = None
        previous = None
        for value in values:
            if value.period == number:
                current = value
            elif value.period == number - 1:
                previous = value
        if current is None:
            continue
        retained = zero(context.currency)
        previous_retained = zero(context.currency)
        for step in accrued.get(line.code, ()):
            if step.period == number:
                retained = step.retained_to_date
            elif step.period == number - 1:
                previous_retained = step.retained_to_date
        previous_work = previous.earned if previous is not None else zero(context.currency)
        previous_stored = previous.stored if previous is not None else zero(context.currency)
        sheet.add(
            ApplicationLine(
                line.code,
                line.description,
                line.scheduled_value,
                previous=previous_work,
                this_period=current.earned - previous_work,
                stored=current.stored,
                previous_stored=previous_stored,
                retainage=retained,
                previous_retainage=previous_retained,
                rate=context.contract.retainage.rate_for_line(line, current.completion),
                kind=str(line.kind),
                group=line.group,
                change_order=line.change_order,
            )
        )
    return sheet


def compute_deductions(context, sheet, number):
    """Return the deductions that apply to one period's billing.

    The result carries the gross adjustment separately from the net one,
    because a back-charge taken before retainage changes the retainage base and
    one taken after does not.

    >>> from ..core.money import money
    >>> from ..core.period import monthly_schedule
    >>> from ..deductions.backcharge import BackCharge, BackChargeRegister
    >>> from ..model.contract import Contract
    >>> from ..model.parties import Party
    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> from .context import RunContext
    >>> owner = Party("OWN", "Owner", "owner")
    >>> builder = Party("GC", "Builder", "contractor")
    >>> sov = ScheduleOfValues([SOVLine("03300", "Concrete", money("400000"))])
    >>> charges = BackChargeRegister([BackCharge("BC-1", money("2500"), 2, stage="net")])
    >>> context = RunContext(Contract("C-1", owner, builder, sov),
    ...                      monthly_schedule("2024-09-01", 3), backcharges=charges)
    >>> sheet = ContinuationSheet([], "USD")
    >>> result = compute_deductions(context, sheet, 2)
    >>> str(result["net"]), str(result["gross"])
    ('$2,500.00', '$0.00')
    """
    policy = context.policy
    allow_disputed = policy.flag("backcharge_allow_disputed")
    gross_billing = sheet.total_this_period() + sheet.total_stored()
    retainage = sheet.total_retainage()
    adjusted_gross, retainage_charges, net_charges = apply_backcharges(
        gross_billing, retainage, context.backcharges, number, allow_disputed, context.trace
    )
    offsets = context.offsets.open_total(number)
    tax = zero(context.currency)
    if context.tax_rule is not None:
        tax = tax_on(
            sheet.total_this_period(),
            policy.get("tax_material_share"),
            sheet.total_stored(),
            context.tax_rule,
            context.trace,
        )
    return {
        "gross": gross_billing - adjusted_gross,
        "net": net_charges,
        "retainage": retainage_charges,
        "offsets": offsets,
        "tax": tax,
        "total": (gross_billing - adjusted_gross) + net_charges + offsets,
    }


def build_summary(context, sheet, deductions, number):
    """Return the summary page for one period.

    >>> from ..core.money import money
    >>> from ..core.period import monthly_schedule
    >>> from ..model.contract import Contract
    >>> from ..model.parties import Party
    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> from ..progress.observation import ProgressEntry, ProgressLedger
    >>> from .context import RunContext
    >>> owner = Party("OWN", "Owner", "owner")
    >>> builder = Party("GC", "Builder", "contractor")
    >>> sov = ScheduleOfValues([SOVLine("03300", "Concrete", money("400000"))])
    >>> progress = ProgressLedger([ProgressEntry("03300", 1, percent="25%")])
    >>> context = RunContext(Contract("C-1", owner, builder, sov),
    ...                      monthly_schedule("2024-09-01", 2), progress=progress)
    >>> series = value_periods(context, 1)
    >>> accrued = accrue_retainage(context, series, 1)
    >>> sheet = assemble_sheet(context, series, accrued, 1)
    >>> summary = build_summary(context, sheet, compute_deductions(context, sheet, 1), 1)
    >>> str(summary.current_payment_due())
    '$90,000.00'
    """
    policy = context.policy
    contract = context.contract
    period = context.period(number)
    retainage = sheet.total_retainage()
    work_retainage = sheet.retainage_on_work()
    stored_retainage = retainage - work_retainage
    if policy.flag("retainage_apply_cap"):
        capped, bound = apply_cap(
            retainage,
            context.contract_sum_at(number),
            sheet.total_completed_and_stored(),
            contract.retainage,
            context.trace,
        )
        if bound:
            share = capped.ratio_to(retainage) if not retainage.is_zero() else Decimal(0)
            work_retainage = work_retainage * share
            stored_retainage = capped - work_retainage
    released = zero(context.currency)
    if contract.completion.is_substantially_complete(period.end):
        released, _held = substantial_completion_release(
            work_retainage + stored_retainage,
            contract.retainage,
            context.punchlist_value,
            context.trace,
        )
        work_retainage = work_retainage - released
        if work_retainage.is_negative():
            stored_retainage = stored_retainage + work_retainage
            work_retainage = zero(context.currency)
    previous = context.revisions.previous_certified(
        context.applications, number, policy.get("previous_basis")
    )
    return ApplicationSummary(
        original=contract.original_sum(),
        change_orders=contract.change_order_sum(
            period.end, policy.get("change_order_threshold")
        ),
        completed_and_stored=sheet.total_completed_and_stored(),
        work_completed=sheet.total_work_to_date(),
        stored=sheet.total_stored(),
        retainage_work=work_retainage,
        retainage_stored=stored_retainage,
        previous_certificates=previous,
        previous_basis=policy.get("previous_basis"),
        deductions=deductions["total"],
        tax=deductions["tax"],
    )
