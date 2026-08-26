"""The summary page: nine lines, and the two that people disagree about.

The form is old and the arithmetic is fixed:

1. original contract sum
2. net change by change orders
3. contract sum to date (1 + 2)
4. total completed and stored to date
5. retainage (work + stored)
6. total earned less retainage (4 - 5)
7. less previous certificates for payment
8. current payment due (6 - 7)
9. balance to finish including retainage (3 - 6)

Line 7 is the first place two honest systems diverge.  "Previous certificates"
can mean what the payer *certified* or what the payer actually *paid*, and on a
job where an application was certified short, the two differ for the rest of
the contract.  Certification is the form's own reading and the default here;
paid is what a contractor's accounting department usually wants, and it makes
line 8 include the arrears.

Line 9 is the second.  It is a subtraction from the contract sum, so it
includes retainage by construction -- yet the balance a superintendent quotes
is usually the *work* left, which is line 3 minus line 4.  Both are available
here under names that say which is which.
"""

from ..core.money import Money, money, zero
from ..core.percent import Rate
from ..core.table import key_value_block
from ..errors import DataError, InputError

__all__ = ["ApplicationSummary", "PREVIOUS_BASES"]

PREVIOUS_BASES = ("certified", "paid")


class ApplicationSummary:
    """The summary figures of one pay application.

    >>> from ..core.money import money
    >>> summary = ApplicationSummary(
    ...     original=money("500000"), change_orders=money("42000"),
    ...     completed_and_stored=money("175000"),
    ...     retainage_work=money("16000"), retainage_stored=money("1500"),
    ...     previous_certificates=money("90000"))
    >>> str(summary.contract_sum())
    '$542,000.00'
    >>> str(summary.total_retainage())
    '$17,500.00'
    >>> str(summary.earned_less_retainage())
    '$157,500.00'
    >>> str(summary.current_payment_due())
    '$67,500.00'
    >>> str(summary.balance_to_finish())
    '$384,500.00'
    """

    __slots__ = (
        "original",
        "change_orders",
        "completed_and_stored",
        "work_completed",
        "stored",
        "retainage_work",
        "retainage_stored",
        "previous_certificates",
        "previous_basis",
        "deductions",
        "tax",
        "released_retainage",
        "currency",
    )

    def __init__(
        self,
        original,
        change_orders=None,
        completed_and_stored=None,
        work_completed=None,
        stored=None,
        retainage_work=None,
        retainage_stored=None,
        previous_certificates=None,
        previous_basis="certified",
        deductions=None,
        tax=None,
        released_retainage=None,
    ):
        if not isinstance(original, Money):
            raise InputError("the original contract sum must be Money")
        self.currency = original.currency
        self.original = original
        self.change_orders = self._amount(change_orders)
        self.work_completed = self._amount(work_completed)
        self.stored = self._amount(stored)
        if completed_and_stored is None:
            self.completed_and_stored = self.work_completed + self.stored
        else:
            self.completed_and_stored = completed_and_stored
        self.retainage_work = self._amount(retainage_work)
        self.retainage_stored = self._amount(retainage_stored)
        self.previous_certificates = self._amount(previous_certificates)
        if str(previous_basis) not in PREVIOUS_BASES:
            raise InputError(
                "unknown previous-certificates basis %r; known: %s"
                % (previous_basis, ", ".join(PREVIOUS_BASES))
            )
        self.previous_basis = str(previous_basis)
        self.deductions = self._amount(deductions)
        self.tax = self._amount(tax)
        self.released_retainage = self._amount(released_retainage)

    def _amount(self, value):
        """Return a Money, defaulting to zero in this summary's currency."""
        if value is None:
            return zero(self.currency)
        if not isinstance(value, Money):
            raise InputError("summary figures must be Money, got %r" % (value,))
        if value.currency != self.currency:
            raise InputError("summary figures must share a currency")
        return value

    def contract_sum(self):
        """Line 3: the contract sum to date."""
        return self.original + self.change_orders

    def total_retainage(self):
        """Line 5: retainage on work plus retainage on stored materials."""
        return self.retainage_work + self.retainage_stored

    def earned_less_retainage(self):
        """Line 6: what has been earned and is not being held."""
        return self.completed_and_stored - self.total_retainage()

    def current_payment_due(self):
        """Line 8: this application's payment before deductions and tax."""
        return self.earned_less_retainage() - self.previous_certificates

    def net_payable(self):
        """Return the payment after deductions, tax and retainage released.

        >>> from ..core.money import money
        >>> summary = ApplicationSummary(money("100000"),
        ...     completed_and_stored=money("50000"), retainage_work=money("5000"),
        ...     deductions=money("2000"), tax=money("1200"))
        >>> str(summary.net_payable())
        '$44,200.00'
        """
        return self.current_payment_due() - self.deductions + self.tax + self.released_retainage

    def balance_to_finish(self):
        """Line 9: contract sum less what has been earned net of retainage."""
        return self.contract_sum() - self.earned_less_retainage()

    def work_remaining(self):
        """Return the value of work not yet billed, retainage excluded."""
        return self.contract_sum() - self.completed_and_stored

    def percent_complete(self):
        """Return completed and stored over the contract sum."""
        total = self.contract_sum()
        if total.is_zero():
            raise DataError("cannot take a percentage of a zero contract sum")
        return Rate(self.completed_and_stored.ratio_to(total))

    def retainage_rate(self):
        """Return retainage held over what has been billed."""
        if self.completed_and_stored.is_zero():
            return Rate(0)
        return Rate(self.total_retainage().ratio_to(self.completed_and_stored))

    def validate(self):
        """Return the problems with this summary, empty when it is sound."""
        problems = []
        if self.completed_and_stored > self.contract_sum():
            problems.append("more has been billed than the contract sum to date")
        if self.total_retainage() > self.completed_and_stored:
            problems.append("retainage held exceeds what has been billed")
        if self.current_payment_due().is_negative():
            problems.append("this application asks for a negative payment")
        if (
            self.work_completed
            and self.stored
            and self.work_completed + self.stored != self.completed_and_stored
        ):
            problems.append("column F does not equal work completed plus stored materials")
        return problems

    def render(self):
        """Return the nine lines as a labelled block.

        >>> from ..core.money import money
        >>> print(ApplicationSummary(money("100000"),
        ...     completed_and_stored=money("25000"),
        ...     retainage_work=money("2500")).render())
        1. Original contract sum          : $100,000.00
        2. Net change by change orders    : $0.00
        3. Contract sum to date           : $100,000.00
        4. Total completed and stored     : $25,000.00
        5. Retainage                      : $2,500.00
        6. Total earned less retainage    : $22,500.00
        7. Less previous certificates     : $0.00
        8. Current payment due            : $22,500.00
        9. Balance to finish plus retainage: $77,500.00
        """
        return key_value_block(
            [
                ("1. Original contract sum", self.original.format()),
                ("2. Net change by change orders", self.change_orders.format()),
                ("3. Contract sum to date", self.contract_sum().format()),
                ("4. Total completed and stored", self.completed_and_stored.format()),
                ("5. Retainage", self.total_retainage().format()),
                ("6. Total earned less retainage", self.earned_less_retainage().format()),
                ("7. Less previous certificates", self.previous_certificates.format()),
                ("8. Current payment due", self.current_payment_due().format()),
                ("9. Balance to finish plus retainage", self.balance_to_finish().format()),
            ],
            width=34,
        )

    def to_dict(self):
        """Return the summary as plain data."""
        return {
            "original": str(self.original.amount),
            "change_orders": str(self.change_orders.amount),
            "contract_sum": str(self.contract_sum().amount),
            "completed_and_stored": str(self.completed_and_stored.amount),
            "work_completed": str(self.work_completed.amount),
            "stored": str(self.stored.amount),
            "retainage_work": str(self.retainage_work.amount),
            "retainage_stored": str(self.retainage_stored.amount),
            "retainage_total": str(self.total_retainage().amount),
            "earned_less_retainage": str(self.earned_less_retainage().amount),
            "previous_certificates": str(self.previous_certificates.amount),
            "previous_basis": self.previous_basis,
            "current_payment_due": str(self.current_payment_due().amount),
            "deductions": str(self.deductions.amount),
            "tax": str(self.tax.amount),
            "released_retainage": str(self.released_retainage.amount),
            "net_payable": str(self.net_payable().amount),
            "balance_to_finish": str(self.balance_to_finish().amount),
        }

    @classmethod
    def from_dict(cls, data, currency="USD"):
        """Rebuild a summary from :meth:`to_dict` output."""
        return cls(
            money(data["original"], currency),
            money(data.get("change_orders", "0"), currency),
            money(data.get("completed_and_stored", "0"), currency),
            money(data.get("work_completed", "0"), currency),
            money(data.get("stored", "0"), currency),
            money(data.get("retainage_work", "0"), currency),
            money(data.get("retainage_stored", "0"), currency),
            money(data.get("previous_certificates", "0"), currency),
            data.get("previous_basis", "certified"),
            money(data.get("deductions", "0"), currency),
            money(data.get("tax", "0"), currency),
            money(data.get("released_retainage", "0"), currency),
        )

    def __eq__(self, other):
        return isinstance(other, ApplicationSummary) and other.to_dict() == self.to_dict()

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("ApplicationSummary", str(self.current_payment_due().amount)))

    def __str__(self):
        return "payment due %s of %s" % (self.current_payment_due(), self.contract_sum())

    def __repr__(self):
        return "ApplicationSummary(due=%s)" % (self.current_payment_due(),)
