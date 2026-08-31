//! Byte order: the one place in the crate where a byte string is reversed.
//!
//! [`BigU::to_bytes_be`] and [`BigU::from_bytes_be`] are the only byte
//! primitives the crate ships, and they speak big-endian exclusively. Every
//! protocol that wants the other order therefore ends up writing the same two
//! lines — reverse on the way out, reverse on the way back — and every one of
//! them gets the *minimality* rule subtly wrong, because which end carries the
//! padding flips with the order. This module owns both halves of that so
//! nothing above it has to think about direction again.
//!
//! The minimality invariants are stated per order, because they are not the
//! same statement:
//!
//! * big-endian is minimal when the **first** byte is non-zero,
//! * little-endian is minimal when the **last** byte is non-zero,
//! * the empty slice is minimal in both orders and decodes to zero.
//!
//! A protocol that demands canonical bytes on the wire — so that one value has
//! exactly one encoding, and a digest over the encoding is a digest over the
//! value — calls [`Endian::check_minimal`] before accepting a field. A protocol
//! with fixed-width fields must not: its padding is legitimate, and stripping
//! it is [`super::width`]'s job.

use core::fmt;

use crate::bigu::BigU;
use crate::error::{Error, Result};

/// Which end of a byte string carries the most significant byte.
///
/// ```
/// use bigu::wire::Endian;
/// assert_eq!(Endian::Big.to_string(), "big-endian");
/// assert!(Endian::Big.pads_at_front());
/// assert!(!Endian::Little.pads_at_front());
/// ```
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Endian {
    /// Most significant byte first, the order the core primitives emit.
    Big,
    /// Least significant byte first, the order most host protocols use.
    Little,
}

impl fmt::Display for Endian {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Endian::Big => f.write_str("big-endian"),
            Endian::Little => f.write_str("little-endian"),
        }
    }
}

impl Endian {
    /// Rewrites a big-endian byte string into this order.
    ///
    /// Takes the vector by value because the big-endian side is always freshly
    /// produced by `to_bytes_be`, so the reversal can happen in place.
    ///
    /// ```
    /// use bigu::wire::Endian;
    /// assert_eq!(Endian::Big.from_be(vec![1, 2, 3]), vec![1, 2, 3]);
    /// assert_eq!(Endian::Little.from_be(vec![1, 2, 3]), vec![3, 2, 1]);
    /// ```
    pub fn from_be(self, mut be: Vec<u8>) -> Vec<u8> {
        if self == Endian::Little {
            be.reverse();
        }
        be
    }

    /// Rewrites a byte string in this order back into big-endian, ready to be
    /// handed to `BigU::from_bytes_be`.
    ///
    /// ```
    /// use bigu::wire::Endian;
    /// assert_eq!(Endian::Little.to_be(&[3, 2, 1]), vec![1, 2, 3]);
    /// assert_eq!(Endian::Big.to_be(&[1, 2, 3]), vec![1, 2, 3]);
    /// ```
    pub fn to_be(self, bytes: &[u8]) -> Vec<u8> {
        match self {
            Endian::Big => bytes.to_vec(),
            Endian::Little => bytes.iter().rev().copied().collect(),
        }
    }

    /// Encodes a magnitude with no padding at all: exactly the bytes
    /// `to_bytes_be` produced, in this order.
    ///
    /// ```
    /// use bigu::{BigU, wire::Endian};
    /// let v = BigU::from(0x0102_0304u32);
    /// assert_eq!(Endian::Little.encode_magnitude(&v), vec![4, 3, 2, 1]);
    /// assert!(Endian::Big.encode_magnitude(&BigU::zero()).is_empty());
    /// ```
    pub fn encode_magnitude(self, value: &BigU) -> Vec<u8> {
        self.from_be(value.to_bytes_be())
    }

    /// Decodes a magnitude from bytes in this order. Padding bytes on the
    /// appropriate end are accepted and ignored; only the value matters here.
    ///
    /// ```
    /// use bigu::{BigU, wire::Endian};
    /// assert_eq!(Endian::Little.decode_magnitude(&[4, 3, 2, 1]), BigU::from(0x0102_0304u32));
    /// assert!(Endian::Little.decode_magnitude(&[]).is_zero());
    /// ```
    pub fn decode_magnitude(self, bytes: &[u8]) -> BigU {
        BigU::from_bytes_be(&self.to_be(bytes))
    }

    /// True when a padding byte would be prepended rather than appended, which
    /// is exactly the big-endian case.
    pub fn pads_at_front(self) -> bool {
        self == Endian::Big
    }

    /// True when the slice carries no padding byte for this order.
    ///
    /// ```
    /// use bigu::wire::Endian;
    /// assert!(Endian::Big.is_minimal(&[1, 0]));
    /// assert!(!Endian::Big.is_minimal(&[0, 1]));
    /// assert!(Endian::Little.is_minimal(&[0, 1]));
    /// assert!(Endian::Big.is_minimal(&[]) && Endian::Little.is_minimal(&[]));
    /// ```
    pub fn is_minimal(self, bytes: &[u8]) -> bool {
        let edge = if self.pads_at_front() { bytes.first() } else { bytes.last() };
        edge != Some(&0)
    }

    /// Rejects a non-minimal encoding, for callers whose protocol says one
    /// value has exactly one legal byte string.
    ///
    /// The offending byte is reported as [`Error::InvalidDigit`] over radix
    /// 256: the wire subsystem reads a byte string as digits in base 256, so a
    /// byte that is illegal at its position is an invalid digit.
    ///
    /// ```
    /// use bigu::wire::Endian;
    /// assert!(Endian::Big.check_minimal(&[1, 0]).is_ok());
    /// assert!(Endian::Big.check_minimal(&[0, 1]).is_err());
    /// ```
    pub fn check_minimal(self, bytes: &[u8]) -> Result<()> {
        if self.is_minimal(bytes) {
            Ok(())
        } else {
            Err(Error::InvalidDigit { ch: '\0', radix: 256 })
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_through_both_orders() {
        for order in [Endian::Big, Endian::Little] {
            for raw in [0u64, 1, 255, 256, 0x0102_0304, u64::MAX] {
                let v = BigU::from(raw);
                let bytes = order.encode_magnitude(&v);
                assert_eq!(order.decode_magnitude(&bytes), v, "{order} {raw}");
            }
        }
    }

    #[test]
    fn zero_is_the_empty_string_in_both_orders() {
        assert!(Endian::Big.encode_magnitude(&BigU::zero()).is_empty());
        assert!(Endian::Little.encode_magnitude(&BigU::zero()).is_empty());
        assert!(Endian::Little.decode_magnitude(&[0, 0, 0]).is_zero());
    }

    #[test]
    fn minimality_flips_with_the_order() {
        // The same bytes are minimal in one order and padded in the other.
        assert!(Endian::Big.is_minimal(&[1, 0]));
        assert!(!Endian::Little.is_minimal(&[1, 0]));
        assert!(!Endian::Big.is_minimal(&[0, 1]));
        assert!(Endian::Little.is_minimal(&[0, 1]));
    }

    #[test]
    fn padding_never_changes_the_value() {
        let v = BigU::from(300u32);
        assert_eq!(Endian::Big.decode_magnitude(&[0, 0, 1, 44]), v);
        assert_eq!(Endian::Little.decode_magnitude(&[44, 1, 0, 0]), v);
    }

    #[test]
    fn single_zero_byte_is_not_minimal() {
        assert!(!Endian::Big.is_minimal(&[0]));
        assert!(!Endian::Little.is_minimal(&[0]));
        assert!(Endian::Big.check_minimal(&[0]).is_err());
    }
}
