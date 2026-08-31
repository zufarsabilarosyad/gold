//! A recycler for limb buffers.
//!
//! Every routine in `mul.rs`, `div.rs` and `radix.rs` builds its answer into a
//! fresh `Vec<Limb>` and lets it go when the operation ends. That is right for a
//! value type and wrong for a *long* computation, where the same shapes are
//! allocated and freed thousands of times: a Karatsuba recursion, a division
//! loop, a divide-and-conquer render. A pool lets those callers draw a buffer,
//! use it and hand it back, one round of allocator traffic instead of one per
//! call.
//!
//! Buffers are filed by capacity class, not exact size, because exact sizes
//! never repeat and powers of two always do. A request for `n` limbs is served
//! from the bucket for `2^ceil(log2 n)`, and every buffer filed there holds at
//! least that much — the size guarantee is structural rather than checked. A
//! miss allocates at the same rounded size, so the buffer files itself back into
//! the bucket it came from. Retention is capped per bucket: uncapped, one
//! enormous transient would pin its capacity for the process's whole life.

use super::metrics::{Counters, MetricsSnapshot};
use crate::Limb;

/// Buffers retained per capacity class before further returns are dropped.
pub const DEFAULT_BUCKET_DEPTH: usize = 8;

/// One bucket per representable capacity class, plus the class for zero.
const BUCKET_COUNT: usize = usize::BITS as usize + 1;

/// The bucket a request for `n` limbs is served from: `ceil(log2 n)`, with 0
/// and 1 sharing the smallest class.
fn request_bucket(n: usize) -> usize {
    (usize::BITS - n.saturating_sub(1).leading_zeros()) as usize
}

/// The bucket a buffer of `cap` limbs is filed in: `floor(log2 cap)`.
fn capacity_bucket(cap: usize) -> usize {
    (usize::BITS - 1 - cap.leading_zeros()) as usize
}

/// A recycler handing out cleared limb buffers of at least a requested size.
///
/// ```
/// let mut pool = bigu::reuse::LimbPool::new();
/// let buf = pool.take(10);
/// assert!(buf.is_empty() && buf.capacity() >= 10);
/// pool.recycle(buf);
/// pool.take(10); // the second request for the class is free
/// assert_eq!(pool.metrics().pool_hits, 1);
/// ```
#[derive(Debug)]
pub struct LimbPool {
    buckets: Vec<Vec<Vec<Limb>>>,
    depth: usize,
    counters: Counters,
}

impl LimbPool {
    /// A pool retaining [`DEFAULT_BUCKET_DEPTH`] buffers per capacity class.
    ///
    /// ```
    /// assert_eq!(bigu::reuse::LimbPool::new().stored_buffers(), 0);
    /// ```
    pub fn new() -> LimbPool {
        LimbPool::bounded(DEFAULT_BUCKET_DEPTH)
    }

    /// A pool retaining at most `depth` buffers per capacity class. Depth zero
    /// counts traffic without retaining anything: the baseline to measure
    /// against.
    ///
    /// ```
    /// let mut pool = bigu::reuse::LimbPool::bounded(0);
    /// let buf = pool.take(4);
    /// pool.recycle(buf);
    /// assert_eq!(pool.stored_buffers(), 0);
    /// ```
    pub fn bounded(depth: usize) -> LimbPool {
        let mut buckets = Vec::with_capacity(BUCKET_COUNT);
        buckets.resize_with(BUCKET_COUNT, Vec::new);
        LimbPool { buckets, depth, counters: Counters::new() }
    }

    /// Hands out an empty buffer with room for at least `n` limbs; only the
    /// capacity is reused, never the contents.
    ///
    /// ```
    /// let buf = bigu::reuse::LimbPool::new().take(1000);
    /// assert!(buf.is_empty() && buf.capacity() >= 1000);
    /// ```
    pub fn take(&mut self, n: usize) -> Vec<Limb> {
        let bucket = request_bucket(n);
        if let Some(mut buf) = self.buckets[bucket].pop() {
            buf.clear();
            self.counters.record_pool_hit(buf.capacity());
            return buf;
        }
        // Allocate at the class size so the buffer files itself back here.
        let rounded = 1usize.checked_shl(bucket as u32).unwrap_or(n).max(n);
        let buf = Vec::with_capacity(rounded);
        self.counters.record_pool_miss(buf.capacity());
        buf
    }

