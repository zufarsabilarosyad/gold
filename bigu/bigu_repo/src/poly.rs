//! Univariate polynomials over exact numeric types.
//!
//! [`Poly<T>`] represents a univariate polynomial $P(x) = \sum_{i=0}^n c_i x^i$
//! with coefficients in `T` (such as [`BigI`] or [`BigQ`]).
//!
//! Canonical representation is maintained at all times: trailing zero
//! coefficients are stripped, and the zero polynomial has an empty coefficient
//! vector with degree `None`.

use core::fmt;
use core::ops::{Add, Mul, Neg, Sub};
use core::str::FromStr;

use crate::bigi::BigI;
use crate::error::{Error, Result};
use crate::ratio::BigQ;

/// A univariate polynomial with coefficients of type `T`.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Poly<T> {
    coeffs: Vec<T>,
}

/// Helper trait for polynomial coefficient rings and fields.
pub trait PolyCoeff: Clone + PartialEq + fmt::Display + fmt::Debug {
    fn zero() -> Self;
    fn one() -> Self;
    fn is_zero(&self) -> bool;
    fn is_one(&self) -> bool;
    fn is_negative(&self) -> bool;
    fn add_coeff(&self, other: &Self) -> Self;
}

impl PolyCoeff for BigI {
    fn zero() -> Self {
        BigI::zero()
    }
    fn one() -> Self {
        BigI::one()
    }
    fn is_zero(&self) -> bool {
        BigI::is_zero(self)
    }
    fn is_one(&self) -> bool {
        self == &BigI::one()
    }
    fn is_negative(&self) -> bool {
        BigI::is_negative(self)
    }
    fn add_coeff(&self, other: &Self) -> Self {
        self + other
    }
}

impl PolyCoeff for BigQ {
    fn zero() -> Self {
        BigQ::zero()
    }
    fn one() -> Self {
        BigQ::one()
    }
    fn is_zero(&self) -> bool {
        BigQ::is_zero(self)
    }
    fn is_one(&self) -> bool {
        self == &BigQ::one()
    }
    fn is_negative(&self) -> bool {
        self.numer().is_negative()
    }
    fn add_coeff(&self, other: &Self) -> Self {
        self + other
    }
}

impl<T: PolyCoeff> Poly<T> {
    /// Creates a polynomial from a list of coefficients $[c_0, c_1, \dots, c_n]$,
    /// normalizing away any trailing zeros.
    pub fn new(mut coeffs: Vec<T>) -> Self {
        while let Some(last) = coeffs.last() {
            if last.is_zero() {
                coeffs.pop();
            } else {
                break;
            }
        }
        Poly { coeffs }
    }

    /// Creates a polynomial from a coefficient slice.
    pub fn from_coeffs(coeffs: &[T]) -> Self {
        Self::new(coeffs.to_vec())
    }

    /// The zero polynomial $0$.
    pub fn zero() -> Self {
        Poly { coeffs: Vec::new() }
    }

    /// The multiplicative identity $1$.
    pub fn one() -> Self {
        Poly {
            coeffs: vec![T::one()],
        }
    }

    /// The monomial $x$.
    pub fn x() -> Self {
        Poly {
            coeffs: vec![T::zero(), T::one()],
        }
    }

    /// Creates a single monomial $c \cdot x^d$.
    pub fn from_monomial(degree: usize, coeff: T) -> Self {
        if coeff.is_zero() {
            Self::zero()
        } else {
            let mut coeffs = vec![T::zero(); degree];
            coeffs.push(coeff);
            Poly { coeffs }
        }
    }

    /// Returns `true` if this is the zero polynomial.
    pub fn is_zero(&self) -> bool {
        self.coeffs.is_empty()
    }

    /// Returns `true` if this is the constant polynomial $1$.
    pub fn is_one(&self) -> bool {
        self.coeffs.len() == 1 && self.coeffs[0].is_one()
    }

    /// Returns `true` if this is a constant polynomial (degree 0 or zero).
    pub fn is_constant(&self) -> bool {
        self.coeffs.len() <= 1
    }

    /// The degree of the polynomial, or `None` if this is the zero polynomial.
    pub fn degree(&self) -> Option<usize> {
        if self.coeffs.is_empty() {
            None
        } else {
            Some(self.coeffs.len() - 1)
        }
    }

    /// The leading coefficient of the polynomial, or `None` if zero.
    pub fn leading_coeff(&self) -> Option<&T> {
        self.coeffs.last()
    }

    /// Borrow the coefficient slice $[c_0, c_1, \dots, c_n]$.
    pub fn coeffs(&self) -> &[T] {
        &self.coeffs
    }

    /// Consume the polynomial and return the coefficient vector.
    pub fn into_coeffs(self) -> Vec<T> {
        self.coeffs
    }

    /// Returns the coefficient of $x^k$, or `None` if $k > \deg(P)$.
    pub fn coeff(&self, power: usize) -> Option<&T> {
        self.coeffs.get(power)
    }
}

// === Addition, Subtraction, Negation ===

impl<T: PolyCoeff> Add for &Poly<T> {
    type Output = Poly<T>;
    fn add(self, rhs: Self) -> Poly<T> {
        let max_len = self.coeffs.len().max(rhs.coeffs.len());
        let mut out = Vec::with_capacity(max_len);
        for i in 0..max_len {
            let a = self.coeffs.get(i);
            let b = rhs.coeffs.get(i);
            let val = match (a, b) {
                (Some(x), Some(y)) => x.add_coeff(y),
                (Some(x), None) => x.clone(),
                (None, Some(y)) => y.clone(),
                (None, None) => unreachable!(),
            };
            out.push(val);
        }
        Poly::new(out)
    }
}

impl<T: PolyCoeff> Add for Poly<T> {
    type Output = Poly<T>;
    fn add(self, rhs: Self) -> Poly<T> {
        &self + &rhs
    }
}

impl Sub for &Poly<BigI> {
    type Output = Poly<BigI>;
    fn sub(self, rhs: Self) -> Poly<BigI> {
        let max_len = self.coeffs.len().max(rhs.coeffs.len());
        let mut out = Vec::with_capacity(max_len);
        for i in 0..max_len {
            let a = self.coeffs.get(i);
            let b = rhs.coeffs.get(i);
            let val = match (a, b) {
                (Some(x), Some(y)) => x - y,
                (Some(x), None) => x.clone(),
                (None, Some(y)) => -y,
                (None, None) => unreachable!(),
            };
            out.push(val);
        }
        Poly::new(out)
    }
}

impl Sub for Poly<BigI> {
    type Output = Poly<BigI>;
    fn sub(self, rhs: Self) -> Poly<BigI> {
        &self - &rhs
    }
}

