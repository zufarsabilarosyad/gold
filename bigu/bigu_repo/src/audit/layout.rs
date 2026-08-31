//! The sanctioned window into a [`BigU`]'s private limb vector.
//!
//! Every other module in this directory needs to look at limbs: the invariant
//! checker asks whether the top one is zero, the dump prints them, the delta
//! walks them in parallel. If each did that by reaching into the field
//! directly, the private representation would have six users instead of one and
//! changing it would mean editing six files. So the reach-through happens
//! exactly here, and the rest of the subsystem is written against these
//! functions.
//!
//! The vocabulary is fixed by the storage: limbs are little-endian, index `0`
//! is the least significant, and limb `i` covers bit positions
//! `[i * 32, i * 32 + 32)` of the value. Bit indices are `u64` because a value
//! may hold far more bits than a `u32` can count; limb indices are `usize`
//! because they index a vector.

use crate::bigu::BigU;
use crate::LIMB_BITS;

/// Borrows the little-endian limb slice backing `v`.
///
/// The slice is canonical for any value the crate produced: it is empty for
/// zero and its last element is nonzero otherwise.
///
/// ```
/// use bigu::{audit::layout, BigU};
/// assert_eq!(layout::limbs(&BigU::from(1u64 << 32)), &[0u32, 1][..]);
/// assert!(layout::limbs(&BigU::zero()).is_empty());
/// ```
pub fn limbs(v: &BigU) -> &[u32] {
    &v.limbs
}

/// How many limbs `v` occupies. Zero occupies none.
///
/// ```
/// use bigu::{audit::layout, BigU};
/// assert_eq!(layout::limb_count(&BigU::from(u32::MAX)), 1);
/// assert_eq!(layout::limb_count(&BigU::from(u64::MAX)), 2);
/// assert_eq!(layout::limb_count(&BigU::zero()), 0);
/// ```
pub fn limb_count(v: &BigU) -> usize {
    v.limbs.len()
}

/// The most-significant limb, or `None` for zero.
///
/// ```
/// use bigu::{audit::layout, BigU};
/// assert_eq!(layout::top_limb(&BigU::from(0x2_0000_0001u64)), Some(2));
/// assert_eq!(layout::top_limb(&BigU::zero()), None);
/// ```
pub fn top_limb(v: &BigU) -> Option<u32> {
    v.limbs.last().copied()
}

/// The least-significant limb, or `None` for zero.
///
/// ```
/// use bigu::{audit::layout, BigU};
/// assert_eq!(layout::least_limb(&BigU::from(0x2_0000_0001u64)), Some(1));
/// assert_eq!(layout::least_limb(&BigU::zero()), None);
/// ```
pub fn least_limb(v: &BigU) -> Option<u32> {
    v.limbs.first().copied()
}

/// Walks the limbs from least to most significant, pairing each with its index.
///
/// ```
/// use bigu::{audit::layout, BigU};
/// let seen: Vec<(usize, u32)> = layout::limbs_low_to_high(&BigU::from(0x2_0000_0001u64)).collect();
/// assert_eq!(seen, vec![(0, 1), (1, 2)]);
/// ```
pub fn limbs_low_to_high(v: &BigU) -> impl Iterator<Item = (usize, u32)> + '_ {
    v.limbs.iter().copied().enumerate()
}

/// Walks the limbs from most to least significant, pairing each with its index.
///
/// The indices still refer to the little-endian positions, so they count down.
/// This is the order a dump prints in, because it reads like a written number.
///
/// ```
/// use bigu::{audit::layout, BigU};
/// let seen: Vec<(usize, u32)> = layout::limbs_high_to_low(&BigU::from(0x2_0000_0001u64)).collect();
/// assert_eq!(seen, vec![(1, 2), (0, 1)]);
/// ```
pub fn limbs_high_to_low(v: &BigU) -> impl Iterator<Item = (usize, u32)> + '_ {
    v.limbs.iter().copied().enumerate().rev()
}

/// Splits a bit position into its limb index and its offset inside that limb.
///
/// ```
/// use bigu::audit::layout;
/// assert_eq!(layout::split_bit(0), (0, 0));
/// assert_eq!(layout::split_bit(31), (0, 31));
/// assert_eq!(layout::split_bit(32), (1, 0));
/// assert_eq!(layout::split_bit(70), (2, 6));
/// ```
pub fn split_bit(bit: u64) -> (usize, u32) {
    (
        (bit / LIMB_BITS as u64) as usize,
        (bit % LIMB_BITS as u64) as u32,
    )
}

