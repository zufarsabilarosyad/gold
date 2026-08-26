"""Writing a run out again, in the format the loader reads.

Two rules hold here.  Money is written as a decimal string, never a float, so
nothing is lost on the way out.  And keys are written in a fixed order, so two
dumps of the same run are byte-identical and a diff of two exports shows what
actually changed rather than what happened to hash differently.
"""

import json

from ..errors import InputError

__all__ = ["dump_context", "dump_json", "dump_result", "write_json_file"]


def dump_context(context):
    """Return a run context as plain data.

    >>> from .samples import sample_context
    >>> document = dump_context(sample_context(2))
    >>> sorted(document)[:4]
    ['applications', 'backcharges', 'contract', 'costs']
    >>> document["contract"]["id"]
    'C-2024-118'
    """
    document = {
        "contract": context.contract.to_dict(),
        "periods": context.periods.to_list(),
        "policy": context.policy.to_dict(only_overrides=True),
        "progress": context.progress.to_list(),
        "stored": context.stored.to_list(),
        "costs": context.costs.to_list(),
        "backcharges": context.backcharges.to_list(),
        "offsets": context.offsets.to_list(),
        "waivers": context.waivers.to_list(),
        "applications": context.applications.to_list(),
        "revisions": context.revisions.to_list(),
    }
    if context.punchlist_value is not None:
        document["punchlist_value"] = str(context.punchlist_value.amount)
    return document


def dump_json(context, indent=2):
    """Return a run context as JSON text, with sorted keys.

    >>> from .samples import sample_context
    >>> text = dump_json(sample_context(1))
    >>> text.splitlines()[0]
    '{'
    >>> '"id": "C-2024-118"' in text
    True
    """
    return json.dumps(dump_context(context), indent=indent, sort_keys=True)


def dump_result(result, with_trace=True, indent=2):
    """Return a run result as JSON text.

    >>> from ..engine.run import build_application
    >>> from .samples import sample_context
    >>> result = build_application(sample_context(2), 1, evaluate=False)
    >>> '"number": 1' in dump_result(result)
    True
    """
    return json.dumps(result.to_dict(with_trace), indent=indent, sort_keys=True)


def write_json_file(path, context, indent=2):
    """Write a run context to a JSON file."""
    with open(path, "w") as handle:
        handle.write(dump_json(context, indent))
        handle.write("\n")
