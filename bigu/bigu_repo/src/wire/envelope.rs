//! Sign framing: how a [`BigI`] becomes bytes, and back.
//!
//! The crate stores a signed value as a sign flag plus an unsigned magnitude,
//! and exposes exactly that pair through [`BigI::from_parts`] and
//! [`BigI::into_parts`]. Everything here is built from that pair and the two
//! byte primitives underneath it — no limb is inspected, no arithmetic is
//! reimplemented, and the two's-complement conversion is a subtraction the
//! crate already performs.
//!
//! Two envelopes, because protocols disagree:
//!
//! * [`Envelope::SignMagnitude`] prefixes one sign byte (`0x00` non-negative,
//!   `0x01` negative) to the magnitude field. It is the direct image of the
//!   in-memory form, so encode and decode are both O(bytes), and the magnitude
//!   field obeys the [`Width`] policy exactly as an unsigned field would.
//! * [`Envelope::TwosComplement`] is what a C struct, a DER `INTEGER` and most
//!   binary protocols mean by a signed field: the sign lives in the top bit,
//!   negative `v` is `2^(8k) - |v|`, and `k` is the smallest byte count that
//!   leaves the top bit meaning what it should.
//!
//! Two rules belong to this module and nowhere else. **Negative zero is not a
//! value**: `from_parts` normalizes it away, so a sign-magnitude field that
//! claims a negative sign over a zero magnitude is a lie about a value this
//! crate cannot hold, and is rejected rather than silently normalized.
//! **Redundant sign extension decodes, it does not fail**: an encoder here
//! never emits a leading `0xFF` that the byte below it already implies, but a
//! decoder accepts any number of them, because a fixed-width field from a peer
//! is *made* of them. `FF FF FF` is `-1`, not an error.

use crate::bigi::BigI;
use crate::bigu::BigU;
use crate::error::{Error, Result};
use crate::wire::order::Endian;
use crate::wire::width::Width;

/// How the sign of a [`BigI`] is carried in the byte string.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Envelope {
    /// One sign byte, then the magnitude field.
    SignMagnitude,
    /// Sign in the top bit of the most significant byte.
    TwosComplement,
}

impl Envelope {
    /// Wraps a signed value in this envelope, laid out in `endian` order with
    /// the magnitude field sized by `width`.
    ///
    /// The sign byte of [`Envelope::SignMagnitude`] is always the first byte of
    /// the envelope whatever the order: it is a header for the field, not a
    /// digit of the number.
    ///
    /// ```
    /// use bigu::{BigI, wire::{Endian, Envelope, Width}};
    /// let neg = BigI::from(-2i64);
    /// let sm = Envelope::SignMagnitude.encode(&neg, Endian::Big, Width::Minimal).unwrap();
    /// assert_eq!(sm, vec![0x01, 0x02]);
    /// let tc = Envelope::TwosComplement.encode(&neg, Endian::Big, Width::Minimal).unwrap();
    /// assert_eq!(tc, vec![0xFE]);
    /// ```
    pub fn encode(self, value: &BigI, endian: Endian, width: Width) -> Result<Vec<u8>> {
        let (negative, mag) = value.clone().into_parts();
        match self {
            Envelope::SignMagnitude => {
                let field = width.pad(endian, endian.encode_magnitude(&mag))?;
                let mut out = Vec::with_capacity(field.len() + 1);
                out.push(u8::from(negative));
                out.extend_from_slice(&field);
                Ok(out)
            }
            Envelope::TwosComplement => {
                let body = twos_be(negative, &mag);
                let target = width.field_len(body.len())?;
                let filler = if negative { 0xFF } else { 0x00 };
                let mut be = vec![filler; target - body.len()];
                be.extend_from_slice(&body);
                Ok(endian.from_be(be))
            }
        }
    }

    /// Reads a signed value back out of this envelope.
    ///
    /// ```
    /// use bigu::{BigI, wire::{Endian, Envelope, Width}};
    /// let e = Envelope::TwosComplement;
    /// // Redundant sign extension is one value, not an error.
    /// assert_eq!(e.decode(&[0xFF, 0xFF, 0xFF], Endian::Big, Width::Minimal).unwrap(),
    ///            BigI::from(-1i64));
    /// assert_eq!(e.decode(&[0x00, 0x80], Endian::Big, Width::Minimal).unwrap(),
    ///            BigI::from(128i64));
    /// ```
    pub fn decode(self, bytes: &[u8], endian: Endian, width: Width) -> Result<BigI> {
        match self {
            Envelope::SignMagnitude => {
                let (&sign, field) = bytes.split_first().ok_or(Error::EmptyString)?;
                if sign > 1 {
                    return Err(Error::InvalidDigit { ch: sign as char, radix: 256 });
                }
                let mag = endian.decode_magnitude(width.strip(endian, field)?);
                if sign == 1 && mag.is_zero() {
                    // Negative zero is not a value this crate can represent, so
                    // its encoding is refused rather than folded into zero.
                    return Err(Error::InvalidDigit { ch: '\u{1}', radix: 256 });
                }
                Ok(BigI::from_parts(sign == 1, mag))
            }
            Envelope::TwosComplement => {
                width.check_len(bytes.len())?;
                from_twos_be(&endian.to_be(bytes))
            }
        }
    }
}

