//! Fast modular arithmetic: a reduction engine, a ring type, and a CRT basis.
//!
//! [`BigU::modpow`] and [`BigU::modinv`] already reduce with Knuth division,
//! which is correct but pays for a full multi-limb division on every step. When
//! the *same* modulus is used over and over — the situation in every modular
//! exponentiation, every RSA-shaped protocol, every multi-modular convolution —
//! it is worth paying once to precompute a reducer and then never dividing
//! again.
//!
//! Three pieces sit on top of each other:
//!
//! * [`Reduction`] picks the strategy. Montgomery (Montgomery 1985) replaces
//!   division with a shift, but only works for an **odd** modulus. Barrett
//!   (Barrett 1986, Handbook of Applied Cryptography Alg. 14.42) replaces it
//!   with two multiplications by a precomputed reciprocal and accepts **any**
//!   modulus. [`ModRing::new`] auto-selects: Montgomery when it can, Barrett
//!   otherwise.
//! * [`ModRing`] owns the modulus and the precomputed reducer. Its elements are
//!   [`ModInt`] values which carry a borrow of the ring, so an element can never
//!   silently escape into a different modulus: mixing them is
//!   [`Error::ModulusMismatch`], not a wrong answer.
//! * [`CrtBasis`] layers Garner's algorithm over a set of pairwise-coprime
//!   moduli, so a wide value can be split into small residues, worked on
//!   independently, and reconstructed exactly.
//!
//! The Montgomery representation is an internal detail. `ModInt::value` always
//! hands back the ordinary residue in `[0, n)`, so which reducer is in play
//! changes the cost of an operation and nothing else about its result.

use core::cmp::Ordering;
use core::fmt;
use core::ops::{Add, Mul, Neg, Sub};

use crate::bigu::BigU;
use crate::error::{Error, Result};
use crate::mul::mul_limbs;
use crate::{Limb, LIMB_BITS};

/// Which reduction strategy a [`ModRing`] uses internally.
///
/// This is observable through [`ModRing::reduction`] and selectable through
/// [`ModRing::with_reduction`], but it never changes the value of a result —
/// only how quickly it is reached.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Reduction {
    /// Montgomery multiplication. Requires an odd modulus.
    Montgomery,
    /// Barrett reduction. Works for every modulus.
    Barrett,
}

impl fmt::Display for Reduction {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Reduction::Montgomery => f.write_str("Montgomery"),
            Reduction::Barrett => f.write_str("Barrett"),
        }
    }
}

/// Precomputed Montgomery parameters for an odd modulus `n`.
///
/// `R` is `2^(LIMB_BITS * k)` where `k` is the limb count of `n`, so `R > n` and
/// `gcd(R, n) == 1` exactly because `n` is odd. Montgomery 1985.
#[derive(Debug, Clone)]
struct MontgomeryCtx {
    /// Limbs of the modulus, padded to exactly `k`.
    n: Vec<Limb>,
    /// Limb count of the modulus; `R == 2^(LIMB_BITS * k)`.
    k: usize,
    /// `-n^-1 mod 2^LIMB_BITS`, the per-limb reduction multiplier.
    n_prime: Limb,
    /// `R^2 mod n`, used to enter the Montgomery domain with one multiply.
    r2: BigU,
    /// `R mod n`, the Montgomery form of one.
    r_mod_n: BigU,
}

impl MontgomeryCtx {
    /// Precomputes the parameters. `modulus` must be odd and nonzero.
    fn new(modulus: &BigU) -> MontgomeryCtx {
        debug_assert!(!modulus.is_zero() && modulus.limbs[0] & 1 == 1);
        let k = modulus.limbs.len();
        let n = modulus.limbs.clone();

        // Newton iteration on the low limb: each step doubles the number of
        // correct bits, so 1 -> 2 -> 4 -> 8 -> 16 -> 32 needs five rounds for a
        // 32-bit limb. The seed is correct modulo 2 because `n` is odd.
        let n0 = n[0];
        let mut inv: Limb = 1;
        let rounds = LIMB_BITS.trailing_zeros();
        for _ in 0..rounds {
            inv = inv.wrapping_mul(2u32.wrapping_sub(n0.wrapping_mul(inv)));
        }
        debug_assert_eq!(n0.wrapping_mul(inv), 1);
        let n_prime = inv.wrapping_neg();

        let shift = LIMB_BITS * k as u32;
        let r = &BigU::one() << shift;
        let r_mod_n = &r % modulus;
        let r2 = &(&r << shift) % modulus;

        MontgomeryCtx {
            n,
            k,
            n_prime,
            r2,
            r_mod_n,
        }
    }

