"""Contracts, projects, subcontract flow-down and the terms objects."""

import unittest

from strongback.core.money import money
from strongback.errors import DataError, InputError
from strongback.model.changeorder import ChangeOrder, ChangeOrderLog
from strongback.model.contract import Contract
from strongback.model.milestone import Milestone, MilestoneSet
from strongback.model.parties import Party, PartyDirectory, Role
from strongback.model.project import Project
from strongback.model.subcontract import FlowDownPolicy, SubcontractLink, SubcontractRegister
from strongback.model.terms import CompletionDates, LiquidatedDamages, PaymentTerms
from strongback.model.unitprice import UnitPriceItem, billable_quantity
from strongback.core.quantity import quantity
from strongback.retainage.terms import RetainageTerms, Stepdown
from tests.support import BUILDER, OWNER, SUB, contract, line, schedule


class PartyTest(unittest.TestCase):
    """Roles imply a direction of payment."""

    def test_an_owner_pays_downstream(self):
        self.assertTrue(Role("owner").pays_downstream())

    def test_a_subcontractor_does_not(self):
        self.assertFalse(Role("subcontractor").pays_downstream())

    def test_roles_are_ordered_down_the_chain(self):
        self.assertTrue(Role("contractor").is_upstream_of("subcontractor"))

    def test_an_unknown_role_is_refused(self):
        self.assertRaises(InputError, Role, "consultant")

    def test_a_directory_refuses_duplicates(self):
        directory = PartyDirectory([OWNER])
        self.assertRaises(InputError, directory.add, Party("OWN", "Someone else", "owner"))


class ContractTest(unittest.TestCase):
    """A contract sums its schedule and its billable change orders."""

    def setUp(self):
        self.contract = contract(
            schedule(line("01000", "100000"), line("03300", "400000"))
        )
        change = ChangeOrder("CO-001", 1, status="executed", date_executed="2024-10-22")
        change.add_line(line("08400", "68000"))
        self.contract.add_change_order(change)

    def test_the_original_sum_excludes_change_orders(self):
        self.assertEqual(self.contract.original_sum(), money("500000"))

    def test_the_contract_sum_includes_effective_change_orders(self):
        self.assertEqual(self.contract.contract_sum("2024-11-01"), money("568000"))

    def test_a_change_order_is_not_in_the_sum_before_it_is_executed(self):
        self.assertEqual(self.contract.contract_sum("2024-10-01"), money("500000"))

    def test_the_billing_schedule_gains_the_change_order_line(self):
        billing = self.contract.billing_schedule("2024-11-01")
        self.assertIn("08400", billing)
        self.assertNotIn("08400", self.contract.schedule)

    def test_the_same_party_on_both_sides_is_refused(self):
        self.assertRaises(DataError, Contract, "C-2", OWNER, OWNER, schedule())

    def test_validation_notices_an_executed_order_with_no_date(self):
        change = ChangeOrder("CO-002", 2, status="executed")
        change.add_line(line("09900", "1000"))
        self.contract.add_change_order(change)
        self.assertTrue(
            any("executed with no date" in problem for problem in self.contract.validate())
        )

    def test_a_contract_round_trips_through_plain_data(self):
        rebuilt = Contract.from_dict(self.contract.to_dict())
        self.assertEqual(rebuilt.contract_sum("2024-11-01"), money("568000"))
        self.assertEqual(rebuilt.retainage.describe(), self.contract.retainage.describe())


class TermsTest(unittest.TestCase):
    """Payment terms, completion dates and liquidated damages."""

    def test_payment_terms_describe_themselves(self):
        self.assertEqual(
            PaymentTerms(net_days=45).describe(),
            "net 45 calendar days from certification_date",
        )

    def test_pay_if_paid_shifts_risk_and_pay_when_paid_does_not(self):
        self.assertTrue(PaymentTerms(chain_rule="pay_if_paid").shifts_risk_upstream())
        self.assertFalse(PaymentTerms(chain_rule="pay_when_paid").shifts_risk_upstream())

    def test_a_discount_needs_a_window(self):
        self.assertRaises(InputError, PaymentTerms, 30, "calendar", "certification_date", 7, "independent", 0, "2%", 0)

    def test_completion_dates_measure_lateness_from_substantial_completion(self):
        dates = CompletionDates(
            notice_to_proceed="2024-09-16",
            contract_completion="2025-06-30",
            substantial_completion="2025-07-21",
        )
        self.assertEqual(dates.days_late("2025-08-01"), 21)

    def test_final_completion_cannot_precede_substantial(self):
        self.assertRaises(
            DataError,
            CompletionDates,
            None,
            None,
            "2025-07-21",
            "2025-07-01",
        )

    def test_liquidated_damages_stop_at_the_cap(self):
        damages = LiquidatedDamages(money("2500"), cap=money("50000"), grace_days=5)
        self.assertEqual(damages.assess(10), money("12500"))
        self.assertEqual(damages.assess(100), money("50000"))
        self.assertTrue(damages.is_capped_at(100))