impl Sub for &Poly<BigQ> {
    type Output = Poly<BigQ>;
    fn sub(self, rhs: Self) -> Poly<BigQ> {
        let max_len = self.coeffs.len().max(rhs.coeffs.len());
        let mut out = Vec::with_capacity(max_len);
        for i in 0..max_len {
            let a = self.coeffs.get(i);
            let b = rhs.coeffs.get(i);
            let val = match (a, b) {
                (Some(x), Some(y)) => x - y,
                (Some(x), None) => x.clone(),
                (None, Some(y)) => -y,
                (None, None) => unreachable!(),
            };
            out.push(val);
        }
        Poly::new(out)
    }
}

impl Sub for Poly<BigQ> {
    type Output = Poly<BigQ>;
    fn sub(self, rhs: Self) -> Poly<BigQ> {
        &self - &rhs
    }
}

impl Neg for &Poly<BigI> {
    type Output = Poly<BigI>;
    fn neg(self) -> Poly<BigI> {
        let out: Vec<BigI> = self.coeffs.iter().map(|c| -c).collect();
        Poly::new(out)
    }
}

impl Neg for Poly<BigI> {
    type Output = Poly<BigI>;
    fn neg(self) -> Poly<BigI> {
        -&self
    }
}

impl Neg for &Poly<BigQ> {
    type Output = Poly<BigQ>;
    fn neg(self) -> Poly<BigQ> {
        let out: Vec<BigQ> = self.coeffs.iter().map(|c| -c).collect();
        Poly::new(out)
    }
}

impl Neg for Poly<BigQ> {
    type Output = Poly<BigQ>;
    fn neg(self) -> Poly<BigQ> {
        -&self
    }
}

// === Multiplication with Karatsuba ===

const KARATSUBA_POLY_THRESHOLD: usize = 16;

fn schoolbook_mul_bigi(a: &[BigI], b: &[BigI]) -> Vec<BigI> {
    if a.is_empty() || b.is_empty() {
        return Vec::new();
    }
    let mut out = vec![BigI::zero(); a.len() + b.len() - 1];
    for (i, x) in a.iter().enumerate() {
        if x.is_zero() {
            continue;
        }
        for (j, y) in b.iter().enumerate() {
            if y.is_zero() {
                continue;
            }
            let prod = x * y;
            out[i + j] = &out[i + j] + &prod;
        }
    }
    out
}

fn karatsuba_mul_bigi(a: &[BigI], b: &[BigI]) -> Vec<BigI> {
    let n = a.len();
    let m = b.len();
    if n == 0 || m == 0 {
        return Vec::new();
    }
    if n < KARATSUBA_POLY_THRESHOLD || m < KARATSUBA_POLY_THRESHOLD {
        return schoolbook_mul_bigi(a, b);
    }
    let k = n.max(m) / 2;
    let (a0, a1) = if a.len() <= k { (a, &[][..]) } else { (&a[..k], &a[k..]) };
    let (b0, b1) = if b.len() <= k { (b, &[][..]) } else { (&b[..k], &b[k..]) };

    let z0 = karatsuba_mul_bigi(a0, b0);
    let z2 = karatsuba_mul_bigi(a1, b1);

    let max_a = a0.len().max(a1.len());
    let mut a_sum = vec![BigI::zero(); max_a];
    for (i, c) in a0.iter().enumerate() { a_sum[i] = &a_sum[i] + c; }
    for (i, c) in a1.iter().enumerate() { a_sum[i] = &a_sum[i] + c; }

    let max_b = b0.len().max(b1.len());
    let mut b_sum = vec![BigI::zero(); max_b];
    for (i, c) in b0.iter().enumerate() { b_sum[i] = &b_sum[i] + c; }
    for (i, c) in b1.iter().enumerate() { b_sum[i] = &b_sum[i] + c; }

    let z1_raw = karatsuba_mul_bigi(&a_sum, &b_sum);

    let mut z1 = z1_raw;
    for (i, c) in z0.iter().enumerate() {
        if i < z1.len() { z1[i] = &z1[i] - c; }
    }
    for (i, c) in z2.iter().enumerate() {
        if i < z1.len() { z1[i] = &z1[i] - c; }
    }

    let out_len = n + m - 1;
    let mut out = vec![BigI::zero(); out_len];
    for (i, c) in z0.iter().enumerate() {
        if i < out_len { out[i] = &out[i] + c; }
    }
    for (i, c) in z1.iter().enumerate() {
        if i + k < out_len { out[i + k] = &out[i + k] + c; }
    }
    for (i, c) in z2.iter().enumerate() {
        if i + 2 * k < out_len { out[i + 2 * k] = &out[i + 2 * k] + c; }
    }
    out
}

impl Mul for &Poly<BigI> {
    type Output = Poly<BigI>;
    fn mul(self, rhs: Self) -> Poly<BigI> {
        let coeffs = karatsuba_mul_bigi(&self.coeffs, &rhs.coeffs);
        Poly::new(coeffs)
    }
}

impl Mul for Poly<BigI> {
    type Output = Poly<BigI>;
    fn mul(self, rhs: Self) -> Poly<BigI> {
        &self * &rhs
    }
}

fn schoolbook_mul_bigq(a: &[BigQ], b: &[BigQ]) -> Vec<BigQ> {
    if a.is_empty() || b.is_empty() {
        return Vec::new();
    }
    let mut out = vec![BigQ::zero(); a.len() + b.len() - 1];
    for (i, x) in a.iter().enumerate() {
        if x.is_zero() {
            continue;
        }
        for (j, y) in b.iter().enumerate() {
            if y.is_zero() {
                continue;
            }
            let prod = x * y;
            out[i + j] = &out[i + j] + &prod;
        }
    }
    out
}

fn karatsuba_mul_bigq(a: &[BigQ], b: &[BigQ]) -> Vec<BigQ> {
    let n = a.len();
    let m = b.len();
    if n == 0 || m == 0 {
        return Vec::new();
    }
    if n < KARATSUBA_POLY_THRESHOLD || m < KARATSUBA_POLY_THRESHOLD {
        return schoolbook_mul_bigq(a, b);
    }
    let k = n.max(m) / 2;
    let (a0, a1) = if a.len() <= k { (a, &[][..]) } else { (&a[..k], &a[k..]) };
    let (b0, b1) = if b.len() <= k { (b, &[][..]) } else { (&b[..k], &b[k..]) };

    let z0 = karatsuba_mul_bigq(a0, b0);
    let z2 = karatsuba_mul_bigq(a1, b1);

    let max_a = a0.len().max(a1.len());
    let mut a_sum = vec![BigQ::zero(); max_a];
    for (i, c) in a0.iter().enumerate() { a_sum[i] = &a_sum[i] + c; }
    for (i, c) in a1.iter().enumerate() { a_sum[i] = &a_sum[i] + c; }

    let max_b = b0.len().max(b1.len());
    let mut b_sum = vec![BigQ::zero(); max_b];
    for (i, c) in b0.iter().enumerate() { b_sum[i] = &b_sum[i] + c; }
    for (i, c) in b1.iter().enumerate() { b_sum[i] = &b_sum[i] + c; }

    let z1_raw = karatsuba_mul_bigq(&a_sum, &b_sum);

    let mut z1 = z1_raw;
    for (i, c) in z0.iter().enumerate() {
        if i < z1.len() { z1[i] = &z1[i] - c; }
    }
    for (i, c) in z2.iter().enumerate() {
        if i < z1.len() { z1[i] = &z1[i] - c; }
    }

    let out_len = n + m - 1;
    let mut out = vec![BigQ::zero(); out_len];
    for (i, c) in z0.iter().enumerate() {
        if i < out_len { out[i] = &out[i] + c; }
    }
    for (i, c) in z1.iter().enumerate() {
        if i + k < out_len { out[i + k] = &out[i + k] + c; }
    }
    for (i, c) in z2.iter().enumerate() {
        if i + 2 * k < out_len { out[i + 2 * k] = &out[i + 2 * k] + c; }
    }
    out
}

