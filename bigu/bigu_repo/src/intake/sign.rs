//! Splitting an optional sign off the scanned run.
//!
//! A sign is not a digit, and the flat parser knows that only in the sense that
//! `'-'` fails the digit table — so `"-5"`, `"5-"` and `"--5"` all fail the same
//! way, with the same message, at no particular place. They are three different
//! mistakes.
//!
//! This pass names them. It looks at the run the scanner produced, not at the
//! input, so a sign that was separated from its digits by whitespace or a
//! separator is still found. The rule is positional and blunt: at most one sign,
//! and only as the very first character of the run. A sign anywhere else is a
//! placement error regardless of what surrounds it, which is what makes the
//! doubled, interior and trailing cases fall out of one comparison.
//!
//! Nothing here negates anything. `BigU` has no sign to carry and the intake
//! never builds a value; the pass hands back a flag and a range of digits, and
//! it is the caller's job to feed those to `BigI::from_parts` or to reject the
//! flag outright.

use core::ops::Range;

use crate::intake::diagnostic::{Diagnostic, Rule};
use crate::intake::policy::Policy;
use crate::intake::scan::Scanned;
use crate::intake::span::Span;

/// Whether the caller can represent a negative result.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Target {
    /// A `BigU` is being built: an absent sign or an explicit `+` only.
    Unsigned,
    /// A `BigI` is being built: the flag is reported rather than rejected.
    Signed,
}

/// What the sign pass concluded.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Split {
    /// True when the run opened with `-`.
    pub negative: bool,
    /// Span of the sign character, when one was written.
    pub marker: Option<Span>,
    /// Run indices of everything after the sign.
    pub digits: Range<usize>,
}

/// True for the two characters this pass treats as signs.
///
/// ```
/// use bigu::intake::sign::is_sign;
/// assert!(is_sign('+') && is_sign('-'));
/// assert!(!is_sign('0'));
/// ```
pub fn is_sign(ch: char) -> bool {
    ch == '+' || ch == '-'
}

/// Splits a leading sign off `scanned`, rejecting every other placement.
///
/// ```
/// use bigu::intake::{scan::scan, sign::{split, Target}, Policy};
/// let p = Policy::lenient();
/// let s = scan("-42", &p, 10).unwrap();
/// let out = split(&s, &p, Target::Signed).unwrap();
/// assert!(out.negative);
/// assert_eq!(&s.run()[out.digits], "42");
/// ```
pub fn split(scanned: &Scanned, policy: &Policy, target: Target) -> Result<Split, Diagnostic> {
    let run = scanned.run().as_bytes();

    // Any sign past the first character is doubled, interior or trailing; all
    // three are the same mistake seen from different sides.
    for (index, &byte) in run.iter().enumerate().skip(1) {
        if is_sign(byte as char) {
            let rule = Rule::SignPlacement { ch: byte as char };
            return Err(Diagnostic::new(rule, scanned.span_of(index)));
        }
    }

    let first = match run.first() {
        Some(&b) if is_sign(b as char) => b as char,
        _ => return Ok(Split { negative: false, marker: None, digits: 0..run.len() }),
    };
    let marker = scanned.span_of(0);
    if !policy.allow_sign {
        return Err(Diagnostic::new(Rule::SignPlacement { ch: first }, marker));
    }
    let negative = first == '-';
    if negative && target == Target::Unsigned {
        return Err(Diagnostic::new(Rule::SignedInput, marker));
    }
    Ok(Split { negative, marker: Some(marker), digits: 1..run.len() })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::intake::scan::scan;

    fn lenient(input: &str) -> Result<Split, Diagnostic> {
        let p = Policy::lenient();
        let s = scan(input, &p, 10).unwrap();
        split(&s, &p, Target::Signed)
    }

    #[test]
    fn an_absent_sign_is_positive() {
        let out = lenient("42").unwrap();
        assert!(!out.negative);
        assert_eq!(out.marker, None);
        assert_eq!(out.digits, 0..2);
    }

    #[test]
    fn explicit_signs_are_split_off() {
        let plus = lenient("+42").unwrap();
        assert!(!plus.negative);
        assert_eq!(plus.marker, Some(Span::at(0)));
        assert_eq!(plus.digits, 1..3);

        let minus = lenient("-42").unwrap();
        assert!(minus.negative);
        assert_eq!(minus.digits, 1..3);
    }

    #[test]
    fn doubled_interior_and_trailing_signs_are_rejected() {
        // The second sign of a doubled pair is the one blamed.
        assert_eq!(lenient("--42").unwrap_err().span, Span::at(1));
        assert_eq!(lenient("4-2").unwrap_err().span, Span::at(1));
        assert_eq!(lenient("42-").unwrap_err().span, Span::at(2));
        assert_eq!(
            lenient("+4+2").unwrap_err().rule,
            Rule::SignPlacement { ch: '+' }
        );
    }

    #[test]
    fn a_sign_is_found_through_separators() {
        let p = Policy::lenient();
        // The separator vanishes in the scan, so the sign is still interior.
        let s = scan("4_-2", &p, 10).unwrap();
        let err = split(&s, &p, Target::Signed).unwrap_err();
        assert_eq!(err.span, Span::at(2));
    }

    #[test]
    fn a_strict_policy_forbids_signs_outright() {
        let p = Policy::strict();
        let s = scan("+42", &p, 10).unwrap();
        let err = split(&s, &p, Target::Unsigned).unwrap_err();
        // Lowered flat, this is exactly what from_str_radix says today.
        assert_eq!(err.rule, Rule::SignPlacement { ch: '+' });
        assert_eq!(err.span, Span::at(0));
    }

    #[test]
    fn unsigned_targets_refuse_a_minus_but_accept_a_plus() {
        let p = Policy::lenient();
        let s = scan("-42", &p, 10).unwrap();
        assert_eq!(split(&s, &p, Target::Unsigned).unwrap_err().rule, Rule::SignedInput);
        let s = scan("+42", &p, 10).unwrap();
        assert!(split(&s, &p, Target::Unsigned).is_ok());
    }

    #[test]
    fn a_lone_sign_leaves_an_empty_digit_range() {
        let out = lenient("-").unwrap();
        assert!(out.negative);
        assert!(out.digits.is_empty());
    }

    #[test]
    fn an_empty_run_is_not_a_sign_error() {
        let p = Policy::strict();
        let s = scan("__", &p, 10).unwrap();
        let out = split(&s, &p, Target::Unsigned).unwrap();
        assert_eq!(out.digits, 0..0);
        assert_eq!(out.marker, None);
    }
}
