//! A signed arbitrary-precision integer, [`BigI`], layered on [`BigU`].
//!
//! The value is stored in **sign + magnitude** form: an unsigned [`BigU`]
//! magnitude paired with a sign flag. This sidesteps the asymmetry of a
//! two's-complement representation — there is no `MIN` with no positive
//! counterpart — so every value's negation is representable. The single
//! invariant is that zero is always positive: whenever the magnitude is zero the
//! sign flag is cleared, so `-0` normalizes to `0` and equality/ordering behave
//! as ordinary integer comparisons.
//!
//! Division and remainder are **truncated** (round the quotient toward zero),
//! matching Rust's primitive `/` and `%`: the remainder takes the sign of the
//! dividend and the identity `a == (a / b) * b + (a % b)` always holds. The
//! separate [`BigI::div_euclid`] / [`BigI::rem_euclid`] give the Euclidean
//! variant, whose remainder is always non-negative and smaller than `|b|`.
//!
//! ```
//! use bigu::BigI;
//! let a = BigI::from(-17i64);
//! let b = BigI::from(5i64);
//! let (q, r) = a.div_rem(&b).unwrap();
//! assert_eq!(q, BigI::from(-3i64));   // truncated toward zero
//! assert_eq!(r, BigI::from(-2i64));   // sign of the dividend
//! assert_eq!(a.rem_euclid(&b).unwrap(), BigI::from(3i64)); // non-negative
//! ```

use core::cmp::Ordering;
use core::fmt;
use core::ops::{Add, AddAssign, Div, Mul, MulAssign, Neg, Rem, Sub, SubAssign};
use core::str::FromStr;

use crate::bigu::BigU;
use crate::error::{Error, Result};

/// An arbitrary-precision signed integer stored as sign + magnitude.
///
/// The magnitude is a [`BigU`]; `negative` records the sign. The type keeps a
/// single invariant — zero is never negative — which makes `Eq`, `Ord` and
/// `Hash` line up with integer semantics.
#[derive(Clone, Default)]
pub struct BigI {
    /// True when the value is strictly less than zero. Always false when `mag`
    /// is zero, so that `-0` and `0` share one canonical representation.
    negative: bool,
    /// The absolute value.
    mag: BigU,
}

impl BigI {
    /// Assembles a signed value from a sign flag and a magnitude, enforcing the
    /// zero-is-positive invariant.
    pub fn from_parts(negative: bool, mag: BigU) -> BigI {
        // A zero magnitude can never be negative; force the canonical sign so a
        // stray `-0` never leaks out and poisons comparisons.
        let negative = negative && !mag.is_zero();
        BigI { negative, mag }
    }

    /// The additive identity, `0`.
    pub fn zero() -> BigI {
        BigI { negative: false, mag: BigU::zero() }
    }

    /// The multiplicative identity, `1`.
    pub fn one() -> BigI {
        BigI { negative: false, mag: BigU::one() }
    }

    /// Wraps an unsigned magnitude as a non-negative signed value.
    pub fn from_biguint(mag: BigU) -> BigI {
        BigI { negative: false, mag }
    }

    /// Returns `true` when the value is exactly zero.
    pub fn is_zero(&self) -> bool {
        self.mag.is_zero()
    }

    /// Returns `true` when the value is strictly negative.
    pub fn is_negative(&self) -> bool {
        self.negative
    }

    /// Returns `true` when the value is strictly positive.
    pub fn is_positive(&self) -> bool {
        !self.negative && !self.mag.is_zero()
    }

    /// The sign as one of `-1`, `0` or `1`.
    pub fn signum(&self) -> i32 {
        if self.mag.is_zero() {
            0
        } else if self.negative {
            -1
        } else {
            1
        }
    }

    /// The absolute value as a signed integer (always non-negative).
    pub fn abs(&self) -> BigI {
        BigI { negative: false, mag: self.mag.clone() }
    }

    /// Borrows the magnitude as an unsigned integer.
    pub fn magnitude(&self) -> &BigU {
        &self.mag
    }