/// The minimal big-endian two's-complement body for a sign/magnitude pair.
///
/// `k` is chosen as the smallest byte count with `|v| <= 2^(8k-1)`, which is
/// `ceil(bits/8)` except when the magnitude fills its top byte exactly: then
/// only the single value `2^(bits-1)` still fits, and that is exactly the
/// magnitude with one bit set.
fn twos_be(negative: bool, mag: &BigU) -> Vec<u8> {
    let mut be = mag.to_bytes_be();
    if !negative {
        if be.first().map_or(true, |&b| b & 0x80 != 0) {
            be.insert(0, 0);
        }
        return be;
    }
    let bits = mag.bit_len();
    let mut k = ((bits + 7) / 8).max(1) as u32;
    if bits == 8 * u64::from(k) && mag.count_ones() != 1 {
        k += 1;
    }
    let modulus = BigU::one() << (8 * k);
    (&modulus - mag).to_bytes_be()
}

/// The inverse of [`twos_be`], over a non-empty big-endian field.
fn from_twos_be(be: &[u8]) -> Result<BigI> {
    let &first = be.first().ok_or(Error::EmptyString)?;
    if first & 0x80 == 0 {
        return Ok(BigI::from_biguint(BigU::from_bytes_be(be)));
    }
    let bits = u32::try_from(be.len()).ok().and_then(|n| n.checked_mul(8)).ok_or(Error::Overflow)?;
    let modulus = BigU::one() << bits;
    Ok(BigI::from_parts(true, &modulus - &BigU::from_bytes_be(be)))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn round(e: Envelope, v: i64, endian: Endian, width: Width) -> BigI {
        let bytes = e.encode(&BigI::from(v), endian, width).unwrap();
        e.decode(&bytes, endian, width).unwrap()
    }

    #[test]
    fn both_envelopes_round_trip_across_the_sign_boundary() {
        for v in [0i64, 1, -1, 127, 128, -128, -129, 255, -256, i32::MIN as i64, i64::MAX] {
            for e in [Envelope::SignMagnitude, Envelope::TwosComplement] {
                for endian in [Endian::Big, Endian::Little] {
                    assert_eq!(round(e, v, endian, Width::Minimal), BigI::from(v), "{v}");
                }
            }
        }
    }

    #[test]
    fn twos_complement_matches_the_primitive_for_one_byte() {
        for v in -128i64..=127 {
            let bytes = Envelope::TwosComplement
                .encode(&BigI::from(v), Endian::Big, Width::Exact(1))
                .unwrap();
            assert_eq!(bytes, vec![(v as i8) as u8], "{v}");
        }
    }

    #[test]
    fn sign_extension_is_minimal_on_encode() {
        let e = Envelope::TwosComplement;
        assert_eq!(e.encode(&BigI::from(-1i64), Endian::Big, Width::Minimal).unwrap(), vec![0xFF]);
        // 128 needs a leading zero so its top bit is not read as a sign.
        assert_eq!(e.encode(&BigI::from(128i64), Endian::Big, Width::Minimal).unwrap(), vec![0, 0x80]);
        assert_eq!(e.encode(&BigI::zero(), Endian::Big, Width::Minimal).unwrap(), vec![0]);
    }

    #[test]
    fn negative_zero_is_refused() {
        let bad = [0x01u8, 0x00];
        let got = Envelope::SignMagnitude.decode(&bad, Endian::Big, Width::Minimal);
        assert_eq!(got, Err(Error::InvalidDigit { ch: '\u{1}', radix: 256 }));
        // The positive spelling of the same field is fine.
        assert!(Envelope::SignMagnitude.decode(&[0x00, 0x00], Endian::Big, Width::Minimal).is_ok());
    }

    #[test]
    fn a_stray_sign_byte_is_an_invalid_digit() {
        let got = Envelope::SignMagnitude.decode(&[0x02, 0x01], Endian::Big, Width::Minimal);
        assert_eq!(got, Err(Error::InvalidDigit { ch: '\u{2}', radix: 256 }));
        assert_eq!(
            Envelope::SignMagnitude.decode(&[], Endian::Big, Width::Minimal),
            Err(Error::EmptyString)
        );
    }

    #[test]
    fn fixed_width_sign_extends_rather_than_zero_pads() {
        let bytes = Envelope::TwosComplement
            .encode(&BigI::from(-2i64), Endian::Big, Width::Exact(4))
            .unwrap();
        assert_eq!(bytes, vec![0xFF, 0xFF, 0xFF, 0xFE]);
        let le = Envelope::TwosComplement
            .encode(&BigI::from(-2i64), Endian::Little, Width::Exact(4))
            .unwrap();
        assert_eq!(le, vec![0xFE, 0xFF, 0xFF, 0xFF]);
        assert_eq!(
            Envelope::TwosComplement.decode(&le, Endian::Little, Width::Exact(4)).unwrap(),
            BigI::from(-2i64)
        );
    }
}
