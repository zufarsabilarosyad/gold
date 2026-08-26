"""Continuation rows, the summary page, application lifecycle and revisions."""

import unittest

from strongback.billing.application import ApplicationRegister, PayApplication
from strongback.billing.continuation import ContinuationSheet
from strongback.billing.line import ApplicationLine
from strongback.billing.numbering import (
    check_consecutive,
    find_gaps,
    format_application_id,
    next_number,
    revision_id,
)
from strongback.billing.revision import Revision, RevisionChain
from strongback.billing.summary import ApplicationSummary
from strongback.core.money import money
from strongback.core.percent import Rate
from strongback.core.period import BillingPeriod, monthly_schedule
from strongback.errors import DataError, InputError, SequenceError


def row(code="03300", scheduled="400000", **kwargs):
    """Build one continuation row."""
    amounts = {}
    for name in ("previous", "this_period", "stored", "previous_stored", "retainage", "previous_retainage"):
        if name in kwargs:
            amounts[name] = money(kwargs.pop(name))
    return ApplicationLine(code, kwargs.pop("description", "Concrete"), money(scheduled), **amounts)


def application(number=1, **kwargs):
    """Build a pay application with a summary."""
    period = monthly_schedule("2024-09-01", number).period(number)
    summary = ApplicationSummary(
        money(kwargs.pop("original", "500000")),
        completed_and_stored=money(kwargs.pop("completed", "175000")),
        retainage_work=money(kwargs.pop("retainage", "17500")),
        previous_certificates=money(kwargs.pop("previous", "0")),
    )
    return PayApplication("PA-%03d" % number, number, period, summary=summary, **kwargs)


class LineTest(unittest.TestCase):
    """The columns of a row are related by arithmetic, not by data entry."""

    def test_completed_and_stored_is_the_sum_of_three_columns(self):
        item = row(previous="100000", this_period="60000", stored="15000")
        self.assertEqual(item.completed_and_stored(), money("175000"))

    def test_the_percentage_comes_from_the_money(self):
        item = row(previous="100000", this_period="75000")
        self.assertEqual(item.percent_complete(), Rate("0.4375"))

    def test_the_balance_includes_stored_material(self):
        item = row(previous="100000", stored="15000")
        self.assertEqual(item.balance_to_finish(), money("285000"))

    def test_the_payment_effect_nets_retainage_and_stored_movement(self):
        item = row(this_period="60000", stored="15000", previous_stored="5000", retainage="7500")
        self.assertEqual(item.net_this_period(), money("62500"))

    def test_overbilling_is_reported_unless_it_is_allowed(self):
        item = row(this_period="500000")
        self.assertTrue(item.is_overbilled())
        self.assertEqual(len(item.validate()), 1)
        self.assertEqual(item.validate(allow_overbilling=True), [])

    def test_a_zero_scheduled_value_gives_a_zero_percentage(self):
        item = row(scheduled="0", this_period="1000")
        self.assertEqual(item.percent_complete(), Rate("0"))


class SheetTest(unittest.TestCase):
    """Every total on a sheet is the sum of its column."""

    def setUp(self):
        self.sheet = ContinuationSheet(
            [
                row("01000", "100000", previous="40000", this_period="10000", retainage="5000"),
                row("03300", "400000", this_period="60000", stored="15000", retainage="7500"),
            ]
        )

    def test_totals_add_up(self):
        self.assertEqual(self.sheet.total_scheduled(), money("500000"))
        self.assertEqual(self.sheet.total_completed_and_stored(), money("125000"))
        self.assertEqual(self.sheet.total_retainage(), money("12500"))

    def test_the_percentage_uses_the_totals(self):
        self.assertEqual(self.sheet.percent_complete(), Rate("0.25"))

    def test_retainage_splits_between_work_and_stored_by_base(self):
        self.assertEqual(self.sheet.retainage_on_work().rounded(), money("11000.00"))
        self.assertEqual(self.sheet.retainage_on_stored().rounded(), money("1500.00"))

    def test_a_duplicate_code_is_refused(self):
        self.assertRaises(DataError, self.sheet.add, row("03300"))

    def test_the_sheet_round_trips_through_plain_data(self):
        rebuilt = ContinuationSheet.from_list(self.sheet.to_list())
        self.assertEqual(rebuilt.total_retainage(), self.sheet.total_retainage())

    def test_rendering_has_no_trailing_whitespace(self):
        for text in self.sheet.as_table().splitlines():
            self.assertEqual(text, text.rstrip())


