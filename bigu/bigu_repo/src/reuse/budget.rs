//! A ceiling on how much limb storage a computation may hold at once.
//!
//! Arbitrary precision means the size of a result is decided by its inputs, and
//! when the inputs are untrusted that is a denial-of-service surface with no
//! natural bound: a `pow` on a large exponent, a billion-digit parse, a CRT
//! basis over a hundred wide moduli. The parsing side already has an answer in
//! the `intake::limits` caps, which reject a text before it becomes a value.
//! This is the other half, the cap that applies once the value exists and the
//! arithmetic starts producing intermediates wider than anything supplied.
//!
//! The rule the module is built around is that a refusal must come *before* the
//! allocation. Checking a size once the buffer is live has already admitted the
//! memory the ceiling existed to exclude, and on a hostile input one allocation
//! is the whole attack, so [`Budget::charge`] is consulted first. Refusals use
//! [`Error::Overflow`], the crate's existing "does not fit" signal: a caller
//! matching on the error enum should not grow an arm because it started pooling.

use super::pool::LimbPool;
use crate::error::{Error, Result};
use crate::Limb;

/// A ceiling on outstanding limb storage, charged and released explicitly.
///
/// ```
/// use bigu::reuse::Budget;
/// let mut budget = Budget::new(100);
/// let buf = budget.checked_vec(64).unwrap();
/// assert_eq!(budget.outstanding(), 64);
/// assert!(budget.checked_vec(64).is_err(), "a second 64 would exceed 100");
/// budget.release(buf.capacity());
/// assert_eq!(budget.outstanding(), 0);
/// ```
#[derive(Debug, Clone)]
pub struct Budget {
    ceiling: usize,
    outstanding: usize,
    peak: usize,
}

impl Budget {
    /// A budget admitting at most `ceiling` limbs outstanding at once.
    /// ```
    /// let b = bigu::reuse::Budget::new(1024);
    /// assert_eq!((b.ceiling(), b.remaining()), (1024, 1024));
    /// ```
    pub fn new(ceiling: usize) -> Budget {
        Budget { ceiling, outstanding: 0, peak: 0 }
    }

    /// A budget that never refuses but still tracks the peak — how to learn what
    /// a workload needs before picking a number to enforce.
    /// ```
    /// let mut b = bigu::reuse::Budget::unlimited();
    /// b.charge(usize::MAX / 2).unwrap();
    /// assert_eq!(b.peak(), usize::MAX / 2);
    /// ```
    pub fn unlimited() -> Budget {
        Budget::new(usize::MAX)
    }

    /// The configured ceiling, in limbs.
    /// ```
    /// assert_eq!(bigu::reuse::Budget::new(42).ceiling(), 42);
    /// ```
    pub fn ceiling(&self) -> usize {
        self.ceiling
    }

    /// Limbs currently charged and not yet released.
    /// ```
    /// let mut b = bigu::reuse::Budget::new(10);
    /// b.charge(4).unwrap();
    /// assert_eq!((b.outstanding(), b.remaining()), (4, 6));
    /// ```
    pub fn outstanding(&self) -> usize {
        self.outstanding
    }

    /// How many further limbs the budget would admit right now.
    /// ```
    /// assert_eq!(bigu::reuse::Budget::new(10).remaining(), 10);
    /// ```
    pub fn remaining(&self) -> usize {
        self.ceiling - self.outstanding
    }

    /// The largest outstanding total ever reached; unlike
    /// [`Budget::outstanding`] it never falls back on release.
    /// ```
    /// let mut b = bigu::reuse::Budget::new(10);
    /// b.charge(7).unwrap();
    /// b.release(7);
    /// assert_eq!((b.peak(), b.outstanding()), (7, 0));
    /// ```
    pub fn peak(&self) -> usize {
        self.peak
    }

