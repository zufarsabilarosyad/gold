//! What the intake will and will not accept, stated once in one place.
//!
//! `from_str_radix` hard-codes its answers: underscores are skipped wherever
//! they appear, whitespace is a bad digit, a sign is a bad digit, uppercase is
//! always fine. Those are reasonable defaults but they are invisible — no
//! caller can ask what they are, and none can tighten them for input that
//! arrived from somewhere untrusted.
//!
//! [`Policy`] turns each answer into a field. It is plain data with public
//! fields and no invariants, so a caller starts from a preset and flips one
//! thing without a builder ceremony; deciding is done by the passes. The
//! important preset is [`Policy::strict`], which reproduces exactly what
//! `from_str_radix` accepts today, down to accepting `"_1__2_"`. That is what
//! makes the subsystem adoptable: wrapping the existing parser in a strict
//! intake changes no behaviour, only how much a failure can say.

/// Which characters may separate digit groups.
///
/// A four-bit set rather than a `Vec<char>`: the legal alphabet is known at
/// compile time, membership is a mask test on the scanner's hot path, and the
/// set stays `Copy` so a [`Policy`] can be passed by value.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct SeparatorSet(u8);

impl SeparatorSet {
    /// No separators at all: every non-digit is junk.
    pub const NONE: SeparatorSet = SeparatorSet(0);
    /// `_`, the separator Rust's own integer literals use.
    pub const UNDERSCORE: SeparatorSet = SeparatorSet(1);
    /// `,`, the thousands separator of English prose.
    pub const COMMA: SeparatorSet = SeparatorSet(2);
    /// `'`, the digit separator of C++ and of Swiss typography.
    pub const APOSTROPHE: SeparatorSet = SeparatorSet(4);
    /// ASCII space, common in hand-typed hex dumps.
    pub const SPACE: SeparatorSet = SeparatorSet(8);
    /// Every separator this crate recognises.
    pub const ALL: SeparatorSet = SeparatorSet(15);

    /// The union of two sets.
    ///
    /// ```
    /// # use bigu::intake::policy::SeparatorSet;
    /// let set = SeparatorSet::UNDERSCORE.with(SeparatorSet::COMMA);
    /// assert!(set.contains(',') && !set.contains('\''));
    /// ```
    pub fn with(self, other: SeparatorSet) -> SeparatorSet {
        SeparatorSet(self.0 | other.0)
    }

    /// True when `ch` is legal as a separator under this set.
    ///
    /// ```
    /// # use bigu::intake::policy::SeparatorSet;
    /// assert!(SeparatorSet::ALL.contains(' '));
    /// assert!(!SeparatorSet::NONE.contains('_'));
    /// ```
    pub fn contains(self, ch: char) -> bool {
        Self::bit(ch).map_or(false, |b| self.0 & b != 0)
    }

    /// True when the set admits nothing.
    ///
    /// ```
    /// # use bigu::intake::policy::SeparatorSet;
    /// assert!(SeparatorSet::NONE.is_empty());
    /// ```
    pub fn is_empty(self) -> bool {
        self.0 == 0
    }

    /// The mask bit a character occupies, or `None` if it is never a separator.
    fn bit(ch: char) -> Option<u8> {
        match ch {
            '_' => Some(1),
            ',' => Some(2),
            '\'' => Some(4),
            ' ' => Some(8),
            _ => None,
        }
    }
}

/// Where separators may sit relative to the digits.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Placement {
    /// Anywhere at all, runs and edges included — what `from_str_radix` does.
    Anywhere,
    /// Strictly between two digits: no leading, trailing or doubled separator.
    Interior,
}

/// The complete set of intake rules.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Policy {
    /// Which characters are legal separators.
    pub separators: SeparatorSet,
    /// Where a legal separator may sit.
    pub placement: Placement,
    /// When set, every digit group between separators must be this wide.
    pub group_size: Option<usize>,
    /// Whether whitespace around the whole input is dropped before scanning.
    pub trim_whitespace: bool,
    /// Whether a leading `+` or `-` is permitted.
    pub allow_sign: bool,
    /// Whether a `0x`, `0b` or `0o` prefix is honoured.
    pub allow_prefix: bool,
    /// Whether digits above nine may be written uppercase.
    pub allow_uppercase_digits: bool,
    /// Whether a significant digit may be preceded by zeros.
    pub allow_leading_zeros: bool,
}

