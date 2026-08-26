"""Policy: knobs, profiles, resolution and the options objects they build."""

import unittest

from strongback.errors import PolicyError
from strongback.policy.describe import differences_table, explain_knob, policy_report, policy_table
from strongback.policy.knobs import KNOBS, groups, knob, knob_names, validate_value
from strongback.policy.profile import (
    describe_profile,
    profile_differences,
    profile_names,
    profile_settings,
)
from strongback.policy.resolve import Policy, resolve
from tests.support import contract


class KnobTest(unittest.TestCase):
    """Every knob has allowed values, a default and a sentence."""

    def test_every_knob_documents_itself(self):
        for name in knob_names():
            self.assertTrue(KNOBS[name].doc, "%s has no documentation" % (name,))

    def test_every_choice_knob_defaults_to_an_allowed_value(self):
        for name in knob_names():
            definition = KNOBS[name]
            if definition.kind == "choice" and definition.values:
                self.assertIn(definition.default, definition.values)

    def test_an_unknown_knob_is_refused(self):
        self.assertRaises(PolicyError, knob, "vibes")

    def test_a_value_outside_the_allowed_set_is_refused(self):
        self.assertRaises(PolicyError, validate_value, "previous_basis", "vibes")

    def test_booleans_accept_the_words_people_type(self):
        self.assertTrue(validate_value("stored_allow_offsite", "yes"))
        self.assertFalse(validate_value("stored_allow_offsite", "no"))

    def test_numbers_are_coerced(self):
        self.assertEqual(validate_value("retainage_places", "3"), 3)

    def test_groups_partition_the_knobs(self):
        counted = sum(len(knob_names(group)) for group in groups())
        self.assertEqual(counted, len(knob_names()))


class ProfileTest(unittest.TestCase):
    """The profiles are named after who wrote the contract."""

    def test_every_profile_validates(self):
        for name in profile_names():
            self.assertTrue(profile_settings(name))

    def test_every_profile_explains_itself(self):
        for name in profile_names():
            self.assertTrue(describe_profile(name))

    def test_an_unknown_profile_is_refused(self):
        self.assertRaises(PolicyError, profile_settings, "generous")

    def test_the_two_sides_disagree_about_the_waiver_exchange(self):
        differences = profile_differences("owner_favorable", "subcontractor_favorable")
        self.assertEqual(differences["waiver_exchange"], ("before_payment", "after_payment"))

    def test_public_works_caps_retainage(self):
        self.assertTrue(profile_settings("public_works")["retainage_apply_cap"])


class PolicyTest(unittest.TestCase):
    """A policy remembers where each setting came from."""

    def test_defaults_are_marked_as_defaults(self):
        policy = Policy()
        self.assertEqual(policy.source("previous_basis"), "default")

    def test_a_profile_marks_its_settings(self):
        policy = Policy("owner_favorable")
        self.assertEqual(policy.source("waiver_exchange"), "profile")

    def test_an_override_wins_and_is_marked(self):
        policy = Policy("owner_favorable", {"stored_cap": "40%"})
        self.assertEqual(policy.get("stored_cap"), "40%")
        self.assertEqual(policy.source("stored_cap"), "override")

    def test_an_invalid_override_is_refused(self):
        self.assertRaises(PolicyError, Policy, None, {"previous_basis": "someday"})

    def test_overrides_are_listed_on_their_own(self):
        policy = Policy("public_works", {"line_places": 3})
        self.assertEqual(policy.overrides(), {"line_places": 3})

    def test_differences_between_policies_are_reported(self):
        differences = Policy("owner_favorable").differences(Policy("subcontractor_favorable"))
        self.assertEqual(differences["backcharge_stage"], ("gross", "net"))

    def test_the_progress_options_follow_the_policy(self):
        self.assertEqual(Policy("owner_favorable").progress_options().over_hundred, "error")

    def test_the_stored_options_follow_the_policy(self):
        self.assertEqual(Policy("lender_draw").stored_options().conversion, "on_completion")

    def test_the_retainage_options_follow_the_policy(self):
        options = Policy(None, {"retainage_round_stage": "summary"}).retainage_options()
        self.assertEqual(options.round_stage, "summary")

    def test_the_waiver_requirement_follows_the_policy(self):
        self.assertEqual(Policy("owner_favorable").waiver_requirement().exchange, "before_payment")

    def test_a_policy_round_trips_through_plain_data(self):
        policy = Policy("public_works", {"stored_cap": "60%"})
        rebuilt = Policy.from_dict(policy.to_dict())
        self.assertEqual(rebuilt.get("stored_cap"), "60%")

    def test_resolution_takes_the_contract_threshold(self):
        deal = contract()
        deal.billable_threshold = "approved"
        policy = resolve("aia_standard", None, deal)
        self.assertEqual(policy.get("change_order_threshold"), "approved")

    def test_an_explicit_override_beats_the_contract(self):
        deal = contract()
        deal.billable_threshold = "approved"
        policy = resolve("aia_standard", {"change_order_threshold": "proposed"}, deal)
        self.assertEqual(policy.get("change_order_threshold"), "proposed")


class DescribeTest(unittest.TestCase):
    """The rendering is for reading against a contract."""

    def test_the_table_lists_settings_with_their_source(self):
        rendered = policy_table(Policy("owner_favorable"), group="stored")
        self.assertIn("stored_conversion", rendered)
        self.assertIn("profile", rendered)

    def test_the_report_groups_the_settings(self):
        rendered = policy_report(Policy("public_works"), changed_only=True)
        self.assertIn("Retainage", rendered)

    def test_a_knob_explains_itself(self):
        rendered = explain_knob("previous_basis")
        self.assertIn("allowed: certified, paid", rendered)

    def test_the_difference_table_shows_both_sides(self):
        rendered = differences_table(Policy("aia_standard"), Policy("lender_draw"))
        self.assertIn("stored_conversion", rendered)

    def test_rendering_leaves_no_trailing_whitespace(self):
        for line in policy_report(Policy("owner_favorable")).splitlines():
            self.assertEqual(line, line.rstrip())


if __name__ == "__main__":
    unittest.main()
