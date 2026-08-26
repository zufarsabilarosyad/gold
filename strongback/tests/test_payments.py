"""Due dates, receipts, allocation, aging, interest, pay-chains and joint cheques."""

import unittest

from strongback.billing.application import PayApplication
from strongback.billing.summary import ApplicationSummary
from strongback.core.dates import format_date
from strongback.core.money import money
from strongback.core.period import monthly_schedule
from strongback.core.workcalendar import calendar_named
from strongback.errors import DataError, InputError
from strongback.model.terms import PaymentTerms
from strongback.payments.aging import age_applications
from strongback.payments.allocation import Allocation, allocate_receipt, open_balances
from strongback.payments.chain import chain_due_date, chain_status
from strongback.payments.due import days_late, due_date, is_late, start_date_for
from strongback.payments.interest import InterestTerms, accrue_interest, day_count_fraction
from strongback.payments.jointcheck import JointCheck, credited_to_payee, split_joint_check
from strongback.payments.receipt import Receipt, ReceiptLedger


def application(number=1, due="40000", **kwargs):
    """Build an application asking for a given amount."""
    period = monthly_schedule("2024-09-01", number).period(number)
    summary = ApplicationSummary(money("500000"), completed_and_stored=money(due))
    return PayApplication("PA-%03d" % number, number, period, summary=summary, **kwargs)


class DueDateTest(unittest.TestCase):
    """The clock starts at an event and runs on a calendar."""

    def setUp(self):
        self.application = application(
            1, submitted_on="2024-10-03", certified_on="2024-10-11"
        )

    def test_certification_starts_the_clock_by_default(self):
        terms = PaymentTerms(net_days=30)
        self.assertEqual(format_date(due_date(terms, self.application)), "2024-11-12")

    def test_receipt_starts_it_earlier(self):
        terms = PaymentTerms(net_days=30, start_event="receipt_date")
        self.assertEqual(format_date(due_date(terms, self.application)), "2024-11-04")

    def test_business_days_are_a_different_count(self):
        terms = PaymentTerms(net_days=10, day_basis="business")
        self.assertEqual(format_date(due_date(terms, self.application)), "2024-10-28")

    def test_an_uncertified_application_uses_the_certification_window(self):
        pending = application(2, submitted_on="2024-10-03")
        terms = PaymentTerms(net_days=30, certification_days=7)
        self.assertEqual(format_date(start_date_for(terms, pending)), "2024-10-10")

    def test_a_due_date_rolls_off_a_holiday(self):
        item = application(3, submitted_on="2024-11-20", certified_on="2024-11-21")
        terms = PaymentTerms(net_days=7)
        self.assertEqual(format_date(due_date(terms, item)), "2024-11-29")

    def test_lateness_is_counted_from_the_due_date(self):
        self.assertEqual(days_late("2024-11-12", "2024-11-20"), 8)
        self.assertEqual(days_late("2024-11-12", "2024-11-01"), 0)

    def test_an_unpaid_application_needs_an_as_of_date(self):
        self.assertRaises(InputError, is_late, "2024-11-12")


class ReceiptTest(unittest.TestCase):
    """Receipts record what arrived, not what was owed."""

    def setUp(self):
        self.ledger = ReceiptLedger(
            [
                Receipt("R-1", money("60000"), "2024-11-15"),
                Receipt("R-2", money("42000"), "2024-12-18"),
            ]
        )

    def test_totals_run_to_a_date(self):
        self.assertEqual(self.ledger.total_through("2024-11-30"), money("60000"))

    def test_receipts_in_a_window_are_found(self):
        found = self.ledger.between("2024-12-01", "2024-12-31")
        self.assertEqual([item.id for item in found], ["R-2"])

    def test_a_joint_cheque_names_its_payees(self):
        receipt = Receipt(
            "R-3", money("10000"), "2024-12-20", method="joint_check", joint_payees=["SUP-1"]
        )
        self.assertTrue(receipt.is_joint())

    def test_a_joint_cheque_with_no_joint_payee_is_refused(self):
        self.assertRaises(
            DataError, Receipt, "R-4", money("1"), "2024-12-20", "joint_check"
        )

    def test_the_ledger_round_trips_through_plain_data(self):
        rebuilt = ReceiptLedger.from_list(self.ledger.to_list())
        self.assertEqual(rebuilt.total(), self.ledger.total())


