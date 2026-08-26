"""Certificates of insurance, and the lapse nobody notices until the audit.

A certificate is a promise about a date range.  The compliance question is not
"do we have a certificate" but "was there coverage on the day the work was
done", and those differ whenever a policy renews mid-job -- which is most jobs,
because policies renew annually and jobs do not.

The other half is endorsements.  Additional-insured status and a waiver of
subrogation are separate boxes on the form, and a certificate with the right
limits and neither endorsement satisfies the letter of the requirement while
protecting nobody.
"""

from ..core.dates import add_days, format_date, parse_date
from ..core.ids import normalise_id
from ..core.money import Money, money, zero
from ..errors import DataError, InputError

__all__ = ["COVERAGE_KINDS", "Certificate", "InsuranceFile", "coverage_gaps"]

COVERAGE_KINDS = (
    "general_liability",
    "auto",
    "workers_compensation",
    "umbrella",
    "builders_risk",
    "professional",
    "pollution",
)


class Certificate:
    """One policy's coverage of one party for one date range.

    >>> from ..core.money import money
    >>> certificate = Certificate("COI-1", "general_liability", "2024-07-01",
    ...                           "2025-07-01", each_occurrence=money("1000000"),
    ...                           aggregate=money("2000000"), additional_insured=True)
    >>> certificate.covers("2024-11-30")
    True
    >>> certificate.covers("2025-08-01")
    False
    >>> certificate.expires_within(60, "2025-06-01")
    True
    """

    __slots__ = (
        "id",
        "kind",
        "effective",
        "expires",
        "each_occurrence",
        "aggregate",
        "carrier",
        "policy_number",
        "additional_insured",
        "waiver_of_subrogation",
        "primary_noncontributory",
    )

    def __init__(
        self,
        identifier,
        kind,
        effective,
        expires,
        each_occurrence=None,
        aggregate=None,
        carrier="",
        policy_number="",
        additional_insured=False,
        waiver_of_subrogation=False,
        primary_noncontributory=False,
    ):
        self.id = normalise_id(identifier, "certificate id")
        if str(kind) not in COVERAGE_KINDS:
            raise InputError("unknown coverage %r; known: %s" % (kind, ", ".join(COVERAGE_KINDS)))
        self.kind = str(kind)
        self.effective = parse_date(effective, "effective date")
        self.expires = parse_date(expires, "expiry date")
        if self.expires <= self.effective:
            raise DataError("certificate %s expires before it starts" % (self.id,))
        for name, limit in (("each occurrence", each_occurrence), ("aggregate", aggregate)):
            if limit is not None and not isinstance(limit, Money):
                raise InputError("the %s limit must be Money" % (name,))
        self.each_occurrence = each_occurrence
        self.aggregate = aggregate
        self.carrier = str(carrier)
        self.policy_number = str(policy_number)
        self.additional_insured = bool(additional_insured)
        self.waiver_of_subrogation = bool(waiver_of_subrogation)
        self.primary_noncontributory = bool(primary_noncontributory)

    def covers(self, day):
        """Return True when the policy was in force on a date."""
        day = parse_date(day)
        return self.effective <= day < self.expires

    def expires_within(self, days, as_of):
        """Return True when the policy lapses within a window of a date."""
        return self.expires <= add_days(parse_date(as_of), int(days))

    def meets_limits(self, each_occurrence=None, aggregate=None):
        """Return True when the certificate's limits reach the requirement."""
        if each_occurrence is not None:
            if self.each_occurrence is None or self.each_occurrence < each_occurrence:
                return False
        if aggregate is not None:
            if self.aggregate is None or self.aggregate < aggregate:
                return False
        return True

    def to_dict(self):
        """Return the certificate as plain data."""
        return {
            "id": self.id,
            "kind": self.kind,
            "effective": format_date(self.effective),
            "expires": format_date(self.expires),
            "each_occurrence": str(self.each_occurrence.amount) if self.each_occurrence else None,
            "aggregate": str(self.aggregate.amount) if self.aggregate else None,
            "carrier": self.carrier,
            "policy_number": self.policy_number,
            "additional_insured": self.additional_insured,
            "waiver_of_subrogation": self.waiver_of_subrogation,
            "primary_noncontributory": self.primary_noncontributory,
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild a certificate from :meth:`to_dict` output."""
        return cls(
            data["id"],
            data["kind"],
            data["effective"],
            data["expires"],
            money(data["each_occurrence"], currency) if data.get("each_occurrence") else None,
            money(data["aggregate"], currency) if data.get("aggregate") else None,
            data.get("carrier", ""),
            data.get("policy_number", ""),
            data.get("additional_insured", False),
            data.get("waiver_of_subrogation", False),
            data.get("primary_noncontributory", False),
        )

    def __repr__(self):
        return "Certificate(%r, %r)" % (self.id, self.kind)


class InsuranceFile:
    """The certificates held for one party.

    >>> from ..core.money import money
    >>> file = InsuranceFile()
    >>> file.add(Certificate("A", "general_liability", "2024-01-01", "2025-01-01",
    ...                      money("1000000"), money("2000000"), additional_insured=True))
    >>> file.covered_on("general_liability", "2024-11-01")
    True
    >>> file.covered_on("auto", "2024-11-01")
    False
    >>> [problem for problem in file.check("2024-11-01", {"auto": None})]
    ['no auto coverage in force on 2024-11-01']
    """

    def __init__(self, certificates=()):
        self.certificates = {}
        for certificate in certificates:
            self.add(certificate)

    def add(self, certificate):
        """Add a certificate, refusing a duplicate identifier."""
        if certificate.id in self.certificates:
            raise DataError("certificate %s appears twice" % (certificate.id,))
        self.certificates[certificate.id] = certificate

    def ordered(self):
        """Return the certificates in kind then effective-date order."""
        return sorted(
            self.certificates.values(), key=lambda item: (item.kind, item.effective, item.id)
        )

    def of_kind(self, kind):
        """Return the certificates of one coverage kind."""
        return [item for item in self.ordered() if item.kind == str(kind)]

    def in_force(self, kind, day):
        """Return the certificates of a kind in force on a date."""
        return [item for item in self.of_kind(kind) if item.covers(day)]

    def covered_on(self, kind, day):
        """Return True when any certificate of a kind was in force."""
        return bool(self.in_force(kind, day))

    def check(self, day, requirements, endorsements=()):
        """Return the compliance problems on a date, empty when clean.

        ``requirements`` maps a coverage kind to a required each-occurrence
        limit, or to ``None`` when only the coverage itself is required.
        """
        problems = []
        for kind in sorted(requirements):
            in_force = self.in_force(kind, day)
            if not in_force:
                problems.append("no %s coverage in force on %s" % (kind, format_date(day)))
                continue
            limit = requirements[kind]
            if limit is not None and not any(item.meets_limits(limit) for item in in_force):
                problems.append(
                    "%s coverage on %s is below the required %s"
                    % (kind, format_date(day), limit)
                )
            for endorsement in endorsements:
                if not any(getattr(item, endorsement, False) for item in in_force):
                    problems.append(
                        "%s coverage lacks %s" % (kind, endorsement.replace("_", " "))
                    )
        return problems

    def to_list(self):
        """Return the file as plain data."""
        return [certificate.to_dict() for certificate in self.ordered()]

    @classmethod
    def from_list(cls, data, currency="USD"):
        """Rebuild a file from :meth:`to_list` output."""
        return cls([Certificate.from_dict(entry, currency) for entry in data])

    def __len__(self):
        return len(self.certificates)

    def __iter__(self):
        return iter(self.ordered())

    def __repr__(self):
        return "InsuranceFile(%d certificates)" % (len(self.certificates),)


def coverage_gaps(file, kind, start, end):
    """Return the date ranges within a window that have no coverage.

    >>> from ..core.money import money
    >>> file = InsuranceFile([
    ...     Certificate("A", "general_liability", "2024-01-01", "2024-07-01"),
    ...     Certificate("B", "general_liability", "2024-08-01", "2025-01-01"),
    ... ])
    >>> [(format_date(start), format_date(end))
    ...  for start, end in coverage_gaps(file, "general_liability",
    ...                                  "2024-01-01", "2024-12-31")]
    [('2024-07-01', '2024-07-31')]
    """
    start = parse_date(start, "start")
    end = parse_date(end, "end")
    gaps = []
    current = start
    open_gap = None
    while current <= end:
        if file.covered_on(kind, current):
            if open_gap is not None:
                gaps.append((open_gap, add_days(current, -1)))
                open_gap = None
        else:
            if open_gap is None:
                open_gap = current
        current = add_days(current, 1)
    if open_gap is not None:
        gaps.append((open_gap, end))
    return gaps
