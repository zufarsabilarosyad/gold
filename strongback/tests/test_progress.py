"""What the field reported, and what the conventions make of it."""

import unittest

from strongback.core.money import money
from strongback.core.percent import Rate
from strongback.core.quantity import quantity
from strongback.errors import DataError, InputError, SequenceError
from strongback.model.sov import SOVLine
from strongback.progress.costtocost import CostEntry, CostLedger, percent_by_cost
from strongback.progress.method import (
    ProgressOptions,
    completion_fraction,
    earned_for_schedule,
    earned_to_date,
    percent_to_date,
)
from strongback.progress.observation import ProgressEntry, ProgressLedger
from strongback.progress.rollup import rollup_by
from tests.support import line, schedule


class ObservationTest(unittest.TestCase):
    """An observation records exactly what was reported."""

    def test_an_entry_reports_exactly_one_shape(self):
        self.assertRaises(
            InputError, ProgressEntry, "03300", 1, percent="20%", value=money("1000")
        )

    def test_an_entry_reporting_nothing_is_refused(self):
        self.assertRaises(InputError, ProgressEntry, "03300", 1)

    def test_cumulative_entries_replace_the_running_figure(self):
        ledger = ProgressLedger(
            [
                ProgressEntry("03300", 1, percent="20%"),
                ProgressEntry("03300", 2, percent="55%"),
            ]
        )
        self.assertEqual(ledger.latest_percent("03300", 2), Rate("0.55"))

    def test_incremental_entries_add_to_it(self):
        ledger = ProgressLedger(
            [
                ProgressEntry("03300", 1, percent="20%"),
                ProgressEntry("03300", 2, percent="15%", basis="this_period"),
            ]
        )
        self.assertEqual(ledger.latest_percent("03300", 2), Rate("0.35"))

    def test_two_observations_for_one_line_period_are_refused(self):
        ledger = ProgressLedger([ProgressEntry("03300", 1, percent="20%")])
        self.assertRaises(DataError, ledger.record, ProgressEntry("03300", 1, percent="25%"))

    def test_a_revision_replaces_deliberately(self):
        ledger = ProgressLedger([ProgressEntry("03300", 1, percent="20%")])
        ledger.replace(ProgressEntry("03300", 1, percent="25%"))
        self.assertEqual(ledger.latest_percent("03300", 1), Rate("0.25"))

    def test_progress_going_backwards_can_be_checked_for(self):
        ledger = ProgressLedger(
            [
                ProgressEntry("03300", 1, percent="60%"),
                ProgressEntry("03300", 2, percent="45%"),
            ]
        )
        self.assertRaises(SequenceError, ledger.check_monotonic, "03300")

    def test_quantities_accumulate_when_reported_incrementally(self):
        ledger = ProgressLedger(
            [
                ProgressEntry("31200", 1, installed=quantity("100", "cy")),
                ProgressEntry("31200", 2, installed=quantity("150", "cy"), basis="this_period"),
            ]
        )
        self.assertEqual(ledger.cumulative_quantity("31200", 2), quantity("250", "cy"))

    def test_the_ledger_round_trips_through_plain_data(self):
        ledger = ProgressLedger([ProgressEntry("03300", 1, percent="20%")])
        rebuilt = ProgressLedger.from_list(ledger.to_list())
        self.assertEqual(rebuilt.latest_percent("03300", 1), Rate("0.2"))


