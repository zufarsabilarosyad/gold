"""Joint cheques: one instrument, two payees, and a split nobody wrote down.

A joint cheque names the subcontractor and their supplier, and it discharges
the general contractor's obligation to the sub in full even though the sub may
receive none of it.  Two questions follow, and they are answered differently:

*How much of the cheque counts as paying the sub's application?*  Under the
``full`` convention the whole cheque does -- the sub was paid, and what they did
with it is between them and their supplier.  Under ``net`` only the part the sub
actually banked counts, which keeps the sub's ledger honest and the general
contractor's exposure visible.

*What happens to the balance if the supplier is owed less than the cheque?*
The supplier endorses and the remainder goes to the sub, which is a second
allocation, not a rounding.
"""

from ..core.money import Money, zero
from ..core.numbers import allocate
from ..core.trace import NULL_TRACE
from ..errors import DataError, InputError

__all__ = ["CREDIT_RULES", "JointCheck", "split_joint_check", "credited_to_payee"]

CREDIT_RULES = ("full", "net")


class JointCheck:
    """A cheque naming a payee and one or more joint payees.

    >>> from ..core.money import money
    >>> check = JointCheck("JC-1", money("42000"), "SUB-STEEL",
    ...                    {"SUP-MILL": money("31000")})
    >>> str(check.amount)
    '$42,000.00'
    >>> str(check.claimed_total())
    '$31,000.00'
    """

    __slots__ = ("id", "amount", "payee", "claims", "issued_on", "reference", "note")

    def __init__(self, identifier, amount, payee, claims=None, issued_on=None, reference="", note=""):
        self.id = str(identifier)
        if not isinstance(amount, Money):
            raise InputError("a joint cheque needs a Money amount")
        if amount.is_negative():
            raise DataError("joint cheque %s is negative" % (self.id,))
        self.amount = amount
        self.payee = str(payee)
        self.claims = {}
        for name, claimed in dict(claims or {}).items():
            if not isinstance(claimed, Money):
                raise InputError("a joint payee claim must be Money")
            self.claims[str(name)] = claimed
        from ..core.dates import parse_date

        self.issued_on = parse_date(issued_on) if issued_on else None
        self.reference = str(reference)
        self.note = str(note)

    def claimed_total(self):
        """Return the total claimed by the joint payees."""
        running = zero(self.amount.currency)
        for name in sorted(self.claims):
            running = running + self.claims[name]
        return running

    def is_oversubscribed(self):
        """Return True when the joint payees claim more than the cheque."""
        return self.claimed_total() > self.amount

    def to_dict(self):
        """Return the cheque as plain data."""
        from ..core.dates import format_date

        return {
            "id": self.id,
            "amount": str(self.amount.amount),
            "payee": self.payee,
            "claims": {name: str(value.amount) for name, value in sorted(self.claims.items())},
            "issued_on": format_date(self.issued_on) if self.issued_on else None,
            "reference": self.reference,
            "note": self.note,
        }

    def __repr__(self):
        return "JointCheck(%r, %s, %d joint payees)" % (self.id, self.amount, len(self.claims))


def split_joint_check(check, trace=NULL_TRACE):
    """Return how a joint cheque divides between its payees.

    An ordinary cheque covers every claim and the remainder goes to the payee:

    >>> from ..core.money import money
    >>> check = JointCheck("JC-1", money("42000"), "SUB-STEEL",
    ...                    {"SUP-MILL": money("31000")})
    >>> split = split_joint_check(check)
    >>> str(split["SUP-MILL"]), str(split["SUB-STEEL"])
    ('$31,000.00', '$11,000.00')

    An oversubscribed cheque is shared out in proportion to the claims and the
    payee receives nothing:

    >>> tight = JointCheck("JC-2", money("30000"), "SUB-STEEL",
    ...                    {"SUP-MILL": money("25000"), "SUP-DECK": money("15000")})
    >>> split = split_joint_check(tight)
    >>> str(split["SUP-MILL"]), str(split["SUP-DECK"]), str(split["SUB-STEEL"])
    ('$18,750.00', '$11,250.00', '$0.00')
    """
    currency = check.amount.currency
    result = {}
    if not check.claims:
        result[check.payee] = check.amount
        return result
    if check.is_oversubscribed():
        names = sorted(check.claims)
        weights = [check.claims[name].amount for name in names]
        parts = allocate(check.amount.amount, weights)
        for name, part in zip(names, parts):
            result[name] = Money(part, currency)
        result[check.payee] = zero(currency)
        trace.record(
            "joint-check",
            check.id,
            "claims of %s exceed the cheque; shared pro rata" % (check.claimed_total(),),
        )
        return result
    remainder = check.amount
    for name in sorted(check.claims):
        result[name] = check.claims[name]
        remainder = remainder - check.claims[name]
    result[check.payee] = remainder
    trace.record("joint-check", check.id, "%s endorsed to the payee" % (remainder,))
    return result


def credited_to_payee(check, rule="full", trace=NULL_TRACE):
    """Return how much of a joint cheque counts against the payee's balance.

    >>> from ..core.money import money
    >>> check = JointCheck("JC-1", money("42000"), "SUB-STEEL",
    ...                    {"SUP-MILL": money("31000")})
    >>> str(credited_to_payee(check, "full"))
    '$42,000.00'
    >>> str(credited_to_payee(check, "net"))
    '$11,000.00'
    """
    rule = str(rule)
    if rule not in CREDIT_RULES:
        raise InputError("unknown credit rule %r; known: %s" % (rule, ", ".join(CREDIT_RULES)))
    if rule == "full":
        return check.amount
    split = split_joint_check(check, trace)
    return split.get(check.payee, zero(check.amount.currency))
