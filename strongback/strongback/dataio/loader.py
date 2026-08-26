"""Building a run context from plain data.

The document format is the objects' own ``to_dict`` output, so a run can be
dumped, edited by hand and loaded back.  That round trip is a test in this
repository rather than an aspiration: a context that does not survive it is a
context whose export is lying about something.
"""

import json

from ..billing.application import ApplicationRegister
from ..billing.revision import RevisionChain
from ..core.money import money
from ..core.period import PeriodSchedule
from ..deductions.backcharge import BackChargeRegister
from ..deductions.offset import OffsetRegister
from ..deductions.tax import TaxRule
from ..engine.context import RunContext
from ..errors import DataError
from ..model.contract import Contract
from ..policy.resolve import Policy
from ..progress.costtocost import CostLedger
from ..progress.observation import ProgressLedger
from ..progress.stored import StoredLedger
from ..waivers.ledger import WaiverLedger
from .schema import check_document, raise_for_problems

__all__ = ["load_context", "load_json", "read_json_file"]


def load_context(document):
    """Build a :class:`~strongback.engine.context.RunContext` from plain data.

    >>> from .dump import dump_context
    >>> from .samples import sample_context
    >>> document = dump_context(sample_context(2))
    >>> context = load_context(document)
    >>> context.contract.id
    'C-2024-118'
    >>> len(context.periods)
    2
    >>> str(context.contract.original_sum())
    '$2,450,000.00'
    """
    raise_for_problems(check_document(document), "run document")
    contract = Contract.from_dict(document["contract"])
    currency = contract.currency
    periods = PeriodSchedule.from_list(document["periods"])
    policy_data = document.get("policy")
    policy = Policy.from_dict(policy_data) if policy_data else Policy()
    tax = document.get("tax_rule")
    punchlist = document.get("punchlist_value")
    return RunContext(
        contract,
        periods,
        policy,
        ProgressLedger.from_list(document.get("progress", ()), currency),
        StoredLedger.from_list(document.get("stored", ()), currency),
        CostLedger.from_list(document.get("costs", ()), currency),
        BackChargeRegister.from_list(document.get("backcharges", ()), currency),
        OffsetRegister.from_list(document.get("offsets", ()), currency),
        TaxRule.from_dict(tax) if tax else None,
        WaiverLedger.from_list(document.get("waivers", ()), currency),
        None,
        None,
        None,
        None,
        ApplicationRegister.from_list(document.get("applications", ()), currency),
        RevisionChain.from_list(document.get("revisions", ())),
        None,
        money(punchlist, currency) if punchlist else None,
    )


def load_json(text):
    """Load a context from JSON text.

    >>> from .dump import dump_json
    >>> from .samples import sample_context
    >>> context = load_json(dump_json(sample_context(1)))
    >>> len(context.periods)
    1
    """
    try:
        document = json.loads(text)
    except ValueError as error:
        raise DataError("the run document is not valid JSON: %s" % (error,))
    return load_context(document)


def read_json_file(path):
    """Load a context from a JSON file on disk."""
    with open(path, "r") as handle:
        return load_json(handle.read())
