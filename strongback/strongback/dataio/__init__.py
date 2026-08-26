"""Reading and writing runs, in JSON for machines and CSV for spreadsheets.

The JSON format is the objects' own serialisation, so a dump-load round trip is
lossless and testable.  The CSV readers are narrow on purpose: they take the
columns they know and name the row when something is wrong.
"""

from .csvio import read_progress_csv, read_schedule_csv, write_continuation_csv, write_schedule_csv
from .dump import dump_context, dump_json, dump_result, write_json_file
from .loader import load_context, load_json, read_json_file
from .samples import sample_context, sample_contract, sample_progress, sample_stored
from .schema import check_document, raise_for_problems

__all__ = [
    "read_progress_csv",
    "read_schedule_csv",
    "write_continuation_csv",
    "write_schedule_csv",
    "dump_context",
    "dump_json",
    "dump_result",
    "write_json_file",
    "load_context",
    "load_json",
    "read_json_file",
    "sample_context",
    "sample_contract",
    "sample_progress",
    "sample_stored",
    "check_document",
    "raise_for_problems",
]
