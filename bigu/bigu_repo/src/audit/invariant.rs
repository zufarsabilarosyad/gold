//! One statement of every canonical-form rule the crate relies on.
//!
//! The rules are real — division assumes a canonical divisor, `Eq` assumes a
//! canonical vector, Garner assumes coprime moduli — but each lived as a
//! `debug_assert!` where it was needed, written several times, in several
//! wordings, and gone entirely in a release build.
//!
//! Nothing here panics. A checker returns the [`Violation`]s it found, empty
//! when the value is well formed, so an assertion, a test and a failure report
//! can quote one description instead of inventing three.

use core::fmt;

use crate::audit::layout;
use crate::bigi::BigI;
use crate::bigu::BigU;
use crate::modring::{CrtBasis, ModInt};
use crate::ratio::BigQ;

/// A canonical-form rule that a value was found to break. Every variant names
/// the rule rather than the symptom, so the text stands alone in a failure.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Violation {
    /// A [`BigU`] carries a zero limb, at this index, above a nonzero one.
    TrailingZeroLimb(usize),
    /// Limbs stored, then limbs implied by the bit length; the two disagree.
    BitLenMismatch(usize, usize),
    /// A [`BigI`] is flagged negative while its magnitude is zero.
    NegativeZero,
    /// A [`BigQ`] has a zero denominator, which no constructor may produce.
    ZeroDenominator,
    /// A [`BigQ`] is not in lowest terms: its parts share a factor.
    UnreducedFraction,
    /// A [`ModInt`] holds a residue that is not below its modulus.
    ResidueOutOfRange,
    /// Two moduli of a [`CrtBasis`] share a factor, so reconstruction is not
    /// unique.
    ModuliShareFactor(usize, usize),
    /// A [`CrtBasis`] stores a product that is not the product of its moduli.
    BasisProductMismatch,
}

impl fmt::Display for Violation {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Violation::TrailingZeroLimb(i) => write!(f, "limb {i} is a trailing zero"),
            Violation::BitLenMismatch(n, w) => write!(f, "{n} limbs stored, {w} implied"),
            Violation::NegativeZero => f.write_str("zero is flagged negative"),
            Violation::ZeroDenominator => f.write_str("denominator is zero"),
            Violation::UnreducedFraction => f.write_str("fraction is not reduced"),
            Violation::ResidueOutOfRange => f.write_str("residue is not below the modulus"),
            Violation::ModuliShareFactor(a, b) => write!(f, "moduli {a} and {b} share a factor"),
            Violation::BasisProductMismatch => f.write_str("stored product is wrong"),
        }
    }
}

/// The two rules a [`BigU`] must satisfy: no trailing zero limb, and a limb
/// count that agrees with the bit length.
///
/// ```
/// use bigu::{audit::invariant, BigU};
/// assert!(invariant::check_bigu(&BigU::from(u64::MAX)).is_empty());
/// ```
pub fn check_bigu(v: &BigU) -> Vec<Violation> {
    let mut found = Vec::new();
    if let Some(0) = layout::top_limb(v) {
        found.push(Violation::TrailingZeroLimb(layout::limb_count(v) - 1));
    }
    if !layout::bit_len_agrees(v) {
        let n = layout::limbs_for_bits(v.bit_len());
        found.push(Violation::BitLenMismatch(layout::limb_count(v), n));
    }
    found
}

/// Checks a [`BigI`]: a canonical magnitude, and zero never carrying the
/// negative flag. That sign rule is what makes `Eq` and `Ord` behave like
/// integer comparison, so a stray `-0` would split zero into two unequal values.
///
/// ```
/// use bigu::{audit::invariant, BigI};
/// assert!(invariant::check_bigi(&BigI::from(-42i64)).is_empty());
/// ```
pub fn check_bigi(v: &BigI) -> Vec<Violation> {
    let mut found = check_bigu(v.magnitude());
    if v.is_negative() && v.magnitude().is_zero() {
        found.push(Violation::NegativeZero);
    }
    found
}

/// Checks a [`BigQ`]: nonzero denominator, canonical components, lowest terms.
/// Coprimality is what lets `Eq` compare component-wise, so an unreduced value
/// would differ from its own reduced form.
///
/// ```
/// use bigu::{audit::invariant, BigQ};
/// use std::str::FromStr;
/// assert!(invariant::check_bigq(&BigQ::from_str("2/4").unwrap()).is_empty());
/// ```
pub fn check_bigq(v: &BigQ) -> Vec<Violation> {
    let mut found = check_bigi(v.numer());
    found.extend(check_bigu(v.denom()));
    if v.denom().is_zero() {
        found.push(Violation::ZeroDenominator);
    } else if !v.numer().magnitude().is_coprime(v.denom()) {
        found.push(Violation::UnreducedFraction);
    }
    found
}