    /// Consumes the value, returning its sign flag and magnitude.
    pub fn into_parts(self) -> (bool, BigU) {
        (self.negative, self.mag)
    }

    /// Raises `self` to the `exp` power. The sign follows the parity of `exp`:
    /// an even exponent is always non-negative, an odd one keeps the base sign.
    /// `x.pow(0)` is `1` for every `x`.
    pub fn pow(&self, exp: u32) -> BigI {
        let mag = self.mag.pow(exp);
        let negative = self.negative && (exp & 1 == 1);
        BigI::from_parts(negative, mag)
    }

    /// The greatest common divisor of `self` and `other`, always non-negative.
    /// The sign of the operands is irrelevant; `gcd(0, 0)` is `0`.
    pub fn gcd(&self, other: &BigI) -> BigI {
        BigI::from_biguint(self.mag.gcd(&other.mag))
    }

    /// The number of bits in the magnitude; zero has bit length `0`.
    pub fn bit_len(&self) -> u64 {
        self.mag.bit_len()
    }

    /// Returns `true` when the value is even (including zero).
    pub fn is_even(&self) -> bool {
        // The parity lives entirely in the low limb of the magnitude.
        self.mag.count_ones() == 0 || (&self.mag & &BigU::one()).is_zero()
    }

    /// Truncated quotient and remainder together: `q` rounds toward zero and
    /// `r` carries the sign of `self`, so `self == q * other + r`.
    pub fn div_rem(&self, other: &BigI) -> Result<(BigI, BigI)> {
        let (q_mag, r_mag) = self.mag.div_rem(&other.mag)?;
        let q = BigI::from_parts(self.negative ^ other.negative, q_mag);
        let r = BigI::from_parts(self.negative, r_mag);
        Ok((q, r))
    }

    /// Euclidean division: the quotient `q` and a remainder in `0..|other|`.
    ///
    /// Returns the pair `(q, r)` with `self == q * other + r` and
    /// `0 <= r < |other|`, matching `i128::div_euclid` / `i128::rem_euclid`.
    pub fn div_rem_euclid(&self, other: &BigI) -> Result<(BigI, BigI)> {
        let (mut q, mut r) = self.div_rem(other)?;
        if r.negative {
            // Truncated remainder went negative; pull it up into range and shift
            // the quotient by one toward the divisor's sign to compensate.
            r = &r + &other.abs();
            if other.negative {
                q = &q + &BigI::one();
            } else {
                q = &q - &BigI::one();
            }
        }
        Ok((q, r))
    }

    /// Euclidean quotient alone; see [`BigI::div_rem_euclid`].
    pub fn div_euclid(&self, other: &BigI) -> Result<BigI> {
        Ok(self.div_rem_euclid(other)?.0)
    }

    /// Euclidean (non-negative) remainder alone; see [`BigI::div_rem_euclid`].
    pub fn rem_euclid(&self, other: &BigI) -> Result<BigI> {
        Ok(self.div_rem_euclid(other)?.1)
    }

    /// Parses a signed integer in the given radix, honouring an optional leading
    /// `+` or `-`. The magnitude is delegated to [`BigU::from_str_radix`].
    pub fn from_str_radix(s: &str, radix: u32) -> Result<BigI> {
        let (negative, rest) = match s.strip_prefix('-') {
            Some(r) => (true, r),
            None => (false, s.strip_prefix('+').unwrap_or(s)),
        };
        let mag = BigU::from_str_radix(rest, radix)?;
        Ok(BigI::from_parts(negative, mag))
    }

    /// Renders the value in the given radix, prefixing `-` for negatives.
    pub fn to_str_radix(&self, radix: u32) -> Result<String> {
        let body = self.mag.to_str_radix(radix)?;
        if self.negative {
            Ok(format!("-{body}"))
        } else {
            Ok(body)
        }
    }

