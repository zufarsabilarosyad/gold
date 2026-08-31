//! Bitwise shifts.
//!
//! Each shift decomposes into a whole-limb move plus an intra-limb bit shift.
//! The intra-limb step uses a [`DoubleLimb`] window so bits crossing a limb
//! boundary are not lost. When the bit component is zero the cross-limb merge
//! is skipped entirely, which avoids an undefined `>> 32` on the limb word.

use core::ops::{Shl, ShlAssign, Shr, ShrAssign};

use crate::bigu::BigU;
use crate::{DoubleLimb, Limb, LIMB_BITS};

/// Left-shifts limbs by `bits`, returning canonical limbs.
pub(crate) fn shl_bits(a: &[Limb], bits: u32) -> Vec<Limb> {
    if a.is_empty() || bits == 0 {
        let mut out = a.to_vec();
        while let Some(&0) = out.last() {
            out.pop();
        }
        return out;
    }

    let limb_shift = (bits / LIMB_BITS) as usize;
    let bit_shift = bits % LIMB_BITS;

    let mut out = vec![0 as Limb; a.len() + limb_shift + 1];

    if bit_shift == 0 {
        // Pure whole-limb move: no cross-limb merge required.
        for (i, &limb) in a.iter().enumerate() {
            out[i + limb_shift] = limb;
        }
    } else {
        let mut carry: Limb = 0;
        for (i, &limb) in a.iter().enumerate() {
            let window = ((limb as DoubleLimb) << bit_shift) | carry as DoubleLimb;
            out[i + limb_shift] = window as Limb;
            carry = (window >> 32) as Limb;
        }
        out[a.len() + limb_shift] = carry;
    }

    while let Some(&0) = out.last() {
        out.pop();
    }
    out
}

/// Right-shifts limbs by `bits`, returning canonical limbs.
pub(crate) fn shr_bits(a: &[Limb], bits: u32) -> Vec<Limb> {
    if a.is_empty() || bits == 0 {
        let mut out = a.to_vec();
        while let Some(&0) = out.last() {
            out.pop();
        }
        return out;
    }

    let limb_shift = (bits / LIMB_BITS) as usize;
    let bit_shift = bits % LIMB_BITS;

    if limb_shift >= a.len() {
        return Vec::new();
    }

    let remaining = a.len() - limb_shift;
    let mut out = vec![0 as Limb; remaining];

    if bit_shift == 0 {
        // Pure whole-limb move; pulling in bits from the next limb would be a
        // `<< 32` overflow, so the cross-limb merge is skipped here.
        for i in 0..remaining {
            out[i] = a[i + limb_shift];
        }
    } else {
        let mut carry: Limb = 0;
        for i in (0..remaining).rev() {
            let cur = a[i + limb_shift];
            out[i] = (cur >> bit_shift) | carry;
            carry = ((cur as DoubleLimb) << (LIMB_BITS - bit_shift)) as Limb;
        }
    }

    while let Some(&0) = out.last() {
        out.pop();
    }
    out
}

impl BigU {
    /// Returns the number of trailing zero bits, i.e. the exponent of the
    /// largest power of two that divides the value (its 2-adic valuation).
    ///
    /// Zero has no set bits, so by convention this returns `None` for the zero
    /// value; every nonzero value yields `Some(k)` where `k` is finite. The
    /// scan skips whole zero limbs and then counts the trailing zeros of the
    /// first nonzero limb, so it runs in time proportional to the number of
    /// zero limbs rather than the number of zero bits.
    pub fn trailing_zeros(&self) -> Option<u64> {
        for (i, &limb) in self.limbs.iter().enumerate() {
            if limb != 0 {
                return Some(i as u64 * LIMB_BITS as u64 + limb.trailing_zeros() as u64);
            }
        }
        None
    }

    /// Returns the value of the bit at position `idx`, counting from the
    /// least-significant bit at index `0`.
    ///
    /// The value is conceptually padded with infinitely many leading zero bits,
    /// so any index at or beyond [`BigU::bit_len`] reads as `false` rather than
    /// panicking. This makes it safe to probe arbitrary bit positions, including
    /// far past the top of the number. The lookup is constant time: the index is
    /// split into a limb and an in-limb bit offset and the relevant limb is read
    /// directly.
    pub fn bit(&self, idx: u64) -> bool {
        let limb_idx = (idx / LIMB_BITS as u64) as usize;
        match self.limbs.get(limb_idx) {
            None => false,
            Some(&limb) => {
                let bit_idx = (idx % LIMB_BITS as u64) as u32;
                (limb >> bit_idx) & 1 == 1
            }
        }
    }

