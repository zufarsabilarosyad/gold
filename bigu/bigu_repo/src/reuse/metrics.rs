//! Counters for the reuse machinery itself.
//!
//! Everything else here makes a claim about cost: the pool recycles, the
//! registry precomputes once, the budget refuses before allocating. None of
//! those claims shows up in a result, so without counters they are assumptions.
//! This is what turns "the pool is being used" into something a test can fail on.
//!
//! Two types split the mutable and the observable halves. [`Counters`] is the
//! live tally a pool or a registry updates as it works, crate-internal because
//! nothing outside should inflate a hit rate. [`MetricsSnapshot`] is the frozen
//! copy handed to callers: public fields, `Copy` and comparable, so a benchmark
//! reads one before, one after, and subtracts. Unlike `audit`'s footprint of a
//! single value, this measures the machinery around every value.

use crate::LIMB_BITS;

/// Bytes occupied by a single limb, for restating limb counts as bytes.
const LIMB_BYTES: u64 = (LIMB_BITS / 8) as u64;

/// The live tally kept by a pool or a registry.
///
/// A caller may read a [`MetricsSnapshot`] but never write one, so a reported
/// rate always reflects work that really happened. The tally holds a snapshot
/// rather than a parallel field set, so the two cannot drift apart.
#[derive(Debug, Clone, Default)]
pub(crate) struct Counters {
    inner: MetricsSnapshot,
}

impl Counters {
    /// A tally with every counter at zero.
    pub(crate) fn new() -> Counters {
        Counters::default()
    }

    /// Records a request served from a recycled buffer of `limbs`.
    pub(crate) fn record_pool_hit(&mut self, limbs: usize) {
        self.inner.pool_hits += 1;
        self.inner.limbs_recycled += limbs as u64;
        self.charge(limbs);
    }

    /// Records a request that had to allocate `limbs` of fresh capacity.
    pub(crate) fn record_pool_miss(&mut self, limbs: usize) {
        self.inner.pool_misses += 1;
        self.inner.limbs_allocated += limbs as u64;
        self.charge(limbs);
    }

    /// Records `limbs` coming back under the pool's control. Saturates at zero,
    /// since a buffer the pool never issued is no reason to report an absurd
    /// outstanding count.
    pub(crate) fn record_release(&mut self, limbs: usize) {
        let out = &mut self.inner.limbs_outstanding;
        *out = out.saturating_sub(limbs as u64);
    }

    /// Records a precomputation served from the registry.
    pub(crate) fn record_registry_hit(&mut self) {
        self.inner.registry_hits += 1;
    }

    /// Records a precomputation the registry had to build.
    pub(crate) fn record_registry_miss(&mut self) {
        self.inner.registry_misses += 1;
    }

    /// Adds to the outstanding total and lifts the high-water mark if needed.
    fn charge(&mut self, limbs: usize) {
        let m = &mut self.inner;
        m.limbs_outstanding += limbs as u64;
        m.peak_limbs_outstanding = m.peak_limbs_outstanding.max(m.limbs_outstanding);
    }

    /// Freezes the tally into a value the caller can keep and compare.
    pub(crate) fn snapshot(&self) -> MetricsSnapshot {
        self.inner
    }
}

/// A frozen reading of the reuse counters.
///
/// ```
/// let before = bigu::reuse::MetricsSnapshot::default();
/// assert_eq!((before.pool_hits, before.peak_limbs_outstanding), (0, 0));
/// ```
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct MetricsSnapshot {
    /// Requests served from a recycled buffer.
    pub pool_hits: u64,
    /// Requests that had to allocate.
    pub pool_misses: u64,
    /// Limbs of capacity handed out from recycled buffers.
    pub limbs_recycled: u64,
    /// Limbs of capacity handed out from fresh allocations.
    pub limbs_allocated: u64,
    /// Precomputations served from the registry.
    pub registry_hits: u64,
    /// Precomputations the registry had to build.
    pub registry_misses: u64,
    /// Limbs currently issued and not yet returned.
    pub limbs_outstanding: u64,
    /// The largest `limbs_outstanding` ever reached.
    pub peak_limbs_outstanding: u64,
}

