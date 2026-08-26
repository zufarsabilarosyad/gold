"""The knobs, in one place, with their allowed values and what they mean.

Every convention this package implements is reachable from here.  That is the
point: a run is a contract plus a policy, and two runs that differ are two
policies that differ, which ``strongback compare`` can price.

A knob has a name, a set of allowed values (or a type), a default, and a
sentence saying what turning it does.  The sentence is not documentation for
its own sake -- ``strongback policy explain`` prints it, and a project manager
reading the output should be able to tell whether the setting matches their
contract.
"""

from ..errors import InputError, PolicyError

__all__ = ["Knob", "KNOBS", "knob", "knob_names", "validate_value", "knobs_in_group"]


class Knob:
    """One setting: its allowed values, its default and its effect.

    >>> setting = Knob("rounding_stage", ("line", "summary"), "line",
    ...                "where money is rounded", group="billing")
    >>> setting.validate("line")
    'line'
    >>> setting.validate("nowhere")
    Traceback (most recent call last):
        ...
    strongback.errors.PolicyError: rounding_stage cannot be 'nowhere'; allowed: line, summary
    """

    __slots__ = ("name", "values", "default", "doc", "group", "kind")

    def __init__(self, name, values, default, doc, group="general", kind="choice"):
        self.name = str(name)
        self.values = tuple(values) if values else ()
        self.default = default
        self.doc = str(doc)
        self.group = str(group)
        if str(kind) not in ("choice", "boolean", "number", "rate", "text"):
            raise InputError("unknown knob kind %r" % (kind,))
        self.kind = str(kind)

    def validate(self, value):
        """Return the value if it is allowed, raising otherwise."""
        if self.kind == "boolean":
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in ("true", "yes", "1"):
                return True
            if text in ("false", "no", "0"):
                return False
            raise PolicyError("%s must be a boolean, got %r" % (self.name, value))
        if self.kind == "number":
            try:
                return int(value)
            except (TypeError, ValueError):
                raise PolicyError("%s must be a whole number, got %r" % (self.name, value))
        if self.kind in ("rate", "text"):
            if value is None:
                return None
            return str(value)
        if self.values and value not in self.values:
            raise PolicyError(
                "%s cannot be %r; allowed: %s" % (self.name, value, ", ".join(self.values))
            )
        return value

    def to_dict(self):
        """Return the knob's definition as plain data."""
        return {
            "name": self.name,
            "values": list(self.values),
            "default": self.default,
            "doc": self.doc,
            "group": self.group,
            "kind": self.kind,
        }

    def __repr__(self):
        return "Knob(%r, default=%r)" % (self.name, self.default)


