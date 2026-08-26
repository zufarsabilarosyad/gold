"""A worked example: one job, six months, and every convention exercised.

The sample is the fixture the examples, the tests and ``strongback demo`` all
share.  It is deliberately awkward -- a step-down that lands mid-job, stored
switchgear that converts, a change order that is directed before it is
executed, a back-charge and a disputed one, a unit-price line that overruns --
because a sample where nothing is difficult proves nothing.

Everything here is a constant.  No dates are computed from a clock and no
figures are random, so the sample renders the same output today and next year.
"""

from ..core.money import money
from ..core.period import monthly_schedule
from ..core.quantity import quantity
from ..deductions.backcharge import BackCharge, BackChargeRegister
from ..deductions.offset import Offset, OffsetRegister
from ..model.changeorder import ChangeOrder, ChangeOrderLog
from ..model.contract import Contract
from ..model.parties import Party
from ..model.sov import ScheduleOfValues, SOVLine
from ..model.terms import CompletionDates, LiquidatedDamages, PaymentTerms
from ..progress.costtocost import CostEntry, CostLedger
from ..progress.observation import ProgressEntry, ProgressLedger
from ..progress.stored import StoredEntry, StoredLedger
from ..retainage.terms import RetainageTerms, Stepdown
from ..waivers.document import LienWaiver
from ..waivers.ledger import WaiverLedger

__all__ = [
    "sample_contract",
    "sample_progress",
    "sample_stored",
    "sample_costs",
    "sample_periods",
    "sample_backcharges",
    "sample_offsets",
    "sample_waivers",
    "sample_context",
]


def sample_parties():
    """Return the owner and the general contractor of the sample job.

    >>> owner, builder = sample_parties()
    >>> owner.name
    'Harbor Point Holdings LLC'
    """
    return (
        Party("OWN", "Harbor Point Holdings LLC", "owner", address="14 Wharf Road"),
        Party("GC", "Keel & Sons Construction", "contractor", license_number="C-88214"),
    )


def sample_schedule():
    """Return the sample schedule of values.

    >>> str(sample_schedule().total())
    '$2,450,000.00'
    """
    return ScheduleOfValues(
        [
            SOVLine("01000", "General conditions", money("180000"), "01000", group="General"),
            SOVLine("02200", "Site demolition", money("95000"), "02200", group="Sitework"),
            SOVLine(
                "31200",
                "Mass excavation",
                money("240000"),
                "31200",
                kind="unit_price",
                unit_quantity=quantity("12000", "cy"),
                unit_rate=money("20"),
                group="Sitework",
            ),
            SOVLine("03100", "Foundations", money("410000"), "03100", group="Structure"),
            SOVLine("03300", "Slab on grade", money("265000"), "03300", group="Structure"),
            SOVLine("05100", "Structural steel", money("520000"), "05100", group="Structure",
                    stored_eligible=True),
            SOVLine("07500", "Roofing", money("185000"), "07500", group="Envelope"),
            SOVLine("08400", "Curtain wall", money("230000"), "08400", group="Envelope",
                    stored_eligible=True),
            SOVLine("09900", "Painting", money("75000"), "09900", group="Finishes"),
            SOVLine("26200", "Switchgear and distribution", money("250000"), "26200",
                    group="Electrical", stored_eligible=True),
        ]
    )


def sample_change_orders():
    """Return the sample change order log.

    >>> log = sample_change_orders()
    >>> [order.id for order in log]
    ['CO-001', 'CO-002', 'CO-003']
    >>> str(log.value_under("executed_only", "2024-12-31"))
    '$53,000.00'
    """
    first = ChangeOrder(
        "CO-001",
        1,
        "Rock excavation beyond the geotechnical report",
        status="executed",
        date_priced="2024-10-08",
        date_approved="2024-10-15",
        date_executed="2024-10-22",
        reason="differing site condition",
    )
    first.add_line(SOVLine("31250", "Rock excavation", money("68000"), "31200", group="Sitework"))
    second = ChangeOrder(
        "CO-002",
        2,
        "Storefront upgrade at the lobby",
        status="directed",
        date_priced="2024-11-06",
        date_directed="2024-11-12",
        reason="owner election",
        retainage_rate="5%",
    )
    second.add_line(SOVLine("08450", "Lobby storefront", money("42000"), "08400", group="Envelope"))
    third = ChangeOrder(
        "CO-003",
        3,
        "Deleted planter irrigation",
        status="executed",
        date_priced="2024-12-02",
        date_approved="2024-12-09",
        date_executed="2024-12-16",
        reason="scope deletion",
    )
    third.add_line(SOVLine("32800", "Planter irrigation", money("-15000"), "32800", group="Sitework"))
    return ChangeOrderLog([first, second, third])