impl Mul for &Poly<BigQ> {
    type Output = Poly<BigQ>;
    fn mul(self, rhs: Self) -> Poly<BigQ> {
        let coeffs = karatsuba_mul_bigq(&self.coeffs, &rhs.coeffs);
        Poly::new(coeffs)
    }
}

impl Mul for Poly<BigQ> {
    type Output = Poly<BigQ>;
    fn mul(self, rhs: Self) -> Poly<BigQ> {
        &self * &rhs
    }
}

// === BigQ Operations: Division, GCD, Evaluation, Roots ===

impl Poly<BigQ> {
    /// Divides `self` by `divisor`, returning quotient and remainder `(Q, R)`
    /// such that `self == Q * divisor + R` and `deg(R) < deg(divisor)`.
    pub fn div_rem(&self, divisor: &Self) -> Result<(Self, Self)> {
        if divisor.is_zero() {
            return Err(Error::DivByZero);
        }
        if self.is_zero() {
            return Ok((Poly::zero(), Poly::zero()));
        }
        let deg_self = self.degree().unwrap();
        let deg_div = divisor.degree().unwrap();
        if deg_self < deg_div {
            return Ok((Poly::zero(), self.clone()));
        }

        let mut rem_coeffs = self.coeffs.clone();
        let mut quot_coeffs = vec![BigQ::zero(); deg_self - deg_div + 1];
        let div_lc = divisor.leading_coeff().unwrap();

        for i in (0..=deg_self - deg_div).rev() {
            let cur_deg = i + deg_div;
            let cur_coeff = rem_coeffs[cur_deg].clone();
            if !cur_coeff.is_zero() {
                let q_k = &cur_coeff / div_lc;
                quot_coeffs[i] = q_k.clone();
                for j in 0..=deg_div {
                    let sub = &q_k * &divisor.coeffs[j];
                    rem_coeffs[i + j] = &rem_coeffs[i + j] - &sub;
                }
            }
        }
        Ok((Poly::new(quot_coeffs), Poly::new(rem_coeffs)))
    }

    /// Normalizes the polynomial to monic form (leading coefficient 1).
    pub fn to_monic(&self) -> Self {
        if self.is_zero() {
            Poly::zero()
        } else {
            let lc = self.leading_coeff().unwrap();
            let inv_lc = lc.recip().unwrap();
            let new_coeffs: Vec<BigQ> = self.coeffs.iter().map(|c| c * &inv_lc).collect();
            Poly::new(new_coeffs)
        }
    }

    /// Computes the monic greatest common divisor of `self` and `other`.
    pub fn gcd(&self, other: &Self) -> Self {
        if self.is_zero() {
            return other.to_monic();
        }
        if other.is_zero() {
            return self.to_monic();
        }
        let mut a = self.clone();
        let mut b = other.clone();
        while !b.is_zero() {
            let (_, r) = a.div_rem(&b).unwrap();
            a = b;
            b = r;
        }
        a.to_monic()
    }

    /// Evaluates the polynomial at a point `at` using Horner's method.
    pub fn eval(&self, at: &BigQ) -> BigQ {
        if self.is_zero() {
            return BigQ::zero();
        }
        let mut res = BigQ::zero();
        for coeff in self.coeffs.iter().rev() {
            res = &(&res * at) + coeff;
        }
        res
    }

    /// Composes polynomials: computes $P(Q(x))$.
    pub fn compose(&self, inner: &Self) -> Self {
        if self.is_zero() {
            return Poly::zero();
        }
        let mut res = Poly::zero();
        for coeff in self.coeffs.iter().rev() {
            let term = Poly::from_coeffs(&[coeff.clone()]);
            res = &(&res * inner) + &term;
        }
        res
    }

    /// Formal derivative $P'(x)$.
    pub fn derivative(&self) -> Self {
        if self.coeffs.len() <= 1 {
            return Poly::zero();
        }
        let mut d_coeffs = Vec::with_capacity(self.coeffs.len() - 1);
        for (i, coeff) in self.coeffs.iter().enumerate().skip(1) {
            let factor = BigQ::from_integer(BigI::from(i as i64));
            d_coeffs.push(coeff * &factor);
        }
        Poly::new(d_coeffs)
    }

    /// Formal antiderivative $\int P(x) dx$ with constant term zero.
    pub fn integral(&self) -> Self {
        if self.is_zero() {
            return Poly::zero();
        }
        let mut int_coeffs = Vec::with_capacity(self.coeffs.len() + 1);
        int_coeffs.push(BigQ::zero());
        for (i, coeff) in self.coeffs.iter().enumerate() {
            let divisor = BigQ::from_integer(BigI::from((i + 1) as i64));
            int_coeffs.push(coeff / &divisor);
        }
        Poly::new(int_coeffs)
    }

    /// Decomposes a polynomial into square-free factors via Yun's algorithm.
    /// Returns a list of `(factor, multiplicity)`.
    pub fn square_free_factorization(&self) -> Vec<(Self, usize)> {
        if self.is_zero() || self.degree() == Some(0) {
            return Vec::new();
        }
        let p = self.to_monic();
        let p_prime = p.derivative();
        let c = p.gcd(&p_prime);
        let mut w = p.div_rem(&c).unwrap().0;
        let mut y = p_prime.div_rem(&c).unwrap().0;
        let mut factors = Vec::new();
        let mut i = 1;

        while !w.is_one() && !w.is_zero() {
            let y_minus_w_prime = &y - &w.derivative();
            let a_i = w.gcd(&y_minus_w_prime);
            if !a_i.is_one() && a_i.degree().unwrap_or(0) > 0 {
                factors.push((a_i.clone(), i));
            }
            w = w.div_rem(&a_i).unwrap().0;
            y = y_minus_w_prime.div_rem(&a_i).unwrap().0;
            i += 1;
        }
        factors
    }

