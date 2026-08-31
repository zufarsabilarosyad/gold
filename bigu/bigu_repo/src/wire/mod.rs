//! Byte-level interchange: an explicit encoding contract around the crate's two
//! byte primitives.
//!
//! [`BigU::to_bytes_be`] and [`BigU::from_bytes_be`] answer one question — what
//! are the bytes of this magnitude, most significant first — and deliberately
//! answer nothing else. Putting a value on a socket, in a file header or in a
//! fixed-size protocol field needs four more answers: which end goes first, how
//! wide the field is, where the sign lives, and how a reader knows where the
//! record stops. Every caller that has ever serialized a bignum has hand-rolled
//! those four, and each hand-rolled version disagrees with the next about
//! padding, about negative zero, and about what a truncated buffer means. This
//! subsystem writes them down once.
//!
//! The layering is fixed and one-directional; each layer only ever sees the
//! output of the one below it:
//!
//! ```text
//! order  -> which end carries the most significant byte      (Endian)
//! width  -> how many bytes the field occupies, and padding   (Width)
//! frame  -> magic, version, kind, varint length, payload     (FrameHeader)
//! stream -> the same frames pulled off a Read or Write       (Frames)
//! ```
//!
//! with the sign envelope sitting between width and frame: it composes an
//! order and a width into a signed field ([`Envelope`]) and hands the result to
//! the framing. [`Encoding`] is the value that binds one choice at each layer,
//! and it is what a caller holds and reuses, the way they hold one `ModRing`.
//!
//! The rule the whole directory obeys: **the limb vector is never touched**.
//! Nothing here packs limbs, converts radixes or reimplements arithmetic. Every
//! path funnels through `to_bytes_be` and `from_bytes_be` (and, for signed
//! values, `BigI::into_parts` / `BigI::from_parts`) and then decides only
//! ordering, padding and framing around the byte string those calls hand back.
//! A change to the limb representation cannot break this subsystem, and a bug
//! in this subsystem cannot corrupt a value's internal form.
//!
//! Failures are reported with the crate's existing [`Error`] variants, in a
//! deliberately small vocabulary: [`Error::Overflow`] when a value does not fit
//! its field or a declared length exceeds a ceiling, [`Error::EmptyString`]
//! when the input runs out before the encoding is complete, and
//! [`Error::InvalidDigit`] over radix 256 when a byte is illegal where it
//! stands — a bad magic byte, an unknown kind, a stray sign byte, a
//! non-canonical pad. The [`stream`] adapters are the one exception: they speak
//! [`std::io::Result`], converting at the boundary, which is what keeps
//! `error.rs` free of `From` glue to outside error types.
//!
//! # Examples
//!
//! ```
//! use bigu::{BigU, wire::{Encoding, Endian, Width}};
//!
//! // A protocol field: little-endian, exactly eight bytes, framed.
//! let enc = Encoding::new()
//!     .with_endian(Endian::Little)
//!     .with_width(Width::Exact(8))
//!     .with_frame(true);
//!
//! let value = BigU::from(0x0102_0304u32);
//! let bytes = enc.encode(&value).unwrap();
//! assert_eq!(enc.decode(&bytes).unwrap(), value);
//! ```
//!
//! [`BigU::to_bytes_be`]: crate::BigU::to_bytes_be
//! [`BigU::from_bytes_be`]: crate::BigU::from_bytes_be
//! [`Error`]: crate::Error

pub mod codec;
pub mod envelope;
pub mod frame;
pub mod hex;
pub mod order;
pub mod stream;
pub mod varint;
pub mod width;

pub use self::codec::{decode, encode, Encoding};
pub use self::envelope::Envelope;
pub use self::frame::{FrameHeader, Kind};
pub use self::order::Endian;
pub use self::stream::{frames, read_framed, write_framed, Frames};
pub use self::varint::{decode_varint, encode_varint};
pub use self::width::{byte_len, Width};

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{BigI, BigQ, BigU};

    #[test]
    fn the_free_entry_points_agree_with_the_primitives() {
        let v = BigU::from(0xDEAD_BEEFu32);
        assert_eq!(encode(&v), v.to_bytes_be());
        assert_eq!(decode(&v.to_bytes_be()).unwrap(), v);
    }

    #[test]
    fn every_layer_composes_without_touching_the_value() {
        let enc = Encoding::new()
            .with_endian(Endian::Little)
            .with_width(Width::AtLeast(4))
            .with_envelope(Envelope::SignMagnitude)
            .with_frame(true);
        for raw in [0i64, 1, -1, -70000, i64::MIN + 1] {
            let v = BigI::from(raw);
            assert_eq!(enc.decode_signed(&enc.encode_signed(&v).unwrap()).unwrap(), v, "{raw}");
        }
    }

    #[test]
    fn a_composite_blob_has_one_documented_shape() {
        let enc = Encoding::new();
        let q = BigQ::new(BigI::from(-355i64), BigI::from(113i64)).unwrap();
        let blob = frame::encode_ratio(&enc, &q).unwrap();
        // A reader can measure the record without decoding the numbers in it.
        assert_eq!(frame::skip(&blob).unwrap(), blob.len());
        assert_eq!(frame::peek(&blob).unwrap().kind, Kind::Rational);
        assert_eq!(frame::decode_ratio(&enc, &blob).unwrap(), q);
    }

    #[test]
    fn byte_len_sizes_a_buffer_before_anything_is_encoded() {
        let v = BigU::from(2u32).pow(255);
        assert_eq!(byte_len(&v), 32);
        assert_eq!(encode(&v).len(), byte_len(&v));
    }
}
