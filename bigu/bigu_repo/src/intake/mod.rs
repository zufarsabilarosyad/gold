//! Text intake: everything that has to happen to a string before a digit is
//! allowed to be folded into a value.
//!
//! `BigU::from_str_radix` does the numeric work well and the textual work by
//! accident. It skips `'_'` wherever it appears because skipping was the easiest
//! thing to write in the digit loop; it has no opinion on whitespace, signs or
//! base prefixes beyond "not a digit"; it reports a bad character without saying
//! where it sat; and it sizes a buffer from the input length before anything has
//! asked whether the input is a size this program wants.
//!
//! This subsystem decides those questions out loud, in a fixed pass order:
//!
//! 1. [`scan`] — one left-to-right walk over the raw bytes, producing a cleaned
//!    run, a span per surviving character, and the separator spans it dropped.
//! 2. [`sign`] — splits a leading `+` or `-` off the run and names a doubled,
//!    interior or trailing one; hands back a flag and never negates.
//! 3. [`prefix`] — reads `0x`, `0b` and `0o`, and checks the base they imply
//!    against the base the caller asked for.
//! 4. [`group`] — decides whether the separators sat where the policy allows,
//!    and whether the groups are the promised width.
//! 5. [`limits`] — converts the digit count to a bit count and refuses anything
//!    over the ceiling, while no buffer has been allocated yet.
//! 6. delegation — the digits, the radix and the sign go to the existing parser.
//!
//! The rule this directory keeps: **no module here multiplies, adds or folds a
//! digit into a value.** Digits are counted, classified, sliced and bounded, and
//! the only numeric call in the subsystem is the `from_str_radix` in
//! [`Intake::unsigned`]. Anything else would be a second implementation of the
//! parser, and two parsers disagree eventually.
//!
//! Failures are [`Diagnostic`]s rather than the flat [`Error`], so a caller
//! learns which rule fired and where; [`Diagnostic::to_error`] lowers back onto
//! the flat surface. [`Policy::strict`] reproduces exactly what `from_str_radix`
//! accepts today, so the layer can be adopted with no change in behaviour.
//!
//! [`Error`]: crate::Error

pub mod dialect;
pub mod diagnostic;
pub mod group;
pub mod limits;
pub mod policy;
pub mod prefix;
pub mod scan;
pub mod sign;
pub mod span;

pub use self::dialect::Dialect;
pub use self::diagnostic::Diagnostic;
pub use self::limits::Limits;
pub use self::policy::Policy;
pub use self::scan::Scanned;
pub use self::span::Span;

use core::ops::Range;

use crate::bigu::BigU;
use crate::intake::diagnostic::Rule;
use crate::intake::sign::Target;
use crate::{MAX_RADIX, MIN_RADIX};

/// A policy and a set of ceilings, ready to be applied to input.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Intake {
    /// The rules the text must satisfy.
    pub policy: Policy,
    /// The ceilings checked before construction.
    pub limits: Limits,
}

impl Intake {
    /// The adoption case: today's behaviour, with positions attached.
    ///
    /// ```
    /// # use bigu::{intake::Intake, BigU};
    /// assert_eq!(Intake::strict().unsigned("1_000", Some(10)).unwrap(), BigU::from(1000u32));
    /// ```
    pub fn strict() -> Intake {
        Intake { policy: Policy::strict(), limits: Limits::default() }
    }

    /// The typed-by-a-human case: trimmed edges, signs, prefixes, and
    /// separators that must sit between digits.
    ///
    /// ```
    /// # use bigu::{intake::Intake, BigU};
    /// let v = Intake::lenient().unsigned("  0xdead_beef ", None).unwrap();
    /// assert_eq!(v, BigU::from(0xdead_beefu32));
    /// ```
    pub fn lenient() -> Intake {
        Intake { policy: Policy::lenient(), limits: Limits::default() }
    }

    /// Copy of the intake with different ceilings.
    ///
    /// ```
    /// # use bigu::intake::{Intake, Limits};
    /// let tight = Intake::lenient().with_limits(Limits::of_bits(64));
    /// assert!(tight.unsigned(&"9".repeat(40), Some(10)).is_err());
    /// ```
    pub fn with_limits(mut self, limits: Limits) -> Intake {
        self.limits = limits;
        self
    }

