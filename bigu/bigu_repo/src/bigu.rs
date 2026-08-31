//! The [`BigU`] value type and its structural operations.

use core::fmt;

use crate::error::{Error, Result};
use crate::{Limb, LIMB_BITS};

/// An arbitrary-precision unsigned integer.
///
/// Internally the value is a little-endian vector of base-`2^32` limbs. The
/// representation is always kept canonical: the highest limb is never zero, so
/// the integer zero is the empty vector. Two `BigU` values are equal exactly
/// when their canonical limb vectors are equal, which makes `Eq`, `Ord` and
/// `Hash` behave as plain integer comparisons.
#[derive(Clone, Default)]
pub struct BigU {
    /// Little-endian limbs; canonical means `limbs.last() != Some(&0)`.
    pub(crate) limbs: Vec<Limb>,
}

impl BigU {
    /// Builds a value directly from a limb vector and canonicalizes it.
    pub(crate) fn from_limbs(limbs: Vec<Limb>) -> BigU {
        let mut v = BigU { limbs };
        v.normalize();
        v
    }

    /// Strips trailing zero limbs so the representation stays canonical.
    ///
    /// All internal routines that build a fresh limb vector funnel through here
    /// before the value escapes, which keeps the no-leading-zero invariant from
    /// ever being observable.
    pub(crate) fn normalize(&mut self) {
        while let Some(&0) = self.limbs.last() {
            self.limbs.pop();
        }
    }

    /// The additive identity, `0`.
    pub fn zero() -> BigU {
        BigU { limbs: Vec::new() }
    }

    /// The multiplicative identity, `1`.
    pub fn one() -> BigU {
        BigU { limbs: vec![1] }
    }

    /// Returns `true` when the value is exactly zero.
    pub fn is_zero(&self) -> bool {
        self.limbs.is_empty()
    }

    /// The position of the most-significant set bit plus one, i.e. the number
    /// of bits required to represent the value. Zero has a bit length of 0.
    pub fn bit_len(&self) -> u64 {
        match self.limbs.last() {
            None => 0,
            Some(&top) => {
                let full = (self.limbs.len() as u64 - 1) * LIMB_BITS as u64;
                full + (LIMB_BITS - top.leading_zeros()) as u64
            }
        }
    }

    /// The population count: how many bits are set across all limbs.
    pub fn count_ones(&self) -> u64 {
        self.limbs.iter().map(|l| l.count_ones() as u64).sum()
    }

    /// Builds a value from its big-endian byte representation, the most
    /// significant byte first.
    ///
    /// This is the natural inverse of a big-endian serialization: an empty slice
    /// and any all-zero slice both decode to zero, and leading zero bytes are
    /// ignored (they only affect the canonical form, never the value). Bytes are
    /// packed four at a time into the little-endian `2^32` limbs, so a slice of
    /// length `n` yields at most `ceil(n / 4)` limbs and the result is always
    /// canonical.
    ///
    /// ```
    /// use bigu::BigU;
    /// // 0x01_02_03_04 == 16909060.
    /// assert_eq!(BigU::from_bytes_be(&[1, 2, 3, 4]), BigU::from(16909060u32));
    /// assert!(BigU::from_bytes_be(&[]).is_zero());
    /// assert!(BigU::from_bytes_be(&[0, 0, 0]).is_zero());
    /// ```
    pub fn from_bytes_be(bytes: &[u8]) -> BigU {
        // Skip leading zero bytes so the chunking below lines up with the value
        // rather than its padding; an all-zero (or empty) slice falls through to
        // the empty limb vector, which is canonical zero.
        let start = bytes.iter().position(|&b| b != 0).unwrap_or(bytes.len());
        let trimmed = &bytes[start..];
        if trimmed.is_empty() {
            return BigU::zero();
        }

        let mut limbs = Vec::with_capacity(trimmed.len() / 4 + 1);
        // Consume the bytes from least- to most-significant in groups of four,
        // each group forming one little-endian limb.
        let mut chunk = [0u8; 4];
        let mut filled = 0usize;
        for &byte in trimmed.iter().rev() {
            chunk[filled] = byte;
            filled += 1;
            if filled == 4 {
                limbs.push(Limb::from_le_bytes(chunk));
                chunk = [0u8; 4];
                filled = 0;
            }
        }
        if filled != 0 {
            limbs.push(Limb::from_le_bytes(chunk));
        }
        BigU::from_limbs(limbs)
    }

