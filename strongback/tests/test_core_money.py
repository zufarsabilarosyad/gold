"""Money is exact, carries its currency, and rounds only when asked."""

import unittest
from decimal import Decimal

from strongback.core.money import Money, currency_by_code, money, total, zero
from strongback.errors import CurrencyMismatch, InputError


class MoneyArithmeticTest(unittest.TestCase):
    """Addition, multiplication and comparison keep full precision."""

    def test_addition_keeps_exact_cents(self):
        self.assertEqual(money("0.10") + money("0.20"), money("0.30"))

    def test_multiplication_does_not_round(self):
        product = money("1000.00") * "0.0725"
        self.assertEqual(product.amount, Decimal("72.500000"))

    def test_division_by_money_gives_a_ratio(self):
        self.assertEqual(money("50") / money("200"), Decimal("0.25"))

    def test_rounding_happens_only_when_asked(self):
        self.assertEqual(money("10.005").rounded(), money("10.01"))
        self.assertEqual(money("10.005").amount, Decimal("10.005"))

    def test_negation_and_absolute_value(self):
        self.assertEqual(-money("5"), money("-5"))
        self.assertEqual(abs(money("-5")), money("5"))

    def test_summing_an_empty_iterable_is_zero(self):
        self.assertEqual(total([]), zero())

    def test_sum_builtin_works_through_radd(self):
        self.assertEqual(sum([money("1"), money("2")]), money("3"))


class MoneyRefusalTest(unittest.TestCase):
    """The type refuses the two mistakes that lose money quietly."""

    def test_a_float_is_refused(self):
        self.assertRaises(InputError, money, 0.1)

    def test_two_currencies_do_not_mix(self):
        self.assertRaises(CurrencyMismatch, lambda: money("1", "USD") + money("1", "EUR"))

    def test_comparison_across_currencies_is_refused(self):
        self.assertRaises(CurrencyMismatch, lambda: money("1", "USD") < money("1", "CAD"))

    def test_division_by_zero_is_refused(self):
        self.assertRaises(InputError, lambda: money("1") / 0)


class MoneySplitTest(unittest.TestCase):
    """Splitting never loses or invents a cent."""

    def test_thirds_sum_back_to_the_whole(self):
        parts = money("100.00").split([1, 1, 1])
        self.assertEqual(total(parts), money("100.00"))
        self.assertEqual([str(part.amount) for part in parts], ["33.34", "33.33", "33.33"])

    def test_weighted_split_follows_the_weights(self):
        parts = money("1000.00").split([3, 1])
        self.assertEqual([str(part.amount) for part in parts], ["750.00", "250.00"])

    def test_zero_weights_put_everything_on_the_first_part(self):
        parts = money("10.00").split([0, 0])
        self.assertEqual(total(parts), money("10.00"))


class MoneyFormatTest(unittest.TestCase):
    """Rendering is for documents and stays stable."""

    def test_thousands_separator_and_symbol(self):
        self.assertEqual(money("1234567.5").format(), "$1,234,567.50")

    def test_negatives_can_be_parenthesised(self):
        self.assertEqual(money("-250").format(parens_for_negative=True), "($250.00)")

    def test_parsing_accepts_accounting_notation(self):
        self.assertEqual(Money.parse("(1,250.50)"), money("-1250.50"))

    def test_unknown_currency_codes_are_accepted(self):
        self.assertEqual(currency_by_code("SEK").minor_units, 2)


if __name__ == "__main__":
    unittest.main()
