//! An exact rational number, [`BigQ`], layered on [`BigI`] and [`BigU`].
//!
//! The value is stored as a signed numerator over an unsigned denominator, and
//! two invariants hold at all times: the denominator is never zero, and the
//! fraction is fully reduced (`gcd(|num|, den) == 1`, with zero canonicalized
//! to `0/1`). Because construction always reduces, `Eq`, `Ord` and `Hash` all
//! line up with mathematical equality — `2/4` and `1/2` are the same value.
//!
//! Addition and multiplication follow Knuth's cross-gcd recipe (TAOCP Vol. 2,
//! §4.5.1): common factors are divided out *before* the cross products are
//! formed, so intermediates stay near the size of the reduced result instead
//! of ballooning and being reduced after the fact.
//!
//! ```
//! use bigu::BigQ;
//! use std::str::FromStr;
//!
//! let third = BigQ::from_str("1/3").unwrap();
//! let sum = &third + &BigQ::from_str("1/6").unwrap();
//! assert_eq!(sum, BigQ::from_str("1/2").unwrap());
//! assert_eq!(sum.to_decimal(4), "0.5000");
//! ```

use core::cmp::Ordering;
use core::fmt;
use core::ops::{Add, Div, Mul, Neg, Sub};
use core::str::FromStr;

use crate::bigi::BigI;
use crate::bigu::BigU;
use crate::error::{Error, Result};

/// An arbitrary-precision rational number in lowest terms.
///
/// The numerator carries the sign; the denominator is strictly positive. Every
/// constructor reduces, so equal values always share one representation.
#[derive(Clone)]
pub struct BigQ {
    /// Signed numerator; zero exactly when the value is zero.
    num: BigI,
    /// Unsigned denominator; never zero, coprime to `|num|`.
    den: BigU,
}

impl BigQ {
    /// Builds a rational from a signed numerator and denominator, reducing to
    /// lowest terms. A zero denominator is rejected with [`Error::DivByZero`];
    /// a negative denominator moves its sign onto the numerator.
    pub fn new(num: BigI, den: BigI) -> Result<BigQ> {
        if den.is_zero() {
            return Err(Error::DivByZero);
        }
        let (den_neg, den_mag) = den.into_parts();
        let num = if den_neg { -num } else { num };
        Ok(BigQ::reduced(num, den_mag))
    }

    /// Internal constructor: reduces `num/den` assuming `den` is nonzero.
    fn reduced(num: BigI, den: BigU) -> BigQ {
        if num.is_zero() {
            return BigQ::zero();
        }
        let g = num.magnitude().gcd(&den);
        if g == BigU::one() {
            return BigQ { num, den };
        }
        let (neg, mag) = num.into_parts();
        let mag = mag.div_rem(&g).expect("gcd of a nonzero pair is nonzero").0;
        let den = den.div_rem(&g).expect("gcd of a nonzero pair is nonzero").0;
        BigQ {
            num: BigI::from_parts(neg, mag),
            den,
        }
    }

    /// The additive identity, `0/1`.
    pub fn zero() -> BigQ {
        BigQ {
            num: BigI::zero(),
            den: BigU::one(),
        }
    }

    /// The multiplicative identity, `1/1`.
    pub fn one() -> BigQ {
        BigQ {
            num: BigI::one(),
            den: BigU::one(),
        }
    }

    /// Wraps an integer as a rational with denominator one.
    pub fn from_integer(n: BigI) -> BigQ {
        BigQ {
            num: n,
            den: BigU::one(),
        }
    }

    /// Borrows the numerator.
    pub fn numer(&self) -> &BigI {
        &self.num
    }

    /// Borrows the denominator.
    pub fn denom(&self) -> &BigU {
        &self.den
    }

    /// Returns `true` when the value is exactly zero.
    pub fn is_zero(&self) -> bool {
        self.num.is_zero()
    }