    /// Raises `self` to the `exp` power using binary exponentiation.
    ///
    /// `x.pow(0)` is `1` for every `x`, including zero.
    pub fn pow(&self, exp: u32) -> BigU {
        let mut result = BigU::one();
        let mut base = self.clone();
        let mut e = exp;
        while e > 0 {
            if e & 1 == 1 {
                result = &result * &base;
            }
            e >>= 1;
            if e > 0 {
                base = &base * &base;
            }
        }
        result
    }

    /// Returns the integer square root: the largest `r` such that
    /// `r * r <= self`.
    ///
    /// This is the floor of the real square root. For `0` and `1` the result is
    /// the value itself. The computation uses Newton's method on integers,
    /// starting from an over-estimate derived from the bit length so the
    /// iteration converges from above and is guaranteed to terminate. The
    /// returned `r` always satisfies `r*r <= self < (r+1)*(r+1)`.
    pub fn sqrt(&self) -> BigU {
        if self.limbs.len() <= 1 {
            // Fits in a single limb (or is zero); use the primitive square root
            // of the lone limb, which is exact and cannot overflow.
            let v = self.limbs.first().copied().unwrap_or(0) as u64;
            return BigU::from((v as f64).sqrt() as u32).adjust_sqrt(self);
        }

        // Initial guess: 2^ceil(bit_len / 2) is at least the true root, so the
        // Newton iteration below decreases monotonically toward the answer.
        let half_bits = (self.bit_len() + 1) / 2;
        let mut x = &BigU::one() << half_bits as u32;

        loop {
            // next = (x + self / x) / 2. `x` is nonzero here, so the division is
            // always valid and never panics.
            let (q, _) = self.div_rem(&x).expect("guess is nonzero");
            let next = &(&x + &q) >> 1;
            if next >= x {
                // Newton's method for floor-sqrt stops increasing once it has
                // reached the floor; `x` now holds the answer.
                break;
            }
            x = next;
        }
        x
    }

    /// Returns the big-endian byte representation, the most significant byte
    /// first, with no leading zero padding.
    ///
    /// This is the exact inverse of [`BigU::from_bytes_be`]: feeding the result
    /// back through that constructor reproduces the value. Zero serializes to an
    /// empty vector (it has no significant bytes), and every nonzero value
    /// produces a slice whose first byte is itself nonzero, so the encoding is
    /// minimal. The limbs are emitted from most- to least-significant and only
    /// the meaningful bytes of the top limb are kept, which is what makes the
    /// round trip exact.
    ///
    /// ```
    /// use bigu::BigU;
    /// assert_eq!(BigU::from(16909060u32).to_bytes_be(), vec![1, 2, 3, 4]);
    /// assert!(BigU::zero().to_bytes_be().is_empty());
    /// // Round-trips with the big-endian constructor.
    /// let v = BigU::from(0xDEAD_BEEF_u32);
    /// assert_eq!(BigU::from_bytes_be(&v.to_bytes_be()), v);
    /// ```
    pub fn to_bytes_be(&self) -> Vec<u8> {
        if self.is_zero() {
            return Vec::new();
        }

        // Emit the most-significant limb without its leading zero bytes, then
        // every remaining limb in full so the byte count stays minimal yet the
        // low limbs keep their interior zeros.
        let mut out = Vec::with_capacity(self.limbs.len() * 4);
        let top = *self.limbs.last().expect("nonzero value has a top limb");
        let top_bytes = top.to_be_bytes();
        let first = top.leading_zeros() as usize / 8;
        out.extend_from_slice(&top_bytes[first..]);
        for &limb in self.limbs.iter().rev().skip(1) {
            out.extend_from_slice(&limb.to_be_bytes());
        }
        out
    }

    /// Returns `true` when `self` is a perfect square, i.e. there exists an
    /// integer `r` with `r * r == self`.
    ///
    /// This reuses the floor square root: the value is a perfect square
    /// exactly when squaring that floor reproduces the original value.
    ///
    /// ```
    /// use bigu::BigU;
    /// assert!(BigU::zero().is_perfect_square());
    /// assert!(BigU::from(144u32).is_perfect_square());
    /// assert!(!BigU::from(145u32).is_perfect_square());
    /// let big = BigU::from(10u32).pow(30);
    /// assert!((&big * &big).is_perfect_square());
    /// ```
    pub fn is_perfect_square(&self) -> bool {
        let r = self.sqrt();
        &(&r * &r) == self
    }