    /// Core sign+magnitude addition shared by every operator form.
    fn add_ref(&self, other: &BigI) -> BigI {
        if self.negative == other.negative {
            // Like signs: magnitudes add and the shared sign carries through.
            BigI::from_parts(self.negative, &self.mag + &other.mag)
        } else {
            // Opposite signs: the larger magnitude wins and dictates the sign.
            match self.mag.cmp(&other.mag) {
                Ordering::Equal => BigI::zero(),
                Ordering::Greater => BigI::from_parts(
                    self.negative,
                    self.mag.checked_sub(&other.mag).expect("self.mag > other.mag"),
                ),
                Ordering::Less => BigI::from_parts(
                    other.negative,
                    other.mag.checked_sub(&self.mag).expect("other.mag > self.mag"),
                ),
            }
        }
    }

    /// Core negation.
    fn neg_ref(&self) -> BigI {
        BigI::from_parts(!self.negative, self.mag.clone())
    }

    /// Core subtraction, expressed as `self + (-other)`.
    fn sub_ref(&self, other: &BigI) -> BigI {
        self.add_ref(&other.neg_ref())
    }

    /// Core multiplication: magnitudes multiply, signs xor.
    fn mul_ref(&self, other: &BigI) -> BigI {
        BigI::from_parts(self.negative ^ other.negative, &self.mag * &other.mag)
    }
}

// --- primitive conversions -------------------------------------------------

macro_rules! from_signed {
    ($($t:ty),*) => {$(
        impl From<$t> for BigI {
            fn from(v: $t) -> BigI {
                // unsigned_abs sidesteps the i*::MIN overflow that plain negation
                // would hit, since the magnitude fits the matching unsigned type.
                BigI::from_parts(v < 0, BigU::from(v.unsigned_abs()))
            }
        }
    )*};
}
from_signed!(i32, i64, i128, isize);

macro_rules! from_unsigned {
    ($($t:ty),*) => {$(
        impl From<$t> for BigI {
            fn from(v: $t) -> BigI {
                BigI::from_biguint(BigU::from(v))
            }
        }
    )*};
}
from_unsigned!(u32, u64, u128, usize);

impl From<BigU> for BigI {
    fn from(mag: BigU) -> BigI {
        BigI::from_biguint(mag)
    }
}

macro_rules! try_into_signed {
    ($($t:ty => $u:ty),*) => {$(
        impl TryFrom<&BigI> for $t {
            type Error = Error;
            fn try_from(v: &BigI) -> Result<$t> {
                // Narrow the magnitude into the matching unsigned type first, then
                // fold the sign back in. The magnitude of a negative value may be
                // exactly one past the positive range (the target's MIN), so the
                // bound is checked against MAX for positives and MIN for negatives.
                let m: $u = <$u>::try_from(v.magnitude())?;
                if v.is_negative() {
                    if m == (<$t>::MAX as $u) + 1 {
                        Ok(<$t>::MIN)
                    } else if m <= <$t>::MAX as $u {
                        Ok(-(m as $t))
                    } else {
                        Err(Error::Overflow)
                    }
                } else if m <= <$t>::MAX as $u {
                    Ok(m as $t)
                } else {
                    Err(Error::Overflow)
                }
            }
        }
    )*};
}
try_into_signed!(i64 => u64, i128 => u128);

// --- comparison ------------------------------------------------------------

impl PartialEq for BigI {
    fn eq(&self, other: &Self) -> bool {
        self.negative == other.negative && self.mag == other.mag
    }
}

impl Eq for BigI {}

impl PartialOrd for BigI {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for BigI {
    fn cmp(&self, other: &Self) -> Ordering {
        match (self.negative, other.negative) {
            (false, true) => Ordering::Greater,
            (true, false) => Ordering::Less,
            // Same sign: magnitudes order directly when positive, and invert
            // when both are negative (the larger magnitude is the smaller value).
            (false, false) => self.mag.cmp(&other.mag),
            (true, true) => other.mag.cmp(&self.mag),
        }
    }
}

impl core::hash::Hash for BigI {
    fn hash<H: core::hash::Hasher>(&self, state: &mut H) {
        self.negative.hash(state);
        self.mag.hash(state);
    }
}

// --- formatting ------------------------------------------------------------

impl fmt::Display for BigI {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Route through pad_integral so width/fill/sign flags apply to the whole
        // signed number, magnitude rendered by BigU's decimal conversion.
        let body = self.mag.to_str_radix(10).map_err(|_| fmt::Error)?;
        f.pad_integral(!self.negative, "", &body)
    }
}

