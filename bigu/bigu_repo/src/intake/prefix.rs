//! Base prefixes, and the argument between a prefix and a requested radix.
//!
//! `from_str_prefixed` already reads `0x`, `0b` and `0o`, but it reads them by
//! slicing two bytes off the front and calling the parser with a base of its own
//! choosing. Nobody ever asks whether the prefix agrees with what the caller
//! wanted, because in that entry point the caller wanted nothing in particular.
//!
//! The moment a radix is supplied as well, disagreement becomes possible and
//! today it is reported as nonsense: `from_str_radix("0x1f", 10)` complains
//! about an invalid digit `'x'`, which is true and useless. The string is not
//! decimal-with-a-typo, it is hexadecimal offered to a decimal parser. This pass
//! says so.
//!
//! Two design points are worth stating. A prefix is only honoured when the
//! policy allows it: under [`Policy::strict`] the marker stays in the digit run
//! and fails the digit check exactly as it does today, which is what keeps
//! strict adoption behaviour-free. And stripping moves a run index, never a
//! span — the marker's own span is kept and reported, so a conflict points at
//! the `0x` in the caller's string and not at some offset into a copy.

use core::ops::Range;

use crate::intake::diagnostic::{Diagnostic, Rule};
use crate::intake::policy::Policy;
use crate::intake::scan::Scanned;
use crate::intake::span::Span;
use crate::{MAX_RADIX, MIN_RADIX};

/// The radix a marker character selects.
///
/// ```
/// use bigu::intake::prefix::radix_of;
/// assert_eq!(radix_of('X'), Some(16));
/// assert_eq!(radix_of('o'), Some(8));
/// assert_eq!(radix_of('d'), None);
/// ```
pub fn radix_of(marker: char) -> Option<u32> {
    match marker {
        'x' | 'X' => Some(16),
        'b' | 'B' => Some(2),
        'o' | 'O' => Some(8),
        _ => None,
    }
}

/// The radix in force, and the digits left once any prefix is stripped.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Prefixed {
    /// The radix the digits will be folded in.
    pub radix: u32,
    /// Span of the two-character marker, when one was consumed.
    pub marker: Option<Span>,
    /// Run indices of the digits that remain.
    pub digits: Range<usize>,
}

