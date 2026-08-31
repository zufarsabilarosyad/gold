//! Bitwise AND, OR and XOR.
//!
//! The values are unsigned and conceptually padded with infinitely many leading
//! zero bits, so combining operands of different limb counts just treats the
//! missing high limbs of the shorter one as zero. AND therefore truncates to the
//! shorter operand, while OR and XOR keep the longer one's high limbs. Every
//! result is canonicalized, since AND and XOR can easily clear the top limbs.

use core::ops::{BitAnd, BitAndAssign, BitOr, BitOrAssign, BitXor, BitXorAssign};

use crate::bigu::BigU;
use crate::Limb;

/// Bitwise AND of two little-endian limb slices.
pub(crate) fn and_limbs(a: &[Limb], b: &[Limb]) -> Vec<Limb> {
    // Beyond the shorter operand every bit is zero, so the result cannot be
    // longer than that operand.
    let n = a.len().min(b.len());
    (0..n).map(|i| a[i] & b[i]).collect()
}

/// Bitwise OR of two little-endian limb slices.
pub(crate) fn or_limbs(a: &[Limb], b: &[Limb]) -> Vec<Limb> {
    let (long, short) = if a.len() >= b.len() { (a, b) } else { (b, a) };
    let mut out = long.to_vec();
    for i in 0..short.len() {
        out[i] |= short[i];
    }
    out
}

/// Bitwise XOR of two little-endian limb slices.
pub(crate) fn xor_limbs(a: &[Limb], b: &[Limb]) -> Vec<Limb> {
    let (long, short) = if a.len() >= b.len() { (a, b) } else { (b, a) };
    let mut out = long.to_vec();
    for i in 0..short.len() {
        out[i] ^= short[i];
    }
    out
}

impl BigU {
    /// Bitwise AND of `self` and `other`.
    ///
    /// Both operands are treated as having infinitely many leading zero bits, so
    /// the result never has more bits than the smaller operand and
    /// `x & 0 == 0` for every `x`.
    ///
    /// ```
    /// use bigu::BigU;
    /// assert_eq!(BigU::from(0b1100u32).bit_and(&BigU::from(0b1010u32)), BigU::from(0b1000u32));
    /// assert!(BigU::from(255u32).bit_and(&BigU::zero()).is_zero());
    /// ```
    pub fn bit_and(&self, other: &BigU) -> BigU {
        BigU::from_limbs(and_limbs(&self.limbs, &other.limbs))
    }

    /// Bitwise OR of `self` and `other`.
    ///
    /// ```
    /// use bigu::BigU;
    /// assert_eq!(BigU::from(0b1100u32).bit_or(&BigU::from(0b1010u32)), BigU::from(0b1110u32));
    /// ```
    pub fn bit_or(&self, other: &BigU) -> BigU {
        BigU::from_limbs(or_limbs(&self.limbs, &other.limbs))
    }

    /// Bitwise XOR of `self` and `other`.
    ///
    /// `x ^ x` is zero for every `x`, which is the case that most needs the
    /// canonicalization: all limbs cancel and the result must come back as the
    /// empty limb vector.
    ///
    /// ```
    /// use bigu::BigU;
    /// assert_eq!(BigU::from(0b1100u32).bit_xor(&BigU::from(0b1010u32)), BigU::from(0b0110u32));
    /// let v = BigU::from(2u32).pow(200);
    /// assert!(v.bit_xor(&v).is_zero());
    /// ```
    pub fn bit_xor(&self, other: &BigU) -> BigU {
        BigU::from_limbs(xor_limbs(&self.limbs, &other.limbs))
    }
}

impl BitAnd for BigU {
    type Output = BigU;
    fn bitand(self, rhs: BigU) -> BigU {
        self.bit_and(&rhs)
    }
}

impl BitAnd<&BigU> for &BigU {
    type Output = BigU;
    fn bitand(self, rhs: &BigU) -> BigU {
        self.bit_and(rhs)
    }
}

impl BitOr for BigU {
    type Output = BigU;
    fn bitor(self, rhs: BigU) -> BigU {
        self.bit_or(&rhs)
    }
}