    /// Returns `true` when the value is a whole integer.
    pub fn is_integer(&self) -> bool {
        self.den == BigU::one()
    }

    /// The sign as one of `-1`, `0` or `1`.
    pub fn signum(&self) -> i32 {
        self.num.signum()
    }

    /// The absolute value.
    pub fn abs(&self) -> BigQ {
        BigQ {
            num: self.num.abs(),
            den: self.den.clone(),
        }
    }

    /// The multiplicative inverse; zero has none and reports
    /// [`Error::DivByZero`].
    pub fn recip(&self) -> Result<BigQ> {
        if self.is_zero() {
            return Err(Error::DivByZero);
        }
        let (neg, mag) = self.num.clone().into_parts();
        // Swapping a reduced pair stays reduced; only the sign moves.
        Ok(BigQ {
            num: BigI::from_parts(neg, self.den.clone()),
            den: mag,
        })
    }

    /// Knuth's addition: divide out `g1 = gcd(b, d)` first so the cross
    /// products stay small, then clear the one factor (`g2`) the sum can still
    /// share with `g1`.
    fn add_ref(&self, other: &BigQ) -> BigQ {
        let (b, d) = (&self.den, &other.den);
        let g1 = b.gcd(d);
        let b1 = b.div_rem(&g1).expect("gcd is nonzero").0;
        let d1 = d.div_rem(&g1).expect("gcd is nonzero").0;
        let t = &(&self.num * &BigI::from_biguint(d1))
            + &(&other.num * &BigI::from_biguint(b1.clone()));
        if t.is_zero() {
            return BigQ::zero();
        }
        let g2 = t.magnitude().gcd(&g1);
        let (neg, mag) = t.into_parts();
        let mag = mag.div_rem(&g2).expect("gcd is nonzero").0;
        let d2 = d.div_rem(&g2).expect("gcd is nonzero").0;
        BigQ {
            num: BigI::from_parts(neg, mag),
            den: &b1 * &d2,
        }
    }

    /// Knuth's multiplication: cancel across the diagonal before multiplying,
    /// so the products come out already reduced.
    fn mul_ref(&self, other: &BigQ) -> BigQ {
        if self.is_zero() || other.is_zero() {
            return BigQ::zero();
        }
        let g1 = self.num.magnitude().gcd(&other.den);
        let g2 = other.num.magnitude().gcd(&self.den);
        let (n1, m1) = self.num.clone().into_parts();
        let (n2, m2) = other.num.clone().into_parts();
        let m1 = m1.div_rem(&g1).expect("gcd is nonzero").0;
        let m2 = m2.div_rem(&g2).expect("gcd is nonzero").0;
        let b = self.den.div_rem(&g2).expect("gcd is nonzero").0;
        let d = other.den.div_rem(&g1).expect("gcd is nonzero").0;
        BigQ {
            num: BigI::from_parts(n1 ^ n2, &m1 * &m2),
            den: &b * &d,
        }
    }

    /// Checked division; dividing by zero reports [`Error::DivByZero`].
    pub fn checked_div(&self, other: &BigQ) -> Result<BigQ> {
        Ok(self.mul_ref(&other.recip()?))
    }

    /// Raises `self` to a signed power. A negative exponent inverts first, so
    /// `0.pow(-k)` reports [`Error::DivByZero`]; `x.pow(0)` is `1` for every
    /// `x`, including zero.
    pub fn pow(&self, exp: i32) -> Result<BigQ> {
        if exp == 0 {
            return Ok(BigQ::one());
        }
        let base = if exp < 0 { self.recip()? } else { self.clone() };
        let e = exp.unsigned_abs();
        // Both halves of a reduced fraction stay coprime under powers.
        Ok(BigQ {
            num: base.num.pow(e),
            den: base.den.pow(e),
        })
    }

