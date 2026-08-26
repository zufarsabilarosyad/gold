"""The closeout report: everything still open when the building is finished.

Closeout is where a job's loose ends become money.  Retainage still held,
punchlist work not done, conditional waivers never converted, an insurance
certificate that expired before the warranty period, a lien nobody bonded off.
The report is a checklist with amounts against it, because a checklist without
amounts gets deferred and one with amounts gets a meeting.
"""

from ..core.dates import format_date
from ..core.money import zero
from ..core.table import Column, Table, key_value_block
from ..core.text import bullet_list, underline
from ..retainage.release import final_release, substantial_completion_release

__all__ = ["closeout_items", "closeout_report", "outstanding_documents"]


def outstanding_documents(context, paid_applications=()):
    """Return the documents still missing at closeout.

    >>> from ..dataio.samples import sample_context
    >>> outstanding_documents(sample_context(2), ["PA-001"])
    ['unconditional waiver for PA-002', 'unconditional waiver for PA-003']
    """
    missing = []
    for waiver in context.waivers.pending_conditional(paid_applications):
        missing.append("unconditional waiver for %s" % (waiver.application_id or waiver.id,))
    if context.notices is not None and context.notice_events:
        for kind in context.notices.missing(context.notice_events):
            missing.append("timely %s notice" % (kind,))
    for offset in context.offsets.open_at(len(context.periods)):
        if offset.is_reversible():
            missing.append("release of the %s offset %s" % (offset.kind, offset.id))
    return missing


def closeout_items(context, held, punchlist_value=None, deductions=None):
    """Return the closeout figures as ordered pairs.

    >>> from ..core.money import money
    >>> from ..dataio.samples import sample_context
    >>> items = dict(closeout_items(sample_context(4), money("100000"), money("40000")))
    >>> items["Retainage held"]
    '$100,000.00'
    >>> items["Punchlist holdback"]
    '$60,000.00'
    """
    contract = context.contract
    currency = held.currency
    released, remaining = substantial_completion_release(
        held, contract.retainage, punchlist_value
    )
    deductions = deductions if deductions is not None else zero(currency)
    final, withheld = final_release(remaining, deductions)
    rows = [
        ("Contract", "%s %s" % (contract.id, contract.title)),
        ("Retainage held", held.format()),
        ("Released at substantial completion", released.format()),
        ("Punchlist holdback", (held - released).format()),
        ("Final deductions", deductions.format()),
        ("Final release", final.format()),
        ("Withheld at final", withheld.format()),
    ]
    if contract.completion.substantial_completion:
        rows.append(
            ("Substantial completion", format_date(contract.completion.substantial_completion))
        )
    if contract.completion.final_completion:
        rows.append(("Final completion", format_date(contract.completion.final_completion)))
    return rows


def closeout_report(context, held, punchlist_value=None, deductions=None, paid_applications=()):
    """Render the closeout report.

    >>> from ..core.money import money
    >>> from ..dataio.samples import sample_context
    >>> report = closeout_report(sample_context(4), money("100000"), money("40000"))
    >>> report.splitlines()[0]
    'Closeout'
    >>> 'Outstanding documents' in report
    True
    """
    blocks = [
        underline("Closeout", "="),
        key_value_block(closeout_items(context, held, punchlist_value, deductions), width=35),
        underline("Outstanding documents", "-")
        + "\n"
        + bullet_list(outstanding_documents(context, paid_applications)),
    ]
    offsets = context.offsets.open_at(len(context.periods))
    if offsets:
        table = Table(
            [
                Column("id", "Offset"),
                Column("kind", "Kind"),
                Column("amount", "Amount", "right"),
                Column("reversible", "Reversible"),
            ]
        )
        for offset in offsets:
            table.add(
                {
                    "id": offset.id,
                    "kind": offset.kind,
                    "amount": offset.amount.format(),
                    "reversible": "yes" if offset.is_reversible() else "no",
                }
            )
        blocks.append(underline("Open offsets", "-") + "\n" + table.render())
    return "\n\n".join(blocks)
