//! Division and remainder.
//!
//! Three code paths cooperate:
//!
//! * a divisor of zero is rejected with [`Error::DivByZero`];
//! * a single-limb divisor uses the linear [`div_rem_small`] fast path;
//! * a multi-limb divisor uses Knuth's Algorithm D (TAOCP Vol. 2, §4.3.1),
//!   which normalizes both operands so the divisor's top limb has its high bit
//!   set, estimates each quotient digit with a two-limb `q-hat`, corrects the
//!   estimate, then performs a multiply-and-subtract with an add-back on the
//!   rare over-estimate.

use core::ops::{Div, DivAssign, Rem, RemAssign};

use crate::bigu::BigU;
use crate::cmp::cmp_limbs;
use crate::error::{Error, Result};
use crate::{DoubleLimb, Limb, LIMB_BITS};

/// Divides a limb slice by a single nonzero limb.
///
/// Returns the canonical quotient limbs and the `u32` remainder.
pub(crate) fn div_rem_small(a: &[Limb], divisor: Limb) -> (Vec<Limb>, Limb) {
    debug_assert!(divisor != 0);
    let mut quotient = vec![0 as Limb; a.len()];
    let mut rem: DoubleLimb = 0;
    for i in (0..a.len()).rev() {
        let cur = (rem << 32) | a[i] as DoubleLimb;
        quotient[i] = (cur / divisor as DoubleLimb) as Limb;
        rem = cur % divisor as DoubleLimb;
    }
    while let Some(&0) = quotient.last() {
        quotient.pop();
    }
    (quotient, rem as Limb)
}

/// Multi-limb long division via Knuth Algorithm D.
///
/// `a` is the dividend, `b` the divisor with `b.len() >= 2`. Returns
/// `(quotient, remainder)` in canonical form.
fn div_rem_knuth(a: &[Limb], b: &[Limb]) -> (Vec<Limb>, Vec<Limb>) {
    let n = b.len();
    let m = a.len() - n;

    // D1: normalize so the divisor's most-significant limb has its top bit set.
    let shift = b[n - 1].leading_zeros();

    let v = shl_small(b, shift); // divisor, exactly n limbs after shift
    debug_assert_eq!(v.len(), n);

    // The dividend gets the same shift and one guard limb on top.
    let mut u = shl_small(a, shift);
    u.resize(a.len() + 1, 0); // ensure room for the guard limb u[m + n]

    let mut q = vec![0 as Limb; m + 1];

    let v_top = v[n - 1] as DoubleLimb;
    let v_second = v[n - 2] as DoubleLimb;

    // D2/D7: loop over quotient digits from most to least significant.
    for j in (0..=m).rev() {
        // D3: estimate q-hat from the top two limbs of the current window.
        let numer = ((u[j + n] as DoubleLimb) << 32) | u[j + n - 1] as DoubleLimb;
        let mut qhat = numer / v_top;
        let mut rhat = numer % v_top;

        // Refine q-hat using the third limb so it is at most one too large.
        while qhat >= (1 << 32)
            || qhat * v_second > (rhat << 32) + u[j + n - 2] as DoubleLimb
        {
            qhat -= 1;
            rhat += v_top;
            if rhat >= (1 << 32) {
                break;
            }
        }

        // D4: multiply the divisor by q-hat and subtract from the window.
        let mut borrow: i64 = 0;
        let mut carry: DoubleLimb = 0;
        for i in 0..n {
            let prod = qhat * v[i] as DoubleLimb + carry;
            carry = prod >> 32;
            let sub = u[j + i] as i64 - borrow - (prod as Limb) as i64;
            if sub < 0 {
                u[j + i] = (sub + (1i64 << 32)) as Limb;
                borrow = 1;
            } else {
                u[j + i] = sub as Limb;
                borrow = 0;
            }
        }
        let sub_top = u[j + n] as i64 - borrow - carry as i64;
        let over_estimated = sub_top < 0;
        u[j + n] = sub_top as Limb; // wraps; corrected by add-back below if needed

        // D5/D6: if the subtraction went negative, q-hat was one too large.
        if over_estimated {
            qhat -= 1;
            // Add the divisor back into the window to repair the remainder.
            let mut add_carry: DoubleLimb = 0;
            for i in 0..n {
                let sum = u[j + i] as DoubleLimb + v[i] as DoubleLimb + add_carry;
                u[j + i] = sum as Limb;
                add_carry = sum >> 32;
            }
            u[j + n] = (u[j + n] as DoubleLimb + add_carry) as Limb;
        }

        q[j] = qhat as Limb;
    }

    // D8: un-normalize the remainder by undoing the shift.
    let mut rem = u;
    rem.truncate(n);
    let rem = shr_small(&rem, shift);

    let mut quotient = q;
    while let Some(&0) = quotient.last() {
        quotient.pop();
    }
    let mut remainder = rem;
    while let Some(&0) = remainder.last() {
        remainder.pop();
    }

    (quotient, remainder)
}

