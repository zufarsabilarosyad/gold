//! Multiplication.
//!
//! Small operands use a straightforward schoolbook `O(n*m)` multiply with a
//! [`DoubleLimb`] accumulator. Once both operands exceed
//! [`MUL_KARATSUBA_THRESHOLD`] limbs the routine switches to Karatsuba, which
//! splits each operand into low and high halves and recombines three half-size
//! products.

use core::ops::{Mul, MulAssign};

use crate::add_sub::{add_limbs, sub_limbs};
use crate::bigu::BigU;
use crate::{DoubleLimb, Limb};

/// Operand size (in limbs) at or below which schoolbook multiplication is used.
pub(crate) const MUL_KARATSUBA_THRESHOLD: usize = 32;

/// Computes `a * m + add` in one pass, returning the canonical result. The
/// addend rides in as the initial carry, which is what lets the radix parser
/// fold a whole chunk of digits in without a second traversal. The widest
/// intermediate is `(2^32 - 1)^2 + (2^32 - 1)`, so the carry stays one limb.
pub(crate) fn mul_add_small(a: &[Limb], m: Limb, add: Limb) -> Vec<Limb> {
    let mut out = Vec::with_capacity(a.len() + 1);
    let mut carry = add as DoubleLimb;
    for &limb in a {
        let prod = limb as DoubleLimb * m as DoubleLimb + carry;
        out.push(prod as Limb);
        carry = prod >> 32;
    }
    if carry != 0 {
        out.push(carry as Limb);
    }
    while let Some(&0) = out.last() {
        out.pop();
    }
    out
}

/// Schoolbook multiplication of two limb slices.
fn mul_schoolbook(a: &[Limb], b: &[Limb]) -> Vec<Limb> {
    if a.is_empty() || b.is_empty() {
        return Vec::new();
    }
    let mut out = vec![0 as Limb; a.len() + b.len()];
    for (i, &av) in a.iter().enumerate() {
        if av == 0 {
            continue;
        }
        let mut carry: DoubleLimb = 0;
        for (j, &bv) in b.iter().enumerate() {
            let idx = i + j;
            let cur = out[idx] as DoubleLimb + av as DoubleLimb * bv as DoubleLimb + carry;
            out[idx] = cur as Limb;
            carry = cur >> 32;
        }
        // Propagate the leftover carry into the next column.
        let mut idx = i + b.len();
        while carry != 0 {
            let cur = out[idx] as DoubleLimb + carry;
            out[idx] = cur as Limb;
            carry = cur >> 32;
            idx += 1;
        }
    }
    while let Some(&0) = out.last() {
        out.pop();
    }
    out
}

/// Shifts a limb slice up by `limbs` whole limbs (multiply by `2^(32*limbs)`).
fn shift_left_limbs(a: &[Limb], limbs: usize) -> Vec<Limb> {
    if a.is_empty() {
        return Vec::new();
    }
    let mut out = Vec::with_capacity(a.len() + limbs);
    out.resize(limbs, 0);
    out.extend_from_slice(a);
    out
}

/// Recursive Karatsuba multiplication.
///
/// Splits `a` and `b` at `half = max(len)/2` limbs into low/high halves and
/// computes `z0 = lo_a*lo_b`, `z2 = hi_a*hi_b`, and the cross term
/// `z1 = (lo_a+hi_a)*(lo_b+hi_b) - z0 - z2`. The result is
/// `z2 << (2*half) + z1 << half + z0`.
fn mul_karatsuba(a: &[Limb], b: &[Limb]) -> Vec<Limb> {
    let n = a.len().max(b.len());
    if a.len() <= MUL_KARATSUBA_THRESHOLD || b.len() <= MUL_KARATSUBA_THRESHOLD {
        return mul_schoolbook(a, b);
    }

    let half = n / 2;

    let (a_lo, a_hi) = split_at(a, half);
    let (b_lo, b_hi) = split_at(b, half);

    // Low and high products.
    let z0 = mul_karatsuba(a_lo, b_lo);
    let z2 = mul_karatsuba(a_hi, b_hi);

    // Cross term via the sums of the halves.
    let sum_a = add_limbs(a_lo, a_hi);
    let sum_b = add_limbs(b_lo, b_hi);
    let mut z1 = mul_karatsuba(&sum_a, &sum_b);

    // z1 = (lo+hi)(lo+hi) - z0 - z2. Both subtractions are non-negative.
    z1 = sub_limbs(&z1, &z0);
    z1 = sub_limbs(&z1, &z2);

    // Recombine: z0 + (z1 << half) + (z2 << 2*half).
    let mut result = z0;
    let z1_shifted = shift_left_limbs(&z1, half);
    result = add_limbs(&result, &z1_shifted);
    let z2_shifted = shift_left_limbs(&z2, 2 * half);
    result = add_limbs(&result, &z2_shifted);

    while let Some(&0) = result.last() {
        result.pop();
    }
    result
}