    /// Returns `true` when the value is exactly divisible by `2^exp`.
    ///
    /// This is a cheap query over the low bits that avoids a full division:
    /// a value is divisible by `2^exp` exactly when it has at least `exp`
    /// trailing zero bits. Zero is divisible by every power of two, so this
    /// always returns `true` for the zero value.
    pub fn is_divisible_by_pow2(&self, exp: u64) -> bool {
        match self.trailing_zeros() {
            None => true, // zero is divisible by any power of two
            Some(tz) => tz >= exp,
        }
    }

    /// Returns a copy of the value with the bit at position `idx` set to
    /// `value`, counting from the least-significant bit at index `0`.
    ///
    /// This is the transforming counterpart to [`BigU::bit`]: setting a bit that
    /// lies above the current top simply grows the value, and clearing a bit at
    /// or beyond the top is a no-op, so any `idx` is accepted without panicking.
    /// The result is always canonical — clearing the highest set bit shrinks the
    /// limb vector — which keeps equality and ordering well behaved.
    ///
    /// ```
    /// use bigu::BigU;
    /// // Setting bit 3 of 0 yields 8; clearing it again returns to 0.
    /// let v = BigU::zero().with_bit(3, true);
    /// assert_eq!(v, BigU::from(8u32));
    /// assert!(v.with_bit(3, false).is_zero());
    /// ```
    pub fn with_bit(&self, idx: u64, value: bool) -> BigU {
        let limb_idx = (idx / LIMB_BITS as u64) as usize;
        let bit_idx = (idx % LIMB_BITS as u64) as u32;
        let mask: Limb = 1 << bit_idx;

        if value {
            // Grow the limb vector with zero limbs up to the target position so
            // the bit has somewhere to live, then OR it in.
            let mut limbs = self.limbs.clone();
            if limb_idx >= limbs.len() {
                limbs.resize(limb_idx + 1, 0);
            }
            limbs[limb_idx] |= mask;
            BigU::from_limbs(limbs)
        } else {
            // Clearing a bit beyond the top limb changes nothing; otherwise mask
            // it off and re-canonicalize in case the top limb became zero.
            if limb_idx >= self.limbs.len() {
                return self.clone();
            }
            let mut limbs = self.limbs.clone();
            limbs[limb_idx] &= !mask;
            BigU::from_limbs(limbs)
        }
    }

    /// Reference-based left shift used internally.
    pub(crate) fn shl_ref(&self, bits: u32) -> BigU {
        BigU::from_limbs(shl_bits(&self.limbs, bits))
    }

    /// Reference-based right shift used internally.
    pub(crate) fn shr_ref(&self, bits: u32) -> BigU {
        BigU::from_limbs(shr_bits(&self.limbs, bits))
    }
}

impl Shl<u32> for BigU {
    type Output = BigU;
    fn shl(self, bits: u32) -> BigU {
        self.shl_ref(bits)
    }
}

impl Shl<u32> for &BigU {
    type Output = BigU;
    fn shl(self, bits: u32) -> BigU {
        self.shl_ref(bits)
    }
}

impl Shr<u32> for BigU {
    type Output = BigU;
    fn shr(self, bits: u32) -> BigU {
        self.shr_ref(bits)
    }
}

impl Shr<u32> for &BigU {
    type Output = BigU;
    fn shr(self, bits: u32) -> BigU {
        self.shr_ref(bits)
    }
}

impl ShlAssign<u32> for BigU {
    fn shl_assign(&mut self, bits: u32) {
        *self = self.shl_ref(bits);
    }
}