/// Left-shifts a limb slice by `0..32` bits, returning fresh limbs.
fn shl_small(a: &[Limb], shift: u32) -> Vec<Limb> {
    if shift == 0 {
        return a.to_vec();
    }
    let mut out = Vec::with_capacity(a.len() + 1);
    let mut carry: Limb = 0;
    for &limb in a {
        let cur = ((limb as DoubleLimb) << shift) | carry as DoubleLimb;
        out.push(cur as Limb);
        carry = (cur >> 32) as Limb;
    }
    if carry != 0 {
        out.push(carry);
    }
    out
}

/// Right-shifts a limb slice by `0..32` bits, returning fresh limbs.
fn shr_small(a: &[Limb], shift: u32) -> Vec<Limb> {
    if shift == 0 {
        let mut out = a.to_vec();
        while let Some(&0) = out.last() {
            out.pop();
        }
        return out;
    }
    let mut out = vec![0 as Limb; a.len()];
    let mut carry: Limb = 0;
    for i in (0..a.len()).rev() {
        let cur = a[i];
        out[i] = (cur >> shift) | carry;
        carry = ((cur as DoubleLimb) << (LIMB_BITS - shift)) as Limb;
    }
    while let Some(&0) = out.last() {
        out.pop();
    }
    out
}

/// Modular subtraction of two residues that are already reduced into `[0, m)`.
///
/// Returns `(a - b) mod m` without ever going negative: when `a < b` one modulus
/// is folded back in, so the result stays in `[0, m)` and never underflows the
/// unsigned representation.
fn mod_sub(a: &BigU, b: &BigU, m: &BigU) -> BigU {
    if a >= b {
        a.checked_sub(b).expect("a >= b, so no underflow")
    } else {
        // a - b would be negative; a + (m - b) lands back in [0, m) since b < m.
        let complement = m.checked_sub(b).expect("b < m");
        a + &complement
    }
}

impl BigU {
    /// Computes the greatest common divisor of `self` and `other` using the
    /// Euclidean algorithm.
    ///
    /// `gcd(0, 0)` is defined as `0`, and `gcd(x, 0) == gcd(0, x) == x` for any
    /// `x`, which matches the usual mathematical convention. The result divides
    /// both inputs exactly and is the largest such value.
    ///
    /// Each step replaces `(a, b)` with `(b, a mod b)` until the second operand
    /// reaches zero; the surviving operand is the gcd. Because the remainder is
    /// produced by the panic-free [`BigU::div_rem`] and the divisor is checked
    /// for zero before every step, this routine never panics.
    pub fn gcd(&self, other: &BigU) -> BigU {
        let mut a = self.clone();
        let mut b = other.clone();
        while !b.is_zero() {
            // `b` is nonzero here, so `div_rem` cannot return `DivByZero`.
            let (_, r) = a.div_rem(&b).expect("divisor checked nonzero");
            a = b;
            b = r;
        }
        a
    }

    /// Computes the least common multiple of `self` and `other`.
    ///
    /// Returns `0` whenever either operand is zero, matching the convention that
    /// the lcm involving zero is zero. Otherwise the value is computed as
    /// `(self / gcd) * other`, dividing before multiplying so the intermediate
    /// product never grows larger than the final result. The division is always
    /// exact because the gcd divides `self`.
    pub fn lcm(&self, other: &BigU) -> BigU {
        if self.is_zero() || other.is_zero() {
            return BigU::zero();
        }
        let g = self.gcd(other);
        // `g` divides `self` exactly, so this quotient has no remainder, and `g`
        // is nonzero because both operands are nonzero.
        let (reduced, _) = self.div_rem(&g).expect("gcd of nonzero is nonzero");
        &reduced * other
    }

