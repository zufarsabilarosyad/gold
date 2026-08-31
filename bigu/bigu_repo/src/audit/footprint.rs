//! What a value costs, as opposed to what it is.
//!
//! A bignum's price is its allocation, and the allocation is not visible from
//! the number: `2^128` and `2^128 - 1` print very differently and cost the same,
//! while a value that once held a thousand limbs and was then reduced to one
//! still owns the thousand-limb buffer. That gap gets a figure of its own here.
//! A [`BigI`](crate::BigI) has no entry point, being a flag beside a magnitude
//! that `of(v.magnitude())` already prices; a [`BigQ`] has one, owning two
//! vectors.
//!
//! Two accountings can only be bounds. The tables inside a [`ModRing`] and the
//! Garner coefficients inside a [`CrtBasis`] are private to their module, so
//! their size is derived from the geometry the public API does expose and the
//! answer carries [`Footprint::exact`] cleared — a bound that says so beats a
//! precise figure that is quietly wrong.

use core::fmt;
use core::mem::size_of;

use crate::audit::layout;
use crate::bigu::BigU;
use crate::modring::{CrtBasis, ModRing, Reduction};
use crate::ratio::BigQ;

/// Bytes one limb occupies.
const LIMB_BYTES: usize = size_of::<u32>();

/// The memory a value holds, split into the part carrying information and the
/// part merely reserved.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Footprint {
    /// Limbs actually holding value.
    pub limbs: usize,
    /// Limbs the allocation can hold before it must grow.
    pub capacity: usize,
    /// Bytes on the heap: `capacity * 4`.
    pub heap_bytes: usize,
    /// Bytes held inline in the value: vector headers and any sign flag.
    pub inline_bytes: usize,
    /// Cleared when the figures are an upper bound rather than a reading.
    pub exact: bool,
}

impl Footprint {
    /// Assembles the derived fields from a limb count and a capacity.
    fn new(limbs: usize, capacity: usize, inline: usize, exact: bool) -> Footprint {
        let heap_bytes = capacity * LIMB_BYTES;
        Footprint { limbs, capacity, heap_bytes, inline_bytes: inline, exact }
    }

    /// Heap plus inline bytes.
    ///
    /// ```
    /// use bigu::{audit::footprint, BigU};
    /// let f = footprint::of(&BigU::from(u64::MAX));
    /// assert_eq!(f.total_bytes(), f.heap_bytes + f.inline_bytes);
    /// ```
    pub fn total_bytes(&self) -> usize {
        self.heap_bytes + self.inline_bytes
    }

    /// Bytes reserved but unused: `(capacity - limbs) * 4`.
    ///
    /// ```
    /// use bigu::{audit::footprint, BigU};
    /// assert_eq!(footprint::of(&BigU::zero()).slack_bytes(), 0);
    /// ```
    pub fn slack_bytes(&self) -> usize {
        self.capacity.saturating_sub(self.limbs) * LIMB_BYTES
    }
}

impl fmt::Display for Footprint {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let mark = if self.exact { "" } else { "<= " };
        let (n, heap) = (self.limbs, self.heap_bytes);
        let (slack, inline) = (self.slack_bytes(), self.inline_bytes);
        write!(f, "{mark}{n} limbs, {mark}{heap} heap + {inline} inline ({slack} slack)")
    }
}

/// The exact footprint of a [`BigU`], read from its limb vector.
///
/// ```
/// use bigu::{audit::footprint, BigU};
/// let f = footprint::of(&BigU::from(u64::MAX));
/// assert_eq!((f.limbs, f.exact, f.heap_bytes), (2, true, f.capacity * 4));
/// ```
pub fn of(v: &BigU) -> Footprint {
    let capacity = v.limbs.capacity();
    Footprint::new(layout::limb_count(v), capacity, size_of::<BigU>(), true)
}

/// The footprint of a [`BigQ`]: numerator and denominator together.
///
/// ```
/// use bigu::{audit::footprint, BigQ};
/// use std::str::FromStr;
/// // One limb each side of the bar.
/// assert_eq!(footprint::of_bigq(&BigQ::from_str("1/3").unwrap()).limbs, 2);
/// ```
pub fn of_bigq(v: &BigQ) -> Footprint {
    let (n, d) = (of(v.numer().magnitude()), of(v.denom()));
    Footprint::new(n.limbs + d.limbs, n.capacity + d.capacity, size_of::<BigQ>(), true)
}