    /// The largest integer not above the value.
    pub fn floor(&self) -> BigI {
        let den = BigI::from_biguint(self.den.clone());
        self.num
            .div_rem_euclid(&den)
            .expect("denominator is nonzero")
            .0
    }

    /// The smallest integer not below the value.
    pub fn ceil(&self) -> BigI {
        // ceil(x) = -floor(-x): reuse the Euclidean floor through negation.
        -(-self.clone()).floor()
    }

    /// The integer part, rounding toward zero.
    pub fn trunc(&self) -> BigI {
        let den = BigI::from_biguint(self.den.clone());
        self.num.div_rem(&den).expect("denominator is nonzero").0
    }

    /// Rounds to the nearest integer, ties to the even neighbour.
    pub fn round_half_even(&self) -> BigI {
        let fl = self.floor();
        // Compare the fractional part against 1/2 by cross-multiplying:
        // frac = self - fl, so 2 * (num - fl * den) versus den.
        let den = BigI::from_biguint(self.den.clone());
        let rem = &self.num - &(&fl * &den);
        let twice = &rem + &rem;
        match twice.magnitude().cmp(&self.den) {
            Ordering::Less => fl,
            Ordering::Greater => &fl + &BigI::one(),
            Ordering::Equal => {
                // Tie: pick whichever neighbour is even.
                let up = &fl + &BigI::one();
                if fl.magnitude().bit(0) {
                    up
                } else {
                    fl
                }
            }
        }
    }

    /// Returns `true` when the decimal expansion terminates — that is, the
    /// reduced denominator has no prime factors besides 2 and 5.
    pub fn is_terminating(&self) -> bool {
        let mut d = self.den.clone();
        for p in [2u32, 5] {
            let p = BigU::from(p);
            loop {
                let (q, r) = d.div_rem(&p).expect("p is nonzero");
                if r.is_zero() {
                    d = q;
                } else {
                    break;
                }
            }
        }
        d == BigU::one()
    }

    /// Renders the value as an exact decimal string with `places` digits after
    /// the point, rounding ties to even. The digits are computed by integer
    /// scaling and division — no floating point is involved, so the result is
    /// correct for values of any size.
    pub fn to_decimal(&self, places: usize) -> String {
        let scale = BigU::from(10u32).pow(places as u32);
        let scaled = self.num.magnitude() * &scale;
        let (mut q, r) = scaled.div_rem(&self.den).expect("denominator is nonzero");
        // Round half to even on the discarded remainder.
        let twice = &r + &r;
        let round_up = match twice.cmp(&self.den) {
            Ordering::Greater => true,
            Ordering::Less => false,
            Ordering::Equal => q.bit(0),
        };
        if round_up {
            q = &q + &BigU::one();
        }
        let digits = q.to_str_radix(10).expect("radix 10 is supported");
        let digits = if digits.len() <= places {
            format!("{}{}", "0".repeat(places - digits.len() + 1), digits)
        } else {
            digits
        };
        let split = digits.len() - places;
        let sign = if self.num.is_negative() && digits.bytes().any(|b| b != b'0') {
            "-"
        } else {
            ""
        };
        if places == 0 {
            format!("{sign}{digits}")
        } else {
            format!("{sign}{}.{}", &digits[..split], &digits[split..])
        }
    }
}

impl PartialEq for BigQ {
    fn eq(&self, other: &BigQ) -> bool {
        // Canonical form makes structural equality mathematical equality.
        self.num == other.num && self.den == other.den
    }
}

impl Eq for BigQ {}

