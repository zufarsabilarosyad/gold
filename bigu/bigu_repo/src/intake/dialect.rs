//! Intake policies named after where the text came from.
//!
//! [`Policy::strict`] and [`Policy::lenient`] are the two ends of a dial, and
//! most real input sits at neither: it came out of a config file, a JSON
//! document, a Rust or C source literal, or a person typing a number with
//! thousands separators. Each of those has settled rules that somebody else
//! decided years ago, and getting them wrong is not a matter of taste — a JSON
//! reader that accepts `1_000` accepts documents no other reader will, and a
//! Rust-literal reader that rejects `0xFF_FF` rejects source that compiles.
//!
//! So this module states them once, as named [`Dialect`] values, rather than
//! leaving every caller to assemble a [`Policy`] and get one flag wrong. Each
//! is a plain function of the dialect: nothing here parses anything, and the
//! policies it returns go through the same [`crate::intake`] passes as any
//! hand-built one.
//!
//! Where a dialect's real grammar reaches past what a [`Policy`] can express —
//! JSON's exponents, C's octal-by-leading-zero — the policy covers the integer
//! subset and the difference is documented on the variant rather than silently
//! approximated.

use super::policy::{Placement, Policy, SeparatorSet};

/// A named source of numeric text.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Dialect {
    /// A Rust integer literal: `1_000`, `0xFF_FF`, `0b1010`, `0o777`.
    ///
    /// Underscores anywhere except leading, base prefixes honoured, no sign
    /// (in Rust the minus is an operator, not part of the literal) and no
    /// surrounding whitespace.
    Rust,
    /// A C integer literal: `1000`, `0xFF`, `0777`.
    ///
    /// No digit separators at all before C23, prefixes honoured, no sign. The
    /// leading-zero-means-octal rule is *not* applied here: this layer does not
    /// choose a radix from the text, so `0777` reads as decimal seven hundred
    /// and seventy-seven unless the caller asks for radix 8.
    C,
    /// A JSON number's integer part: `1000`, `-1000`.
    ///
    /// No separators, no prefixes, no leading zeros — JSON forbids `007` — and
    /// a leading minus is part of the number. Exponents and fractions belong to
    /// a float reader and are not accepted here.
    Json,
    /// A number a person typed: `1,000,000` or `1 000 000`.
    ///
    /// Every separator, only between digits, edges trimmed, sign allowed. Pair
    /// with [`Policy::with_group_size`] when the grouping is known to be
    /// regular, which turns `1,00,000` from accepted into reported.
    Human,
    /// A value from a configuration file or environment variable.
    ///
    /// Underscores between digits, prefixes honoured so `0x1f` works, edges
    /// trimmed because a trailing newline is the single most common thing
    /// wrong with a config value, and a sign allowed.
    Config,
}

impl Dialect {
    /// The [`Policy`] this dialect stands for.
    ///
    /// # Examples
    ///
    /// ```
    /// use bigu::intake::{Dialect, Policy};
    ///
    /// let json = Dialect::Json.policy();
    /// assert!(!json.allow_leading_zeros);
    /// assert!(json.allow_sign);
    /// assert!(json.separators.is_empty());
    /// ```
    pub fn policy(self) -> Policy {
        match self {
            Dialect::Rust => Policy {
                separators: SeparatorSet::UNDERSCORE,
                placement: Placement::Interior,
                group_size: None,
                trim_whitespace: false,
                allow_sign: false,
                allow_prefix: true,
                allow_uppercase_digits: true,
                allow_leading_zeros: true,
            },
            Dialect::C => Policy {
                separators: SeparatorSet::NONE,
                placement: Placement::Interior,
                group_size: None,
                trim_whitespace: false,
                allow_sign: false,
                allow_prefix: true,
                allow_uppercase_digits: true,
                allow_leading_zeros: true,
            },
            Dialect::Json => Policy {
                separators: SeparatorSet::NONE,
                placement: Placement::Interior,
                group_size: None,
                trim_whitespace: false,
                allow_sign: true,
                allow_prefix: false,
                allow_uppercase_digits: false,
                allow_leading_zeros: false,
            },
            Dialect::Human => Policy {
                separators: SeparatorSet::ALL,
                placement: Placement::Interior,
                group_size: None,
                trim_whitespace: true,
                allow_sign: true,
                allow_prefix: false,
                allow_uppercase_digits: true,
                allow_leading_zeros: true,
            },
            Dialect::Config => Policy {
                separators: SeparatorSet::UNDERSCORE,
                placement: Placement::Interior,
                group_size: None,
                trim_whitespace: true,
                allow_sign: true,
                allow_prefix: true,
                allow_uppercase_digits: true,
                allow_leading_zeros: true,
            },
        }
    }