    /// Computes `self^exp mod modulus` using right-to-left binary
    /// (square-and-multiply) modular exponentiation.
    ///
    /// Returns [`Error::DivByZero`] when `modulus` is zero. The modulus of `1`
    /// collapses every value to `0`, matching the usual convention. The base is
    /// reduced modulo `modulus` before the loop and after every squaring, so the
    /// intermediate values never grow past two modulus-widths and the routine is
    /// far cheaper than materializing `self.pow(exp)` and dividing afterwards.
    ///
    /// `x.modpow(0, m)` is `1 mod m` for every `x`, including zero, which means
    /// `0.modpow(0, m)` follows the common `0^0 == 1` convention. Because every
    /// step goes through the panic-free [`BigU::div_rem`] with a divisor that is
    /// checked nonzero, this routine never panics.
    pub fn modpow(&self, exp: &BigU, modulus: &BigU) -> Result<BigU> {
        if modulus.is_zero() {
            return Err(Error::DivByZero);
        }
        // Everything is congruent to 0 modulo 1, so the answer is always zero.
        if modulus == &BigU::one() {
            return Ok(BigU::zero());
        }

        let mut result = BigU::one();
        // Reduce the base first so the running square stays bounded by the
        // modulus width regardless of how large `self` is.
        let (_, mut base) = self.div_rem(modulus).expect("modulus checked nonzero");
        // Walk the exponent from its least- to most-significant bit.
        let mut e = exp.clone();
        while !e.is_zero() {
            if e.limbs[0] & 1 == 1 {
                let prod = &result * &base;
                let (_, r) = prod.div_rem(modulus).expect("modulus checked nonzero");
                result = r;
            }
            e = e.shr_ref(1);
            if !e.is_zero() {
                let sq = &base * &base;
                let (_, r) = sq.div_rem(modulus).expect("modulus checked nonzero");
                base = r;
            }
        }
        Ok(result)
    }

    /// Computes the modular multiplicative inverse of `self` modulo `modulus`:
    /// the value `x` in `[0, modulus)` with `self * x` congruent to `1`.
    ///
    /// Returns [`Error::DivByZero`] when `modulus` is zero, mirroring the rest of
    /// the modular family, and [`Error::NotInvertible`] when `self` and `modulus`
    /// are not coprime, since an inverse exists exactly when their gcd is one.
    /// The modulus of `1` inverts every value to `0`, matching the convention that
    /// the trivial ring has `0` as its lone element.
    ///
    /// This is the natural companion to [`BigU::modpow`]: `a.modinv(m)` and
    /// `a.modpow(m - 2, m)` agree whenever `m` is prime. The result is produced by
    /// the extended Euclidean algorithm, carrying only the Bezout coefficient of
    /// `self` and keeping it reduced modulo `modulus` at every step so that all
    /// intermediates stay unsigned and bounded by the modulus width. Every
    /// division goes through the panic-free [`BigU::div_rem`] with a divisor that
    /// is checked nonzero, so the routine never panics.
    ///
    /// ```
    /// use bigu::BigU;
    /// // 3 * 4 == 12 == 1 (mod 11), so the inverse of 3 modulo 11 is 4.
    /// assert_eq!(BigU::from(3u32).modinv(&BigU::from(11u32)).unwrap(), BigU::from(4u32));
    /// // 6 and 9 share the factor 3, so 6 has no inverse modulo 9.
    /// assert!(BigU::from(6u32).modinv(&BigU::from(9u32)).is_err());
    /// ```
    pub fn modinv(&self, modulus: &BigU) -> Result<BigU> {
        if modulus.is_zero() {
            return Err(Error::DivByZero);
        }
        // Everything is congruent to 0 modulo 1, so the trivial inverse is zero.
        if modulus == &BigU::one() {
            return Ok(BigU::zero());
        }

        // Reduce the base into [0, modulus) first; the loop tracks its inverse
        // modulo `modulus`, and self is congruent to this reduced form.
        let (_, a) = self.div_rem(modulus).expect("modulus checked nonzero");

        // Extended Euclidean on (modulus, a). Only `t`, the coefficient that
        // multiplies `a`, is carried, kept in [0, modulus) via `mod_sub`.
        let mut r = modulus.clone();
        let mut new_r = a;
        let mut t = BigU::zero();
        let mut new_t = BigU::one();

        while !new_r.is_zero() {
            // `new_r` is nonzero, so both div_rem calls below are safe.
            let (q, rem) = r.div_rem(&new_r).expect("divisor nonzero");
            // next_t = t - q*new_t (mod modulus); reduce the product first.
            let (_, qt) = (&q * &new_t)
                .div_rem(modulus)
                .expect("modulus checked nonzero");
            let next_t = mod_sub(&t, &qt, modulus);
            t = new_t;
            new_t = next_t;
            r = new_r;
            new_r = rem;
        }

        // `r` is now gcd(self, modulus); an inverse exists only when it is one.
        if r != BigU::one() {
            return Err(Error::NotInvertible);
        }
        Ok(t)
    }

