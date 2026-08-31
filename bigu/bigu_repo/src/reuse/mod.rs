//! Allocation and precomputation lifecycle for the arithmetic core.
//!
//! Nothing in this subsystem changes a result. That is the charter, and it is
//! worth stating flatly because every module below touches memory that a value
//! is made of: identical answers, different cost. A computation run with a pool,
//! a registry and a budget produces exactly what the same computation produces
//! without them, and any divergence is a bug in here rather than a tuning
//! choice.
//!
//! It exists because the arithmetic core is written in the style that suits a
//! value type and not the style that suits a long computation. Every routine in
//! `mul.rs`, `div.rs` and `radix.rs` builds its answer into a fresh
//! `Vec<Limb>` and drops it when the operation ends, so a Karatsuba recursion
//! or a divide-and-conquer render generates allocator traffic proportional to
//! the number of operations rather than to the size of the problem. And
//! [`ModRing::new`](crate::ModRing::new) redoes the Montgomery or Barrett setup
//! on every call, so a loop over [`BigU::modpow_fast`](crate::BigU::modpow_fast)
//! with one modulus pays for the precomputation once per exponentiation instead
//! of once.
//!
//! The pieces layer:
//!
//! * [`pool`] is the floor. It recycles limb buffers in capacity classes and
//!   knows nothing about big integers.
//! * [`scratch`] sits directly on the pool and makes the return happen. A
//!   [`Scratch`] hands its buffer back in `Drop`, so early returns and the `?`
//!   operator cannot leak one — which matters because the crate is
//!   `#![forbid(unsafe_code)]` and a hand-written guard was never an option.
//! * [`capacity`] and [`assign`] sit above both. The first decides how large a
//!   buffer should be before anything is written into it; the second writes a
//!   new value through an existing allocation, re-canonicalizing on every exit
//!   so the no-trailing-zero-limb invariant cannot be observed broken.
//! * [`registry`] and [`budget`] stand beside that stack rather than on it. One
//!   caches whole precomputed objects, the other caps how much storage may be
//!   outstanding at once.
//! * [`metrics`] observes all of it, so "the pool is being used" is a claim a
//!   test can fail on.
//!
//! # Example
//!
//! ```
//! use bigu::BigU;
//! use bigu::reuse::{with_scratch, Budget, LimbPool, Registry};
//!
//! let mut pool = LimbPool::new();
//! let mut registry = Registry::new();
//! let mut budget = Budget::new(4096);
//!
//! // Working buffers come from the pool and go back to it.
//! for _ in 0..100 {
//!     with_scratch(&mut pool, 64, |buf| buf.resize(64, 0));
//! }
//! assert_eq!(pool.metrics().pool_misses, 1);
//! assert_eq!(pool.metrics().pool_hits, 99);
//!
//! // The Montgomery setup for this modulus is paid for once.
//! let modulus = BigU::from(1_000_000_007u32);
//! let mut acc = BigU::one();
//! for e in 1..10u32 {
//!     acc = registry.ring(&modulus).unwrap().pow(&BigU::from(3u32), &BigU::from(e));
//! }
//! assert_eq!(registry.rings_cached(), 1);
//! assert_eq!(acc, BigU::from(3u32).modpow_fast(&BigU::from(9u32), &modulus).unwrap());
//!
//! // And nothing oversized gets past the ceiling.
//! assert!(budget.checked_take(&mut pool, 1 << 20).is_err());
//! ```

pub mod assign;
pub mod budget;
pub mod capacity;
pub mod metrics;
pub mod pool;
pub mod registry;
pub mod scratch;

pub use crate::reuse::budget::Budget;
pub use crate::reuse::metrics::MetricsSnapshot;
pub use crate::reuse::pool::LimbPool;
pub use crate::reuse::registry::Registry;
pub use crate::reuse::scratch::{with_scratch, Scratch};

#[cfg(test)]
mod tests {
    use super::assign::{assign_from, assign_from_limbs, take_limbs};
    use super::capacity::{product_hint, sum_hint};
    use super::*;
    use crate::bigu::BigU;

    #[test]
    fn the_pooled_path_and_the_plain_path_agree() {
        // The charter, tested: routing a multiplication's working buffer
        // through the pool must not move a single bit of the answer.
        let a = BigU::from(u128::MAX);
        let b = BigU::from(0xDEAD_BEEF_CAFE_F00Du64);
        let plain = &a * &b;

        let mut pool = LimbPool::new();
        let mut pooled = BigU::zero();
        let hint = product_hint(a.limbs.len(), b.limbs.len());
        with_scratch(&mut pool, hint, |scratch| {
            scratch.extend_from_slice(&(&a * &b).limbs);
            // Padding the working buffer must not survive into the value.
            scratch.push(0);
            assign_from_limbs(&mut pooled, scratch);
        });

        assert_eq!(plain, pooled);
        assert_eq!(pooled.limbs.last(), plain.limbs.last());
        assert_eq!(pool.stored_buffers(), 1, "the working buffer came back");
    }

    #[test]
    fn an_accumulator_loop_allocates_once() {
        // Repeatedly overwriting one value through `assign_from` must not grow
        // its buffer, which is the whole reason the module exists.
        let mut acc = BigU::from(u128::MAX);
        let cap = acc.limb_capacity();
        for n in 0..200u32 {
            assign_from(&mut acc, &BigU::from(n));
        }
        assert_eq!(acc, BigU::from(199u32));
        assert_eq!(acc.limb_capacity(), cap);
    }

    #[test]
    fn every_layer_reports_its_own_snapshot() {
        let mut pool = LimbPool::new();
        let mut registry = Registry::new();
        let modulus = BigU::from(97u32);

        for _ in 0..4 {
            with_scratch(&mut pool, sum_hint(3, 3), |b| b.push(1));
            registry.ring(&modulus).unwrap();
        }

        let (p, r) = (pool.metrics(), registry.metrics());
        assert_eq!((p.pool_hits, p.pool_misses), (3, 1));
        assert_eq!((r.registry_hits, r.registry_misses), (3, 1));
        assert_eq!(p.pool_hit_rate(), r.registry_hit_rate());
    }

    #[test]
    fn a_budget_refusal_stops_before_the_pool_is_touched() {
        let mut pool = LimbPool::new();
        let mut budget = Budget::new(16);
        assert!(budget.checked_take(&mut pool, 1024).is_err());
        assert_eq!(
            pool.metrics().pool_misses,
            0,
            "the pool must never see a request the budget refused"
        );
    }

    #[test]
    fn a_value_emptied_by_take_is_still_an_ordinary_zero() {
        let mut pool = LimbPool::new();
        let mut v = BigU::from(u64::MAX);
        let limbs = take_limbs(&mut v);
        assert!(v.is_zero());
        assert_eq!(&v * &BigU::from(5u32), BigU::zero());
        assert_eq!(v.to_str_radix(10).unwrap(), "0");
        pool.recycle(limbs);
        assert_eq!(pool.stored_buffers(), 1);
    }
}
