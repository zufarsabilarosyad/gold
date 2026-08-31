//! Where separators are allowed to sit.
//!
//! `from_str_radix` skips `'_'` unconditionally, so `"_1__2_"` parses as twelve
//! and nobody ever wrote that on purpose. The permissiveness is not a decision
//! anyone made; it is what falls out of a `continue` in the digit loop. Silent
//! acceptance is fine for a literal a compiler already checked and wrong for a
//! field someone typed into a config file.
//!
//! This pass turns the `continue` into a policy. Under [`Placement::Anywhere`]
//! it agrees with today exactly, so nothing changes for existing callers. Under
//! [`Placement::Interior`] a separator must have a digit on each side, which
//! rejects the leading, trailing and doubled cases together — all three are
//! only "no digit since the last boundary" seen from different positions.
//!
//! Fixed-width grouping is the second, optional rule. It reads the digits from
//! the left while the convention it enforces is anchored on the right, so the
//! first group is the short one: `"1_000_000"` is well formed and `"10_00_000"`
//! is not. Everything is decided from the two span lists the scanner already
//! produced, with no re-lexing and no assumption that digits and separators
//! interleave in any particular way.
//!
//! [`Placement::Anywhere`]: crate::intake::policy::Placement::Anywhere
//! [`Placement::Interior`]: crate::intake::policy::Placement::Interior

use crate::intake::diagnostic::{Diagnostic, Rule};
use crate::intake::policy::{Placement, Policy};
use crate::intake::span::Span;

/// The grouping a radix is conventionally written in: nibbles for the
/// power-of-two bases, thousands for everything else.
///
/// ```
/// # use bigu::intake::group::conventional_size;
/// assert_eq!((conventional_size(10), conventional_size(16)), (3, 4));
/// ```
pub fn conventional_size(radix: u32) -> usize {
    if radix.is_power_of_two() {
        4
    } else {
        3
    }
}

/// Checks separator placement and, when the policy asks for it, group width.
///
/// `digits` are the spans of the digits that survived the sign and prefix
/// passes; `separators` are the separator spans in the same region, which
/// [`Scanned::separators_from`] supplies. Both must be sorted by offset, as the
/// scanner produces them. `input` is sliced only to name the offending
/// character — this pass classifies nothing.
///
/// ```
/// # use bigu::intake::{scan::scan, group::check, Policy};
/// let p = Policy::lenient();
/// let s = scan("1_000", &p, 10).unwrap();
/// assert!(check("1_000", s.spans(), s.separators(), &p).is_ok());
/// let bad = scan("1__000", &p, 10).unwrap();
/// assert!(check("1__000", bad.spans(), bad.separators(), &p).is_err());
/// ```
///
/// [`Scanned::separators_from`]: crate::intake::scan::Scanned::separators_from
pub fn check(
    input: &str,
    digits: &[Span],
    separators: &[Span],
    policy: &Policy,
) -> Result<(), Diagnostic> {
    if separators.is_empty() {
        return Ok(());
    }
    let interior = policy.placement == Placement::Interior;
    if !interior && policy.group_size.is_none() {
        return Ok(());
    }

    let mut seen = 0usize; // digits consumed so far
    let mut run = 0usize; // digits since the previous separator
    for (nth, sep) in separators.iter().enumerate() {
        while seen < digits.len() && digits[seen].start < sep.start {
            seen += 1;
            run += 1;
        }
        if interior && run == 0 {
            return Err(placement(input, *sep));
        }
        if let Some(size) = policy.group_size {
            // The leftmost group may be short — 1_000 is grouped correctly —
            // but every later one must be exactly the group width.
            let bad = if nth == 0 { run > size } else { run != size };
            if bad {
                return Err(width(input, *sep, size, run));
            }
        }
        run = 0;
    }

    let tail = digits.len() - seen;
    let last = separators[separators.len() - 1];
    if interior && tail == 0 {
        return Err(placement(input, last));
    }
    if let Some(size) = policy.group_size {
        if tail != size {
            return Err(width(input, last, size, tail));
        }
    }
    Ok(())
}

/// The separator character a span covers, defaulting to `'_'` if a span and an
/// input have been paired up wrongly.
fn char_at(input: &str, sep: Span) -> char {
    sep.text(input).chars().next().unwrap_or('_')
}

