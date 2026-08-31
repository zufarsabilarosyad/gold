//! The [`Encoding`] value: one reusable spec, bound once and used everywhere.
//!
//! The rest of this directory is components — an order, a width policy, a sign
//! envelope, a frame. A caller does not want to thread four decisions through
//! every call site; a caller wants to say "this is what my protocol looks like"
//! once and then serialize against it, the way they build one `ModRing` and
//! then do arithmetic in it. That is what `Encoding` is: an immutable, `Copy`
//! spec that composes the components in the fixed order the subsystem doc gives
//! and offers the four operations a protocol actually performs.
//!
//! Encoding is fallible for exactly one reason: a [`Width::Exact`] field can be
//! narrower than the value needs, which is [`Error::Overflow`]. Nothing else
//! about encoding can fail, which is why the free [`encode`] entry point — the
//! default spec, big-endian and minimal — returns bytes rather than a result.
//!
//! [`Error::Overflow`]: crate::Error::Overflow

use crate::bigi::BigI;
use crate::bigu::BigU;
use crate::error::Result;
use crate::wire::envelope::Envelope;
use crate::wire::frame::{self, Kind};
use crate::wire::order::Endian;
use crate::wire::width::Width;

/// A byte-order, width and sign-envelope policy, optionally framed.
///
/// Build one with [`Encoding::new`] and the `with_*` methods, hold it, and
/// reuse it: it borrows nothing and allocates nothing.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Encoding {
    endian: Endian,
    width: Width,
    envelope: Envelope,
    framed: bool,
    canonical: bool,
}

impl Default for Encoding {
    fn default() -> Encoding {
        Encoding::new()
    }
}

impl Encoding {
    /// The default spec: big-endian, minimal width, two's-complement signs, no
    /// frame, lenient about padding on the way in.
    ///
    /// ```
    /// use bigu::{BigU, wire::Encoding};
    /// assert_eq!(Encoding::new().encode(&BigU::from(258u32)).unwrap(), vec![1, 2]);
    /// ```
    pub fn new() -> Encoding {
        Encoding {
            endian: Endian::Big,
            width: Width::Minimal,
            envelope: Envelope::TwosComplement,
            framed: false,
            canonical: false,
        }
    }

    /// Rebinds the byte order.
    ///
    /// ```
    /// use bigu::{BigU, wire::{Encoding, Endian}};
    /// let enc = Encoding::new().with_endian(Endian::Little);
    /// assert_eq!(enc.encode(&BigU::from(258u32)).unwrap(), vec![2, 1]);
    /// ```
    pub fn with_endian(self, endian: Endian) -> Encoding {
        Encoding { endian, ..self }
    }

    /// Rebinds the field width.
    ///
    /// ```
    /// use bigu::{BigU, wire::{Encoding, Width}};
    /// let enc = Encoding::new().with_width(Width::Exact(4));
    /// assert_eq!(enc.encode(&BigU::from(258u32)).unwrap(), vec![0, 0, 1, 2]);
    /// ```
    pub fn with_width(self, width: Width) -> Encoding {
        Encoding { width, ..self }
    }

    /// Rebinds the sign envelope used by the signed operations.
    ///
    /// ```
    /// use bigu::{BigI, wire::{Encoding, Envelope}};
    /// let enc = Encoding::new().with_envelope(Envelope::SignMagnitude);
    /// assert_eq!(enc.encode_signed(&BigI::from(-1i64)).unwrap(), vec![1, 1]);
    /// ```
    pub fn with_envelope(self, envelope: Envelope) -> Encoding {
        Encoding { envelope, ..self }
    }

    /// Turns record framing on or off. A framed spec wraps its field in an
    /// unsigned or signed frame and requires one back on decode.
    ///
    /// ```
    /// use bigu::{BigU, wire::Encoding};
    /// let enc = Encoding::new().with_frame(true);
    /// let bytes = enc.encode(&BigU::from(7u32)).unwrap();
    /// assert_eq!((&bytes[..2], enc.decode(&bytes).unwrap()), (&b"BU"[..], BigU::from(7u32)));
    /// ```
    pub fn with_frame(self, framed: bool) -> Encoding {
        Encoding { framed, ..self }
    }

