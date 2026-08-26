"""Running a period, and running a whole job.

``build_application`` is the entry point everything else goes through: the CLI,
the comparison tool, and the tests.  It runs the stages in order, assembles the
document, evaluates the payment gates and returns a
:class:`~strongback.engine.result.RunResult`.

``run_contract`` runs every period in sequence, feeding each application into
the register before the next one is built.  That sequencing is what makes line
7 -- previous certificates -- correct without anybody having to store it.
"""

from ..billing.application import ApplicationRegister, PayApplication
from ..billing.numbering import format_application_id
from ..compliance.gate import evaluate_gates
from ..core.trace import Trace
from ..errors import DataError, InputError
from .context import RunContext
from .result import RunResult
from .stages import (
    accrue_retainage,
    assemble_sheet,
    build_summary,
    compute_deductions,
    value_periods,
)

__all__ = ["build_application", "run_contract", "rebuild_register"]


def build_application(context, number, identifier=None, application_date=None, evaluate=True):
    """Build one period's application.

    >>> from ..core.money import money
    >>> from ..core.period import monthly_schedule
    >>> from ..model.contract import Contract
    >>> from ..model.parties import Party
    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> from ..progress.observation import ProgressEntry, ProgressLedger
    >>> owner = Party("OWN", "Owner", "owner")
    >>> builder = Party("GC", "Builder", "contractor")
    >>> sov = ScheduleOfValues([SOVLine("01000", "General conditions", money("100000")),
    ...                         SOVLine("03300", "Concrete", money("400000"))])
    >>> progress = ProgressLedger([ProgressEntry("01000", 1, percent="30%"),
    ...                            ProgressEntry("03300", 1, percent="25%")])
    >>> context = RunContext(Contract("C-1", owner, builder, sov),
    ...                      monthly_schedule("2024-09-01", 3), progress=progress)
    >>> result = build_application(context, 1, evaluate=False)
    >>> str(result.summary.completed_and_stored)
    '$130,000.00'
    >>> str(result.summary.total_retainage())
    '$13,000.00'
    >>> str(result.payment_due())
    '$117,000.00'
    """
    if not isinstance(context, RunContext):
        raise InputError("build_application needs a RunContext")
    number = int(number)
    period = context.period(number)
    context.trace = Trace()
    diagnostics = list(context.validate())
    series = value_periods(context, number)
    accrued = accrue_retainage(context, series, number)
    sheet = assemble_sheet(context, series, accrued, number)
    deductions = compute_deductions(context, sheet, number)
    summary = build_summary(context, sheet, deductions, number)
    identifier = identifier or format_application_id(
        number, width=3
    )
    application = PayApplication(
        identifier,
        number,
        period,
        sheet=sheet,
        summary=summary,
        application_date=application_date or period.end,
        trace=context.trace,
        policy_name=context.policy.name,
    )
    diagnostics.extend(application.validate(context.policy.flag("allow_overbilling")))
    gates = None
    if evaluate:
        previous = context.previous_application(number)
        gates = evaluate_gates(
            application,
            context.policy.waiver_requirement(),
            context.waivers,
            context.insurance if context.policy.flag("gate_on_insurance") else None,
            context.insurance_requirements,
            context.notices,
            context.notice_events,
            period.end,
            previous.id if previous is not None else None,
        )
    return RunResult(application, gates, diagnostics, series, accrued, deductions)


def run_contract(context, through=None, evaluate=False):
    """Build every application up to a period, in order.

    >>> from ..core.money import money
    >>> from ..core.period import monthly_schedule
    >>> from ..model.contract import Contract
    >>> from ..model.parties import Party
    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> from ..progress.observation import ProgressEntry, ProgressLedger
    >>> owner = Party("OWN", "Owner", "owner")
    >>> builder = Party("GC", "Builder", "contractor")
    >>> sov = ScheduleOfValues([SOVLine("03300", "Concrete", money("400000"))])
    >>> progress = ProgressLedger([ProgressEntry("03300", 1, percent="25%"),
    ...                            ProgressEntry("03300", 2, percent="60%")])
    >>> context = RunContext(Contract("C-1", owner, builder, sov),
    ...                      monthly_schedule("2024-09-01", 2), progress=progress)
    >>> results = run_contract(context)
    >>> [str(result.payment_due()) for result in results]
    ['$90,000.00', '$126,000.00']

    The second application's line 7 is the first application's request, so the
    two payments sum to the earned-less-retainage figure rather than
    double-counting it:

    >>> str(results[1].summary.earned_less_retainage())
    '$216,000.00'
    """
    through = int(through) if through is not None else len(context.periods)
    register = ApplicationRegister(context.applications.ordered(), context.currency)
    results = []
    for number in range(1, through + 1):
        context.applications = register
        result = build_application(context, number, evaluate=evaluate)
        register = ApplicationRegister(
            [item for item in register.ordered() if item.number != number]
            + [result.application],
            context.currency,
        )
        results.append(result)
    context.applications = register
    return results


def rebuild_register(context, results):
    """Return a register holding the applications a run produced.

    >>> from ..core.money import money
    >>> from ..core.period import monthly_schedule
    >>> from ..model.contract import Contract
    >>> from ..model.parties import Party
    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> owner = Party("OWN", "Owner", "owner")
    >>> builder = Party("GC", "Builder", "contractor")
    >>> sov = ScheduleOfValues([SOVLine("03300", "Concrete", money("400000"))])
    >>> context = RunContext(Contract("C-1", owner, builder, sov),
    ...                      monthly_schedule("2024-09-01", 1))
    >>> results = run_contract(context)
    >>> len(rebuild_register(context, results))
    1
    """
    return ApplicationRegister(
        [result.application for result in results], context.currency
    )
