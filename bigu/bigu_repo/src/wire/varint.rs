//! Self-delimiting lengths: seven value bits per byte, top bit continues.
//!
//! Framing needs to write a byte count, and a byte count is itself a number, so
//! there is an obvious temptation to encode it with the machinery in the rest
//! of this directory. That temptation is wrong twice over. A length prefix must
//! be *self-delimiting* — a reader has to know where it ends without being told
//! its width first — and it must be readable by a party that has no interest in
//! the value inside the record: a router that skips a frame, an index that
//! records offsets, a stream that resynchronizes. Keeping this encoding
//! separate is what lets those callers measure a record without decoding the
//! number it carries.
//!
//! The encoding is the usual base-128 one: seven value bits per byte, least
//! significant group first, the top bit set on every byte but the last. Two
//! rules make it safe to read from a hostile peer. An **overlong** encoding —
//! trailing groups that add nothing, so one length has two spellings — is
//! rejected, which keeps a frame header canonical. And every decode takes a
//! **ceiling**: a length prefix is a request for an allocation, and a reader
//! that honours `0xFF 0xFF 0xFF 0xFF 0xFF 0xFF 0xFF 0xFF 0xFF 0x7F` bytes of
//! payload has handed the peer a way to exhaust it.

use crate::error::{Error, Result};

/// The longest encoding of a [`u64`]: ten groups of seven bits.
pub const MAX_VARINT_LEN: usize = 10;

/// The number of bytes [`encode_varint`] produces for `value`.
///
/// ```
/// use bigu::wire::varint::varint_len;
/// assert_eq!(varint_len(0), 1);
/// assert_eq!(varint_len(127), 1);
/// assert_eq!(varint_len(128), 2);
/// assert_eq!(varint_len(u64::MAX), 10);
/// ```
pub fn varint_len(value: u64) -> usize {
    let bits = 64 - value.leading_zeros() as usize;
    (bits.max(1) + 6) / 7
}

/// Appends the encoding of `value` to `out`, returning how many bytes it added.
///
/// ```
/// use bigu::wire::varint::encode_varint_into;
/// let mut buf = vec![0xAA];
/// assert_eq!(encode_varint_into(300, &mut buf), 2);
/// assert_eq!(buf, vec![0xAA, 0xAC, 0x02]);
/// ```
pub fn encode_varint_into(mut value: u64, out: &mut Vec<u8>) -> usize {
    let mut written = 0;
    loop {
        let group = (value & 0x7F) as u8;
        value >>= 7;
        written += 1;
        if value == 0 {
            out.push(group);
            return written;
        }
        out.push(group | 0x80);
    }
}

/// The encoding of `value` as a fresh vector.
///
/// ```
/// use bigu::wire::varint::encode_varint;
/// assert_eq!(encode_varint(0), vec![0x00]);
/// assert_eq!(encode_varint(127), vec![0x7F]);
/// assert_eq!(encode_varint(128), vec![0x80, 0x01]);
/// ```
pub fn encode_varint(value: u64) -> Vec<u8> {
    let mut out = Vec::with_capacity(varint_len(value));
    encode_varint_into(value, &mut out);
    out
}

/// Reads one length from the front of `bytes`, returning it and how many bytes
/// it occupied.
///
/// `ceiling` is the largest value the caller is prepared to act on; anything
/// above it is [`Error::Overflow`] *before* the caller ever sizes a buffer. A
/// truncated encoding — the slice ends while a continuation bit is still set —
/// is [`Error::EmptyString`], and an overlong one is an invalid digit.
///
/// ```
/// use bigu::wire::varint::decode_varint;
/// assert_eq!(decode_varint(&[0xAC, 0x02, 0xFF], u64::MAX).unwrap(), (300, 2));
/// // A length above the ceiling never becomes an allocation.
/// assert!(decode_varint(&[0xAC, 0x02], 100).is_err());
/// // Overlong: 300 spelled with a group that adds nothing.
/// assert!(decode_varint(&[0xAC, 0x82, 0x00], u64::MAX).is_err());
/// ```
pub fn decode_varint(bytes: &[u8], ceiling: u64) -> Result<(u64, usize)> {
    let mut value: u64 = 0;
    let mut shift = 0u32;
    for (i, &byte) in bytes.iter().take(MAX_VARINT_LEN).enumerate() {
        let group = u64::from(byte & 0x7F);
        // The tenth group carries a single value bit; anything above it would
        // wrap silently, so refuse it as an overflow rather than truncating.
        if shift == 63 && group > 1 {
            return Err(Error::Overflow);
        }
        value |= group << shift;
        if byte & 0x80 == 0 {
            if i > 0 && byte == 0 {
                return Err(Error::InvalidDigit { ch: '\0', radix: 256 });
            }
            if value > ceiling {
                return Err(Error::Overflow);
            }
            return Ok((value, i + 1));
        }
        shift += 7;
    }
    // Either the slice ran out mid-encoding, or ten groups all continued.
    if bytes.len() >= MAX_VARINT_LEN {
        Err(Error::Overflow)
    } else {
        Err(Error::EmptyString)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trips_over_the_group_boundaries() {
        let cases = [0u64, 1, 127, 128, 129, 16383, 16384, 1 << 35, u64::MAX];
        for &n in &cases {
            let bytes = encode_varint(n);
            assert_eq!(bytes.len(), varint_len(n), "{n}");
            assert_eq!(decode_varint(&bytes, u64::MAX).unwrap(), (n, bytes.len()), "{n}");
        }
    }

    #[test]
    fn decode_stops_at_the_terminator_and_reports_the_offset() {
        let mut buf = encode_varint(300);
        buf.extend_from_slice(b"payload");
        let (n, used) = decode_varint(&buf, u64::MAX).unwrap();
        assert_eq!((n, used), (300, 2));
        assert_eq!(&buf[used..], b"payload");
    }

    #[test]
    fn overlong_encodings_are_rejected() {
        // 0 spelled in two groups, and 1 spelled in three.
        assert!(decode_varint(&[0x80, 0x00], u64::MAX).is_err());
        assert!(decode_varint(&[0x81, 0x80, 0x00], u64::MAX).is_err());
        // The one-byte zero is legal: it is the only spelling with i == 0.
        assert_eq!(decode_varint(&[0x00], u64::MAX).unwrap(), (0, 1));
    }

    #[test]
    fn a_hostile_length_cannot_request_an_unbounded_read() {
        let huge = encode_varint(u64::MAX);
        assert_eq!(decode_varint(&huge, 4096), Err(Error::Overflow));
        assert_eq!(decode_varint(&huge, u64::MAX).unwrap().0, u64::MAX);
    }

    #[test]
    fn truncation_is_told_apart_from_overflow() {
        assert_eq!(decode_varint(&[], u64::MAX), Err(Error::EmptyString));
        assert_eq!(decode_varint(&[0x80], u64::MAX), Err(Error::EmptyString));
        // Ten continuing groups can never terminate inside a u64.
        assert_eq!(decode_varint(&[0x80; 12], u64::MAX), Err(Error::Overflow));
    }

    #[test]
    fn the_tenth_group_holds_exactly_one_bit() {
        let mut bytes = vec![0x80; 9];
        bytes.push(0x01);
        assert_eq!(decode_varint(&bytes, u64::MAX).unwrap(), (1 << 63, 10));
        bytes[9] = 0x02;
        assert_eq!(decode_varint(&bytes, u64::MAX), Err(Error::Overflow));
    }
}