    /// Demands canonical bytes on decode: under [`Width::Minimal`], a field
    /// carrying a padding byte is rejected rather than accepted, so one value
    /// has exactly one legal encoding. Ignored under a fixed width, where the
    /// padding is the point.
    ///
    /// ```
    /// use bigu::wire::Encoding;
    /// assert!(Encoding::new().decode(&[0, 1]).is_ok());
    /// assert!(Encoding::new().with_canonical(true).decode(&[0, 1]).is_err());
    /// ```
    pub fn with_canonical(self, canonical: bool) -> Encoding {
        Encoding { canonical, ..self }
    }

    /// The three layout choices this spec binds.
    ///
    /// ```
    /// use bigu::wire::{Encoding, Endian, Envelope, Width};
    /// let parts = (Endian::Big, Width::Minimal, Envelope::TwosComplement);
    /// assert_eq!(Encoding::new().parts(), parts);
    /// ```
    pub fn parts(self) -> (Endian, Width, Envelope) {
        (self.endian, self.width, self.envelope)
    }

    /// The magnitude field with no frame around it.
    pub(crate) fn encode_field(&self, value: &BigU) -> Result<Vec<u8>> {
        self.width.pad(self.endian, self.endian.encode_magnitude(value))
    }

    /// The inverse of [`Encoding::encode_field`].
    pub(crate) fn decode_field(&self, bytes: &[u8]) -> Result<BigU> {
        if self.canonical && self.width == Width::Minimal {
            self.endian.check_minimal(bytes)?;
        }
        Ok(self.endian.decode_magnitude(self.width.strip(self.endian, bytes)?))
    }

    /// The signed field with no frame around it.
    pub(crate) fn encode_signed_field(&self, value: &BigI) -> Result<Vec<u8>> {
        self.envelope.encode(value, self.endian, self.width)
    }

    /// The inverse of [`Encoding::encode_signed_field`].
    pub(crate) fn decode_signed_field(&self, bytes: &[u8]) -> Result<BigI> {
        self.envelope.decode(bytes, self.endian, self.width)
    }

    /// Encodes an unsigned value against this spec.
    ///
    /// ```
    /// use bigu::{BigU, wire::{Encoding, Endian, Width}};
    /// let enc = Encoding::new().with_endian(Endian::Little).with_width(Width::Exact(8));
    /// assert_eq!(enc.encode(&BigU::from(1u32)).unwrap(), vec![1, 0, 0, 0, 0, 0, 0, 0]);
    /// assert!(enc.encode(&BigU::from(2u32).pow(100)).is_err());
    /// ```
    pub fn encode(&self, value: &BigU) -> Result<Vec<u8>> {
        let field = self.encode_field(value)?;
        Ok(if self.framed { frame::frame(Kind::Unsigned, &field) } else { field })
    }

    /// Decodes an unsigned value against this spec.
    ///
    /// ```
    /// use bigu::{BigU, wire::{Encoding, Width}};
    /// let enc = Encoding::new().with_width(Width::Exact(4));
    /// assert_eq!(enc.decode(&[0, 0, 1, 2]).unwrap(), BigU::from(258u32));
    /// assert!(enc.decode(&[0, 1, 2]).is_err()); // wrong field size
    /// ```
    pub fn decode(&self, bytes: &[u8]) -> Result<BigU> {
        let field = if self.framed { frame::expect(bytes, Kind::Unsigned)?.1 } else { bytes };
        self.decode_field(field)
    }

    /// Encodes a signed value against this spec's envelope.
    ///
    /// ```
    /// use bigu::{BigI, wire::Encoding};
    /// assert_eq!(Encoding::new().encode_signed(&BigI::from(-2i64)).unwrap(), vec![0xFE]);
    /// ```
    pub fn encode_signed(&self, value: &BigI) -> Result<Vec<u8>> {
        let field = self.encode_signed_field(value)?;
        Ok(if self.framed { frame::frame(Kind::Signed, &field) } else { field })
    }