_DEFINITIONS = (
    # progress
    Knob("over_hundred", ("clamp", "allow", "error"), "clamp",
         "what to do when a line reports more than a hundred percent complete",
         "progress"),
    Knob("negative_progress", ("clamp", "allow"), "clamp",
         "whether a line may go backwards, correcting an earlier over-billing",
         "progress"),
    Knob("milestone_rule", ("event_only", "line_percent"), "event_only",
         "whether a milestone line may bill partial credit before the event",
         "progress"),
    Knob("unit_overrun_rule", ("rate", "capped", "threshold"), "rate",
         "how quantity measured beyond the estimate is billed", "progress"),
    Knob("unit_overrun_threshold", (), "15%",
         "the variance a threshold overrun rule allows before capping",
         "progress", "rate"),
    # stored materials
    Knob("stored_conversion", ("explicit", "proportional", "on_completion"), "explicit",
         "how stored material becomes work in place", "stored"),
    Knob("stored_cap", (), None,
         "ceiling on stored material as a share of the line's scheduled value",
         "stored", "rate"),
    Knob("stored_allow_offsite", (), False,
         "whether material stored away from the site may be billed", "stored", "boolean"),
    Knob("stored_require_insurance", (), True,
         "whether stored material must be insured to be billed", "stored", "boolean"),
    # retainage
    Knob("retainage_round_stage", ("line", "summary", "none"), "line",
         "whether retainage is rounded per line or once on the summary",
         "retainage"),
    Knob("retainage_rounding", ("half_up", "half_even", "down", "up"), "half_up",
         "the rounding mode applied to retainage", "retainage"),
    Knob("retainage_places", (), 2, "decimal places retainage is rounded to",
         "retainage", "number"),
    Knob("retainage_apply_cap", (), True,
         "whether the contract's retainage ceiling is enforced", "retainage", "boolean"),
    Knob("stepdown_certification", (), True,
         "whether a step-down requiring certification is treated as certified",
         "retainage", "boolean"),
    Knob("early_release_allowed", (), False,
         "whether a finished line's retainage may be released before closeout",
         "retainage", "boolean"),
    # billing
    Knob("change_order_threshold", ("executed_only", "approved", "directed", "proposed"),
         "executed_only", "which change orders may appear on an application", "billing"),
    Knob("previous_basis", ("certified", "paid"), "certified",
         "whether line 7 quotes what was certified or what was actually paid",
         "billing"),
    Knob("line_rounding", ("half_up", "half_even", "down", "up"), "half_up",
         "the rounding mode applied to continuation-sheet lines", "billing"),
    Knob("line_places", (), 2, "decimal places a continuation line is rounded to",
         "billing", "number"),
    Knob("numbering_scheme", ("sequential", "period", "prefixed"), "sequential",
         "how applications are numbered", "billing"),
    Knob("allow_overbilling", (), False,
         "whether a line may bill past its scheduled value", "billing", "boolean"),
    # deductions
    Knob("backcharge_stage", ("gross", "net", "retainage"), "net",
         "the default stage at which a back-charge lands", "deductions"),
    Knob("backcharge_allow_disputed", (), False,
         "whether a disputed back-charge is still deducted", "deductions", "boolean"),
    Knob("tax_material_share", (), "40%",
         "the share of work treated as material where tax is material-only",
         "deductions", "rate"),
    Knob("allowance_markup_rule", ("included", "on_difference", "on_actual"),
         "on_difference", "how markup applies when an allowance reconciles",
         "deductions"),
    # payments
    Knob("allocation_order", ("oldest_first", "newest_first", "pro_rata", "specified"),
         "oldest_first", "how a receipt is applied across open applications", "payments"),
    Knob("aging_basis", ("due_date", "application_date", "period_end"), "due_date",
         "the event an aging report counts from", "payments"),
    Knob("due_roll", ("none", "forward", "backward"), "forward",
         "how a due date landing on a non-working day moves", "payments"),
    Knob("longstop_days", (), 90,
         "days after which a pay-when-paid obligation matures anyway", "payments", "number"),
    Knob("pay_if_paid_enforceable", (), True,
         "whether a pay-if-paid clause is honoured in this jurisdiction",
         "payments", "boolean"),
    Knob("joint_check_credit", ("full", "net"), "full",
         "how much of a joint cheque counts against the payee's balance", "payments"),
    Knob("interest_day_count", ("actual_365", "actual_360", "thirty_360"), "actual_365",
         "the day-count basis for late-payment interest", "payments"),
    Knob("interest_compounding", ("simple", "monthly"), "simple",
         "whether late-payment interest compounds", "payments"),
    # waivers and compliance
    Knob("waiver_exchange", ("with_application", "before_payment", "after_payment", "none"),
         "with_application", "when a waiver is exchanged for payment", "waivers"),
    Knob("waiver_through_rule", ("period_end", "application_through", "payment_date"),
         "period_end", "the date a waiver has to reach", "waivers"),
    Knob("waiver_require_notarised", (), False,
         "whether waivers must be notarised to be accepted", "waivers", "boolean"),
    Knob("waiver_allow_exceptions", (), False,
         "whether a waiver may except claims from its release", "waivers", "boolean"),
    Knob("gate_on_insurance", (), True,
         "whether lapsed insurance blocks a payment", "waivers", "boolean"),
    # work in progress
    Knob("wip_percent_basis", ("cost", "billing"), "cost",
         "whether percent complete for the WIP report comes from cost or billing",
         "wip"),
    Knob("wip_forecast_method", ("remaining_budget", "trend", "manual"), "remaining_budget",
         "how the cost to complete is forecast", "wip"),
    Knob("overbilling_basis", ("earned_cost", "earned_percent"), "earned_cost",
         "the earned-revenue figure over- and under-billing is measured against",
         "wip"),
)

KNOBS = {definition.name: definition for definition in _DEFINITIONS}


def knob(name):
    """Return one knob definition by name.

    >>> knob("previous_basis").default
    'certified'
    """
    key = str(name)
    if key not in KNOBS:
        raise PolicyError("unknown policy knob %r" % (name,))
    return KNOBS[key]


def knob_names(group=None):
    """Return the knob names, optionally in one group, in definition order.

    >>> knob_names("wip")
    ['wip_percent_basis', 'wip_forecast_method', 'overbilling_basis']
    """
    return [
        definition.name
        for definition in _DEFINITIONS
        if group is None or definition.group == str(group)
    ]


def knobs_in_group(group):
    """Return the knob definitions in one group.

    >>> [item.name for item in knobs_in_group("stored")][:2]
    ['stored_conversion', 'stored_cap']
    """
    return [definition for definition in _DEFINITIONS if definition.group == str(group)]


def validate_value(name, value):
    """Validate one setting against its knob definition.

    >>> validate_value("retainage_places", "3")
    3
    """
    return knob(name).validate(value)


def groups():
    """Return the knob groups in definition order.

    >>> groups()[:3]
    ['progress', 'stored', 'retainage']
    """
    seen = []
    for definition in _DEFINITIONS:
        if definition.group not in seen:
            seen.append(definition.group)
    return seen
