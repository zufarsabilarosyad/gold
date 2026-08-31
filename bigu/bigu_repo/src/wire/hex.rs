//! Hexadecimal rendering of an encoded byte string, and the way back.
//!
//! This is not radix conversion. [`crate::radix`] turns a *number* into base-16
//! text, which is a division loop over limbs and says nothing about how that
//! number was laid out on a wire. This module turns the *bytes* an
//! [`Encoding`](super::codec::Encoding) produced into text and back, one byte
//! to two digits, with the frame headers and padding still in place.
//!
//! The distinction matters at exactly the moment somebody is debugging a
//! protocol. `format!("{:x}", value)` shows what the number is; a hex dump of
//! the encoded frame shows what actually went down the socket, including the
//! magic, the width padding and the sign envelope — the parts that are wrong
//! when a decode fails. The two disagree whenever the encoding is doing its
//! job, and the encoded form is the one worth looking at.
//!
//! Reading is the mirror image and exists for the same reason: a specification
//! or a conformance suite states its vectors as hex byte strings, and
//! [`from_hex`] takes one back to bytes without the caller hand-rolling a
//! nibble loop that silently accepts an odd digit count.

use crate::error::{Error, Result};

/// Lowercase hex digits, indexed by nibble.
const LOWER: &[u8; 16] = b"0123456789abcdef";

/// Uppercase hex digits, indexed by nibble.
const UPPER: &[u8; 16] = b"0123456789ABCDEF";

/// How a byte string is laid out as text.
///
/// Grouping is cosmetic and applies only on the way out — [`from_hex`] accepts
/// any of these forms, and ignores the separators entirely.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Grouping {
    /// One unbroken run of digits: `deadbeef`.
    None,
    /// A space between every byte: `de ad be ef`.
    Bytes,
    /// A space between every four bytes, matching the word size a limb dump
    /// reads at: `deadbeef 12345678`.
    Words,
}

/// Render `bytes` as lowercase hex.
///
/// # Examples
///
/// ```
/// use bigu::wire::hex::to_hex;
///
/// assert_eq!(to_hex(&[0xde, 0xad, 0xbe, 0xef]), "deadbeef");
/// assert_eq!(to_hex(&[]), "");
/// ```
pub fn to_hex(bytes: &[u8]) -> String {
    render(bytes, LOWER, Grouping::None)
}

/// Render `bytes` as uppercase hex.
///
/// # Examples
///
/// ```
/// use bigu::wire::hex::to_hex_upper;
///
/// assert_eq!(to_hex_upper(&[0x0f, 0xa0]), "0FA0");
/// ```
pub fn to_hex_upper(bytes: &[u8]) -> String {
    render(bytes, UPPER, Grouping::None)
}

/// Render `bytes` as lowercase hex, broken up for reading.
///
/// # Examples
///
/// ```
/// use bigu::wire::hex::{to_hex_grouped, Grouping};
///
/// let frame = [0xde, 0xad, 0xbe, 0xef, 0x01, 0x02, 0x03, 0x04];
/// assert_eq!(to_hex_grouped(&frame, Grouping::Bytes), "de ad be ef 01 02 03 04");
/// assert_eq!(to_hex_grouped(&frame, Grouping::Words), "deadbeef 01020304");
/// ```
pub fn to_hex_grouped(bytes: &[u8], grouping: Grouping) -> String {
    render(bytes, LOWER, grouping)
}

fn render(bytes: &[u8], digits: &[u8; 16], grouping: Grouping) -> String {
    let stride = match grouping {
        Grouping::None => 0,
        Grouping::Bytes => 1,
        Grouping::Words => 4,
    };
    let mut out = String::with_capacity(bytes.len() * 2 + bytes.len() / 4);
    for (index, byte) in bytes.iter().enumerate() {
        if stride != 0 && index != 0 && index % stride == 0 {
            out.push(' ');
        }
        out.push(digits[(byte >> 4) as usize] as char);
        out.push(digits[(byte & 0x0f) as usize] as char);
    }
    out
}

