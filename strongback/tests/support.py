"""Fixtures shared by the tests.

The builders here are deliberately small and explicit.  Where a test needs a
whole job it uses :func:`strongback.dataio.samples.sample_context`; where it
needs one line and one rule it builds exactly that, so the assertion is about
the rule and not about the fixture.
"""

from strongback.core.money import money
from strongback.core.period import monthly_schedule
from strongback.engine.context import RunContext
from strongback.model.contract import Contract
from strongback.model.parties import Party
from strongback.model.sov import ScheduleOfValues, SOVLine
from strongback.progress.observation import ProgressEntry, ProgressLedger
from strongback.retainage.terms import RetainageTerms

OWNER = Party("OWN", "Harbor Point Holdings", "owner")
BUILDER = Party("GC", "Keel & Sons", "contractor")
SUB = Party("SUB", "Tidewater Concrete", "subcontractor")


def line(code="03300", value="400000", **kwargs):
    """Build one schedule-of-values line."""
    description = kwargs.pop("description", "Concrete")
    return SOVLine(code, description, money(value), **kwargs)


def schedule(*lines):
    """Build a schedule of values from lines, defaulting to a single one."""
    return ScheduleOfValues(list(lines) or [line()])


def contract(sov=None, retainage=None, **kwargs):
    """Build a contract between the standard owner and builder."""
    return Contract(
        kwargs.pop("identifier", "C-1"),
        kwargs.pop("payer", OWNER),
        kwargs.pop("payee", BUILDER),
        sov if sov is not None else schedule(),
        retainage if retainage is not None else RetainageTerms("10%"),
        **kwargs
    )


def progress(*entries):
    """Build a progress ledger from ``(code, period, percent)`` triples."""
    ledger = ProgressLedger()
    for code, period, percent in entries:
        ledger.record(ProgressEntry(code, period, percent=percent))
    return ledger


def context(sov=None, retainage=None, periods=3, ledger=None, **kwargs):
    """Build a run context around a contract and a progress ledger."""
    return RunContext(
        contract(sov, retainage),
        monthly_schedule("2024-09-01", periods),
        progress=ledger,
        **kwargs
    )
