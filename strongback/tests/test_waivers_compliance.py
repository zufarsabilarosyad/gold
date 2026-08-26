"""Waivers, insurance, statutory notices and the gates they close."""

import unittest

from strongback.billing.application import PayApplication
from strongback.billing.summary import ApplicationSummary
from strongback.compliance.gate import GateResult, evaluate_gates
from strongback.compliance.insurance import Certificate, InsuranceFile, coverage_gaps
from strongback.compliance.notice import Notice, NoticeRegister, NoticeRule, deadline_for
from strongback.core.dates import format_date
from strongback.core.money import money
from strongback.core.period import monthly_schedule
from strongback.errors import DataError, GateError, InputError
from strongback.waivers.document import LienWaiver, WaiverType
from strongback.waivers.ledger import WaiverLedger, coverage_gap
from strongback.waivers.requirement import WaiverRequirement, required_through


def application(number=3):
    """Build an application for the gate tests."""
    period = monthly_schedule("2024-09-01", number).period(number)
    summary = ApplicationSummary(
        money("500000"), completed_and_stored=money("175000"), retainage_work=money("17500")
    )
    return PayApplication("PA-%03d" % number, number, period, summary=summary)


class WaiverDocumentTest(unittest.TestCase):
    """Two axes, four documents, and the through date."""

    def test_a_conditional_waiver_releases_nothing_until_payment(self):
        waiver = LienWaiver("W-1", "conditional_progress", money("1000"), "2024-09-30")
        self.assertFalse(waiver.is_effective(paid=False))
        self.assertTrue(waiver.is_effective(paid=True))

    def test_an_unconditional_waiver_releases_on_signature(self):
        waiver = LienWaiver("W-2", "unconditional_progress", money("1000"), "2024-09-30")
        self.assertTrue(waiver.is_effective(paid=False))

    def test_a_final_waiver_reaches_retainage(self):
        self.assertTrue(WaiverType("conditional_final").releases_retainage())
        self.assertFalse(WaiverType("conditional_progress").releases_retainage())

    def test_the_counterpart_crosses_the_conditional_axis(self):
        self.assertEqual(
            WaiverType("conditional_progress").counterpart(), WaiverType("unconditional_progress")
        )

    def test_a_through_date_does_not_reach_later_work(self):
        waiver = LienWaiver("W-3", "conditional_progress", money("1000"), "2024-11-30")
        self.assertTrue(waiver.covers_through("2024-11-30"))
        self.assertFalse(waiver.covers_through("2024-12-01"))

    def test_a_progress_waiver_signed_before_its_through_date_is_refused(self):
        self.assertRaises(
            DataError,
            LienWaiver,
            "W-4",
            "conditional_progress",
            money("1000"),
            "2024-11-30",
            "2024-11-01",
        )


class WaiverLedgerTest(unittest.TestCase):
    """The log answers what is released, not what is on file."""

    def setUp(self):
        self.ledger = WaiverLedger(
            [
                LienWaiver("W-1", "conditional_progress", money("40000"), "2024-09-30",
                           "2024-10-02", "PA-001"),
                LienWaiver("W-2", "unconditional_progress", money("40000"), "2024-09-30",
                           "2024-11-04", "PA-001"),
                LienWaiver("W-3", "conditional_progress", money("60000"), "2024-10-31",
                           "2024-11-04", "PA-002"),
            ]
        )

    def test_an_unconditional_waiver_is_recognised(self):
        self.assertTrue(self.ledger.has_unconditional("PA-001"))
        self.assertFalse(self.ledger.has_unconditional("PA-002"))

    def test_pending_conditional_waivers_are_listed(self):
        pending = self.ledger.pending_conditional(["PA-001"])
        self.assertEqual([item.id for item in pending], ["W-3"])

    def test_the_exposure_is_what_is_paid_and_not_released(self):
        self.assertEqual(coverage_gap(self.ledger, money("100000"), ["PA-001"]), money("20000"))

    def test_paying_the_second_application_closes_the_gap(self):
        self.assertEqual(
            coverage_gap(self.ledger, money("100000"), ["PA-001", "PA-002"]), money("0")
        )

    def test_the_ledger_round_trips_through_plain_data(self):
        rebuilt = WaiverLedger.from_list(self.ledger.to_list())
        self.assertEqual(len(rebuilt), len(self.ledger))


