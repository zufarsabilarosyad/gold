"""Change orders: four statuses, four billing thresholds."""

import unittest

from strongback.core.money import money
from strongback.errors import DataError, InputError, SequenceError
from strongback.model.changeorder import ChangeOrder, ChangeOrderLog, ChangeStatus
from tests.support import line


def order(identifier, number, status, value="10000", **dates):
    """Build a one-line change order."""
    change = ChangeOrder(identifier, number, status=status, **dates)
    change.add_line(line("08400", value, description="Storefront"))
    return change


class ChangeStatusTest(unittest.TestCase):
    """Which statuses bill is a threshold, not a property of the status."""

    def test_an_executed_order_bills_under_every_threshold(self):
        for threshold in ("executed_only", "approved", "directed", "proposed"):
            self.assertTrue(ChangeStatus("executed").is_billable_under(threshold))

    def test_a_directive_bills_only_from_the_directed_threshold_up(self):
        self.assertFalse(ChangeStatus("directed").is_billable_under("approved"))
        self.assertTrue(ChangeStatus("directed").is_billable_under("directed"))

    def test_a_rejected_order_never_bills(self):
        self.assertTrue(ChangeStatus("rejected").is_dead())
        self.assertFalse(ChangeStatus("rejected").is_billable_under("proposed"))

    def test_statuses_only_move_forward(self):
        self.assertTrue(ChangeStatus("proposed").can_become("executed"))
        self.assertFalse(ChangeStatus("executed").can_become("proposed"))

    def test_an_unknown_threshold_is_refused(self):
        self.assertRaises(InputError, ChangeStatus("executed").is_billable_under, "someday")


class ChangeOrderTest(unittest.TestCase):
    """An order takes effect on the date matching its status."""

    def test_the_effective_date_follows_the_status(self):
        change = order(
            "CO-001",
            1,
            "approved",
            date_priced="2024-10-04",
            date_approved="2024-10-18",
            date_executed="2024-10-30",
        )
        self.assertTrue(change.is_effective_on("2024-10-20"))
        self.assertFalse(change.is_effective_on("2024-10-10"))

    def test_an_order_with_no_date_is_not_effective(self):
        self.assertFalse(order("CO-002", 2, "proposed").is_effective_on("2030-01-01"))

    def test_a_transition_records_its_date(self):
        change = order("CO-003", 3, "proposed", date_priced="2024-11-01")
        change.transition("executed", "2024-11-20")
        self.assertEqual(str(change.status), "executed")
        self.assertTrue(change.is_effective_on("2024-11-20"))

    def test_a_backwards_transition_is_refused(self):
        change = order("CO-004", 4, "executed", date_executed="2024-11-01")
        self.assertRaises(SequenceError, change.transition, "proposed")

    def test_an_order_rate_flows_down_to_its_lines(self):
        change = ChangeOrder("CO-005", 5, retainage_rate="5%")
        added = change.add_line(line("08450", "42000"))
        self.assertEqual(str(added.retainage_rate), "5%")

    def test_a_credit_order_reduces_the_sum(self):
        change = ChangeOrder("CO-006", 6, status="executed", date_executed="2024-12-01")
        change.add_line(line("32800", "-15000"))
        self.assertTrue(change.is_credit())

    def test_an_order_round_trips_through_plain_data(self):
        change = order("CO-007", 7, "executed", date_executed="2024-10-30")
        rebuilt = ChangeOrder.from_dict(change.to_dict())
        self.assertEqual(rebuilt.value(), change.value())
        self.assertEqual(str(rebuilt.status), "executed")


class ChangeOrderLogTest(unittest.TestCase):
    """The log answers what may be billed, and what is waiting."""

    def setUp(self):
        self.log = ChangeOrderLog(
            [
                order("CO-001", 1, "executed", "68000", date_executed="2024-10-22"),
                order("CO-002", 2, "directed", "42000", date_directed="2024-11-12"),
                order("CO-003", 3, "proposed", "9000", date_priced="2024-12-01"),
            ]
        )

    def test_executed_only_bills_the_executed_order(self):
        self.assertEqual(self.log.value_under("executed_only", "2024-12-31"), money("68000"))

    def test_the_directed_threshold_adds_the_directive(self):
        self.assertEqual(self.log.value_under("directed", "2024-12-31"), money("110000"))

    def test_nothing_bills_before_it_is_effective(self):
        self.assertEqual(self.log.value_under("directed", "2024-11-01"), money("68000"))

    def test_pending_value_is_what_is_live_and_not_billable(self):
        self.assertEqual(self.log.pending_value("executed_only", "2024-12-31"), money("51000"))

    def test_duplicate_numbers_are_refused(self):
        self.assertRaises(DataError, self.log.add, order("CO-009", 1, "executed"))

    def test_lines_come_back_for_the_billable_orders_only(self):
        codes = [item.code for item in self.log.lines_for("executed_only", "2024-12-31")]
        self.assertEqual(codes, ["08400"])

    def test_the_log_round_trips_through_plain_data(self):
        rebuilt = ChangeOrderLog.from_list(self.log.to_list())
        self.assertEqual(
            rebuilt.value_under("directed", "2024-12-31"),
            self.log.value_under("directed", "2024-12-31"),
        )


if __name__ == "__main__":
    unittest.main()
