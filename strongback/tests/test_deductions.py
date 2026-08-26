"""Back-charges, offsets, tax and allowance reconciliation."""

import unittest

from strongback.core.money import money
from strongback.deductions.allowance import Allowance, AllowanceRegister, reconcile_allowance
from strongback.deductions.backcharge import BackCharge, BackChargeRegister, apply_backcharges
from strongback.deductions.offset import Offset, OffsetRegister
from strongback.deductions.tax import TaxRule, tax_on
from strongback.errors import DataError, InputError


class BackChargeTest(unittest.TestCase):
    """Where a back-charge lands changes what it costs the payee."""

    def setUp(self):
        self.register = BackChargeRegister(
            [
                BackCharge("BC-1", money("10000"), 4, stage="gross"),
                BackCharge("BC-2", money("5000"), 4, stage="net"),
                BackCharge("BC-3", money("2500"), 4, stage="retainage"),
                BackCharge("BC-4", money("900"), 4, stage="net", disputed=True),
            ]
        )

    def test_a_gross_charge_reduces_the_billing(self):
        gross, retainage, net = apply_backcharges(
            money("200000"), money("20000"), self.register, 4
        )
        self.assertEqual(gross, money("190000"))

    def test_a_net_charge_leaves_the_billing_alone(self):
        gross, retainage, net = apply_backcharges(
            money("200000"), money("20000"), self.register, 4
        )
        self.assertEqual(net, money("5000"))

    def test_a_retainage_charge_comes_out_of_what_is_held(self):
        gross, retainage, net = apply_backcharges(
            money("200000"), money("20000"), self.register, 4
        )
        self.assertEqual(retainage, money("2500"))

    def test_disputed_charges_are_excluded_by_default(self):
        self.assertEqual(self.register.total_for_period(4, "net"), money("5000"))

    def test_disputed_charges_can_be_included(self):
        self.assertEqual(
            self.register.total_for_period(4, "net", allow_disputed=True), money("5900")
        )

    def test_a_negative_back_charge_is_refused(self):
        self.assertRaises(DataError, BackCharge, "BC-9", money("-1"), 1)

    def test_the_register_round_trips_through_plain_data(self):
        rebuilt = BackChargeRegister.from_list(self.register.to_list())
        self.assertEqual(rebuilt.total_for_period(4, "gross"), money("10000"))


class OffsetTest(unittest.TestCase):
    """Reversible offsets are still owed; absorbed ones are not."""

    def setUp(self):
        self.register = OffsetRegister(
            [
                Offset("OF-1", "lien", money("15000"), 5),
                Offset("OF-2", "liquidated_damages", money("9000"), 6),
                Offset("OF-3", "insurance", money("2000"), 4, resolved_on="2024-12-01"),
            ]
        )

    def test_open_offsets_exclude_the_resolved(self):
        self.assertEqual(self.register.open_total(6), money("24000"))

    def test_reversible_and_absorbed_are_reported_apart(self):
        self.assertEqual(self.register.reversible_total(6), money("15000"))
        self.assertEqual(self.register.absorbed_total(6), money("9000"))

    def test_an_offset_raised_later_is_not_open_yet(self):
        self.assertEqual(self.register.open_total(5), money("15000"))

    def test_resolving_an_offset_closes_it(self):
        self.register.get("OF-1").resolve("2025-01-15")
        self.assertEqual(self.register.open_total(6), money("9000"))

    def test_an_unknown_kind_is_refused(self):
        self.assertRaises(InputError, Offset, "OF-9", "vibes", money("1"), 1)


class TaxTest(unittest.TestCase):
    """When tax attaches decides whether stored material is taxed."""

    def test_material_only_tax_on_installation(self):
        rule = TaxRule("6%", "material_only", "installation")
        self.assertEqual(tax_on(money("100000"), "40%", money("20000"), rule), money("2400.0000"))

    def test_tax_on_delivery_reaches_stored_material(self):
        rule = TaxRule("6%", "material_only", "delivery")
        self.assertEqual(tax_on(money("100000"), "40%", money("20000"), rule), money("3600.0000"))

    def test_taxing_all_work_ignores_the_material_share(self):
        rule = TaxRule("6%", "all_work", "installation")
        self.assertEqual(tax_on(money("100000"), "40%", money("20000"), rule), money("6000.00"))

    def test_an_exempt_job_pays_nothing(self):
        rule = TaxRule("6%", exempt=True)
        self.assertEqual(tax_on(money("100000"), "40%", money("20000"), rule), money("0"))


class AllowanceTest(unittest.TestCase):
    """Markup on an allowance reconciliation is three different answers."""

    def test_cost_only_reconciliation(self):
        allowance = Allowance("11400", money("80000"), money("92000"), "15%", "included")
        self.assertEqual(reconcile_allowance(allowance), money("12000"))

    def test_markup_on_the_difference(self):
        allowance = Allowance("11400", money("80000"), money("92000"), "15%", "on_difference")
        self.assertEqual(reconcile_allowance(allowance), money("13800.00"))

    def test_an_underrun_credits_the_markup_back_on_the_difference(self):
        allowance = Allowance("11400", money("80000"), money("70000"), "15%", "on_difference")
        self.assertEqual(reconcile_allowance(allowance), money("-11500.00"))

    def test_markup_on_actual_can_leave_an_underrun_positive(self):
        allowance = Allowance("11400", money("80000"), money("70000"), "15%", "on_actual")
        self.assertEqual(reconcile_allowance(allowance), money("500.00"))

    def test_an_unreconciled_allowance_has_no_difference(self):
        allowance = Allowance("11400", money("80000"))
        self.assertRaises(DataError, allowance.difference)

    def test_the_register_separates_open_from_reconciled(self):
        register = AllowanceRegister(
            [
                Allowance("11400", money("80000"), money("92000"), "15%"),
                Allowance("12500", money("40000")),
            ]
        )
        self.assertEqual([item.code for item in register.outstanding()], ["12500"])
        self.assertEqual(register.net_adjustment(), money("13800.00"))
        self.assertEqual(register.outstanding_value(), money("40000"))


if __name__ == "__main__":
    unittest.main()
