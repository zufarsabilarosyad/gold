"""The application-for-payment page, as text.

The layout follows the form everyone in the industry already reads: a header
block identifying the job and the period, the nine summary lines, the change
order recapitulation, and the certification block.  None of it is decorative --
a payment application that does not say which period it covers is a payment
application that gets returned.
"""

from ..core.dates import format_date
from ..core.table import Column, Table, key_value_block
from ..core.text import underline
from ..errors import DataError

__all__ = ["application_header", "change_order_recap", "application_page"]


def application_header(contract, application, project_name=""):
    """Return the identifying block at the head of an application.

    >>> from ..dataio.samples import sample_contract, sample_context
    >>> from ..engine.run import build_application
    >>> context = sample_context(2)
    >>> result = build_application(context, 2, evaluate=False)
    >>> print(application_header(context.contract, result.application))
    Application  : PA-002 (#2)
    Period       : 2024-10-01 to 2024-10-31
    Through      : 2024-10-25
    Contract     : C-2024-118 Harbor Point Phase II -- shell and core
    From         : Keel & Sons Construction
    To           : Harbor Point Holdings LLC
    Status       : draft
    """
    period = application.period
    rows = [
        ("Application", "%s (#%d)" % (application.id, application.number)),
        ("Period", "%s to %s" % (format_date(period.start), format_date(period.end))),
        ("Through", format_date(period.through)),
        (
            "Contract",
            "%s %s" % (contract.id, contract.title) if contract.title else contract.id,
        ),
        ("From", contract.payee.name),
        ("To", contract.payer.name),
        ("Status", application.status),
    ]
    if project_name:
        rows.insert(0, ("Project", project_name))
    return key_value_block(rows, width=13)


def change_order_recap(contract, application, threshold="executed_only"):
    """Return the change-order recapitulation block.

    >>> from ..dataio.samples import sample_context
    >>> from ..engine.run import build_application
    >>> context = sample_context(3)
    >>> result = build_application(context, 3, evaluate=False)
    >>> print(change_order_recap(context.contract, result.application))
    Change order  Status          Value  Effective
    ------------  --------  -----------  ----------
    CO-001        executed   $68,000.00  2024-10-22
    CO-002        directed   $42,000.00  2024-11-12
    CO-003        executed  -$15,000.00  2024-12-16
    ------------  --------  -----------  ----------
    Billable                 $68,000.00
    Pending                  $27,000.00
    """
    period = application.period
    table = Table(
        [
            Column("id", "Change order"),
            Column("status", "Status"),
            Column("value", "Value", "right"),
            Column("effective", "Effective"),
        ]
    )
    for order in contract.change_orders:
        effective = order.effective_date()
        table.add(
            {
                "id": order.id,
                "status": str(order.status),
                "value": order.value(contract.currency).format(),
                "effective": format_date(effective) if effective else "-",
            }
        )
    table.add_separator()
    table.add(
        {
            "id": "Billable",
            "status": "",
            "value": contract.change_order_sum(period.end, threshold).format(),
            "effective": "",
        }
    )
    table.add(
        {
            "id": "Pending",
            "status": "",
            "value": contract.pending_change_orders(period.end, threshold).format(),
            "effective": "",
        }
    )
    return table.render()


def certification_block(application):
    """Return the certification lines at the foot of the page.

    >>> from ..dataio.samples import sample_context
    >>> from ..engine.run import build_application
    >>> result = build_application(sample_context(1), 1, evaluate=False)
    >>> print(certification_block(result.application))
    Submitted    : -
    Certified    : -
    Certified sum: -
    Paid         : -
    """
    return key_value_block(
        [
            ("Submitted", format_date(application.submitted_on) if application.submitted_on else "-"),
            ("Certified", format_date(application.certified_on) if application.certified_on else "-"),
            (
                "Certified sum",
                application.certified_amount.format() if application.certified_amount else "-",
            ),
            ("Paid", format_date(application.paid_on) if application.paid_on else "-"),
        ],
        width=13,
    )


def application_page(contract, result, project_name="", threshold="executed_only"):
    """Return the whole application page.

    >>> from ..dataio.samples import sample_context
    >>> from ..engine.run import build_application
    >>> context = sample_context(2)
    >>> result = build_application(context, 2, evaluate=False)
    >>> page = application_page(context.contract, result)
    >>> page.splitlines()[0]
    'Application for payment'
    >>> '9. Balance to finish plus retainage' in page
    True
    """
    if result.application.summary is None:
        raise DataError("application %s has no summary to print" % (result.application.id,))
    blocks = [
        underline("Application for payment", "="),
        application_header(contract, result.application, project_name),
        underline("Summary", "-") + "\n" + result.summary.render(),
        underline("Change orders", "-") + "\n" + change_order_recap(contract, result.application, threshold),
        underline("Certification", "-") + "\n" + certification_block(result.application),
    ]
    if result.gates is not None and not result.gates.ok():
        blocks.append(
            underline("Payment held", "-")
            + "\n"
            + "\n".join("- %s" % (reason,) for reason in result.gates.reasons())
        )
    return "\n\n".join(blocks)
