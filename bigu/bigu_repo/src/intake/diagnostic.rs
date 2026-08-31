//! The failure value every intake pass returns, and how it is rendered.
//!
//! The crate's own [`Error`] is a flat leaf enum on purpose: it stays cheap to
//! clone, compare and assert on. That flatness is also its limit. It can say
//! `InvalidDigit { ch: '_', radix: 10 }` but it cannot say *a doubled separator
//! at byte 4*, and a caller checking a hand-written file needs the second
//! sentence, not the first.
//!
//! So the intake reports a [`Diagnostic`]: the rule that fired, plus the span it
//! fired on. Nothing is formatted eagerly — each rule carries its own data and
//! grows a message only when asked — so a rejected input costs no allocation on
//! the failure path. [`Diagnostic::render`] is the human view and
//! [`Diagnostic::to_error`] lowers back onto the flat surface. This module
//! decides nothing; it only describes a judgement another pass has made.

use core::fmt;

use crate::error::Error;
use crate::intake::span::Span;

/// The policy rule that rejected the input.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Rule {
    /// A byte that can never belong to a number in any base.
    Junk { ch: char, radix: u32 },
    /// A character that is a digit somewhere, but not in this base.
    DigitValue { ch: char, radix: u32 },
    /// An uppercase digit above nine under a lowercase-only policy.
    DigitCase { ch: char },
    /// A leading zero under a policy that forbids them.
    LeadingZero,
    /// A sign that was doubled, interior, trailing, or forbidden outright.
    SignPlacement { ch: char },
    /// A negative value offered to an unsigned intake.
    SignedInput,
    /// A base prefix that disagrees with the radix the caller asked for.
    PrefixConflict { marker: char, found: u32, requested: u32 },
    /// A separator that was leading, trailing or doubled.
    SeparatorPlacement { ch: char },
    /// A digit group of the wrong width under a fixed-group policy.
    GroupSize { ch: char, expected: usize, found: usize },
    /// No digits at all once the separators were dropped.
    NoDigits,
    /// More digits than the intake will accept.
    DigitCap { found: usize, max: usize },
    /// More bits than the intake will accept, as the digit count implies.
    BitCap { found: u64, max: u64 },
    /// A radix outside the crate's supported `2..=36`.
    UnsupportedRadix(u32),
}

impl Rule {
    /// The character at fault, when the rule has one. Used by the lowering to
    /// the flat error and by nothing else.
    ///
    /// ```
    /// # use bigu::intake::diagnostic::Rule;
    /// assert_eq!(Rule::SignPlacement { ch: '-' }.offending_char(), Some('-'));
    /// assert_eq!(Rule::NoDigits.offending_char(), None);
    /// ```
    pub fn offending_char(&self) -> Option<char> {
        match *self {
            Rule::Junk { ch, .. } | Rule::DigitValue { ch, .. } => Some(ch),
            Rule::DigitCase { ch } | Rule::SignPlacement { ch } => Some(ch),
            Rule::SeparatorPlacement { ch } | Rule::GroupSize { ch, .. } => Some(ch),
            Rule::PrefixConflict { marker, .. } => Some(marker),
            Rule::LeadingZero => Some('0'),
            Rule::SignedInput => Some('-'),
            Rule::NoDigits | Rule::DigitCap { .. } => None,
            Rule::BitCap { .. } | Rule::UnsupportedRadix(_) => None,
        }
    }
}

impl fmt::Display for Rule {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match *self {
            Rule::Junk { ch, radix } => write!(f, "{ch:?} is not usable in radix {radix}"),
            Rule::DigitValue { ch, radix } => write!(f, "invalid digit {ch:?} for radix {radix}"),
            Rule::DigitCase { ch } => write!(f, "uppercase digit {ch:?} is not allowed"),
            Rule::LeadingZero => f.write_str("leading zeros are not allowed"),
            Rule::SignPlacement { ch } => write!(f, "misplaced sign {ch:?}"),
            Rule::SignedInput => f.write_str("a negative value cannot be parsed as unsigned"),
            Rule::PrefixConflict { marker, found, requested } => write!(
                f,
                "prefix {marker:?} selects radix {found}, but radix {requested} was requested"
            ),
            Rule::SeparatorPlacement { ch } => {
                write!(f, "separator {ch:?} must sit between two digits")
            }
            Rule::GroupSize { expected, found, .. } => {
                write!(f, "digit group of {found} where {expected} was expected")
            }
            Rule::NoDigits => f.write_str("no digits in input"),
            Rule::DigitCap { found, max } => write!(f, "{found} digits exceeds the cap of {max}"),
            Rule::BitCap { found, max } => write!(f, "{found} bits exceeds the cap of {max}"),
            Rule::UnsupportedRadix(r) => write!(f, "unsupported radix {r}; must be in 2..=36"),
        }
    }
}

/// A rejected intake: what went wrong, and where.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Diagnostic {
    /// The rule that fired.
    pub rule: Rule,
    /// The offending region of the original input.
    pub span: Span,
}

impl Diagnostic {
    /// Pairs a rule with the place it fired.
    ///
    /// ```
    /// # use bigu::intake::{Diagnostic, Span, diagnostic::Rule};
    /// assert_eq!(Diagnostic::new(Rule::NoDigits, Span::at(0)).span, Span::at(0));
    /// ```
    pub fn new(rule: Rule, span: Span) -> Diagnostic {
        Diagnostic { rule, span }
    }