def sample_contract():
    """Return the sample contract, retainage step-down and all.

    >>> contract = sample_contract()
    >>> str(contract.original_sum())
    '$2,450,000.00'
    >>> str(contract.retainage.base_rate)
    '10%'
    >>> [str(step) for step in contract.retainage.stepdowns]
    ['at 50% completion, 5%']
    """
    owner, builder = sample_parties()
    retainage = RetainageTerms(
        "10%",
        change_order_rate=None,
        stored_materials_retained=True,
        basis="work_and_stored",
        stepdowns=[Stepdown("50%", "5%", note="upon fifty percent completion")],
        stepdown_mode="prospective",
        cap_rate=None,
        cap_basis="none",
        release_at_substantial="90%",
        punchlist_multiple="1.5",
        final_release_days=30,
    )
    return Contract(
        "C-2024-118",
        owner,
        builder,
        sample_schedule(),
        retainage,
        PaymentTerms(net_days=30, start_event="certification_date", certification_days=7),
        CompletionDates(
            notice_to_proceed="2024-09-16",
            contract_completion="2025-08-29",
        ),
        sample_change_orders(),
        None,
        LiquidatedDamages(money("2500"), cap=money("125000"), grace_days=0),
        "us-federal",
        "USD",
        "Harbor Point Phase II -- shell and core",
        signed_on="2024-09-09",
        billable_threshold="executed_only",
    )


def sample_periods(count=4):
    """Return the sample billing periods.

    >>> str(sample_periods(2).period(2))
    '#2 2024-10-01..2024-10-31'
    """
    return monthly_schedule("2024-09-01", count, through_day=25)


def sample_progress(periods=None):
    """Return the sample field reports, optionally truncated to a period.

    >>> ledger = sample_progress()
    >>> str(ledger.latest_percent("03100", 3))
    '85%'
    >>> len(sample_progress(1))
    3
    """
    ledger = ProgressLedger(
        [
            ProgressEntry("01000", 1, percent="12%", reported_by="site"),
            ProgressEntry("02200", 1, percent="60%", reported_by="site"),
            ProgressEntry("31200", 1, installed=quantity("3400", "cy"), reference="field book 4"),
            ProgressEntry("01000", 2, percent="30%"),
            ProgressEntry("02200", 2, percent="100%"),
            ProgressEntry("31200", 2, installed=quantity("7900", "cy")),
            ProgressEntry("03100", 2, percent="35%"),
            ProgressEntry("31250", 2, percent="55%"),
            ProgressEntry("01000", 3, percent="48%"),
            ProgressEntry("31200", 3, installed=quantity("12400", "cy")),
            ProgressEntry("03100", 3, percent="85%"),
            ProgressEntry("03300", 3, percent="40%"),
            ProgressEntry("05100", 3, percent="15%"),
            ProgressEntry("31250", 3, percent="100%"),
            ProgressEntry("01000", 4, percent="62%"),
            ProgressEntry("03100", 4, percent="100%"),
            ProgressEntry("03300", 4, percent="90%"),
            ProgressEntry("05100", 4, percent="55%"),
            ProgressEntry("07500", 4, percent="10%"),
            ProgressEntry("26200", 4, percent="5%"),
        ]
    )
    if periods is None:
        return ledger
    return ProgressLedger(
        [entry for entry in ledger if entry.period <= int(periods)], ledger.currency
    )


def sample_stored(periods=None):
    """Return the sample stored-materials movements, optionally truncated.

    >>> str(sample_stored().delivered_to_date("26200", 4))
    '$120,000.00'
    >>> len(sample_stored(3))
    1
    """
    ledger = StoredLedger(
        [
            StoredEntry("05100", 3, delivered=money("85000"), invoice="MIL-4471",
                        description="steel deck and joists"),
            StoredEntry("05100", 4, converted=money("40000")),
            StoredEntry("26200", 4, delivered=money("120000"), invoice="SG-1188",
                        description="switchgear"),
            StoredEntry("08400", 4, delivered=money("38000"), offsite=True, insured=True,
                        invoice="CW-2210", description="curtain wall glass, warehouse"),
        ]
    )
    if periods is None:
        return ledger
    return StoredLedger(
        [entry for entry in ledger if entry.period <= int(periods)], ledger.currency
    )


