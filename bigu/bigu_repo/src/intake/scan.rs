//! The one left-to-right walk over the raw input.
//!
//! Every pass downstream wants to talk about positions in the caller's string,
//! and each would be tempted to re-lex it to find them. That way lies four
//! walks with four slightly different ideas of what a digit is.
//!
//! So this module walks once. It classifies each byte as a sign, a digit
//! candidate, a separator or junk, and produces a [`Scanned`]: the cleaned run
//! with separators and trimmed whitespace already gone, one span per surviving
//! character, and the spans of the separators it dropped. After this, no module
//! here touches the original string again except to quote it.
//!
//! The run holds signs and prefix markers as well as digits, because what counts
//! as a prefix is not knowable byte by byte — `0b1010` is a prefix in one base
//! and four hex digits in another. Classification is therefore radix-blind: any
//! ASCII alphanumeric is a digit candidate, and [`Scanned::validate_digits`]
//! judges values afterwards, once the prefix pass has settled the radix.

use core::ops::Range;

use crate::intake::diagnostic::{Diagnostic, Rule};
use crate::intake::policy::Policy;
use crate::intake::span::Span;

/// The result of the single pass: a cleaned character run plus its geometry.
#[derive(Clone, Debug)]
pub struct Scanned {
    run: String,
    spans: Vec<Span>,
    separators: Vec<Span>,
    region: Span,
}

/// Maps an ASCII byte to its digit value, the same table `radix.rs` folds with.
/// Duplicated rather than shared: that one is a private detail of the numeric
/// parser, and this module must not reach into it.
fn digit_value(byte: u8, radix: u32) -> Option<u32> {
    let v = match byte {
        b'0'..=b'9' => (byte - b'0') as u32,
        b'a'..=b'z' => (byte - b'a') as u32 + 10,
        b'A'..=b'Z' => (byte - b'A') as u32 + 10,
        _ => return None,
    };
    if v < radix {
        Some(v)
    } else {
        None
    }
}

/// Walks `input` once under `policy`, rejecting what cannot belong to a number.
///
/// `radix` is carried only so a junk character can be reported against the base
/// the caller asked for; digit *values* are not judged here.
///
/// ```
/// # use bigu::intake::{scan::scan, Policy};
/// let s = scan("1_2_3", &Policy::strict(), 10).unwrap();
/// assert_eq!(s.run(), "123");
/// assert_eq!(s.separators().len(), 2);
/// ```
pub fn scan(input: &str, policy: &Policy, radix: u32) -> Result<Scanned, Diagnostic> {
    let bytes = input.as_bytes();
    let (mut i, mut end) = (0usize, bytes.len());
    if policy.trim_whitespace {
        while i < end && bytes[i].is_ascii_whitespace() {
            i += 1;
        }
        while end > i && bytes[end - 1].is_ascii_whitespace() {
            end -= 1;
        }
    }
    let region = Span::new(i, end);

    let mut run = String::with_capacity(end - i);
    let mut spans = Vec::with_capacity(end - i);
    let mut separators = Vec::new();
    while i < end {
        let byte = bytes[i];
        if byte.is_ascii() && policy.separators.contains(byte as char) {
            separators.push(Span::at(i));
            i += 1;
            continue;
        }
        match byte {
            b'+' | b'-' | b'0'..=b'9' | b'a'..=b'z' | b'A'..=b'Z' => {
                run.push(byte as char);
                spans.push(Span::at(i));
                i += 1;
            }
            _ => {
                // Only ASCII bytes advance one at a time, so `i` is still on a
                // character boundary and the whole character can be named.
                let ch = input[i..].chars().next().unwrap_or('\u{fffd}');
                let span = Span::new(i, i + ch.len_utf8());
                return Err(Diagnostic::new(Rule::Junk { ch, radix }, span));
            }
        }
    }
    Ok(Scanned { run, spans, separators, region })
}

impl Scanned {
    /// The cleaned run: signs, markers and digit candidates, all ASCII, with
    /// separators removed. Character indices into it are byte indices.
    ///
    /// ```
    /// # use bigu::intake::{scan::scan, Policy};
    /// assert_eq!(scan("-0x_ff", &Policy::lenient(), 16).unwrap().run(), "-0xff");
    /// ```
    pub fn run(&self) -> &str {
        &self.run
    }

