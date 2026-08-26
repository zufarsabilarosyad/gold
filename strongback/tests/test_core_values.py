"""Rates, quantities and the decimal helpers under them."""

import unittest
from decimal import Decimal

from strongback.core.numbers import allocate, clamp, decimal_from, quantize, safe_divide
from strongback.core.percent import Rate, complement, rate
from strongback.core.quantity import Quantity, quantity
from strongback.errors import DataError, InputError, ParseError


class DecimalHelperTest(unittest.TestCase):
    """The helpers refuse floats and split without drift."""

    def test_strings_with_separators_parse(self):
        self.assertEqual(decimal_from("1,250.50"), Decimal("1250.50"))

    def test_accounting_parentheses_parse_as_negative(self):
        self.assertEqual(decimal_from("(300)"), Decimal("-300"))

    def test_a_float_is_refused(self):
        self.assertRaises(InputError, decimal_from, 1.5)

    def test_nonsense_is_a_parse_error(self):
        self.assertRaises(ParseError, decimal_from, "eleven")

    def test_half_up_and_half_even_differ_where_it_matters(self):
        self.assertEqual(quantize(Decimal("1.005")), Decimal("1.01"))
        self.assertEqual(quantize(Decimal("1.005"), mode="half_even"), Decimal("1.00"))

    def test_allocation_sums_back_exactly(self):
        parts = allocate(Decimal("1.00"), [1, 1, 1])
        self.assertEqual(sum(parts), Decimal("1.00"))

    def test_allocation_of_a_negative_total_sums_back(self):
        parts = allocate(Decimal("-1.00"), [1, 1, 1])
        self.assertEqual(sum(parts), Decimal("-1.00"))

    def test_clamp_respects_open_bounds(self):
        self.assertEqual(clamp(Decimal(5), None, Decimal(3)), Decimal(3))
        self.assertEqual(clamp(Decimal(5), Decimal(7), None), Decimal(7))

    def test_safe_divide_needs_a_default_for_zero(self):
        self.assertRaises(InputError, safe_divide, Decimal(1), Decimal(0))
        self.assertEqual(safe_divide(Decimal(1), Decimal(0), Decimal(0)), Decimal(0))


class RateTest(unittest.TestCase):
    """A rate is a fraction, and parsing guesses only where it is safe to."""

    def test_percent_sign_divides_by_a_hundred(self):
        self.assertEqual(rate("10%"), Rate("0.1"))

    def test_a_bare_number_at_or_above_one_reads_as_percent(self):
        self.assertEqual(rate("10"), Rate("0.1"))

    def test_a_bare_fraction_reads_as_a_fraction(self):
        self.assertEqual(rate("0.075"), Rate("0.075"))

    def test_a_share_never_guesses(self):
        self.assertEqual(Rate.share("1.0"), Rate("1"))
        self.assertEqual(Rate.share("50%"), Rate("0.5"))

    def test_progress_above_a_hundred_is_representable(self):
        self.assertEqual(str(Rate.parse("120%")), "120%")

    def test_an_absurd_rate_is_refused(self):
        self.assertRaises(InputError, Rate, "20")

    def test_complement_is_what_is_left(self):
        self.assertEqual(complement("10%"), Rate("0.9"))

    def test_multiplication_applies_to_money_and_numbers(self):
        from strongback.core.money import money

        self.assertEqual(Rate("0.1") * money("200"), money("20.0"))
        self.assertEqual(Rate("0.1") * 200, Decimal("20.0"))

    def test_percent_rendering_drops_trailing_zeroes(self):
        self.assertEqual(str(Rate("0.05")), "5%")
        self.assertEqual(str(Rate("0.0725")), "7.25%")


class QuantityTest(unittest.TestCase):
    """Quantities carry their unit and refuse to mix."""

    def test_addition_within_a_unit(self):
        self.assertEqual(quantity("100", "cy") + quantity("50", "cy"), quantity("150", "cy"))

    def test_units_do_not_mix(self):
        self.assertRaises(InputError, lambda: quantity("1", "cy") + quantity("1", "ton"))

    def test_unit_codes_are_case_insensitive(self):
        self.assertEqual(quantity("1", "CY"), quantity("1", "cy"))

    def test_ratio_between_quantities(self):
        self.assertEqual(quantity("50", "cy").ratio_to(quantity("200", "cy")), Decimal("0.25"))

    def test_ratio_to_zero_is_refused(self):
        self.assertRaises(InputError, quantity("1", "cy").ratio_to, quantity("0", "cy"))

    def test_formatting_shows_the_unit(self):
        self.assertEqual(quantity("1250.5", "lf").format(), "1,250.50 lf")


if __name__ == "__main__":
    unittest.main()
