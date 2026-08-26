"""Retainage terms: the clause, as data.

Retainage is the part of earned value the payer keeps until the payee finishes.
Every contract states it in a sentence or two, and those sentences hide at
least six independent decisions:

* the rate, and whether change-order work carries a different one;
* whether stored materials are retained or paid in full;
* what the rate applies to -- work in this period, or work to date;
* whether the rate steps down at a completion threshold, and if so whether the
  step-down applies only to later work or is applied back over everything
  already retained;
* whether a ceiling applies, expressed against the contract sum;
* what is released at substantial completion, and what is held to the end.

The one that surprises people is the fourth.  "Retainage shall be reduced to
five percent at fifty percent completion" is read by owners as *future work is
retained at five* and by contractors as *total retainage becomes five percent
of everything*, and on a fifty-million-dollar job the difference is a cheque
for one and a quarter million.  Both readings are implemented here; neither is
the default, because the default is whatever the contract says and
:class:`RetainageTerms` is where you say it.
"""

from decimal import Decimal

from ..core.money import Money, money
from ..core.percent import Rate, rate_text
from ..errors import DataError, InputError

__all__ = [
    "Stepdown",
    "RetainageTerms",
    "STEPDOWN_MODES",
    "RETAINAGE_BASES",
    "CAP_BASES",
    "standard_terms",
]

STEPDOWN_MODES = ("prospective", "retroactive")
RETAINAGE_BASES = ("work_and_stored", "work_only", "work_less_change_orders")
CAP_BASES = ("contract_sum", "work_completed", "none")