    /// Runs every pass and delegates to the numeric parser. `radix` is the base
    /// to parse in, or `None` to take it from a prefix and fall back to
    /// decimal. A `-` is refused here; see [`Intake::signed`].
    ///
    /// ```
    /// # use bigu::intake::Intake;
    /// let err = Intake::strict().unsigned("12a", Some(10)).unwrap_err();
    /// assert_eq!(err.span.start, 2);
    /// assert_eq!(err.to_error(10), bigu::Error::InvalidDigit { ch: 'a', radix: 10 });
    /// ```
    pub fn unsigned(&self, input: &str, radix: Option<u32>) -> Result<BigU, Diagnostic> {
        let (scanned, digits, _, radix) = self.prepare(input, radix, Target::Unsigned)?;
        let span = scanned.span_over(digits.clone());
        // The only arithmetic in the subsystem. Everything above has already
        // guaranteed the slice is non-empty and made of digits of this radix,
        // so the error arm is unreachable rather than merely unlikely.
        BigU::from_str_radix(&scanned.run()[digits], radix)
            .map_err(|_| Diagnostic::new(Rule::NoDigits, span))
    }

    /// As [`Intake::unsigned`], but a leading `-` is reported instead of
    /// refused: the flag and the magnitude are what `BigI::from_parts` wants.
    ///
    /// ```
    /// # use bigu::{intake::Intake, BigI};
    /// let (negative, mag) = Intake::lenient().signed("-1_234", Some(10)).unwrap();
    /// assert_eq!(BigI::from_parts(negative, mag), BigI::from(-1234i32));
    /// ```
    pub fn signed(&self, input: &str, radix: Option<u32>) -> Result<(bool, BigU), Diagnostic> {
        let (scanned, digits, negative, radix) = self.prepare(input, radix, Target::Signed)?;
        let span = scanned.span_over(digits.clone());
        let mag = BigU::from_str_radix(&scanned.run()[digits], radix)
            .map_err(|_| Diagnostic::new(Rule::NoDigits, span))?;
        Ok((negative, mag))
    }

    /// The pass order itself. Returns the scan (which owns the run the digits
    /// point into), the digit range, the sign flag and the settled radix.
    fn prepare(
        &self,
        input: &str,
        radix: Option<u32>,
        target: Target,
    ) -> Result<(Scanned, Range<usize>, bool, u32), Diagnostic> {
        // Checked before anything else so a bad radix outranks a bad character,
        // which is the order from_str_radix already reports in.
        if let Some(r) = radix {
            if !(MIN_RADIX..=MAX_RADIX).contains(&r) {
                let rule = Rule::UnsupportedRadix(r);
                return Err(Diagnostic::new(rule, Span::new(0, input.len())));
            }
        }
        let scanned = scan::scan(input, &self.policy, radix.unwrap_or(MAX_RADIX))?;
        let signed = sign::split(&scanned, &self.policy, target)?;
        let prefixed = prefix::resolve(&scanned, signed.digits, radix, &self.policy)?;

        // Separators swallowed by the sign or the prefix are none of the group
        // rule's business; the rest must obey it.
        let cut = prefixed.marker.or(signed.marker).map_or(scanned.region().start, |s| s.end);
        let spans = &scanned.spans()[prefixed.digits.clone()];
        group::check(input, spans, scanned.separators_from(cut), &self.policy)?;

        scanned.validate_digits(prefixed.digits.clone(), prefixed.radix, &self.policy)?;
        let span = scanned.span_over(prefixed.digits.clone());
        self.limits.check(prefixed.digits.len(), prefixed.radix, span)?;
        Ok((scanned, prefixed.digits, signed.negative, prefixed.radix))
    }
}