    /// Generates the Sturm sequence for the polynomial:
    /// $P_0 = P, P_1 = P', P_{i+1} = -\text{rem}(P_{i-1}, P_i)$.
    pub fn sturm_sequence(&self) -> Vec<Self> {
        if self.is_zero() {
            return Vec::new();
        }
        let p0 = self.clone();
        let p1 = self.derivative();
        if p1.is_zero() {
            return vec![p0];
        }
        let mut seq = vec![p0, p1];
        loop {
            let k = seq.len();
            let (_, rem) = seq[k - 2].div_rem(&seq[k - 1]).unwrap();
            if rem.is_zero() {
                break;
            }
            let next = -&rem;
            let is_const = next.degree() == Some(0);
            seq.push(next);
            if is_const {
                break;
            }
        }
        seq
    }

    /// Counts sign variations of the Sturm sequence evaluated at `at`.
    pub fn count_sign_variations(seq: &[Self], at: &BigQ) -> usize {
        let mut prev_sign = 0;
        let mut variations = 0;
        for poly in seq {
            let val = poly.eval(at);
            if val.is_zero() {
                continue;
            }
            let sign = if !val.numer().is_negative() { 1 } else { -1 };
            if prev_sign != 0 && sign != prev_sign {
                variations += 1;
            }
            prev_sign = sign;
        }
        variations
    }

    /// Counts the exact number of distinct real roots in the half-open interval `(a, b]`.
    pub fn count_real_roots_between(&self, a: &BigQ, b: &BigQ) -> usize {
        if a >= b || self.is_zero() {
            return 0;
        }
        let seq = self.sturm_sequence();
        if seq.is_empty() {
            return 0;
        }
        let va = Self::count_sign_variations(&seq, a);
        let vb = Self::count_sign_variations(&seq, b);
        va.saturating_sub(vb)
    }

    /// Computes the Cauchy upper bound on the absolute value of all real roots.
    pub fn cauchy_root_bound(&self) -> BigQ {
        if self.is_zero() || self.degree() == Some(0) {
            return BigQ::one();
        }
        let deg = self.degree().unwrap();
        let lc = self.leading_coeff().unwrap();
        let lc_abs = lc.abs();
        let mut max_ratio = BigQ::zero();
        for i in 0..deg {
            let c_abs = self.coeffs[i].abs();
            let ratio = &c_abs / &lc_abs;
            if ratio > max_ratio {
                max_ratio = ratio;
            }
        }
        &BigQ::one() + &max_ratio
    }

    /// Isolates all real roots of the polynomial into disjoint half-open intervals `(l, r]`
    /// such that each interval contains exactly one real root and `r - l <= eps`.
    pub fn isolate_real_roots(&self, eps: &BigQ) -> Vec<(BigQ, BigQ)> {
        if self.is_zero() || self.degree() == Some(0) || eps.numer().is_negative() || eps.is_zero() {
            return Vec::new();
        }
        // Use square-free part for root isolation
        let p_prime = self.derivative();
        let gcd = self.gcd(&p_prime);
        let p_sf = if gcd.is_one() || gcd.is_zero() {
            self.clone()
        } else {
            self.div_rem(&gcd).unwrap().0
        };

        if p_sf.degree() == Some(1) {
            let c0 = &p_sf.coeffs[0];
            let c1 = &p_sf.coeffs[1];
            let root = -c0 / c1.clone();
            let two = BigQ::from_integer(BigI::from(2));
            let half_eps = eps / &two;
            return vec![(&root - &half_eps, &root + &half_eps)];
        }

        let bound = p_sf.cauchy_root_bound();
        let mut intervals = vec![(-bound.clone(), bound)];
        let mut isolated = Vec::new();

        while let Some((l, r)) = intervals.pop() {
            let count = p_sf.count_real_roots_between(&l, &r);
            if count == 0 {
                continue;
            }
            let width = &r - &l;
            if count == 1 && &width <= eps {
                isolated.push((l, r));
            } else {
                let two = BigQ::from_integer(BigI::from(2));
                let mid = &(&l + &r) / &two;
                intervals.push((mid.clone(), r));
                intervals.push((l, mid));
            }
        }

        isolated.sort_by(|a, b| a.0.cmp(&b.0));
        isolated
    }
}

// === BigI Operations: Pseudo-Division and Subresultant PRS GCD ===

impl Poly<BigI> {
    /// Computes the content (GCD of all coefficients) of the polynomial.
    pub fn content(&self) -> BigI {
        if self.is_zero() {
            return BigI::zero();
        }
        let mut g = self.coeffs[0].abs();
        for c in &self.coeffs[1..] {
            g = g.gcd(&c.abs());
            if g == BigI::one() {
                break;
            }
        }
        g
    }

    /// Divides out the content to produce the primitive part.
    pub fn primitive_part(&self) -> Self {
        if self.is_zero() {
            return Poly::zero();
        }
        let c = self.content();
        if c == BigI::one() || c.is_zero() {
            self.clone()
        } else {
            let coeffs: Vec<BigI> = self.coeffs.iter().map(|x| x / &c).collect();
            Poly::new(coeffs)
        }
    }

    /// Pseudo-division of `self` by `divisor`:
    /// Computes $Q, R$ such that $d^\delta \cdot \text{self} = Q \cdot \text{divisor} + R$,
    /// where $d = \text{lc}(\text{divisor})$, $\delta = \max(0, \deg(A) - \deg(B) + 1)$.
    pub fn pseudo_div_rem(&self, divisor: &Self) -> Result<(Self, Self, BigI, usize)> {
        if divisor.is_zero() {
            return Err(Error::DivByZero);
        }
        if self.is_zero() {
            return Ok((Poly::zero(), Poly::zero(), BigI::one(), 0));
        }
        let deg_a = self.degree().unwrap();
        let deg_b = divisor.degree().unwrap();
        if deg_a < deg_b {
            return Ok((Poly::zero(), self.clone(), BigI::one(), 0));
        }

        let delta = deg_a - deg_b + 1;
        let d = divisor.leading_coeff().unwrap().clone();
        let multiplier = d.pow(delta as u32);

        let mut rem_coeffs: Vec<BigI> = self.coeffs.iter().map(|c| c * &multiplier).collect();
        let mut quot_coeffs = vec![BigI::zero(); deg_a - deg_b + 1];

        for i in (0..=deg_a - deg_b).rev() {
            let cur_deg = i + deg_b;
            let cur_coeff = rem_coeffs[cur_deg].clone();
            if !cur_coeff.is_zero() {
                let q_k = &cur_coeff / &d;
                quot_coeffs[i] = q_k.clone();
                for j in 0..=deg_b {
                    let sub = &q_k * &divisor.coeffs[j];
                    rem_coeffs[i + j] = &rem_coeffs[i + j] - &sub;
                }
            }
        }
        Ok((Poly::new(quot_coeffs), Poly::new(rem_coeffs), multiplier, delta))
    }

