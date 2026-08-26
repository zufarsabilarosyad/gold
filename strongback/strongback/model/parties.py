"""Who is on the job, and which direction money flows between them.

A pay application always has a payer and a payee, and almost every convention
in this package depends on which side of that pair you are standing.  Retainage
withheld from a subcontractor is not the same money as retainage withheld from
the general contractor by the owner, and a system that models only one of them
cannot answer the question the project superintendent actually asks: how much
of what the owner is holding is mine to release.
"""

from ..core.ids import normalise_id, slugify
from ..errors import InputError

__all__ = ["Party", "Role", "ROLES", "PartyDirectory"]

ROLES = (
    "owner",
    "contractor",
    "subcontractor",
    "supplier",
    "architect",
    "engineer",
    "lender",
    "surety",
    "public_agency",
)


class Role:
    """A named role on a project, with the payment direction implied by it."""

    __slots__ = ("name",)

    def __init__(self, name):
        text = str(name).strip().lower().replace(" ", "_").replace("-", "_")
        if text not in ROLES:
            raise InputError("unknown role %r; known: %s" % (name, ", ".join(ROLES)))
        self.name = text

    def pays_downstream(self):
        """Return True when this role normally pays rather than bills."""
        return self.name in ("owner", "contractor", "lender", "public_agency")

    def is_upstream_of(self, other):
        """Return True when this role sits above ``other`` in the chain."""
        order = {
            "owner": 0,
            "public_agency": 0,
            "lender": 0,
            "architect": 1,
            "engineer": 1,
            "contractor": 2,
            "subcontractor": 3,
            "supplier": 4,
            "surety": 5,
        }
        return order[self.name] < order[Role(other).name if not isinstance(other, Role) else other.name]

    def __eq__(self, other):
        if isinstance(other, Role):
            return other.name == self.name
        if isinstance(other, str):
            return self.name == str(other).strip().lower()
        return NotImplemented

    def __ne__(self, other):
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    def __hash__(self):
        return hash(("Role", self.name))

    def __str__(self):
        return self.name

    def __repr__(self):
        return "Role(%r)" % (self.name,)


class Party:
    """A company or agency on the project.

    >>> owner = Party("OWN", "Harbor Point Holdings", "owner")
    >>> owner.role.pays_downstream()
    True
    >>> owner.slug
    'harbor-point-holdings'
    """

    __slots__ = ("id", "name", "role", "license_number", "address", "tax_id")

    def __init__(self, identifier, name, role, license_number="", address="", tax_id=""):
        self.id = normalise_id(identifier, "party id")
        self.name = str(name).strip()
        if not self.name:
            raise InputError("party %s needs a name" % (self.id,))
        self.role = role if isinstance(role, Role) else Role(role)
        self.license_number = str(license_number)
        self.address = str(address)
        self.tax_id = str(tax_id)

    @property
    def slug(self):
        """Return a filename-safe form of the party name."""
        return slugify(self.name)

    def to_dict(self):
        """Return the party as plain data."""
        return {
            "id": self.id,
            "name": self.name,
            "role": str(self.role),
            "license_number": self.license_number,
            "address": self.address,
            "tax_id": self.tax_id,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild a party from :meth:`to_dict` output."""
        return cls(
            data["id"],
            data["name"],
            data["role"],
            data.get("license_number", ""),
            data.get("address", ""),
            data.get("tax_id", ""),
        )

    def __eq__(self, other):
        return isinstance(other, Party) and other.id == self.id

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("Party", self.id))

    def __str__(self):
        return "%s (%s)" % (self.name, self.role)

    def __repr__(self):
        return "Party(%r, %r)" % (self.id, self.name)


class PartyDirectory:
    """The parties on one project, addressable by identifier.

    >>> directory = PartyDirectory([Party("O1", "Owner Co", "owner")])
    >>> directory.add(Party("G1", "Builder Co", "contractor"))
    >>> [party.id for party in directory.with_role("contractor")]
    ['G1']
    >>> directory["O1"].name
    'Owner Co'
    """

    def __init__(self, parties=()):
        self.parties = {}
        for party in parties:
            self.add(party)

    def add(self, party):
        """Add a party, refusing a duplicate identifier."""
        if party.id in self.parties:
            raise InputError("party %s is already in the directory" % (party.id,))
        self.parties[party.id] = party

    def get(self, identifier, default=None):
        """Return a party by identifier, or ``default``."""
        return self.parties.get(normalise_id(identifier, "party id"), default)

    def require(self, identifier):
        """Return a party by identifier, raising when it is missing."""
        party = self.get(identifier)
        if party is None:
            raise InputError("no party %r on this project" % (identifier,))
        return party

    def with_role(self, role):
        """Return every party holding a role, in identifier order."""
        role = role if isinstance(role, Role) else Role(role)
        return [party for party in self.ordered() if party.role == role]

    def ordered(self):
        """Return the parties sorted by identifier."""
        return [self.parties[key] for key in sorted(self.parties)]

    def to_list(self):
        """Return the directory as plain data."""
        return [party.to_dict() for party in self.ordered()]

    @classmethod
    def from_list(cls, data):
        """Rebuild a directory from :meth:`to_list` output."""
        return cls([Party.from_dict(entry) for entry in data])

    def __getitem__(self, identifier):
        return self.require(identifier)

    def __contains__(self, identifier):
        return normalise_id(identifier, "party id") in self.parties

    def __len__(self):
        return len(self.parties)

    def __iter__(self):
        return iter(self.ordered())

    def __repr__(self):
        return "PartyDirectory(%d parties)" % (len(self.parties),)