/// Checks a [`crate::Poly`]: no trailing zero coefficients and each coefficient is canonical.
pub fn check_poly(p: &crate::poly::Poly<BigI>) -> Vec<Violation> {
    let mut found = Vec::new();
    let coeffs = p.coeffs();
    if let Some(last) = coeffs.last() {
        if last.is_zero() {
            found.push(Violation::TrailingZeroLimb(coeffs.len() - 1));
        }
    }
    for c in coeffs {
        found.extend(check_bigi(c));
    }
    found
}

/// Checks that a [`ModInt`] holds a residue strictly below its ring's modulus.
///
/// ```
/// use bigu::{audit::invariant, BigU, ModRing};
/// let r = ModRing::new(&BigU::from(97u32)).unwrap();
/// assert!(invariant::check_modint(&r.elem(&BigU::from(1000u32))).is_empty());
/// ```
pub fn check_modint(x: &ModInt<'_>) -> Vec<Violation> {
    let value = x.value();
    let mut found = check_bigu(&value);
    if &value >= x.ring().modulus() {
        found.push(Violation::ResidueOutOfRange);
    }
    found
}

/// Checks a [`CrtBasis`]: every modulus canonical, the moduli pairwise coprime,
/// and the stored product equal to their product. The quadratic pairwise scan is
/// the price of naming *which* pair collides.
///
/// ```
/// use bigu::{audit::invariant, BigU, CrtBasis};
/// let basis = CrtBasis::new(&[BigU::from(3u32), BigU::from(5u32)]).unwrap();
/// assert!(invariant::check_basis(&basis).is_empty());
/// ```
pub fn check_basis(basis: &CrtBasis) -> Vec<Violation> {
    let moduli = basis.moduli();
    let mut found: Vec<Violation> = moduli.iter().flat_map(check_bigu).collect();
    for i in 0..moduli.len() {
        for j in (i + 1)..moduli.len() {
            if !moduli[i].is_coprime(&moduli[j]) {
                found.push(Violation::ModuliShareFactor(i, j));
            }
        }
    }
    // Evidence about the stored product, never a value this module hands back.
    let product = moduli.iter().fold(BigU::one(), |acc, m| &acc * m);
    if &product != basis.product() {
        found.push(Violation::BasisProductMismatch);
    }
    found
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::modring::ModRing;
    use core::str::FromStr;

    #[test]
    fn canonical_values_report_nothing() {
        assert!(check_bigu(&(BigU::from(1u32) << 96)).is_empty());
        assert!(check_bigu(&BigU { limbs: Vec::new() }).is_empty());
        assert!(check_bigi(&BigI::from(-1i64)).is_empty());
        assert!(check_bigq(&BigQ::from_str("-9/12").unwrap()).is_empty());
        assert!(check_bigq(&BigQ::from(0i64)).is_empty());
    }

    #[test]
    fn trailing_zero_limb_is_named_with_its_index() {
        let found = check_bigu(&BigU { limbs: vec![5, 0, 0] });
        assert!(found.contains(&Violation::TrailingZeroLimb(2)));
        // Both padding limbs are counted by `bit_len`, so it reads 64 bits and
        // implies two limbs where three are stored.
        assert!(found.iter().any(|v| matches!(v, Violation::BitLenMismatch(3, 2))));
        // The same corruption surfaces through every wrapper around it.
        let wrapped = BigI::from_parts(true, BigU { limbs: vec![1, 0] });
        assert!(!check_bigi(&wrapped).is_empty());
    }

    #[test]
    fn the_modular_types_pass_their_own_rules() {
        // Both reduction engines keep their residues below the modulus.
        for m in [97u32, 98u32] {
            let r = ModRing::new(&BigU::from(m)).unwrap();
            assert!(check_modint(&r.elem(&BigU::from(123_456u32))).is_empty());
        }
        let basis = CrtBasis::new(&[4u32, 9, 25, 49].map(BigU::from)).unwrap();
        assert!(check_basis(&basis).is_empty());
        assert_eq!(basis.product(), &BigU::from(44100u32));
    }

    #[test]
    fn violations_render_as_sentences() {
        assert_eq!(Violation::NegativeZero.to_string(), "zero is flagged negative");
        let pair = Violation::ModuliShareFactor(0, 2);
        assert_eq!(pair.to_string(), "moduli 0 and 2 share a factor");
    }
}
