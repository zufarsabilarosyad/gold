"""The schedule of values and the lines in it."""

import unittest

from strongback.core.money import money
from strongback.core.quantity import quantity
from strongback.errors import DataError, InputError, UnknownLine
from strongback.model.sov import LineKind, ScheduleOfValues, SOVLine
from tests.support import line, schedule


class LineTest(unittest.TestCase):
    """A line knows how it is measured and what it is worth."""

    def test_a_lump_sum_line_is_not_measured_by_quantity(self):
        self.assertFalse(LineKind("lump_sum").measured_by_quantity())

    def test_a_unit_price_line_needs_a_quantity_and_a_rate(self):
        self.assertRaises(
            DataError,
            SOVLine,
            "31200",
            "Excavation",
            money("50000"),
            kind="unit_price",
        )

    def test_a_unit_price_line_values_a_measurement(self):
        unit = SOVLine(
            "31200",
            "Excavation",
            money("50000"),
            kind="unit_price",
            unit_quantity=quantity("2500", "cy"),
            unit_rate=money("20"),
        )
        self.assertEqual(unit.value_of(quantity("1000", "cy")), money("20000"))

    def test_measuring_in_the_wrong_unit_is_refused(self):
        unit = SOVLine(
            "31200",
            "Excavation",
            money("50000"),
            kind="unit_price",
            unit_quantity=quantity("2500", "cy"),
            unit_rate=money("20"),
        )
        self.assertRaises(DataError, unit.value_of, quantity("100", "ton"))

    def test_a_change_order_line_knows_where_it_came_from(self):
        added = line(code="08400", origin="CO-001", change_order="CO-001")
        self.assertTrue(added.is_change_order())

    def test_a_credit_line_is_negative(self):
        self.assertTrue(line(value="-15000").is_credit())

    def test_a_line_rate_overrides_the_contract_rate(self):
        self.assertEqual(str(line(retainage_rate="5%").effective_retainage_rate("10%")), "5%")

    def test_a_line_without_a_rate_falls_back(self):
        self.assertEqual(str(line().effective_retainage_rate("10%")), "10%")

    def test_a_line_round_trips_through_plain_data(self):
        original = line(stored_eligible=True, group="Structure")
        rebuilt = SOVLine.from_dict(original.to_dict())
        self.assertEqual(rebuilt.to_dict(), original.to_dict())


class ScheduleTest(unittest.TestCase):
    """The schedule is addressable, ordered and total-able."""

    def setUp(self):
        self.sov = schedule(
            line("01000", "100000", description="General conditions", group="General"),
            line("03300", "400000", description="Concrete", group="Structure"),
            line("09900", "60000", description="Painting", group="Finishes"),
        )

    def test_the_total_is_the_sum_of_the_lines(self):
        self.assertEqual(self.sov.total(), money("560000"))

    def test_a_duplicate_code_is_refused(self):
        self.assertRaises(DataError, self.sov.add, line("03300", "1"))

    def test_a_missing_line_raises_unknown_line(self):
        self.assertRaises(UnknownLine, self.sov.require, "99999")

    def test_lines_keep_their_insertion_order(self):
        self.assertEqual(self.sov.codes(), ["01000", "03300", "09900"])

    def test_groups_are_listed_in_schedule_order(self):
        self.assertEqual(self.sov.groups(), ["General", "Structure", "Finishes"])

    def test_change_order_lines_are_separated_from_the_base(self):
        with_change = self.sov.with_lines([line("08400", "42000", origin="CO-001", change_order="CO-001")])
        self.assertEqual(with_change.base_total(), money("560000"))
        self.assertEqual(with_change.change_order_total(), money("42000"))

    def test_copies_are_independent(self):
        copy = self.sov.copy()
        copy.add(line("07500", "10000"))
        self.assertEqual(len(self.sov), 3)
        self.assertEqual(len(copy), 4)

    def test_validation_catches_a_unit_price_mismatch(self):
        broken = ScheduleOfValues(
            [
                SOVLine(
                    "31200",
                    "Excavation",
                    money("60000"),
                    kind="unit_price",
                    unit_quantity=quantity("2500", "cy"),
                    unit_rate=money("20"),
                )
            ]
        )
        problems = broken.validate()
        self.assertEqual(len(problems), 1)
        self.assertIn("quantity times rate", problems[0])

    def test_a_schedule_round_trips_through_plain_data(self):
        rebuilt = ScheduleOfValues.from_list(self.sov.to_list())
        self.assertEqual(rebuilt.total(), self.sov.total())
        self.assertEqual(rebuilt.codes(), self.sov.codes())


if __name__ == "__main__":
    unittest.main()
