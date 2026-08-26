"""Payment gates: the reasons a cheque does not go out even though it is owed.

A gate is not a deduction.  A back-charge reduces what is owed; a gate holds
what is owed until a document arrives.  Conflating the two produces the worst
kind of error, where a payment is reduced permanently for a condition that was
cured the next week.

Gates here are advisory objects with reasons attached, because the useful
output is not "blocked" but "blocked, and here is the list to send the
subcontractor".
"""

from ..core.dates import format_date, parse_date
from ..errors import GateError, InputError

__all__ = ["GateResult", "evaluate_gates", "GATE_NAMES"]

GATE_NAMES = ("waivers", "insurance", "notices", "closeout", "schedule")


class GateResult:
    """Whether a payment may go out, and why not.

    >>> result = GateResult()
    >>> result.ok()
    True
    >>> result.block("insurance", "no general liability in force on 2024-11-30")
    >>> result.ok()
    False
    >>> result.reasons()
    ['insurance: no general liability in force on 2024-11-30']
    """

    __slots__ = ("blocks", "warnings")

    def __init__(self):
        self.blocks = []
        self.warnings = []

    def block(self, gate, reason):
        """Record a blocking condition."""
        if str(gate) not in GATE_NAMES:
            raise InputError("unknown gate %r; known: %s" % (gate, ", ".join(GATE_NAMES)))
        self.blocks.append((str(gate), str(reason)))

    def warn(self, gate, reason):
        """Record a condition worth reporting that does not block payment."""
        if str(gate) not in GATE_NAMES:
            raise InputError("unknown gate %r" % (gate,))
        self.warnings.append((str(gate), str(reason)))

    def ok(self):
        """Return True when nothing blocks the payment."""
        return not self.blocks

    def reasons(self):
        """Return the blocking reasons as text, in the order they were found."""
        return ["%s: %s" % (gate, reason) for gate, reason in self.blocks]

    def warning_text(self):
        """Return the non-blocking notes as text."""
        return ["%s: %s" % (gate, reason) for gate, reason in self.warnings]

    def raise_if_blocked(self):
        """Raise :class:`~strongback.errors.GateError` when blocked."""
        if not self.ok():
            raise GateError("; ".join(self.reasons()))

    def to_dict(self):
        """Return the result as plain data."""
        return {
            "ok": self.ok(),
            "blocks": [{"gate": gate, "reason": reason} for gate, reason in self.blocks],
            "warnings": [{"gate": gate, "reason": reason} for gate, reason in self.warnings],
        }

    def __bool__(self):
        return self.ok()

    def __len__(self):
        return len(self.blocks)

    def __repr__(self):
        return "GateResult(%s, %d blocks)" % ("ok" if self.ok() else "blocked", len(self.blocks))


def evaluate_gates(
    application,
    requirement=None,
    waivers=None,
    insurance=None,
    insurance_requirements=None,
    notices=None,
    notice_events=None,
    as_of=None,
    previous_application_id=None,
    paid_applications=(),
):
    """Return the gate result for one application.

    >>> from ..core.money import money
    >>> from ..core.period import BillingPeriod
    >>> from ..billing.application import PayApplication
    >>> from ..billing.summary import ApplicationSummary
    >>> from ..waivers.document import LienWaiver
    >>> from ..waivers.ledger import WaiverLedger
    >>> from ..waivers.requirement import WaiverRequirement
    >>> period = BillingPeriod(3, "2024-11-01", "2024-11-30")
    >>> summary = ApplicationSummary(money("500000"),
    ...     completed_and_stored=money("175000"), retainage_work=money("17500"))
    >>> application = PayApplication("PA-003", 3, period, summary=summary)
    >>> ledger = WaiverLedger()
    >>> result = evaluate_gates(application, WaiverRequirement(), ledger)
    >>> result.ok()
    False
    >>> result.reasons()
    ['waivers: no conditional_progress waiver on file for PA-003']

    >>> ledger.add(LienWaiver("W-3", "conditional_progress", money("67500"),
    ...                       "2024-11-30", "2024-12-02", "PA-003"))
    >>> evaluate_gates(application, WaiverRequirement(), ledger).ok()
    True
    """
    result = GateResult()
    as_of = parse_date(as_of) if as_of else application.period.end
    if requirement is not None and requirement.gates_payment():
        if waivers is None:
            raise InputError("a waiver requirement needs a waiver ledger to check")
        expected = requirement.type_for_current()
        candidates = [
            waiver
            for waiver in waivers.for_application(application.id)
            if waiver.type == expected
        ]
        if not candidates:
            result.block(
                "waivers", "no %s waiver on file for %s" % (expected, application.id)
            )
        else:
            from ..waivers.requirement import required_through

            needed = required_through(requirement, application.period)
            for waiver in candidates:
                problems = requirement.accepts(waiver, expected)
                for problem in problems:
                    result.block("waivers", problem)
                if not waiver.covers_through(needed):
                    result.block(
                        "waivers",
                        "waiver %s covers through %s but %s is required"
                        % (waiver.id, format_date(waiver.through), format_date(needed)),
                    )
        if previous_application_id is not None and not waivers.has_unconditional(
            previous_application_id
        ):
            result.block(
                "waivers",
                "no unconditional waiver on file for %s" % (previous_application_id,),
            )
    if insurance is not None and insurance_requirements:
        for problem in insurance.check(as_of, insurance_requirements):
            result.block("insurance", problem)
    if notices is not None and notice_events:
        for kind in notices.missing(notice_events):
            result.warn("notices", "no timely %s notice" % (kind,))
    return result