class Stepdown:
    """A reduction of the retainage rate once completion passes a threshold.

    >>> step = Stepdown("50%", "5%")
    >>> step.applies_at("0.6")
    True
    >>> step.applies_at("0.4")
    False
    """

    __slots__ = ("threshold", "rate", "mode", "requires_certification", "note")

    def __init__(self, threshold, rate, mode=None, requires_certification=False, note=""):
        self.threshold = Rate.parse(threshold)
        self.rate = Rate.parse(rate)
        if mode is not None and str(mode) not in STEPDOWN_MODES:
            raise InputError(
                "unknown step-down mode %r; known: %s" % (mode, ", ".join(STEPDOWN_MODES))
            )
        self.mode = str(mode) if mode is not None else None
        self.requires_certification = bool(requires_certification)
        self.note = str(note)

    def applies_at(self, completion):
        """Return True when a completion fraction has reached the threshold."""
        if isinstance(completion, Rate):
            value = completion.value
        else:
            value = Rate.parse(completion).value if not isinstance(completion, Decimal) else completion
        return value >= self.threshold.value

    def to_dict(self):
        """Return the step-down as plain data."""
        return {
            "threshold": rate_text(self.threshold),
            "rate": rate_text(self.rate),
            "mode": self.mode,
            "requires_certification": self.requires_certification,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild a step-down from :meth:`to_dict` output."""
        return cls(
            data["threshold"],
            data["rate"],
            data.get("mode"),
            data.get("requires_certification", False),
            data.get("note", ""),
        )

    def __eq__(self, other):
        return (
            isinstance(other, Stepdown)
            and other.threshold == self.threshold
            and other.rate == self.rate
            and other.mode == self.mode
        )

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("Stepdown", self.threshold.value, self.rate.value, self.mode))

    def __str__(self):
        return "at %s completion, %s" % (self.threshold, self.rate)

    def __repr__(self):
        return "Stepdown(%r, %r)" % (str(self.threshold), str(self.rate))


class RetainageTerms:
    """The retainage clause of one contract.

    >>> terms = standard_terms()
    >>> str(terms.base_rate)
    '10%'
    >>> str(terms.rate_for_completion("0.60"))
    '10%'
    >>> stepped = RetainageTerms("10%", stepdowns=[Stepdown("50%", "5%")])
    >>> str(stepped.rate_for_completion("0.60"))
    '5%'
    """

    __slots__ = (
        "base_rate",
        "change_order_rate",
        "stored_materials_retained",
        "basis",
        "stepdowns",
        "stepdown_mode",
        "cap_rate",
        "cap_basis",
        "release_at_substantial",
        "punchlist_multiple",
        "final_release_days",
        "note",
    )

    def __init__(
        self,
        base_rate="10%",
        change_order_rate=None,
        stored_materials_retained=True,
        basis="work_and_stored",
        stepdowns=(),
        stepdown_mode="prospective",
        cap_rate=None,
        cap_basis="contract_sum",
        release_at_substantial=None,
        punchlist_multiple=None,
        final_release_days=30,
        note="",
    ):
        self.base_rate = Rate.parse(base_rate)
        self.change_order_rate = (
            Rate.parse(change_order_rate) if change_order_rate is not None else None
        )
        self.stored_materials_retained = bool(stored_materials_retained)
        if str(basis) not in RETAINAGE_BASES:
            raise InputError(
                "unknown retainage basis %r; known: %s" % (basis, ", ".join(RETAINAGE_BASES))
            )
        self.basis = str(basis)
        self.stepdowns = tuple(
            sorted(stepdowns, key=lambda step: step.threshold.value)
        )
        if str(stepdown_mode) not in STEPDOWN_MODES:
            raise InputError("unknown step-down mode %r" % (stepdown_mode,))
        self.stepdown_mode = str(stepdown_mode)
        self.cap_rate = Rate.parse(cap_rate) if cap_rate is not None else None
        if str(cap_basis) not in CAP_BASES:
            raise InputError("unknown cap basis %r" % (cap_basis,))
        self.cap_basis = str(cap_basis)
        if self.cap_rate is None and self.cap_basis != "none":
            self.cap_basis = "none" if self.cap_rate is None else self.cap_basis
        self.release_at_substantial = (
            Rate.parse(release_at_substantial) if release_at_substantial is not None else None
        )
        self.punchlist_multiple = (
            Rate.parse(punchlist_multiple)
            if isinstance(punchlist_multiple, (Rate,))
            else (Decimal(str(punchlist_multiple)) if punchlist_multiple is not None else None)
        )
        self.final_release_days = int(final_release_days)
        self.note = str(note)
        for step in self.stepdowns:
            if step.rate.value > self.base_rate.value:
                raise DataError(
                    "step-down to %s is above the base rate %s" % (step.rate, self.base_rate)
                )

    def rate_for_line(self, line, completion=None):
        """Return the rate applying to a schedule line at a completion level.

        A line's own rate wins; otherwise a change-order line takes the change
        order rate if the contract sets one; otherwise the completion-adjusted
        base rate applies.
        """
        if getattr(line, "retainage_rate", None) is not None:
            return line.retainage_rate
        if getattr(line, "is_change_order", None) is not None and line.is_change_order():
            if self.change_order_rate is not None:
                return self.change_order_rate
        return self.rate_for_completion(completion)

    def rate_for_completion(self, completion=None):
        """Return the base rate after any step-down that has been reached."""
        rate = self.base_rate
        if completion is None:
            return rate
        for step in self.stepdowns:
            if step.applies_at(completion):
                rate = step.rate
        return rate

    def stepdown_reached(self, completion):
        """Return the deepest step-down reached, or ``None``."""
        reached = None
        for step in self.stepdowns:
            if step.applies_at(completion):
                reached = step
        return reached

    def mode_for(self, step):
        """Return the step-down mode, preferring the step's own override."""
        if step is not None and step.mode is not None:
            return step.mode
        return self.stepdown_mode

    def retains_stored(self):
        """Return True when stored materials are subject to retainage."""
        return self.stored_materials_retained

    def cap_amount(self, contract_sum, work_completed):
        """Return the ceiling on total retainage, or ``None`` when uncapped."""
        if self.cap_rate is None or self.cap_basis == "none":
            return None
        if self.cap_basis == "contract_sum":
            base = contract_sum
        else:
            base = work_completed
        if not isinstance(base, Money):
            raise InputError("a cap needs a Money base")
        return base * self.cap_rate.value

    def describe(self):
        """Return a human-readable summary of the clause."""
        parts = ["%s of work completed" % (self.base_rate,)]
        if self.change_order_rate is not None:
            parts.append("change orders at %s" % (self.change_order_rate,))
        parts.append(
            "stored materials %s" % ("retained" if self.stored_materials_retained else "paid in full",)
        )
        for step in self.stepdowns:
            parts.append("%s (%s)" % (step, self.mode_for(step)))
        if self.cap_rate is not None:
            parts.append("capped at %s of %s" % (self.cap_rate, self.cap_basis.replace("_", " ")))
        if self.release_at_substantial is not None:
            parts.append("%s released at substantial completion" % (self.release_at_substantial,))
        return "; ".join(parts)

    def to_dict(self):
        """Return the terms as plain data."""
        return {
            "base_rate": rate_text(self.base_rate),
            "change_order_rate": (
                rate_text(self.change_order_rate) if self.change_order_rate else None
            ),
            "stored_materials_retained": self.stored_materials_retained,
            "basis": self.basis,
            "stepdowns": [step.to_dict() for step in self.stepdowns],
            "stepdown_mode": self.stepdown_mode,
            "cap_rate": rate_text(self.cap_rate) if self.cap_rate else None,
            "cap_basis": self.cap_basis,
            "release_at_substantial": (
                rate_text(self.release_at_substantial) if self.release_at_substantial else None
            ),
            "punchlist_multiple": (
                str(self.punchlist_multiple) if self.punchlist_multiple is not None else None
            ),
            "final_release_days": self.final_release_days,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild terms from :meth:`to_dict` output."""
        return cls(
            data.get("base_rate", "10%"),
            data.get("change_order_rate"),
            data.get("stored_materials_retained", True),
            data.get("basis", "work_and_stored"),
            [Stepdown.from_dict(entry) for entry in data.get("stepdowns", ())],
            data.get("stepdown_mode", "prospective"),
            data.get("cap_rate"),
            data.get("cap_basis", "contract_sum"),
            data.get("release_at_substantial"),
            data.get("punchlist_multiple"),
            data.get("final_release_days", 30),
            data.get("note", ""),
        )

    def __eq__(self, other):
        return isinstance(other, RetainageTerms) and other.to_dict() == self.to_dict()

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("RetainageTerms", self.base_rate.value, self.basis, self.stepdown_mode))

    def __str__(self):
        return self.describe()

    def __repr__(self):
        return "RetainageTerms(%r, %d step-downs)" % (str(self.base_rate), len(self.stepdowns))


def standard_terms(rate="10%"):
    """Return the common private-work clause: ten percent, no step-down.

    >>> standard_terms("5%").describe()
    '5% of work completed; stored materials retained'
    """
    return RetainageTerms(rate)