    /// Corrects a primitive-derived square-root estimate so it is exactly the
    /// floor of the true root of `target`, nudging by one in either direction to
    /// absorb floating-point rounding.
    fn adjust_sqrt(self, target: &BigU) -> BigU {
        let mut r = self;
        // Step down while the square overshoots the target. `r` is at least one
        // here because zero never overshoots a non-negative target, so the
        // subtraction cannot underflow.
        while &(&r * &r) > target {
            r = r.checked_sub(&BigU::one()).unwrap_or_else(|_| BigU::zero());
        }
        // Step up while one more still fits.
        loop {
            let next = &r + &BigU::one();
            if &(&next * &next) <= target {
                r = next;
            } else {
                break;
            }
        }
        r
    }
}

impl From<u32> for BigU {
    fn from(v: u32) -> BigU {
        if v == 0 {
            BigU::zero()
        } else {
            BigU { limbs: vec![v] }
        }
    }
}

impl From<u64> for BigU {
    fn from(v: u64) -> BigU {
        let lo = v as Limb;
        let hi = (v >> LIMB_BITS) as Limb;
        BigU::from_limbs(vec![lo, hi])
    }
}

impl From<u128> for BigU {
    fn from(v: u128) -> BigU {
        let limbs = vec![
            v as Limb,
            (v >> 32) as Limb,
            (v >> 64) as Limb,
            (v >> 96) as Limb,
        ];
        BigU::from_limbs(limbs)
    }
}

impl From<usize> for BigU {
    fn from(v: usize) -> BigU {
        BigU::from(v as u64)
    }
}

impl TryFrom<&BigU> for u64 {
    type Error = Error;

    fn try_from(v: &BigU) -> Result<u64> {
        match v.limbs.len() {
            0 => Ok(0),
            1 => Ok(v.limbs[0] as u64),
            2 => Ok((v.limbs[0] as u64) | ((v.limbs[1] as u64) << LIMB_BITS)),
            _ => Err(Error::Overflow),
        }
    }
}

impl TryFrom<&BigU> for u128 {
    type Error = Error;

    fn try_from(v: &BigU) -> Result<u128> {
        if v.limbs.len() > 4 {
            return Err(Error::Overflow);
        }
        let mut acc: u128 = 0;
        for (i, &limb) in v.limbs.iter().enumerate() {
            acc |= (limb as u128) << (LIMB_BITS as usize * i);
        }
        Ok(acc)
    }
}

impl TryFrom<&BigU> for u32 {
    type Error = Error;

    fn try_from(v: &BigU) -> Result<u32> {
        match v.limbs.len() {
            0 => Ok(0),
            1 => Ok(v.limbs[0]),
            _ => Err(Error::Overflow),
        }
    }
}