    /// The one-line message, without position information.
    ///
    /// ```
    /// # use bigu::intake::{Diagnostic, Span, diagnostic::Rule};
    /// let d = Diagnostic::new(Rule::DigitValue { ch: 'g', radix: 16 }, Span::at(2));
    /// assert_eq!(d.message(), "invalid digit 'g' for radix 16");
    /// ```
    pub fn message(&self) -> String {
        self.rule.to_string()
    }

    /// Renders the message, the source line and a caret under the offending
    /// characters. The caret is at least one column wide even for a zero-width
    /// span, so an "input ended here" report still points somewhere.
    ///
    /// ```
    /// # use bigu::intake::{Diagnostic, Span, diagnostic::Rule};
    /// let d = Diagnostic::new(Rule::DigitValue { ch: 'g', radix: 16 }, Span::at(2));
    /// let shown = d.render("0xg1");
    /// assert!(shown.contains("1:3"));
    /// assert_eq!(shown.lines().last().unwrap(), "  |   ^");
    /// ```
    pub fn render(&self, input: &str) -> String {
        use fmt::Write;
        let (line, col) = self.span.line_col(input);
        let text = self.span.line(input);
        let width = self.span.text(input).chars().count().max(1);
        let mut out = String::with_capacity(text.len() + 64);
        let _ = write!(out, "{}\n --> {line}:{col}\n  | {text}\n  | ", self.rule);
        for _ in 1..col {
            out.push(' ');
        }
        for _ in 0..width {
            out.push('^');
        }
        out
    }

    /// Lowers onto the crate's flat [`Error`], for callers that want only the
    /// surface `from_str_radix` already has.
    ///
    /// Structural rules have no flat twin — the enum cannot say "doubled
    /// separator" — so they lower to [`Error::InvalidDigit`] naming the
    /// character at fault against `radix`, the base the caller was parsing in.
    /// Rules carrying their own radix use that one instead.
    ///
    /// ```
    /// # use bigu::intake::{Diagnostic, Span, diagnostic::Rule};
    /// let d = Diagnostic::new(Rule::SeparatorPlacement { ch: '_' }, Span::at(0));
    /// assert_eq!(d.to_error(10), bigu::Error::InvalidDigit { ch: '_', radix: 10 });
    /// ```
    pub fn to_error(&self, radix: u32) -> Error {
        match self.rule {
            Rule::Junk { ch, radix } | Rule::DigitValue { ch, radix } => {
                Error::InvalidDigit { ch, radix }
            }
            Rule::NoDigits => Error::EmptyString,
            Rule::UnsupportedRadix(r) => Error::UnsupportedRadix(r),
            Rule::DigitCap { .. } | Rule::BitCap { .. } => Error::Overflow,
            // Every remaining rule carries a character, so the fallback below
            // never runs; it exists so the lowering stays total.
            other => Error::InvalidDigit {
                ch: other.offending_char().unwrap_or('\u{fffd}'),
                radix,
            },
        }
    }
}

impl fmt::Display for Diagnostic {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{} at {}", self.rule, self.span)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn caret_sits_under_the_character() {
        let d = Diagnostic::new(Rule::DigitValue { ch: 'g', radix: 16 }, Span::at(3));
        // "  | " prefix plus three columns of padding.
        assert_eq!(d.render("0x1g5").lines().last().unwrap(), "  |    ^");
        // A wider span gets a wider caret.
        let d = Diagnostic::new(
            Rule::PrefixConflict { marker: 'x', found: 16, requested: 10 },
            Span::new(0, 2),
        );
        let shown = d.render("0xff");
        assert!(shown.starts_with("prefix 'x' selects radix 16"));
        assert!(shown.lines().last().unwrap().ends_with("^^"));
    }

    #[test]
    fn caret_survives_multibyte_input_and_empty_spans() {
        // The offending byte is at 4 but only three characters precede it.
        let d = Diagnostic::new(Rule::Junk { ch: 'q', radix: 10 }, Span::new(4, 5));
        assert_eq!(d.render("12٢q").lines().last().unwrap(), "  |    ^");
        let d = Diagnostic::new(Rule::NoDigits, Span::new(3, 3));
        assert!(d.render("___").lines().last().unwrap().ends_with('^'));
    }

    #[test]
    fn lowering_keeps_the_flat_surface() {
        let at = Span::at(0);
        assert_eq!(
            Diagnostic::new(Rule::Junk { ch: '٢', radix: 10 }, at).to_error(10),
            Error::InvalidDigit { ch: '٢', radix: 10 }
        );
        assert_eq!(Diagnostic::new(Rule::NoDigits, at).to_error(10), Error::EmptyString);
        assert_eq!(
            Diagnostic::new(Rule::UnsupportedRadix(37), at).to_error(10),
            Error::UnsupportedRadix(37)
        );
        assert_eq!(
            Diagnostic::new(Rule::DigitCap { found: 9, max: 4 }, at).to_error(10),
            Error::Overflow
        );
        // A rule with no flat twin still names its character.
        assert_eq!(
            Diagnostic::new(Rule::LeadingZero, at).to_error(8),
            Error::InvalidDigit { ch: '0', radix: 8 }
        );
    }

    #[test]
    fn display_names_the_span() {
        let d = Diagnostic::new(Rule::SignedInput, Span::at(0));
        assert_eq!(d.to_string(), "a negative value cannot be parsed as unsigned at 0..1");
        assert_eq!(d.message(), "a negative value cannot be parsed as unsigned");
    }
}