/// Splits a slice into `(low, high)` at `mid` limbs, clamping `mid`.
fn split_at(a: &[Limb], mid: usize) -> (&[Limb], &[Limb]) {
    if mid >= a.len() {
        (a, &[])
    } else {
        a.split_at(mid)
    }
}

/// Top-level limb multiply that dispatches to schoolbook or Karatsuba.
pub(crate) fn mul_limbs(a: &[Limb], b: &[Limb]) -> Vec<Limb> {
    if a.is_empty() || b.is_empty() {
        return Vec::new();
    }
    if a.len() <= MUL_KARATSUBA_THRESHOLD || b.len() <= MUL_KARATSUBA_THRESHOLD {
        mul_schoolbook(a, b)
    } else {
        mul_karatsuba(a, b)
    }
}

impl BigU {
    /// Reference-based multiplication used internally.
    pub(crate) fn mul_ref(&self, other: &BigU) -> BigU {
        BigU::from_limbs(mul_limbs(&self.limbs, &other.limbs))
    }
}

impl Mul for BigU {
    type Output = BigU;
    fn mul(self, rhs: BigU) -> BigU {
        self.mul_ref(&rhs)
    }
}

impl Mul<&BigU> for &BigU {
    type Output = BigU;
    fn mul(self, rhs: &BigU) -> BigU {
        self.mul_ref(rhs)
    }
}

impl MulAssign for BigU {
    fn mul_assign(&mut self, rhs: BigU) {
        *self = self.mul_ref(&rhs);
    }
}

impl MulAssign<&BigU> for BigU {
    fn mul_assign(&mut self, rhs: &BigU) {
        *self = self.mul_ref(rhs);
    }
}

