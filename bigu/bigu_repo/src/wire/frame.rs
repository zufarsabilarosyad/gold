//! Record framing: magic, version, kind, length, payload.
//!
//! A bare field is fine when both ends already agree on the layout. The moment
//! a blob carries more than one value — a rational's two halves, a residue
//! vector, a log of appended records — it needs a shape a reader can walk
//! without knowing in advance what it will find:
//!
//! ```text
//! 'B' 'U' | version | kind | varint payload_len | payload
//! ```
//!
//! The magic makes a misaligned buffer fail loudly instead of decoding into a
//! plausible wrong number; the version byte leaves room for a later layout; the
//! kind byte tells a reader which decoder to reach for; and the length prefix —
//! [`super::varint`], deliberately not the value encoding — lets [`peek`] and
//! [`skip`] measure and step over a record without decoding the number in it.
//!
//! The composite layouts live here too, because "how many pieces, in what
//! order" is a framing question. A [`BigQ`] is two framed integers inside one
//! frame; a residue vector is a counted run of frames. Their pieces are encoded
//! by whatever [`Encoding`] the caller holds, so composite shape and scalar
//! layout stay independently choosable.

use crate::bigi::BigI;
use crate::bigu::BigU;
use crate::error::{Error, Result};
use crate::ratio::BigQ;
use crate::wire::codec::Encoding;
use crate::wire::varint::{decode_varint, encode_varint, encode_varint_into};

/// The two bytes every frame starts with.
pub const MAGIC: [u8; 2] = *b"BU";

/// The layout version this module writes.
pub const VERSION: u8 = 1;

/// What a frame's payload holds.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Kind {
    /// One [`BigU`] field.
    Unsigned = 1,
    /// One [`BigI`] field in the encoding's envelope.
    Signed = 2,
    /// A signed numerator frame followed by an unsigned denominator frame.
    Rational = 3,
    /// A varint count followed by that many unsigned frames.
    Residues = 4,
}

impl Kind {
    /// Reads a kind byte, rejecting one this version does not define.
    pub(crate) fn from_byte(byte: u8) -> Result<Kind> {
        match byte {
            1 => Ok(Kind::Unsigned),
            2 => Ok(Kind::Signed),
            3 => Ok(Kind::Rational),
            4 => Ok(Kind::Residues),
            _ => Err(Error::InvalidDigit { ch: byte as char, radix: 256 }),
        }
    }
}

/// Everything a reader learns from a frame header without touching the payload.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FrameHeader {
    /// The layout version the writer used.
    pub version: u8,
    /// What the payload holds.
    pub kind: Kind,
    /// Payload size in bytes, as declared by the length prefix.
    pub payload_len: usize,
    /// Header size in bytes, which varies with the length prefix.
    pub header_len: usize,
}

impl FrameHeader {
    /// Header plus payload: how far along the next frame starts.
    ///
    /// ```
    /// use bigu::wire::{frame::{frame, peek}, Kind};
    /// let f = frame(Kind::Unsigned, &[1, 2, 3]);
    /// assert_eq!(peek(&f).unwrap().total_len(), f.len());
    /// ```
    pub fn total_len(&self) -> usize {
        self.header_len + self.payload_len
    }
}

/// Wraps a payload in a frame of the given kind.
///
/// ```
/// use bigu::wire::{frame::frame, Kind};
/// assert_eq!(frame(Kind::Unsigned, &[0xAB]), vec![b'B', b'U', 1, 1, 1, 0xAB]);
/// ```
pub fn frame(kind: Kind, payload: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(payload.len() + 6);
    out.extend_from_slice(&MAGIC);
    out.push(VERSION);
    out.push(kind as u8);
    encode_varint_into(payload.len() as u64, &mut out);
    out.extend_from_slice(payload);
    out
}

