//! Fixed-width fields: padding, pad-stripping and the size arithmetic.
//!
//! `to_bytes_be` is deliberately minimal — it never emits a leading zero — but
//! wire formats rarely are. A protocol header has a 4-byte length, an RSA
//! modulus occupies exactly 256 bytes whatever its top byte happens to be, and
//! a record layout wants every field at a known offset. Reconciling those two
//! is mechanical, and getting it wrong is silent: pad on the wrong end and the
//! value changes by a factor of 2^(8n) instead of staying put.
//!
//! [`Width`] is the policy, and it composes on top of [`Endian`]: the padding
//! goes wherever that order puts its insignificant end, so a little-endian
//! field grows at the back and a big-endian field grows at the front. The
//! policy is checked in both directions — a value too wide for its field is
//! [`Error::Overflow`] on encode, and a field of the wrong size is refused on
//! decode rather than quietly reinterpreted.
//!
//! [`byte_len`] exists so a caller can size a buffer *before* encoding
//! anything. It is derived from `BigU::bit_len`, never from a trial encode, so
//! asking the question costs a limb inspection rather than an allocation.

use crate::bigu::BigU;
use crate::error::{Error, Result};
use crate::wire::order::Endian;

/// The number of bytes the minimal encoding of `value` occupies.
///
/// Derived from `bit_len`, so it allocates nothing. Zero occupies zero bytes,
/// matching the empty string `to_bytes_be` hands back for it.
///
/// ```
/// use bigu::{BigU, wire::byte_len};
/// assert_eq!(byte_len(&BigU::zero()), 0);
/// assert_eq!(byte_len(&BigU::from(255u32)), 1);
/// assert_eq!(byte_len(&BigU::from(256u32)), 2);
/// let big = BigU::from(2u32).pow(1023);
/// assert_eq!(byte_len(&big), 128);
/// ```
pub fn byte_len(value: &BigU) -> usize {
    ((value.bit_len() + 7) / 8) as usize
}

/// How wide the magnitude field is allowed to be.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Width {
    /// Exactly as many bytes as the value needs; zero occupies none.
    Minimal,
    /// Always `n` bytes. A value needing more is [`Error::Overflow`].
    Exact(usize),
    /// At least `n` bytes, more when the value needs them.
    AtLeast(usize),
}

impl Width {
    /// The field size this policy produces for a value whose minimal encoding
    /// is `minimal` bytes long.
    ///
    /// ```
    /// use bigu::wire::Width;
    /// assert_eq!(Width::Minimal.field_len(3).unwrap(), 3);
    /// assert_eq!(Width::AtLeast(8).field_len(3).unwrap(), 8);
    /// assert_eq!(Width::AtLeast(2).field_len(3).unwrap(), 3);
    /// assert_eq!(Width::Exact(4).field_len(3).unwrap(), 4);
    /// assert!(Width::Exact(2).field_len(3).is_err());
    /// ```
    pub fn field_len(self, minimal: usize) -> Result<usize> {
        match self {
            Width::Minimal => Ok(minimal),
            Width::AtLeast(n) => Ok(minimal.max(n)),
            Width::Exact(n) if minimal <= n => Ok(n),
            Width::Exact(_) => Err(Error::Overflow),
        }
    }

    /// Grows a body already laid out in `endian` order up to the field size by
    /// inserting zero bytes on the insignificant end.
    ///
    /// ```
    /// use bigu::wire::{Endian, Width};
    /// assert_eq!(Width::Exact(4).pad(Endian::Big, vec![1, 2]).unwrap(), vec![0, 0, 1, 2]);
    /// assert_eq!(Width::Exact(4).pad(Endian::Little, vec![2, 1]).unwrap(), vec![2, 1, 0, 0]);
    /// assert!(Width::Exact(1).pad(Endian::Big, vec![1, 2]).is_err());
    /// ```
    pub fn pad(self, endian: Endian, body: Vec<u8>) -> Result<Vec<u8>> {
        let target = self.field_len(body.len())?;
        let extra = target - body.len();
        if extra == 0 {
            return Ok(body);
        }
        let mut out = Vec::with_capacity(target);
        if endian.pads_at_front() {
            out.resize(extra, 0);
            out.extend_from_slice(&body);
        } else {
            out.extend_from_slice(&body);
            out.resize(target, 0);
        }
        Ok(out)
    }