/// The diagnostic for a separator with no digit on one side.
fn placement(input: &str, sep: Span) -> Diagnostic {
    Diagnostic::new(Rule::SeparatorPlacement { ch: char_at(input, sep) }, sep)
}

/// The diagnostic for a group of the wrong width, blaming the separator that
/// closed it.
fn width(input: &str, sep: Span, expected: usize, found: usize) -> Diagnostic {
    let rule = Rule::GroupSize { ch: char_at(input, sep), expected, found };
    Diagnostic::new(rule, sep)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::intake::scan::scan;

    fn run(input: &str, policy: &Policy) -> Result<(), Diagnostic> {
        let s = scan(input, policy, 10).unwrap();
        check(input, s.spans(), s.separators(), policy)
    }

    #[test]
    fn anywhere_reproduces_todays_permissiveness() {
        let p = Policy::strict();
        for input in ["_1__2_", "1_2", "___", "_", "12"] {
            assert!(run(input, &p).is_ok(), "{input} should be accepted");
        }
    }

    #[test]
    fn interior_rejects_the_edges() {
        let p = Policy::lenient();
        assert!(run("1_2", &p).is_ok());
        // Leading, trailing and doubled all blame a separator span.
        assert_eq!(run("_12", &p).unwrap_err().span, Span::at(0));
        assert_eq!(run("12_", &p).unwrap_err().span, Span::at(2));
        assert_eq!(run("1__2", &p).unwrap_err().span, Span::at(2));
        assert_eq!(run("1_2_", &p).unwrap_err().span, Span::at(3));
        // With no digits at all, the first separator is the one at fault.
        let err = run("__", &p).unwrap_err();
        assert_eq!(err.rule, Rule::SeparatorPlacement { ch: '_' });
        assert_eq!(err.span, Span::at(0));
    }

    #[test]
    fn no_separators_is_always_fine() {
        let p = Policy::lenient().with_group_size(3);
        assert!(run("1234567", &p).is_ok());
        assert!(run("", &p).is_ok());
    }

    #[test]
    fn thousands_grouping() {
        let p = Policy::lenient().with_group_size(3);
        for input in ["1_000", "12_345_678", "123_456"] {
            assert!(run(input, &p).is_ok(), "{input} should be accepted");
        }
        // A short interior group is blamed on the separator that closed it.
        let err = run("1_00_000", &p).unwrap_err();
        assert_eq!(err.rule, Rule::GroupSize { ch: '_', expected: 3, found: 2 });
        assert_eq!(err.span, Span::at(4));
        // A long leading group is caught too, as is a short tail.
        assert_eq!(
            run("1234_567", &p).unwrap_err().rule,
            Rule::GroupSize { ch: '_', expected: 3, found: 4 }
        );
        assert_eq!(run("1_000_00", &p).unwrap_err().span, Span::at(5));
    }

    #[test]
    fn nibble_grouping_for_hex() {
        let p = Policy::lenient().with_group_size(conventional_size(16));
        let s = scan("dead_beef", &p, 16).unwrap();
        assert!(check("dead_beef", s.spans(), s.separators(), &p).is_ok());
        let s = scan("dea_dbeef", &p, 16).unwrap();
        assert!(check("dea_dbeef", s.spans(), s.separators(), &p).is_err());
    }

    #[test]
    fn the_offending_separator_is_named() {
        let mut p = Policy::lenient();
        assert_eq!(run(",12", &p).unwrap_err().rule, Rule::SeparatorPlacement { ch: ',' });
        // With trimming off, a trailing space is a separator like any other.
        p.trim_whitespace = false;
        assert_eq!(run("1 2 ", &p).unwrap_err().rule, Rule::SeparatorPlacement { ch: ' ' });
    }

    #[test]
    fn grouping_alone_still_allows_loose_placement() {
        // Placement stays Anywhere, so only the widths are judged; the leading
        // separator opens a group of its own and shortens the one after it.
        let p = Policy::strict().with_group_size(3);
        assert!(run("1_000", &p).is_ok());
        let err = run("_1_000", &p).unwrap_err();
        assert_eq!(err.rule, Rule::GroupSize { ch: '_', expected: 3, found: 1 });
        assert_eq!(err.span, Span::at(2));
    }
}