class WaiverRequirementTest(unittest.TestCase):
    """What document is required, and what date it has to reach."""

    def test_the_standard_exchange_asks_for_a_conditional_waiver(self):
        requirement = WaiverRequirement()
        self.assertEqual(str(requirement.type_for_current()), "conditional_progress")

    def test_paying_after_the_waiver_asks_for_an_unconditional_one(self):
        requirement = WaiverRequirement(exchange="before_payment")
        self.assertEqual(str(requirement.type_for_current()), "unconditional_progress")

    def test_an_exchange_after_payment_does_not_gate(self):
        self.assertFalse(WaiverRequirement(exchange="after_payment").gates_payment())

    def test_the_through_rule_moves_the_date_required(self):
        period = monthly_schedule("2024-11-01", 1, through_day=25).period(1)
        self.assertEqual(format_date(required_through(WaiverRequirement(), period)), "2024-11-30")
        self.assertEqual(
            format_date(
                required_through(WaiverRequirement(through_rule="application_through"), period)
            ),
            "2024-11-25",
        )

    def test_an_unnotarised_waiver_fails_a_notarised_requirement(self):
        requirement = WaiverRequirement(require_notarised=True)
        waiver = LienWaiver(
            "W-1", "conditional_progress", money("1000"), "2024-11-30", "2024-12-01"
        )
        self.assertEqual(requirement.accepts(waiver), ["waiver W-1 is not notarised"])

    def test_an_excepted_waiver_fails_unless_exceptions_are_allowed(self):
        waiver = LienWaiver(
            "W-2",
            "conditional_progress",
            money("1000"),
            "2024-11-30",
            "2024-12-01",
            exceptions=["retainage"],
        )
        self.assertEqual(len(WaiverRequirement().accepts(waiver)), 1)
        self.assertEqual(WaiverRequirement(allow_exceptions=True).accepts(waiver), [])


class InsuranceTest(unittest.TestCase):
    """Coverage is a date range, and endorsements are separate boxes."""

    def setUp(self):
        self.file = InsuranceFile(
            [
                Certificate(
                    "COI-1",
                    "general_liability",
                    "2024-07-01",
                    "2025-07-01",
                    money("1000000"),
                    money("2000000"),
                    additional_insured=True,
                )
            ]
        )

    def test_coverage_inside_the_range(self):
        self.assertTrue(self.file.covered_on("general_liability", "2024-11-30"))

    def test_no_coverage_after_expiry(self):
        self.assertFalse(self.file.covered_on("general_liability", "2025-08-01"))

    def test_a_missing_coverage_is_reported(self):
        problems = self.file.check("2024-11-01", {"auto": None})
        self.assertEqual(problems, ["no auto coverage in force on 2024-11-01"])

    def test_a_limit_below_the_requirement_is_reported(self):
        problems = self.file.check("2024-11-01", {"general_liability": money("2000000")})
        self.assertEqual(len(problems), 1)

    def test_a_missing_endorsement_is_reported(self):
        problems = self.file.check(
            "2024-11-01", {"general_liability": None}, ["waiver_of_subrogation"]
        )
        self.assertEqual(len(problems), 1)

    def test_a_renewal_gap_is_found(self):
        file = InsuranceFile(
            [
                Certificate("A", "general_liability", "2024-01-01", "2024-07-01"),
                Certificate("B", "general_liability", "2024-08-01", "2025-01-01"),
            ]
        )
        gaps = coverage_gaps(file, "general_liability", "2024-01-01", "2024-12-31")
        self.assertEqual(
            [(format_date(start), format_date(end)) for start, end in gaps],
            [("2024-07-01", "2024-07-31")],
        )

    def test_a_certificate_expiring_before_it_starts_is_refused(self):
        self.assertRaises(
            DataError, Certificate, "COI-9", "auto", "2025-01-01", "2024-01-01"
        )