/// Rebuilds a bit position from a limb index and an in-limb offset, the inverse
/// of [`split_bit`].
///
/// ```
/// use bigu::audit::layout;
/// assert_eq!(layout::join_bit(2, 6), 70);
/// assert_eq!(layout::join_bit(0, 0), 0);
/// ```
pub fn join_bit(limb: usize, offset: u32) -> u64 {
    limb as u64 * LIMB_BITS as u64 + offset as u64
}

/// The half-open bit range `[low, high)` that limb `index` covers.
///
/// ```
/// use bigu::audit::layout;
/// assert_eq!(layout::limb_bit_range(0), (0, 32));
/// assert_eq!(layout::limb_bit_range(3), (96, 128));
/// ```
pub fn limb_bit_range(index: usize) -> (u64, u64) {
    let low = index as u64 * LIMB_BITS as u64;
    (low, low + LIMB_BITS as u64)
}

/// How many limbs a value of `bits` bits needs: `ceil(bits / 32)`.
///
/// ```
/// use bigu::audit::layout;
/// assert_eq!(layout::limbs_for_bits(0), 0);
/// assert_eq!(layout::limbs_for_bits(1), 1);
/// assert_eq!(layout::limbs_for_bits(32), 1);
/// assert_eq!(layout::limbs_for_bits(33), 2);
/// ```
pub fn limbs_for_bits(bits: u64) -> usize {
    ((bits + LIMB_BITS as u64 - 1) / LIMB_BITS as u64) as usize
}

/// Checks that the limb count and [`BigU::bit_len`] tell the same story.
///
/// The two are independent readings of the same fact — one counts vector
/// elements, the other counts significant bits — so they can only disagree if
/// the value carries a zero top limb. That makes this the cheapest structural
/// test the subsystem has, and [`crate::audit::invariant`] reports it rather
/// than asserting it.
///
/// ```
/// use bigu::{audit::layout, BigU};
/// assert!(layout::bit_len_agrees(&BigU::zero()));
/// assert!(layout::bit_len_agrees(&BigU::from(u64::MAX)));
/// ```
pub fn bit_len_agrees(v: &BigU) -> bool {
    limbs_for_bits(v.bit_len()) == v.limbs.len()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zero_has_no_limbs_and_no_ends() {
        let z = BigU::zero();
        assert!(limbs(&z).is_empty());
        assert_eq!(limb_count(&z), 0);
        assert_eq!(top_limb(&z), None);
        assert_eq!(least_limb(&z), None);
        assert_eq!(limbs_low_to_high(&z).count(), 0);
        assert_eq!(limbs_high_to_low(&z).count(), 0);
    }

    #[test]
    fn single_limb_is_both_ends() {
        let v = BigU::from(7u32);
        assert_eq!(top_limb(&v), Some(7));
        assert_eq!(least_limb(&v), Some(7));
    }

    #[test]
    fn iteration_orders_are_mirror_images() {
        let v = BigU::from(1u32) << 100;
        let up: Vec<_> = limbs_low_to_high(&v).collect();
        let mut down: Vec<_> = limbs_high_to_low(&v).collect();
        down.reverse();
        assert_eq!(up, down);
        assert_eq!(up.len(), 4);
    }

    #[test]
    fn split_and_join_round_trip() {
        for bit in [0u64, 1, 31, 32, 63, 64, 1000, 4_294_967_296] {
            let (limb, offset) = split_bit(bit);
            assert!(offset < LIMB_BITS);
            assert_eq!(join_bit(limb, offset), bit);
            let (low, high) = limb_bit_range(limb);
            assert!(bit >= low && bit < high);
        }
    }

    #[test]
    fn bit_len_agrees_on_every_boundary() {
        assert!(bit_len_agrees(&BigU::zero()));
        for shift in [0u32, 31, 32, 33, 63, 64, 127] {
            let v = BigU::from(1u32) << shift;
            assert!(bit_len_agrees(&v), "shift {shift}");
            assert_eq!(limb_count(&v), limbs_for_bits(v.bit_len()));
        }
    }

    #[test]
    fn bit_len_disagrees_on_a_padded_value() {
        // Only reachable by bypassing the normalizing constructors, which is
        // exactly the corruption this check exists to name.
        let padded = BigU { limbs: vec![1, 0] };
        // The zero top limb is still counted, so the bit length overstates the
        // value by a whole limb while the vector overstates it by one element.
        assert_eq!(padded.bit_len(), 32);
        assert_eq!(limbs_for_bits(padded.bit_len()), 1);
        assert!(!bit_len_agrees(&padded));
    }
}
