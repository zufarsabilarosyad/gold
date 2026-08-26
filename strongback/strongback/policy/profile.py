"""Named policies: the five ways this gets set up in practice.

A profile is a starting point, not a straitjacket -- every knob can be
overridden.  What the profiles capture is that the settings are *correlated*.
An owner who insists on executed-only change orders is also the owner who wants
stored materials retained and offsite storage refused; a subcontractor-friendly
agreement tends to pair a retroactive step-down with a waiver exchange that
follows payment rather than preceding it.

The profiles are named after who wrote the contract, because that is what
actually predicts the settings.
"""

from ..errors import PolicyError
from .knobs import KNOBS, knob

__all__ = ["PROFILES", "profile_settings", "profile_names", "describe_profile"]

PROFILES = {
    "aia_standard": {
        "_doc": "the standard general-conditions reading: executed changes, "
                "prospective step-downs, conditional waiver with the application",
        "change_order_threshold": "executed_only",
        "previous_basis": "certified",
        "stored_conversion": "explicit",
        "waiver_exchange": "with_application",
        "waiver_through_rule": "period_end",
        "retainage_round_stage": "line",
        "allocation_order": "oldest_first",
    },
    "owner_favorable": {
        "_doc": "everything that can wait, waits: nothing bills before it is "
                "executed, stored material is capped and onsite only, and the "
                "unconditional waiver comes before the cheque",
        "change_order_threshold": "executed_only",
        "previous_basis": "certified",
        "stored_conversion": "proportional",
        "stored_cap": "50%",
        "stored_allow_offsite": False,
        "waiver_exchange": "before_payment",
        "waiver_require_notarised": True,
        "waiver_allow_exceptions": False,
        "over_hundred": "error",
        "unit_overrun_rule": "capped",
        "backcharge_stage": "gross",
        "retainage_apply_cap": False,
        "gate_on_insurance": True,
    },
    "subcontractor_favorable": {
        "_doc": "the sub's reading: directives bill, offsite storage counts, the "
                "unconditional waiver follows the money, and interest runs on a "
                "360-day year",
        "change_order_threshold": "directed",
        "previous_basis": "paid",
        "stored_conversion": "explicit",
        "stored_allow_offsite": True,
        "waiver_exchange": "after_payment",
        "waiver_allow_exceptions": True,
        "backcharge_stage": "net",
        "backcharge_allow_disputed": False,
        "early_release_allowed": True,
        "pay_if_paid_enforceable": False,
        "interest_day_count": "actual_360",
        "unit_overrun_rule": "rate",
    },
    "public_works": {
        "_doc": "statutory work: capped retainage, prompt-payment interest with a "
                "grace period, notarised waivers and no offsite storage",
        "change_order_threshold": "approved",
        "previous_basis": "paid",
        "retainage_apply_cap": True,
        "stored_allow_offsite": False,
        "stored_cap": "75%",
        "waiver_exchange": "with_application",
        "waiver_require_notarised": True,
        "unit_overrun_rule": "threshold",
        "unit_overrun_threshold": "25%",
        "interest_day_count": "actual_365",
        "aging_basis": "due_date",
        "pay_if_paid_enforceable": False,
    },
    "lender_draw": {
        "_doc": "a construction loan draw: nothing unfunded bills, stored material "
                "must be insured, waivers gate the draw and the aging runs from "
                "the application date",
        "change_order_threshold": "executed_only",
        "previous_basis": "paid",
        "stored_conversion": "on_completion",
        "stored_require_insurance": True,
        "stored_allow_offsite": False,
        "waiver_exchange": "before_payment",
        "aging_basis": "application_date",
        "allocation_order": "specified",
        "gate_on_insurance": True,
        "allow_overbilling": False,
    },
}


def profile_names():
    """Return the profile names in alphabetical order.

    >>> profile_names()
    ['aia_standard', 'lender_draw', 'owner_favorable', 'public_works', 'subcontractor_favorable']
    """
    return sorted(PROFILES)


def profile_settings(name):
    """Return one profile's settings, validated against the knobs.

    >>> profile_settings("owner_favorable")["stored_cap"]
    '50%'
    >>> try:
    ...     profile_settings("nope")
    ... except PolicyError as error:
    ...     print(str(error).split(";")[0])
    unknown profile 'nope'
    """
    key = str(name)
    if key not in PROFILES:
        raise PolicyError(
            "unknown profile %r; known: %s" % (name, ", ".join(profile_names()))
        )
    settings = {}
    for setting, value in PROFILES[key].items():
        if setting.startswith("_"):
            continue
        settings[setting] = knob(setting).validate(value)
    return settings


def describe_profile(name):
    """Return a profile's one-line rationale.

    >>> describe_profile("aia_standard").startswith("the standard")
    True
    """
    key = str(name)
    if key not in PROFILES:
        raise PolicyError("unknown profile %r" % (name,))
    return PROFILES[key].get("_doc", "")


def profile_differences(first, second):
    """Return the knobs two profiles set differently.

    >>> differences = profile_differences("owner_favorable", "subcontractor_favorable")
    >>> differences["waiver_exchange"]
    ('before_payment', 'after_payment')
    """
    left = profile_settings(first)
    right = profile_settings(second)
    names = sorted(set(left) | set(right))
    changed = {}
    for name in names:
        default = KNOBS[name].default
        first_value = left.get(name, default)
        second_value = right.get(name, default)
        if first_value != second_value:
            changed[name] = (first_value, second_value)
    return changed