    /// Computes the greatest common divisor using the Subresultant Polynomial
    /// Remainder Sequence algorithm to eliminate intermediate coefficient explosion.
    pub fn subresultant_gcd(&self, other: &Self) -> Self {
        if self.is_zero() {
            let mut res = other.primitive_part();
            if res.leading_coeff().map_or(false, |lc| lc.is_negative()) {
                res = -&res;
            }
            return res;
        }
        if other.is_zero() {
            let mut res = self.primitive_part();
            if res.leading_coeff().map_or(false, |lc| lc.is_negative()) {
                res = -&res;
            }
            return res;
        }

        let mut p1 = self.primitive_part();
        let mut p2 = other.primitive_part();

        if p1.degree().unwrap() < p2.degree().unwrap() {
            core::mem::swap(&mut p1, &mut p2);
        }

        let mut gamma = BigI::one();
        let mut beta = if (p1.degree().unwrap() - p2.degree().unwrap() + 1) % 2 == 1 {
            -BigI::one()
        } else {
            BigI::one()
        };

        loop {
            let d1 = p1.degree().unwrap();
            let d2 = p2.degree().unwrap();
            let delta = d1 - d2;

            let (_, rem, _, _) = p1.pseudo_div_rem(&p2).unwrap();
            if rem.is_zero() {
                let mut res = p2.primitive_part();
                if res.leading_coeff().map_or(false, |lc| lc.is_negative()) {
                    res = -&res;
                }
                return res;
            }
            if rem.degree() == Some(0) {
                return Poly::one();
            }

            let next_coeffs: Vec<BigI> = rem.coeffs.into_iter().map(|c| &c / &beta).collect();
            let p3 = Poly::new(next_coeffs);

            let lc2 = p2.leading_coeff().unwrap().clone();
            let lc2_pow = lc2.pow(delta as u32);
            let gamma_pow = if delta > 1 {
                gamma.pow((delta - 1) as u32)
            } else {
                BigI::one()
            };
            gamma = &lc2_pow / &gamma_pow;
            let next_delta = d2 - p3.degree().unwrap();
            let gamma_next_delta = gamma.pow(next_delta as u32);
            beta = -(&lc2 * &gamma_next_delta);

            p1 = p2;
            p2 = p3;
        }
    }

    /// Computes the resultant of two integer polynomials via the Sylvester matrix determinant.
    pub fn resultant(&self, other: &Self) -> BigI {
        if self.is_zero() || other.is_zero() {
            return BigI::zero();
        }
        let m = self.degree().unwrap();
        let n = other.degree().unwrap();
        if m == 0 && n == 0 {
            return BigI::one();
        }
        if m == 0 {
            return self.coeffs[0].pow(n as u32);
        }
        if n == 0 {
            return other.coeffs[0].pow(m as u32);
        }
        let dim = m + n;
        let mut mat = vec![vec![BigI::zero(); dim]; dim];
        for i in 0..n {
            for j in 0..=m {
                mat[i][i + j] = self.coeffs[m - j].clone();
            }
        }
        for i in 0..m {
            for j in 0..=n {
                mat[n + i][i + j] = other.coeffs[n - j].clone();
            }
        }
        bareiss_determinant(&mut mat)
    }

    /// Computes the discriminant of the polynomial:
    /// $\text{disc}(P) = (-1)^{n(n-1)/2} \frac{\text{res}(P, P')}{a_n}$.
    pub fn discriminant(&self) -> Option<BigI> {
        let n = self.degree()?;
        if n == 0 {
            return None;
        }
        if n == 1 {
            return Some(BigI::one());
        }
        let an = self.leading_coeff().unwrap();
        let mut d_coeffs = Vec::with_capacity(self.coeffs.len() - 1);
        for (i, coeff) in self.coeffs.iter().enumerate().skip(1) {
            d_coeffs.push(coeff * &BigI::from(i as i64));
        }
        let p_prime = Poly::new(d_coeffs);
        let res = self.resultant(&p_prime);
        let div = &res / an;
        let sign_exp = (n * (n - 1) / 2) % 2;
        if sign_exp == 1 {
            Some(-div)
        } else {
            Some(div)
        }
    }
}

fn bareiss_determinant(mat: &mut [Vec<BigI>]) -> BigI {
    let n = mat.len();
    if n == 0 {
        return BigI::one();
    }
    if n == 1 {
        return mat[0][0].clone();
    }
    let mut sign = 1i64;
    for k in 0..n - 1 {
        if mat[k][k].is_zero() {
            let mut swap_idx = None;
            for r in k + 1..n {
                if !mat[r][k].is_zero() {
                    swap_idx = Some(r);
                    break;
                }
            }
            match swap_idx {
                Some(r) => {
                    mat.swap(k, r);
                    sign = -sign;
                }
                None => return BigI::zero(),
            }
        }
        let prev_pivot = if k == 0 {
            BigI::one()
        } else {
            mat[k - 1][k - 1].clone()
        };
        let cur_pivot = mat[k][k].clone();
        for i in k + 1..n {
            let mik = mat[i][k].clone();
            for j in k + 1..n {
                let num = &(&mat[i][j] * &cur_pivot) - &(&mik * &mat[k][j]);
                mat[i][j] = &num / &prev_pivot;
            }
        }
    }
    let det = mat[n - 1][n - 1].clone();
    if sign < 0 {
        -det
    } else {
        det
    }
}

// === Parsing and Formatting ===

impl<T: PolyCoeff> fmt::Display for Poly<T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.is_zero() {
            return write!(f, "0");
        }
        let mut first = true;
        for (i, c) in self.coeffs.iter().enumerate().rev() {
            if c.is_zero() {
                continue;
            }
            let is_neg = c.is_negative();
            if first {
                if is_neg {
                    write!(f, "-")?;
                }
                first = false;
            } else if is_neg {
                write!(f, " - ")?;
            } else {
                write!(f, " + ")?;
            }

            let abs_c_str = format!("{c}");
            let abs_c = abs_c_str.trim_start_matches('-');

            if i == 0 {
                write!(f, "{abs_c}")?;
            } else if i == 1 {
                if c.is_one() || abs_c == "1" {
                    write!(f, "x")?;
                } else {
                    write!(f, "{abs_c}x")?;
                }
            } else if c.is_one() || abs_c == "1" {
                write!(f, "x^{i}")?;
            } else {
                write!(f, "{abs_c}x^{i}")?;
            }
        }
        Ok(())
    }
}

impl<T: PolyCoeff + FromStr<Err = Error>> FromStr for Poly<T> {
    type Err = Error;