def sample_costs(periods=None):
    """Return the sample cost postings, optionally truncated to a period.

    >>> str(sample_costs().incurred_to_date("03100", 4))
    '$318,000.00'
    >>> str(sample_costs(2).incurred_to_date("03100", 4))
    '$128,000.00'
    """
    ledger = CostLedger(
        [
            CostEntry("01000", 1, money("21000"), "labor"),
            CostEntry("02200", 1, money("52000"), "subcontract"),
            CostEntry("31200", 1, money("61000"), "equipment"),
            CostEntry("01000", 2, money("24000"), "labor"),
            CostEntry("02200", 2, money("39000"), "subcontract"),
            CostEntry("31200", 2, money("83000"), "equipment"),
            CostEntry("03100", 2, money("128000"), "subcontract"),
            CostEntry("01000", 3, money("23000"), "labor"),
            CostEntry("31200", 3, money("74000"), "equipment"),
            CostEntry("03100", 3, money("152000"), "subcontract"),
            CostEntry("03300", 3, money("96000"), "subcontract"),
            CostEntry("01000", 4, money("26000"), "labor"),
            CostEntry("03100", 4, money("38000"), "subcontract"),
            CostEntry("03300", 4, money("118000"), "subcontract"),
            CostEntry("05100", 4, money("214000"), "subcontract"),
        ]
    )
    if periods is None:
        return ledger
    return CostLedger(
        [entry for entry in ledger if entry.period <= int(periods)], ledger.currency
    )


def sample_backcharges(periods=None):
    """Return the sample back-charges, one of them disputed.

    >>> [charge.id for charge in sample_backcharges()]
    ['BC-01', 'BC-02']
    >>> [charge.id for charge in sample_backcharges(3)]
    ['BC-01']
    """
    register = BackChargeRegister(
        [
            BackCharge("BC-01", money("4200"), 3, stage="net", code="01000",
                       reason="site cleanup by others", issued_on="2024-11-27"),
            BackCharge("BC-02", money("9800"), 4, stage="gross", code="05100",
                       reason="crane standby, disputed", issued_on="2024-12-18",
                       disputed=True),
        ]
    )
    if periods is None:
        return register
    return BackChargeRegister(
        [charge for charge in register if charge.period <= int(periods)], register.currency
    )


def sample_offsets(periods=None):
    """Return the sample offsets, optionally truncated to a period.

    >>> [offset.kind for offset in sample_offsets()]
    ['lien']
    >>> len(sample_offsets(3))
    0
    """
    register = OffsetRegister(
        [
            Offset("OF-01", "lien", money("18500"), 4, reason="second-tier steel supplier",
                   raised_on="2024-12-20"),
        ]
    )
    if periods is None:
        return register
    return OffsetRegister(
        [offset for offset in register if offset.period <= int(periods)], register.currency
    )


def sample_waivers():
    """Return the sample waiver log.

    >>> [waiver.id for waiver in sample_waivers()]
    ['W-001', 'W-002', 'W-003', 'W-004']
    """
    return WaiverLedger(
        [
            LienWaiver("W-001", "conditional_progress", money("152000"), "2024-09-30",
                       "2024-10-02", "PA-001", signer="Keel & Sons"),
            LienWaiver("W-002", "unconditional_progress", money("152000"), "2024-09-30",
                       "2024-11-08", "PA-001", signer="Keel & Sons"),
            LienWaiver("W-003", "conditional_progress", money("264000"), "2024-10-31",
                       "2024-11-04", "PA-002", signer="Keel & Sons"),
            LienWaiver("W-004", "conditional_progress", money("398000"), "2024-11-30",
                       "2024-12-03", "PA-003", signer="Keel & Sons"),
        ]
    )


def sample_context(periods=4, policy=None):
    """Return a ready-to-run context for the sample job.

    >>> from ..engine.run import build_application
    >>> context = sample_context()
    >>> result = build_application(context, 2, evaluate=False)
    >>> str(result.summary.contract_sum())
    '$2,518,000.00'
    """
    from ..engine.context import RunContext

    return RunContext(
        sample_contract(),
        sample_periods(periods),
        policy,
        sample_progress(periods),
        sample_stored(periods),
        sample_costs(periods),
        sample_backcharges(periods),
        sample_offsets(periods),
        None,
        sample_waivers(),
        punchlist_value=money("40000"),
    )