/// The aggregate footprint of a slice of values, inline bytes included.
///
/// ```
/// use bigu::{audit::footprint, BigU};
/// let vals = [BigU::from(1u32), BigU::from(u64::MAX), BigU::zero()];
/// assert_eq!(footprint::total(&vals).limbs, 3);
/// assert_eq!(footprint::total(&[]).total_bytes(), 0);
/// ```
pub fn total(values: &[BigU]) -> Footprint {
    let limbs: usize = values.iter().map(layout::limb_count).sum();
    let capacity: usize = values.iter().map(|v| v.limbs.capacity()).sum();
    Footprint::new(limbs, capacity, values.len() * size_of::<BigU>(), true)
}

/// A bound on what a [`ModRing`]'s precomputed tables cost.
///
/// With `k` the limb count of the modulus, Montgomery keeps the padded modulus
/// (`k`) plus `R^2 mod n` and `R mod n`, both below `n` and so at most `k` each;
/// Barrett keeps the modulus (`k`) and `mu = floor(b^2k / n)`, at most `k + 1`.
/// The ring's own copy of the modulus brings those to `4k` and `3k + 1` limbs.
///
/// ```
/// use bigu::{audit::footprint, BigU, ModRing};
/// // A one-limb odd modulus, so Montgomery: at most four limbs of tables.
/// let f = footprint::of_ring(&ModRing::new(&BigU::from(97u32)).unwrap());
/// assert_eq!((f.limbs, f.exact), (4, false));
/// ```
pub fn of_ring(ring: &ModRing) -> Footprint {
    let k = layout::limb_count(ring.modulus());
    let limbs = match ring.reduction() {
        Reduction::Montgomery => 4 * k,
        Reduction::Barrett => 3 * k + 1,
    };
    Footprint::new(limbs, limbs, size_of::<ModRing>(), false)
}

/// A bound on what a [`CrtBasis`] costs: its moduli and product exactly, plus
/// the Garner coefficients, each a residue below its own modulus.
///
/// ```
/// use bigu::{audit::footprint, BigU, CrtBasis};
/// let basis = CrtBasis::new(&[BigU::from(3u32), BigU::from(5u32)]).unwrap();
/// // Two moduli, one product limb, one coefficient: the first one is unused.
/// assert_eq!(footprint::of_basis(&basis).limbs, 4);
/// ```
pub fn of_basis(basis: &CrtBasis) -> Footprint {
    let moduli = basis.moduli();
    let modulus_limbs: usize = moduli.iter().map(layout::limb_count).sum();
    // `coeffs[0]` is a placeholder zero; the rest are residues below their own.
    let coeff_limbs = modulus_limbs - layout::limb_count(&moduli[0]);
    let limbs = modulus_limbs + coeff_limbs + layout::limb_count(basis.product());
    Footprint::new(limbs, limbs, size_of::<CrtBasis>(), false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use core::str::FromStr;

    #[test]
    fn heap_tracks_capacity_not_length() {
        // A vector reserved far beyond its content still owns every byte.
        let mut v = BigU::from(1u32);
        v.limbs.reserve_exact(64);
        let f = of(&v);
        assert_eq!((f.limbs, f.heap_bytes), (1, f.capacity * 4));
        assert!(f.capacity >= 65 && f.slack_bytes() >= 64 * 4);
        // Zero, by contrast, costs only the header it carries inline.
        let z = of(&BigU::zero());
        assert_eq!((z.limbs, z.heap_bytes, z.slack_bytes()), (0, 0, 0));
        assert_eq!(z.total_bytes(), size_of::<BigU>());
    }

    #[test]
    fn values_scale_by_four_bytes_a_limb() {
        let f = of(&(BigU::from(1u32) << 1024));
        assert_eq!((f.limbs, f.heap_bytes >= 33 * 4), (33, true));
        let q = BigQ::from_str("123456789012345678901234567890/7").unwrap();
        assert_eq!(of_bigq(&q).limbs, of(q.numer().magnitude()).limbs + 1);
        let vals = [BigU::from(1u32) << 100, BigU::from(7u32), BigU::zero()];
        let parts: usize = vals.iter().map(|v| of(v).heap_bytes).sum();
        assert_eq!((total(&vals).limbs, total(&vals).heap_bytes), (5, parts));
    }

    #[test]
    fn both_engines_bound_the_tables_and_say_that_they_do() {
        let odd = ModRing::new(&BigU::from(u64::MAX)).unwrap();
        let even = ModRing::new(&BigU::from(u64::MAX - 1)).unwrap();
        assert_eq!((odd.reduction(), even.reduction()), (Reduction::Montgomery, Reduction::Barrett));
        assert_eq!((of_ring(&odd).limbs, of_ring(&even).limbs), (8, 7));
        assert!(of_ring(&odd).to_string().starts_with("<= "));
        assert!(!of(&BigU::from(3u32)).to_string().starts_with("<= "));
    }
}