class SummaryTest(unittest.TestCase):
    """The nine lines, and the two that are conventions."""

    def setUp(self):
        self.summary = ApplicationSummary(
            money("500000"),
            change_orders=money("42000"),
            completed_and_stored=money("175000"),
            work_completed=money("160000"),
            stored=money("15000"),
            retainage_work=money("16000"),
            retainage_stored=money("1500"),
            previous_certificates=money("90000"),
        )

    def test_line_three_is_the_contract_sum(self):
        self.assertEqual(self.summary.contract_sum(), money("542000"))

    def test_line_six_is_earned_less_retainage(self):
        self.assertEqual(self.summary.earned_less_retainage(), money("157500"))

    def test_line_eight_is_the_payment(self):
        self.assertEqual(self.summary.current_payment_due(), money("67500"))

    def test_line_nine_includes_retainage(self):
        self.assertEqual(self.summary.balance_to_finish(), money("384500"))

    def test_work_remaining_excludes_retainage(self):
        self.assertEqual(self.summary.work_remaining(), money("367000"))

    def test_deductions_and_tax_move_the_net(self):
        summary = ApplicationSummary(
            money("100000"),
            completed_and_stored=money("50000"),
            retainage_work=money("5000"),
            deductions=money("2000"),
            tax=money("1200"),
        )
        self.assertEqual(summary.net_payable(), money("44200"))

    def test_billing_more_than_the_contract_is_reported(self):
        summary = ApplicationSummary(money("100000"), completed_and_stored=money("120000"))
        self.assertIn("more has been billed than the contract sum to date", summary.validate())

    def test_the_summary_round_trips_through_plain_data(self):
        rebuilt = ApplicationSummary.from_dict(self.summary.to_dict())
        self.assertEqual(rebuilt.current_payment_due(), self.summary.current_payment_due())


class ApplicationLifecycleTest(unittest.TestCase):
    """An application is prepared, submitted, certified and paid."""

    def test_the_lifecycle_runs_forwards(self):
        item = application()
        item.submit("2024-10-02")
        item.certify("2024-10-09", money("60000"))
        item.mark_paid("2024-11-08")
        self.assertEqual(item.status, "paid")

    def test_certifying_before_submitting_is_refused(self):
        self.assertRaises(SequenceError, application().certify, "2024-10-09")

    def test_a_short_certification_is_a_shortfall(self):
        item = application()
        item.submit("2024-10-02")
        item.certify("2024-10-09", money("60000"))
        self.assertEqual(item.shortfall(), money("97500"))

    def test_certifying_without_an_amount_certifies_the_request(self):
        item = application()
        item.submit("2024-10-02")
        item.certify("2024-10-09")
        self.assertEqual(item.certified_amount, item.requested_amount())

    def test_rejection_records_a_reason(self):
        item = application()
        item.submit("2024-10-02")
        item.reject("2024-10-09", "stored materials not supported")
        self.assertEqual(item.status, "rejected")

    def test_a_register_refuses_two_live_applications_with_one_number(self):
        register = ApplicationRegister([application(1)])
        self.assertRaises(DataError, register.add, application(1))

    def test_the_register_totals_what_was_certified(self):
        first = application(1)
        first.submit("2024-10-02")
        first.certify("2024-10-09", money("60000"))
        register = ApplicationRegister([first, application(2)])
        self.assertEqual(register.certified_to_date(2), money("60000"))


class NumberingTest(unittest.TestCase):
    """Numbers, revisions and the gaps a lender notices."""

    def test_sequential_numbering_continues(self):
        self.assertEqual(next_number([1, 2, 3]), 4)

    def test_period_numbering_takes_the_period(self):
        self.assertEqual(next_number([1, 2], scheme="period", period=5), 5)

    def test_identifiers_are_zero_padded(self):
        self.assertEqual(format_application_id(7), "PA-007")

    def test_revisions_append_a_suffix(self):
        self.assertEqual(revision_id("PA-007", 1), "PA-007R1")
        self.assertEqual(revision_id("PA-007R1", 2), "PA-007R2")

    def test_gaps_are_found(self):
        self.assertEqual(find_gaps([1, 2, 4, 6]), [3, 5])

    def test_consecutive_numbers_pass_the_check(self):
        self.assertIsNone(check_consecutive([1, 2, 3]))

    def test_a_hole_fails_the_check(self):
        self.assertRaises(DataError, check_consecutive, [1, 3])


class RevisionTest(unittest.TestCase):
    """A revision moves what later applications quote as previously certified."""

    def setUp(self):
        self.chain = RevisionChain([Revision("PA-007", "PA-007R1", 1)])

    def test_the_chain_finds_the_live_application(self):
        self.assertEqual(self.chain.current("PA-007"), "PA-007R1")

    def test_the_superseded_one_is_marked(self):
        self.assertTrue(self.chain.is_superseded("PA-007"))

    def test_a_second_supersession_of_the_same_application_is_refused(self):
        self.assertRaises(DataError, self.chain.add, Revision("PA-007", "PA-007R2", 2))

    def test_a_cycle_is_refused(self):
        chain = RevisionChain([Revision("A", "B", 1)])
        self.assertRaises(SequenceError, chain.add, Revision("B", "A", 2))

    def test_history_runs_oldest_first(self):
        self.chain.add(Revision("PA-007R1", "PA-007R2", 2))
        self.assertEqual(self.chain.history("PA-007R2"), ["PA-007", "PA-007R1", "PA-007R2"])

    def test_a_superseded_application_is_left_out_of_previous_certificates(self):
        first = application(1)
        first.submit("2024-10-02")
        first.certify("2024-10-09", money("30000"))
        revised = application(1)
        revised.id = "PA-001R1"
        revised.submit("2024-10-20")
        revised.certify("2024-10-27", money("25000"))
        register = ApplicationRegister([first])
        register.applications["PA-001R1"] = revised
        chain = RevisionChain([Revision("PA-001", "PA-001R1", 1)])
        self.assertEqual(chain.previous_certified(register, 2), money("25000"))


if __name__ == "__main__":
    unittest.main()