class AllocationTest(unittest.TestCase):
    """Which application a cheque pays is a convention."""

    def setUp(self):
        self.first = application(1, "40000")
        self.second = application(2, "30000")
        self.receipt = Receipt("R-1", money("55000"), "2024-11-20")

    def test_oldest_first_clears_the_earliest(self):
        allocations = allocate_receipt(self.receipt, [self.first, self.second])
        self.assertEqual(
            [(item.application_id, item.amount) for item in allocations],
            [("PA-001", money("40000")), ("PA-002", money("15000"))],
        )

    def test_newest_first_clears_the_latest(self):
        allocations = allocate_receipt(
            self.receipt, [self.first, self.second], order="newest_first"
        )
        self.assertEqual(allocations[0].application_id, "PA-002")

    def test_pro_rata_credits_everything(self):
        allocations = allocate_receipt(
            self.receipt, [self.first, self.second], order="pro_rata"
        )
        self.assertEqual(len(allocations), 2)
        total = allocations[0].amount + allocations[1].amount
        self.assertEqual(total, money("55000.00"))

    def test_a_remittance_advice_is_followed(self):
        allocations = allocate_receipt(
            self.receipt,
            [self.first, self.second],
            order="specified",
            specified={"PA-002": money("30000")},
        )
        self.assertEqual(allocations[0].application_id, "PA-002")

    def test_a_remittance_advice_over_the_cheque_is_refused(self):
        self.assertRaises(
            DataError,
            allocate_receipt,
            self.receipt,
            [self.first],
            (),
            "specified",
            {"PA-001": money("90000")},
        )

    def test_balances_fall_as_allocations_are_recorded(self):
        allocations = [Allocation("R-1", "PA-001", money("40000"))]
        balances = open_balances([self.first, self.second], allocations)
        self.assertEqual(balances["PA-001"], money("0"))
        self.assertEqual(balances["PA-002"], money("30000"))


class AgingTest(unittest.TestCase):
    """The basis decides which bucket a balance falls in."""

    def setUp(self):
        self.applications = [
            application(1, application_date="2024-10-02"),
            application(2, application_date="2024-11-02"),
        ]
        self.balances = {"PA-001": money("50000"), "PA-002": money("30000")}

    def test_ageing_from_the_application_date(self):
        rows = age_applications(
            self.applications, self.balances, "2024-12-15", basis="application_date"
        )
        found = {row.label: row.total for row in rows if len(row)}
        self.assertEqual(found["61-90"], money("50000"))
        self.assertEqual(found["31-60"], money("30000"))

    def test_ageing_from_the_due_date_shows_less(self):
        due_dates = {"PA-001": "2024-12-01", "PA-002": "2024-12-20"}
        rows = age_applications(
            self.applications, self.balances, "2024-12-15", due_dates=due_dates
        )
        found = {row.label: row.total for row in rows if len(row)}
        self.assertEqual(found["1-30"], money("50000"))
        self.assertEqual(found["current"], money("30000"))

    def test_ageing_without_a_due_date_is_refused(self):
        self.assertRaises(
            DataError, age_applications, self.applications, self.balances, "2024-12-15"
        )


