"""Comparing two readings of a job, and explaining one of them."""

import unittest

from strongback.compare.attribute import attribute_difference
from strongback.compare.diff import diff_results, total_difference
from strongback.compare.render import attribution_table, comparison_report, difference_table
from strongback.core.money import money
from strongback.dataio.samples import sample_context
from strongback.engine.run import build_application
from strongback.errors import DataError, InputError
from strongback.explain.line import explain_line, line_facts, retainage_steps_table
from strongback.explain.narrative import narrate, narrate_subject, stage_summary
from strongback.explain.render import explain_run, trace_overview, trace_table
from strongback.policy.resolve import Policy


class DiffTest(unittest.TestCase):
    """Two policies, one set of documents, one priced difference."""

    def setUp(self):
        self.context = sample_context(4)
        self.first = build_application(
            self.context.with_policy(Policy("aia_standard")), 4, evaluate=False
        )
        self.second = build_application(
            self.context.with_policy(Policy("owner_favorable")), 4, evaluate=False
        )
        self.differences, self.summary = diff_results(self.first, self.second)

    def test_the_lines_that_moved_are_reported(self):
        codes = sorted(item.code for item in self.differences)
        self.assertEqual(codes, ["05100", "26200", "31200"])

    def test_a_line_difference_prices_the_payment_effect(self):
        found = {item.code: item for item in self.differences}
        self.assertEqual(found["26200"].billed_delta(), money("-6000.00"))

    def test_the_summary_fields_that_moved_are_reported(self):
        self.assertIn("completed_and_stored", self.summary.fields())

    def test_the_total_difference_is_the_payment_movement(self):
        self.assertEqual(
            total_difference(self.first, self.second),
            self.second.summary.current_payment_due() - self.first.summary.current_payment_due(),
        )

    def test_comparing_different_periods_is_refused(self):
        other = build_application(self.context, 3, evaluate=False)
        self.assertRaises(InputError, diff_results, self.first, other)

    def test_the_rendered_comparison_names_both_policies(self):
        rendered = comparison_report(
            self.first, self.second, self.differences, self.summary, None, ("aia", "owner")
        )
        self.assertIn("aia", rendered)
        self.assertIn("owner", rendered)

    def test_the_difference_table_sorts_by_effect(self):
        rendered = difference_table(self.differences)
        self.assertIn("31200", rendered.splitlines()[2])


class AttributionTest(unittest.TestCase):
    """Each knob is priced on its own, and the remainder is reported."""

    def setUp(self):
        self.context = sample_context(4)
        self.attribution = attribute_difference(
            self.context, Policy("aia_standard"), Policy("owner_favorable"), 4
        )

    def test_the_knobs_that_mattered_are_named(self):
        names = [name for name, _ in self.attribution.ranked()]
        self.assertIn("stored_conversion", names)

    def test_the_parts_and_the_residue_add_to_the_total(self):
        self.assertEqual(
            self.attribution.explained() + self.attribution.residue, self.attribution.total
        )

    def test_a_knob_that_changed_nothing_is_left_out(self):
        names = [name for name, _ in self.attribution.ranked()]
        self.assertNotIn("waiver_require_notarised", names)

    def test_the_attribution_renders_with_the_residue_at_the_foot(self):
        rendered = attribution_table(self.attribution)
        self.assertIn("interaction", rendered)
        self.assertIn("total", rendered)

    def test_attribution_needs_two_policies(self):
        self.assertRaises(
            InputError, attribute_difference, self.context, "aia_standard", Policy(), 4
        )


class ExplainTest(unittest.TestCase):
    """The explanation is read out of the run's own record."""

    def setUp(self):
        self.result = build_application(sample_context(3), 3, evaluate=False)

    def test_the_facts_of_a_line_are_listed(self):
        facts = dict(line_facts(self.result, "03100"))
        self.assertEqual(facts["Scheduled value"], "$410,000.00")
        self.assertIn("Retainage held", facts)

    def test_a_missing_line_is_refused(self):
        self.assertRaises(DataError, line_facts, self.result, "99999")

    def test_the_retainage_steps_are_shown_period_by_period(self):
        rendered = retainage_steps_table(self.result, "03100")
        self.assertEqual(len(rendered.splitlines()), 5)
        self.assertEqual(rendered.splitlines()[2].split()[0], "1")

    def test_the_line_explanation_has_a_heading(self):
        self.assertTrue(explain_line(self.result, "03100").startswith("Line 03100"))

    def test_the_narrative_groups_by_subject(self):
        rendered = narrate(self.result.trace, ["03100"])
        self.assertTrue(rendered.startswith("03100"))

    def test_the_narrative_of_an_unmentioned_subject_is_refused(self):
        self.assertRaises(DataError, narrate_subject, self.result.trace, "99999")

    def test_the_stage_summary_counts_decisions(self):
        counts = dict(stage_summary(self.result.trace))
        self.assertIn("progress", counts)
        self.assertTrue(counts["progress"] > 0)

    def test_the_trace_table_can_be_narrowed(self):
        rendered = trace_table(self.result.trace, subject="03100")
        self.assertNotIn("03300", rendered)

    def test_the_overview_lists_the_stages(self):
        self.assertIn("progress", trace_overview(self.result.trace))

    def test_the_run_explanation_names_the_application(self):
        self.assertTrue(explain_run(self.result).startswith("PA-003"))


if __name__ == "__main__":
    unittest.main()
