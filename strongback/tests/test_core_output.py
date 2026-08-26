"""Tables, text helpers and the trace that explains a run."""

import unittest

from strongback.core.ids import code_sort_key, next_sequence, normalise_code, slugify
from strongback.core.table import Column, Table, key_value_block, simple_table
from strongback.core.text import bullet_list, pad, plural, truncate, wrap
from strongback.core.trace import Trace, TraceEvent
from strongback.errors import InputError


class IdentifierTest(unittest.TestCase):
    """Codes normalise and sort the way a specification does."""

    def test_punctuation_is_stripped_from_codes(self):
        self.assertEqual(normalise_code(" 03-300 "), "03300")

    def test_sub_codes_survive_normalisation(self):
        self.assertEqual(normalise_code("03300.1"), "03300.1")

    def test_codes_sort_numerically_not_lexically(self):
        self.assertEqual(sorted(["10", "9", "9.1"], key=code_sort_key), ["9", "9.1", "10"])

    def test_an_empty_code_is_refused(self):
        self.assertRaises(InputError, normalise_code, "   ")

    def test_sequences_continue_from_the_highest(self):
        self.assertEqual(next_sequence(["CO-001", "CO-014"], prefix="CO-"), "CO-015")

    def test_slugs_are_filename_safe(self):
        self.assertEqual(slugify("Concrete -- Slab on Grade"), "concrete-slab-on-grade")


class TextTest(unittest.TestCase):
    """The text helpers never leave trailing whitespace in a report."""

    def test_padding_aligns_three_ways(self):
        self.assertEqual(pad("ab", 5), "ab   ")
        self.assertEqual(pad("ab", 5, "right"), "   ab")
        self.assertEqual(pad("ab", 5, "center"), " ab  ")

    def test_truncation_marks_the_cut(self):
        self.assertEqual(truncate("concrete slab on grade", 12), "concrete...")

    def test_wrapping_breaks_on_spaces(self):
        self.assertEqual(wrap("one two three four", 9), ["one two", "three", "four"])

    def test_plural_agrees_with_the_count(self):
        self.assertEqual(plural(1, "line"), "1 line")
        self.assertEqual(plural(2, "line"), "2 lines")

    def test_an_empty_bullet_list_says_so(self):
        self.assertEqual(bullet_list([]), "(none)")


class TableTest(unittest.TestCase):
    """Tables are deterministic and never trail whitespace."""

    def setUp(self):
        self.table = Table([Column("code", "Code"), Column("value", "Value", "right")])
        self.table.add({"code": "03300", "value": "1,000"})
        self.table.add({"code": "09900", "value": "250"})

    def test_columns_are_as_wide_as_their_content(self):
        rendered = self.table.render().splitlines()
        self.assertEqual(rendered[0], "Code   Value")
        self.assertEqual(rendered[2], "03300  1,000")

    def test_no_line_has_trailing_whitespace(self):
        for line in self.table.render().splitlines():
            self.assertEqual(line, line.rstrip())

    def test_rendering_twice_gives_the_same_bytes(self):
        self.assertEqual(self.table.render(), self.table.render())

    def test_a_separator_draws_a_rule(self):
        self.table.add_separator()
        self.table.add({"code": "", "value": "1,250"})
        self.assertIn("-----  -----\n       1,250", self.table.render())

    def test_simple_tables_take_tuples(self):
        self.assertEqual(simple_table(["a"], [(1,), (2,)]).splitlines()[2], "1")

    def test_key_value_blocks_align_on_the_separator(self):
        block = key_value_block([("Contract", "C-1"), ("Retainage", "10%")])
        self.assertEqual(block.splitlines()[0], "Contract   : C-1")

    def test_a_table_needs_a_column(self):
        self.assertRaises(InputError, Table, [])


class TraceTest(unittest.TestCase):
    """The trace records decisions in order and can be filtered."""

    def setUp(self):
        self.trace = Trace()
        self.trace.record("progress", "03300", "35% complete", {"kind": "lump_sum"})
        self.trace.record("retainage", "03300", "held at 10%")
        self.trace.record("progress", "01000", "50% complete")

    def test_events_keep_the_order_they_were_recorded_in(self):
        self.assertEqual([event.stage for event in self.trace], ["progress", "retainage", "progress"])

    def test_filtering_by_subject_keeps_order(self):
        self.assertEqual(
            [event.stage for event in self.trace.for_subject("03300")], ["progress", "retainage"]
        )

    def test_values_render_sorted_so_output_is_stable(self):
        event = TraceEvent("stage", "subject", "message", {"b": 2, "a": 1})
        self.assertEqual(event.render(), "stage subject: message (a=1, b=2)")

    def test_a_trace_round_trips_through_plain_data(self):
        rebuilt = Trace.from_list(self.trace.to_list())
        self.assertEqual(rebuilt.render(), self.trace.render())

    def test_a_disabled_trace_records_nothing(self):
        quiet = Trace(enabled=False)
        quiet.record("stage", "subject", "message")
        self.assertEqual(len(quiet), 0)

    def test_subjects_are_listed_in_first_seen_order(self):
        self.assertEqual(self.trace.subjects(), ["03300", "01000"])


if __name__ == "__main__":
    unittest.main()
