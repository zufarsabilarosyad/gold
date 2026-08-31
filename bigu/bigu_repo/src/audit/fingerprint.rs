//! A stable 64-bit fingerprint over a value's canonical bytes.
//!
//! The crate implements [`core::hash::Hash`] for every value type, and that is
//! the right hash for a `HashMap` and the wrong one for anything that outlives
//! the process. A map's hasher is seeded per process, and the standard library
//! declines to promise that any of its hashers produce the same number in the
//! next release — so a snapshot file, a golden test or an on-disk cache key
//! built from `Hash` is a value that changes underneath you for reasons that
//! have nothing to do with the number.
//!
//! This module fixes the function instead: FNV-1a over the canonical big-endian
//! bytes, written out here in full so it cannot drift. Two rules keep it honest.
//! Every component is preceded by its length, so `1/23` and `12/3` cannot fold
//! to the same byte stream; and every type contributes a distinct tag byte, so
//! the unsigned `5`, the signed `5` and the rational `5/1` are three different
//! fingerprints even though they are one number.

use core::fmt;

use crate::bigi::BigI;
use crate::bigu::BigU;
use crate::ratio::BigQ;

/// FNV-1a 64-bit offset basis.
const FNV_OFFSET: u64 = 0xcbf2_9ce4_8422_2325;

/// FNV-1a 64-bit prime.
const FNV_PRIME: u64 = 0x0000_0100_0000_01b3;

/// Tag byte for an unsigned magnitude.
const TAG_UNSIGNED: u8 = b'u';

/// Tag byte for a signed value.
const TAG_SIGNED: u8 = b'i';

/// Tag byte for a rational's numerator.
const TAG_RATIONAL: u8 = b'q';

/// Tag byte for a rational's denominator.
const TAG_DENOM: u8 = b'/';

/// Tag byte for a sequence of values.
const TAG_SEQUENCE: u8 = b'*';

/// A run-independent 64-bit digest of a value's canonical representation.
///
/// Equal values always fingerprint equally. Different values almost always
/// fingerprint differently — this is a 64-bit non-cryptographic digest, so it
/// identifies a value for caching and snapshotting, and never proves equality.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Fingerprint(u64);

impl Fingerprint {
    /// The digest as a plain integer.
    ///
    /// ```
    /// use bigu::{audit::fingerprint, BigU};
    /// let a = fingerprint::of(&BigU::from(42u32));
    /// let b = fingerprint::of(&BigU::from(42u64));
    /// assert_eq!(a.value(), b.value());
    /// ```
    pub const fn value(&self) -> u64 {
        self.0
    }
}

impl fmt::Display for Fingerprint {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:016x}", self.0)
    }
}

/// Folds `bytes` into the running state, one byte at a time.
fn absorb(state: u64, bytes: &[u8]) -> u64 {
    let mut h = state;
    for &b in bytes {
        h ^= b as u64;
        h = h.wrapping_mul(FNV_PRIME);
    }
    h
}

/// Folds one tagged, length-prefixed component into the running state.
///
/// The length prefix is what makes the encoding unambiguous: without it,
/// concatenating two components would lose the boundary between them.
fn field(state: u64, tag: u8, bytes: &[u8]) -> u64 {
    let h = absorb(state, &[tag]);
    let h = absorb(h, &(bytes.len() as u64).to_be_bytes());
    absorb(h, bytes)
}

/// Fingerprints a [`BigU`] over its canonical big-endian bytes.
///
/// ```
/// use bigu::{audit::fingerprint, BigU};
/// assert_eq!(fingerprint::of(&BigU::from(7u32)), fingerprint::of(&BigU::from(7u64)));
/// assert_ne!(fingerprint::of(&BigU::from(7u32)), fingerprint::of(&BigU::from(8u32)));
/// // The digest is a fixed function of the value, printed as 16 hex digits.
/// assert_eq!(fingerprint::of(&BigU::zero()).to_string().len(), 16);
/// ```
pub fn of(v: &BigU) -> Fingerprint {
    Fingerprint(field(FNV_OFFSET, TAG_UNSIGNED, &v.to_bytes_be()))
}

/// Fingerprints a [`BigI`], folding in the sign.
///
/// ```
/// use bigu::{audit::fingerprint, BigI};
/// assert_ne!(fingerprint::of_bigi(&BigI::from(5i64)), fingerprint::of_bigi(&BigI::from(-5i64)));
/// assert_eq!(fingerprint::of_bigi(&BigI::zero()), fingerprint::of_bigi(&BigI::from(0i64)));
/// ```
pub fn of_bigi(v: &BigI) -> Fingerprint {
    let h = field(FNV_OFFSET, TAG_SIGNED, &v.magnitude().to_bytes_be());
    Fingerprint(absorb(h, &[u8::from(v.is_negative())]))
}

