"""The run: the order of the stages and the numbers they produce."""

import unittest

from strongback.core.money import money
from strongback.core.percent import Rate
from strongback.core.period import monthly_schedule
from strongback.core.quantity import quantity
from strongback.dataio.samples import sample_context
from strongback.deductions.backcharge import BackCharge, BackChargeRegister
from strongback.engine.context import RunContext
from strongback.engine.run import build_application, rebuild_register, run_contract
from strongback.engine.stages import accrue_retainage, assemble_sheet, value_periods
from strongback.errors import InputError
from strongback.model.sov import SOVLine
from strongback.policy.resolve import Policy
from strongback.progress.observation import ProgressEntry, ProgressLedger
from strongback.progress.stored import StoredEntry, StoredLedger
from strongback.retainage.terms import RetainageTerms, Stepdown
from tests.support import contract, line, progress, schedule


def simple_context(periods=3, retainage=None, ledger=None, **kwargs):
    """A two-line job with reported progress."""
    sov = schedule(line("01000", "100000", description="General"), line("03300", "400000"))
    return RunContext(
        contract(sov, retainage),
        monthly_schedule("2024-09-01", periods),
        progress=ledger
        if ledger is not None
        else progress(("01000", 1, "30%"), ("03300", 1, "25%"), ("03300", 2, "60%")),
        **kwargs
    )


class ValuationStageTest(unittest.TestCase):
    """Valuation runs over every period, not just the one being billed."""

    def test_a_series_covers_every_period_up_to_the_one_billed(self):
        series = value_periods(simple_context(), 2)
        self.assertEqual([value.period for value in series["03300"]], [1, 2])

    def test_the_completion_fraction_is_contract_wide(self):
        series = value_periods(simple_context(), 1)
        self.assertEqual(series["03300"][0].completion, Rate("0.26"))

    def test_a_line_with_no_report_is_still_valued_at_zero(self):
        series = value_periods(simple_context(), 2)
        self.assertEqual(series["01000"][1].earned, money("30000.00"))


class SheetAssemblyTest(unittest.TestCase):
    """This period is always a difference of two cumulative figures."""

    def setUp(self):
        self.context = simple_context()
        self.series = value_periods(self.context, 2)
        self.accrued = accrue_retainage(self.context, self.series, 2)
        self.sheet = assemble_sheet(self.context, self.series, self.accrued, 2)

    def test_previous_and_this_period_split_the_to_date_figure(self):
        row = self.sheet["03300"]
        self.assertEqual(row.previous, money("100000.00"))
        self.assertEqual(row.this_period, money("140000.00"))

    def test_retainage_carries_its_previous_balance(self):
        row = self.sheet["03300"]
        self.assertEqual(row.previous_retainage, money("10000.00"))
        self.assertEqual(row.retainage, money("24000.00"))

    def test_a_line_that_did_not_move_bills_nothing_this_period(self):
        row = self.sheet["01000"]
        self.assertEqual(row.this_period, money("0.00"))


class ApplicationTest(unittest.TestCase):
    """One period, one document, and the diagnostics that come with it."""

    def test_the_summary_matches_the_sheet(self):
        result = build_application(simple_context(), 1, evaluate=False)
        self.assertEqual(
            result.summary.completed_and_stored, result.sheet.total_completed_and_stored()
        )
        self.assertEqual(result.summary.total_retainage(), result.sheet.total_retainage())

    def test_the_payment_is_earned_less_retainage_less_previous(self):
        result = build_application(simple_context(), 1, evaluate=False)
        self.assertEqual(result.payment_due(), money("117000.00"))

    def test_a_second_period_nets_off_the_first(self):
        results = run_contract(simple_context())
        self.assertEqual(results[1].summary.previous_certificates, results[0].payment_due())

    def test_the_run_is_clean_when_nothing_is_wrong(self):
        result = build_application(simple_context(), 1, evaluate=False)
        self.assertTrue(result.is_clean())

    def test_an_overbilled_line_is_diagnosed(self):
        ledger = progress(("03300", 1, "120%"))
        context = simple_context(ledger=ledger)
        context.policy = Policy(None, {"over_hundred": "allow"})
        result = build_application(context, 1, evaluate=False)
        self.assertTrue(any("billed" in item for item in result.diagnostics))

    def test_overbilling_can_be_allowed(self):
        ledger = progress(("03300", 1, "120%"))
        context = simple_context(ledger=ledger)
        context.policy = Policy(None, {"over_hundred": "allow", "allow_overbilling": "yes"})
        result = build_application(context, 1, evaluate=False)
        self.assertEqual(result.diagnostics, [])

    def test_the_trace_records_a_decision_for_every_line(self):
        result = build_application(simple_context(), 1, evaluate=False)
        self.assertIn("03300", result.trace.subjects())

    def test_the_engine_needs_a_run_context(self):
        self.assertRaises(InputError, build_application, "not a context", 1)


