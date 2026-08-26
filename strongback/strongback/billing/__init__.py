"""Producing the document: the continuation sheet and the summary page.

This package assembles; it does not decide.  The values on a row arrive from
the progress and retainage packages, and the engine is what puts them together.
Keeping the assembly free of judgement is what makes an application
reproducible from its inputs, and what makes two policies comparable on the
same job.
"""

from .application import ApplicationRegister, PayApplication
from .continuation import ContinuationSheet
from .line import ApplicationLine
from .numbering import format_application_id, next_number, revision_id
from .revision import Revision, RevisionChain
from .summary import ApplicationSummary

__all__ = [
    "ApplicationRegister",
    "PayApplication",
    "ContinuationSheet",
    "ApplicationLine",
    "format_application_id",
    "next_number",
    "revision_id",
    "Revision",
    "RevisionChain",
    "ApplicationSummary",
]