/// Fingerprints a [`BigQ`], folding in the sign and the denominator.
///
/// Because a rational is always stored in lowest terms, equal rationals have
/// equal fingerprints even when they were written differently.
///
/// ```
/// use bigu::{audit::fingerprint, BigQ};
/// use std::str::FromStr;
/// let half = BigQ::from_str("1/2").unwrap();
/// assert_eq!(fingerprint::of_bigq(&half), fingerprint::of_bigq(&BigQ::from_str("3/6").unwrap()));
/// assert_ne!(fingerprint::of_bigq(&half), fingerprint::of_bigq(&BigQ::from_str("2/1").unwrap()));
/// ```
pub fn of_bigq(v: &BigQ) -> Fingerprint {
    let h = field(FNV_OFFSET, TAG_RATIONAL, &v.numer().magnitude().to_bytes_be());
    let h = absorb(h, &[u8::from(v.numer().is_negative())]);
    Fingerprint(field(h, TAG_DENOM, &v.denom().to_bytes_be()))
}

/// Fingerprints a whole slice, order included.
///
/// The element count is folded in first, so a sequence can never collide with a
/// longer one that happens to start the same way.
///
/// ```
/// use bigu::{audit::fingerprint, BigU};
/// let a = [BigU::from(1u32), BigU::from(2u32)];
/// let b = [BigU::from(2u32), BigU::from(1u32)];
/// assert_ne!(fingerprint::of_slice(&a), fingerprint::of_slice(&b));
/// assert_eq!(fingerprint::of_slice(&a), fingerprint::of_slice(&a.clone()));
/// ```
pub fn of_slice(values: &[BigU]) -> Fingerprint {
    let mut h = absorb(FNV_OFFSET, &[TAG_SEQUENCE]);
    h = absorb(h, &(values.len() as u64).to_be_bytes());
    for v in values {
        h = field(h, TAG_UNSIGNED, &v.to_bytes_be());
    }
    Fingerprint(h)
}

#[cfg(test)]
mod tests {
    use super::*;
    use core::str::FromStr;

    #[test]
    fn the_digest_is_pinned_to_these_constants() {
        // Pinned on purpose: if the fold changes, every stored snapshot key
        // silently stops matching, so the change has to be deliberate.
        assert_eq!(of(&BigU::zero()).value(), 0xa8e0_d8f2_1a97_7ef0);
        assert_eq!(of(&BigU::from(1u32)).value(), 0x8d92_f863_2f6f_9346);
        assert_eq!(of_bigi(&BigI::from(-1i64)).value(), 0x3d69_cfa9_15ee_3979);
    }

    #[test]
    fn types_are_separated_even_at_the_same_value() {
        let five_u = of(&BigU::from(5u32));
        let five_i = of_bigi(&BigI::from(5i64));
        let five_q = of_bigq(&BigQ::from_str("5/1").unwrap());
        assert_ne!(five_u, five_i);
        assert_ne!(five_i, five_q);
        assert_ne!(five_u, five_q);
    }

    #[test]
    fn length_prefixes_keep_components_apart() {
        // Without the prefix these two would fold the same byte stream.
        let a = BigQ::from_str("1/23").unwrap();
        let b = BigQ::from_str("12/3").unwrap();
        assert_ne!(of_bigq(&a), of_bigq(&b));
    }

    #[test]
    fn wide_values_are_distinguished() {
        let a = BigU::from(1u32) << 4096;
        let b = &a + &BigU::from(1u32);
        assert_ne!(of(&a), of(&b));
        assert_eq!(of(&a), of(&(BigU::from(1u32) << 4096)));
    }

    #[test]
    fn sequences_depend_on_order_and_length() {
        let one = BigU::from(1u32);
        let two = BigU::from(2u32);
        assert_ne!(
            of_slice(&[one.clone(), two.clone()]),
            of_slice(&[two.clone(), one.clone()])
        );
        assert_ne!(of_slice(&[one.clone()]), of_slice(&[one.clone(), BigU::zero()]));
        assert_ne!(of_slice(&[]), of_slice(&[BigU::zero()]));
    }

    #[test]
    fn display_is_sixteen_lowercase_hex_digits() {
        let text = of(&BigU::from(255u32)).to_string();
        assert_eq!(text.len(), 16);
        assert!(text.chars().all(|c| c.is_ascii_hexdigit() && !c.is_uppercase()));
    }
}