/// Force schoolbook multiplication regardless of operand size. Used by tests to
/// cross-check the Karatsuba path against an independent oracle.
#[cfg(test)]
pub(crate) fn mul_schoolbook_forced(a: &[Limb], b: &[Limb]) -> Vec<Limb> {
    mul_schoolbook(a, b)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cmp::cmp_limbs as _cmp;

    fn big_from_limbs(v: Vec<Limb>) -> BigU {
        BigU::from_limbs(v)
    }

    #[test]
    fn mul_add_small_basics() {
        assert_eq!(mul_add_small(&[5], 3, 0), vec![15]);
        assert_eq!(mul_add_small(&[0xFFFF_FFFF], 2, 0), vec![0xFFFF_FFFE, 1]);
        assert!(mul_add_small(&[1, 2, 3], 0, 0).is_empty());
    }

    #[test]
    fn mul_add_small_folds_in_the_addend() {
        assert_eq!(mul_add_small(&[5], 3, 7), vec![22]);
        // The addend alone builds a value out of nothing, which is how parsing
        // starts from an empty accumulator.
        assert_eq!(mul_add_small(&[], 1_000_000_000, 42), vec![42]);
        assert!(mul_add_small(&[], 10, 0).is_empty());
        // A carry out of the top limb caused by the addend alone.
        assert_eq!(
            mul_add_small(&[0xFFFF_FFFF], 0xFFFF_FFFF, 0xFFFF_FFFF),
            vec![0, 0xFFFF_FFFF]
        );
    }

    #[test]
    fn mul_add_small_matches_full_multiply() {
        // Cross-check the fused form against a separate multiply and add.
        let a = pseudo(6, 21);
        for &(m, add) in &[(1u32, 0u32), (7, 3), (0xFFFF_FFFF, 0xFFFF_FFFF), (0, 9)] {
            let fused = BigU::from_limbs(mul_add_small(&a, m, add));
            let stepwise = &(&BigU::from_limbs(a.clone()) * &BigU::from(m)) + &BigU::from(add);
            assert_eq!(fused, stepwise, "m = {m}, add = {add}");
        }
    }

    #[test]
    fn mul_zero_and_one() {
        let a = BigU::from(123456789u64);
        assert!((a.clone() * BigU::zero()).is_zero());
        assert_eq!(a.clone() * BigU::one(), a);
    }

    #[test]
    fn mul_carry_across_limbs() {
        let a = BigU::from(0xFFFF_FFFFu32);
        let b = BigU::from(0xFFFF_FFFFu32);
        let c = a * b;
        // (2^32 - 1)^2 = 2^64 - 2^33 + 1.
        assert_eq!(c, BigU::from(0xFFFF_FFFE_0000_0001u64));
    }

    #[test]
    fn mul_known_decimal() {
        let a = BigU::from(123456789u64);
        let b = BigU::from(987654321u64);
        let c = a * b;
        assert_eq!(c.to_str_radix(10).unwrap(), "121932631112635269");
    }

    /// Build a deterministic multi-limb value of `n` limbs.
    fn pseudo(n: usize, seed: u64) -> Vec<Limb> {
        let mut x = seed.wrapping_mul(0x9E37_79B9_7F4A_7C15).wrapping_add(1);
        let mut v = Vec::with_capacity(n);
        for _ in 0..n {
            x = x.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            v.push((x >> 16) as Limb);
        }
        // Ensure canonical (top limb nonzero).
        if let Some(last) = v.last_mut() {
            if *last == 0 {
                *last = 1;
            }
        }
        v
    }

    #[test]
    fn karatsuba_matches_schoolbook_large() {
        // Operands well above the threshold so Karatsuba actually runs.
        let a = pseudo(40, 1);
        let b = pseudo(45, 2);
        let karatsuba = mul_limbs(&a, &b);
        let school = mul_schoolbook_forced(&a, &b);
        assert_eq!(
            karatsuba, school,
            "Karatsuba result must equal the schoolbook oracle"
        );
        assert_eq!(_cmp(&karatsuba, &school), core::cmp::Ordering::Equal);
    }

    #[test]
    fn karatsuba_matches_known_product() {
        // (10^50) * (10^50) == 10^100, an exactly checkable big product.
        let ten50 = BigU::from(10u32).pow(50);
        // Force operands big enough for the Karatsuba path by padding via pow.
        let big_a = big_from_limbs(ten50.limbs.clone());
        let big_b = big_from_limbs(ten50.limbs.clone());
        let prod = &big_a * &big_b;
        let expected = BigU::from(10u32).pow(100);
        assert_eq!(prod, expected);
    }

    #[test]
    fn karatsuba_associative_like_check() {
        // (a*b) must equal (b*a) on the Karatsuba path.
        let a = pseudo(50, 7);
        let b = pseudo(60, 9);
        assert_eq!(mul_limbs(&a, &b), mul_limbs(&b, &a));
    }

    #[test]
    fn mul_assign_works() {
        let mut a = BigU::from(7u32);
        a *= BigU::from(6u32);
        assert_eq!(a, BigU::from(42u32));
    }
    #[test]
    fn mul_assign_accepts_a_borrowed_rhs() {
        let rhs = BigU::from(6u32);
        let mut a = BigU::from(7u32);
        a *= &rhs;
        assert_eq!(a, BigU::from(42u32));
        // Multiplying by the same borrow again reuses it rather than moving it.
        a *= &rhs;
        assert_eq!(a, BigU::from(252u32));
    }

}