impl Default for Intake {
    fn default() -> Intake {
        Intake::strict()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Error;

    #[test]
    fn strict_intake_matches_the_parser_it_wraps() {
        // One input per arm from_str_radix has today, accepted and rejected.
        let corpus = [
            ("42", 10), ("0000042", 10), ("1_000_000", 10), ("_1__2_", 10),
            ("___", 10), ("", 10), ("12a", 10), ("1٢3", 10), (" 42", 10),
            ("+5", 10), ("0x1f", 10), ("1G", 16), ("ff", 16), ("12", 1),
        ];
        for (input, radix) in corpus {
            let mine = Intake::strict()
                .unsigned(input, Some(radix))
                .map_err(|d| d.to_error(radix));
            assert_eq!(mine, BigU::from_str_radix(input, radix), "input {input:?}/{radix}");
        }
    }

    #[test]
    fn a_failure_carries_the_position_the_flat_error_cannot() {
        let err = Intake::strict().unsigned("1_2g4", Some(16)).unwrap_err();
        assert_eq!(err.span, Span::at(3));
        assert_eq!(err.to_error(16), Error::InvalidDigit { ch: 'g', radix: 16 });
        assert!(err.render("1_2g4").contains("1:4"));
    }

    #[test]
    fn the_two_presets_disagree_where_they_should() {
        let err = Intake::lenient().unsigned("0x1f", Some(10)).unwrap_err();
        assert_eq!(err.rule, Rule::PrefixConflict { marker: 'x', found: 16, requested: 10 });
        // Strict has no prefixes at all, so there it stays a bad digit.
        let strict = Intake::strict().unsigned("0x1f", Some(10)).unwrap_err();
        assert_eq!(strict.rule, Rule::DigitValue { ch: 'x', radix: 10 });
        // Loose separators go the other way: strict keeps them, lenient does not.
        assert!(Intake::strict().unsigned("_1__2_", Some(10)).is_ok());
        let err = Intake::lenient().unsigned("_1__2_", Some(10)).unwrap_err();
        assert_eq!(err.rule, Rule::SeparatorPlacement { ch: '_' });
        assert_eq!(err.span, Span::at(0));
    }

    #[test]
    fn lenient_accepts_what_a_person_types() {
        let i = Intake::lenient();
        assert_eq!(i.unsigned(" 1,234 ", None).unwrap(), BigU::from(1234u32));
        assert_eq!(i.unsigned("+1 000", None).unwrap(), BigU::from(1000u32));
        assert_eq!(i.unsigned("0b1010", None).unwrap(), BigU::from(10u32));
        assert_eq!(i.unsigned("0o17", None).unwrap(), BigU::from(15u32));
        assert_eq!(i.unsigned("dead'beef", Some(16)).unwrap(), BigU::from(0xdeadbeefu32));
    }

    #[test]
    fn a_sign_is_reported_not_applied() {
        let i = Intake::lenient();
        assert_eq!(i.signed("-42", Some(10)).unwrap(), (true, BigU::from(42u32)));
        assert_eq!(i.signed("+42", Some(10)).unwrap(), (false, BigU::from(42u32)));
        // The unsigned door stays shut, and a stray sign is placed.
        assert_eq!(i.unsigned("-42", Some(10)).unwrap_err().rule, Rule::SignedInput);
        assert_eq!(i.signed("4-2", Some(10)).unwrap_err().span, Span::at(1));
    }

    #[test]
    fn limits_refuse_before_anything_is_built() {
        let i = Intake::lenient().with_limits(Limits::new(4, u64::MAX));
        assert!(i.unsigned("1234", Some(10)).is_ok());
        let err = i.unsigned("12345", Some(10)).unwrap_err();
        assert_eq!(err.rule, Rule::DigitCap { found: 5, max: 4 });
        assert_eq!(err.to_error(10), Error::Overflow);
        // Separators do not count against the digit cap.
        assert!(i.unsigned("1_234", Some(10)).is_ok());
    }

    #[test]
    fn grouping_and_prefixes_compose() {
        let i = Intake { policy: Policy::lenient().with_group_size(4), limits: Limits::default() };
        assert_eq!(i.unsigned("0xdead_beef", None).unwrap(), BigU::from(0xdeadbeefu32));
        // The marker is not part of the first group: five digits precede the
        // separator, not seven characters.
        let err = i.unsigned("0xdeadb_eef", None).unwrap_err();
        assert!(matches!(err.rule, Rule::GroupSize { expected: 4, found: 5, .. }));
    }

    #[test]
    fn an_empty_run_is_refused_however_it_got_that_way() {
        for input in ["", "___", "+", "0x"] {
            let err = Intake::lenient().unsigned(input, None).unwrap_err();
            assert!(
                matches!(err.rule, Rule::NoDigits | Rule::SeparatorPlacement { .. }),
                "input {input:?} gave {:?}",
                err.rule
            );
        }
    }
}
