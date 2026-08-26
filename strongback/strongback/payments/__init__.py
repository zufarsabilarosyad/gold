"""Getting paid: when it is due, what arrived, what it paid for, and how late.

The order of the modules is the order of the questions.  A due date comes from
the terms and a calendar; a receipt is what actually landed; allocation decides
which application it cleared; aging and interest describe the gap in between.
Pay-chain clauses sit across all of them, because they change the due date
without changing anything else.
"""

from .aging import age_applications, aging_table
from .allocation import Allocation, allocate_receipt, open_balances
from .chain import ChainOutcome, chain_due_date, chain_status
from .due import days_late, due_date, is_late
from .interest import InterestTerms, accrue_interest
from .jointcheck import JointCheck, credited_to_payee, split_joint_check
from .receipt import Receipt, ReceiptLedger

__all__ = [
    "age_applications",
    "aging_table",
    "Allocation",
    "allocate_receipt",
    "open_balances",
    "ChainOutcome",
    "chain_due_date",
    "chain_status",
    "days_late",
    "due_date",
    "is_late",
    "InterestTerms",
    "accrue_interest",
    "JointCheck",
    "credited_to_payee",
    "split_joint_check",
    "Receipt",
    "ReceiptLedger",
]
