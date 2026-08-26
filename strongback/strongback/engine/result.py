"""What a run produces: the application, the trace, and what blocked it.

A result is not just the document.  Two runs of the same job under different
policies produce two documents *and* two traces, and the traces are what make
the difference explainable rather than merely visible.
"""

from ..core.table import key_value_block
from ..core.text import join_lines, underline
from ..errors import DataError

__all__ = ["RunResult"]


class RunResult:
    """One period's application, with everything that explains it.

    >>> from ..core.money import money
    >>> from ..core.period import BillingPeriod
    >>> from ..billing.application import PayApplication
    >>> from ..billing.summary import ApplicationSummary
    >>> period = BillingPeriod(1, "2024-09-01", "2024-09-30")
    >>> summary = ApplicationSummary(money("100000"),
    ...     completed_and_stored=money("25000"), retainage_work=money("2500"))
    >>> application = PayApplication("PA-001", 1, period, summary=summary)
    >>> result = RunResult(application)
    >>> result.is_clean()
    True
    >>> str(result.payment_due())
    '$22,500.00'
    """

    __slots__ = ("application", "gates", "diagnostics", "series", "accrued", "deductions")

    def __init__(self, application, gates=None, diagnostics=(), series=None, accrued=None, deductions=None):
        self.application = application
        self.gates = gates
        self.diagnostics = list(diagnostics)
        self.series = series or {}
        self.accrued = accrued or {}
        self.deductions = deductions or {}

    @property
    def sheet(self):
        """Return the continuation sheet."""
        return self.application.sheet

    @property
    def summary(self):
        """Return the summary page."""
        if self.application.summary is None:
            raise DataError("application %s has no summary" % (self.application.id,))
        return self.application.summary

    @property
    def trace(self):
        """Return the trace of the run."""
        return self.application.trace

    def payment_due(self):
        """Return the payment this application asks for."""
        return self.application.requested_amount()

    def is_clean(self):
        """Return True when nothing blocks and nothing is inconsistent."""
        if self.diagnostics:
            return False
        if self.gates is not None and not self.gates.ok():
            return False
        return True

    def blocking_reasons(self):
        """Return the reasons the payment is held, if any."""
        if self.gates is None:
            return []
        return self.gates.reasons()

    def line_retainage(self, code):
        """Return the retainage accrual steps for one line."""
        return list(self.accrued.get(str(code), ()))

    def render(self, with_sheet=True, with_trace=False):
        """Return the application as text."""
        blocks = [
            underline(
                "%s -- %s" % (self.application.id, self.application.period.label), "="
            ),
            self.summary.render(),
        ]
        if with_sheet and len(self.sheet):
            blocks.append(underline("Continuation sheet", "-") + "\n" + self.sheet.as_table())
        if self.deductions:
            blocks.append(
                underline("Deductions", "-")
                + "\n"
                + key_value_block(
                    [
                        (name.replace("_", " ").capitalize(), amount.format())
                        for name, amount in sorted(self.deductions.items())
                    ],
                    width=12,
                )
            )
        if self.diagnostics:
            blocks.append(
                underline("Diagnostics", "-")
                + "\n"
                + "\n".join("- %s" % (item,) for item in self.diagnostics)
            )
        if self.gates is not None and not self.gates.ok():
            blocks.append(
                underline("Payment held", "-")
                + "\n"
                + "\n".join("- %s" % (item,) for item in self.gates.reasons())
            )
        if with_trace and len(self.trace):
            blocks.append(underline("Trace", "-") + "\n" + self.trace.render())
        return join_lines(*blocks)

    def to_dict(self, with_trace=True):
        """Return the result as plain data."""
        data = self.application.to_dict()
        if not with_trace:
            data.pop("trace", None)
        data["diagnostics"] = list(self.diagnostics)
        data["gates"] = self.gates.to_dict() if self.gates is not None else None
        data["deductions"] = {
            name: str(amount.amount) for name, amount in sorted(self.deductions.items())
        }
        return data

    def __str__(self):
        return "%s: %s" % (self.application.id, self.payment_due())

    def __repr__(self):
        return "RunResult(%r, clean=%s)" % (self.application.id, self.is_clean())
