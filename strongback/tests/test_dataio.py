"""Loading, dumping and the CSV doors."""

import json
import os
import tempfile
import unittest

from strongback.core.money import money
from strongback.dataio.csvio import (
    read_progress_csv,
    read_schedule_csv,
    write_continuation_csv,
    write_schedule_csv,
)
from strongback.dataio.dump import dump_context, dump_json, dump_result, write_json_file
from strongback.dataio.loader import load_context, load_json, read_json_file
from strongback.dataio.samples import sample_context, sample_contract
from strongback.dataio.schema import check_document, raise_for_problems, require
from strongback.engine.run import build_application, run_contract
from strongback.errors import DataError


class SchemaTest(unittest.TestCase):
    """Structural checks name the document, not a frame thirty deep."""

    def test_a_missing_key_names_where_it_was_missing(self):
        try:
            require({}, "id", "contract")
        except DataError as error:
            self.assertEqual(str(error), "contract is missing 'id'")

    def test_a_document_without_a_contract_is_reported(self):
        self.assertEqual(check_document({"periods": [{}]}), ["document is missing 'contract'"])

    def test_a_document_with_no_periods_is_reported(self):
        self.assertEqual(check_document({"contract": {}, "periods": []}), ["document has no billing periods"])

    def test_a_ledger_of_the_wrong_shape_is_reported(self):
        problems = check_document({"contract": {}, "periods": [{}], "progress": {}})
        self.assertEqual(problems, ["progress should be a list, got dict"])

    def test_an_unknown_key_is_reported(self):
        problems = check_document({"contract": {}, "periods": [{}], "vibes": []})
        self.assertIn("unknown top-level key 'vibes'", problems)

    def test_problems_are_raised_together(self):
        self.assertRaises(DataError, raise_for_problems, ["a", "b"])


class RoundTripTest(unittest.TestCase):
    """A run survives being written out and read back."""

    def setUp(self):
        self.context = sample_context(3)

    def test_the_document_carries_every_ledger(self):
        document = dump_context(self.context)
        for key in ("contract", "periods", "progress", "stored", "costs", "waivers"):
            self.assertIn(key, document)

    def test_a_context_round_trips(self):
        rebuilt = load_context(dump_context(self.context))
        self.assertEqual(rebuilt.contract.id, self.context.contract.id)
        self.assertEqual(len(rebuilt.periods), len(self.context.periods))
        self.assertEqual(rebuilt.contract.original_sum(), self.context.contract.original_sum())

    def test_the_run_is_identical_after_a_round_trip(self):
        original = build_application(self.context, 3, evaluate=False)
        rebuilt = build_application(load_context(dump_context(self.context)), 3, evaluate=False)
        self.assertEqual(original.summary.to_dict(), rebuilt.summary.to_dict())

    def test_json_is_sorted_so_two_dumps_diff_cleanly(self):
        first = dump_json(self.context)
        second = dump_json(load_json(first))
        self.assertEqual(first, second)

    def test_json_carries_no_floats(self):
        document = json.loads(dump_json(self.context))

        def walk(value):
            if isinstance(value, float):
                raise AssertionError("a float reached the document")
            if isinstance(value, dict):
                for item in value.values():
                    walk(item)
            if isinstance(value, list):
                for item in value:
                    walk(item)

        walk(document)

    def test_a_run_can_be_written_to_a_file_and_read_back(self):
        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        try:
            write_json_file(path, self.context)
            rebuilt = read_json_file(path)
            self.assertEqual(rebuilt.contract.id, self.context.contract.id)
        finally:
            os.unlink(path)

    def test_a_result_dumps_with_or_without_its_trace(self):
        result = build_application(self.context, 2, evaluate=False)
        self.assertIn("trace", json.loads(dump_result(result)))
        self.assertNotIn("trace", json.loads(dump_result(result, with_trace=False)))

    def test_bad_json_is_a_data_error(self):
        self.assertRaises(DataError, load_json, "{not json")


class CsvTest(unittest.TestCase):
    """The spreadsheet doors are narrow and name the offending row."""

    def test_a_schedule_reads_from_csv(self):
        text = "code,description,scheduled_value,kind\n01000,General,180000,lump_sum\n"
        schedule = read_schedule_csv(text)
        self.assertEqual(schedule.total(), money("180000"))

    def test_a_missing_column_is_refused(self):
        self.assertRaises(DataError, read_schedule_csv, "code,description\n01000,General\n")

    def test_a_bad_row_names_its_line_number(self):
        text = "code,description,scheduled_value\n01000,General,eleven\n"
        try:
            read_schedule_csv(text)
        except DataError as error:
            self.assertIn("row 2", str(error))

    def test_a_schedule_round_trips_through_csv(self):
        original = sample_contract().schedule
        rebuilt = read_schedule_csv(write_schedule_csv(original))
        self.assertEqual(rebuilt.total(), original.total())
        self.assertEqual(rebuilt.codes(), original.codes())

    def test_progress_reads_from_csv(self):
        ledger = read_progress_csv("code,period,percent\n01000,1,12%\n")
        self.assertEqual(str(ledger.latest_percent("01000", 1)), "12%")

    def test_a_row_reporting_two_shapes_is_refused(self):
        text = "code,period,percent,value\n01000,1,12%,1000\n"
        self.assertRaises(DataError, read_progress_csv, text)

    def test_a_continuation_sheet_writes_to_csv(self):
        result = build_application(sample_context(2), 2, evaluate=False)
        rows = write_continuation_csv(result.sheet).strip().splitlines()
        self.assertEqual(rows[0].split(",")[0], "code")
        self.assertEqual(len(rows) - 1, len(result.sheet))


class SampleTest(unittest.TestCase):
    """The sample is a constant, and it exercises the awkward parts."""

    def test_the_sample_is_the_same_every_time(self):
        first = dump_json(sample_context(3))
        second = dump_json(sample_context(3))
        self.assertEqual(first, second)

    def test_the_sample_has_a_step_down_and_a_directive(self):
        contract = sample_contract()
        self.assertEqual(len(contract.retainage.stepdowns), 1)
        statuses = sorted(str(order.status) for order in contract.change_orders)
        self.assertEqual(statuses, ["directed", "executed", "executed"])

    def test_the_sample_runs_clean_apart_from_the_unit_price_overrun(self):
        results = run_contract(sample_context(2))
        self.assertEqual(results[0].diagnostics, [])
        self.assertEqual(results[1].diagnostics, [])


if __name__ == "__main__":
    unittest.main()