impl fmt::Debug for BigU {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // The decimal rendering is the friendliest debug form for a number.
        match self.to_str_radix(10) {
            Ok(s) => write!(f, "BigU({s})"),
            Err(_) => write!(f, "BigU({:?})", self.limbs),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zero_and_one_are_canonical() {
        assert!(BigU::zero().is_zero());
        assert_eq!(BigU::zero().limbs.len(), 0);
        assert!(!BigU::one().is_zero());
        assert_eq!(BigU::one().limbs, vec![1]);
    }

    #[test]
    fn from_u32_zero_is_empty() {
        assert!(BigU::from(0u32).is_zero());
        assert_eq!(BigU::from(0u32).limbs, Vec::<Limb>::new());
    }

    #[test]
    fn from_u64_strips_high_zero_limb() {
        let v = BigU::from(5u64);
        assert_eq!(v.limbs, vec![5]);
        let v = BigU::from(0u64);
        assert!(v.is_zero());
    }

    #[test]
    fn from_u64_keeps_both_limbs() {
        let v = BigU::from(0x1_0000_0001u64);
        assert_eq!(v.limbs, vec![1, 1]);
    }

    #[test]
    fn from_u128_canonicalizes() {
        let v = BigU::from(0xFFu128);
        assert_eq!(v.limbs, vec![0xFF]);
        let v = BigU::from(u128::MAX);
        assert_eq!(v.limbs, vec![u32::MAX, u32::MAX, u32::MAX, u32::MAX]);
    }

    #[test]
    fn bit_len_basic() {
        assert_eq!(BigU::zero().bit_len(), 0);
        assert_eq!(BigU::one().bit_len(), 1);
        assert_eq!(BigU::from(2u32).bit_len(), 2);
        assert_eq!(BigU::from(0xFFFF_FFFFu32).bit_len(), 32);
        assert_eq!(BigU::from(0x1_0000_0000u64).bit_len(), 33);
    }

    #[test]
    fn count_ones_basic() {
        assert_eq!(BigU::zero().count_ones(), 0);
        assert_eq!(BigU::from(0xFFu32).count_ones(), 8);
        assert_eq!(BigU::from(u128::MAX).count_ones(), 128);
    }

    #[test]
    fn try_into_u64_bounds() {
        let small = BigU::from(123u64);
        assert_eq!(u64::try_from(&small).unwrap(), 123);
        let max = BigU::from(u64::MAX);
        assert_eq!(u64::try_from(&max).unwrap(), u64::MAX);
        let too_big = BigU::from(u128::MAX);
        assert_eq!(u64::try_from(&too_big), Err(Error::Overflow));
    }

    #[test]
    fn try_into_u32_bounds() {
        assert_eq!(u32::try_from(&BigU::zero()).unwrap(), 0);
        assert_eq!(u32::try_from(&BigU::from(7u32)).unwrap(), 7);
        assert_eq!(u32::try_from(&BigU::from(u64::MAX)), Err(Error::Overflow));
    }

    #[test]
    fn pow_basics() {
        assert_eq!(BigU::from(2u32).pow(0), BigU::one());
        assert_eq!(BigU::from(0u32).pow(0), BigU::one());
        assert_eq!(BigU::from(2u32).pow(10), BigU::from(1024u32));
        assert_eq!(BigU::from(10u32).pow(3), BigU::from(1000u32));
        // 2^128 fits in five limbs and is a well known value.
        let p = BigU::from(2u32).pow(128);
        assert_eq!(
            p.to_str_radix(10).unwrap(),
            "340282366920938463463374607431768211456"
        );
    }

    #[test]
    fn debug_renders_decimal() {
        assert_eq!(format!("{:?}", BigU::from(42u32)), "BigU(42)");
        assert_eq!(format!("{:?}", BigU::zero()), "BigU(0)");
    }

    #[test]
    fn sqrt_small_perfect_squares() {
        assert!(BigU::zero().sqrt().is_zero());
        assert_eq!(BigU::one().sqrt(), BigU::one());
        assert_eq!(BigU::from(4u32).sqrt(), BigU::from(2u32));
        assert_eq!(BigU::from(144u32).sqrt(), BigU::from(12u32));
        assert_eq!(BigU::from(1_000_000u32).sqrt(), BigU::from(1000u32));
    }

    #[test]
    fn sqrt_floors_non_squares() {
        assert_eq!(BigU::from(2u32).sqrt(), BigU::one());
        assert_eq!(BigU::from(3u32).sqrt(), BigU::one());
        assert_eq!(BigU::from(8u32).sqrt(), BigU::from(2u32));
        assert_eq!(BigU::from(15u32).sqrt(), BigU::from(3u32));
        assert_eq!(BigU::from(99u32).sqrt(), BigU::from(9u32));
    }

    #[test]
    fn sqrt_large_perfect_square_roundtrips() {
        // (10^40)^2 == 10^80, whose floor-sqrt must recover 10^40 exactly.
        let root = BigU::from(10u32).pow(40);
        let square = &root * &root;
        assert_eq!(square.sqrt(), root);
    }

    #[test]
    fn sqrt_invariant_brackets_value() {
        // For several large values, r*r <= v < (r+1)*(r+1).
        let mut x: u64 = 0xACE1_2345_6789;
        for _ in 0..50 {
            x = x.wrapping_mul(6364136223846793005).wrapping_add(1);
            let v = BigU::from(x as u128) * BigU::from((x ^ 0x5555) as u128);
            let r = v.sqrt();
            let r1 = &r + &BigU::one();
            assert!(&(&r * &r) <= &v, "lower bound failed");
            assert!(&(&r1 * &r1) > &v, "upper bound failed");
        }
    }

    #[test]
    fn sqrt_just_below_perfect_square() {
        // One less than a perfect square must floor to root - 1.
        let root = BigU::from(123456u32);
        let square = &root * &root;
        let below = square.checked_sub(&BigU::one()).unwrap();
        assert_eq!(below.sqrt(), &root - &BigU::one());
    }

    #[test]
    fn is_perfect_square_small_cases() {
        assert!(BigU::zero().is_perfect_square());
        assert!(BigU::one().is_perfect_square());
        assert!(BigU::from(4u32).is_perfect_square());
        assert!(BigU::from(144u32).is_perfect_square());
        assert!(!BigU::from(2u32).is_perfect_square());
        assert!(!BigU::from(143u32).is_perfect_square());
        assert!(!BigU::from(145u32).is_perfect_square());
    }

    #[test]
    fn is_perfect_square_large_values() {
        let root = BigU::from(10u32).pow(30);
        let square = &root * &root;
        assert!(square.is_perfect_square());
        let one_less = square.checked_sub(&BigU::one()).unwrap();
        let one_more = &square + &BigU::one();
        assert!(!one_less.is_perfect_square());
        assert!(!one_more.is_perfect_square());
    }

    #[test]
    fn from_bytes_be_empty_and_zero() {
        assert!(BigU::from_bytes_be(&[]).is_zero());
        assert!(BigU::from_bytes_be(&[0]).is_zero());
        assert!(BigU::from_bytes_be(&[0, 0, 0, 0, 0]).is_zero());
    }

    #[test]
    fn from_bytes_be_basic_values() {
        assert_eq!(BigU::from_bytes_be(&[0xFF]), BigU::from(255u32));
        assert_eq!(BigU::from_bytes_be(&[1, 0]), BigU::from(256u32));
        // 0x01_02_03_04 packs into a single limb.
        let v = BigU::from_bytes_be(&[1, 2, 3, 4]);
        assert_eq!(v, BigU::from(0x0102_0304u32));
        assert_eq!(v.limbs, vec![0x0102_0304]);
    }

    #[test]
    fn from_bytes_be_ignores_leading_zeros() {
        assert_eq!(
            BigU::from_bytes_be(&[0, 0, 1, 2, 3, 4]),
            BigU::from_bytes_be(&[1, 2, 3, 4])
        );
    }

    #[test]
    fn from_bytes_be_crosses_limb_boundary() {
        // Five bytes span two limbs: high limb 0x01, low limb 0x02030405.
        let v = BigU::from_bytes_be(&[1, 2, 3, 4, 5]);
        assert_eq!(v.limbs, vec![0x0203_0405, 0x01]);
        assert_eq!(v, BigU::from(0x01_0203_0405u64));
    }

    #[test]
    fn to_bytes_be_empty_and_minimal() {
        assert!(BigU::zero().to_bytes_be().is_empty());
        // Single-byte values carry exactly one byte, with no leading zero.
        assert_eq!(BigU::from(0xFFu32).to_bytes_be(), vec![0xFF]);
        assert_eq!(BigU::from(1u32).to_bytes_be(), vec![1]);
        // 256 needs two bytes and the high byte is significant.
        assert_eq!(BigU::from(256u32).to_bytes_be(), vec![1, 0]);
    }

    #[test]
    fn to_bytes_be_packs_full_limb() {
        // A value filling exactly one limb yields four bytes, most significant
        // first.
        assert_eq!(
            BigU::from(0x0102_0304u32).to_bytes_be(),
            vec![1, 2, 3, 4]
        );
    }

    #[test]
    fn to_bytes_be_keeps_interior_zeros() {
        // Five-byte value spanning two limbs: the low limb's interior zeros must
        // survive while the top limb is trimmed to its single meaningful byte.
        let v = BigU::from(0x01_0203_0405u64);
        assert_eq!(v.to_bytes_be(), vec![1, 2, 3, 4, 5]);
    }

    #[test]
    fn to_bytes_be_roundtrips_with_from_bytes_be() {
        // Several spans of widths, including ones with embedded zero bytes, must
        // survive a full encode/decode round trip.
        for value in [
            BigU::zero(),
            BigU::from(7u32),
            BigU::from(0xFFu32),
            BigU::from(0x1234_5678u32),
            BigU::from(u64::MAX),
            BigU::from(u128::MAX),
            BigU::from(2u32).pow(200),
            BigU::from_str_radix("123456789012345678901234567890", 10).unwrap(),
        ] {
            let bytes = value.to_bytes_be();
            assert_eq!(BigU::from_bytes_be(&bytes), value);
            // The encoding is minimal: a nonzero value never starts with a zero.
            if !value.is_zero() {
                assert_ne!(bytes[0], 0, "encoding must not have a leading zero");
            }
        }
    }

    #[test]
    fn from_bytes_be_matches_radix_parse() {
        // A 16-byte (128-bit) value decoded from bytes must equal the same value
        // parsed from its decimal string.
        let bytes: [u8; 16] = [
            0x0F, 0x1E, 0x2D, 0x3C, 0x4B, 0x5A, 0x69, 0x78, 0x87, 0x96, 0xA5, 0xB4, 0xC3, 0xD2,
            0xE1, 0xF0,
        ];
        let mut expected = 0u128;
        for &byte in &bytes {
            expected = (expected << 8) | byte as u128;
        }
        assert_eq!(BigU::from_bytes_be(&bytes), BigU::from(expected));
    }
}
