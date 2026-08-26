"""Conventions, named and resolvable, so two readings can be run side by side.

The package holds no arithmetic.  It holds the forty-odd decisions the rest of
the code needs made, the profiles that bundle them the way real contracts do,
and the translation into the small options objects each computing module takes.
"""

from .describe import differences_table, explain_knob, policy_report, policy_table
from .knobs import KNOBS, Knob, knob, knob_names
from .profile import PROFILES, describe_profile, profile_names, profile_settings
from .resolve import Policy, resolve

__all__ = [
    "differences_table",
    "explain_knob",
    "policy_report",
    "policy_table",
    "KNOBS",
    "Knob",
    "knob",
    "knob_names",
    "PROFILES",
    "describe_profile",
    "profile_names",
    "profile_settings",
    "Policy",
    "resolve",
]