impl ShrAssign<u32> for BigU {
    fn shr_assign(&mut self, bits: u32) {
        *self = self.shr_ref(bits);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::str::FromStr;

    fn b(s: &str) -> BigU {
        BigU::from_str(s).unwrap()
    }

    #[test]
    fn shl_within_limb() {
        assert_eq!(BigU::from(1u32) << 1, BigU::from(2u32));
        assert_eq!(BigU::from(1u32) << 31, BigU::from(0x8000_0000u32));
        assert_eq!(BigU::from(1u32) << 32, BigU::from(0x1_0000_0000u64));
    }

    #[test]
    fn shl_zero_is_identity() {
        let x = b("123456789012345678901234567890");
        assert_eq!(&x << 0, x);
    }

    #[test]
    fn shr_drops_low_limb_on_multiple_of_32() {
        // x >> 32 must equal dropping the lowest limb exactly.
        let x = BigU::from(0xAAAA_BBBB_CCCC_DDDDu64);
        assert_eq!(&x >> 32, BigU::from(0xAAAA_BBBBu32));
    }

    #[test]
    fn shl_then_shr_roundtrip_multiple_of_32() {
        // (x << 64) >> 64 == x — the exact-multiple-of-32 whole-limb path.
        let x = b("340282366920938463463374607431768211455"); // 2^128 - 1
        assert_eq!((&x << 64) >> 64, x);
    }

    #[test]
    fn shl_33_equiv_shr_1_relation() {
        // (x << 33) >> 1 == x << 32 — mixes the cross-limb and whole-limb paths.
        let x = b("987654321987654321987654321");
        assert_eq!((&x << 33) >> 1, &x << 32);
    }

    #[test]
    fn shr_past_end_is_zero() {
        let x = BigU::from(0xFFu32);
        assert!((x >> 100).is_zero());
    }

    #[test]
    fn shl_shr_general_roundtrip() {
        let x = b("123456789012345678901234567890123456789");
        for &s in &[1u32, 5, 31, 32, 33, 63, 64, 65, 96, 100] {
            assert_eq!((&x << s) >> s, x, "roundtrip failed for shift {s}");
        }
    }

    #[test]
    fn shl_equals_mul_by_power_of_two() {
        let x = b("314159265358979323846");
        let shifted = &x << 10;
        let multiplied = &x * &BigU::from(1024u32);
        assert_eq!(shifted, multiplied);
    }

    #[test]
    fn assign_variants() {
        let mut x = BigU::from(1u32);
        x <<= 64;
        assert_eq!(x, BigU::from(0x1_0000_0000_0000_0000u128));
        x >>= 32;
        assert_eq!(x, BigU::from(0x1_0000_0000u64));
    }

    #[test]
    fn shr_zero_value() {
        assert!((BigU::zero() >> 5).is_zero());
        assert!((BigU::zero() << 5).is_zero());
    }

    #[test]
    fn trailing_zeros_basic() {
        assert_eq!(BigU::zero().trailing_zeros(), None);
        assert_eq!(BigU::one().trailing_zeros(), Some(0));
        assert_eq!(BigU::from(2u32).trailing_zeros(), Some(1));
        assert_eq!(BigU::from(8u32).trailing_zeros(), Some(3));
        // 12 = 0b1100 has two trailing zeros.
        assert_eq!(BigU::from(12u32).trailing_zeros(), Some(2));
    }

    #[test]
    fn trailing_zeros_crosses_whole_limbs() {
        // 1 << 64 has exactly 64 trailing zeros and skips two whole zero limbs.
        let v = &BigU::one() << 64;
        assert_eq!(v.trailing_zeros(), Some(64));
        // 1 << 70 lands inside the third limb.
        let v = &BigU::one() << 70;
        assert_eq!(v.trailing_zeros(), Some(70));
    }

    #[test]
    fn trailing_zeros_matches_shift_factor() {
        // Multiplying an odd value by 2^k gives exactly k trailing zeros.
        let odd = b("123456789123456789123456789");
        assert_eq!(odd.trailing_zeros(), Some(0));
        for k in [1u32, 5, 31, 32, 33, 96, 200] {
            let shifted = &odd << k;
            assert_eq!(shifted.trailing_zeros(), Some(k as u64), "k = {k}");
        }
    }

    #[test]
    fn bit_reads_individual_bits() {
        // 0b1010 == 10: bits 1 and 3 are set, 0 and 2 are clear.
        let v = BigU::from(0b1010u32);
        assert!(!v.bit(0));
        assert!(v.bit(1));
        assert!(!v.bit(2));
        assert!(v.bit(3));
    }

    #[test]
    fn bit_out_of_range_is_false() {
        // Zero has no set bits at any index.
        assert!(!BigU::zero().bit(0));
        assert!(!BigU::zero().bit(1000));
        // Reading past the top of a value yields false, never a panic.
        let v = BigU::from(1u32);
        assert!(v.bit(0));
        assert!(!v.bit(1));
        assert!(!v.bit(64));
        assert!(!v.bit(u64::MAX));
    }

    #[test]
    fn bit_crosses_limb_boundaries() {
        // A single high bit set by shifting must be readable at its exact index.
        for k in [0u32, 1, 31, 32, 33, 63, 64, 65, 96, 130] {
            let v = &BigU::one() << k;
            assert!(v.bit(k as u64), "bit {k} should be set");
            if k > 0 {
                assert!(!v.bit(k as u64 - 1), "bit {} should be clear", k - 1);
            }
            assert!(!v.bit(k as u64 + 1), "bit {} should be clear", k + 1);
        }
    }

    #[test]
    fn bit_agrees_with_bit_len_and_trailing_zeros() {
        // The lowest set bit reported by trailing_zeros must read as set, and the
        // bit just above the top (bit_len) must read as clear.
        let v = b("123456789012345678901234567890");
        let lo = v.trailing_zeros().unwrap();
        assert!(v.bit(lo));
        assert!(v.bit(v.bit_len() - 1), "top bit must be set");
        assert!(!v.bit(v.bit_len()), "bit above the top must be clear");
    }

    #[test]
    fn with_bit_sets_and_clears() {
        // Set individual bits to build 0b1010 == 10, then clear one back out.
        let v = BigU::zero().with_bit(1, true).with_bit(3, true);
        assert_eq!(v, BigU::from(0b1010u32));
        assert_eq!(v.with_bit(1, false), BigU::from(0b1000u32));
        // Setting an already-set bit is idempotent.
        assert_eq!(v.with_bit(3, true), v);
    }

    #[test]
    fn with_bit_clear_above_top_is_noop() {
        let v = BigU::from(5u32);
        assert_eq!(v.with_bit(100, false), v);
        // Clearing the only set bit collapses to canonical zero.
        let cleared = BigU::one().with_bit(0, false);
        assert!(cleared.is_zero());
        assert_eq!(cleared.limbs.len(), 0);
    }

    #[test]
    fn with_bit_grows_across_limbs() {
        // Setting a high bit on zero must match a left shift of one.
        for k in [0u64, 1, 31, 32, 33, 64, 65, 130] {
            let v = BigU::zero().with_bit(k, true);
            assert_eq!(v, &BigU::one() << k as u32, "set bit {k}");
            assert!(v.bit(k), "bit {k} should read back as set");
        }
    }

    #[test]
    fn with_bit_clearing_top_recanonicalizes() {
        // Clearing the most-significant limb's only bit must drop the limb so the
        // representation stays canonical.
        let v = &BigU::one() << 64; // single bit in the third limb
        let cleared = v.with_bit(64, false);
        assert!(cleared.is_zero());
    }

    #[test]
    fn with_bit_agrees_with_bit_query() {
        // For an arbitrary value, toggling a bit and reading it back is
        // consistent with the bit accessor across the whole width.
        let v = b("123456789012345678901234567890");
        for idx in 0..v.bit_len() + 4 {
            let set = v.with_bit(idx, true);
            assert!(set.bit(idx));
            let clr = v.with_bit(idx, false);
            assert!(!clr.bit(idx));
            // Flipping a bit on then off returns to a value with that bit clear,
            // matching whatever the original had elsewhere.
            assert_eq!(set.with_bit(idx, v.bit(idx)), v);
        }
    }

    #[test]
    fn is_divisible_by_pow2_basic() {
        assert!(BigU::zero().is_divisible_by_pow2(100));
        let v = &BigU::one() << 40; // 2^40
        assert!(v.is_divisible_by_pow2(0));
        assert!(v.is_divisible_by_pow2(40));
        assert!(!v.is_divisible_by_pow2(41));
        // An odd value is divisible only by 2^0.
        let odd = BigU::from(7u32);
        assert!(odd.is_divisible_by_pow2(0));
        assert!(!odd.is_divisible_by_pow2(1));
    }
}