    /// The Montgomery reduction `REDC`: given `t < R * n`, returns
    /// `t * R^-1 mod n` in `[0, n)`.
    fn redc(&self, t: &[Limb]) -> BigU {
        let mut t = t.to_vec();
        // `t + m*n*b^i` accumulates into at most `2k + 1` limbs.
        t.resize(2 * self.k + 1, 0);

        for i in 0..self.k {
            // Choose `m` so the i-th limb of `t + m*n*b^i` becomes zero.
            let m = t[i].wrapping_mul(self.n_prime);
            let mut carry: u64 = 0;
            for j in 0..self.k {
                let s = t[i + j] as u64 + m as u64 * self.n[j] as u64 + carry;
                t[i + j] = s as Limb;
                carry = s >> LIMB_BITS;
            }
            debug_assert_eq!(t[i], 0);
            let mut idx = i + self.k;
            while carry != 0 {
                let s = t[idx] as u64 + carry;
                t[idx] = s as Limb;
                carry = s >> LIMB_BITS;
                idx += 1;
            }
        }

        // The low `k` limbs are now zero, so the shift by `R` is a slice.
        let u = BigU::from_limbs(t[self.k..].to_vec());
        let n = BigU::from_limbs(self.n.clone());
        // A single conditional subtraction suffices: `u < 2n` on entry.
        if u >= n {
            &u - &n
        } else {
            u
        }
    }

    /// Montgomery product: `(a * b) * R^-1 mod n` for `a, b < n`.
    fn mul(&self, a: &BigU, b: &BigU) -> BigU {
        if a.is_zero() || b.is_zero() {
            return BigU::zero();
        }
        self.redc(&mul_limbs(&a.limbs, &b.limbs))
    }
}

/// Precomputed Barrett parameters for an arbitrary modulus `n`.
///
/// `mu == floor(b^(2k) / n)` with `b == 2^LIMB_BITS` and `k` the limb count of
/// `n`. Handbook of Applied Cryptography, Algorithm 14.42.
#[derive(Debug, Clone)]
struct BarrettCtx {
    /// The modulus.
    n: BigU,
    /// Limb count of the modulus.
    k: usize,
    /// `floor(b^(2k) / n)`.
    mu: BigU,
}

impl BarrettCtx {
    /// Precomputes the reciprocal. `modulus` must be nonzero.
    fn new(modulus: &BigU) -> BarrettCtx {
        debug_assert!(!modulus.is_zero());
        let k = modulus.limbs.len();
        let b2k = &BigU::one() << (LIMB_BITS * 2 * k as u32);
        let mu = &b2k / modulus;
        BarrettCtx {
            n: modulus.clone(),
            k,
            mu,
        }
    }

    /// Reduces `x < b^(2k)` to `[0, n)` using two multiplications and no
    /// division. Inputs outside that bound fall back to a real division, which
    /// keeps the routine total rather than silently wrong.
    fn reduce(&self, x: &BigU) -> BigU {
        if x.limbs.len() > 2 * self.k {
            return x % &self.n;
        }
        if x < &self.n {
            return x.clone();
        }

        // q3 = floor(floor(x / b^(k-1)) * mu / b^(k+1)) is within one of the
        // true quotient, so at most two corrective subtractions are needed.
        let q1 = limb_shr(x, self.k - 1);
        let q2 = &q1 * &self.mu;
        let q3 = limb_shr(&q2, self.k + 1);

        let r1 = limb_trunc(x, self.k + 1);
        let r2 = limb_trunc(&(&q3 * &self.n), self.k + 1);

        let mut r = if r1 >= r2 {
            &r1 - &r2
        } else {
            // Borrow from b^(k+1); the difference is congruent either way.
            let base = &BigU::one() << (LIMB_BITS * (self.k as u32 + 1));
            &(&r1 + &base) - &r2
        };
        // The estimate is never low by more than two multiples of `n`.
        let mut guard = 0;
        while r >= self.n {
            r = &r - &self.n;
            guard += 1;
            debug_assert!(guard <= 2, "Barrett quotient estimate off by more than 2");
        }
        r
    }
}