/// Reads the header without requiring the payload to be present yet, which is
/// what a reader that has buffered only the head of a record needs.
///
/// ```
/// use bigu::wire::{frame::{frame, peek}, Kind};
/// let mut f = frame(Kind::Signed, &[7, 7, 7]);
/// f.truncate(5); // payload not read yet
/// assert_eq!(peek(&f).unwrap().payload_len, 3);
/// assert!(peek(b"XX").is_err());
/// ```
pub fn peek(bytes: &[u8]) -> Result<FrameHeader> {
    if bytes.len() < 4 {
        return Err(Error::EmptyString);
    }
    let illegal = |b: u8| Error::InvalidDigit { ch: b as char, radix: 256 };
    if bytes[..2] != MAGIC {
        return Err(illegal(bytes[0]));
    }
    if bytes[2] != VERSION {
        return Err(illegal(bytes[2]));
    }
    let kind = Kind::from_byte(bytes[3])?;
    let (len, used) = decode_varint(&bytes[4..], usize::MAX as u64)?;
    Ok(FrameHeader { version: bytes[2], kind, payload_len: len as usize, header_len: 4 + used })
}

/// The offset of the next frame, erroring when the payload is truncated.
///
/// ```
/// use bigu::wire::{frame::{frame, skip}, Kind};
/// let mut blob = frame(Kind::Unsigned, &[1]);
/// blob.extend_from_slice(&frame(Kind::Unsigned, &[2]));
/// let at = skip(&blob).unwrap(); // the second frame starts here
/// assert_eq!(skip(&blob[at..]).unwrap(), blob.len() - at);
/// ```
pub fn skip(bytes: &[u8]) -> Result<usize> {
    let header = peek(bytes)?;
    if bytes.len() < header.total_len() {
        return Err(Error::EmptyString);
    }
    Ok(header.total_len())
}

/// Splits one frame off the front, returning its header and payload. Trailing
/// bytes are left alone, so a run of frames is walked by repeated calls.
///
/// ```
/// use bigu::wire::{frame::{frame, unframe}, Kind};
/// let f = frame(Kind::Unsigned, &[9, 9]);
/// assert_eq!(unframe(&f).unwrap().1, &[9, 9][..]);
/// ```
pub fn unframe(bytes: &[u8]) -> Result<(FrameHeader, &[u8])> {
    let header = peek(bytes)?;
    if bytes.len() < header.total_len() {
        return Err(Error::EmptyString);
    }
    Ok((header, &bytes[header.header_len..header.total_len()]))
}

/// Unframes and insists on a kind, so a mislabelled payload never reaches a
/// decoder that would misread it.
pub(crate) fn expect(bytes: &[u8], kind: Kind) -> Result<(FrameHeader, &[u8])> {
    let (header, payload) = unframe(bytes)?;
    if header.kind != kind {
        return Err(Error::InvalidDigit { ch: header.kind as u8 as char, radix: 256 });
    }
    Ok((header, payload))
}

/// Lays out a rational as one frame holding a signed numerator frame and an
/// unsigned denominator frame.
///
/// ```
/// use bigu::{BigI, BigQ, wire::{Encoding, frame::{encode_ratio, decode_ratio}}};
/// let (enc, q) = (Encoding::new(), BigQ::new(BigI::from(-3i64), BigI::from(4i64)).unwrap());
/// assert_eq!(decode_ratio(&enc, &encode_ratio(&enc, &q).unwrap()).unwrap(), q);
/// ```
pub fn encode_ratio(enc: &Encoding, value: &BigQ) -> Result<Vec<u8>> {
    let mut body = frame(Kind::Signed, &enc.encode_signed_field(value.numer())?);
    body.extend_from_slice(&frame(Kind::Unsigned, &enc.encode_field(value.denom())?));
    Ok(frame(Kind::Rational, &body))
}

/// Reads back a rational laid out by [`encode_ratio`].
///
/// ```
/// use bigu::{BigI, BigQ, wire::{Encoding, frame::{encode_ratio, decode_ratio}}};
/// let (enc, q) = (Encoding::new(), BigQ::from_integer(BigI::from(5i64)));
/// assert!(decode_ratio(&enc, &encode_ratio(&enc, &q).unwrap()).unwrap().is_integer());
/// ```
pub fn decode_ratio(enc: &Encoding, bytes: &[u8]) -> Result<BigQ> {
    let (_, body) = expect(bytes, Kind::Rational)?;
    let (head, num) = expect(body, Kind::Signed)?;
    let num = enc.decode_signed_field(num)?;
    let rest = body.get(head.total_len()..).ok_or(Error::EmptyString)?;
    let (_, den) = expect(rest, Kind::Unsigned)?;
    BigQ::new(num, BigI::from(enc.decode_field(den)?))
}