    /// Hands out exactly `n` zeroed limbs — the shape schoolbook multiplication
    /// wants, an accumulator it indexes into rather than pushes onto.
    ///
    /// ```
    /// assert_eq!(bigu::reuse::LimbPool::new().take_zeroed(3), vec![0u32, 0, 0]);
    /// ```
    pub fn take_zeroed(&mut self, n: usize) -> Vec<Limb> {
        let mut buf = self.take(n);
        buf.resize(n, 0);
        buf
    }

    /// Files a buffer by capacity for a later request. One arriving at a full
    /// bucket, or with no capacity at all, is dropped.
    ///
    /// ```
    /// let mut pool = bigu::reuse::LimbPool::bounded(1);
    /// let (a, b) = (pool.take(8), pool.take(8));
    /// pool.recycle(a);
    /// pool.recycle(b); // bucket already full
    /// assert_eq!(pool.stored_buffers(), 1);
    /// ```
    pub fn recycle(&mut self, buf: Vec<Limb>) {
        let cap = buf.capacity();
        if cap == 0 {
            return;
        }
        self.counters.record_release(cap);
        let bucket = capacity_bucket(cap);
        if self.buckets[bucket].len() < self.depth {
            self.buckets[bucket].push(buf);
        }
    }

    /// How many buffers the pool is currently holding.
    ///
    /// ```
    /// let mut pool = bigu::reuse::LimbPool::new();
    /// let buf = pool.take(2);
    /// pool.recycle(buf);
    /// assert_eq!(pool.stored_buffers(), 1);
    /// ```
    pub fn stored_buffers(&self) -> usize {
        self.buckets.iter().map(Vec::len).sum()
    }

    /// A frozen reading of this pool's counters.
    ///
    /// ```
    /// assert_eq!(bigu::reuse::LimbPool::new().metrics().pool_hits, 0);
    /// ```
    pub fn metrics(&self) -> MetricsSnapshot {
        self.counters.snapshot()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_recycled_buffer_is_handed_back_cleared() {
        let mut pool = LimbPool::new();
        let mut buf = pool.take(4);
        buf.extend_from_slice(&[1, 2, 3, 4]);
        pool.recycle(buf);
        assert!(pool.take(4).is_empty(), "stale limbs must not be observable");
        assert_eq!(pool.take_zeroed(2), vec![0 as Limb, 0]);
    }

    #[test]
    fn a_hit_always_satisfies_the_requested_size() {
        for n in 1..=1024usize {
            let b = request_bucket(n);
            assert!(1usize << b >= n && capacity_bucket(1usize << b) == b);
        }
        // A buffer filed from a request for 5 sits in the class for 8.
        let mut pool = LimbPool::new();
        assert_eq!(pool.take(0).len(), 0, "a zero request is still serviceable");
        let five = pool.take(5);
        assert!(five.capacity() >= 8);
        pool.recycle(five);
        let eight = pool.take(8);
        assert_eq!(pool.metrics().pool_hits, 1);
        pool.recycle(eight);
        assert!(pool.take(9).capacity() >= 9);
        assert_eq!(pool.metrics().pool_hits, 1, "9 cannot draw from the 8 class");
    }

    #[test]
    fn depth_bounds_retention_so_a_transient_cannot_pin_memory() {
        let mut pool = LimbPool::bounded(2);
        let bufs: Vec<_> = (0..5).map(|_| pool.take(64)).collect();
        bufs.into_iter().for_each(|b| pool.recycle(b));
        assert_eq!(pool.stored_buffers(), 2);
        assert!(pool.metrics().peak_limbs_outstanding >= 320);
    }
}