/// Drops the low `limbs` limbs, i.e. divides by `b^limbs`.
fn limb_shr(x: &BigU, limbs: usize) -> BigU {
    if limbs >= x.limbs.len() {
        return BigU::zero();
    }
    BigU::from_limbs(x.limbs[limbs..].to_vec())
}

/// Keeps only the low `limbs` limbs, i.e. reduces modulo `b^limbs`.
fn limb_trunc(x: &BigU, limbs: usize) -> BigU {
    let take = limbs.min(x.limbs.len());
    BigU::from_limbs(x.limbs[..take].to_vec())
}

/// The reduction engine actually installed in a ring.
#[derive(Debug, Clone)]
enum Engine {
    Montgomery(MontgomeryCtx),
    Barrett(BarrettCtx),
}

/// A residue ring `Z/nZ` carrying a precomputed reduction engine.
///
/// Construct once, then mint elements with [`ModRing::elem`]. Elements borrow
/// the ring, and every binary operation checks that both sides came from a ring
/// with the same modulus *and* the same reduction strategy — the two use
/// different internal representations, so silently mixing them would produce a
/// wrong answer rather than a detectable one.
///
/// ```
/// use bigu::{BigU, ModRing};
///
/// let ring = ModRing::new(&BigU::from(497u32)).unwrap();
/// let base = ring.elem(&BigU::from(4u32));
/// assert_eq!(base.pow(&BigU::from(13u32)).value(), BigU::from(445u32));
/// ```
#[derive(Debug, Clone)]
pub struct ModRing {
    modulus: BigU,
    engine: Engine,
}

impl ModRing {
    /// Builds a ring for `modulus`, choosing Montgomery when the modulus is odd
    /// and Barrett otherwise.
    ///
    /// Returns [`Error::DivByZero`] for a zero modulus, matching the rest of the
    /// modular family. A modulus of `1` is accepted and gives the trivial ring
    /// in which every element is zero.
    pub fn new(modulus: &BigU) -> Result<ModRing> {
        if modulus.is_zero() {
            return Err(Error::DivByZero);
        }
        let reduction = if modulus.limbs[0] & 1 == 1 {
            Reduction::Montgomery
        } else {
            Reduction::Barrett
        };
        ModRing::with_reduction(modulus, reduction)
    }

    /// Builds a ring with an explicitly chosen reduction strategy.
    ///
    /// Returns [`Error::DivByZero`] for a zero modulus and
    /// [`Error::EvenModulus`] when [`Reduction::Montgomery`] is requested for an
    /// even modulus, which the algorithm cannot represent: Montgomery needs
    /// `gcd(2^k, n) == 1`.
    pub fn with_reduction(modulus: &BigU, reduction: Reduction) -> Result<ModRing> {
        if modulus.is_zero() {
            return Err(Error::DivByZero);
        }
        let engine = match reduction {
            Reduction::Montgomery => {
                if modulus.limbs[0] & 1 == 0 {
                    return Err(Error::EvenModulus);
                }
                Engine::Montgomery(MontgomeryCtx::new(modulus))
            }
            Reduction::Barrett => Engine::Barrett(BarrettCtx::new(modulus)),
        };
        Ok(ModRing {
            modulus: modulus.clone(),
            engine,
        })
    }

    /// The modulus this ring reduces by.
    pub fn modulus(&self) -> &BigU {
        &self.modulus
    }

    /// Which strategy the ring installed.
    pub fn reduction(&self) -> Reduction {
        match self.engine {
            Engine::Montgomery(_) => Reduction::Montgomery,
            Engine::Barrett(_) => Reduction::Barrett,
        }
    }

    /// True when the two rings agree on both modulus and strategy, and so their
    /// elements share a representation.
    pub fn is_compatible(&self, other: &ModRing) -> bool {
        core::ptr::eq(self, other)
            || (self.modulus == other.modulus && self.reduction() == other.reduction())
    }

