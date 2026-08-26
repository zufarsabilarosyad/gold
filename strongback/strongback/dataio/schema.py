"""Checking a document before it becomes objects.

Loading a badly-shaped file and letting the constructors raise gives an error
about a missing key thirty frames down.  Checking first gives an error about
*the file*, with the path to the offending entry in it, which is the difference
between a usable tool and an annoying one.

The checks here are structural only -- present, right type, right shape.
Whether a schedule of values adds up to the contract sum is a question for
:meth:`~strongback.model.contract.Contract.validate`, not for a loader.
"""

from ..errors import DataError, InputError

__all__ = ["require", "expect_list", "expect_mapping", "check_document", "DOCUMENT_KEYS"]

DOCUMENT_KEYS = (
    "contract",
    "periods",
    "policy",
    "progress",
    "stored",
    "costs",
    "backcharges",
    "offsets",
    "waivers",
    "applications",
    "revisions",
    "punchlist_value",
    "tax_rule",
)


def require(mapping, key, where="document"):
    """Return a required key, raising a message that names where it was missing.

    >>> require({"id": "C-1"}, "id")
    'C-1'
    >>> require({}, "id", "contract")
    Traceback (most recent call last):
        ...
    strongback.errors.DataError: contract is missing 'id'
    """
    if not isinstance(mapping, dict):
        raise DataError("%s should be a mapping, got %s" % (where, type(mapping).__name__))
    if key not in mapping:
        raise DataError("%s is missing %r" % (where, key))
    return mapping[key]


def expect_list(value, where="document"):
    """Return the value as a list, raising when it is not a sequence.

    >>> expect_list([1, 2], "periods")
    [1, 2]
    >>> expect_list({}, "periods")
    Traceback (most recent call last):
        ...
    strongback.errors.DataError: periods should be a list, got dict
    """
    if isinstance(value, (list, tuple)):
        return list(value)
    raise DataError("%s should be a list, got %s" % (where, type(value).__name__))


def expect_mapping(value, where="document"):
    """Return the value as a dict, raising when it is not a mapping.

    >>> expect_mapping({"a": 1}, "policy")
    {'a': 1}
    """
    if isinstance(value, dict):
        return dict(value)
    raise DataError("%s should be a mapping, got %s" % (where, type(value).__name__))


def check_document(document):
    """Return the problems with a run document, empty when it is loadable.

    >>> check_document({"contract": {}, "periods": []})
    ['document has no billing periods']
    >>> check_document({"periods": [{}]})
    ["document is missing 'contract'"]
    >>> check_document({"contract": {}, "periods": [{}], "progress": {}})
    ['progress should be a list, got dict']
    """
    problems = []
    if not isinstance(document, dict):
        return ["a run document should be a mapping"]
    if "contract" not in document:
        problems.append("document is missing 'contract'")
    if "periods" not in document:
        problems.append("document is missing 'periods'")
    elif not isinstance(document["periods"], (list, tuple)):
        problems.append("periods should be a list, got %s" % (type(document["periods"]).__name__,))
    elif not document["periods"]:
        problems.append("document has no billing periods")
    for key in ("progress", "stored", "costs", "backcharges", "offsets", "waivers", "applications", "revisions"):
        if key in document and not isinstance(document[key], (list, tuple)):
            problems.append("%s should be a list, got %s" % (key, type(document[key]).__name__))
    if "policy" in document and not isinstance(document["policy"], dict):
        problems.append("policy should be a mapping, got %s" % (type(document["policy"]).__name__,))
    for key in sorted(document):
        if key not in DOCUMENT_KEYS:
            problems.append("unknown top-level key %r" % (key,))
    return problems


def raise_for_problems(problems, what="document"):
    """Raise a single error listing every problem found.

    >>> raise_for_problems([], "document")
    >>> raise_for_problems(["a", "b"], "document")
    Traceback (most recent call last):
        ...
    strongback.errors.DataError: document has 2 problems: a; b
    """
    if not problems:
        return
    raise DataError(
        "%s has %d problem%s: %s"
        % (what, len(problems), "" if len(problems) == 1 else "s", "; ".join(problems))
    )