class StepdownRunTest(unittest.TestCase):
    """The step-down mode changes the payment, not just the balance."""

    def setUp(self):
        self.ledger = progress(("03300", 1, "40%"), ("03300", 2, "70%"))
        self.sov = schedule(line("03300", "500000"))

    def _run(self, mode):
        terms = RetainageTerms(
            "10%", stepdowns=[Stepdown("50%", "5%")], stepdown_mode=mode
        )
        context = RunContext(
            contract(self.sov, terms),
            monthly_schedule("2024-09-01", 3),
            progress=self.ledger,
        )
        return run_contract(context)

    def test_prospectively_the_earlier_retainage_stays_held(self):
        results = self._run("prospective")
        self.assertEqual(results[1].summary.total_retainage(), money("27500.00"))

    def test_retroactively_the_balance_is_re_rated(self):
        results = self._run("retroactive")
        self.assertEqual(results[1].summary.total_retainage(), money("17500.00"))

    def test_the_difference_lands_in_the_payment(self):
        prospective = self._run("prospective")[1].payment_due()
        retroactive = self._run("retroactive")[1].payment_due()
        self.assertEqual(retroactive - prospective, money("10000.00"))


class DeductionRunTest(unittest.TestCase):
    """A back-charge lands where the contract says it lands."""

    def _run(self, stage):
        charges = BackChargeRegister([BackCharge("BC-1", money("10000"), 1, stage=stage)])
        context = simple_context(backcharges=charges)
        return build_application(context, 1, evaluate=False)

    def test_a_net_charge_leaves_retainage_alone(self):
        result = self._run("net")
        self.assertEqual(result.summary.total_retainage(), money("13000.00"))
        self.assertEqual(result.payment_due(), money("107000.00"))

    def test_a_gross_charge_reduces_the_payment_by_the_same_amount(self):
        result = self._run("gross")
        self.assertEqual(result.payment_due(), money("107000.00"))

    def test_the_deduction_is_reported_separately(self):
        result = self._run("net")
        self.assertEqual(result.deductions["net"], money("10000"))


class SampleJobTest(unittest.TestCase):
    """The worked example exercises the awkward parts."""

    def setUp(self):
        self.context = sample_context(4)
        self.results = run_contract(self.context)

    def test_every_period_produces_an_application(self):
        self.assertEqual([result.application.number for result in self.results], [1, 2, 3, 4])

    def test_the_contract_sum_grows_with_the_executed_change_orders(self):
        self.assertEqual(self.results[0].summary.contract_sum(), money("2450000"))
        self.assertEqual(self.results[1].summary.contract_sum(), money("2518000"))

    def test_stored_materials_reach_the_sheet(self):
        self.assertEqual(self.results[3].summary.stored, money("165000"))

    def test_offsite_material_is_left_off_by_default(self):
        row = self.results[3].sheet["08400"]
        self.assertEqual(row.stored, money("0"))

    def test_the_unit_price_overrun_bills_at_the_rate(self):
        row = self.results[2].sheet["31200"]
        self.assertEqual(row.completed_and_stored(), money("248000"))

    def test_a_register_can_be_rebuilt_from_the_results(self):
        register = rebuild_register(self.context, self.results)
        self.assertEqual(len(register), 4)

    def test_a_policy_change_moves_the_payment(self):
        other = self.context.with_policy(Policy("owner_favorable"))
        theirs = run_contract(other)
        self.assertEqual(
            self.results[2].payment_due() - theirs[2].payment_due(), money("18675.00")
        )

    def test_a_policy_change_moves_what_has_been_billed_to_date(self):
        other = self.context.with_policy(Policy("owner_favorable"))
        theirs = run_contract(other)
        self.assertEqual(
            self.results[3].summary.completed_and_stored
            - theirs[3].summary.completed_and_stored,
            money("20750.00"),
        )


if __name__ == "__main__":
    unittest.main()