class ValuationTest(unittest.TestCase):
    """The conventions decide what a percentage is worth."""

    def setUp(self):
        self.line = line("03300", "400000")
        self.ledger = ProgressLedger([ProgressEntry("03300", 1, percent="25%")])

    def test_a_percentage_values_against_the_scheduled_value(self):
        self.assertEqual(earned_to_date(self.line, self.ledger, 1), money("100000.00"))

    def test_over_a_hundred_percent_clamps_by_default(self):
        ledger = ProgressLedger([ProgressEntry("03300", 1, percent="120%")])
        self.assertEqual(percent_to_date(self.line, ledger, 1), Rate("1"))

    def test_over_a_hundred_percent_can_be_allowed(self):
        ledger = ProgressLedger([ProgressEntry("03300", 1, percent="120%")])
        options = ProgressOptions(over_hundred="allow")
        self.assertEqual(percent_to_date(self.line, ledger, 1, options), Rate("1.2"))

    def test_over_a_hundred_percent_can_be_an_error(self):
        ledger = ProgressLedger([ProgressEntry("03300", 1, percent="120%")])
        options = ProgressOptions(over_hundred="error")
        self.assertRaises(DataError, percent_to_date, self.line, ledger, 1, options)

    def test_negative_progress_clamps_by_default(self):
        ledger = ProgressLedger(
            [
                ProgressEntry("03300", 1, percent="40%"),
                ProgressEntry("03300", 2, percent="-50%", basis="this_period"),
            ]
        )
        self.assertEqual(percent_to_date(self.line, ledger, 2), Rate("0"))

    def test_a_value_observation_bills_directly(self):
        ledger = ProgressLedger([ProgressEntry("03300", 1, value=money("60000"))])
        self.assertEqual(earned_to_date(self.line, ledger, 1), money("60000.00"))

    def test_a_unit_price_line_values_the_measured_quantity(self):
        unit = SOVLine(
            "31200",
            "Excavation",
            money("240000"),
            kind="unit_price",
            unit_quantity=quantity("12000", "cy"),
            unit_rate=money("20"),
        )
        ledger = ProgressLedger([ProgressEntry("31200", 1, installed=quantity("3400", "cy"))])
        self.assertEqual(earned_to_date(unit, ledger, 1), money("68000"))

    def test_a_capped_overrun_rule_stops_at_the_estimate(self):
        unit = SOVLine(
            "31200",
            "Excavation",
            money("240000"),
            kind="unit_price",
            unit_quantity=quantity("12000", "cy"),
            unit_rate=money("20"),
        )
        ledger = ProgressLedger([ProgressEntry("31200", 1, installed=quantity("12400", "cy"))])
        options = ProgressOptions(overrun_rule="capped")
        self.assertEqual(earned_to_date(unit, ledger, 1, options), money("240000"))

    def test_a_milestone_line_earns_nothing_before_the_event(self):
        stone = SOVLine("MS1", "Topping out", money("150000"), kind="milestone")
        ledger = ProgressLedger([ProgressEntry("MS1", 1, percent="80%")])
        self.assertEqual(earned_to_date(stone, ledger, 1), money("0.00"))

    def test_a_milestone_line_can_be_allowed_partial_credit(self):
        stone = SOVLine("MS1", "Topping out", money("150000"), kind="milestone")
        ledger = ProgressLedger([ProgressEntry("MS1", 1, percent="80%")])
        options = ProgressOptions(milestone_rule="line_percent")
        self.assertEqual(earned_to_date(stone, ledger, 1, options), money("120000.0"))

    def test_a_schedule_values_line_by_line(self):
        sov = schedule(line("01000", "100000"), line("03300", "400000"))
        ledger = ProgressLedger(
            [
                ProgressEntry("01000", 1, percent="50%"),
                ProgressEntry("03300", 1, percent="25%"),
            ]
        )
        earned = earned_for_schedule(sov, ledger, 1)
        self.assertEqual(earned["01000"], money("50000.00"))
        self.assertEqual(completion_fraction(sov, ledger, 1), Rate("0.3"))


class CostTest(unittest.TestCase):
    """Cost-to-cost is the other measure of progress."""

    def setUp(self):
        self.ledger = CostLedger(
            [
                CostEntry("03300", 1, money("40000"), "labor"),
                CostEntry("03300", 2, money("35000"), "material"),
                CostEntry("03300", 2, money("15000"), "subcontract", committed=True),
            ]
        )

    def test_incurred_excludes_commitments(self):
        self.assertEqual(self.ledger.incurred_to_date("03300", 2), money("75000"))

    def test_committed_includes_them(self):
        self.assertEqual(self.ledger.committed_to_date("03300", 2), money("90000"))

    def test_categories_are_kept_apart(self):
        self.assertEqual(self.ledger.by_category("03300", 2)["labor"], money("40000"))

    def test_percent_by_cost_caps_at_a_hundred(self):
        self.assertEqual(percent_by_cost(money("120000"), money("100000")), Rate("1"))

    def test_percent_by_cost_needs_a_forecast(self):
        self.assertRaises(DataError, percent_by_cost, money("1"), money("0"))


class RollupTest(unittest.TestCase):
    """Group totals are the sum of the lines under them."""

    def test_groups_total_their_lines(self):
        sov = schedule(
            line("03300", "100000", group="Structure"),
            line("03400", "60000", group="Structure"),
            line("09900", "40000", group="Finishes"),
        )
        earned = {"03300": money("50000"), "03400": money("30000"), "09900": money("4000")}
        rows = {row.key: row for row in rollup_by(sov, earned)}
        self.assertEqual(rows["Structure"].earned, money("80000"))
        self.assertEqual(rows["Structure"].completion(), Rate("0.5"))
        self.assertEqual(rows["Finishes"].balance(), money("36000"))


if __name__ == "__main__":
    unittest.main()
