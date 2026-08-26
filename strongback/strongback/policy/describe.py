"""Rendering a policy so a project manager can check it against the contract.

The output is deliberately plain: one row per setting, its value, where the
value came from, and the sentence explaining what it does.  A policy that
cannot be read against a contract is a policy nobody will notice is wrong.
"""

from ..core.table import Column, Table
from ..core.text import indent, title_case, wrap
from .knobs import KNOBS, groups, knob, knob_names

__all__ = ["policy_table", "policy_report", "explain_knob", "differences_table"]


def policy_table(policy, group=None, changed_only=False):
    """Render a policy's settings as a table.

    >>> from .resolve import Policy
    >>> print(policy_table(Policy("owner_favorable"), group="stored"))
    Setting                   Value         Source
    ------------------------  ------------  -------
    stored_conversion         proportional  profile
    stored_cap                50%           profile
    stored_allow_offsite      False         profile
    stored_require_insurance  True          default
    """
    table = Table(
        [
            Column("setting", "Setting"),
            Column("value", "Value"),
            Column("source", "Source"),
        ]
    )
    for name in knob_names(group):
        if changed_only and policy.source(name) == "default":
            continue
        table.add(
            {
                "setting": name,
                "value": str(policy.get(name)),
                "source": policy.source(name),
            }
        )
    return table.render()


def policy_report(policy, changed_only=False):
    """Render every group of a policy under headings.

    >>> from .resolve import Policy
    >>> report = policy_report(Policy("public_works"), changed_only=True)
    >>> "Retainage" in report
    True
    """
    blocks = []
    for group in groups():
        rendered = policy_table(policy, group, changed_only)
        if len(rendered.splitlines()) <= 2:
            continue
        blocks.append("%s\n%s" % (title_case(group.replace("_", " ")), indent(rendered)))
    header = "Policy %s%s" % (
        policy.name,
        " (profile %s)" % (policy.profile,) if policy.profile else "",
    )
    return "\n\n".join([header] + blocks)


def explain_knob(name, width=72):
    """Return a paragraph explaining one knob.

    >>> print(explain_knob("previous_basis"))
    previous_basis (billing)
      whether line 7 quotes what was certified or what was actually paid
      allowed: certified, paid
      default: certified
    """
    definition = knob(name)
    lines = ["%s (%s)" % (definition.name, definition.group)]
    for line in wrap(definition.doc, width - 2):
        lines.append("  " + line)
    if definition.values:
        lines.append("  allowed: %s" % (", ".join(str(value) for value in definition.values),))
    lines.append("  default: %s" % (definition.default,))
    return "\n".join(lines)


def differences_table(first, second, first_label="first", second_label="second"):
    """Render the settings two policies disagree on.

    >>> from .resolve import Policy
    >>> print(differences_table(Policy("aia_standard"), Policy("lender_draw"),
    ...                         "aia", "lender"))
    Setting            aia               lender
    -----------------  ----------------  ----------------
    stored_conversion  explicit          on_completion
    previous_basis     certified         paid
    allocation_order   oldest_first      specified
    aging_basis        due_date          application_date
    waiver_exchange    with_application  before_payment
    """
    table = Table(
        [
            Column("setting", "Setting"),
            Column("first", first_label),
            Column("second", second_label),
        ]
    )
    changed = first.differences(second)
    for name in knob_names():
        if name not in changed:
            continue
        left, right = changed[name]
        table.add({"setting": name, "first": str(left), "second": str(right)})
    return table.render()
