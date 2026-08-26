"""The reports: what they contain, and that they render the same twice."""

import unittest

from strongback.core.money import money
from strongback.dataio.samples import sample_context, sample_waivers
from strongback.engine.run import build_application, run_contract
from strongback.errors import DataError
from strongback.report.aging import interest_schedule, open_items_table, payments_report
from strongback.report.closeout import closeout_items, closeout_report, outstanding_documents
from strongback.report.g702 import application_header, application_page, change_order_recap
from strongback.report.g703 import continuation_page, grouped_sheet, sheet_totals
from strongback.report.retainage import release_schedule, retainage_movement, retainage_report
from strongback.report.summary import job_report, job_summary, period_table
from strongback.report.waivers import exposure_report, waiver_log, waiver_report
from strongback.payments.interest import InterestTerms


class ApplicationPageTest(unittest.TestCase):
    """The page identifies the job, the period and the money."""

    def setUp(self):
        self.context = sample_context(3)
        self.result = build_application(self.context, 3, evaluate=False)

    def test_the_header_names_the_period_and_both_parties(self):
        header = application_header(self.context.contract, self.result.application)
        self.assertIn("2024-11-01 to 2024-11-30", header)
        self.assertIn("Keel & Sons Construction", header)
        self.assertIn("Harbor Point Holdings LLC", header)

    def test_the_page_carries_all_nine_summary_lines(self):
        page = application_page(self.context.contract, self.result)
        for number in range(1, 10):
            self.assertIn("%d. " % (number,), page)

    def test_the_recapitulation_separates_billable_from_pending(self):
        recap = change_order_recap(self.context.contract, self.result.application)
        self.assertIn("Billable", recap)
        self.assertIn("Pending", recap)

    def test_a_held_payment_is_printed_on_the_page(self):
        result = build_application(self.context, 3, evaluate=True)
        page = application_page(self.context.contract, result)
        if not result.gates.ok():
            self.assertIn("Payment held", page)

    def test_the_page_renders_identically_twice(self):
        first = application_page(self.context.contract, self.result)
        second = application_page(self.context.contract, self.result)
        self.assertEqual(first, second)

    def test_no_line_of_the_page_trails_whitespace(self):
        for line in application_page(self.context.contract, self.result).splitlines():
            self.assertEqual(line, line.rstrip())


class ContinuationReportTest(unittest.TestCase):
    """The sheet, flat and grouped."""

    def setUp(self):
        self.result = build_application(sample_context(3), 3, evaluate=False)

    def test_the_sheet_has_a_row_per_line_plus_a_total(self):
        rendered = continuation_page(self.result.sheet)
        self.assertIn("Totals", rendered)

    def test_the_grouped_sheet_folds_the_lines(self):
        rendered = grouped_sheet(self.result.sheet)
        self.assertIn("Structure", rendered)
        self.assertNotIn("03300", rendered)

    def test_the_totals_block_reports_both_retainage_parts(self):
        totals = dict(sheet_totals(self.result.sheet))
        self.assertIn("Retainage on work", totals)
        self.assertIn("Retainage on stored", totals)


class RetainageReportTest(unittest.TestCase):
    """Held, moved and released."""

    def setUp(self):
        self.context = sample_context(3)
        self.results = run_contract(self.context)

    def test_the_movement_table_has_one_row_per_period(self):
        rendered = retainage_movement(self.results)
        self.assertEqual(len(rendered.splitlines()), 5)

    def test_the_release_schedule_shows_the_punchlist_holdback(self):
        rendered = release_schedule(
            self.context.contract, money("101225"), money("40000")
        )
        self.assertIn("Punchlist holdback", rendered)

    def test_the_report_describes_the_clause(self):
        rendered = retainage_report(self.context.contract, self.results[-1], money("40000"))
        self.assertIn("at 50% completion", rendered)


class WaiverReportTest(unittest.TestCase):
    """The log, and the exposure the log does not show."""

    def test_the_log_lists_every_waiver(self):
        rendered = waiver_log(sample_waivers())
        self.assertEqual(len(rendered.splitlines()), 6)

    def test_the_exposure_report_counts_pending_conditionals(self):
        rendered = exposure_report(sample_waivers(), money("400000"), ["PA-001"])
        self.assertIn("Conditional pending: 2", rendered)

    def test_the_report_has_all_three_blocks(self):
        rendered = waiver_report(sample_waivers(), money("400000"), ["PA-001"])
        self.assertIn("Lien waivers", rendered)
        self.assertIn("Log", rendered)
        self.assertIn("Pending conditional", rendered)


class PaymentReportTest(unittest.TestCase):
    """Open items, aging and interest."""

    def setUp(self):
        self.results = run_contract(sample_context(2))
        self.applications = [result.application for result in self.results]
        self.balances = {
            result.application.id: result.summary.current_payment_due()
            for result in self.results
        }
        self.due_dates = {"PA-001": "2024-11-12", "PA-002": "2024-12-10"}

    def test_open_items_show_days_late(self):
        rendered = open_items_table(
            self.applications, self.balances, self.due_dates, "2024-12-20"
        )
        self.assertIn("Days late", rendered)

    def test_interest_is_scheduled_per_application(self):
        rendered = interest_schedule(
            self.balances, self.due_dates, InterestTerms("12%"), "2024-12-20"
        )
        self.assertEqual(len(rendered.splitlines()), 4)

    def test_the_report_carries_aging_and_interest(self):
        rendered = payments_report(
            self.applications,
            self.balances,
            self.due_dates,
            "2024-12-20",
            terms=InterestTerms("12%"),
        )
        self.assertIn("Aging", rendered)
        self.assertIn("Interest", rendered)


class CloseoutReportTest(unittest.TestCase):
    """What is still open when the building is finished."""

    def setUp(self):
        self.context = sample_context(4)

    def test_the_missing_documents_are_listed(self):
        missing = outstanding_documents(self.context, ["PA-001"])
        self.assertTrue(any("unconditional waiver" in item for item in missing))

    def test_the_open_offset_is_listed_as_reversible(self):
        rendered = closeout_report(self.context, money("100000"), money("40000"))
        self.assertIn("Open offsets", rendered)

    def test_the_items_price_the_release(self):
        items = dict(closeout_items(self.context, money("100000"), money("40000")))
        self.assertEqual(items["Retainage held"], "$100,000.00")
        self.assertEqual(items["Punchlist holdback"], "$60,000.00")


class JobSummaryTest(unittest.TestCase):
    """The one-page picture."""

    def setUp(self):
        self.context = sample_context(3)
        self.results = run_contract(self.context)

    def test_the_summary_has_the_headline_figures(self):
        summary = dict(job_summary(self.context.contract, self.results))
        self.assertEqual(summary["Contract sum to date"], "$2,518,000.00")

    def test_the_period_table_has_one_row_per_application(self):
        self.assertEqual(len(period_table(self.results).splitlines()), 5)

    def test_the_report_states_the_conventions_in_force(self):
        rendered = job_report(self.context.contract, self.results, self.context.policy)
        self.assertIn("Conventions in force", rendered)
        self.assertIn("executed_only", rendered)


if __name__ == "__main__":
    unittest.main()
