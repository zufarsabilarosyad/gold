"""A project: the parties, the contracts under it, and the shared calendar.

Most of this package works on one contract at a time.  The project exists for
the two questions that cannot be answered from a single contract: whether the
subcontracts add up to less than the prime contract they sit under, and how
much of what the owner is holding flows through to whom.
"""

from ..core.dates import format_date, parse_date
from ..core.ids import normalise_id, slugify
from ..core.money import zero
from ..core.workcalendar import WorkCalendar, calendar_named
from ..errors import DataError, InputError
from .contract import Contract
from .costcode import CostCodeTable
from .parties import PartyDirectory

__all__ = ["Project"]


class Project:
    """A job, its parties and its contracts.

    >>> from .parties import Party
    >>> from .sov import ScheduleOfValues, SOVLine
    >>> from ..core.money import money
    >>> owner = Party("OWN", "Harbor Point Holdings", "owner")
    >>> builder = Party("GC", "Keel & Sons", "contractor")
    >>> sov = ScheduleOfValues([SOVLine("01000", "General conditions", money("500000"))])
    >>> project = Project("P-1", "Harbor Point Phase II", parties=[owner, builder])
    >>> _ = project.add_contract(Contract("C-100", owner, builder, sov))
    >>> str(project.prime_contract().original_sum())
    '$500,000.00'
    >>> project.slug
    'harbor-point-phase-ii'
    """

    def __init__(
        self,
        identifier,
        name,
        parties=(),
        contracts=(),
        cost_codes=None,
        calendar=None,
        currency="USD",
        address="",
        started_on=None,
        jurisdiction="",
    ):
        self.id = normalise_id(identifier, "project id")
        self.name = str(name).strip()
        if not self.name:
            raise InputError("project %s needs a name" % (self.id,))
        self.parties = parties if isinstance(parties, PartyDirectory) else PartyDirectory(parties)
        self.contracts = {}
        self.cost_codes = cost_codes if cost_codes is not None else CostCodeTable()
        if calendar is None:
            self.calendar = calendar_named("us-federal")
        elif isinstance(calendar, WorkCalendar):
            self.calendar = calendar
        else:
            self.calendar = calendar_named(calendar)
        self.currency = currency
        self.address = str(address)
        self.started_on = parse_date(started_on) if started_on else None
        self.jurisdiction = str(jurisdiction)
        for contract in contracts:
            self.add_contract(contract)

    @property
    def slug(self):
        """Return a filename-safe form of the project name."""
        return slugify(self.name)

    def add_contract(self, contract):
        """Attach a contract, refusing a duplicate identifier."""
        if not isinstance(contract, Contract):
            raise InputError("expected a Contract")
        if contract.id in self.contracts:
            raise DataError("contract %s is already on this project" % (contract.id,))
        self.contracts[contract.id] = contract
        return contract

    def contract(self, identifier):
        """Return a contract by identifier."""
        key = normalise_id(identifier, "contract id")
        if key not in self.contracts:
            raise DataError("no contract %r on project %s" % (identifier, self.id))
        return self.contracts[key]

    def ordered_contracts(self):
        """Return the contracts in identifier order."""
        return [self.contracts[key] for key in sorted(self.contracts)]

    def prime_contract(self):
        """Return the owner-to-contractor contract, or raise when ambiguous."""
        primes = [
            contract
            for contract in self.ordered_contracts()
            if contract.payer.role == "owner" or contract.payer.role == "public_agency"
        ]
        if not primes:
            raise DataError("project %s has no prime contract" % (self.id,))
        if len(primes) > 1:
            raise DataError("project %s has %d prime contracts" % (self.id, len(primes)))
        return primes[0]

    def subcontracts(self):
        """Return the contracts whose payer is the general contractor."""
        return [
            contract
            for contract in self.ordered_contracts()
            if contract.payer.role == "contractor"
        ]

    def subcontracted_value(self, as_of=None):
        """Return the total value of the subcontracts let so far."""
        running = zero(self.currency)
        for contract in self.subcontracts():
            running = running + contract.contract_sum(as_of)
        return running

    def uncommitted_value(self, as_of=None):
        """Return prime contract sum less the subcontracts let against it."""
        return self.prime_contract().contract_sum(as_of) - self.subcontracted_value(as_of)

    def contracts_for(self, party_id):
        """Return every contract a party is on, either side."""
        key = normalise_id(party_id, "party id")
        return [
            contract
            for contract in self.ordered_contracts()
            if contract.payer.id == key or contract.payee.id == key
        ]

    def validate(self):
        """Return a list of problems across the project."""
        problems = []
        for contract in self.ordered_contracts():
            problems.extend(
                "%s: %s" % (contract.id, problem) for problem in contract.validate()
            )
        try:
            if self.uncommitted_value().is_negative():
                problems.append("subcontracts exceed the prime contract sum")
        except DataError as error:
            problems.append(str(error))
        return problems

    def to_dict(self):
        """Return the project as plain data."""
        return {
            "id": self.id,
            "name": self.name,
            "currency": self.currency,
            "address": self.address,
            "jurisdiction": self.jurisdiction,
            "started_on": format_date(self.started_on) if self.started_on else None,
            "calendar": self.calendar.name,
            "parties": self.parties.to_list(),
            "cost_codes": self.cost_codes.to_list(),
            "contracts": [contract.to_dict() for contract in self.ordered_contracts()],
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild a project from :meth:`to_dict` output."""
        currency = data.get("currency", "USD")
        project = cls(
            data["id"],
            data["name"],
            PartyDirectory.from_list(data.get("parties", ())),
            (),
            CostCodeTable.from_list(data.get("cost_codes", ()), currency),
            data.get("calendar"),
            currency,
            data.get("address", ""),
            data.get("started_on"),
            data.get("jurisdiction", ""),
        )
        for entry in data.get("contracts", ()):
            project.add_contract(Contract.from_dict(entry))
        return project

    def __len__(self):
        return len(self.contracts)

    def __iter__(self):
        return iter(self.ordered_contracts())

    def __repr__(self):
        return "Project(%r, %d contracts)" % (self.id, len(self.contracts))