    /// Decodes a signed value against this spec's envelope.
    ///
    /// ```
    /// use bigu::{BigI, wire::Encoding};
    /// let enc = Encoding::new().with_frame(true);
    /// let bytes = enc.encode_signed(&BigI::from(-70000i64)).unwrap();
    /// assert_eq!(enc.decode_signed(&bytes).unwrap(), BigI::from(-70000i64));
    /// ```
    pub fn decode_signed(&self, bytes: &[u8]) -> Result<BigI> {
        let field = if self.framed { frame::expect(bytes, Kind::Signed)?.1 } else { bytes };
        self.decode_signed_field(field)
    }
}

/// Encodes with the default spec — big-endian, minimal, unframed — which is
/// exactly `to_bytes_be` and so cannot fail.
///
/// ```
/// use bigu::{BigU, wire::encode};
/// assert_eq!(encode(&BigU::from(258u32)), vec![1, 2]);
/// assert!(encode(&BigU::zero()).is_empty());
/// ```
pub fn encode(value: &BigU) -> Vec<u8> {
    Endian::Big.encode_magnitude(value)
}

/// Decodes with the default spec, accepting leading zero padding.
///
/// ```
/// use bigu::{BigU, wire::{decode, encode}};
/// assert_eq!(decode(&encode(&BigU::from(258u32))).unwrap(), BigU::from(258u32));
/// assert!(decode(&[]).unwrap().is_zero());
/// ```
pub fn decode(bytes: &[u8]) -> Result<BigU> {
    Encoding::new().decode(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::error::Error;

    #[test]
    fn one_spec_round_trips_every_shape() {
        for endian in [Endian::Big, Endian::Little] {
            for width in [Width::Minimal, Width::Exact(16), Width::AtLeast(4)] {
                let enc = Encoding::new().with_endian(endian).with_width(width).with_frame(true);
                for raw in [0u64, 1, 255, 0x0102_0304, u64::MAX] {
                    let v = BigU::from(raw);
                    assert_eq!(enc.decode(&enc.encode(&v).unwrap()).unwrap(), v, "{raw}");
                }
            }
        }
    }

    #[test]
    fn signed_round_trips_in_both_envelopes() {
        for envelope in [Envelope::SignMagnitude, Envelope::TwosComplement] {
            let enc = Encoding::new().with_envelope(envelope).with_width(Width::Exact(8));
            for raw in [0i64, 1, -1, 255, -256, i32::MIN as i64] {
                let v = BigI::from(raw);
                assert_eq!(enc.decode_signed(&enc.encode_signed(&v).unwrap()).unwrap(), v, "{raw}");
            }
        }
    }

    #[test]
    fn a_narrow_field_refuses_a_wide_value() {
        let enc = Encoding::new().with_width(Width::Exact(2));
        assert_eq!(enc.encode(&BigU::from(0x1_0000u32)), Err(Error::Overflow));
        assert_eq!(enc.encode(&BigU::from(0xFFFFu32)).unwrap(), vec![0xFF, 0xFF]);
    }

    #[test]
    fn canonical_mode_rejects_what_lenient_mode_accepts() {
        let strict = Encoding::new().with_canonical(true);
        assert_eq!(Encoding::new().decode(&[0, 0, 5]).unwrap(), BigU::from(5u32));
        assert!(strict.decode(&[0, 0, 5]).is_err());
        assert_eq!(strict.decode(&[5]).unwrap(), BigU::from(5u32));
        assert!(strict.decode(&[]).unwrap().is_zero()); // zero is the empty field
    }

    #[test]
    fn a_framed_spec_refuses_a_bare_field_and_the_wrong_kind() {
        let enc = Encoding::new().with_frame(true);
        assert!(enc.decode(&[1, 2, 3]).is_err());
        let signed = enc.encode_signed(&BigI::from(1i64)).unwrap();
        assert!(enc.decode(&signed).is_err());
    }
}