    /// Reduces `value` into the ring, converting to the internal representation.
    ///
    /// `value` may be arbitrarily larger than the modulus; the initial reduction
    /// goes through ordinary division exactly once.
    pub fn elem(&self, value: &BigU) -> ModInt<'_> {
        let reduced = value % &self.modulus;
        let inner = match &self.engine {
            // Entering the Montgomery domain is one multiply by `R^2 mod n`.
            Engine::Montgomery(ctx) => ctx.mul(&reduced, &ctx.r2),
            Engine::Barrett(_) => reduced,
        };
        ModInt { ring: self, inner }
    }

    /// The additive identity of the ring.
    pub fn zero(&self) -> ModInt<'_> {
        ModInt {
            ring: self,
            inner: BigU::zero(),
        }
    }

    /// The multiplicative identity of the ring. In the trivial ring `Z/1Z` this
    /// is zero, because zero is the only element.
    pub fn one(&self) -> ModInt<'_> {
        let inner = match &self.engine {
            Engine::Montgomery(ctx) => ctx.r_mod_n.clone(),
            Engine::Barrett(_) => &BigU::one() % &self.modulus,
        };
        ModInt { ring: self, inner }
    }

    /// Computes `base^exp mod n` through the ring's engine.
    ///
    /// A convenience wrapper for callers that want the speed of a precomputed
    /// reducer without holding on to [`ModInt`] values.
    pub fn pow(&self, base: &BigU, exp: &BigU) -> BigU {
        self.elem(base).pow(exp).value()
    }

    /// Internal product of two values already in the ring's representation.
    fn mul_inner(&self, a: &BigU, b: &BigU) -> BigU {
        match &self.engine {
            Engine::Montgomery(ctx) => ctx.mul(a, b),
            Engine::Barrett(ctx) => ctx.reduce(&(a * b)),
        }
    }

    /// Converts an internal representation back to an ordinary residue.
    fn out(&self, inner: &BigU) -> BigU {
        match &self.engine {
            // Leaving the Montgomery domain is REDC against one.
            Engine::Montgomery(ctx) => {
                if inner.is_zero() {
                    BigU::zero()
                } else {
                    ctx.redc(&inner.limbs)
                }
            }
            Engine::Barrett(_) => inner.clone(),
        }
    }
}

impl PartialEq for ModRing {
    fn eq(&self, other: &ModRing) -> bool {
        self.is_compatible(other)
    }
}

impl Eq for ModRing {}

impl fmt::Display for ModRing {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Z/{}Z [{}]", self.modulus, self.reduction())
    }
}

/// An element of a [`ModRing`], tied to its ring by a borrow.
///
/// The stored limbs are in whatever representation the ring's engine uses, which
/// for Montgomery is *not* the ordinary residue. Use [`ModInt::value`] to get
/// the residue in `[0, n)`.
#[derive(Debug, Clone)]
pub struct ModInt<'a> {
    ring: &'a ModRing,
    inner: BigU,
}