impl BitOr<&BigU> for &BigU {
    type Output = BigU;
    fn bitor(self, rhs: &BigU) -> BigU {
        self.bit_or(rhs)
    }
}

impl BitXor for BigU {
    type Output = BigU;
    fn bitxor(self, rhs: BigU) -> BigU {
        self.bit_xor(&rhs)
    }
}

impl BitXor<&BigU> for &BigU {
    type Output = BigU;
    fn bitxor(self, rhs: &BigU) -> BigU {
        self.bit_xor(rhs)
    }
}

impl BitAndAssign for BigU {
    fn bitand_assign(&mut self, rhs: BigU) {
        *self = self.bit_and(&rhs);
    }
}

impl BitAndAssign<&BigU> for BigU {
    fn bitand_assign(&mut self, rhs: &BigU) {
        *self = self.bit_and(rhs);
    }
}

impl BitOrAssign for BigU {
    fn bitor_assign(&mut self, rhs: BigU) {
        *self = self.bit_or(&rhs);
    }
}

impl BitOrAssign<&BigU> for BigU {
    fn bitor_assign(&mut self, rhs: &BigU) {
        *self = self.bit_or(rhs);
    }
}

impl BitXorAssign for BigU {
    fn bitxor_assign(&mut self, rhs: BigU) {
        *self = self.bit_xor(&rhs);
    }
}