impl PartialOrd for BigQ {
    fn partial_cmp(&self, other: &BigQ) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for BigQ {
    fn cmp(&self, other: &BigQ) -> Ordering {
        // Cross-multiply: a/b <=> c/d exactly when a*d <=> c*b (b, d > 0).
        let lhs = &self.num * &BigI::from_biguint(other.den.clone());
        let rhs = &other.num * &BigI::from_biguint(self.den.clone());
        lhs.cmp(&rhs)
    }
}

impl core::hash::Hash for BigQ {
    fn hash<H: core::hash::Hasher>(&self, state: &mut H) {
        self.num.hash(state);
        self.den.hash(state);
    }
}

impl Default for BigQ {
    fn default() -> BigQ {
        BigQ::zero()
    }
}

// --- conversions ------------------------------------------------------------

impl From<BigI> for BigQ {
    fn from(n: BigI) -> BigQ {
        BigQ::from_integer(n)
    }
}

impl From<BigU> for BigQ {
    fn from(n: BigU) -> BigQ {
        BigQ::from_integer(BigI::from_biguint(n))
    }
}

impl From<i64> for BigQ {
    fn from(n: i64) -> BigQ {
        BigQ::from_integer(BigI::from(n))
    }
}

impl FromStr for BigQ {
    type Err = Error;

    /// Accepts three shapes: a plain integer (`"-42"`), a fraction
    /// (`"-3/4"`), and a decimal literal (`"2.75"`), each with an optional
    /// leading sign. Decimal literals convert exactly: `"0.1"` becomes `1/10`,
    /// not the nearest double.
    fn from_str(s: &str) -> Result<BigQ> {
        if let Some((n, d)) = s.split_once('/') {
            return BigQ::new(BigI::from_str(n)?, BigI::from_str(d)?);
        }
        if let Some((whole, frac)) = s.split_once('.') {
            if frac.is_empty() || frac.starts_with(['+', '-']) {
                let ch = frac.chars().next().unwrap_or('.');
                return Err(Error::InvalidDigit { ch, radix: 10 });
            }
            // "-0.5" needs the sign applied to the whole value, not just the
            // integer part, which parses to a signless zero.
            let (neg, whole) = match whole.strip_prefix('-') {
                Some(rest) => (true, rest),
                None => (false, whole.strip_prefix('+').unwrap_or(whole)),
            };
            let scale = BigU::from(10u32).pow(frac.len() as u32);
            let whole = if whole.is_empty() {
                BigU::zero()
            } else {
                BigU::from_str(whole)?
            };
            let mag = &(&whole * &scale) + &BigU::from_str(frac)?;
            return Ok(BigQ::reduced(BigI::from_parts(neg, mag), scale));
        }
        Ok(BigQ::from_integer(BigI::from_str(s)?))
    }
}

// --- operators ---------------------------------------------------------------

macro_rules! forward_binop {
    ($trait:ident, $method:ident, $core:ident) => {
        impl $trait for &BigQ {
            type Output = BigQ;
            fn $method(self, rhs: &BigQ) -> BigQ {
                self.$core(rhs)
            }
        }
        impl $trait for BigQ {
            type Output = BigQ;
            fn $method(self, rhs: BigQ) -> BigQ {
                self.$core(&rhs)
            }
        }
    };
}

impl BigQ {
    /// Core subtraction, expressed as `self + (-other)`.
    fn sub_ref(&self, other: &BigQ) -> BigQ {
        self.add_ref(&-other.clone())
    }

    /// Core division; panics on a zero divisor, matching primitive `/`. Use
    /// [`BigQ::checked_div`] for a non-panicking variant.
    fn div_ref(&self, other: &BigQ) -> BigQ {
        self.checked_div(other).expect("division by zero")
    }
}

forward_binop!(Add, add, add_ref);
forward_binop!(Sub, sub, sub_ref);
forward_binop!(Mul, mul, mul_ref);
forward_binop!(Div, div, div_ref);

impl Neg for BigQ {
    type Output = BigQ;
    fn neg(self) -> BigQ {
        BigQ {
            num: -self.num,
            den: self.den,
        }
    }
}

impl Neg for &BigQ {
    type Output = BigQ;
    fn neg(self) -> BigQ {
        -self.clone()
    }
}

// --- formatting --------------------------------------------------------------

impl fmt::Display for BigQ {
    /// Integers render bare (`"5"`), everything else as `"num/den"`, with the
    /// format spec applied to the whole token via `pad_integral`.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let mag = self
            .num
            .magnitude()
            .to_str_radix(10)
            .map_err(|_| fmt::Error)?;
        let body = if self.is_integer() {
            mag
        } else {
            let den = self.den.to_str_radix(10).map_err(|_| fmt::Error)?;
            format!("{mag}/{den}")
        };
        f.pad_integral(!self.num.is_negative(), "", &body)
    }
}