impl<'a> ModInt<'a> {
    /// The ring this element belongs to.
    pub fn ring(&self) -> &'a ModRing {
        self.ring
    }

    /// The ordinary residue in `[0, n)`.
    pub fn value(&self) -> BigU {
        self.ring.out(&self.inner)
    }

    /// True when the element is the additive identity. Cheap: zero is zero in
    /// both representations.
    pub fn is_zero(&self) -> bool {
        self.inner.is_zero()
    }

    /// True when the element is the multiplicative identity.
    pub fn is_one(&self) -> bool {
        self.value() == &BigU::one() % self.ring.modulus()
    }

    /// Fails unless both operands came from a compatible ring.
    fn check(&self, other: &ModInt<'_>) -> Result<()> {
        if self.ring.is_compatible(other.ring) {
            Ok(())
        } else {
            Err(Error::ModulusMismatch)
        }
    }

    /// Modular addition, erroring on a cross-ring operand.
    pub fn checked_add(&self, other: &ModInt<'_>) -> Result<ModInt<'a>> {
        self.check(other)?;
        let mut sum = &self.inner + &other.inner;
        // Both operands are below `n`, so one subtraction always suffices.
        if sum >= *self.ring.modulus() {
            sum -= self.ring.modulus();
        }
        Ok(ModInt {
            ring: self.ring,
            inner: sum,
        })
    }

    /// Modular subtraction, erroring on a cross-ring operand.
    pub fn checked_sub(&self, other: &ModInt<'_>) -> Result<ModInt<'a>> {
        self.check(other)?;
        let inner = if self.inner >= other.inner {
            &self.inner - &other.inner
        } else {
            &(&self.inner + self.ring.modulus()) - &other.inner
        };
        Ok(ModInt {
            ring: self.ring,
            inner,
        })
    }

    /// Modular multiplication through the ring's engine, erroring on a
    /// cross-ring operand.
    pub fn checked_mul(&self, other: &ModInt<'_>) -> Result<ModInt<'a>> {
        self.check(other)?;
        Ok(ModInt {
            ring: self.ring,
            inner: self.ring.mul_inner(&self.inner, &other.inner),
        })
    }

    /// The additive inverse.
    pub fn negate(&self) -> ModInt<'a> {
        let inner = if self.inner.is_zero() {
            BigU::zero()
        } else {
            self.ring.modulus() - &self.inner
        };
        ModInt {
            ring: self.ring,
            inner,
        }
    }

    /// The square of the element, one engine multiply.
    pub fn square(&self) -> ModInt<'a> {
        ModInt {
            ring: self.ring,
            inner: self.ring.mul_inner(&self.inner, &self.inner),
        }
    }

    /// The multiplicative inverse, or [`Error::NotInvertible`] when the element
    /// shares a factor with the modulus.
    ///
    /// The inverse is computed on the ordinary residue by extended Euclid and
    /// then re-entered into the ring, so it is correct for either engine.
    pub fn inv(&self) -> Result<ModInt<'a>> {
        let inverse = self.value().modinv(self.ring.modulus())?;
        Ok(self.ring.elem(&inverse))
    }

    /// Raises the element to `exp` with a Montgomery ladder.
    ///
    /// The ladder performs exactly one squaring and one multiplication per
    /// exponent bit regardless of the bit's value, so the operation sequence
    /// does not leak the exponent the way plain square-and-multiply does. The
    /// name is Montgomery's (1987) and is unrelated to the reduction strategy —
    /// the ladder runs over a Barrett ring just as happily.
    pub fn pow(&self, exp: &BigU) -> ModInt<'a> {
        let bits = exp.bit_len();
        if bits == 0 {
            return self.ring.one();
        }
        let mut r0 = self.ring.one();
        let mut r1 = self.clone();
        for i in (0..bits).rev() {
            if exp.bit(i) {
                r0 = ModInt {
                    ring: self.ring,
                    inner: self.ring.mul_inner(&r0.inner, &r1.inner),
                };
                r1 = r1.square();
            } else {
                r1 = ModInt {
                    ring: self.ring,
                    inner: self.ring.mul_inner(&r0.inner, &r1.inner),
                };
                r0 = r0.square();
            }
        }
        r0
    }
}

impl PartialEq for ModInt<'_> {
    /// Elements compare equal only when they live in compatible rings; an
    /// element of `Z/7Z` is never equal to one of `Z/11Z`.
    fn eq(&self, other: &ModInt<'_>) -> bool {
        self.ring.is_compatible(other.ring) && self.inner == other.inner
    }
}

impl Eq for ModInt<'_> {}

impl fmt::Display for ModInt<'_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.value())
    }
}

