"""A run is a function of its inputs, and produces the same bytes every time.

These are the tests that would catch a dictionary iteration order leaking into
a report, a clock being read, or a hash seed changing an answer.  They are
cheap and they fail loudly, which is what a determinism check is for.
"""

import io
import subprocess
import sys
import unittest

from strongback.cli.main import main
from strongback.dataio.dump import dump_json, dump_result
from strongback.dataio.samples import sample_context
from strongback.engine.run import build_application, run_contract
from strongback.policy.resolve import Policy
from strongback.report.g702 import application_page
from strongback.report.summary import job_report


def command(argv):
    """Run a command and return its output."""
    out = io.StringIO()
    main(argv, out)
    return out.getvalue()


class RepeatedRunTest(unittest.TestCase):
    """The same context billed twice gives the same answer."""

    def test_two_runs_agree_on_every_figure(self):
        first = build_application(sample_context(4), 4, evaluate=False)
        second = build_application(sample_context(4), 4, evaluate=False)
        self.assertEqual(first.summary.to_dict(), second.summary.to_dict())

    def test_two_runs_produce_the_same_sheet(self):
        first = build_application(sample_context(3), 3, evaluate=False)
        second = build_application(sample_context(3), 3, evaluate=False)
        self.assertEqual(first.sheet.to_list(), second.sheet.to_list())

    def test_two_runs_produce_the_same_trace(self):
        first = build_application(sample_context(3), 3, evaluate=False)
        second = build_application(sample_context(3), 3, evaluate=False)
        self.assertEqual(first.trace.to_list(), second.trace.to_list())

    def test_a_whole_contract_runs_identically(self):
        first = [result.summary.to_dict() for result in run_contract(sample_context(4))]
        second = [result.summary.to_dict() for result in run_contract(sample_context(4))]
        self.assertEqual(first, second)

    def test_billing_one_period_matches_billing_them_all(self):
        alone = build_application(sample_context(4), 4, evaluate=False)
        in_sequence = run_contract(sample_context(4))[-1]
        self.assertEqual(
            alone.sheet.total_completed_and_stored(),
            in_sequence.sheet.total_completed_and_stored(),
        )


class RenderedOutputTest(unittest.TestCase):
    """Reports are byte-identical between runs."""

    def test_the_application_page_is_stable(self):
        context = sample_context(3)
        result = build_application(context, 3, evaluate=False)
        first = application_page(context.contract, result)
        second = application_page(context.contract, build_application(context, 3, evaluate=False))
        self.assertEqual(first, second)

    def test_the_job_report_is_stable(self):
        context = sample_context(3)
        first = job_report(context.contract, run_contract(context), context.policy)
        context = sample_context(3)
        second = job_report(context.contract, run_contract(context), context.policy)
        self.assertEqual(first, second)

    def test_the_exported_run_is_stable(self):
        self.assertEqual(dump_json(sample_context(3)), dump_json(sample_context(3)))

    def test_the_exported_result_is_stable(self):
        first = dump_result(build_application(sample_context(2), 2, evaluate=False))
        second = dump_result(build_application(sample_context(2), 2, evaluate=False))
        self.assertEqual(first, second)

    def test_every_command_repeats_itself(self):
        for argv in (
            ["summary"],
            ["bill", "3"],
            ["retainage", "--movement"],
            ["wip"],
            ["compare", "3", "aia_standard", "owner_favorable"],
        ):
            self.assertEqual(command(argv), command(argv), argv)


class HashSeedTest(unittest.TestCase):
    """Output does not depend on the interpreter's hash seed."""

    def _run_with_seed(self, seed):
        """Run a command in a subprocess under a fixed hash seed."""
        return subprocess.check_output(
            [sys.executable, "-m", "strongback", "summary", "--periods", "3"],
            env=dict(PYTHONHASHSEED=seed, PATH="/usr/bin:/bin", PYTHONPATH="."),
        )

    def test_two_hash_seeds_give_the_same_report(self):
        self.assertEqual(self._run_with_seed("0"), self._run_with_seed("12345"))

    def test_a_third_seed_agrees_too(self):
        self.assertEqual(self._run_with_seed("1"), self._run_with_seed("98765"))


class PolicyIsolationTest(unittest.TestCase):
    """Running under one policy does not disturb another."""

    def test_a_comparison_leaves_the_original_context_alone(self):
        context = sample_context(3)
        before = build_application(context, 3, evaluate=False).summary.to_dict()
        build_application(context.with_policy(Policy("owner_favorable")), 3, evaluate=False)
        after = build_application(context, 3, evaluate=False).summary.to_dict()
        self.assertEqual(before, after)

    def test_the_order_of_two_policy_runs_does_not_matter(self):
        context = sample_context(3)
        owner = build_application(
            context.with_policy(Policy("owner_favorable")), 3, evaluate=False
        )
        standard = build_application(
            context.with_policy(Policy("aia_standard")), 3, evaluate=False
        )
        other = sample_context(3)
        standard_first = build_application(
            other.with_policy(Policy("aia_standard")), 3, evaluate=False
        )
        owner_second = build_application(
            other.with_policy(Policy("owner_favorable")), 3, evaluate=False
        )
        self.assertEqual(owner.summary.to_dict(), owner_second.summary.to_dict())
        self.assertEqual(standard.summary.to_dict(), standard_first.summary.to_dict())


if __name__ == "__main__":
    unittest.main()