impl Policy {
    /// The preset matching `from_str_radix` exactly: underscores anywhere, no
    /// trimming, no sign, no prefix, uppercase and leading zeros both fine.
    ///
    /// ```
    /// # use bigu::intake::Policy;
    /// assert!(Policy::strict().separators.contains('_'));
    /// assert!(!Policy::strict().allow_sign);
    /// ```
    pub fn strict() -> Policy {
        Policy {
            separators: SeparatorSet::UNDERSCORE,
            placement: Placement::Anywhere,
            group_size: None,
            trim_whitespace: false,
            allow_sign: false,
            allow_prefix: false,
            allow_uppercase_digits: true,
            allow_leading_zeros: true,
        }
    }

    /// The preset for input a human typed: every separator, trimmed edges,
    /// signs and prefixes honoured, separators only between digits.
    ///
    /// ```
    /// # use bigu::intake::Policy;
    /// let p = Policy::lenient();
    /// assert!(p.allow_prefix && p.trim_whitespace);
    /// ```
    pub fn lenient() -> Policy {
        Policy {
            separators: SeparatorSet::ALL,
            placement: Placement::Interior,
            group_size: None,
            trim_whitespace: true,
            allow_sign: true,
            allow_prefix: true,
            allow_uppercase_digits: true,
            allow_leading_zeros: true,
        }
    }

    /// Copy of the policy that additionally demands fixed-width digit groups.
    ///
    /// ```
    /// # use bigu::intake::Policy;
    /// assert_eq!(Policy::lenient().with_group_size(3).group_size, Some(3));
    /// ```
    pub fn with_group_size(mut self, size: usize) -> Policy {
        self.group_size = Some(size);
        self
    }

    /// Copy of the policy with a different separator alphabet.
    ///
    /// ```
    /// # use bigu::intake::{Policy, policy::SeparatorSet};
    /// assert!(Policy::strict().with_separators(SeparatorSet::NONE).separators.is_empty());
    /// ```
    pub fn with_separators(mut self, separators: SeparatorSet) -> Policy {
        self.separators = separators;
        self
    }
}

impl Default for Policy {
    fn default() -> Policy {
        Policy::strict()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn separator_membership() {
        for ch in ['_', ',', '\'', ' '] {
            assert!(SeparatorSet::ALL.contains(ch));
        }
        // A tab is whitespace but never a separator, and neither is a period.
        assert!(!SeparatorSet::ALL.contains('\t'));
        assert!(!SeparatorSet::ALL.contains('.'));
        assert!(!SeparatorSet::UNDERSCORE.contains(','));
    }

    #[test]
    fn union_is_idempotent() {
        let a = SeparatorSet::UNDERSCORE.with(SeparatorSet::SPACE);
        assert_eq!(a.with(SeparatorSet::UNDERSCORE), a);
        assert_eq!(SeparatorSet::NONE.with(SeparatorSet::ALL), SeparatorSet::ALL);
    }

    #[test]
    fn strict_matches_todays_parser() {
        let p = Policy::strict();
        // Underscores anywhere is precisely what radix.rs does.
        assert_eq!(p.separators, SeparatorSet::UNDERSCORE);
        assert_eq!(p.placement, Placement::Anywhere);
        assert_eq!(p.group_size, None);
        assert!(!p.trim_whitespace && !p.allow_sign && !p.allow_prefix);
        assert!(p.allow_uppercase_digits && p.allow_leading_zeros);
        assert_eq!(Policy::default(), p);
        assert_ne!(Policy::lenient(), p);
    }

    #[test]
    fn modifiers_leave_the_rest_alone() {
        let base = Policy::lenient();
        let grouped = base.with_group_size(4);
        assert_eq!(grouped.group_size, Some(4));
        assert_eq!(grouped.separators, base.separators);
        assert_eq!(grouped.trim_whitespace, base.trim_whitespace);
    }
}
