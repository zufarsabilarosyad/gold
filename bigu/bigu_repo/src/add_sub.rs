//! Addition and subtraction.
//!
//! Addition propagates a carry through a [`DoubleLimb`] accumulator; subtraction
//! propagates a borrow the same way. The borrow path assumes the minuend is at
//! least as large as the subtrahend (the caller checks this), and the public
//! [`BigU::checked_sub`] surfaces [`Error::Underflow`] when it is not.

use core::ops::{Add, AddAssign, Sub, SubAssign};

use crate::bigu::BigU;
use crate::cmp::cmp_limbs;
use crate::error::{Error, Result};
use crate::{DoubleLimb, Limb};

/// Adds two little-endian limb slices and returns the canonicalized sum.
pub(crate) fn add_limbs(a: &[Limb], b: &[Limb]) -> Vec<Limb> {
    let (long, short) = if a.len() >= b.len() { (a, b) } else { (b, a) };
    let mut out = Vec::with_capacity(long.len() + 1);
    let mut carry: DoubleLimb = 0;
    for i in 0..long.len() {
        let mut sum = long[i] as DoubleLimb + carry;
        if i < short.len() {
            sum += short[i] as DoubleLimb;
        }
        out.push(sum as Limb);
        carry = sum >> 32;
    }
    if carry != 0 {
        out.push(carry as Limb);
    }
    out
}

/// Subtracts `b` from `a`, where `a >= b` must already hold.
///
/// The result is canonicalized (trailing zero limbs removed). Calling this with
/// `a < b` would underflow; callers gate on [`cmp_limbs`] first.
pub(crate) fn sub_limbs(a: &[Limb], b: &[Limb]) -> Vec<Limb> {
    debug_assert!(cmp_limbs(a, b) != core::cmp::Ordering::Less);
    let mut out = Vec::with_capacity(a.len());
    let mut borrow: i64 = 0;
    for i in 0..a.len() {
        let bv = if i < b.len() { b[i] as i64 } else { 0 };
        let mut diff = a[i] as i64 - bv - borrow;
        if diff < 0 {
            diff += 1i64 << 32;
            borrow = 1;
        } else {
            borrow = 0;
        }
        out.push(diff as Limb);
    }
    debug_assert_eq!(borrow, 0, "sub_limbs called with a < b");
    while let Some(&0) = out.last() {
        out.pop();
    }
    out
}

impl BigU {
    /// Subtracts `other` from `self`, returning [`Error::Underflow`] if the
    /// result would be negative.
    ///
    /// This is the safe counterpart to the [`Sub`] operator, which panics on
    /// underflow to mirror the behaviour of the primitive integer types.
    pub fn checked_sub(&self, other: &BigU) -> Result<BigU> {
        if cmp_limbs(&self.limbs, &other.limbs) == core::cmp::Ordering::Less {
            return Err(Error::Underflow);
        }
        Ok(BigU::from_limbs(sub_limbs(&self.limbs, &other.limbs)))
    }

    /// Reference-based addition used internally to avoid moving operands.
    pub(crate) fn add_ref(&self, other: &BigU) -> BigU {
        BigU::from_limbs(add_limbs(&self.limbs, &other.limbs))
    }
}

impl Add for BigU {
    type Output = BigU;
    fn add(self, rhs: BigU) -> BigU {
        self.add_ref(&rhs)
    }
}

impl Add<&BigU> for &BigU {
    type Output = BigU;
    fn add(self, rhs: &BigU) -> BigU {
        self.add_ref(rhs)
    }
}

impl AddAssign for BigU {
    fn add_assign(&mut self, rhs: BigU) {
        *self = self.add_ref(&rhs);
    }
}

impl AddAssign<&BigU> for BigU {
    fn add_assign(&mut self, rhs: &BigU) {
        *self = self.add_ref(rhs);
    }
}

