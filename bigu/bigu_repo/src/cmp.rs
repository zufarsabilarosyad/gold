//! Magnitude comparison for [`BigU`].
//!
//! Because the representation is canonical, comparison is a two-step process:
//! the value with more limbs is larger, and on a tie the most-significant limbs
//! are compared downward. The internal [`cmp_limbs`] helper is shared with
//! subtraction and division so they can decide ordering without allocating.

use core::cmp::Ordering;

use crate::bigu::BigU;
use crate::Limb;

/// Compares two little-endian limb slices as magnitudes.
///
/// Both slices are assumed canonical (no trailing zero limbs), which lets the
/// length be used as the primary key.
pub(crate) fn cmp_limbs(a: &[Limb], b: &[Limb]) -> Ordering {
    match a.len().cmp(&b.len()) {
        Ordering::Equal => {
            for (x, y) in a.iter().rev().zip(b.iter().rev()) {
                match x.cmp(y) {
                    Ordering::Equal => continue,
                    other => return other,
                }
            }
            Ordering::Equal
        }
        other => other,
    }
}

impl PartialEq for BigU {
    fn eq(&self, other: &Self) -> bool {
        self.limbs == other.limbs
    }
}

impl Eq for BigU {}

impl PartialOrd for BigU {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for BigU {
    fn cmp(&self, other: &Self) -> Ordering {
        cmp_limbs(&self.limbs, &other.limbs)
    }
}

impl core::hash::Hash for BigU {
    fn hash<H: core::hash::Hasher>(&self, state: &mut H) {
        self.limbs.hash(state);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    #[test]
    fn equality_is_value_based() {
        assert_eq!(BigU::from(0u32), BigU::zero());
        assert_eq!(BigU::from(7u32), BigU::from(7u64));
        assert_ne!(BigU::from(7u32), BigU::from(8u32));
    }

    #[test]
    fn ordering_by_length_then_limbs() {
        assert!(BigU::from(0u32) < BigU::from(1u32));
        assert!(BigU::from(u64::MAX) > BigU::from(u32::MAX));
        assert!(BigU::from(0x1_0000_0000u64) > BigU::from(0xFFFF_FFFFu32));
        assert!(BigU::from(100u32) > BigU::from(99u32));
        assert_eq!(BigU::from(5u32).cmp(&BigU::from(5u32)), Ordering::Equal);
    }

    #[test]
    fn cmp_limbs_handles_ties() {
        assert_eq!(cmp_limbs(&[1, 2, 3], &[1, 2, 3]), Ordering::Equal);
        assert_eq!(cmp_limbs(&[9, 2, 3], &[1, 2, 3]), Ordering::Greater);
        assert_eq!(cmp_limbs(&[1, 2, 3], &[1, 2, 9]), Ordering::Less);
        assert_eq!(cmp_limbs(&[1, 2], &[1, 2, 3]), Ordering::Less);
    }

    #[test]
    fn equal_values_hash_equal() {
        let mut set = HashSet::new();
        set.insert(BigU::from(42u32));
        assert!(set.contains(&BigU::from(42u64)));
        assert!(!set.contains(&BigU::from(43u32)));
    }
}