impl fmt::Debug for BigI {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.to_str_radix(10) {
            Ok(s) => write!(f, "BigI({s})"),
            Err(_) => write!(f, "BigI(negative={}, {:?})", self.negative, self.mag),
        }
    }
}

impl FromStr for BigI {
    type Err = Error;
    fn from_str(s: &str) -> Result<BigI> {
        BigI::from_str_radix(s, 10)
    }
}

// --- operators -------------------------------------------------------------

impl Neg for BigI {
    type Output = BigI;
    fn neg(self) -> BigI {
        self.neg_ref()
    }
}

impl Neg for &BigI {
    type Output = BigI;
    fn neg(self) -> BigI {
        self.neg_ref()
    }
}

macro_rules! binop {
    ($trait:ident, $method:ident, $core:ident) => {
        impl $trait for BigI {
            type Output = BigI;
            fn $method(self, rhs: BigI) -> BigI {
                self.$core(&rhs)
            }
        }
        impl $trait<&BigI> for &BigI {
            type Output = BigI;
            fn $method(self, rhs: &BigI) -> BigI {
                self.$core(rhs)
            }
        }
        impl $trait<&BigI> for BigI {
            type Output = BigI;
            fn $method(self, rhs: &BigI) -> BigI {
                self.$core(rhs)
            }
        }
        impl $trait<BigI> for &BigI {
            type Output = BigI;
            fn $method(self, rhs: BigI) -> BigI {
                self.$core(&rhs)
            }
        }
    };
}
binop!(Add, add, add_ref);
binop!(Sub, sub, sub_ref);
binop!(Mul, mul, mul_ref);

impl Div for BigI {
    type Output = BigI;
    /// Truncated division; panics on a zero divisor.
    fn div(self, rhs: BigI) -> BigI {
        self.div_rem(&rhs).expect("attempt to divide by zero").0
    }
}

impl Div<&BigI> for &BigI {
    type Output = BigI;
    fn div(self, rhs: &BigI) -> BigI {
        self.div_rem(rhs).expect("attempt to divide by zero").0
    }
}

impl Rem for BigI {
    type Output = BigI;
    /// Truncated remainder; panics on a zero divisor.
    fn rem(self, rhs: BigI) -> BigI {
        self.div_rem(&rhs).expect("attempt to take remainder of a division by zero").1
    }
}

impl Rem<&BigI> for &BigI {
    type Output = BigI;
    fn rem(self, rhs: &BigI) -> BigI {
        self.div_rem(rhs).expect("attempt to take remainder of a division by zero").1
    }
}

macro_rules! assign_op {
    ($trait:ident, $method:ident, $core:ident) => {
        impl $trait for BigI {
            fn $method(&mut self, rhs: BigI) {
                *self = self.$core(&rhs);
            }
        }
        impl $trait<&BigI> for BigI {
            fn $method(&mut self, rhs: &BigI) {
                *self = self.$core(rhs);
            }
        }
    };
}
assign_op!(AddAssign, add_assign, add_ref);
assign_op!(SubAssign, sub_assign, sub_ref);
assign_op!(MulAssign, mul_assign, mul_ref);

#[cfg(test)]
mod tests {
    use super::*;

    // Small deterministic pseudo-random stream for differential testing.
    fn lcg(state: &mut u64) -> u64 {
        *state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        *state
    }

    #[test]
    fn parts_normalize_negative_zero() {
        let z = BigI::from_parts(true, BigU::zero());
        assert!(!z.is_negative());
        assert_eq!(z, BigI::zero());
        assert_eq!(z.signum(), 0);
        // -0 and 0 must hash and compare identically.
        assert_eq!(z.cmp(&BigI::zero()), Ordering::Equal);
    }