impl MetricsSnapshot {
    /// Fraction of pool requests that avoided an allocation; a pool never asked
    /// for anything reports `0.0`, not a division by zero.
    ///
    /// ```
    /// use bigu::reuse::MetricsSnapshot as M;
    /// let m = M { pool_hits: 3, pool_misses: 1, ..Default::default() };
    /// assert_eq!(m.pool_hit_rate(), 0.75);
    /// assert_eq!(M::default().pool_hit_rate(), 0.0);
    /// ```
    pub fn pool_hit_rate(&self) -> f64 {
        ratio(self.pool_hits, self.pool_misses)
    }

    /// Fraction of registry lookups that reused an existing precomputation.
    /// ```
    /// use bigu::reuse::MetricsSnapshot as M;
    /// let m = M { registry_hits: 9, registry_misses: 1, ..M::default() };
    /// assert_eq!(m.registry_hit_rate(), 0.9);
    /// ```
    pub fn registry_hit_rate(&self) -> f64 {
        ratio(self.registry_hits, self.registry_misses)
    }

    /// Bytes of limb storage that came from the pool, not the allocator.
    /// ```
    /// use bigu::reuse::MetricsSnapshot as M;
    /// assert_eq!(M { limbs_recycled: 10, ..M::default() }.bytes_recycled(), 40);
    /// ```
    pub fn bytes_recycled(&self) -> u64 {
        self.limbs_recycled * LIMB_BYTES
    }

    /// Bytes of limb storage the allocator had to produce.
    /// ```
    /// use bigu::reuse::MetricsSnapshot as M;
    /// assert_eq!(M { limbs_allocated: 7, ..M::default() }.bytes_allocated(), 28);
    /// ```
    pub fn bytes_allocated(&self) -> u64 {
        self.limbs_allocated * LIMB_BYTES
    }
}

/// `hits / (hits + misses)`, or zero when nothing has happened yet.
fn ratio(hits: u64, misses: u64) -> f64 {
    match hits + misses {
        0 => 0.0,
        total => hits as f64 / total as f64,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn peak_tracks_the_high_water_mark_not_the_last_value() {
        let mut c = Counters::new();
        c.record_pool_miss(100);
        c.record_release(100);
        c.record_pool_miss(10);
        let s = c.snapshot();
        assert_eq!((s.limbs_outstanding, s.peak_limbs_outstanding), (10, 100));
        c.record_release(1000);
        assert_eq!(c.snapshot().limbs_outstanding, 0, "release saturates");
    }

    #[test]
    fn hits_and_misses_land_in_separate_byte_totals() {
        let mut c = Counters::new();
        c.record_pool_hit(8);
        c.record_pool_miss(4);
        let s = c.snapshot();
        assert_eq!((s.bytes_recycled(), s.bytes_allocated()), (32, 16));
        assert_eq!(s.pool_hit_rate(), 0.5);
        assert_eq!(s.registry_hit_rate(), 0.0, "an untouched rate is not NaN");

        c.record_registry_miss(); // registry traffic is tallied apart
        c.record_registry_hit();
        c.record_registry_hit();
        let s = c.snapshot();
        assert_eq!((s.registry_hits, s.pool_hits), (2, 1));
        assert!((s.registry_hit_rate() - 2.0 / 3.0).abs() < 1e-12);
    }

    #[test]
    fn a_snapshot_is_a_frozen_copy_not_a_live_view() {
        let mut c = Counters::new();
        c.record_pool_miss(32);
        let taken = c.snapshot();
        c.record_pool_miss(32);
        assert_eq!((taken.pool_misses, c.snapshot().pool_misses), (1, 2));
    }
}