    /// One span per character of [`Scanned::run`], in order.
    ///
    /// ```
    /// # use bigu::intake::{scan::scan, Policy, Span};
    /// assert_eq!(scan("1_2", &Policy::strict(), 10).unwrap().spans()[1], Span::at(2));
    /// ```
    pub fn spans(&self) -> &[Span] {
        &self.spans
    }

    /// The spans of every separator that was dropped, in input order.
    ///
    /// ```
    /// # use bigu::intake::{scan::scan, Policy, Span};
    /// assert_eq!(scan("1_2", &Policy::strict(), 10).unwrap().separators(), &[Span::at(1)]);
    /// ```
    pub fn separators(&self) -> &[Span] {
        &self.separators
    }

    /// The separators at or after `offset`, which is how the group pass ignores
    /// one that a prefix or sign already swallowed.
    ///
    /// ```
    /// # use bigu::intake::{scan::scan, Policy};
    /// let s = scan("0x_f_f", &Policy::lenient(), 16).unwrap();
    /// assert_eq!(s.separators_from(3).len(), 1);
    /// ```
    pub fn separators_from(&self, offset: usize) -> &[Span] {
        &self.separators[self.separators.partition_point(|s| s.start < offset)..]
    }

    /// The region of the input the scan consumed, after trimming.
    ///
    /// ```
    /// # use bigu::intake::{scan::scan, Policy, Span};
    /// assert_eq!(scan("  42 ", &Policy::lenient(), 10).unwrap().region(), Span::new(2, 4));
    /// ```
    pub fn region(&self) -> Span {
        self.region
    }

    /// The span of one run character; an index past the end collapses to a
    /// zero-width span at the region's end, so "input stopped here" still
    /// points somewhere.
    ///
    /// ```
    /// # use bigu::intake::{scan::scan, Policy, Span};
    /// let s = scan("42", &Policy::strict(), 10).unwrap();
    /// assert_eq!((s.span_of(1), s.span_of(9)), (Span::at(1), Span::new(2, 2)));
    /// ```
    pub fn span_of(&self, index: usize) -> Span {
        match self.spans.get(index) {
            Some(s) => *s,
            None => Span::new(self.region.end, self.region.end),
        }
    }

    /// The span covering a range of run characters.
    ///
    /// ```
    /// # use bigu::intake::{scan::scan, Policy, Span};
    /// let s = scan("1_234", &Policy::strict(), 10).unwrap();
    /// assert_eq!(s.span_over(0..2), Span::new(0, 3));
    /// ```
    pub fn span_over(&self, range: Range<usize>) -> Span {
        if range.start >= range.end {
            return self.span_of(range.start);
        }
        self.span_of(range.start).join(self.span_of(range.end - 1))
    }

