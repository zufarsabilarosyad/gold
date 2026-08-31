//! In-place replacement of a value's contents, reusing what it already owns.
//!
//! `*dst = src.clone()` is two allocator events: the clone takes new memory and
//! the assignment drops whatever `dst` was holding. In a loop where `dst` is the
//! accumulator — a running product, a Horner fold, a modular ladder — that
//! repeats on every iteration even though the destination's buffer was already
//! the right size. Writing through the existing allocation turns both events
//! into a copy.
//!
//! Doing that means reaching past [`BigU`]'s public surface into its limb
//! vector, which is exactly where the canonical form can be broken: a limb
//! vector with a trailing zero is a `BigU` that compares unequal to itself
//! written the ordinary way, and `bit_len`, `Ord` and every formatting trait
//! read the top limb directly. So every entry point here re-runs `normalize`
//! before the value escapes. There is no path through this module that leaves a
//! caller holding a non-canonical value, which is what makes it safe to expose
//! the moves at all.
//!
//! [`take_limbs`] and [`put_limbs`] are the two halves of the exchange with a
//! [`LimbPool`](super::LimbPool): pull a value's buffer out to work on it, push
//! a finished buffer back in and receive the old one for recycling. Neither
//! copies a limb.

use crate::bigu::BigU;
use crate::Limb;

/// Replaces `dst` with the value of `src`, reusing `dst`'s allocation when it is
/// already large enough. Self-assignment is a no-op, not a corruption.
///
/// ```
/// use bigu::{BigU, reuse::assign::assign_from};
///
/// let mut dst = BigU::from(u128::MAX);
/// let cap = dst.limb_capacity();
/// assign_from(&mut dst, &BigU::from(7u32));
/// assert_eq!(dst, BigU::from(7u32));
/// assert_eq!(dst.limb_capacity(), cap, "the buffer was reused, not replaced");
/// ```
pub fn assign_from(dst: &mut BigU, src: &BigU) {
    if dst.limbs == src.limbs {
        return;
    }
    dst.limbs.clear();
    dst.limbs.extend_from_slice(&src.limbs);
    dst.normalize();
}

/// Replaces `dst` with the little-endian limbs of `slice`, reusing `dst`'s
/// allocation. Trailing zero limbs are stripped, so a caller may hand over a
/// padded working buffer without thinking about it.
///
/// ```
/// use bigu::{BigU, reuse::assign::assign_from_limbs};
///
/// let mut dst = BigU::zero();
/// assign_from_limbs(&mut dst, &[5, 0, 0]);
/// assert_eq!(dst, BigU::from(5u32));
/// ```
pub fn assign_from_limbs(dst: &mut BigU, slice: &[Limb]) {
    dst.limbs.clear();
    dst.limbs.extend_from_slice(slice);
    dst.normalize();
}

/// Sets `dst` to zero without releasing its buffer. The canonical form of zero
/// is the empty limb vector, so this is a truncation and the capacity survives
/// for the next value written into it.
///
/// ```
/// use bigu::{BigU, reuse::assign::assign_zero};
///
/// let mut dst = BigU::from(u64::MAX);
/// let cap = dst.limb_capacity();
/// assign_zero(&mut dst);
/// assert!(dst.is_zero() && dst.limb_capacity() == cap);
/// ```
pub fn assign_zero(dst: &mut BigU) {
    dst.limbs.clear();
}

/// Moves the limb buffer out of `value`, leaving it zero.
///
/// The returned vector is canonical, so it may be inspected as well as
/// overwritten. Pair it with [`put_limbs`] or hand it straight to a pool.
///
/// ```
/// use bigu::{BigU, reuse::assign::take_limbs};
///
/// let mut v = BigU::from(0x1234_5678u32);
/// assert_eq!(take_limbs(&mut v), vec![0x1234_5678u32]);
/// assert!(v.is_zero());
/// ```
pub fn take_limbs(value: &mut BigU) -> Vec<Limb> {
    core::mem::take(&mut value.limbs)
}