class UnitPriceTest(unittest.TestCase):
    """The overrun rule decides what a measurement is worth."""

    def test_the_rate_rule_bills_everything_measured(self):
        self.assertEqual(
            billable_quantity(quantity("110", "cy"), quantity("100", "cy"), "rate"),
            quantity("110", "cy"),
        )

    def test_the_capped_rule_stops_at_the_estimate(self):
        self.assertEqual(
            billable_quantity(quantity("110", "cy"), quantity("100", "cy"), "capped"),
            quantity("100", "cy"),
        )

    def test_the_threshold_rule_allows_a_stated_variance(self):
        self.assertEqual(
            billable_quantity(quantity("130", "cy"), quantity("100", "cy"), "threshold", "15%"),
            quantity("115", "cy"),
        )

    def test_an_underrun_bills_only_what_was_installed(self):
        item = UnitPriceItem("31200", quantity("2500", "cy"), money("20"))
        self.assertEqual(item.value_of(quantity("2000", "cy")), money("40000"))

    def test_the_unbilled_overrun_is_reported(self):
        item = UnitPriceItem(
            "31200", quantity("2500", "cy"), money("20"), overrun_rule="capped"
        )
        self.assertEqual(item.unbilled_overrun(quantity("2600", "cy")), money("2000"))


class MilestoneTest(unittest.TestCase):
    """A milestone earns on an event, not on a percentage."""

    def test_nothing_is_earned_before_the_event(self):
        stone = Milestone("MS-1", "Topping out", money("150000"))
        self.assertEqual(stone.earned_value(), money("0"))

    def test_everything_is_earned_when_the_event_happens(self):
        stone = Milestone("MS-1", "Topping out", money("150000"), achieved_on="2024-11-08")
        self.assertEqual(stone.earned_value("2024-11-30"), money("150000"))

    def test_proportional_credit_needs_the_rule_and_the_progress(self):
        stone = Milestone(
            "MS-2", "Structure", money("100000"), partial_rule="proportional"
        )
        self.assertEqual(stone.earned_value(None, "0.4"), money("40000.0"))

    def test_a_stated_partial_ignores_the_progress(self):
        stone = Milestone(
            "MS-3", "Enclosure", money("100000"), partial_rule="stated", partial_share="25%"
        )
        self.assertEqual(stone.earned_value(None, "0.9"), money("25000.00"))

    def test_achieving_twice_on_different_dates_is_refused(self):
        stone = Milestone("MS-4", "Roof", money("10000"), achieved_on="2024-11-01")
        self.assertRaises(DataError, stone.achieve, "2024-12-01")

    def test_a_set_reports_what_is_blocked(self):
        stones = MilestoneSet(
            [
                Milestone("MS-1", "Foundations", money("100000")),
                Milestone("MS-2", "Structure", money("150000"), predecessors=["MS-1"]),
            ]
        )
        self.assertTrue(stones.blocked("MS-2"))
        stones["MS-1"].achieve("2024-10-04")
        self.assertFalse(stones.blocked("MS-2"))


class FlowDownTest(unittest.TestCase):
    """What a subcontract inherits is a choice, not an assumption."""

    def setUp(self):
        self.prime = RetainageTerms("5%", stepdowns=[Stepdown("50%", "2.5%")])
        self.sub = RetainageTerms("10%")

    def test_independent_terms_keep_the_sub_rate(self):
        policy = FlowDownPolicy("independent")
        self.assertEqual(str(policy.effective_terms(self.prime, self.sub).base_rate), "10%")

    def test_mirroring_the_rate_takes_the_prime_rate_only(self):
        policy = FlowDownPolicy("mirror_rate")
        effective = policy.effective_terms(self.prime, self.sub)
        self.assertEqual(str(effective.base_rate), "5%")
        self.assertEqual(effective.stepdowns, ())

    def test_mirroring_everything_takes_the_step_downs_too(self):
        policy = FlowDownPolicy("mirror_all")
        effective = policy.effective_terms(self.prime, self.sub)
        self.assertEqual(len(effective.stepdowns), 1)

    def test_a_share_over_one_is_refused(self):
        self.assertRaises(DataError, SubcontractLink, "C-200", "C-100", {"03300": "1.5"})

    def test_oversubscribed_lines_are_reported(self):
        register = SubcontractRegister(
            [
                SubcontractLink("C-200", "C-100", {"03300": "0.75"}),
                SubcontractLink("C-201", "C-100", {"03300": "0.5"}),
            ]
        )
        self.assertEqual(register.oversubscribed(), ["03300"])


class ProjectTest(unittest.TestCase):
    """A project knows its prime contract and what is let below it."""

    def setUp(self):
        self.project = Project("P-1", "Harbor Point", parties=[OWNER, BUILDER, SUB])
        self.prime = self.project.add_contract(
            Contract("C-100", OWNER, BUILDER, schedule(line("03300", "500000")))
        )
        self.sub = self.project.add_contract(
            Contract("C-200", BUILDER, SUB, schedule(line("03300", "300000")))
        )

    def test_the_prime_contract_is_the_owner_contract(self):
        self.assertEqual(self.project.prime_contract().id, "C-100")

    def test_subcontracts_are_the_ones_the_builder_pays(self):
        self.assertEqual([item.id for item in self.project.subcontracts()], ["C-200"])

    def test_uncommitted_value_is_what_is_not_let(self):
        self.assertEqual(self.project.uncommitted_value(), money("200000"))

    def test_a_project_round_trips_through_plain_data(self):
        rebuilt = Project.from_dict(self.project.to_dict())
        self.assertEqual(rebuilt.uncommitted_value(), money("200000"))

    def test_over_letting_the_prime_is_reported(self):
        self.project.add_contract(
            Contract("C-201", BUILDER, SUB, schedule(line("03300", "400000")))
        )
        self.assertIn("subcontracts exceed the prime contract sum", self.project.validate())


if __name__ == "__main__":
    unittest.main()