    #[test]
    fn signum_and_predicates() {
        assert_eq!(BigI::from(5i64).signum(), 1);
        assert_eq!(BigI::from(-5i64).signum(), -1);
        assert_eq!(BigI::zero().signum(), 0);
        assert!(BigI::from(-1i64).is_negative());
        assert!(BigI::from(1i64).is_positive());
        assert!(!BigI::zero().is_positive());
        assert!(!BigI::zero().is_negative());
    }

    #[test]
    fn abs_and_neg() {
        assert_eq!(BigI::from(-7i64).abs(), BigI::from(7i64));
        assert_eq!(BigI::from(7i64).abs(), BigI::from(7i64));
        assert_eq!(-BigI::from(3i64), BigI::from(-3i64));
        assert_eq!(-BigI::from(-3i64), BigI::from(3i64));
        // Negating zero stays zero (and positive).
        assert_eq!(-BigI::zero(), BigI::zero());
        assert!(!(-BigI::zero()).is_negative());
    }

    #[test]
    fn from_min_values_have_representable_magnitude() {
        // Sign+magnitude has no MIN asymmetry: i*::MIN negates cleanly.
        assert_eq!(BigI::from(i32::MIN).abs().to_str_radix(10).unwrap(), "2147483648");
        assert_eq!(BigI::from(i64::MIN).abs().to_str_radix(10).unwrap(), "9223372036854775808");
        assert_eq!(
            BigI::from(i128::MIN).abs().to_str_radix(10).unwrap(),
            "170141183460469231731687303715884105728"
        );
    }

    #[test]
    fn ordering_across_signs() {
        assert!(BigI::from(-1i64) < BigI::from(0i64));
        assert!(BigI::from(0i64) < BigI::from(1i64));
        assert!(BigI::from(-100i64) < BigI::from(-99i64));
        assert!(BigI::from(-100i64) < BigI::from(1i64));
        assert!(BigI::from(5i64) > BigI::from(-9999i64));
        assert_eq!(BigI::from(-42i64).cmp(&BigI::from(-42i64)), Ordering::Equal);
    }

    #[test]
    fn display_and_debug() {
        assert_eq!(format!("{}", BigI::from(-123i64)), "-123");
        assert_eq!(format!("{}", BigI::from(123i64)), "123");
        assert_eq!(format!("{}", BigI::zero()), "0");
        assert_eq!(format!("{:?}", BigI::from(-5i64)), "BigI(-5)");
        // pad_integral honours width, fill and the explicit-sign flag.
        assert_eq!(format!("{:05}", BigI::from(-42i64)), "-0042");
        assert_eq!(format!("{:+}", BigI::from(42i64)), "+42");
        assert_eq!(format!("{:>6}", BigI::from(-7i64)), "    -7");
    }

    #[test]
    fn parse_roundtrip_and_signs() {
        assert_eq!(BigI::from_str("-123").unwrap(), BigI::from(-123i64));
        assert_eq!(BigI::from_str("+123").unwrap(), BigI::from(123i64));
        assert_eq!(BigI::from_str("123").unwrap(), BigI::from(123i64));
        assert_eq!(BigI::from_str("-0").unwrap(), BigI::zero());
        assert!(!BigI::from_str("-0").unwrap().is_negative());
        assert_eq!(BigI::from_str_radix("-ff", 16).unwrap(), BigI::from(-255i64));
        // Round-trips through the string form.
        let v = BigI::from_str("-99999999999999999999999999").unwrap();
        assert_eq!(BigI::from_str(&v.to_str_radix(10).unwrap()).unwrap(), v);
    }

    #[test]
    fn add_sub_edge_cases() {
        // a - a is zero and positive.
        let a = BigI::from(-123456789i64);
        assert_eq!(&a - &a, BigI::zero());
        assert!(!(&a - &a).is_negative());
        // Opposite signs, equal magnitude cancel.
        assert_eq!(&BigI::from(7i64) + &BigI::from(-7i64), BigI::zero());
        // Mixed-sign addition picks the larger magnitude's sign.
        assert_eq!(&BigI::from(-10i64) + &BigI::from(3i64), BigI::from(-7i64));
        assert_eq!(&BigI::from(10i64) + &BigI::from(-3i64), BigI::from(7i64));
    }