impl Sub for BigU {
    type Output = BigU;
    /// Subtracts `rhs` from `self`.
    ///
    /// Panics if the result would be negative; use [`BigU::checked_sub`] for a
    /// non-panicking variant.
    fn sub(self, rhs: BigU) -> BigU {
        self.checked_sub(&rhs).expect("attempt to subtract with overflow")
    }
}

impl Sub<&BigU> for &BigU {
    type Output = BigU;
    fn sub(self, rhs: &BigU) -> BigU {
        self.checked_sub(rhs).expect("attempt to subtract with overflow")
    }
}

impl SubAssign for BigU {
    fn sub_assign(&mut self, rhs: BigU) {
        *self = self.checked_sub(&rhs).expect("attempt to subtract with overflow");
    }
}

impl SubAssign<&BigU> for BigU {
    fn sub_assign(&mut self, rhs: &BigU) {
        *self = self.checked_sub(rhs).expect("attempt to subtract with overflow");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn add_with_carry_across_limb() {
        let a = BigU::from(0xFFFF_FFFFu32);
        let b = BigU::from(1u32);
        let c = a + b;
        assert_eq!(c, BigU::from(0x1_0000_0000u64));
        assert_eq!(c.limbs, vec![0, 1]);
    }

    #[test]
    fn add_identity() {
        let a = BigU::from(12345u64);
        assert_eq!(&a + &BigU::zero(), a);
        assert_eq!(&BigU::zero() + &a, a);
    }

    #[test]
    fn add_long_carry_chain() {
        // All-ones plus one rolls over an entire limb chain.
        let a = BigU::from(u128::MAX);
        let b = BigU::from(1u32);
        let c = &a + &b;
        assert_eq!(c.limbs, vec![0, 0, 0, 0, 1]);
    }

    #[test]
    fn sub_basic_and_borrow() {
        let a = BigU::from(0x1_0000_0000u64);
        let b = BigU::from(1u32);
        let c = a - b;
        assert_eq!(c, BigU::from(0xFFFF_FFFFu32));
    }

    #[test]
    fn sub_to_zero_is_canonical() {
        let a = BigU::from(500u32);
        let c = a.clone() - a;
        assert!(c.is_zero());
        assert_eq!(c.limbs.len(), 0);
    }

    #[test]
    fn checked_sub_underflow() {
        let a = BigU::from(3u32);
        let b = BigU::from(5u32);
        assert_eq!(a.checked_sub(&b), Err(Error::Underflow));
        assert_eq!(BigU::zero().checked_sub(&BigU::one()), Err(Error::Underflow));
    }

    #[test]
    #[should_panic(expected = "subtract with overflow")]
    fn sub_operator_panics_on_underflow() {
        let _ = BigU::from(1u32) - BigU::from(2u32);
    }

    #[test]
    fn add_then_sub_roundtrip() {
        let a = BigU::from(0xDEAD_BEEF_CAFEu64);
        let b = BigU::from(0x1234_5678u64);
        let sum = &a + &b;
        assert_eq!(sum.checked_sub(&b).unwrap(), a);
    }

    #[test]
    fn add_assign_and_sub_assign() {
        let mut a = BigU::from(100u32);
        a += BigU::from(50u32);
        assert_eq!(a, BigU::from(150u32));
        a -= BigU::from(70u32);
        assert_eq!(a, BigU::from(80u32));
    }
    #[test]
    fn assign_ops_accept_a_borrowed_rhs() {
        // The borrowed forms must leave the operand usable afterwards.
        let rhs = BigU::from(10u32);
        let mut a = BigU::from(32u32);
        a += &rhs;
        assert_eq!(a, BigU::from(42u32));
        a -= &rhs;
        assert_eq!(a, BigU::from(32u32));
        assert_eq!(rhs, BigU::from(10u32), "rhs must survive both operations");
    }

    #[test]
    fn borrowed_assign_matches_owned_assign() {
        let big = BigU::from(u64::MAX);
        let mut owned = BigU::from(7u32);
        let mut borrowed = BigU::from(7u32);
        owned += big.clone();
        borrowed += &big;
        assert_eq!(owned, borrowed);
    }

}