    /// Charges `limbs` against the ceiling, or refuses with [`Error::Overflow`].
    /// A refusal changes nothing at all, so a caller may retry with a smaller
    /// size and carry on.
    /// ```
    /// use bigu::{Error, reuse::Budget};
    /// let mut b = Budget::new(8);
    /// assert_eq!(b.charge(9), Err(Error::Overflow));
    /// assert!(b.outstanding() == 0 && b.charge(8).is_ok());
    /// ```
    pub fn charge(&mut self, limbs: usize) -> Result<()> {
        match self.outstanding.checked_add(limbs) {
            Some(next) if next <= self.ceiling => {
                self.outstanding = next;
                self.peak = self.peak.max(next);
                Ok(())
            }
            _ => Err(Error::Overflow),
        }
    }

    /// Releases `limbs` back to the budget, saturating at zero.
    /// ```
    /// let mut b = bigu::reuse::Budget::new(8);
    /// b.charge(8).unwrap();
    /// b.release(100);
    /// assert_eq!(b.outstanding(), 0);
    /// ```
    pub fn release(&mut self, limbs: usize) {
        self.outstanding = self.outstanding.saturating_sub(limbs);
    }

    /// Allocates a buffer of `limbs` capacity, refusing before the allocation
    /// rather than after it.
    /// ```
    /// let mut b = bigu::reuse::Budget::new(16);
    /// assert!(b.checked_vec(1 << 40).is_err(), "refused, never allocated");
    /// assert!(b.checked_vec(16).unwrap().capacity() >= 16);
    /// ```
    pub fn checked_vec(&mut self, limbs: usize) -> Result<Vec<Limb>> {
        self.charge(limbs)?;
        Ok(Vec::with_capacity(limbs))
    }

    /// Draws a buffer of at least `limbs` from `pool`, refusing first. A pool hit
    /// costs no new memory but does put limbs back in the caller's hands, so it
    /// is charged alike: the ceiling bounds what is *outstanding*.
    /// ```
    /// use bigu::reuse::{Budget, LimbPool};
    /// let (mut pool, mut budget) = (LimbPool::new(), Budget::new(32));
    /// let buf = budget.checked_take(&mut pool, 8).unwrap();
    /// budget.release(buf.capacity());
    /// pool.recycle(buf);
    /// ```
    pub fn checked_take(&mut self, pool: &mut LimbPool, limbs: usize) -> Result<Vec<Limb>> {
        self.charge(limbs)?;
        Ok(pool.take(limbs))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_refusal_leaves_the_budget_exactly_as_it_was() {
        let mut budget = Budget::new(10);
        budget.charge(6).unwrap();
        assert_eq!(budget.charge(5), Err(Error::Overflow));
        assert_eq!((budget.outstanding(), budget.remaining()), (6, 4));
        assert!(budget.charge(4).is_ok(), "the ceiling is inclusive");
        assert_eq!(budget.charge(1), Err(Error::Overflow));
    }

    #[test]
    fn absurd_and_empty_requests_are_both_handled() {
        let mut budget = Budget::new(usize::MAX);
        budget.charge(usize::MAX - 1).unwrap();
        assert_eq!(budget.charge(usize::MAX), Err(Error::Overflow));
        assert_eq!(budget.outstanding(), usize::MAX - 1);
        let mut zero = Budget::new(0);
        assert!(zero.charge(0).is_ok() && zero.checked_vec(0).is_ok());
        assert_eq!((zero.charge(1), zero.ceiling()), (Err(Error::Overflow), 0));
    }

    #[test]
    fn a_pool_hit_is_charged_like_a_fresh_buffer_and_peak_survives_release() {
        let (mut pool, mut budget) = (LimbPool::new(), Budget::new(16));
        let first = budget.checked_take(&mut pool, 16).unwrap();
        budget.release(first.capacity());
        pool.recycle(first);
        assert_eq!((budget.outstanding(), budget.peak()), (0, 16));
        let second = budget.checked_take(&mut pool, 16).unwrap();
        assert_eq!(pool.metrics().pool_hits, 1);
        assert_eq!(budget.checked_take(&mut pool, 1), Err(Error::Overflow));
        drop(second);
    }
}