impl BitXorAssign<&BigU> for BigU {
    fn bitxor_assign(&mut self, rhs: &BigU) {
        *self = self.bit_xor(rhs);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use core::str::FromStr;

    #[test]
    fn and_or_xor_small() {
        let a = BigU::from(0b1100u32);
        let b = BigU::from(0b1010u32);
        assert_eq!(a.bit_and(&b), BigU::from(0b1000u32));
        assert_eq!(a.bit_or(&b), BigU::from(0b1110u32));
        assert_eq!(a.bit_xor(&b), BigU::from(0b0110u32));
    }

    #[test]
    fn zero_operand_identities() {
        let a = BigU::from(0xDEAD_BEEFu32);
        assert!(a.bit_and(&BigU::zero()).is_zero());
        assert!(BigU::zero().bit_and(&a).is_zero());
        assert_eq!(a.bit_or(&BigU::zero()), a);
        assert_eq!(BigU::zero().bit_or(&a), a);
        assert_eq!(a.bit_xor(&BigU::zero()), a);
        assert!(BigU::zero().bit_xor(&BigU::zero()).is_zero());
    }

    #[test]
    fn one_operand_masks_low_bit() {
        let odd = BigU::from(7u32);
        let even = BigU::from(8u32);
        assert_eq!(odd.bit_and(&BigU::one()), BigU::one());
        assert!(even.bit_and(&BigU::one()).is_zero());
    }

    #[test]
    fn xor_with_self_is_zero_and_canonical() {
        // All limbs cancel, so the result must normalize back to the empty
        // vector rather than a run of zero limbs.
        let v = BigU::from(2u32).pow(200);
        let z = v.bit_xor(&v);
        assert!(z.is_zero());
        assert_eq!(z.limbs.len(), 0);
    }

    #[test]
    fn and_truncates_to_shorter_operand() {
        // A wide value ANDed with a one-limb mask keeps only the low limb.
        let wide = BigU::from(2u32).pow(128) + BigU::from(0xFFFFu32);
        let masked = wide.bit_and(&BigU::from(0xF0F0u32));
        assert_eq!(masked, BigU::from(0xF0F0u32));
        assert_eq!(masked.limbs.len(), 1);
    }

    #[test]
    fn results_stay_canonical() {
        // AND clearing every bit of the top limb must drop that limb.
        let a = BigU::from(0xFFFF_FFFF_0000_0001u64);
        let b = BigU::from(0x0000_0000_FFFF_FFFFu64);
        let r = a.bit_and(&b);
        assert_eq!(r, BigU::one());
        assert_eq!(r.limbs, vec![1]);
    }

    #[test]
    fn or_keeps_high_limbs_of_longer_operand() {
        let long = BigU::from(2u32).pow(100);
        let short = BigU::from(5u32);
        let r = long.bit_or(&short);
        assert_eq!(r, &long + &short);
        // Commutes, including the length-swap path.
        assert_eq!(short.bit_or(&long), r);
    }

    #[test]
    fn xor_across_limb_boundary() {
        let a = BigU::from(0x1_0000_0000u64);
        let b = BigU::from(1u32);
        assert_eq!(a.bit_xor(&b), BigU::from(0x1_0000_0001u64));
        // Undoing the XOR recovers the original.
        assert_eq!(a.bit_xor(&b).bit_xor(&b), a);
    }

    #[test]
    fn agrees_with_u128_semantics() {
        let pairs: [(u128, u128); 6] = [
            (0, 0),
            (1, u128::MAX),
            (0xDEAD_BEEF, 0x1234_5678_9ABC_DEF0),
            (u128::MAX, u128::MAX),
            (1 << 127, (1 << 64) - 1),
            (0xF0F0_F0F0_F0F0_F0F0, 0x0F0F_0F0F_0F0F_0F0F),
        ];
        for (x, y) in pairs {
            let a = BigU::from(x);
            let b = BigU::from(y);
            assert_eq!(a.bit_and(&b), BigU::from(x & y), "and {x} {y}");
            assert_eq!(a.bit_or(&b), BigU::from(x | y), "or {x} {y}");
            assert_eq!(a.bit_xor(&b), BigU::from(x ^ y), "xor {x} {y}");
        }
    }

    #[test]
    fn matches_bit_accessor() {
        // Bit-by-bit agreement with the existing single-bit reader.
        let a = BigU::from_str("123456789012345678901234567890").unwrap();
        let b = BigU::from_str("98765432109876543210").unwrap();
        let and = a.bit_and(&b);
        let or = a.bit_or(&b);
        let xor = a.bit_xor(&b);
        for i in 0..140u64 {
            assert_eq!(and.bit(i), a.bit(i) && b.bit(i), "and bit {i}");
            assert_eq!(or.bit(i), a.bit(i) || b.bit(i), "or bit {i}");
            assert_eq!(xor.bit(i), a.bit(i) ^ b.bit(i), "xor bit {i}");
        }
    }

    #[test]
    fn operators_and_assign_forms() {
        let a = BigU::from(0b1100u32);
        let b = BigU::from(0b1010u32);
        assert_eq!(&a & &b, BigU::from(0b1000u32));
        assert_eq!(a.clone() | b.clone(), BigU::from(0b1110u32));
        assert_eq!(a.clone() ^ b.clone(), BigU::from(0b0110u32));

        let mut x = a.clone();
        x &= b.clone();
        assert_eq!(x, BigU::from(0b1000u32));
        let mut x = a.clone();
        x |= b.clone();
        assert_eq!(x, BigU::from(0b1110u32));
        let mut x = a.clone();
        x ^= b;
        assert_eq!(x, BigU::from(0b0110u32));
    }

    #[test]
    fn self_assignment_is_stable() {
        // a op a: AND and OR are idempotent, XOR clears.
        let mut a = BigU::from_str("340282366920938463463374607431768211457").unwrap();
        let orig = a.clone();
        a &= orig.clone();
        assert_eq!(a, orig);
        a |= orig.clone();
        assert_eq!(a, orig);
        a ^= orig;
        assert!(a.is_zero());
    }

    #[test]
    fn identity_or_xor_reconstructs_sum() {
        // For any x, y: (x | y) == (x ^ y) + (x & y).
        let x = BigU::from_str("77777777777777777777777777").unwrap();
        let y = BigU::from_str("12345678901234567890").unwrap();
        assert_eq!(x.bit_or(&y), &x.bit_xor(&y) + &x.bit_and(&y));
    }
    #[test]
    fn bit_assign_ops_accept_a_borrowed_rhs() {
        let mask = BigU::from(0b1010u32);
        let mut a = BigU::from(0b1100u32);
        a &= &mask;
        assert_eq!(a, BigU::from(0b1000u32));
        a |= &mask;
        assert_eq!(a, BigU::from(0b1010u32));
        a ^= &mask;
        assert!(a.is_zero());
        assert_eq!(mask, BigU::from(0b1010u32), "rhs must survive");
    }

}