    fn from_str(s: &str) -> Result<Self> {
        let s = s.trim();
        if s.is_empty() {
            return Err(Error::EmptyString);
        }
        if s == "0" {
            return Ok(Poly::zero());
        }

        let mut terms_map: std::collections::BTreeMap<usize, T> = std::collections::BTreeMap::new();
        let cleaned = s.replace(" ", "");

        let mut pos = 0;
        let bytes = cleaned.as_bytes();
        let len = bytes.len();

        while pos < len {
            let mut is_neg = false;
            if bytes[pos] == b'+' {
                pos += 1;
            } else if bytes[pos] == b'-' {
                is_neg = true;
                pos += 1;
            }

            if pos >= len {
                return Err(Error::EmptyString);
            }

            let start = pos;
            while pos < len && bytes[pos] != b'+' && bytes[pos] != b'-' {
                pos += 1;
            }
            let term_str = &cleaned[start..pos];
            if term_str.is_empty() {
                return Err(Error::EmptyString);
            }

            if let Some(x_pos) = term_str.find('x') {
                let coeff_part = &term_str[..x_pos];
                let exp_part = &term_str[x_pos + 1..];

                let exp: usize = if exp_part.is_empty() {
                    1
                } else if exp_part.starts_with('^') {
                    exp_part[1..].parse().map_err(|_| Error::InvalidDigit {
                        ch: exp_part.chars().nth(1).unwrap_or('^'),
                        radix: 10,
                    })?
                } else {
                    return Err(Error::InvalidDigit {
                        ch: exp_part.chars().next().unwrap_or('x'),
                        radix: 10,
                    });
                };

                let coeff_val: T = if coeff_part.is_empty() {
                    if is_neg {
                        T::from_str("-1")?
                    } else {
                        T::one()
                    }
                } else {
                    let parsed = if is_neg {
                        T::from_str(&format!("-{coeff_part}"))?
                    } else {
                        T::from_str(coeff_part)?
                    };
                    parsed
                };

                terms_map
                    .entry(exp)
                    .and_modify(|e| *e = e.add_coeff(&coeff_val))
                    .or_insert(coeff_val);
            } else {
                let coeff_val: T = if is_neg {
                    T::from_str(&format!("-{term_str}"))?
                } else {
                    T::from_str(term_str)?
                };
                terms_map
                    .entry(0)
                    .and_modify(|e| *e = e.add_coeff(&coeff_val))
                    .or_insert(coeff_val);
            }
        }

        let max_deg = terms_map.keys().last().copied().unwrap_or(0);
        let mut coeffs = vec![T::zero(); max_deg + 1];
        for (deg, c) in terms_map {
            coeffs[deg] = c;
        }
        Ok(Poly::new(coeffs))
    }
}

// === Exact Real Algebraic Numbers ===

/// An exact real algebraic number defined by a square-free integer polynomial
/// $P(x)$ and an isolating rational interval $(a, b]$ containing a single real root.
#[derive(Clone, Debug)]
pub struct AlgebraicNumber {
    poly: Poly<BigI>,
    interval: (BigQ, BigQ),
}

impl AlgebraicNumber {
    /// Creates an algebraic number representing an exact rational number $q$.
    pub fn from_rational(q: BigQ) -> Self {
        let (n, d) = (q.numer().clone(), q.denom().clone());
        let d_bigi = BigI::from_parts(false, d);
        let poly = Poly::new(vec![-n, d_bigi]);
        let interval = (q.clone(), q);
        Self { poly, interval }
    }

    /// Creates an algebraic number representing $\sqrt{q}$ for $q \ge 0$.
    pub fn sqrt(q: BigQ) -> Option<Self> {
        if q.numer().is_negative() {
            return None;
        }
        if q.is_zero() {
            return Some(Self::from_rational(BigQ::zero()));
        }
        let (n, d) = (q.numer().clone(), q.denom().clone());
        let d_bigi = BigI::from_parts(false, d);
        let poly = Poly::new(vec![-n, BigI::zero(), d_bigi]);
        let upper = if &q < &BigQ::one() {
            BigQ::one()
        } else {
            &q + &BigQ::one()
        };
        let mut alg = Self {
            poly,
            interval: (BigQ::zero(), upper),
        };
        let quarter = BigQ::new(BigI::one(), BigI::from(4)).unwrap();
        alg.refine(&quarter);
        Some(alg)
    }

    /// Creates an algebraic number representing the $k$-th real root of $P(x)$ (0-indexed).
    pub fn root_of(poly: Poly<BigI>, k: usize) -> Option<Self> {
        if poly.is_zero() || poly.degree() == Some(0) {
            return None;
        }
        let q_coeffs: Vec<BigQ> = poly.coeffs().iter().map(|c| BigQ::from(c.clone())).collect();
        let q_poly = Poly::new(q_coeffs);
        let roots = q_poly.isolate_real_roots(&BigQ::one());
        if k >= roots.len() {
            return None;
        }
        let interval = roots[k].clone();
        let primitive = poly.primitive_part();
        let mut alg = Self {
            poly: primitive,
            interval,
        };
        let quarter = BigQ::new(BigI::one(), BigI::from(4)).unwrap();
        alg.refine(&quarter);
        Some(alg)
    }

    /// Accessor for the defining integer polynomial.
    pub fn poly(&self) -> &Poly<BigI> {
        &self.poly
    }

    /// Accessor for the isolating interval $(a, b]$.
    pub fn interval(&self) -> (BigQ, BigQ) {
        self.interval.clone()
    }

    /// Refines the isolating interval until its width is at most `eps`.
    pub fn refine(&mut self, eps: &BigQ) {
        if eps.numer().is_negative() || eps.is_zero() {
            return;
        }
        let (mut a, mut b) = self.interval.clone();
        if a == b {
            return;
        }
        let q_coeffs: Vec<BigQ> = self.poly.coeffs().iter().map(|c| BigQ::from(c.clone())).collect();
        let q_poly = Poly::new(q_coeffs);

        let two = BigQ::from_integer(BigI::from(2));
        while &(&b - &a) > eps {
            let m = &(&a + &b) / &two;
            let val_m = q_poly.eval(&m);
            if val_m.is_zero() {
                a = m.clone();
                b = m;
                break;
            }
            let val_a = q_poly.eval(&a);
            let sign_a = if !val_a.numer().is_negative() { 1 } else { -1 };
            let sign_m = if !val_m.numer().is_negative() { 1 } else { -1 };
            if sign_a != sign_m {
                b = m;
            } else {
                a = m;
            }
        }
        self.interval = (a, b);
    }

    /// Computes a rational approximation within `eps` of the exact value.
    pub fn approx(&self, eps: &BigQ) -> BigQ {
        let mut copy = self.clone();
        copy.refine(eps);
        let two = BigQ::from_integer(BigI::from(2));
        &(&copy.interval.0 + &copy.interval.1) / &two
    }
}