class InterestTest(unittest.TestCase):
    """Day count, grace and compounding each move the number."""

    def test_no_interest_before_the_due_date(self):
        terms = InterestTerms("12%")
        self.assertEqual(
            accrue_interest(money("100000"), "2024-11-12", "2024-11-12", terms), money("0")
        )

    def test_simple_interest_on_a_365_day_year(self):
        terms = InterestTerms("12%")
        interest = accrue_interest(money("100000"), "2024-11-12", "2024-12-12", terms)
        self.assertEqual(interest.rounded(), money("986.30"))

    def test_a_360_day_year_is_slightly_more(self):
        terms = InterestTerms("12%", day_count="actual_360")
        interest = accrue_interest(money("100000"), "2024-11-12", "2024-12-12", terms)
        self.assertEqual(interest.rounded(), money("1000.00"))

    def test_the_grace_period_suppresses_interest_entirely(self):
        terms = InterestTerms("12%", grace_days=7)
        self.assertEqual(
            accrue_interest(money("100000"), "2024-11-12", "2024-11-18", terms), money("0")
        )

    def test_past_the_grace_period_interest_runs_from_the_due_date(self):
        terms = InterestTerms("12%", grace_days=7)
        interest = accrue_interest(money("100000"), "2024-11-12", "2024-11-25", terms)
        self.assertEqual(interest.rounded(), money("427.40"))

    def test_thirty_360_is_a_third_convention(self):
        fraction = day_count_fraction("2024-11-01", "2024-12-01", "thirty_360")
        self.assertEqual(str(fraction)[:6], "0.0833")

    def test_interest_cannot_run_backwards(self):
        self.assertRaises(DataError, day_count_fraction, "2024-12-01", "2024-11-01")


class PayChainTest(unittest.TestCase):
    """Pay-when-paid defers; pay-if-paid can extinguish."""

    def setUp(self):
        self.when = PaymentTerms(net_days=30, chain_rule="pay_when_paid", chain_days=7)
        self.if_paid = PaymentTerms(net_days=30, chain_rule="pay_if_paid")

    def test_an_upstream_payment_starts_the_downstream_clock(self):
        self.assertEqual(
            format_date(chain_due_date("2024-12-05", "2024-12-10", self.when)), "2024-12-17"
        )

    def test_an_early_upstream_payment_does_not_pull_the_date_in(self):
        self.assertEqual(
            format_date(chain_due_date("2024-12-05", "2024-11-01", self.when)), "2024-12-05"
        )

    def test_without_upstream_payment_the_obligation_waits(self):
        self.assertEqual(
            chain_status("2024-12-05", None, self.when, "2024-12-10").status, "waiting_upstream"
        )

    def test_the_long_stop_matures_it_anyway(self):
        self.assertEqual(
            chain_status("2024-09-05", None, self.when, "2024-12-20").status, "due"
        )

    def test_pay_if_paid_extinguishes_after_the_long_stop(self):
        self.assertEqual(
            chain_status("2024-12-05", None, self.if_paid, "2025-06-01").status, "extinguished"
        )

    def test_an_unenforceable_clause_leaves_the_money_owed(self):
        outcome = chain_status(
            "2024-12-05", None, self.if_paid, "2025-06-01", enforceable=False
        )
        self.assertEqual(outcome.status, "due")

    def test_an_ordinary_clause_is_unaffected(self):
        outcome = chain_status("2024-12-05", None, PaymentTerms(), "2025-01-01")
        self.assertTrue(outcome.is_payable())


class JointCheckTest(unittest.TestCase):
    """A joint cheque splits, and how much it credits is a convention."""

    def setUp(self):
        self.check = JointCheck(
            "JC-1", money("42000"), "SUB-STEEL", {"SUP-MILL": money("31000")}
        )

    def test_the_remainder_goes_to_the_payee(self):
        split = split_joint_check(self.check)
        self.assertEqual(split["SUP-MILL"], money("31000"))
        self.assertEqual(split["SUB-STEEL"], money("11000"))

    def test_an_oversubscribed_cheque_shares_out_pro_rata(self):
        tight = JointCheck(
            "JC-2",
            money("30000"),
            "SUB-STEEL",
            {"SUP-MILL": money("25000"), "SUP-DECK": money("15000")},
        )
        split = split_joint_check(tight)
        self.assertEqual(split["SUP-MILL"], money("18750.00"))
        self.assertEqual(split["SUB-STEEL"], money("0"))

    def test_the_full_convention_credits_the_whole_cheque(self):
        self.assertEqual(credited_to_payee(self.check, "full"), money("42000"))

    def test_the_net_convention_credits_only_what_the_payee_banked(self):
        self.assertEqual(credited_to_payee(self.check, "net"), money("11000"))


if __name__ == "__main__":
    unittest.main()