/// Settles the radix for `digits`, honouring or rejecting a base prefix.
///
/// `requested` is the radix the caller named, or `None` to infer one. With no
/// prefix and nothing requested the answer is decimal, the same default the
/// `FromStr` implementation uses.
///
/// ```
/// use bigu::intake::{scan::scan, prefix::resolve, Policy};
/// let p = Policy::lenient();
/// let s = scan("0xff", &p, 16).unwrap();
/// let out = resolve(&s, 0..4, None, &p).unwrap();
/// assert_eq!(out.radix, 16);
/// assert_eq!(&s.run()[out.digits], "ff");
/// ```
pub fn resolve(
    scanned: &Scanned,
    digits: Range<usize>,
    requested: Option<u32>,
    policy: &Policy,
) -> Result<Prefixed, Diagnostic> {
    let run = scanned.run().as_bytes();
    let marker = if policy.allow_prefix && digits.len() >= 2 && run[digits.start] == b'0' {
        radix_of(run[digits.start + 1] as char)
    } else {
        None
    };

    let (radix, marker, digits) = match marker {
        Some(found) => {
            let span = scanned.span_of(digits.start).join(scanned.span_of(digits.start + 1));
            if let Some(want) = requested {
                if want != found {
                    let ch = run[digits.start + 1] as char;
                    let rule = Rule::PrefixConflict { marker: ch, found, requested: want };
                    return Err(Diagnostic::new(rule, span));
                }
            }
            (found, Some(span), digits.start + 2..digits.end)
        }
        None => (requested.unwrap_or(10), None, digits),
    };

    if !(MIN_RADIX..=MAX_RADIX).contains(&radix) {
        let rule = Rule::UnsupportedRadix(radix);
        return Err(Diagnostic::new(rule, scanned.region()));
    }
    Ok(Prefixed { radix, marker, digits })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::intake::scan::scan;

    fn resolved(input: &str, requested: Option<u32>) -> Result<Prefixed, Diagnostic> {
        let p = Policy::lenient();
        let s = scan(input, &p, requested.unwrap_or(MAX_RADIX)).unwrap();
        let len = s.run().len();
        resolve(&s, 0..len, requested, &p)
    }

    #[test]
    fn every_marker_and_its_case() {
        for (input, radix) in [("0xff", 16), ("0XFF", 16), ("0b11", 2), ("0B11", 2)] {
            assert_eq!(resolved(input, None).unwrap().radix, radix);
        }
        assert_eq!(resolved("0o17", None).unwrap().radix, 8);
        assert_eq!(resolved("0O17", None).unwrap().radix, 8);
    }

    #[test]
    fn a_bare_number_keeps_the_requested_radix() {
        assert_eq!(resolved("123", Some(8)).unwrap().radix, 8);
        assert_eq!(resolved("123", None).unwrap().radix, 10);
        assert_eq!(resolved("123", Some(8)).unwrap().marker, None);
    }

    #[test]
    fn a_matching_prefix_is_accepted_and_stripped() {
        let out = resolved("0xff", Some(16)).unwrap();
        assert_eq!(out.digits, 2..4);
        assert_eq!(out.marker, Some(Span::new(0, 2)));
    }

    #[test]
    fn a_conflicting_prefix_is_not_an_invalid_digit() {
        let err = resolved("0x1f", Some(10)).unwrap_err();
        assert_eq!(
            err.rule,
            Rule::PrefixConflict { marker: 'x', found: 16, requested: 10 }
        );
        assert_eq!(err.span, Span::new(0, 2));
        // Even when the marker would have been a perfectly good digit.
        let err = resolved("0b1010", Some(16)).unwrap_err();
        assert_eq!(
            err.rule,
            Rule::PrefixConflict { marker: 'b', found: 2, requested: 16 }
        );
    }

    #[test]
    fn spans_survive_a_separator_inside_the_marker() {
        let p = Policy::lenient();
        let s = scan("0_xff", &p, 16).unwrap();
        let out = resolve(&s, 0..s.run().len(), Some(16), &p).unwrap();
        // Run indices 0 and 1 are input bytes 0 and 2.
        assert_eq!(out.marker, Some(Span::new(0, 3)));
        assert_eq!(out.digits, 2..4);
    }

    #[test]
    fn strict_leaves_the_marker_in_the_digits() {
        let p = Policy::strict();
        let s = scan("0x1f", &p, 10).unwrap();
        let out = resolve(&s, 0..4, Some(10), &p).unwrap();
        assert_eq!(out.marker, None);
        assert_eq!(out.digits, 0..4);
        // The 'x' then fails the digit check, exactly as it does today.
        assert!(s.validate_digits(out.digits, 10, &p).is_err());
    }

    #[test]
    fn a_lone_zero_is_not_a_prefix() {
        let out = resolved("0", None).unwrap();
        assert_eq!(out.marker, None);
        assert_eq!(out.digits, 0..1);
        // Nor is a marker without a leading zero.
        assert_eq!(resolved("x1", Some(36)).unwrap().digits, 0..2);
    }

    #[test]
    fn an_unsupported_radix_is_caught_here() {
        let err = resolved("12", Some(37)).unwrap_err();
        assert_eq!(err.rule, Rule::UnsupportedRadix(37));
        assert_eq!(resolved("12", Some(1)).unwrap_err().rule, Rule::UnsupportedRadix(1));
    }

    #[test]
    fn a_prefix_with_no_digits_leaves_an_empty_range() {
        let out = resolved("0x", None).unwrap();
        assert!(out.digits.is_empty());
        assert_eq!(out.radix, 16);
    }
}