impl PartialEq for AlgebraicNumber {
    fn eq(&self, other: &Self) -> bool {
        self.cmp(other) == core::cmp::Ordering::Equal
    }
}

impl Eq for AlgebraicNumber {}

impl PartialOrd for AlgebraicNumber {
    fn partial_cmp(&self, other: &Self) -> Option<core::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for AlgebraicNumber {
    fn cmp(&self, other: &Self) -> core::cmp::Ordering {
        let mut a = self.clone();
        let mut b = other.clone();

        if a.interval.1 < b.interval.0 {
            return core::cmp::Ordering::Less;
        }
        if b.interval.1 < a.interval.0 {
            return core::cmp::Ordering::Greater;
        }

        let two = BigQ::from_integer(BigI::from(2));
        for _ in 0..100 {
            let gcd = a.poly.subresultant_gcd(&b.poly);
            if gcd.degree().unwrap_or(0) > 0 {
                let q_coeffs: Vec<BigQ> = gcd.coeffs().iter().map(|c| BigQ::from(c.clone())).collect();
                let q_gcd = Poly::new(q_coeffs);
                let overlap_l = if a.interval.0 > b.interval.0 { &a.interval.0 } else { &b.interval.0 };
                let overlap_r = if a.interval.1 < b.interval.1 { &a.interval.1 } else { &b.interval.1 };
                if overlap_l <= overlap_r {
                    if q_gcd.eval(overlap_l).is_zero() || q_gcd.eval(overlap_r).is_zero() {
                        return core::cmp::Ordering::Equal;
                    }
                    if overlap_l < overlap_r && q_gcd.count_real_roots_between(overlap_l, overlap_r) > 0 {
                        return core::cmp::Ordering::Equal;
                    }
                }
            }

            if a.interval.1 < b.interval.0 {
                return core::cmp::Ordering::Less;
            }
            if b.interval.1 < a.interval.0 {
                return core::cmp::Ordering::Greater;
            }

            let w_a = &(&a.interval.1 - &a.interval.0) / &two;
            let w_b = &(&b.interval.1 - &b.interval.0) / &two;
            if w_a > BigQ::zero() {
                a.refine(&w_a);
            }
            if w_b > BigQ::zero() {
                b.refine(&w_b);
            }
        }

        a.interval.0.cmp(&b.interval.0)
    }
}

#[derive(Copy, Clone)]
enum AlgOp {
    Add,
    Sub,
    Mul,
}

fn combine_algebraic(a: &AlgebraicNumber, b: &AlgebraicNumber, op: AlgOp) -> AlgebraicNumber {
    if a.interval.0 == a.interval.1 && b.interval.0 == b.interval.1 {
        let q = match op {
            AlgOp::Add => &a.interval.0 + &b.interval.0,
            AlgOp::Sub => &a.interval.0 - &b.interval.0,
            AlgOp::Mul => &a.interval.0 * &b.interval.0,
        };
        return AlgebraicNumber::from_rational(q);
    }

    let res_poly = compute_bivariate_resultant(&a.poly, &b.poly, match op {
        AlgOp::Add => BivOp::Add,
        AlgOp::Sub => BivOp::Sub,
        AlgOp::Mul => BivOp::Mul,
    });

    let q_coeffs: Vec<BigQ> = res_poly.coeffs().iter().map(|c| BigQ::from(c.clone())).collect();
    let q_poly = Poly::new(q_coeffs);
    let sq_factors = q_poly.square_free_factorization();
    let mut sf_q = Poly::one();
    for (f, _) in sq_factors {
        sf_q = &sf_q * &f;
    }
    let sf_int = Poly::new(sf_q.coeffs().iter().map(|c| c.numer().clone()).collect()).primitive_part();

    let mut a_cur = a.clone();
    let mut b_cur = b.clone();
    let mut target_interval = match op {
        AlgOp::Add => (&a_cur.interval.0 + &b_cur.interval.0, &a_cur.interval.1 + &b_cur.interval.1),
        AlgOp::Sub => (&a_cur.interval.0 - &b_cur.interval.1, &a_cur.interval.1 - &b_cur.interval.0),
        AlgOp::Mul => {
            let pts = [
                &a_cur.interval.0 * &b_cur.interval.0,
                &a_cur.interval.0 * &b_cur.interval.1,
                &a_cur.interval.1 * &b_cur.interval.0,
                &a_cur.interval.1 * &b_cur.interval.1,
            ];
            let mut min_pt = pts[0].clone();
            let mut max_pt = pts[0].clone();
            for pt in &pts[1..] {
                if pt < &min_pt { min_pt = pt.clone(); }
                if pt > &max_pt { max_pt = pt.clone(); }
            }
            (min_pt, max_pt)
        }
    };

    let sf_q_eval: Vec<BigQ> = sf_int.coeffs().iter().map(|c| BigQ::from(c.clone())).collect();
    let sf_poly_q = Poly::new(sf_q_eval);

    let two = BigQ::from_integer(BigI::from(2));
    for _ in 0..50 {
        let roots = sf_poly_q.count_real_roots_between(&target_interval.0, &target_interval.1);
        if roots == 1 {
            break;
        }
        let w_a = &(&a_cur.interval.1 - &a_cur.interval.0) / &two;
        let w_b = &(&b_cur.interval.1 - &b_cur.interval.0) / &two;
        if w_a > BigQ::zero() { a_cur.refine(&w_a); }
        if w_b > BigQ::zero() { b_cur.refine(&w_b); }
        target_interval = match op {
            AlgOp::Add => (&a_cur.interval.0 + &b_cur.interval.0, &a_cur.interval.1 + &b_cur.interval.1),
            AlgOp::Sub => (&a_cur.interval.0 - &b_cur.interval.1, &a_cur.interval.1 - &b_cur.interval.0),
            AlgOp::Mul => {
                let pts = [
                    &a_cur.interval.0 * &b_cur.interval.0,
                    &a_cur.interval.0 * &b_cur.interval.1,
                    &a_cur.interval.1 * &b_cur.interval.0,
                    &a_cur.interval.1 * &b_cur.interval.1,
                ];
                let mut min_pt = pts[0].clone();
                let mut max_pt = pts[0].clone();
                for pt in &pts[1..] {
                    if pt < &min_pt { min_pt = pt.clone(); }
                    if pt > &max_pt { max_pt = pt.clone(); }
                }
                (min_pt, max_pt)
            }
        };
    }

    let mut result = AlgebraicNumber {
        poly: sf_int,
        interval: target_interval,
    };
    let quarter = BigQ::new(BigI::one(), BigI::from(4)).unwrap();
    result.refine(&quarter);
    result
}

#[derive(Copy, Clone)]
enum BivOp {
    Add,
    Sub,
    Mul,
}

fn compute_bivariate_resultant(a: &Poly<BigI>, b: &Poly<BigI>, op: BivOp) -> Poly<BigI> {
    let deg_a = a.degree().unwrap_or(0);
    let deg_b = b.degree().unwrap_or(0);
    if deg_a == 0 || deg_b == 0 {
        return Poly::one();
    }

    let mut p_y: Vec<Poly<BigI>> = vec![Poly::zero(); deg_a + 1];
    match op {
        BivOp::Add => {
            for (k, ak) in a.coeffs().iter().enumerate() {
                for j in 0..=k {
                    let binom = binomial(k, j);
                    let sign = if j % 2 == 1 { -BigI::one() } else { BigI::one() };
                    let coeff = ak * &binom * &sign;
                    let poly_term = Poly::from_monomial(k - j, coeff);
                    p_y[j] = &p_y[j] + &poly_term;
                }
            }
        }
        BivOp::Sub => {
            for (k, ak) in a.coeffs().iter().enumerate() {
                for j in 0..=k {
                    let binom = binomial(k, j);
                    let coeff = ak * &binom;
                    let poly_term = Poly::from_monomial(k - j, coeff);
                    p_y[j] = &p_y[j] + &poly_term;
                }
            }
        }
        BivOp::Mul => {
            for j in 0..=deg_a {
                let k = deg_a - j;
                let ak = a.coeff(k).cloned().unwrap_or_else(BigI::zero);
                p_y[j] = Poly::from_monomial(k, ak);
            }
        }
    }

    let mut q_y: Vec<Poly<BigI>> = vec![Poly::zero(); deg_b + 1];
    for (j, bj) in b.coeffs().iter().enumerate() {
        q_y[j] = Poly::from_monomial(0, bj.clone());
    }

    let m = deg_a;
    let n = deg_b;
    let dim = m + n;
    let mut mat: Vec<Vec<Poly<BigI>>> = vec![vec![Poly::zero(); dim]; dim];

    for i in 0..n {
        for j in 0..=m {
            mat[i][i + j] = p_y[m - j].clone();
        }
    }
    for i in 0..m {
        for j in 0..=n {
            mat[n + i][i + j] = q_y[n - j].clone();
        }
    }

    poly_matrix_det(&mat)
}

fn binomial(n: usize, k: usize) -> BigI {
    if k > n {
        return BigI::zero();
    }
    if k == 0 || k == n {
        return BigI::one();
    }
    let mut res = BigI::one();
    for i in 1..=k {
        res = &res * &BigI::from((n - k + i) as i64);
        res = &res / &BigI::from(i as i64);
    }
    res
}

fn poly_matrix_det(mat: &[Vec<Poly<BigI>>]) -> Poly<BigI> {
    let n = mat.len();
    if n == 0 {
        return Poly::one();
    }
    if n == 1 {
        return mat[0][0].clone();
    }
    if n == 2 {
        return &(&mat[0][0] * &mat[1][1]) - &(&mat[0][1] * &mat[1][0]);
    }
    let mut res = Poly::zero();
    for j in 0..n {
        if mat[0][j].is_zero() {
            continue;
        }
        let mut sub = Vec::with_capacity(n - 1);
        for row in &mat[1..] {
            let mut sub_row = Vec::with_capacity(n - 1);
            for (col_idx, val) in row.iter().enumerate() {
                if col_idx != j {
                    sub_row.push(val.clone());
                }
            }
            sub.push(sub_row);
        }
        let sub_det = poly_matrix_det(&sub);
        let term = &mat[0][j] * &sub_det;
        if j % 2 == 1 {
            res = &res - &term;
        } else {
            res = &res + &term;
        }
    }
    res
}

impl Add for &AlgebraicNumber {
    type Output = AlgebraicNumber;
    fn add(self, other: Self) -> AlgebraicNumber {
        combine_algebraic(self, other, AlgOp::Add)
    }
}

impl Add for AlgebraicNumber {
    type Output = AlgebraicNumber;
    fn add(self, other: Self) -> AlgebraicNumber {
        &self + &other
    }
}

impl Sub for &AlgebraicNumber {
    type Output = AlgebraicNumber;
    fn sub(self, other: Self) -> AlgebraicNumber {
        combine_algebraic(self, other, AlgOp::Sub)
    }
}

impl Sub for AlgebraicNumber {
    type Output = AlgebraicNumber;
    fn sub(self, other: Self) -> AlgebraicNumber {
        &self - &other
    }
}

impl Neg for &AlgebraicNumber {
    type Output = AlgebraicNumber;
    fn neg(self) -> AlgebraicNumber {
        let neg_coeffs: Vec<BigI> = self.poly.coeffs().iter().enumerate().map(|(i, c)| {
            if i % 2 == 1 { -c.clone() } else { c.clone() }
        }).collect();
        let poly = Poly::new(neg_coeffs);
        let interval = (-self.interval.1.clone(), -self.interval.0.clone());
        AlgebraicNumber { poly, interval }
    }
}

impl Neg for AlgebraicNumber {
    type Output = AlgebraicNumber;
    fn neg(self) -> AlgebraicNumber {
        -&self
    }
}

impl Mul for &AlgebraicNumber {
    type Output = AlgebraicNumber;
    fn mul(self, other: Self) -> AlgebraicNumber {
        combine_algebraic(self, other, AlgOp::Mul)
    }
}

impl Mul for AlgebraicNumber {
    type Output = AlgebraicNumber;
    fn mul(self, other: Self) -> AlgebraicNumber {
        &self * &other
    }
}

impl core::ops::Div for &AlgebraicNumber {
    type Output = AlgebraicNumber;
    fn div(self, other: Self) -> AlgebraicNumber {
        if other.cmp(&AlgebraicNumber::from_rational(BigQ::zero())) == core::cmp::Ordering::Equal {
            panic!("division by zero");
        }
        let inv_coeffs: Vec<BigI> = other.poly.coeffs().iter().rev().cloned().collect();
        let inv_poly = Poly::new(inv_coeffs);
        let inv_int = if other.interval.0.is_zero() || other.interval.1.is_zero() {
            (BigQ::one() / other.interval.1.clone(), BigQ::one() / other.interval.0.clone())
        } else {
            let inv_a = BigQ::one() / other.interval.0.clone();
            let inv_b = BigQ::one() / other.interval.1.clone();
            if inv_a < inv_b { (inv_a, inv_b) } else { (inv_b, inv_a) }
        };
        let inv_other = AlgebraicNumber { poly: inv_poly, interval: inv_int };
        self * &inv_other
    }
}

impl core::ops::Div for AlgebraicNumber {
    type Output = AlgebraicNumber;
    fn div(self, other: Self) -> AlgebraicNumber {
        &self / &other
    }
}
