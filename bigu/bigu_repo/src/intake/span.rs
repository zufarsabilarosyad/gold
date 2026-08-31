//! Byte spans over the string handed to the intake.
//!
//! Every failure this subsystem reports names a place in the caller's original
//! input, not a place in some cleaned-up copy of it. That is the whole reason
//! the intake exists: [`Error::InvalidDigit`] can say *which character* was
//! wrong but never *where it sat*, so a caller validating a configuration file
//! has nothing to point at.
//!
//! [`Span`] is a pair of byte offsets rather than a line/column pair, because
//! offsets are what the scanner already has while it walks the bytes, they
//! survive the sign, prefix and group passes without needing the input
//! alongside them, and they slice the original string back out for free. Line
//! and column are resolved only when something is rendered, which is the rare
//! path. Columns are counted in characters, since a caret placed at a byte
//! column lands in the wrong place the moment the input holds a multi-byte
//! character — which is exactly the input that tends to be rejected.
//!
//! [`Error::InvalidDigit`]: crate::Error::InvalidDigit

use core::fmt;
use core::ops::Range;

/// A half-open byte range `[start, end)` into the raw intake string.
///
/// Spans produced here always sit on character boundaries and satisfy
/// `start <= end`. One built by hand that violates either is still safe: the
/// slicing helpers degrade to an empty string rather than panicking.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord)]
pub struct Span {
    /// Byte offset of the first byte covered.
    pub start: usize,
    /// Byte offset one past the last byte covered.
    pub end: usize,
}

impl Span {
    /// Builds a span from an explicit byte range.
    ///
    /// ```
    /// # use bigu::intake::Span;
    /// assert_eq!(Span::new(2, 5).len(), 3);
    /// ```
    pub fn new(start: usize, end: usize) -> Span {
        Span { start, end }
    }

    /// The one-byte span at `pos`, the shape a single ASCII character gets.
    ///
    /// ```
    /// # use bigu::intake::Span;
    /// assert_eq!(Span::at(4), Span::new(4, 5));
    /// ```
    pub fn at(pos: usize) -> Span {
        Span { start: pos, end: pos + 1 }
    }

    /// Number of bytes covered; saturates at zero for a reversed span.
    ///
    /// ```
    /// # use bigu::intake::Span;
    /// assert_eq!(Span::new(3, 9).len(), 6);
    /// ```
    pub fn len(&self) -> usize {
        self.end.saturating_sub(self.start)
    }

    /// True when the span covers nothing, as a zero-width span at the end of
    /// the input does.
    ///
    /// ```
    /// # use bigu::intake::Span;
    /// assert!(Span::new(7, 7).is_empty());
    /// ```
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// The smallest span covering both operands, which is how the two bytes of
    /// a base prefix become one span.
    ///
    /// ```
    /// # use bigu::intake::Span;
    /// assert_eq!(Span::at(0).join(Span::at(1)), Span::new(0, 2));
    /// ```
    pub fn join(self, other: Span) -> Span {
        Span { start: self.start.min(other.start), end: self.end.max(other.end) }
    }

    /// The span as a plain range, for slicing buffers carried alongside.
    ///
    /// ```
    /// # use bigu::intake::Span;
    /// assert_eq!(Span::new(1, 3).range(), 1..3);
    /// ```
    pub fn range(&self) -> Range<usize> {
        self.start..self.end
    }

    /// The text covered, or `""` if the span misses a character boundary.
    ///
    /// ```
    /// # use bigu::intake::Span;
    /// assert_eq!(Span::new(2, 4).text("0xff"), "ff");
    /// ```
    pub fn text<'a>(&self, input: &'a str) -> &'a str {
        input.get(self.range()).unwrap_or("")
    }

    /// The whole source line the span starts on, without its newline.
    ///
    /// ```
    /// # use bigu::intake::Span;
    /// assert_eq!(Span::at(6).line("12\n34x\n"), "34x");
    /// ```
    pub fn line<'a>(&self, input: &'a str) -> &'a str {
        let head = match input.get(..self.start.min(input.len())) {
            Some(h) => h,
            None => return "",
        };
        let rest = &input[head.rfind('\n').map_or(0, |i| i + 1)..];
        rest.find('\n').map_or(rest, |i| &rest[..i])
    }

    /// One-based line and column of the span's start, columns in characters.
    ///
    /// ```
    /// # use bigu::intake::Span;
    /// assert_eq!(Span::at(4).line_col("12\n34"), (2, 2));
    /// ```
    pub fn line_col(&self, input: &str) -> (usize, usize) {
        let head = input.get(..self.start.min(input.len())).unwrap_or("");
        let line = head.bytes().filter(|&b| b == b'\n').count() + 1;
        let col = head.rsplit('\n').next().map_or(0, |t| t.chars().count()) + 1;
        (line, col)
    }
}

impl fmt::Display for Span {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}..{}", self.start, self.end)
    }
}

impl From<Range<usize>> for Span {
    fn from(r: Range<usize>) -> Span {
        Span { start: r.start, end: r.end }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn width_join_and_display() {
        assert_eq!(Span::at(3).len(), 1);
        assert!(Span::new(3, 3).is_empty());
        // A reversed span is nonsense but must not underflow.
        assert_eq!(Span::new(9, 2).len(), 0);
        assert_eq!(Span::at(5).join(Span::at(2)), Span::new(2, 6));
        assert_eq!(Span::from(1..4).to_string(), "1..4");
    }

    #[test]
    fn text_is_guarded_against_bad_boundaries() {
        let input = "1٢3";
        // The middle character is two bytes wide; its span slices out whole.
        assert_eq!(Span::new(1, 3).text(input), "٢");
        // Cutting it in half yields nothing rather than a panic, as does
        // reaching past the end.
        assert_eq!(Span::new(1, 2).text(input), "");
        assert_eq!(Span::new(20, 24).text(input), "");
    }

    #[test]
    fn line_col_counts_characters_not_bytes() {
        // Three characters precede the offending byte, though four bytes do.
        assert_eq!(Span::new(5, 6).line_col("0x1٢f"), (1, 5));
        assert_eq!(Span::at(0).line_col("0x1٢f"), (1, 1));
    }

    #[test]
    fn line_col_across_newlines() {
        let input = "12\n34\n56";
        assert_eq!(Span::at(0).line_col(input), (1, 1));
        assert_eq!(Span::at(3).line_col(input), (2, 1));
        assert_eq!(Span::at(7).line_col(input), (3, 2));
        // An offset past the end still resolves rather than panicking.
        assert_eq!(Span::at(99).line_col(input), (3, 3));
    }

    #[test]
    fn line_extraction() {
        let input = "12\n34\n56";
        assert_eq!(Span::at(0).line(input), "12");
        assert_eq!(Span::at(4).line(input), "34");
        assert_eq!(Span::at(7).line(input), "56");
        // Trailing newline: the final line is empty, not the previous one.
        assert_eq!(Span::at(3).line("12\n"), "");
    }
}
