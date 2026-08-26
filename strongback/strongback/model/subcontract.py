"""Flow-down: what a subcontract inherits from the prime contract above it.

A subcontract is an ordinary :class:`~strongback.model.contract.Contract`, so
this module is not another contract type.  It is the *link* -- which prime
schedule lines a subcontract's scope covers, and which clauses flow down from
the prime rather than being negotiated afresh.

Flow-down is where two conventions collide.  Under a strict flow-down the sub
is retained at whatever rate the owner retains the general contractor, so an
owner's step-down at fifty percent completion reaches the sub automatically.
Under an independent clause the sub's rate is the sub's rate, and a general
contractor whose own retainage drops to five keeps holding ten below.  Both are
written every day.  Which one is in force changes the sub's cheque, so it is
recorded here rather than assumed.
"""

from ..core.ids import normalise_code, normalise_id
from ..core.money import zero
from ..core.percent import Rate
from ..errors import DataError, InputError

__all__ = ["FLOW_DOWN_RULES", "SubcontractLink", "FlowDownPolicy", "SubcontractRegister"]

FLOW_DOWN_RULES = ("independent", "mirror_rate", "mirror_all")


class FlowDownPolicy:
    """Which prime clauses reach a subcontract.

    >>> policy = FlowDownPolicy("mirror_rate")
    >>> policy.mirrors_rate()
    True
    >>> policy.mirrors_stepdowns()
    False
    """

    __slots__ = ("rule", "pay_when_paid", "waiver_flow_down", "note")

    def __init__(self, rule="independent", pay_when_paid=False, waiver_flow_down=True, note=""):
        if str(rule) not in FLOW_DOWN_RULES:
            raise InputError(
                "unknown flow-down rule %r; known: %s" % (rule, ", ".join(FLOW_DOWN_RULES))
            )
        self.rule = str(rule)
        self.pay_when_paid = bool(pay_when_paid)
        self.waiver_flow_down = bool(waiver_flow_down)
        self.note = str(note)

    def mirrors_rate(self):
        """Return True when the sub is retained at the prime's rate."""
        return self.rule in ("mirror_rate", "mirror_all")

    def mirrors_stepdowns(self):
        """Return True when the prime's step-downs reach the sub."""
        return self.rule == "mirror_all"

    def effective_terms(self, prime_terms, sub_terms):
        """Return the retainage terms actually in force for the sub."""
        if self.rule == "independent":
            return sub_terms
        if self.rule == "mirror_all":
            return prime_terms
        from ..retainage.terms import RetainageTerms

        return RetainageTerms(
            prime_terms.base_rate,
            sub_terms.change_order_rate,
            sub_terms.stored_materials_retained,
            sub_terms.basis,
            sub_terms.stepdowns,
            sub_terms.stepdown_mode,
            sub_terms.cap_rate,
            sub_terms.cap_basis,
            sub_terms.release_at_substantial,
            sub_terms.punchlist_multiple,
            sub_terms.final_release_days,
            "rate mirrored from the prime contract",
        )

    def to_dict(self):
        """Return the policy as plain data."""
        return {
            "rule": self.rule,
            "pay_when_paid": self.pay_when_paid,
            "waiver_flow_down": self.waiver_flow_down,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild a policy from :meth:`to_dict` output."""
        return cls(
            data.get("rule", "independent"),
            data.get("pay_when_paid", False),
            data.get("waiver_flow_down", True),
            data.get("note", ""),
        )

    def __repr__(self):
        return "FlowDownPolicy(%r)" % (self.rule,)


class SubcontractLink:
    """A subcontract's scope, expressed as a share of prime schedule lines.

    >>> link = SubcontractLink("C-200", "C-100", {"03300": "1.0", "03400": "0.5"})
    >>> str(link.share_of("03300"))
    '100%'
    >>> link.covers("03400")
    True
    >>> link.covers("09900")
    False
    """

    __slots__ = ("subcontract_id", "prime_contract_id", "shares", "flow_down", "scope")

    def __init__(self, subcontract_id, prime_contract_id, shares=None, flow_down=None, scope=""):
        self.subcontract_id = normalise_id(subcontract_id, "subcontract id")
        self.prime_contract_id = normalise_id(prime_contract_id, "prime contract id")
        self.shares = {}
        for code, share in dict(shares or {}).items():
            rate = Rate.share(share)
            if rate.value <= 0 or rate.value > 1:
                raise DataError(
                    "subcontract %s takes an impossible share of %s"
                    % (self.subcontract_id, code)
                )
            self.shares[normalise_code(code)] = rate
        self.flow_down = flow_down if flow_down is not None else FlowDownPolicy()
        self.scope = str(scope)

    def covers(self, code):
        """Return True when the subcontract covers a prime schedule line."""
        return normalise_code(code) in self.shares

    def share_of(self, code):
        """Return the share of a prime line this subcontract holds."""
        code = normalise_code(code)
        if code not in self.shares:
            raise DataError(
                "subcontract %s does not cover line %s" % (self.subcontract_id, code)
            )
        return self.shares[code]

    def value_against(self, schedule, currency="USD"):
        """Return the prime-side value of the scope this subcontract covers."""
        running = zero(currency)
        for code, share in sorted(self.shares.items()):
            line = schedule.get(code)
            if line is None:
                raise DataError("subcontract %s names missing line %s" % (self.subcontract_id, code))
            running = running + line.scheduled_value * share.value
        return running

    def to_dict(self):
        """Return the link as plain data."""
        return {
            "subcontract_id": self.subcontract_id,
            "prime_contract_id": self.prime_contract_id,
            "shares": {code: str(share.value) for code, share in sorted(self.shares.items())},
            "flow_down": self.flow_down.to_dict(),
            "scope": self.scope,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild a link from :meth:`to_dict` output."""
        return cls(
            data["subcontract_id"],
            data["prime_contract_id"],
            data.get("shares", {}),
            FlowDownPolicy.from_dict(data.get("flow_down", {})),
            data.get("scope", ""),
        )

    def __repr__(self):
        return "SubcontractLink(%r, %d lines)" % (self.subcontract_id, len(self.shares))


class SubcontractRegister:
    """Every subcontract link on a project, addressable both ways.

    >>> register = SubcontractRegister()
    >>> register.add(SubcontractLink("C-200", "C-100", {"03300": "1.0"}))
    >>> [link.subcontract_id for link in register.covering("03300")]
    ['C-200']
    >>> register.total_share("03300")
    Decimal('1.0')
    """

    def __init__(self, links=()):
        self.links = {}
        for link in links:
            self.add(link)

    def add(self, link):
        """Add a link, refusing a duplicate subcontract."""
        if link.subcontract_id in self.links:
            raise DataError("subcontract %s is already linked" % (link.subcontract_id,))
        self.links[link.subcontract_id] = link

    def get(self, subcontract_id, default=None):
        """Return a link, or ``default``."""
        return self.links.get(normalise_id(subcontract_id, "subcontract id"), default)

    def require(self, subcontract_id):
        """Return a link, raising when it is missing."""
        link = self.get(subcontract_id)
        if link is None:
            raise DataError("no link for subcontract %r" % (subcontract_id,))
        return link

    def ordered(self):
        """Return the links in subcontract order."""
        return [self.links[key] for key in sorted(self.links)]

    def covering(self, code):
        """Return the links covering a prime schedule line."""
        return [link for link in self.ordered() if link.covers(code)]

    def total_share(self, code):
        """Return the total share of a prime line let to subcontractors."""
        running = None
        for link in self.covering(code):
            share = link.share_of(code).value
            running = share if running is None else running + share
        if running is None:
            raise DataError("no subcontract covers line %r" % (code,))
        return running

    def oversubscribed(self):
        """Return the prime lines let out more than once over."""
        codes = set()
        for link in self.ordered():
            codes.update(link.shares)
        return [code for code in sorted(codes) if self.total_share(code) > 1]

    def to_list(self):
        """Return the register as plain data."""
        return [link.to_dict() for link in self.ordered()]

    @classmethod
    def from_list(cls, data):
        """Rebuild a register from :meth:`to_list` output."""
        return cls([SubcontractLink.from_dict(entry) for entry in data])

    def __len__(self):
        return len(self.links)

    def __iter__(self):
        return iter(self.ordered())

    def __repr__(self):
        return "SubcontractRegister(%d links)" % (len(self.links),)
