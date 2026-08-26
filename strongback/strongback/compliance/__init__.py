"""Documents that gate a payment without changing what is owed.

Insurance certificates, statutory notices and the waiver exchange all have the
same shape: a condition, a date range, and a consequence that is a hold rather
than a deduction.  Keeping them out of the money makes the closeout arithmetic
tractable -- what was held for a lapsed certificate is still owed once the
certificate arrives.
"""

from .gate import GateResult, evaluate_gates
from .insurance import Certificate, InsuranceFile, coverage_gaps
from .notice import Notice, NoticeRegister, NoticeRule, deadline_for

__all__ = [
    "GateResult",
    "evaluate_gates",
    "Certificate",
    "InsuranceFile",
    "coverage_gaps",
    "Notice",
    "NoticeRegister",
    "NoticeRule",
    "deadline_for",
]
