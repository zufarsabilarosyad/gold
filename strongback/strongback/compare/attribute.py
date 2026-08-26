"""Pricing each convention's share of a difference.

Two policies produce two payments.  Subtracting them says *how much*; this
module says *why*, by running the job again with one knob moved at a time and
recording what that knob alone was worth.

The parts do not add up to the whole, and that is not an error.  Conventions
interact: a step-down that only bites once stored materials are in the base is
worth nothing until the stored-materials knob moves too.  The unexplained
remainder is reported as the interaction residue rather than being smeared
across the parts to make the table balance, because a large residue is the
useful signal that two clauses are entangled.
"""

from ..core.money import zero
from ..engine.run import build_application
from ..errors import InputError
from ..policy.resolve import Policy

__all__ = ["Attribution", "attribute_difference"]


class Attribution:
    """What one knob was worth on its own, and the leftover.

    >>> from ..core.money import money
    >>> attribution = Attribution(money("-6000"),
    ...                           {"stored_conversion": money("-5000")},
    ...                           money("-1000"))
    >>> str(attribution.total)
    '-$6,000.00'
    >>> attribution.ranked()[0][0]
    'stored_conversion'
    >>> str(attribution.residue)
    '-$1,000.00'
    """

    __slots__ = ("total", "parts", "residue")

    def __init__(self, total, parts, residue):
        self.total = total
        self.parts = dict(parts)
        self.residue = residue

    def ranked(self):
        """Return the knobs by absolute effect, largest first."""
        return sorted(
            self.parts.items(),
            key=lambda item: (-abs(item[1].amount), item[0]),
        )

    def explained(self):
        """Return the part of the difference the single knobs account for."""
        running = zero(self.total.currency)
        for amount in self.parts.values():
            running = running + amount
        return running

    def to_dict(self):
        """Return the attribution as plain data."""
        return {
            "total": str(self.total.amount),
            "explained": str(self.explained().amount),
            "residue": str(self.residue.amount),
            "parts": {
                name: str(amount.amount) for name, amount in sorted(self.parts.items())
            },
        }

    def __len__(self):
        return len(self.parts)

    def __repr__(self):
        return "Attribution(%s, %d knobs)" % (self.total, len(self.parts))


def attribute_difference(context, first_policy, second_policy, number, materiality=None):
    """Return what each differing knob contributed to the payment difference.

    >>> from ..core.money import money
    >>> from ..core.period import monthly_schedule
    >>> from ..engine.context import RunContext
    >>> from ..model.contract import Contract
    >>> from ..model.parties import Party
    >>> from ..model.sov import ScheduleOfValues, SOVLine
    >>> from ..progress.observation import ProgressEntry, ProgressLedger
    >>> from ..progress.stored import StoredEntry, StoredLedger
    >>> owner, builder = Party("O", "Owner", "owner"), Party("G", "Builder", "contractor")
    >>> sov = ScheduleOfValues([SOVLine("26200", "Switchgear", money("200000"),
    ...                                 stored_eligible=True)])
    >>> progress = ProgressLedger([ProgressEntry("26200", 1, percent="20%")])
    >>> stored = StoredLedger([StoredEntry("26200", 1, delivered=money("60000"))])
    >>> context = RunContext(Contract("C-1", owner, builder, sov),
    ...                      monthly_schedule("2024-09-01", 2), progress=progress,
    ...                      stored=stored)
    >>> attribution = attribute_difference(context, Policy(),
    ...                                    Policy("owner_favorable"), 1)
    >>> str(attribution.total)
    '-$10,800.00'
    >>> name, effect = attribution.ranked()[0]
    >>> name, str(effect)
    ('stored_conversion', '-$10,800.00')
    >>> str(attribution.residue)
    '$0.00'
    """
    if not isinstance(first_policy, Policy) or not isinstance(second_policy, Policy):
        raise InputError("attribution compares two Policy objects")
    base = build_application(context.with_policy(first_policy), number, evaluate=False)
    target = build_application(context.with_policy(second_policy), number, evaluate=False)
    total = target.summary.current_payment_due() - base.summary.current_payment_due()
    currency = total.currency
    parts = {}
    for name, (mine, theirs) in sorted(first_policy.differences(second_policy).items()):
        moved = Policy(first_policy.profile, dict(first_policy.overrides()), first_policy.name)
        moved.settings.update(first_policy.settings)
        moved.set(name, theirs)
        alone = build_application(context.with_policy(moved), number, evaluate=False)
        effect = alone.summary.current_payment_due() - base.summary.current_payment_due()
        if effect.is_zero():
            continue
        if materiality is not None and abs(effect) < materiality:
            continue
        parts[name] = effect
    explained = zero(currency)
    for amount in parts.values():
        explained = explained + amount
    return Attribution(total, parts, total - explained)
