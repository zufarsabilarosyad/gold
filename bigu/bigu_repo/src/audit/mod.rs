//! Read-only introspection over values the crate has already built.
//!
//! Everything else in `bigu` produces numbers. This directory produces
//! *descriptions* of numbers, and answers three questions the arithmetic
//! modules only ever answered in passing: is this representation well formed
//! ([`invariant`]), what does it cost ([`footprint`]), and how do these two
//! differ ([`delta`])? Before it existed, the first question lived in scattered
//! `debug_assert!`s that disappeared in release builds, the second could not be
//! asked at all, and the third had to be reconstructed by eye from two `Debug`
//! strings.
//!
//! The charter, which every function in this directory keeps:
//!
//! * it takes a shared borrow and never a value, so auditing cannot disturb
//!   what it audits;
//! * it returns a description — a report, a violation list, a string, a count —
//!   and never a `BigU`, `BigI`, `BigQ` or `ModInt`, so no number can escape
//!   from here into a computation;
//! * arithmetic is only ever scratch work. [`invariant::check_basis`] does
//!   multiply the moduli together, because that is the only way to know whether
//!   the stored product is right, but the product it forms is compared and
//!   dropped.
//!
//! The three questions share one entry point, the [`Audit`] trait, implemented
//! for every value type the crate exposes. It is the shallow end: it says
//! whether a value is well formed and describes its shape in a line. When the
//! answer is "no", the submodules say why.
//!
//! ```
//! use bigu::audit::{Audit, AuditReport};
//! use bigu::BigQ;
//! use std::str::FromStr;
//!
//! let q = BigQ::from_str("22/7").unwrap();
//! assert!(q.is_well_formed());
//! assert_eq!(q.describe(), "BigQ{num_limbs=1, den_limbs=1, sign=1}");
//!
//! let report = AuditReport::of("denominator", q.denom());
//! assert!(report.is_clean());
//! ```

pub mod delta;
pub mod dump;
pub mod fingerprint;
pub mod footprint;
pub mod invariant;
pub mod layout;
pub mod report;

pub use self::fingerprint::Fingerprint;
pub use self::footprint::Footprint;
pub use self::invariant::Violation;
pub use self::report::AuditReport;

use crate::bigi::BigI;
use crate::bigu::BigU;
use crate::modring::{CrtBasis, ModInt};
use crate::ratio::BigQ;

/// The common entry point: any crate value can state its own canonical-form
/// rules and describe its representation.
///
/// The two methods are deliberately narrow. `violations` is the type's rule
/// book, evaluated; `describe` is one line about storage, never about value.
/// Anything richer belongs in a submodule, where it can be given a name and a
/// doc of its own.
pub trait Audit {
    /// Every canonical-form rule this value breaks, empty when it is sound.
    fn violations(&self) -> Vec<Violation>;

    /// A one-line description of the representation, not of the number.
    fn describe(&self) -> String;

    /// Whether the value breaks no rule.
    ///
    /// ```
    /// use bigu::audit::Audit;
    /// use bigu::BigU;
    /// assert!(BigU::from(u64::MAX).is_well_formed());
    /// ```
    fn is_well_formed(&self) -> bool {
        self.violations().is_empty()
    }
}

impl Audit for BigU {
    fn violations(&self) -> Vec<Violation> {
        invariant::check_bigu(self)
    }

    fn describe(&self) -> String {
        format!(
            "BigU{{limbs={}, bits={}}}",
            layout::limb_count(self),
            self.bit_len()
        )
    }
}

impl Audit for BigI {
    fn violations(&self) -> Vec<Violation> {
        invariant::check_bigi(self)
    }

    fn describe(&self) -> String {
        format!(
            "BigI{{limbs={}, bits={}, sign={}}}",
            layout::limb_count(self.magnitude()),
            self.bit_len(),
            self.signum()
        )
    }
}

impl Audit for BigQ {
    fn violations(&self) -> Vec<Violation> {
        invariant::check_bigq(self)
    }

    fn describe(&self) -> String {
        format!(
            "BigQ{{num_limbs={}, den_limbs={}, sign={}}}",
            layout::limb_count(self.numer().magnitude()),
            layout::limb_count(self.denom()),
            self.signum()
        )
    }
}

impl Audit for ModInt<'_> {
    fn violations(&self) -> Vec<Violation> {
        invariant::check_modint(self)
    }

    fn describe(&self) -> String {
        format!(
            "ModInt{{modulus_bits={}, {}}}",
            self.ring().modulus().bit_len(),
            self.ring().reduction()
        )
    }
}

impl Audit for CrtBasis {
    fn violations(&self) -> Vec<Violation> {
        invariant::check_basis(self)
    }

    fn describe(&self) -> String {
        format!(
            "CrtBasis{{moduli={}, product_bits={}}}",
            self.len(),
            self.product().bit_len()
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::modring::ModRing;
    use core::str::FromStr;

    #[test]
    fn every_type_reaches_its_own_checker() {
        assert!(BigU::from(5u32).is_well_formed());
        assert!(BigI::from(-5i64).is_well_formed());
        assert!(BigQ::from_str("-5/3").unwrap().is_well_formed());

        let ring = ModRing::new(&BigU::from(101u32)).unwrap();
        assert!(ring.elem(&BigU::from(7u32)).is_well_formed());

        let basis = CrtBasis::new(&[BigU::from(3u32), BigU::from(5u32)]).unwrap();
        assert!(basis.is_well_formed());
    }

    #[test]
    fn a_corrupt_value_fails_through_the_trait_too() {
        let bad = BigU { limbs: vec![3, 0] };
        assert!(!bad.is_well_formed());
        assert_eq!(bad.violations(), invariant::check_bigu(&bad));
    }

    #[test]
    fn descriptions_report_storage_not_value() {
        assert_eq!(BigU::zero().describe(), "BigU{limbs=0, bits=0}");
        assert_eq!(
            BigU::from(u64::MAX).describe(),
            "BigU{limbs=2, bits=64}"
        );
        assert_eq!(
            BigI::from(-1i64).describe(),
            "BigI{limbs=1, bits=1, sign=-1}"
        );
        assert_eq!(
            BigQ::from_str("6/4").unwrap().describe(),
            "BigQ{num_limbs=1, den_limbs=1, sign=1}"
        );
    }

    #[test]
    fn the_modular_descriptions_name_the_engine() {
        let odd = ModRing::new(&BigU::from(97u32)).unwrap();
        let even = ModRing::new(&BigU::from(98u32)).unwrap();
        assert_eq!(
            odd.elem(&BigU::from(1u32)).describe(),
            "ModInt{modulus_bits=7, Montgomery}"
        );
        assert_eq!(
            even.elem(&BigU::from(1u32)).describe(),
            "ModInt{modulus_bits=7, Barrett}"
        );
    }

    #[test]
    fn a_basis_describes_its_width() {
        let basis = CrtBasis::new(&[BigU::from(3u32), BigU::from(5u32)]).unwrap();
        assert_eq!(basis.describe(), "CrtBasis{moduli=2, product_bits=4}");
    }
}
