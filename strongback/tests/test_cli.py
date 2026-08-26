"""The command line: arguments, exit codes and output."""

import io
import json
import os
import tempfile
import unittest

from strongback.cli.args import parse_setting, policy_from_args
from strongback.cli.main import build_parser, main
from strongback.dataio.dump import write_json_file
from strongback.dataio.samples import sample_context
from strongback.errors import InputError


def run(argv):
    """Run the command line and return its exit code and output."""
    out = io.StringIO()
    code = main(argv, out)
    return code, out.getvalue()


class ParserTest(unittest.TestCase):
    """Every command registers and describes itself."""

    def test_the_parser_builds(self):
        self.assertEqual(build_parser().prog, "strongback")

    def test_no_command_prints_help_and_asks_for_one(self):
        code, output = run([])
        self.assertEqual(code, 2)
        self.assertIn("COMMAND", output)

    def test_an_override_is_split_on_the_equals_sign(self):
        self.assertEqual(parse_setting("previous_basis=paid"), ("previous_basis", "paid"))

    def test_an_override_without_a_value_is_refused(self):
        self.assertRaises(InputError, parse_setting, "previous_basis")

    def test_overrides_reach_the_policy(self):
        class Args(object):
            profile = "public_works"
            settings = ["previous_basis=certified"]

        policy = policy_from_args(Args())
        self.assertEqual(policy.source("previous_basis"), "override")


class CommandTest(unittest.TestCase):
    """Each command runs on the built-in sample."""

    def test_validate_is_clean_on_the_sample(self):
        code, output = run(["validate"])
        self.assertEqual(code, 0)
        self.assertIn("no problems found", output)

    def test_schedule_lists_the_lines(self):
        code, output = run(["schedule", "--period", "2"])
        self.assertEqual(code, 0)
        self.assertIn("03300", output)
        self.assertIn("Total", output)

    def test_schedule_can_write_csv(self):
        code, output = run(["schedule", "--csv"])
        self.assertEqual(code, 0)
        self.assertTrue(output.startswith("code,description,scheduled_value"))

    def test_progress_shows_earned_value(self):
        code, output = run(["progress", "--period", "2"])
        self.assertEqual(code, 0)
        self.assertIn("Earned", output)

    def test_progress_can_show_the_raw_reports(self):
        code, output = run(["progress", "--entries", "--period", "1"])
        self.assertEqual(code, 0)
        self.assertIn("Reported", output)

    def test_bill_prints_an_application(self):
        code, output = run(["bill", "2"])
        self.assertEqual(code, 0)
        self.assertIn("Application for payment", output)
        self.assertIn("8. Current payment due", output)

    def test_bill_can_print_the_sheet(self):
        code, output = run(["bill", "2", "--sheet"])
        self.assertIn("Continuation sheet", output)

    def test_bill_returns_one_when_a_gate_blocks(self):
        code, output = run(["bill", "3", "--gates"])
        self.assertEqual(code, 1)
        self.assertIn("Payment held", output)

    def test_retainage_reports_the_movement(self):
        code, output = run(["retainage", "--movement"])
        self.assertEqual(code, 0)
        self.assertIn("Movement", output)

    def test_waivers_reports_the_exposure(self):
        code, output = run(["waivers", "--paid", "PA-001"])
        self.assertEqual(code, 1)
        self.assertIn("Unreleased", output)

    def test_payments_ages_the_open_items(self):
        code, output = run(["payments", "--as-of", "2025-01-15"])
        self.assertEqual(code, 0)
        self.assertIn("Aging", output)

    def test_payments_can_accrue_interest(self):
        code, output = run(["payments", "--as-of", "2025-01-15", "--interest", "12%"])
        self.assertIn("Interest", output)

    def test_wip_reports_the_position(self):
        code, output = run(["wip"])
        self.assertEqual(code, 0)
        self.assertIn("Over/(Under)", output)

    def test_compare_prices_two_profiles(self):
        code, output = run(["compare", "3", "aia_standard", "owner_favorable"])
        self.assertEqual(code, 0)
        self.assertIn("difference", output)

    def test_compare_can_attribute_the_difference(self):
        code, output = run(["compare", "4", "aia_standard", "owner_favorable", "--attribute"])
        self.assertIn("interaction", output)

    def test_explain_narrates_a_line(self):
        code, output = run(["explain", "2", "--line", "03100"])
        self.assertEqual(code, 0)
        self.assertIn("Line 03100", output)

    def test_explain_can_print_the_trace_as_a_table(self):
        code, output = run(["explain", "2", "--table"])
        self.assertIn("Decision", output)

    def test_policy_lists_the_profiles(self):
        code, output = run(["policy", "--list-profiles"])
        self.assertEqual(code, 0)
        self.assertIn("owner_favorable", output)

    def test_policy_explains_a_knob(self):
        code, output = run(["policy", "--knob", "previous_basis"])
        self.assertIn("allowed: certified, paid", output)

    def test_policy_diffs_two_profiles(self):
        code, output = run(["policy", "--profile", "aia_standard", "--against", "lender_draw"])
        self.assertIn("stored_conversion", output)

    def test_summary_prints_the_job(self):
        code, output = run(["summary"])
        self.assertEqual(code, 0)
        self.assertIn("Job summary", output)

    def test_closeout_lists_outstanding_documents(self):
        code, output = run(["closeout"])
        self.assertEqual(code, 0)
        self.assertIn("Outstanding documents", output)

    def test_export_writes_a_loadable_run(self):
        code, output = run(["export", "run"])
        self.assertEqual(code, 0)
        document = json.loads(output)
        self.assertEqual(document["contract"]["id"], "C-2024-118")

    def test_export_writes_the_sheet_as_csv(self):
        code, output = run(["export", "sheet", "--period", "2"])
        self.assertTrue(output.startswith("code,description"))

    def test_demo_runs_the_sample_job(self):
        code, output = run(["demo", "--periods", "2"])
        self.assertEqual(code, 0)
        self.assertIn("Retainage movement", output)


class FileInputTest(unittest.TestCase):
    """A run document on disk is read the same way as the sample."""

    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        write_json_file(self.path, sample_context(2))

    def tearDown(self):
        os.unlink(self.path)

    def test_a_document_can_be_billed(self):
        code, output = run(["bill", "2", "--file", self.path])
        self.assertEqual(code, 0)
        self.assertIn("C-2024-118", output)

    def test_a_profile_applies_to_a_loaded_document(self):
        code, output = run(["summary", "--file", self.path, "--profile", "owner_favorable"])
        self.assertEqual(code, 0)
        self.assertIn("owner_favorable", output)

    def test_a_bad_setting_is_a_usage_error(self):
        code, output = run(["summary", "--set", "previous_basis=someday"])
        self.assertEqual(code, 2)
        self.assertIn("strongback:", output)


if __name__ == "__main__":
    unittest.main()
