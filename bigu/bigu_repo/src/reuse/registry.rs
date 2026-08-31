//! A cache for the crate's expensive precomputations.
//!
//! [`ModRing::new`] is not cheap. Montgomery setup runs a Newton iteration for
//! the inverse of the low limb and then two full-width reductions to get
//! `R mod n` and `R^2 mod n`; Barrett setup computes `floor(b^(2k) / n)`, a
//! division wider than the modulus. Both buy every later multiply, but only if
//! the ring lives long enough to be used, and a program calling
//! [`BigU::modpow_fast`](crate::BigU::modpow_fast) in a loop throws that setup
//! away on every call. The registry keys those objects by what determines them:
//! a [`ModRing`] by its modulus and [`Reduction`], a [`CrtBasis`] by its moduli
//! list; lookup is a linear scan, since a program juggles a handful of moduli.
//!
//! Entries are handed out as borrows, never clones. A clone copies the
//! precomputation and defeats the purpose, and [`ModRing::is_compatible`] opens
//! with a pointer comparison, so elements drawn from one entry take that fast
//! path. Entries are boxed to keep the address stable: the backing vector moves
//! as it grows, and a moved ring would lose that identity.

use super::metrics::{Counters, MetricsSnapshot};
use crate::bigu::BigU;
use crate::error::{Error, Result};
use crate::modring::{CrtBasis, ModRing, Reduction};

/// A keyed cache of [`ModRing`] and [`CrtBasis`] precomputations.
///
/// ```
/// use bigu::{BigU, Reduction, reuse::Registry};
/// let (mut reg, m) = (Registry::new(), BigU::from(497u32));
/// assert_eq!(reg.ring(&m).unwrap().reduction(), Reduction::Montgomery);
/// assert_eq!(reg.ring(&m).unwrap().modulus(), &m); // the second lookup hits
/// assert_eq!((reg.rings_cached(), reg.metrics().registry_hits), (1, 1));
/// ```
#[derive(Debug, Default)]
pub struct Registry {
    rings: Vec<Box<ModRing>>,
    bases: Vec<Box<CrtBasis>>,
    counters: Counters,
}

impl Registry {
    /// An empty registry.
    /// ```
    /// assert_eq!(bigu::reuse::Registry::new().rings_cached(), 0);
    /// ```
    pub fn new() -> Registry {
        Registry::default()
    }

    /// Borrows the ring for `modulus`, building it on first request. Montgomery
    /// for an odd modulus and Barrett otherwise, exactly as [`ModRing::new`]
    /// chooses; a zero modulus is [`Error::DivByZero`].
    ///
    /// ```
    /// use bigu::{BigU, reuse::Registry};
    /// let ring = Registry::new().ring(&BigU::from(97u32)).unwrap().clone();
    /// assert_eq!(ring.pow(&BigU::from(5u32), &BigU::from(3u32)), BigU::from(28u32));
    /// ```
    pub fn ring(&mut self, modulus: &BigU) -> Result<&ModRing> {
        match modulus.limbs.first() {
            None => Err(Error::DivByZero),
            Some(low) if low & 1 == 1 => self.ring_with(modulus, Reduction::Montgomery),
            _ => self.ring_with(modulus, Reduction::Barrett),
        }
    }

    /// Borrows the ring for `modulus` under an explicitly chosen strategy. Two
    /// rings over one modulus with different strategies are separate entries,
    /// since their elements are not interchangeable.
    ///
    /// ```
    /// use bigu::{BigU, Error, Reduction, reuse::Registry};
    /// let (mut reg, m) = (Registry::new(), BigU::from(15u32));
    /// reg.ring_with(&m, Reduction::Montgomery).unwrap();
    /// reg.ring_with(&m, Reduction::Barrett).unwrap();
    /// assert_eq!(reg.rings_cached(), 2);
    /// let bad = reg.ring_with(&BigU::from(16u32), Reduction::Montgomery);
    /// assert_eq!(bad.unwrap_err(), Error::EvenModulus);
    /// ```
    pub fn ring_with(&mut self, modulus: &BigU, reduction: Reduction) -> Result<&ModRing> {
        // Resolve to an index first: a borrow out of one arm would still be
        // live across the insertion in the other.
        let hit = self
            .rings
            .iter()
            .position(|r| r.reduction() == reduction && r.modulus() == modulus);
        let i = match hit {
            Some(i) => self.hit(i),
            None => {
                self.counters.record_registry_miss();
                let built = ModRing::with_reduction(modulus, reduction)?;
                self.rings.push(Box::new(built));
                self.rings.len() - 1
            }
        };
        Ok(&self.rings[i])
    }