    #[test]
    fn add_carries_across_limb_boundary() {
        // 2^32 - 1 plus 1, both negative, must borrow-free carry the magnitude.
        let a = BigI::from(-(0xFFFF_FFFFi64));
        let b = BigI::from(-1i64);
        assert_eq!(&a + &b, BigI::from(-0x1_0000_0000i64));
        // Positive minus larger positive crosses a limb going down.
        let c = BigI::from(0x1_0000_0000i64);
        assert_eq!(&BigI::from(1i64) - &c, BigI::from(-0xFFFF_FFFFi64));
    }

    #[test]
    fn assign_operators() {
        let mut a = BigI::from(-5i64);
        a += BigI::from(3i64);
        assert_eq!(a, BigI::from(-2i64));
        a -= &BigI::from(-10i64);
        assert_eq!(a, BigI::from(8i64));
        a *= BigI::from(-2i64);
        assert_eq!(a, BigI::from(-16i64));
    }

    #[test]
    fn pow_sign_parity() {
        assert_eq!(BigI::from(-2i64).pow(3), BigI::from(-8i64));
        assert_eq!(BigI::from(-2i64).pow(4), BigI::from(16i64));
        assert_eq!(BigI::from(-5i64).pow(0), BigI::one());
        assert_eq!(BigI::from(2i64).pow(10), BigI::from(1024i64));
    }

    #[test]
    fn div_rem_truncated_identity() {
        // Truncated division: quotient toward zero, remainder signed like dividend.
        let cases = [(-17i64, 5i64), (17, -5), (-17, -5), (17, 5), (-3, 7), (3, -7)];
        for (a, b) in cases {
            let (q, r) = BigI::from(a).div_rem(&BigI::from(b)).unwrap();
            assert_eq!(q, BigI::from(a / b), "quotient for {a}/{b}");
            assert_eq!(r, BigI::from(a % b), "remainder for {a}%{b}");
            // Reconstruction identity.
            assert_eq!(&(&q * &BigI::from(b)) + &r, BigI::from(a));
        }
    }

    #[test]
    fn div_by_zero_and_self() {
        assert_eq!(BigI::from(5i64).div_rem(&BigI::zero()), Err(Error::DivByZero));
        // a / a == 1, a % a == 0 for nonzero a of either sign.
        let a = BigI::from(-987654321i64);
        let (q, r) = a.div_rem(&a).unwrap();
        assert_eq!(q, BigI::one());
        assert!(r.is_zero());
    }

    #[test]
    #[should_panic(expected = "divide by zero")]
    fn div_operator_panics_on_zero() {
        let _ = BigI::from(1i64) / BigI::zero();
    }

    #[test]
    fn euclid_matches_primitive() {
        let cases = [(-17i64, 5i64), (17, -5), (-17, -5), (17, 5), (-1, 7), (8, -3), (-8, 3)];
        for (a, b) in cases {
            let q = BigI::from(a).div_euclid(&BigI::from(b)).unwrap();
            let r = BigI::from(a).rem_euclid(&BigI::from(b)).unwrap();
            assert_eq!(q, BigI::from(a.div_euclid(b)), "div_euclid {a},{b}");
            assert_eq!(r, BigI::from(a.rem_euclid(b)), "rem_euclid {a},{b}");
            // Euclidean remainder is always non-negative.
            assert!(!r.is_negative());
        }
    }

    #[test]
    fn differential_add_sub_mul_vs_i128() {
        let mut s = 0x1234_5678_9abc_def0u64;
        for _ in 0..2000 {
            // Keep operands in a range whose sums/products stay inside i128.
            let a = (lcg(&mut s) as i64 as i128) >> 8;
            let b = (lcg(&mut s) as i64 as i128) >> 8;
            let (ba, bb) = (BigI::from(a), BigI::from(b));
            assert_eq!(&ba + &bb, BigI::from(a + b), "{a}+{b}");
            assert_eq!(&ba - &bb, BigI::from(a - b), "{a}-{b}");
            assert_eq!(&ba * &bb, BigI::from(a * b), "{a}*{b}");
            assert_eq!(ba.cmp(&bb), a.cmp(&b), "cmp {a},{b}");
        }
    }