/// Read a hex byte string back into bytes.
///
/// Case is not significant and ASCII whitespace between digits is ignored, so
/// anything [`to_hex_grouped`] emits reads back unchanged. What is refused is
/// an odd number of digits — half a byte is not a byte, and the alternative is
/// guessing which end the missing nibble belongs to — and any character that is
/// neither a hex digit nor whitespace.
///
/// # Errors
///
/// [`Error::InvalidDigit`] for a character outside `0-9a-fA-F` and whitespace,
/// or for a trailing half byte, which is reported against the last digit seen.
///
/// # Examples
///
/// ```
/// use bigu::wire::hex::{from_hex, to_hex};
///
/// assert_eq!(from_hex("deadbeef").unwrap(), vec![0xde, 0xad, 0xbe, 0xef]);
/// assert_eq!(from_hex("DE AD  BE EF").unwrap(), vec![0xde, 0xad, 0xbe, 0xef]);
/// assert!(from_hex("abc").is_err());
///
/// let frame = [0x00, 0x7f, 0x80, 0xff];
/// assert_eq!(from_hex(&to_hex(&frame)).unwrap(), frame);
/// ```
pub fn from_hex(text: &str) -> Result<Vec<u8>> {
    let mut bytes = Vec::with_capacity(text.len() / 2);
    let mut high: Option<u8> = None;
    let mut last = '0';
    for ch in text.chars() {
        if ch.is_ascii_whitespace() {
            continue;
        }
        let nibble = nibble_of(ch)?;
        last = ch;
        match high.take() {
            None => high = Some(nibble),
            Some(upper) => bytes.push((upper << 4) | nibble),
        }
    }
    if high.is_some() {
        // A dangling nibble is the one failure a lenient reader would paper
        // over, and it is exactly what a truncated capture looks like.
        return Err(Error::InvalidDigit {
            ch: last,
            radix: 16,
        });
    }
    Ok(bytes)
}

/// Whether `text` is a well-formed hex byte string.
///
/// The predicate form, for a caller deciding between two input shapes rather
/// than reporting a failure.
///
/// # Examples
///
/// ```
/// use bigu::wire::hex::is_hex;
///
/// assert!(is_hex("00ff"));
/// assert!(is_hex(""));
/// assert!(!is_hex("00f"));
/// assert!(!is_hex("00 gg"));
/// ```
pub fn is_hex(text: &str) -> bool {
    from_hex(text).is_ok()
}

fn nibble_of(ch: char) -> Result<u8> {
    match ch {
        '0'..='9' => Ok(ch as u8 - b'0'),
        'a'..='f' => Ok(ch as u8 - b'a' + 10),
        'A'..='F' => Ok(ch as u8 - b'A' + 10),
        _ => Err(Error::InvalidDigit { ch, radix: 16 }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn renders_lower_and_upper() {
        assert_eq!(to_hex(&[0x0a, 0xb0]), "0ab0");
        assert_eq!(to_hex_upper(&[0x0a, 0xb0]), "0AB0");
    }

    #[test]
    fn renders_every_byte_as_two_digits() {
        assert_eq!(to_hex(&[0x00]), "00");
        assert_eq!(to_hex(&[0xff]), "ff");
        assert_eq!(to_hex(&[0x05]).len(), 2);
    }

    #[test]
    fn groups_without_changing_the_digits() {
        let bytes = [0x01, 0x02, 0x03, 0x04, 0x05];
        let plain = to_hex(&bytes);
        for grouping in [Grouping::None, Grouping::Bytes, Grouping::Words] {
            let grouped = to_hex_grouped(&bytes, grouping);
            assert_eq!(grouped.replace(' ', ""), plain);
        }
    }

    #[test]
    fn word_grouping_breaks_every_four_bytes() {
        let bytes = [0xde, 0xad, 0xbe, 0xef, 0x01];
        assert_eq!(to_hex_grouped(&bytes, Grouping::Words), "deadbeef 01");
    }

    #[test]
    fn empty_input_renders_empty() {
        assert_eq!(to_hex(&[]), "");
        assert_eq!(to_hex_grouped(&[], Grouping::Bytes), "");
        assert_eq!(from_hex("").unwrap(), Vec::<u8>::new());
    }

    #[test]
    fn round_trips_through_every_grouping() {
        let bytes: Vec<u8> = (0u16..=255).map(|b| b as u8).collect();
        for grouping in [Grouping::None, Grouping::Bytes, Grouping::Words] {
            let text = to_hex_grouped(&bytes, grouping);
            assert_eq!(from_hex(&text).unwrap(), bytes);
        }
    }

    #[test]
    fn reading_ignores_case_and_whitespace() {
        assert_eq!(from_hex("DE ad\tBE\nef").unwrap(), vec![0xde, 0xad, 0xbe, 0xef]);
    }

    #[test]
    fn a_dangling_nibble_is_refused() {
        match from_hex("abc") {
            Err(Error::InvalidDigit { ch, radix }) => {
                assert_eq!((ch, radix), ('c', 16));
            }
            other => panic!("expected a dangling-nibble error, got {other:?}"),
        }
    }

    #[test]
    fn a_non_digit_is_refused_with_the_character() {
        match from_hex("00zz") {
            Err(Error::InvalidDigit { ch, radix }) => {
                assert_eq!((ch, radix), ('z', 16));
            }
            other => panic!("expected an invalid digit, got {other:?}"),
        }
    }

    #[test]
    fn the_predicate_agrees_with_the_reader() {
        for text in ["", "00", "00 ff", "0", "gg", "00g"] {
            assert_eq!(is_hex(text), from_hex(text).is_ok(), "disagreed on {text:?}");
        }
    }
}