/// Lays out a residue vector — the shape [`crate::CrtBasis::reduce`] returns —
/// as a counted run of unsigned frames.
///
/// ```
/// use bigu::{BigU, CrtBasis, wire::{Encoding, frame::{encode_residues, decode_residues}}};
/// let basis = CrtBasis::new(&[BigU::from(7u32), BigU::from(11u32)]).unwrap();
/// let (enc, r) = (Encoding::new(), basis.reduce(&BigU::from(50u32)));
/// assert_eq!(decode_residues(&enc, &encode_residues(&enc, &r).unwrap()).unwrap(), r);
/// ```
pub fn encode_residues(enc: &Encoding, residues: &[BigU]) -> Result<Vec<u8>> {
    let mut body = encode_varint(residues.len() as u64);
    for value in residues {
        body.extend_from_slice(&frame(Kind::Unsigned, &enc.encode_field(value)?));
    }
    Ok(frame(Kind::Residues, &body))
}

/// Reads back a residue vector laid out by [`encode_residues`]. The declared
/// count is capped by the payload length — every entry costs at least a frame
/// header — so a lying count cannot make the reader reserve for it.
///
/// ```
/// use bigu::wire::{Encoding, frame::{encode_residues, decode_residues}};
/// let enc = Encoding::new();
/// assert!(decode_residues(&enc, &encode_residues(&enc, &[]).unwrap()).unwrap().is_empty());
/// ```
pub fn decode_residues(enc: &Encoding, bytes: &[u8]) -> Result<Vec<BigU>> {
    let (_, body) = expect(bytes, Kind::Residues)?;
    let (count, mut at) = decode_varint(body, body.len() as u64)?;
    let mut out = Vec::with_capacity(count as usize);
    for _ in 0..count {
        let (head, payload) = expect(body.get(at..).ok_or(Error::EmptyString)?, Kind::Unsigned)?;
        out.push(enc.decode_field(payload)?);
        at += head.total_len();
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_frame_declares_its_own_length() {
        let payload = vec![0xAA; 300];
        let f = frame(Kind::Unsigned, &payload);
        let header = peek(&f).unwrap();
        assert_eq!((header.payload_len, header.header_len), (300, 6)); // two-byte varint
        assert_eq!(unframe(&f).unwrap().1, &payload[..]);
    }

    #[test]
    fn truncation_and_corruption_are_both_refused() {
        let f = frame(Kind::Unsigned, &[1, 2, 3]);
        assert!(peek(&f[..3]).is_err());
        assert!(skip(&f[..f.len() - 1]).is_err());
        assert!(unframe(&f[..f.len() - 1]).is_err());
        assert!(skip(&f).is_ok());
        let mut bad = f.clone();
        bad[0] = b'X';
        assert!(peek(&bad).is_err());
        bad[0] = b'B';
        bad[2] = 99;
        assert!(peek(&bad).is_err());
    }

    #[test]
    fn a_composite_decoder_refuses_a_mislabelled_or_lying_frame() {
        let enc = Encoding::new();
        let wrong = frame(Kind::Unsigned, &[1]);
        assert!(decode_ratio(&enc, &wrong).is_err());
        assert!(decode_residues(&enc, &wrong).is_err());
        // A count no payload could satisfy never becomes a reservation.
        assert!(decode_residues(&enc, &frame(Kind::Residues, &encode_varint(u64::MAX))).is_err());
    }

    #[test]
    fn frames_can_be_walked_without_decoding_them() {
        let mut blob = Vec::new();
        for n in [1usize, 300, 70000] {
            blob.extend_from_slice(&frame(Kind::Unsigned, &vec![7u8; n]));
        }
        let (mut at, mut seen) = (0, 0);
        while at < blob.len() {
            assert_eq!(peek(&blob[at..]).unwrap().kind, Kind::Unsigned);
            at += skip(&blob[at..]).unwrap();
            seen += 1;
        }
        assert_eq!(seen, 3);
    }
}