class NoticeTest(unittest.TestCase):
    """Deadlines run from events, and events are not invoices."""

    def setUp(self):
        self.register = NoticeRegister([NoticeRule("preliminary", "first_furnishing", 20)])
        self.events = {"first_furnishing": "2024-09-16"}

    def test_the_deadline_is_computed_from_the_event(self):
        self.assertEqual(
            format_date(self.register.deadline("preliminary", self.events)), "2024-10-07"
        )

    def test_a_notice_inside_the_window_is_timely(self):
        self.register.serve(Notice("N-1", "preliminary", "2024-10-01"))
        self.assertTrue(self.register.is_timely("preliminary", self.events))

    def test_a_late_notice_is_not(self):
        self.register.serve(Notice("N-2", "preliminary", "2024-11-01"))
        self.assertFalse(self.register.is_timely("preliminary", self.events))

    def test_missing_notices_are_listed(self):
        self.assertEqual(self.register.missing(self.events), ["preliminary"])

    def test_a_deadline_needs_its_event(self):
        self.assertRaises(DataError, self.register.deadline, "preliminary", {})

    def test_a_single_deadline_can_be_computed_directly(self):
        self.assertEqual(format_date(deadline_for("lien", "2024-12-20", 90)), "2025-03-20")


class GateTest(unittest.TestCase):
    """A gate holds a payment; it does not reduce it."""

    def setUp(self):
        self.application = application()
        self.ledger = WaiverLedger()

    def test_a_missing_waiver_blocks(self):
        result = evaluate_gates(self.application, WaiverRequirement(), self.ledger)
        self.assertFalse(result.ok())
        self.assertEqual(
            result.reasons(), ["waivers: no conditional_progress waiver on file for PA-003"]
        )

    def test_the_right_waiver_clears_it(self):
        self.ledger.add(
            LienWaiver(
                "W-3", "conditional_progress", money("67500"), "2024-11-30", "2024-12-02", "PA-003"
            )
        )
        self.assertTrue(evaluate_gates(self.application, WaiverRequirement(), self.ledger).ok())

    def test_a_waiver_that_stops_short_of_the_period_end_blocks(self):
        self.ledger.add(
            LienWaiver(
                "W-3", "conditional_progress", money("67500"), "2024-11-20", "2024-12-02", "PA-003"
            )
        )
        result = evaluate_gates(self.application, WaiverRequirement(), self.ledger)
        self.assertTrue(any("covers through" in reason for reason in result.reasons()))

    def test_the_previous_unconditional_waiver_is_required(self):
        self.ledger.add(
            LienWaiver(
                "W-3", "conditional_progress", money("67500"), "2024-11-30", "2024-12-02", "PA-003"
            )
        )
        result = evaluate_gates(
            self.application,
            WaiverRequirement(),
            self.ledger,
            previous_application_id="PA-002",
        )
        self.assertIn("waivers: no unconditional waiver on file for PA-002", result.reasons())

    def test_lapsed_insurance_blocks(self):
        self.ledger.add(
            LienWaiver(
                "W-3", "conditional_progress", money("67500"), "2024-11-30", "2024-12-02", "PA-003"
            )
        )
        insurance = InsuranceFile([])
        result = evaluate_gates(
            self.application,
            WaiverRequirement(),
            self.ledger,
            insurance,
            {"general_liability": None},
        )
        self.assertFalse(result.ok())

    def test_a_notice_problem_warns_rather_than_blocks(self):
        self.ledger.add(
            LienWaiver(
                "W-3", "conditional_progress", money("67500"), "2024-11-30", "2024-12-02", "PA-003"
            )
        )
        notices = NoticeRegister([NoticeRule("preliminary", "first_furnishing", 20)])
        result = evaluate_gates(
            self.application,
            WaiverRequirement(),
            self.ledger,
            None,
            None,
            notices,
            {"first_furnishing": "2024-09-16"},
        )
        self.assertTrue(result.ok())
        self.assertEqual(result.warning_text(), ["notices: no timely preliminary notice"])

    def test_a_blocked_gate_can_raise(self):
        result = GateResult()
        result.block("insurance", "lapsed")
        self.assertRaises(GateError, result.raise_if_blocked)


if __name__ == "__main__":
    unittest.main()