impl<'a> Add for &ModInt<'a> {
    type Output = ModInt<'a>;
    /// Panics on a cross-ring operand; see [`ModInt::checked_add`].
    fn add(self, other: &ModInt<'a>) -> ModInt<'a> {
        self.checked_add(other)
            .expect("operands from different rings")
    }
}

impl<'a> Sub for &ModInt<'a> {
    type Output = ModInt<'a>;
    /// Panics on a cross-ring operand; see [`ModInt::checked_sub`].
    fn sub(self, other: &ModInt<'a>) -> ModInt<'a> {
        self.checked_sub(other)
            .expect("operands from different rings")
    }
}

impl<'a> Mul for &ModInt<'a> {
    type Output = ModInt<'a>;
    /// Panics on a cross-ring operand; see [`ModInt::checked_mul`].
    fn mul(self, other: &ModInt<'a>) -> ModInt<'a> {
        self.checked_mul(other)
            .expect("operands from different rings")
    }
}

impl<'a> Neg for &ModInt<'a> {
    type Output = ModInt<'a>;
    fn neg(self) -> ModInt<'a> {
        self.negate()
    }
}

/// A set of pairwise-coprime moduli plus the constants Garner's algorithm needs
/// to rebuild a value from its residues.
///
/// Splitting a wide computation across small coprime moduli and reconstructing
/// at the end is the standard way to keep intermediate operands narrow. The
/// basis owns the precomputation, so a reconstruction costs one small inverse
/// multiply per modulus and nothing else.
///
/// ```
/// use bigu::{BigU, CrtBasis};
///
/// // The classic Sun Tzu problem: x = 2 (mod 3), 3 (mod 5), 2 (mod 7).
/// let basis = CrtBasis::new(&[BigU::from(3u32), BigU::from(5u32), BigU::from(7u32)]).unwrap();
/// let residues = [BigU::from(2u32), BigU::from(3u32), BigU::from(2u32)];
/// assert_eq!(basis.reconstruct(&residues).unwrap(), BigU::from(23u32));
/// ```
#[derive(Debug, Clone)]
pub struct CrtBasis {
    moduli: Vec<BigU>,
    /// `coeffs[i] == (m_0 * ... * m_{i-1})^-1 mod m_i`; `coeffs[0]` is unused.
    coeffs: Vec<BigU>,
    /// The product of every modulus, i.e. the range the basis represents.
    product: BigU,
}

impl CrtBasis {
    /// Builds a basis over `moduli`.
    ///
    /// Returns [`Error::EmptyBasis`] when the slice is empty,
    /// [`Error::DivByZero`] when any modulus is zero, and [`Error::NotCoprime`]
    /// when two moduli share a factor — which is exactly the condition under
    /// which reconstruction would not be unique.
    pub fn new(moduli: &[BigU]) -> Result<CrtBasis> {
        if moduli.is_empty() {
            return Err(Error::EmptyBasis);
        }
        for m in moduli {
            if m.is_zero() {
                return Err(Error::DivByZero);
            }
        }
        for i in 0..moduli.len() {
            for j in (i + 1)..moduli.len() {
                if moduli[i].gcd(&moduli[j]) != BigU::one() {
                    return Err(Error::NotCoprime);
                }
            }
        }

        let mut coeffs = Vec::with_capacity(moduli.len());
        coeffs.push(BigU::zero());
        let mut running = moduli[0].clone();
        for m in &moduli[1..] {
            // Coprimality was checked above, so this inverse always exists.
            let c = running.modinv(m)?;
            coeffs.push(c);
            running = &running * m;
        }

        Ok(CrtBasis {
            moduli: moduli.to_vec(),
            coeffs,
            product: running,
        })
    }

    /// The moduli, in the order reconstruction expects residues.
    pub fn moduli(&self) -> &[BigU] {
        &self.moduli
    }

    /// The product of the moduli: reconstruction is unique below this value.
    pub fn product(&self) -> &BigU {
        &self.product
    }

    /// How many moduli the basis carries.
    pub fn len(&self) -> usize {
        self.moduli.len()
    }

    /// Always false — a basis cannot be built empty.
    pub fn is_empty(&self) -> bool {
        self.moduli.is_empty()
    }

    /// Splits `value` into one residue per modulus.
    pub fn reduce(&self, value: &BigU) -> Vec<BigU> {
        self.moduli.iter().map(|m| value % m).collect()
    }

