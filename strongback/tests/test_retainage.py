"""Retainage: the base, the rate, the step-down mode, the cap and the release."""

import unittest

from strongback.core.money import money
from strongback.core.percent import Rate
from strongback.errors import DataError, InputError
from strongback.retainage.accrual import (
    PeriodValue,
    RetainageOptions,
    accrue_line,
    accrue_schedule,
    apply_cap,
)
from strongback.retainage.basis import base_components, is_retained, retainage_base
from strongback.retainage.ledger import RetainageEntry, RetainageLedger
from strongback.retainage.release import (
    ReleaseEvent,
    early_release,
    final_release,
    punchlist_holdback,
    substantial_completion_release,
)
from strongback.retainage.stepdown import effective_rate, stepdown_release
from strongback.retainage.terms import RetainageTerms, Stepdown, standard_terms
from tests.support import line, schedule


class BasisTest(unittest.TestCase):
    """What the rate applies to is three independent decisions."""

    def setUp(self):
        self.line = line("26200", "70000", stored_eligible=True)

    def test_work_and_stored_is_the_default(self):
        self.assertEqual(
            retainage_base(self.line, money("30000"), money("18000"), standard_terms()),
            money("48000"),
        )

    def test_stored_can_be_paid_in_full(self):
        terms = RetainageTerms("10%", stored_materials_retained=False)
        self.assertEqual(
            retainage_base(self.line, money("30000"), money("18000"), terms), money("30000")
        )

    def test_work_only_ignores_stored_material(self):
        terms = RetainageTerms("10%", basis="work_only")
        work, stored = base_components(self.line, money("30000"), money("18000"), terms)
        self.assertEqual(stored, money("0"))

    def test_change_order_work_can_be_out_of_the_base(self):
        change_line = line("08400", "42000", origin="CO-001", change_order="CO-001")
        terms = RetainageTerms("10%", basis="work_less_change_orders")
        self.assertFalse(is_retained(change_line, terms))
        self.assertEqual(
            retainage_base(change_line, money("20000"), money("0"), terms), money("0")
        )


class RateTest(unittest.TestCase):
    """The rate in force depends on completion, the line and certification."""

    def setUp(self):
        self.terms = RetainageTerms("10%", stepdowns=[Stepdown("50%", "5%")])

    def test_the_base_rate_applies_below_the_threshold(self):
        self.assertEqual(effective_rate(self.terms, Rate("0.4")), Rate("0.1"))

    def test_the_step_down_applies_at_the_threshold_exactly(self):
        self.assertEqual(effective_rate(self.terms, Rate("0.5")), Rate("0.05"))

    def test_a_line_rate_beats_everything(self):
        special = line("08400", "10000", retainage_rate="2%")
        self.assertEqual(effective_rate(self.terms, Rate("0.9"), special), Rate("0.02"))

    def test_a_change_order_rate_applies_to_change_order_lines(self):
        terms = RetainageTerms("10%", change_order_rate="5%")
        change_line = line("08400", "42000", origin="CO-001")
        self.assertEqual(effective_rate(terms, Rate("0.1"), change_line), Rate("0.05"))

    def test_an_uncertified_step_down_does_not_apply(self):
        gated = RetainageTerms(
            "10%", stepdowns=[Stepdown("50%", "5%", requires_certification=True)]
        )
        self.assertEqual(effective_rate(gated, Rate("0.8"), None, False), Rate("0.1"))

    def test_a_step_down_above_the_base_rate_is_refused(self):
        self.assertRaises(
            DataError, RetainageTerms, "5%", None, True, "work_and_stored", [Stepdown("50%", "10%")]
        )


class AccrualTest(unittest.TestCase):
    """The step-down mode is the difference between two cheques."""

    def setUp(self):
        self.line = line("03300", "500000")
        self.series = [
            PeriodValue(1, money("200000"), None, Rate("0.4")),
            PeriodValue(2, money("300000"), None, Rate("0.6")),
        ]

    def test_without_a_step_down_the_rate_is_flat(self):
        steps = accrue_line(self.line, self.series, standard_terms())
        self.assertEqual(
            [step.retained_to_date for step in steps], [money("20000.00"), money("30000.00")]
        )

    def test_prospectively_the_new_rate_applies_only_to_new_work(self):
        terms = RetainageTerms("10%", stepdowns=[Stepdown("50%", "5%")])
        steps = accrue_line(self.line, self.series, terms)
        self.assertEqual(steps[1].retained_to_date, money("25000.00"))

    def test_retroactively_the_new_rate_re_rates_everything(self):
        terms = RetainageTerms(
            "10%", stepdowns=[Stepdown("50%", "5%")], stepdown_mode="retroactive"
        )
        steps = accrue_line(self.line, self.series, terms)
        self.assertEqual(steps[1].retained_to_date, money("15000.00"))

    def test_a_retroactive_step_down_releases_the_difference(self):
        terms = RetainageTerms(
            "10%", stepdowns=[Stepdown("50%", "5%")], stepdown_mode="retroactive"
        )
        steps = accrue_line(self.line, self.series, terms)
        self.assertEqual(steps[1].release, money("5000.00"))
        self.assertEqual(stepdown_release(money("20000"), money("300000"), Rate("0.05")), money("5000.00"))

    def test_a_step_down_can_override_the_contract_mode(self):
        terms = RetainageTerms(
            "10%",
            stepdowns=[Stepdown("50%", "5%", mode="retroactive")],
            stepdown_mode="prospective",
        )
        steps = accrue_line(self.line, self.series, terms)
        self.assertEqual(steps[1].retained_to_date, money("15000.00"))

    def test_a_falling_base_gives_retainage_back_at_the_current_rate(self):
        series = [
            PeriodValue(1, money("300000"), None, Rate("0.6")),
            PeriodValue(2, money("290000"), None, Rate("0.58")),
        ]
        steps = accrue_line(self.line, series, standard_terms())
        self.assertEqual(steps[1].retained_this_period, money("-1000.00"))

    def test_rounding_at_the_line_stage_is_visible(self):
        series = [PeriodValue(1, money("33333.33"), None, Rate("0.1"))]
        steps = accrue_line(self.line, series, RetainageTerms("7.5%"))
        self.assertEqual(steps[0].retained_to_date, money("2500.00"))

    def test_rounding_can_be_deferred_to_the_summary(self):
        series = [PeriodValue(1, money("33333.33"), None, Rate("0.1"))]
        options = RetainageOptions(round_stage="summary")
        steps = accrue_line(self.line, series, RetainageTerms("7.5%"), options)
        self.assertEqual(str(steps[0].retained_to_date.amount), "2499.99975")

    def test_a_schedule_accrues_only_the_lines_with_a_series(self):
        sov = schedule(line("03300", "500000"), line("09900", "50000"))
        accrued = accrue_schedule(sov, {"03300": self.series}, standard_terms())
        self.assertEqual(sorted(accrued), ["03300"])