    #[test]
    fn differential_div_rem_vs_i128() {
        let mut s = 0x0fed_cba9_8765_4321u64;
        for _ in 0..2000 {
            let a = (lcg(&mut s) as i64 as i128) >> 8;
            let mut b = (lcg(&mut s) as i64 as i128) >> 8;
            if b == 0 {
                b = 1;
            }
            let (q, r) = BigI::from(a).div_rem(&BigI::from(b)).unwrap();
            assert_eq!(q, BigI::from(a / b), "q {a}/{b}");
            assert_eq!(r, BigI::from(a % b), "r {a}%{b}");
            let qe = BigI::from(a).div_euclid(&BigI::from(b)).unwrap();
            let re = BigI::from(a).rem_euclid(&BigI::from(b)).unwrap();
            assert_eq!(qe, BigI::from(a.div_euclid(b)), "qe {a},{b}");
            assert_eq!(re, BigI::from(a.rem_euclid(b)), "re {a},{b}");
        }
    }

    #[test]
    fn gcd_ignores_sign() {
        assert_eq!(BigI::from(-12i64).gcd(&BigI::from(18i64)), BigI::from(6i64));
        assert_eq!(BigI::from(12i64).gcd(&BigI::from(-18i64)), BigI::from(6i64));
        assert_eq!(BigI::from(-12i64).gcd(&BigI::from(-18i64)), BigI::from(6i64));
        assert_eq!(BigI::zero().gcd(&BigI::zero()), BigI::zero());
        assert!(!BigI::from(-12i64).gcd(&BigI::from(18i64)).is_negative());
    }

    #[test]
    fn bit_len_and_parity() {
        assert_eq!(BigI::zero().bit_len(), 0);
        assert_eq!(BigI::from(-1i64).bit_len(), 1);
        assert_eq!(BigI::from(-256i64).bit_len(), 9);
        assert!(BigI::zero().is_even());
        assert!(BigI::from(-4i64).is_even());
        assert!(!BigI::from(-5i64).is_even());
        assert!(BigI::from(1000000i64).is_even());
    }

    #[test]
    fn try_into_primitive_signed() {
        assert_eq!(i64::try_from(&BigI::from(-42i64)).unwrap(), -42);
        assert_eq!(i64::try_from(&BigI::from(i64::MIN)).unwrap(), i64::MIN);
        assert_eq!(i64::try_from(&BigI::from(i64::MAX)).unwrap(), i64::MAX);
        assert_eq!(i128::try_from(&BigI::from(i128::MIN)).unwrap(), i128::MIN);
        assert_eq!(i128::try_from(&BigI::from(i128::MAX)).unwrap(), i128::MAX);
        // One past MIN/MAX overflows.
        let too_big = &BigI::from(i64::MAX) + &BigI::one();
        assert_eq!(i64::try_from(&too_big), Err(Error::Overflow));
        let too_small = &BigI::from(i64::MIN) - &BigI::one();
        assert_eq!(i64::try_from(&too_small), Err(Error::Overflow));
    }

    #[test]
    fn mixed_owned_and_ref_operators() {
        let a = BigI::from(-10i64);
        let b = BigI::from(3i64);
        assert_eq!(&a + b.clone(), BigI::from(-7i64));
        assert_eq!(a.clone() + &b, BigI::from(-7i64));
        assert_eq!(&a - b.clone(), BigI::from(-13i64));
        assert_eq!(a.clone() * &b, BigI::from(-30i64));
    }

    #[test]
    fn large_multi_limb_arithmetic() {
        // 10^30 spans several limbs; check sign handling survives the scale.
        let big = BigI::from_biguint(BigU::from(10u32).pow(30));
        let neg = -&big;
        assert_eq!(&big + &neg, BigI::zero());
        assert_eq!(&neg * &neg, &big * &big);
        assert!((&neg * &big).is_negative());
        let (q, r) = (&big * &big).div_rem(&big).unwrap();
        assert_eq!(q, big);
        assert!(r.is_zero());
    }
}
