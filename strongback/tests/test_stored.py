"""Stored materials: eligibility, the cap, and the conversion rule."""

import unittest

from strongback.core.money import money
from strongback.core.percent import Rate
from strongback.errors import DataError, InputError
from strongback.progress.stored import StoredEntry, StoredLedger, StoredOptions, stored_on_hand
from tests.support import line


def eligible_line(code="26200", value="70000"):
    """A line that may carry stored materials."""
    return line(code, value, description="Switchgear", stored_eligible=True)


class EligibilityTest(unittest.TestCase):
    """Where the material is decides whether it may be billed."""

    def setUp(self):
        self.line = eligible_line()
        self.ledger = StoredLedger(
            [
                StoredEntry("26200", 1, delivered=money("30000")),
                StoredEntry("26200", 1, delivered=money("18000"), offsite=True),
            ]
        )

    def test_offsite_material_is_excluded_by_default(self):
        self.assertEqual(stored_on_hand(self.line, self.ledger, 1, Rate("0")), money("30000"))

    def test_offsite_material_can_be_allowed(self):
        options = StoredOptions(allow_offsite=True)
        self.assertEqual(
            stored_on_hand(self.line, self.ledger, 1, Rate("0"), options), money("48000")
        )

    def test_uninsured_material_is_excluded_when_insurance_is_required(self):
        ledger = StoredLedger([StoredEntry("26200", 1, delivered=money("30000"), insured=False)])
        self.assertEqual(stored_on_hand(self.line, ledger, 1, Rate("0")), money("0"))

    def test_a_line_that_is_not_eligible_carries_nothing(self):
        plain = line("03300", "100000")
        ledger = StoredLedger([StoredEntry("03300", 1, delivered=money("10000"))])
        self.assertEqual(stored_on_hand(plain, ledger, 1, Rate("0")), money("0"))

    def test_the_excluded_amount_is_reportable(self):
        self.assertEqual(self.ledger.ineligible_to_date("26200", 1), money("18000"))


class ConversionTest(unittest.TestCase):
    """Three readings of when stored material becomes work in place."""

    def setUp(self):
        self.line = eligible_line()
        self.ledger = StoredLedger([StoredEntry("26200", 1, delivered=money("48000"))])

    def test_explicit_conversion_waits_for_a_report(self):
        self.assertEqual(stored_on_hand(self.line, self.ledger, 1, Rate("0.25")), money("48000"))

    def test_explicit_conversion_follows_the_report(self):
        self.ledger.record(StoredEntry("26200", 2, converted=money("18000")))
        self.assertEqual(stored_on_hand(self.line, self.ledger, 2, Rate("0.25")), money("30000"))

    def test_proportional_conversion_follows_the_percentage(self):
        options = StoredOptions(conversion="proportional")
        self.assertEqual(
            stored_on_hand(self.line, self.ledger, 1, Rate("0.25"), options), money("36000.00")
        )

    def test_conversion_on_completion_holds_everything_until_the_end(self):
        options = StoredOptions(conversion="on_completion")
        self.assertEqual(
            stored_on_hand(self.line, self.ledger, 1, Rate("0.99"), options), money("48000")
        )
        self.assertEqual(
            stored_on_hand(self.line, self.ledger, 1, Rate("1"), options), money("0")
        )

    def test_converting_more_than_was_delivered_is_refused(self):
        self.ledger.record(StoredEntry("26200", 2, converted=money("60000")))
        self.assertRaises(DataError, stored_on_hand, self.line, self.ledger, 2, Rate("0.5"))

    def test_an_unknown_conversion_rule_is_refused(self):
        self.assertRaises(InputError, StoredOptions, "osmosis")


class CapTest(unittest.TestCase):
    """The ceiling applies against the line's scheduled value."""

    def test_the_cap_binds(self):
        stored = StoredLedger([StoredEntry("26200", 1, delivered=money("60000"))])
        options = StoredOptions(cap="50%")
        self.assertEqual(
            stored_on_hand(eligible_line(), stored, 1, Rate("0"), options), money("35000.00")
        )

    def test_the_cap_does_not_bind_below_it(self):
        stored = StoredLedger([StoredEntry("26200", 1, delivered=money("20000"))])
        options = StoredOptions(cap="50%")
        self.assertEqual(
            stored_on_hand(eligible_line(), stored, 1, Rate("0"), options), money("20000")
        )

    def test_the_ledger_round_trips_through_plain_data(self):
        stored = StoredLedger([StoredEntry("26200", 1, delivered=money("20000"), invoice="SG-1")])
        rebuilt = StoredLedger.from_list(stored.to_list())
        self.assertEqual(rebuilt.delivered_to_date("26200", 1), money("20000"))


if __name__ == "__main__":
    unittest.main()