    /// Checks an incoming field length against the policy without touching the
    /// bytes, which is what a sign-extended envelope needs: its filler is not
    /// zero, so it can be validated but not stripped.
    ///
    /// A field longer than [`Width::Exact`] allows is [`Error::Overflow`]; one
    /// shorter than required is [`Error::EmptyString`], the crate's "the input
    /// ran out" error.
    ///
    /// ```
    /// use bigu::wire::Width;
    /// assert!(Width::Exact(4).check_len(4).is_ok());
    /// assert!(Width::Exact(4).check_len(5).is_err());
    /// assert!(Width::AtLeast(4).check_len(9).is_ok());
    /// assert!(Width::AtLeast(4).check_len(3).is_err());
    /// ```
    pub fn check_len(self, len: usize) -> Result<()> {
        match self {
            Width::Minimal => Ok(()),
            Width::Exact(n) if len > n => Err(Error::Overflow),
            Width::Exact(n) if len < n => Err(Error::EmptyString),
            Width::Exact(_) => Ok(()),
            Width::AtLeast(n) if len < n => Err(Error::EmptyString),
            Width::AtLeast(_) => Ok(()),
        }
    }

    /// Validates the field length and returns the sub-slice with the zero
    /// padding removed, so what comes back is the minimal body in `endian`
    /// order.
    ///
    /// ```
    /// use bigu::wire::{Endian, Width};
    /// assert_eq!(Width::Exact(4).strip(Endian::Big, &[0, 0, 1, 2]).unwrap(), &[1, 2]);
    /// assert_eq!(Width::Exact(4).strip(Endian::Little, &[2, 1, 0, 0]).unwrap(), &[2, 1]);
    /// // An all-zero field is the value zero, and strips to nothing.
    /// assert!(Width::Exact(4).strip(Endian::Big, &[0; 4]).unwrap().is_empty());
    /// ```
    pub fn strip(self, endian: Endian, field: &[u8]) -> Result<&[u8]> {
        self.check_len(field.len())?;
        Ok(if endian.pads_at_front() {
            let start = field.iter().position(|&b| b != 0).unwrap_or(field.len());
            &field[start..]
        } else {
            let end = field.iter().rposition(|&b| b != 0).map_or(0, |i| i + 1);
            &field[..end]
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn byte_len_matches_the_encoder() {
        for raw in [0u64, 1, 255, 256, 65535, 65536, u64::MAX] {
            let v = BigU::from(raw);
            assert_eq!(byte_len(&v), v.to_bytes_be().len(), "{raw}");
        }
    }

    #[test]
    fn pad_then_strip_is_the_identity() {
        for endian in [Endian::Big, Endian::Little] {
            let body = endian.encode_magnitude(&BigU::from(0x1234u32));
            let field = Width::Exact(16).pad(endian, body.clone()).unwrap();
            assert_eq!(field.len(), 16);
            assert_eq!(Width::Exact(16).strip(endian, &field).unwrap(), &body[..]);
        }
    }

    #[test]
    fn exact_field_refuses_a_value_that_does_not_fit() {
        let body = BigU::from(0x1_0000u32).to_bytes_be();
        assert_eq!(body.len(), 3);
        assert_eq!(Width::Exact(2).pad(Endian::Big, body), Err(Error::Overflow));
    }

    #[test]
    fn at_least_grows_but_never_shrinks() {
        let body = vec![1, 2, 3, 4, 5];
        assert_eq!(Width::AtLeast(2).pad(Endian::Big, body.clone()).unwrap(), body);
        assert_eq!(Width::AtLeast(6).pad(Endian::Big, body).unwrap().len(), 6);
    }

    #[test]
    fn wrong_length_is_told_apart_from_overflow() {
        assert_eq!(Width::Exact(4).check_len(5), Err(Error::Overflow));
        assert_eq!(Width::Exact(4).check_len(3), Err(Error::EmptyString));
        assert!(Width::Minimal.check_len(999).is_ok());
    }

    #[test]
    fn zero_pads_to_a_full_field_of_zeros() {
        let field = Width::Exact(3).pad(Endian::Little, Vec::new()).unwrap();
        assert_eq!(field, vec![0, 0, 0]);
        assert!(Endian::Little.decode_magnitude(&field).is_zero());
    }
}
