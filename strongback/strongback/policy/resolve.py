"""The policy object: a profile, the overrides on top of it, and the options
objects the rest of the package actually consumes.

Two things are deliberate here.

First, a policy remembers *where each setting came from* -- default, profile or
override.  When two runs disagree, the useful report is not "these values
differ" but "these values differ, and this one was an override you set".

Second, the policy does not leak into the computation.  It builds the small
options objects the progress, stored and retainage modules take, and those
modules never import policy.  That inversion is what lets the same ledger be
valued twice under two policies in one process.
"""

from ..errors import PolicyError
from ..progress.method import ProgressOptions
from ..progress.stored import StoredOptions
from ..retainage.accrual import RetainageOptions
from ..waivers.requirement import WaiverRequirement
from .knobs import KNOBS, groups, knob, knob_names
from .profile import PROFILES, profile_settings

__all__ = ["Policy", "resolve"]

SOURCES = ("default", "profile", "override")


class Policy:
    """A resolved set of conventions, with provenance for each setting.

    >>> policy = Policy()
    >>> policy.get("previous_basis")
    'certified'
    >>> policy.source("previous_basis")
    'default'
    >>> owner = Policy("owner_favorable", {"stored_cap": "40%"})
    >>> owner.get("stored_cap"), owner.source("stored_cap")
    ('40%', 'override')
    >>> owner.get("waiver_exchange"), owner.source("waiver_exchange")
    ('before_payment', 'profile')
    """

    __slots__ = ("name", "profile", "settings", "sources")

    def __init__(self, profile=None, overrides=None, name=""):
        self.profile = str(profile) if profile else ""
        self.name = str(name) or (self.profile or "default")
        self.settings = {}
        self.sources = {}
        for setting in knob_names():
            self.settings[setting] = KNOBS[setting].default
            self.sources[setting] = "default"
        if self.profile:
            for setting, value in profile_settings(self.profile).items():
                self.settings[setting] = value
                self.sources[setting] = "profile"
        for setting, value in dict(overrides or {}).items():
            self.set(setting, value)

    def set(self, setting, value):
        """Override one setting, validating it against its knob."""
        definition = knob(setting)
        self.settings[definition.name] = definition.validate(value)
        self.sources[definition.name] = "override"
        return self

    def get(self, setting):
        """Return one setting's value."""
        definition = knob(setting)
        return self.settings[definition.name]

    def source(self, setting):
        """Return where a setting's value came from."""
        return self.sources[knob(setting).name]

    def flag(self, setting):
        """Return a boolean setting."""
        value = self.get(setting)
        return bool(value)

    def number(self, setting):
        """Return a whole-number setting."""
        return int(self.get(setting))

    def overrides(self):
        """Return only the settings that were overridden."""
        return {
            setting: value
            for setting, value in sorted(self.settings.items())
            if self.sources[setting] == "override"
        }

    def differences(self, other):
        """Return the settings two policies disagree on.

        >>> first, second = Policy("owner_favorable"), Policy("subcontractor_favorable")
        >>> first.differences(second)["backcharge_stage"]
        ('gross', 'net')
        """
        changed = {}
        for setting in knob_names():
            mine = self.get(setting)
            theirs = other.get(setting)
            if mine != theirs:
                changed[setting] = (mine, theirs)
        return changed

    def group(self, name):
        """Return the settings in one knob group.

        >>> sorted(Policy().group("wip"))
        ['overbilling_basis', 'wip_forecast_method', 'wip_percent_basis']
        """
        return {setting: self.get(setting) for setting in knob_names(name)}

    def progress_options(self):
        """Return the options the progress package takes.

        >>> Policy("owner_favorable").progress_options().over_hundred
        'error'
        """
        return ProgressOptions(
            over_hundred=self.get("over_hundred"),
            negative=self.get("negative_progress"),
            milestone_rule=self.get("milestone_rule"),
            overrun_rule=self.get("unit_overrun_rule"),
            overrun_threshold=self.get("unit_overrun_threshold"),
            value_places=self.number("line_places"),
        )

    def stored_options(self):
        """Return the options the stored-materials module takes.

        >>> Policy("lender_draw").stored_options().conversion
        'on_completion'
        """
        return StoredOptions(
            conversion=self.get("stored_conversion"),
            cap=self.get("stored_cap"),
            allow_offsite=self.flag("stored_allow_offsite"),
            require_insurance=self.flag("stored_require_insurance"),
        )

    def retainage_options(self):
        """Return the options the retainage accrual takes.

        >>> Policy().retainage_options().round_stage
        'line'
        """
        return RetainageOptions(
            places=self.number("retainage_places"),
            rounding=self.get("retainage_rounding"),
            round_stage=self.get("retainage_round_stage"),
            apply_cap=self.flag("retainage_apply_cap"),
            certified_stepdowns=self.flag("stepdown_certification"),
        )

    def waiver_requirement(self):
        """Return the waiver requirement this policy implies.

        >>> Policy("owner_favorable").waiver_requirement().exchange
        'before_payment'
        """
        return WaiverRequirement(
            exchange=self.get("waiver_exchange"),
            through_rule=self.get("waiver_through_rule"),
            require_notarised=self.flag("waiver_require_notarised"),
            allow_exceptions=self.flag("waiver_allow_exceptions"),
        )

    def to_dict(self, only_overrides=False):
        """Return the policy as plain data."""
        settings = self.overrides() if only_overrides else dict(self.settings)
        return {
            "name": self.name,
            "profile": self.profile,
            "settings": {key: settings[key] for key in sorted(settings)},
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild a policy from :meth:`to_dict` output.

        >>> policy = Policy.from_dict({"profile": "public_works",
        ...                            "settings": {"stored_cap": "60%"}})
        >>> policy.get("stored_cap")
        '60%'
        """
        return cls(data.get("profile") or None, data.get("settings", {}), data.get("name", ""))

    def __eq__(self, other):
        return isinstance(other, Policy) and other.settings == self.settings

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(("Policy", tuple(sorted(self.settings.items(), key=lambda item: item[0]))))

    def __len__(self):
        return len(self.settings)

    def __contains__(self, setting):
        return str(setting) in self.settings

    def __getitem__(self, setting):
        return self.get(setting)

    def __repr__(self):
        return "Policy(%r, %d overrides)" % (self.name, len(self.overrides()))


def resolve(profile=None, overrides=None, contract=None, name=""):
    """Build a policy, taking what the contract already states into account.

    A contract that names a change-order billing threshold has already decided
    that knob, and the policy should not quietly disagree with it.

    >>> policy = resolve("aia_standard")
    >>> policy.get("change_order_threshold")
    'executed_only'
    """
    policy = Policy(profile, overrides, name)
    if contract is not None:
        threshold = getattr(contract, "billable_threshold", None)
        if threshold and "change_order_threshold" not in (overrides or {}):
            policy.settings["change_order_threshold"] = knob(
                "change_order_threshold"
            ).validate(threshold)
            policy.sources["change_order_threshold"] = "profile"
    return policy
