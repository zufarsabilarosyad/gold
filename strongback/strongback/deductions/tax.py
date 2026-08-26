"""Sales and use tax on a progress payment.

Tax on construction is jurisdiction-specific and this module does not pretend
otherwise; what it does is make the three choices that any jurisdiction's rules
reduce to explicit:

* what is taxable -- material only, or the whole contract value;
* when the tax attaches -- on delivery of stored material, or on installation;
* whether retainage is computed on the tax-inclusive or tax-exclusive amount.

The second and third interact.  Taxing on delivery and retaining on the
tax-inclusive figure means the payee finances tax on retained material for the
life of the job, which is a real cash-flow cost and a real argument.
"""

from ..core.money import Money, money, zero
from ..core.percent import Rate, rate_text
from ..core.trace import NULL_TRACE
from ..errors import InputError

__all__ = ["TAXABLE_BASES", "ATTACH_POINTS", "TaxRule", "tax_on"]

TAXABLE_BASES = ("material_only", "all_work", "none")
ATTACH_POINTS = ("delivery", "installation")


class TaxRule:
    """One jurisdiction's treatment, as three choices and a rate.

    >>> rule = TaxRule("6.25%", "material_only", "installation")
    >>> str(rule.rate)
    '6.25%'
    >>> rule.taxes_stored()
    False
    """

    __slots__ = ("rate", "basis", "attach", "retain_on_tax", "jurisdiction", "exempt")

    def __init__(
        self,
        rate,
        basis="material_only",
        attach="installation",
        retain_on_tax=False,
        jurisdiction="",
        exempt=False,
    ):
        self.rate = Rate.parse(rate)
        if str(basis) not in TAXABLE_BASES:
            raise InputError("unknown taxable basis %r; known: %s" % (basis, ", ".join(TAXABLE_BASES)))
        self.basis = str(basis)
        if str(attach) not in ATTACH_POINTS:
            raise InputError("unknown attach point %r; known: %s" % (attach, ", ".join(ATTACH_POINTS)))
        self.attach = str(attach)
        self.retain_on_tax = bool(retain_on_tax)
        self.jurisdiction = str(jurisdiction)
        self.exempt = bool(exempt)

    def taxes_stored(self):
        """Return True when tax attaches to stored material before install."""
        return self.attach == "delivery" and not self.exempt and self.basis != "none"

    def taxable_amount(self, work, material_share, stored):
        """Return the amount tax is charged on this period."""
        currency = work.currency
        if self.exempt or self.basis == "none":
            return zero(currency)
        if self.basis == "all_work":
            base = work
        else:
            base = work * Rate.share(material_share).value
        if self.taxes_stored():
            base = base + stored
        return base

    def to_dict(self):
        """Return the rule as plain data."""
        return {
            "rate": rate_text(self.rate),
            "basis": self.basis,
            "attach": self.attach,
            "retain_on_tax": self.retain_on_tax,
            "jurisdiction": self.jurisdiction,
            "exempt": self.exempt,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild a rule from :meth:`to_dict` output."""
        return cls(
            data.get("rate", "0"),
            data.get("basis", "material_only"),
            data.get("attach", "installation"),
            data.get("retain_on_tax", False),
            data.get("jurisdiction", ""),
            data.get("exempt", False),
        )

    def __repr__(self):
        return "TaxRule(%r, %r)" % (str(self.rate), self.basis)


def tax_on(work, material_share, stored, rule, trace=NULL_TRACE):
    """Return the tax charged on a period's billing.

    >>> from ..core.money import money
    >>> rule = TaxRule("6%", "material_only", "installation")
    >>> str(tax_on(money("100000"), "40%", money("20000"), rule))
    '$2,400.00'
    >>> delivery = TaxRule("6%", "material_only", "delivery")
    >>> str(tax_on(money("100000"), "40%", money("20000"), delivery))
    '$3,600.00'
    >>> str(tax_on(money("100000"), "40%", money("20000"), TaxRule("6%", exempt=True)))
    '$0.00'
    """
    if not isinstance(work, Money) or not isinstance(stored, Money):
        raise InputError("tax needs Money amounts")
    base = rule.taxable_amount(work, material_share, stored)
    charged = base * rule.rate.value
    trace.record(
        "tax",
        "contract",
        "%s on %s (%s, %s)" % (charged, base, rule.basis, rule.attach),
    )
    return charged