    /// Rebuilds the unique value below [`CrtBasis::product`] with the given
    /// residues, using Garner's algorithm.
    ///
    /// Returns [`Error::ModulusMismatch`] when the residue count does not match
    /// the basis. Residues larger than their modulus are reduced first rather
    /// than rejected, so `reconstruct` accepts anything congruent.
    pub fn reconstruct(&self, residues: &[BigU]) -> Result<BigU> {
        if residues.len() != self.moduli.len() {
            return Err(Error::ModulusMismatch);
        }

        let mut x = &residues[0] % &self.moduli[0];
        let mut running = self.moduli[0].clone();
        for ((m, coeff), residue) in self.moduli.iter().zip(&self.coeffs).zip(residues).skip(1) {
            let target = residue % m;
            let current = &x % m;
            // (target - current) * coeff, kept unsigned by borrowing one `m`.
            let diff = if target >= current {
                &target - &current
            } else {
                &(&target + m) - &current
            };
            let step = &(&diff * coeff) % m;
            x = &x + &(&running * &step);
            running = &running * m;
        }
        Ok(x)
    }

    /// Reconstructs from residues expressed as [`ModInt`] values.
    ///
    /// Each element must live in a ring whose modulus is the corresponding entry
    /// of the basis, which is checked; otherwise this is
    /// [`Error::ModulusMismatch`].
    pub fn reconstruct_ints(&self, residues: &[ModInt<'_>]) -> Result<BigU> {
        if residues.len() != self.moduli.len() {
            return Err(Error::ModulusMismatch);
        }
        let mut values = Vec::with_capacity(residues.len());
        for (elem, m) in residues.iter().zip(&self.moduli) {
            if elem.ring().modulus() != m {
                return Err(Error::ModulusMismatch);
            }
            values.push(elem.value());
        }
        self.reconstruct(&values)
    }

    /// Builds a [`ModRing`] for every modulus, so a computation can be carried
    /// out independently in each channel and reconstructed afterwards.
    pub fn rings(&self) -> Result<Vec<ModRing>> {
        self.moduli.iter().map(ModRing::new).collect()
    }
}

impl PartialEq for CrtBasis {
    fn eq(&self, other: &CrtBasis) -> bool {
        self.moduli == other.moduli
    }
}

impl Eq for CrtBasis {}

impl PartialOrd for CrtBasis {
    /// Bases order by the size of the range they can represent.
    fn partial_cmp(&self, other: &CrtBasis) -> Option<Ordering> {
        Some(self.product.cmp(&other.product))
    }
}

impl fmt::Display for CrtBasis {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "CRT basis of {} moduli, range {}",
            self.moduli.len(),
            self.product
        )
    }
}

impl BigU {
    /// Computes `self^exp mod modulus` through a precomputed reduction engine.
    ///
    /// Same result as [`BigU::modpow`], but the modulus is analysed once and
    /// every subsequent reduction avoids a multi-limb division. Prefer building
    /// a [`ModRing`] directly when the same modulus is reused.
    ///
    /// ```
    /// use bigu::BigU;
    /// let b = BigU::from(4u32);
    /// assert_eq!(
    ///     b.modpow_fast(&BigU::from(13u32), &BigU::from(497u32)).unwrap(),
    ///     BigU::from(445u32)
    /// );
    /// ```
    pub fn modpow_fast(&self, exp: &BigU, modulus: &BigU) -> Result<BigU> {
        let ring = ModRing::new(modulus)?;
        Ok(ring.pow(self, exp))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn barrett_falls_back_to_division_for_oversized_input() {
        // `reduce` is only ever fed products below b^(2k) by the ring, so this
        // path needs a direct call to exercise.
        let n = BigU::from(97u32);
        let ctx = BarrettCtx::new(&n);
        assert_eq!(ctx.k, 1);
        let huge = &BigU::one() << 200;
        assert!(huge.limbs.len() > 2 * ctx.k);
        assert_eq!(ctx.reduce(&huge), &huge % &n);
    }

    /// Deterministic pseudo-random stream so these sweeps are reproducible.
    fn stream(seed: u64, count: usize) -> Vec<u64> {
        let mut x = seed | 1;
        (0..count)
            .map(|_| {
                x ^= x >> 12;
                x ^= x << 25;
                x ^= x >> 27;
                x.wrapping_mul(0x2545_F491_4F6C_DD1D)
            })
            .collect()
    }

    #[test]
    fn barrett_reduces_wide_inputs_including_the_borrow_case() {
        // With a two-limb modulus the intermediates are truncated to b^(k+1),
        // so `r1 < r2` really happens and the borrow path is live.
        let n = BigU::from(0x1234_5678_9abc_def0u64);
        let ctx = BarrettCtx::new(&n);
        assert_eq!(ctx.k, 2);
        let words = stream(0xFACE_1234, 400);
        for pair in words.chunks(2) {
            let x = (BigU::from(pair[0]) << 64) + BigU::from(pair[1]);
            assert_eq!(ctx.reduce(&x), &x % &n, "wrong reduction of {x}");
        }

        // The borrow inside the b^(k+1) window only fires when the low k+1
        // limbs of the input are smaller than the true remainder, which random
        // inputs hit with probability about 2^-32. Force it: park the value in
        // the top limb and leave the low window nearly empty.
        let mut borrowed = 0;
        for (i, word) in stream(0x51D3_2468, 64).into_iter().enumerate() {
            let x = (BigU::from(word as u32) << 96) + BigU::from(i as u32);
            let expected = &x % &n;
            assert_eq!(ctx.reduce(&x), expected, "wrong reduction of {x}");
            if expected > BigU::from(i as u32) {
                borrowed += 1;
            }
        }
        assert!(borrowed > 0, "the borrow path was never exercised");
    }

    #[test]
    fn redc_hits_the_conditional_subtraction() {
        // REDC leaves a value below 2n, so a final subtraction is sometimes
        // needed. Sweeping the whole input range exercises both outcomes.
        let n = BigU::from(4294967291u32);
        let ctx = MontgomeryCtx::new(&n);
        let r = &BigU::one() << LIMB_BITS;
        let r_inv = (&r % &n).modinv(&n).unwrap();
        // REDC is only defined for `t < R * n`, so inputs are kept in range.
        let bound = &r * &n;
        for raw in stream(0x0505_0505, 200) {
            let t = &BigU::from(raw) % &bound;
            let expected = &(&(&t % &n) * &r_inv) % &n;
            assert_eq!(ctx.redc(&t.limbs), expected, "wrong REDC of {t}");
        }
    }

    #[test]
    fn barrett_passes_through_values_already_reduced() {
        let ctx = BarrettCtx::new(&BigU::from(97u32));
        assert_eq!(ctx.reduce(&BigU::from(5u32)), BigU::from(5u32));
        assert_eq!(ctx.reduce(&BigU::zero()), BigU::zero());
    }

    #[test]
    fn limb_helpers_handle_over_long_requests() {
        let x = BigU::from(0x1234_5678_9abc_def0u64);
        assert_eq!(limb_shr(&x, 0), x);
        assert_eq!(limb_shr(&x, 1), BigU::from(0x1234_5678u32));
        assert!(limb_shr(&x, 2).is_zero());
        assert!(limb_shr(&x, 9).is_zero());
        assert_eq!(limb_trunc(&x, 1), BigU::from(0x9abc_def0u32));
        assert_eq!(limb_trunc(&x, 9), x);
        assert!(limb_trunc(&x, 0).is_zero());
    }

    #[test]
    fn montgomery_constants_satisfy_their_defining_equations() {
        for m in [3u32, 97, 65535, 0xFFFF_FFFF] {
            let n = BigU::from(m);
            let ctx = MontgomeryCtx::new(&n);
            // n * n' == -1 mod 2^LIMB_BITS.
            assert_eq!(n.limbs[0].wrapping_mul(ctx.n_prime), Limb::MAX);
            let r = &BigU::one() << (LIMB_BITS * ctx.k as u32);
            assert_eq!(ctx.r_mod_n, &r % &n);
            assert_eq!(ctx.r2, &(&r * &r) % &n);
        }
    }

    #[test]
    fn redc_undoes_the_montgomery_factor() {
        let n = BigU::from(4294967291u32);
        let ctx = MontgomeryCtx::new(&n);
        // REDC(a * R mod n) == a.
        for a in [0u32, 1, 2, 12345, 4294967290] {
            let a = BigU::from(a);
            let lifted = &(&a * &(&BigU::one() << (LIMB_BITS * ctx.k as u32))) % &n;
            assert_eq!(ctx.redc(&lifted.limbs), a);
        }
    }
}