class CapTest(unittest.TestCase):
    """A ceiling against the contract sum, or against work completed."""

    def test_the_cap_binds_against_the_contract_sum(self):
        terms = RetainageTerms("10%", cap_rate="5%", cap_basis="contract_sum")
        held, bound = apply_cap(money("60000"), money("1000000"), money("600000"), terms)
        self.assertEqual(held, money("50000.00"))
        self.assertTrue(bound)

    def test_an_uncapped_clause_never_binds(self):
        held, bound = apply_cap(money("60000"), money("1000000"), money("600000"), standard_terms())
        self.assertEqual(held, money("60000"))
        self.assertFalse(bound)


class ReleaseTest(unittest.TestCase):
    """What comes back at substantial completion, and what is held."""

    def test_a_share_release_leaves_the_complement(self):
        terms = RetainageTerms("10%", release_at_substantial="90%")
        released, remaining = substantial_completion_release(money("100000"), terms)
        self.assertEqual(released, money("90000.0"))
        self.assertEqual(remaining, money("10000.0"))

    def test_a_punchlist_multiple_can_hold_more_than_the_share(self):
        terms = RetainageTerms("10%", release_at_substantial="90%", punchlist_multiple="2")
        released, remaining = substantial_completion_release(
            money("100000"), terms, money("20000")
        )
        self.assertEqual(released, money("60000"))
        self.assertEqual(remaining, money("40000"))

    def test_a_punchlist_bigger_than_the_balance_releases_nothing(self):
        terms = RetainageTerms("10%", release_at_substantial="90%", punchlist_multiple="2")
        released, remaining = substantial_completion_release(
            money("30000"), terms, money("40000")
        )
        self.assertEqual(released, money("0"))
        self.assertEqual(remaining, money("30000"))

    def test_a_clause_with_no_release_holds_everything(self):
        released, remaining = substantial_completion_release(money("50000"), standard_terms())
        self.assertEqual(released, money("0"))
        self.assertEqual(remaining, money("50000"))

    def test_the_punchlist_holdback_is_a_multiple_of_the_punchlist(self):
        terms = RetainageTerms("10%", punchlist_multiple="1.5")
        self.assertEqual(punchlist_holdback(money("30000"), terms), money("45000.0"))

    def test_final_deductions_come_out_of_the_release(self):
        released, withheld = final_release(money("40000"), money("6500"))
        self.assertEqual(released, money("33500"))
        self.assertEqual(withheld, money("6500"))

    def test_deductions_larger_than_the_balance_take_it_all(self):
        released, withheld = final_release(money("4000"), money("6500"))
        self.assertEqual(released, money("0"))
        self.assertEqual(withheld, money("4000"))

    def test_early_release_takes_the_named_lines(self):
        balances = {"31200": money("5000"), "03300": money("12000")}
        self.assertEqual(early_release(balances, ["31200"]), money("5000"))

    def test_a_negative_release_is_refused(self):
        self.assertRaises(DataError, ReleaseEvent, "final", money("-1"), 1)


class LedgerTest(unittest.TestCase):
    """The account remembers movements, not a balance."""

    def setUp(self):
        self.ledger = RetainageLedger()
        self.ledger.accrue("03300", 1, money("4000"))
        self.ledger.accrue("03300", 2, money("3000"))
        self.ledger.accrue("09900", 2, money("500"))
        self.ledger.release("03300", 3, money("2000"), "early release")

    def test_the_balance_is_the_sum_of_the_movements(self):
        self.assertEqual(self.ledger.balance(), money("5500"))

    def test_balances_can_be_taken_per_line(self):
        self.assertEqual(self.ledger.balance_for_line("03300"), money("5000"))

    def test_balances_can_be_taken_at_a_period(self):
        self.assertEqual(self.ledger.balance(2), money("7500"))

    def test_accrued_and_released_are_reported_separately(self):
        self.assertEqual(self.ledger.accrued_to_date(), money("7500"))
        self.assertEqual(self.ledger.released_to_date(), money("2000"))

    def test_an_overdraw_is_detectable(self):
        self.ledger.release("09900", 4, money("5000"))
        self.assertRaises(DataError, self.ledger.check_no_overdraw)

    def test_a_negative_accrual_is_refused(self):
        self.assertRaises(DataError, self.ledger.accrue, "03300", 5, money("-1"))

    def test_the_ledger_round_trips_through_plain_data(self):
        rebuilt = RetainageLedger.from_list(self.ledger.to_list())
        self.assertEqual(rebuilt.balance(), self.ledger.balance())


if __name__ == "__main__":
    unittest.main()