    /// The dialect's usual name, for error messages and configuration keys.
    ///
    /// # Examples
    ///
    /// ```
    /// use bigu::intake::Dialect;
    ///
    /// assert_eq!(Dialect::Json.name(), "json");
    /// ```
    pub fn name(self) -> &'static str {
        match self {
            Dialect::Rust => "rust",
            Dialect::C => "c",
            Dialect::Json => "json",
            Dialect::Human => "human",
            Dialect::Config => "config",
        }
    }

    /// Look a dialect up by name, case-insensitively.
    ///
    /// Returns `None` rather than falling back to a default: a configuration
    /// naming a dialect this build does not have is a mistake worth surfacing,
    /// and quietly using `strict` would change how every number in that file
    /// is read.
    ///
    /// # Examples
    ///
    /// ```
    /// use bigu::intake::Dialect;
    ///
    /// assert_eq!(Dialect::by_name("JSON"), Some(Dialect::Json));
    /// assert_eq!(Dialect::by_name("perl"), None);
    /// ```
    pub fn by_name(name: &str) -> Option<Dialect> {
        match name.to_ascii_lowercase().as_str() {
            "rust" => Some(Dialect::Rust),
            "c" => Some(Dialect::C),
            "json" => Some(Dialect::Json),
            "human" => Some(Dialect::Human),
            "config" => Some(Dialect::Config),
            _ => None,
        }
    }

    /// Every dialect, in a fixed order.
    ///
    /// # Examples
    ///
    /// ```
    /// use bigu::intake::Dialect;
    ///
    /// assert_eq!(Dialect::all().len(), 5);
    /// ```
    pub fn all() -> &'static [Dialect] {
        &[
            Dialect::Rust,
            Dialect::C,
            Dialect::Json,
            Dialect::Human,
            Dialect::Config,
        ]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rust_takes_underscores_and_prefixes_but_no_sign() {
        let policy = Dialect::Rust.policy();
        assert!(policy.separators.contains('_'));
        assert!(policy.allow_prefix);
        assert!(!policy.allow_sign);
    }

    #[test]
    fn c_takes_no_separators() {
        assert!(Dialect::C.policy().separators.is_empty());
    }

    #[test]
    fn json_refuses_leading_zeros_and_separators() {
        let policy = Dialect::Json.policy();
        assert!(!policy.allow_leading_zeros);
        assert!(policy.separators.is_empty());
        assert!(!policy.allow_prefix);
    }

    #[test]
    fn json_keeps_its_sign() {
        assert!(Dialect::Json.policy().allow_sign);
    }

    #[test]
    fn human_takes_every_separator_between_digits() {
        let policy = Dialect::Human.policy();
        assert!(policy.separators.contains(','));
        assert!(policy.separators.contains(' '));
        assert_eq!(policy.placement, Placement::Interior);
    }

    #[test]
    fn config_trims_because_of_the_trailing_newline() {
        assert!(Dialect::Config.policy().trim_whitespace);
    }

    #[test]
    fn source_dialects_do_not_trim() {
        assert!(!Dialect::Rust.policy().trim_whitespace);
        assert!(!Dialect::C.policy().trim_whitespace);
        assert!(!Dialect::Json.policy().trim_whitespace);
    }

    #[test]
    fn names_round_trip_through_lookup() {
        for dialect in Dialect::all() {
            assert_eq!(Dialect::by_name(dialect.name()), Some(*dialect));
        }
    }

    #[test]
    fn lookup_is_case_insensitive_and_refuses_the_unknown() {
        assert_eq!(Dialect::by_name("Human"), Some(Dialect::Human));
        assert_eq!(Dialect::by_name("nonesuch"), None);
    }

    #[test]
    fn every_dialect_is_listed_once() {
        let all = Dialect::all();
        for dialect in all {
            assert_eq!(all.iter().filter(|item| *item == dialect).count(), 1);
        }
    }

    #[test]
    fn group_size_can_still_be_layered_on() {
        let policy = Dialect::Human.policy().with_group_size(3);
        assert_eq!(policy.group_size, Some(3));
    }
}
