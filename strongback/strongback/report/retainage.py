"""Retainage reports: what is held, against what, and when it comes back.

Three views, because three people ask.  The project manager wants it by line.
The controller wants the movement this period.  The subcontractor wants the
release schedule -- what comes back at substantial completion, what is held for
the punchlist, and what waits for final.
"""

from ..core.money import zero
from ..core.table import Column, Table, key_value_block
from ..core.text import underline
from ..errors import DataError
from ..retainage.release import punchlist_holdback, substantial_completion_release

__all__ = ["retainage_by_line", "retainage_movement", "release_schedule", "retainage_report"]


def retainage_by_line(result):
    """Render retainage held per line.

    >>> from ..dataio.samples import sample_context
    >>> from ..engine.run import build_application
    >>> result = build_application(sample_context(2), 2, evaluate=False)
    >>> print(retainage_by_line(result).splitlines()[0])
    Item   Description           Completed  Rate        Held    Movement
    """
    table = Table(
        [
            Column("code", "Item"),
            Column("description", "Description", width=24),
            Column("completed", "Completed", "right"),
            Column("rate", "Rate"),
            Column("held", "Held", "right"),
            Column("movement", "Movement", "right"),
        ]
    )
    for line in result.sheet.ordered():
        if line.retainage.is_zero() and line.retainage_this_period().is_zero():
            continue
        table.add(
            {
                "code": line.code,
                "description": line.description,
                "completed": line.completed_and_stored().format(),
                "rate": str(line.rate) if line.rate else "-",
                "held": line.retainage.format(),
                "movement": line.retainage_this_period().format(parens_for_negative=True),
            }
        )
    table.add_separator()
    table.add(
        {
            "code": "",
            "description": "Total",
            "completed": result.sheet.total_completed_and_stored().format(),
            "rate": "",
            "held": result.sheet.total_retainage().format(),
            "movement": (
                result.sheet.total_retainage() - result.sheet.total_previous_retainage()
            ).format(parens_for_negative=True),
        }
    )
    return table.render()


def retainage_movement(results):
    """Render the retainage balance period by period.

    >>> from ..dataio.samples import sample_context
    >>> from ..engine.run import run_contract
    >>> results = run_contract(sample_context(3))
    >>> print(retainage_movement(results))
    Period  Completed      Held         Movement
    ------  -------------  -----------  ----------
         1  $146,600.00    $14,660.00   $14,660.00
         2  $487,900.00    $48,790.00   $34,130.00
         3  $1,114,900.00  $111,490.00  $62,700.00
    """
    table = Table(
        [
            Column("period", "Period", "right"),
            Column("completed", "Completed"),
            Column("held", "Held"),
            Column("movement", "Movement"),
        ]
    )
    previous = None
    for result in results:
        held = result.sheet.total_retainage()
        movement = held if previous is None else held - previous
        table.add(
            {
                "period": result.application.number,
                "completed": result.sheet.total_completed_and_stored().format(),
                "held": held.format(),
                "movement": movement.format(parens_for_negative=True),
            }
        )
        previous = held
    return table.render()


def release_schedule(contract, held, punchlist_value=None):
    """Render what comes back and when.

    >>> from ..core.money import money
    >>> from ..dataio.samples import sample_contract
    >>> print(release_schedule(sample_contract(), money("101225"), money("40000")))
    Held now                 : $101,225.00
    At substantial completion: $41,225.00
    Punchlist holdback       : $60,000.00
    Held to final            : $60,000.00
    Final release            : 30 days after final completion
    """
    released, remaining = substantial_completion_release(
        held, contract.retainage, punchlist_value
    )
    holdback = (
        punchlist_holdback(punchlist_value, contract.retainage)
        if punchlist_value is not None
        else zero(held.currency)
    )
    return key_value_block(
        [
            ("Held now", held.format()),
            ("At substantial completion", released.format()),
            ("Punchlist holdback", holdback.format()),
            ("Held to final", remaining.format()),
            (
                "Final release",
                "%d days after final completion" % (contract.retainage.final_release_days,),
            ),
        ],
        width=25,
    )


def retainage_report(contract, result, punchlist_value=None):
    """Render the whole retainage report for one application.

    >>> from ..dataio.samples import sample_context
    >>> from ..engine.run import build_application
    >>> context = sample_context(2)
    >>> result = build_application(context, 2, evaluate=False)
    >>> print(retainage_report(context.contract, result).splitlines()[0])
    Retainage
    """
    blocks = [
        underline("Retainage", "="),
        key_value_block(
            [
                ("Clause", contract.retainage.describe()),
                ("Held to date", result.sheet.total_retainage().format()),
                ("On work", result.sheet.retainage_on_work().rounded().format()),
                ("On stored materials", result.sheet.retainage_on_stored().rounded().format()),
            ],
            width=20,
        ),
        underline("By line", "-") + "\n" + retainage_by_line(result),
        underline("Release", "-")
        + "\n"
        + release_schedule(contract, result.sheet.total_retainage(), punchlist_value),
    ]
    return "\n\n".join(blocks)