impl fmt::Debug for BigQ {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "BigQ({}/{})", self.num, self.den)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn q(s: &str) -> BigQ {
        BigQ::from_str(s).unwrap()
    }

    #[test]
    fn construction_reduces_and_normalizes_signs() {
        assert_eq!(q("2/4"), q("1/2"));
        assert_eq!(q("-2/4"), q("1/-2"));
        assert_eq!(q("-3/-6"), q("1/2"));
        assert_eq!(q("0/7"), BigQ::zero());
        assert_eq!(q("0/7").denom(), &BigU::one());
        assert_eq!(BigQ::new(BigI::one(), BigI::zero()), Err(Error::DivByZero));
    }

    #[test]
    fn parsing_accepts_all_three_shapes() {
        assert_eq!(q("42"), BigQ::from(42i64));
        assert_eq!(q("+42"), BigQ::from(42i64));
        assert_eq!(q("-42"), BigQ::from(-42i64));
        assert_eq!(q("2.75"), q("11/4"));
        assert_eq!(q("-0.5"), q("-1/2"));
        assert_eq!(q("+0.5"), q("1/2"));
        assert_eq!(q(".5"), q("1/2"));
        // Decimal literals are exact, not nearest-double.
        assert_eq!(q("0.1"), q("1/10"));
    }

    #[test]
    fn parsing_rejects_malformed_input() {
        assert_eq!(BigQ::from_str(""), Err(Error::EmptyString));
        assert_eq!(BigQ::from_str("1/0"), Err(Error::DivByZero));
        assert!(BigQ::from_str("1.").is_err());
        assert!(BigQ::from_str("1.-5").is_err());
        assert!(BigQ::from_str("1.2.3").is_err());
        assert!(BigQ::from_str("a/b").is_err());
        assert!(BigQ::from_str("1/2/3").is_err());
    }

    #[test]
    fn recip_and_checked_div() {
        assert_eq!(q("3/4").recip().unwrap(), q("4/3"));
        assert_eq!(q("-3/4").recip().unwrap(), q("-4/3"));
        assert_eq!(BigQ::zero().recip(), Err(Error::DivByZero));
        assert_eq!(q("1/2").checked_div(&q("3/2")).unwrap(), q("1/3"));
        assert_eq!(q("1/2").checked_div(&BigQ::zero()), Err(Error::DivByZero));
    }

    #[test]
    fn pow_handles_signed_exponents() {
        assert_eq!(q("2/3").pow(3).unwrap(), q("8/27"));
        assert_eq!(q("2/3").pow(-2).unwrap(), q("9/4"));
        assert_eq!(q("-2/3").pow(2).unwrap(), q("4/9"));
        assert_eq!(q("-2/3").pow(3).unwrap(), q("-8/27"));
        assert_eq!(BigQ::zero().pow(0).unwrap(), BigQ::one());
        assert_eq!(BigQ::zero().pow(-1), Err(Error::DivByZero));
    }

    #[test]
    fn integer_extraction_rounds_each_way() {
        let x = q("-7/2"); // -3.5
        assert_eq!(x.floor(), BigI::from(-4i64));
        assert_eq!(x.ceil(), BigI::from(-3i64));
        assert_eq!(x.trunc(), BigI::from(-3i64));
        // Ties go to the even neighbour in both directions.
        assert_eq!(q("7/2").round_half_even(), BigI::from(4i64));
        assert_eq!(q("5/2").round_half_even(), BigI::from(2i64));
        assert_eq!(q("-5/2").round_half_even(), BigI::from(-2i64));
        assert_eq!(q("-7/2").round_half_even(), BigI::from(-4i64));
        // Non-ties round to nearest.
        assert_eq!(q("7/3").round_half_even(), BigI::from(2i64));
        assert_eq!(q("-8/3").round_half_even(), BigI::from(-3i64));
        // Integers pass through every extractor unchanged.
        for f in [BigQ::floor, BigQ::ceil, BigQ::trunc, BigQ::round_half_even] {
            assert_eq!(f(&q("-9")), BigI::from(-9i64));
        }
    }

    #[test]
    fn terminating_detection() {
        assert!(q("1/8").is_terminating());
        assert!(q("3/40").is_terminating());
        assert!(q("7").is_terminating());
        assert!(BigQ::zero().is_terminating());
        assert!(!q("1/3").is_terminating());
        assert!(!q("1/14").is_terminating());
        // Reduction happens first: 3/6 is 1/2, which terminates.
        assert!(q("3/6").is_terminating());
    }

    #[test]
    fn decimal_edge_cases() {
        // Carry across the point: 0.999... rounds up to 1.00.
        assert_eq!(q("2999/3000").to_decimal(2), "1.00");
        // A negative that rounds to zero loses its sign entirely.
        assert_eq!(q("-1/300").to_decimal(2), "0.00");
        assert_eq!(q("-1/30").to_decimal(2), "-0.03");
        // Half-to-even on the discarded tail.
        assert_eq!(q("1/40").to_decimal(2), "0.02"); // 0.025 -> even 2
        assert_eq!(q("3/40").to_decimal(2), "0.08"); // 0.075 -> even 8
        assert_eq!(BigQ::zero().to_decimal(3), "0.000");
    }

    #[test]
    fn display_honours_the_format_spec() {
        assert_eq!(format!("{}", q("-3/4")), "-3/4");
        assert_eq!(format!("{}", q("5/1")), "5");
        assert_eq!(format!("{:>8}", q("1/2")), "     1/2");
        assert_eq!(format!("{:+}", q("1/2")), "+1/2");
        assert_eq!(format!("{:?}", q("-3/4")), "BigQ(-3/4)");
    }

    #[test]
    fn hash_and_ord_line_up_with_equality() {
        use std::collections::hash_map::DefaultHasher;
        use std::hash::{Hash, Hasher};
        let h = |v: &BigQ| {
            let mut s = DefaultHasher::new();
            v.hash(&mut s);
            s.finish()
        };
        assert_eq!(h(&q("2/4")), h(&q("1/2")));
        assert!(q("-1/2") < q("1/3"));
        assert!(q("1/3") < q("1/2"));
        assert!(q("-1/2") < q("-1/3"));
        assert_eq!(q("1/2").cmp(&q("2/4")), Ordering::Equal);
        assert_eq!(BigQ::default(), BigQ::zero());
    }

    #[test]
    fn conversions_and_accessors() {
        assert_eq!(BigQ::from(BigU::from(7u32)), q("7"));
        assert_eq!(BigQ::from(BigI::from(-7i64)), q("-7"));
        assert_eq!(q("-3/4").signum(), -1);
        assert_eq!(BigQ::zero().signum(), 0);
        assert_eq!(q("-3/4").abs(), q("3/4"));
        assert!(q("4/2").is_integer());
        assert!(!q("1/2").is_integer());
        let v = q("-3/4");
        assert_eq!(v.numer(), &BigI::from(-3i64));
        assert_eq!(v.denom(), &BigU::from(4u32));
    }

    #[test]
    #[should_panic(expected = "division by zero")]
    fn operator_div_by_zero_panics() {
        let _ = q("1/2") / BigQ::zero();
    }
}