    /// Returns the floor of the base-`base` logarithm of `self`, i.e. the
    /// largest `k` such that `base^k <= self`.
    ///
    /// The logarithm is undefined when it cannot produce a finite answer, so
    /// `None` is returned for `self == 0` (no power of any base reaches zero) and
    /// for `base < 2` (a base of `0` or `1` never grows). Every other case yields
    /// `Some(k)`: for instance `ilog(10)` of any value in `100..=999` is `2`.
    ///
    /// The result is computed by multiplying a running power of `base` until it
    /// would exceed `self`, so it performs `k + 1` multiplications and no
    /// division, and it never panics. The returned `k` always satisfies
    /// `base^k <= self < base^(k+1)`.
    ///
    /// ```
    /// use bigu::BigU;
    /// assert_eq!(BigU::from(1000u32).ilog(&BigU::from(10u32)), Some(3));
    /// assert_eq!(BigU::from(999u32).ilog(&BigU::from(10u32)), Some(2));
    /// assert_eq!(BigU::one().ilog(&BigU::from(2u32)), Some(0));
    /// assert_eq!(BigU::zero().ilog(&BigU::from(2u32)), None);
    /// ```
    pub fn ilog(&self, base: &BigU) -> Option<u64> {
        // The logarithm of zero is unbounded below, and a base under two never
        // climbs, so neither has a finite floor-log.
        if self.is_zero() || base < &BigU::from(2u32) {
            return None;
        }

        // Walk powers of `base` upward, stopping just before the power passes
        // `self`. `power` holds `base^exp` throughout the loop.
        let mut exp: u64 = 0;
        let mut power = BigU::one();
        loop {
            let next = &power * base;
            if &next > self {
                return Some(exp);
            }
            power = next;
            exp += 1;
        }
    }

    /// Computes the quotient and remainder of `self / other`.
    ///
    /// Returns [`Error::DivByZero`] when `other` is zero. The result always
    /// satisfies `quotient * other + remainder == self` and
    /// `remainder < other`.
    pub fn div_rem(&self, other: &BigU) -> Result<(BigU, BigU)> {
        if other.is_zero() {
            return Err(Error::DivByZero);
        }
        // If the dividend is smaller, the quotient is zero and the dividend is
        // the whole remainder.
        if cmp_limbs(&self.limbs, &other.limbs) == core::cmp::Ordering::Less {
            return Ok((BigU::zero(), self.clone()));
        }

        if other.limbs.len() == 1 {
            let (q, r) = div_rem_small(&self.limbs, other.limbs[0]);
            return Ok((BigU::from_limbs(q), BigU::from(r)));
        }

        let (q, r) = div_rem_knuth(&self.limbs, &other.limbs);
        Ok((BigU::from_limbs(q), BigU::from_limbs(r)))
    }
}

impl Div for BigU {
    type Output = BigU;
    /// Integer quotient. Panics on division by zero, mirroring primitive ints.
    fn div(self, rhs: BigU) -> BigU {
        self.div_rem(&rhs).expect("attempt to divide by zero").0
    }
}

impl Div<&BigU> for &BigU {
    type Output = BigU;
    fn div(self, rhs: &BigU) -> BigU {
        self.div_rem(rhs).expect("attempt to divide by zero").0
    }
}

impl Rem for BigU {
    type Output = BigU;
    /// Remainder. Panics on division by zero, mirroring primitive ints.
    fn rem(self, rhs: BigU) -> BigU {
        self.div_rem(&rhs).expect("attempt to divide by zero").1
    }
}

impl Rem<&BigU> for &BigU {
    type Output = BigU;
    fn rem(self, rhs: &BigU) -> BigU {
        self.div_rem(rhs).expect("attempt to divide by zero").1
    }
}

impl DivAssign for BigU {
    fn div_assign(&mut self, rhs: BigU) {
        *self = self.div_rem(&rhs).expect("attempt to divide by zero").0;
    }
}