    /// Borrows the CRT basis over `moduli`, building it on first request. The
    /// list is the key *in order*, since reconstruction is positional.
    ///
    /// ```
    /// use bigu::{BigU, reuse::Registry};
    /// let mut reg = Registry::new();
    /// let ms = [BigU::from(3u32), BigU::from(5u32), BigU::from(7u32)];
    /// assert_eq!(reg.basis(&ms).unwrap().product(), &BigU::from(105u32));
    /// ```
    pub fn basis(&mut self, moduli: &[BigU]) -> Result<&CrtBasis> {
        let i = match self.bases.iter().position(|b| b.moduli() == moduli) {
            Some(i) => self.hit(i),
            None => {
                self.counters.record_registry_miss();
                self.bases.push(Box::new(CrtBasis::new(moduli)?));
                self.bases.len() - 1
            }
        };
        Ok(&self.bases[i])
    }

    /// Tallies a hit and passes the index back, so both lookups record alike.
    fn hit(&mut self, i: usize) -> usize {
        self.counters.record_registry_hit();
        i
    }

    /// How many distinct rings are held; basis reuse shows up in the tallies.
    ///
    /// ```
    /// let mut reg = bigu::reuse::Registry::new();
    /// reg.ring(&bigu::BigU::from(7u32)).unwrap();
    /// assert_eq!(reg.rings_cached(), 1);
    /// ```
    pub fn rings_cached(&self) -> usize {
        self.rings.len()
    }

    /// A frozen reading of this registry's counters.
    /// ```
    /// assert_eq!(bigu::reuse::Registry::new().metrics().registry_hits, 0);
    /// ```
    pub fn metrics(&self) -> MetricsSnapshot {
        self.counters.snapshot()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_repeated_modulus_is_built_once_and_keeps_its_address() {
        let (mut reg, m) = (Registry::new(), BigU::from(1_000_003u32));
        let first = reg.ring(&m).unwrap() as *const ModRing;
        for p in [101u32, 103, 107, 109, 113, 127, 131, 137, 139, 149] {
            reg.ring(&BigU::from(p)).unwrap();
        }
        let again = reg.ring(&m).unwrap() as *const ModRing;
        assert!(core::ptr::eq(first, again), "boxing keeps ptr equality useful");
        assert_eq!((reg.rings_cached(), reg.metrics().registry_hits), (11, 1));
        // Strategy is part of the key; an even modulus goes to Barrett.
        for r in [Reduction::Montgomery, Reduction::Barrett] {
            assert_eq!(reg.ring_with(&m, r).unwrap().reduction(), r);
        }
        let even = reg.ring(&BigU::from(1024u32)).unwrap().reduction();
        assert_eq!((reg.rings_cached(), even), (13, Reduction::Barrett));
    }

    #[test]
    fn a_rejected_key_leaves_the_cache_untouched() {
        let mut reg = Registry::new();
        assert_eq!(reg.ring(&BigU::zero()).unwrap_err(), Error::DivByZero);
        let even = reg.ring_with(&BigU::from(4u32), Reduction::Montgomery);
        assert_eq!(even.unwrap_err(), Error::EvenModulus);
        assert_eq!(reg.basis(&[]).unwrap_err(), Error::EmptyBasis);
        let shared = [BigU::from(4u32), BigU::from(6u32)];
        assert_eq!(reg.basis(&shared).unwrap_err(), Error::NotCoprime);
        assert_eq!((reg.rings_cached(), reg.metrics().registry_hits), (0, 0));
    }

    #[test]
    fn bases_are_keyed_by_the_moduli_in_order() {
        let mut reg = Registry::new();
        let a = [BigU::from(3u32), BigU::from(5u32)];
        let b = [BigU::from(5u32), BigU::from(3u32)];
        for key in [&a, &b, &a] {
            reg.basis(key).unwrap();
        }
        let s = reg.metrics();
        assert_eq!((s.registry_misses, s.registry_hits), (2, 1));
    }

    #[test]
    fn a_cached_ring_computes_the_same_answers_as_a_fresh_one() {
        let (m, base) = (BigU::from(1_000_000_007u32), BigU::from(123_456_789u32));
        let exp = BigU::from(65_537u32);
        let direct = ModRing::new(&m).unwrap().pow(&base, &exp);
        let mut reg = Registry::new();
        reg.ring(&m).unwrap();
        assert_eq!(direct, reg.ring(&m).unwrap().pow(&base, &exp));
    }
}