/// Installs `limbs` as the contents of `value` and hands back the buffer it was
/// using, cleared and ready for a pool.
///
/// The incoming limbs are canonicalized on the way in, so a working buffer with
/// its top columns still zeroed can be installed directly.
///
/// ```
/// use bigu::{BigU, reuse::{assign::put_limbs, LimbPool}};
///
/// let mut pool = LimbPool::new();
/// let mut v = BigU::from(1u32);
/// let old = put_limbs(&mut v, vec![9, 0]);
/// assert_eq!(v, BigU::from(9u32));
/// assert!(old.is_empty());
/// pool.recycle(old);
/// ```
pub fn put_limbs(value: &mut BigU, limbs: Vec<Limb>) -> Vec<Limb> {
    let mut old = core::mem::replace(&mut value.limbs, limbs);
    value.normalize();
    old.clear();
    old
}

impl BigU {
    /// Limb capacity of the value's buffer, which is at least its limb count.
    ///
    /// Exposed so a caller can tell reuse from reallocation; it says nothing
    /// about the value itself.
    ///
    /// ```
    /// use bigu::BigU;
    ///
    /// assert!(BigU::from(u128::MAX).limb_capacity() >= 4);
    /// assert_eq!(BigU::zero().limb_capacity(), 0);
    /// ```
    pub fn limb_capacity(&self) -> usize {
        self.limbs.capacity()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::reuse::LimbPool;

    #[test]
    fn assignment_never_leaves_a_trailing_zero_limb() {
        let mut dst = BigU::from(1u32);
        assign_from_limbs(&mut dst, &[0, 0, 0]);
        assert!(dst.is_zero() && dst.limbs.is_empty());
        assert_eq!(dst, BigU::zero());
        assign_from_limbs(&mut dst, &[1, 0]);
        assert_eq!(dst.limbs, vec![1 as Limb]);
    }

    #[test]
    fn assign_from_reuses_the_destination_buffer() {
        let mut dst = BigU::from(u128::MAX);
        let cap = dst.limb_capacity();
        for n in 0..50u32 {
            assign_from(&mut dst, &BigU::from(n));
            assert_eq!(dst, BigU::from(n));
        }
        assert_eq!(cap, dst.limb_capacity(), "no reallocation should happen");
        let copy = dst.clone();
        assign_from(&mut dst, &copy);
        assert_eq!(dst, copy, "self-assignment is a no-op");
    }

    #[test]
    fn assign_zero_keeps_capacity_and_the_canonical_empty_form() {
        let mut dst = BigU::from(u128::MAX);
        let cap = dst.limb_capacity();
        assign_zero(&mut dst);
        assert_eq!((dst.bit_len(), dst.limb_capacity()), (0, cap));
        assert_eq!(dst, BigU::zero());
    }

    #[test]
    fn take_leaves_a_usable_zero_behind() {
        let mut v = BigU::from(u64::MAX);
        let limbs = take_limbs(&mut v);
        assert_eq!(limbs.len(), 2);
        assert!(v.is_zero());
        // The emptied value still behaves like an ordinary zero.
        assert_eq!(&v + &BigU::one(), BigU::one());
    }

    #[test]
    fn put_canonicalizes_a_padded_buffer_and_round_trips_through_a_pool() {
        let mut pool = LimbPool::new();
        let mut v = BigU::one();
        let old = put_limbs(&mut v, vec![7, 0, 0, 0]);
        assert_eq!(v, BigU::from(7u32));
        assert_eq!(v.limbs.len(), 1);
        assert!(old.is_empty(), "the returned buffer must be pool-ready");

        let limbs = take_limbs(&mut v);
        pool.recycle(put_limbs(&mut v, limbs));
        assert_eq!(v, BigU::from(7u32));
    }
}