    /// The per-radix judgement the scan postponed: every character in `range`
    /// must be a digit in `radix` and satisfy the case rule, and the run must
    /// not open with a forbidden zero.
    ///
    /// ```
    /// # use bigu::intake::{scan::scan, Policy};
    /// let p = Policy::strict();
    /// let s = scan("1g", &p, 16).unwrap();
    /// assert!(s.validate_digits(0..2, 16, &p).is_err());
    /// assert!(s.validate_digits(0..1, 16, &p).is_ok());
    /// ```
    pub fn validate_digits(
        &self,
        range: Range<usize>,
        radix: u32,
        policy: &Policy,
    ) -> Result<(), Diagnostic> {
        let text = match self.run.get(range.clone()) {
            Some(t) if !t.is_empty() => t.as_bytes(),
            _ => return Err(Diagnostic::new(Rule::NoDigits, self.span_over(range))),
        };
        for (offset, &byte) in text.iter().enumerate() {
            let (index, ch) = (range.start + offset, byte as char);
            if digit_value(byte, radix).is_none() {
                let rule = Rule::DigitValue { ch, radix };
                return Err(Diagnostic::new(rule, self.span_of(index)));
            }
            if !policy.allow_uppercase_digits && byte.is_ascii_uppercase() {
                return Err(Diagnostic::new(Rule::DigitCase { ch }, self.span_of(index)));
            }
        }
        if !policy.allow_leading_zeros && text.len() > 1 && text[0] == b'0' {
            return Err(Diagnostic::new(Rule::LeadingZero, self.span_of(range.start)));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::intake::policy::SeparatorSet;

    #[test]
    fn separators_are_dropped_and_remembered() {
        let s = scan("1_000_000", &Policy::strict(), 10).unwrap();
        assert_eq!(s.run(), "1000000");
        assert_eq!(s.separators(), &[Span::at(1), Span::at(5)]);
        // Every surviving character keeps its original offset.
        assert_eq!((s.spans()[1], s.spans()[6]), (Span::at(2), Span::at(8)));
        assert!(s.separators_from(6).is_empty());
    }

    #[test]
    fn anything_outside_the_policy_is_junk() {
        let strict = Policy::strict();
        let err = scan("1,2", &strict, 10).unwrap_err();
        assert_eq!(err.rule, Rule::Junk { ch: ',', radix: 10 });
        assert_eq!(err.span, Span::at(1));
        // With an empty set even the underscore is rejected.
        let none = strict.with_separators(SeparatorSet::NONE);
        assert_eq!(scan("1_2", &none, 10).unwrap_err().span, Span::at(1));
        // A non-ASCII character is named whole, both bytes of it.
        let err = scan("1٢3", &strict, 10).unwrap_err();
        assert_eq!(err.rule, Rule::Junk { ch: '٢', radix: 10 });
        assert_eq!(err.span, Span::new(1, 3));
    }

    #[test]
    fn trimming_moves_the_region_not_the_offsets() {
        let s = scan("  4 2  ", &Policy::lenient(), 10).unwrap();
        assert_eq!(s.run(), "42");
        assert_eq!(s.region(), Span::new(2, 5));
        assert_eq!(s.spans()[1], Span::at(4));
        // Without trimming the surrounding space is junk, as it is today.
        assert!(scan(" 42", &Policy::strict(), 10).is_err());
        // Trimming reaches the edges only: an interior tab is still junk.
        assert_eq!(scan("\t4\t2\t", &Policy::lenient(), 10).unwrap_err().span, Span::at(2));
    }

    #[test]
    fn signs_and_markers_stay_in_the_run() {
        let s = scan("-0xFF", &Policy::lenient(), 16).unwrap();
        assert_eq!(s.run(), "-0xFF");
        assert_eq!(s.span_over(1..3), Span::new(1, 3));
    }

    #[test]
    fn validate_digits_reports_the_right_place() {
        let p = Policy::strict();
        let s = scan("1_2g4", &p, 16).unwrap();
        let err = s.validate_digits(0..4, 16, &p).unwrap_err();
        assert_eq!(err.rule, Rule::DigitValue { ch: 'g', radix: 16 });
        // Index 2 of the run is byte 3 of the input, past the separator.
        assert_eq!(err.span, Span::at(3));
        // An empty range is the no-digits case, not a silent success.
        let empty = scan("__", &p, 10).unwrap();
        assert_eq!(empty.run(), "");
        assert_eq!(empty.validate_digits(0..0, 10, &p).unwrap_err().rule, Rule::NoDigits);
    }

    #[test]
    fn validate_digits_honours_case_and_zero_rules() {
        let mut p = Policy::strict();
        assert!(scan("ff", &p, 16).unwrap().validate_digits(0..2, 16, &p).is_ok());
        p.allow_uppercase_digits = false;
        let s = scan("fF", &p, 16).unwrap();
        assert_eq!(s.validate_digits(0..2, 16, &p).unwrap_err().rule, Rule::DigitCase { ch: 'F' });
        // Digits nine and below are unaffected by the case rule.
        assert!(scan("42", &p, 10).unwrap().validate_digits(0..2, 10, &p).is_ok());
        p.allow_leading_zeros = false;
        let z = scan("042", &p, 10).unwrap();
        assert_eq!(z.validate_digits(0..3, 10, &p).unwrap_err().rule, Rule::LeadingZero);
        // A lone zero is a value, not a leading zero.
        assert!(scan("0", &p, 10).unwrap().validate_digits(0..1, 10, &p).is_ok());
    }
}