impl DivAssign<&BigU> for BigU {
    fn div_assign(&mut self, rhs: &BigU) {
        *self = self.div_rem(rhs).expect("attempt to divide by zero").0;
    }
}

impl RemAssign for BigU {
    fn rem_assign(&mut self, rhs: BigU) {
        *self = self.div_rem(&rhs).expect("attempt to divide by zero").1;
    }
}

impl RemAssign<&BigU> for BigU {
    fn rem_assign(&mut self, rhs: &BigU) {
        *self = self.div_rem(rhs).expect("attempt to divide by zero").1;
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
    fn div_by_zero_is_error() {
        assert_eq!(BigU::from(5u32).div_rem(&BigU::zero()), Err(Error::DivByZero));
    }

    #[test]
    fn small_divisor_fast_path() {
        let (q, r) = BigU::from(100u32).div_rem(&BigU::from(7u32)).unwrap();
        assert_eq!(q, BigU::from(14u32));
        assert_eq!(r, BigU::from(2u32));
    }

    #[test]
    fn divide_smaller_by_larger() {
        let (q, r) = BigU::from(3u32).div_rem(&BigU::from(10u32)).unwrap();
        assert!(q.is_zero());
        assert_eq!(r, BigU::from(3u32));
    }

    #[test]
    fn exact_division_has_zero_remainder() {
        let a = b("1000000000000000000000000");
        let d = b("1000000000000");
        let (q, r) = a.div_rem(&d).unwrap();
        assert_eq!(q, b("1000000000000"));
        assert!(r.is_zero());
    }

    #[test]
    fn quotient_remainder_invariant_holds() {
        let a = b("123456789012345678901234567890");
        let d = b("987654321987654321");
        let (q, r) = a.div_rem(&d).unwrap();
        // q*d + r == a and r < d.
        assert_eq!(&(&q * &d) + &r, a);
        assert!(r < d);
    }

    #[test]
    fn knuth_normalization_small_top_limb() {
        // Divisor whose top limb is 1 forces a non-trivial normalization shift.
        // 2^96 + 5 divided by 2^64 + 1.
        let a = &BigU::from(2u32).pow(96) + &BigU::from(5u32);
        let d = &BigU::from(2u32).pow(64) + &BigU::one();
        let (q, r) = a.div_rem(&d).unwrap();
        assert_eq!(&(&q * &d) + &r, a);
        assert!(r < d);
        // Cross-check against an exact oracle: floor((2^96+5)/(2^64+1)).
        // 2^96 = (2^64+1)*2^32 - 2^32, so quotient is 2^32 - 1.
        assert_eq!(q, &BigU::from(2u32).pow(32) - &BigU::one());
    }

    #[test]
    fn knuth_add_back_branch() {
        // Operand pair chosen to trigger the rare q-hat over-estimate / add-back.
        let dividend = b("79228162514264337593543950337"); // 2^96 + 1
        let divisor = b("18446744073709551616"); // 2^64
        let (q, r) = dividend.div_rem(&divisor).unwrap();
        assert_eq!(&(&q * &divisor) + &r, dividend);
        assert!(r < divisor);
    }

    #[test]
    fn many_random_division_invariants() {
        // Deterministic pseudo-random pairs; verify the division contract.
        let mut x: u64 = 0x1234_5678_9abc_def0;
        let mut next = || {
            x = x.wrapping_mul(6364136223846793005).wrapping_add(1);
            x
        };
        for _ in 0..200 {
            let a = BigU::from(next() as u128) * BigU::from(next() as u128)
                + BigU::from(next());
            let d = BigU::from(next() as u128) + BigU::one();
            if d.is_zero() {
                continue;
            }
            let (q, r) = a.div_rem(&d).unwrap();
            assert_eq!(&(&q * &d) + &r, a);
            assert!(r < d);
        }
    }

    #[test]
    fn operators_and_assign() {
        let a = BigU::from(1000u32);
        let d = BigU::from(7u32);
        assert_eq!(a.clone() / d.clone(), BigU::from(142u32));
        assert_eq!(a.clone() % d.clone(), BigU::from(6u32));
        let mut m = a.clone();
        m /= d.clone();
        assert_eq!(m, BigU::from(142u32));
        let mut n = a;
        n %= d;
        assert_eq!(n, BigU::from(6u32));
    }

    #[test]
    #[should_panic(expected = "divide by zero")]
    fn div_operator_panics_on_zero() {
        let _ = BigU::from(1u32) / BigU::zero();
    }

    #[test]
    fn ilog_small_known_values() {
        let ten = BigU::from(10u32);
        assert_eq!(BigU::from(1u32).ilog(&ten), Some(0));
        assert_eq!(BigU::from(9u32).ilog(&ten), Some(0));
        assert_eq!(BigU::from(10u32).ilog(&ten), Some(1));
        assert_eq!(BigU::from(99u32).ilog(&ten), Some(1));
        assert_eq!(BigU::from(100u32).ilog(&ten), Some(2));
        assert_eq!(BigU::from(1000u32).ilog(&ten), Some(3));
        // Base two on exact powers and the values just below them.
        let two = BigU::from(2u32);
        assert_eq!(BigU::from(8u32).ilog(&two), Some(3));
        assert_eq!(BigU::from(7u32).ilog(&two), Some(2));
    }

    #[test]
    fn ilog_undefined_cases_return_none() {
        // Zero has no finite logarithm in any base.
        assert_eq!(BigU::zero().ilog(&BigU::from(2u32)), None);
        // Bases below two never grow, so they have no logarithm either.
        assert_eq!(BigU::from(5u32).ilog(&BigU::zero()), None);
        assert_eq!(BigU::from(5u32).ilog(&BigU::one()), None);
    }

    #[test]
    fn ilog_brackets_the_value() {
        // For assorted bases and values, base^k <= v < base^(k+1) must hold.
        let value = b("123456789012345678901234567890");
        for base_n in [2u32, 3, 7, 10, 16, 1000] {
            let base = BigU::from(base_n);
            let k = value.ilog(&base).unwrap();
            let lower = base.pow(k as u32);
            let upper = base.pow(k as u32 + 1);
            assert!(lower <= value, "base {base_n}: base^k must not exceed v");
            assert!(value < upper, "base {base_n}: v must be below base^(k+1)");
        }
    }

    #[test]
    fn ilog_matches_exact_powers() {
        // ilog of base^e back to base is exactly e, and one less drops to e-1.
        let base = BigU::from(7u32);
        for e in 0u32..20 {
            let power = base.pow(e);
            assert_eq!(power.ilog(&base), Some(e as u64), "7^{e}");
            if e > 0 {
                let below = power.checked_sub(&BigU::one()).unwrap();
                assert_eq!(below.ilog(&base), Some(e as u64 - 1), "7^{e} - 1");
            }
        }
    }

    #[test]
    fn gcd_small_known_values() {
        assert_eq!(BigU::from(54u32).gcd(&BigU::from(24u32)), BigU::from(6u32));
        assert_eq!(BigU::from(48u32).gcd(&BigU::from(18u32)), BigU::from(6u32));
        // Coprime inputs share only the divisor one.
        assert_eq!(BigU::from(17u32).gcd(&BigU::from(13u32)), BigU::one());
    }

    #[test]
    fn gcd_zero_conventions() {
        // gcd(x, 0) == gcd(0, x) == x, and gcd(0, 0) == 0.
        let x = BigU::from(42u32);
        assert_eq!(x.gcd(&BigU::zero()), x);
        assert_eq!(BigU::zero().gcd(&x), x);
        assert!(BigU::zero().gcd(&BigU::zero()).is_zero());
    }

    #[test]
    fn gcd_is_symmetric_and_divides_both() {
        let a = b("123456789012345678901234567890");
        let d = b("987654321987654321");
        let g = a.gcd(&d);
        assert_eq!(g, d.gcd(&a), "gcd must be symmetric");
        // The gcd divides both operands with no remainder.
        assert!(a.div_rem(&g).unwrap().1.is_zero());
        assert!(d.div_rem(&g).unwrap().1.is_zero());
    }

    #[test]
    fn gcd_of_known_multiple() {
        // gcd(k*a, k*b) == k*gcd(a, b); here gcd(a, b) == 1 so it is just k.
        let k = b("1000000000000000000000");
        let x = &k * &BigU::from(7u32);
        let y = &k * &BigU::from(11u32);
        assert_eq!(x.gcd(&y), k);
    }

    #[test]
    fn lcm_basic_and_zero() {
        assert_eq!(BigU::from(4u32).lcm(&BigU::from(6u32)), BigU::from(12u32));
        assert_eq!(BigU::from(21u32).lcm(&BigU::from(6u32)), BigU::from(42u32));
        assert!(BigU::from(5u32).lcm(&BigU::zero()).is_zero());
        assert!(BigU::zero().lcm(&BigU::from(5u32)).is_zero());
    }

    #[test]
    fn lcm_times_gcd_equals_product() {
        // The identity lcm(a, b) * gcd(a, b) == a * b holds for nonzero inputs.
        let a = b("123456789012345");
        let d = b("9876543210987");
        let lhs = &a.lcm(&d) * &a.gcd(&d);
        let rhs = &a * &d;
        assert_eq!(lhs, rhs);
    }

    #[test]
    fn modpow_small_known_values() {
        // 2^10 = 1024; 1024 mod 1000 == 24.
        assert_eq!(
            BigU::from(2u32)
                .modpow(&BigU::from(10u32), &BigU::from(1000u32))
                .unwrap(),
            BigU::from(24u32)
        );
        // 3^4 = 81; 81 mod 5 == 1.
        assert_eq!(
            BigU::from(3u32)
                .modpow(&BigU::from(4u32), &BigU::from(5u32))
                .unwrap(),
            BigU::one()
        );
    }

    #[test]
    fn modpow_zero_exponent_and_modulus_one() {
        // Any base to the zero power is 1, then reduced by the modulus.
        assert_eq!(
            BigU::from(7u32)
                .modpow(&BigU::zero(), &BigU::from(13u32))
                .unwrap(),
            BigU::one()
        );
        // 0^0 follows the 0^0 == 1 convention.
        assert_eq!(
            BigU::zero()
                .modpow(&BigU::zero(), &BigU::from(13u32))
                .unwrap(),
            BigU::one()
        );
        // Modulus of one collapses everything to zero, even with a zero exponent.
        assert!(BigU::from(7u32)
            .modpow(&BigU::from(5u32), &BigU::one())
            .unwrap()
            .is_zero());
        assert!(BigU::from(7u32)
            .modpow(&BigU::zero(), &BigU::one())
            .unwrap()
            .is_zero());
    }

    #[test]
    fn modpow_zero_modulus_is_error() {
        assert_eq!(
            BigU::from(2u32).modpow(&BigU::from(3u32), &BigU::zero()),
            Err(Error::DivByZero)
        );
    }

    #[test]
    fn modpow_reduces_large_base_first() {
        // (m + 3)^2 mod m == 9, demonstrating the base is reduced before squaring.
        let m = b("1000000007");
        let base = &m + &BigU::from(3u32);
        assert_eq!(
            base.modpow(&BigU::from(2u32), &m).unwrap(),
            BigU::from(9u32)
        );
    }

    #[test]
    fn modpow_matches_pow_then_reduce() {
        // For exponents small enough to materialize directly, modpow must agree
        // with computing the full power and reducing once.
        let base = b("123456789");
        let modulus = b("987654321");
        for e in 0u32..40 {
            let direct = {
                let (_, r) = base.pow(e).div_rem(&modulus).unwrap();
                r
            };
            let via_modpow = base.modpow(&BigU::from(e), &modulus).unwrap();
            assert_eq!(via_modpow, direct, "exponent {e} mismatch");
        }
    }

    #[test]
    fn modpow_fermat_little_theorem() {
        // For prime p and base a not divisible by p, a^(p-1) mod p == 1.
        let p = b("2147483647"); // a Mersenne prime (2^31 - 1)
        let exp = p.checked_sub(&BigU::one()).unwrap();
        for a in ["2", "3", "10", "123456789"] {
            let base = b(a);
            assert_eq!(base.modpow(&exp, &p).unwrap(), BigU::one(), "base {a}");
        }
    }

    #[test]
    fn modpow_handles_large_exponent() {
        // 2^256 mod 1000 cross-checked against an explicit reduction.
        let big_exp = BigU::from(256u32);
        let modulus = BigU::from(1000u32);
        let via_modpow = BigU::from(2u32).modpow(&big_exp, &modulus).unwrap();
        let (_, direct) = BigU::from(2u32).pow(256).div_rem(&modulus).unwrap();
        assert_eq!(via_modpow, direct);
    }

    #[test]
    fn modinv_small_known_values() {
        // Each inverse satisfies a * inv == 1 (mod m).
        for &(a, m, inv) in &[(3u32, 11u32, 4u32), (10, 17, 12), (7, 26, 15), (2, 5, 3)] {
            let got = BigU::from(a).modinv(&BigU::from(m)).unwrap();
            assert_eq!(got, BigU::from(inv), "modinv({a}, {m})");
            let (_, check) = (&got * &BigU::from(a)).div_rem(&BigU::from(m)).unwrap();
            assert_eq!(check, BigU::one(), "a*inv must be 1 mod m");
        }
    }

    #[test]
    fn modinv_not_coprime_is_error() {
        // Sharing any factor with the modulus rules out an inverse.
        assert_eq!(BigU::from(6u32).modinv(&BigU::from(9u32)), Err(Error::NotInvertible));
        assert_eq!(BigU::from(4u32).modinv(&BigU::from(8u32)), Err(Error::NotInvertible));
        // Zero is never invertible modulo anything above one.
        assert_eq!(BigU::zero().modinv(&BigU::from(7u32)), Err(Error::NotInvertible));
    }

    #[test]
    fn modinv_zero_modulus_is_error() {
        assert_eq!(BigU::from(3u32).modinv(&BigU::zero()), Err(Error::DivByZero));
    }

    #[test]
    fn modinv_modulus_one_is_zero() {
        // The trivial ring collapses every value, so the inverse is zero.
        assert!(BigU::from(5u32).modinv(&BigU::one()).unwrap().is_zero());
        assert!(BigU::zero().modinv(&BigU::one()).unwrap().is_zero());
    }

    #[test]
    fn modinv_reduces_large_base_first() {
        // (m + 3) is congruent to 3, so their inverses modulo m coincide.
        let m = b("1000000007");
        let base = &m + &BigU::from(3u32);
        assert_eq!(base.modinv(&m).unwrap(), BigU::from(3u32).modinv(&m).unwrap());
    }

    #[test]
    fn modinv_result_lies_below_modulus() {
        // A prime modulus makes every nonzero smaller value invertible.
        let m = b("2305843009213693951"); // 2^61 - 1, a Mersenne prime
        let a = b("123456789012345");
        let inv = a.modinv(&m).unwrap();
        assert!(inv < m, "inverse must be reduced into [0, m)");
        let (_, one) = (&inv * &a).div_rem(&m).unwrap();
        assert_eq!(one, BigU::one());
    }

    #[test]
    fn modinv_agrees_with_fermat_via_modpow() {
        // For a prime p and a not divisible by p, a^(p-2) mod p is the inverse,
        // giving an independent oracle built from modpow.
        let p = b("2147483647"); // 2^31 - 1, a Mersenne prime
        let exp = p.checked_sub(&BigU::from(2u32)).unwrap();
        for a in ["2", "3", "1000", "123456789"] {
            let base = b(a);
            let via_inv = base.modinv(&p).unwrap();
            let via_fermat = base.modpow(&exp, &p).unwrap();
            assert_eq!(via_inv, via_fermat, "base {a}");
        }
    }

    #[test]
    fn modinv_large_values_invariant() {
        // Deterministic pseudo-random inputs against a composite modulus. Either
        // an inverse exists and multiplies back to 1, or the pair is not coprime;
        // both outcomes are checked against gcd, independent of modinv itself.
        let m = b("123456789012345678901234567890");
        let mut x: u64 = 0xC0FF_EE12_3456;
        for _ in 0..80 {
            x = x.wrapping_mul(6364136223846793005).wrapping_add(1);
            let a = BigU::from(x as u128) + BigU::one();
            match a.modinv(&m) {
                Ok(inv) => {
                    let (_, check) = (&a * &inv).div_rem(&m).unwrap();
                    assert_eq!(check, BigU::one(), "a*inv should be 1 mod m");
                }
                Err(Error::NotInvertible) => {
                    assert_ne!(a.gcd(&m), BigU::one(), "only non-coprime a lack an inverse");
                }
                Err(e) => panic!("unexpected error {e:?}"),
            }
        }
    }
    #[test]
    fn div_and_rem_assign_accept_a_borrowed_rhs() {
        let rhs = BigU::from(10u32);
        let mut a = BigU::from(97u32);
        a /= &rhs;
        assert_eq!(a, BigU::from(9u32));
        let mut c = BigU::from(97u32);
        c %= &rhs;
        assert_eq!(c, BigU::from(7u32));
        assert_eq!(rhs, BigU::from(10u32), "rhs must survive both operations");
    }

}
