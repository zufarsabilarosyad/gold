//! Structural comparison: not *which* value is larger, but *where* they differ.
//!
//! [`crate::cmp`] decides an inequality and stops at the first limb that settles
//! it. That is the right answer for `<` and the wrong one for a failing test,
//! where the useful facts are how far the two agree, how much of the difference
//! there is, and whether it is confined to the low end — the signature of a
//! truncation or a lost carry — or spread across the whole value, the signature
//! of a wrong operand.
//!
//! The difference set is exactly the XOR of the two magnitudes, so every
//! question here reduces to one already-implemented operation plus a read
//! through [`crate::audit::layout`]. The XOR is scratch work: it never leaves
//! the module.

use crate::audit::layout;
use crate::bigu::BigU;

/// The index of the lowest limb at which `a` and `b` differ, or `None` when
/// they are equal.
///
/// The shorter value is treated as padded with zero limbs, which is what makes
/// a length difference report as a differing limb rather than as no answer.
///
/// ```
/// use bigu::{audit::delta, BigU};
/// assert_eq!(delta::first_differing_limb(&BigU::from(7u32), &BigU::from(7u32)), None);
/// assert_eq!(delta::first_differing_limb(&BigU::from(7u32), &BigU::from(8u32)), Some(0));
/// assert_eq!(delta::first_differing_limb(&BigU::from(1u32), &BigU::from(0x1_0000_0001u64)), Some(1));
/// ```
pub fn first_differing_limb(a: &BigU, b: &BigU) -> Option<usize> {
    let (left, right) = (layout::limbs(a), layout::limbs(b));
    (0..left.len().max(right.len())).find(|&i| {
        left.get(i).copied().unwrap_or(0) != right.get(i).copied().unwrap_or(0)
    })
}

/// The index of the lowest bit at which `a` and `b` differ, or `None` when they
/// are equal.
///
/// ```
/// use bigu::{audit::delta, BigU};
/// assert_eq!(delta::first_differing_bit(&BigU::from(0b1000u32), &BigU::from(0b1010u32)), Some(1));
/// assert_eq!(delta::first_differing_bit(&BigU::zero(), &BigU::zero()), None);
/// ```
pub fn first_differing_bit(a: &BigU, b: &BigU) -> Option<u64> {
    a.bit_xor(b).trailing_zeros()
}

/// How many bit positions the two values disagree on: the Hamming distance of
/// their magnitudes.
///
/// ```
/// use bigu::{audit::delta, BigU};
/// assert_eq!(delta::differing_bits(&BigU::from(0u32), &BigU::from(0xFFu32)), 8);
/// assert_eq!(delta::differing_bits(&BigU::from(5u32), &BigU::from(5u32)), 0);
/// ```
pub fn differing_bits(a: &BigU, b: &BigU) -> u64 {
    a.bit_xor(b).count_ones()
}

/// Returns `true` when every difference between `a` and `b` sits below bit
/// `bit`, i.e. the two agree from that bit upward.
///
/// Equal values differ nowhere, so this holds for every `bit`, including zero.
///
/// ```
/// use bigu::{audit::delta, BigU};
/// // The two agree above bit 8 and disagree in the byte below it.
/// let a = BigU::from(0x1234_0000u32);
/// let b = BigU::from(0x1234_00FFu32);
/// assert!(delta::differs_only_below(&a, &b, 8));
/// assert!(!delta::differs_only_below(&a, &b, 4));
/// assert!(delta::differs_only_below(&a, &a, 0));
/// ```
pub fn differs_only_below(a: &BigU, b: &BigU, bit: u64) -> bool {
    a.bit_xor(b).bit_len() <= bit
}

/// The inclusive span of limb indices touched by the difference, or `None` when
/// the values are equal.
///
/// A span of one limb says the damage is local; a span reaching the top limb
/// says the values diverged early and never resynchronized.
///
/// ```
/// use bigu::{audit::delta, BigU};
/// let a = BigU::from(1u32) << 64;
/// let b = &a + &BigU::from(1u32);
/// assert_eq!(delta::differing_limb_span(&a, &b), Some((0, 0)));
/// assert_eq!(delta::differing_limb_span(&a, &BigU::zero()), Some((2, 2)));
/// assert_eq!(delta::differing_limb_span(&a, &a), None);
/// ```
pub fn differing_limb_span(a: &BigU, b: &BigU) -> Option<(usize, usize)> {
    let diff = a.bit_xor(b);
    let lowest = layout::split_bit(diff.trailing_zeros()?).0;
    Some((lowest, layout::limb_count(&diff) - 1))
}

/// A one-line account of how `a` and `b` differ, for a failure message.
///
/// ```
/// use bigu::{audit::delta, BigU};
/// assert_eq!(delta::describe(&BigU::from(5u32), &BigU::from(5u32)), "identical");
/// let text = delta::describe(&BigU::from(5u32), &BigU::from(7u32));
/// assert!(text.contains("1 bit differ"));
/// assert!(text.contains("limbs 0..=0"));
/// ```
pub fn describe(a: &BigU, b: &BigU) -> String {
    match differing_limb_span(a, b) {
        None => "identical".to_string(),
        Some((low, high)) => {
            let bits = differing_bits(a, b);
            let unit = if bits == 1 { "bit" } else { "bits" };
            let first = first_differing_bit(a, b).unwrap_or(0);
            format!("{bits} {unit} differ, first at bit {first}, limbs {low}..={high}")
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn equal_values_have_no_difference_anywhere() {
        let v = BigU::from(1u32) << 300;
        assert_eq!(first_differing_limb(&v, &v), None);
        assert_eq!(first_differing_bit(&v, &v), None);
        assert_eq!(differing_bits(&v, &v), 0);
        assert_eq!(differing_limb_span(&v, &v), None);
        assert!(differs_only_below(&v, &v, 0));
    }

    #[test]
    fn a_length_difference_is_reported_as_a_limb_difference() {
        let short = BigU::from(1u32);
        let long = BigU::from(1u32) << 96;
        assert_eq!(first_differing_limb(&short, &long), Some(0));
        assert_eq!(differing_bits(&short, &long), 2);
        assert_eq!(differing_limb_span(&short, &long), Some((0, 3)));
    }

    #[test]
    fn zero_against_a_value_differs_in_every_set_bit() {
        let v = BigU::from(0xFFFF_FFFFu32);
        assert_eq!(differing_bits(&v, &BigU::zero()), 32);
        assert_eq!(first_differing_bit(&v, &BigU::zero()), Some(0));
    }

    #[test]
    fn a_truncation_is_confined_to_the_low_end() {
        // Clearing the bottom limb is the classic lost-limb failure.
        let full = BigU::from(0xDEAD_BEEF_1234_5678u64);
        let truncated = BigU::from(0xDEAD_BEEF_0000_0000u64);
        assert!(differs_only_below(&full, &truncated, 32));
        assert!(!differs_only_below(&full, &truncated, 16));
        assert_eq!(differing_limb_span(&full, &truncated), Some((0, 0)));
    }

    #[test]
    fn a_carry_that_escaped_shows_up_at_the_top() {
        let a = BigU::from(1u32) << 64;
        let b = &a - &BigU::from(1u32);
        // Every bit below 64 flipped, and so did bit 64 itself.
        assert_eq!(differing_bits(&a, &b), 65);
        assert_eq!(first_differing_bit(&a, &b), Some(0));
        assert_eq!(differing_limb_span(&a, &b), Some((0, 2)));
    }

    #[test]
    fn description_names_the_span() {
        let a = BigU::from(0x1_0000_0000u64);
        let b = BigU::from(0x1_0000_0001u64);
        let text = describe(&a, &b);
        assert!(text.contains("1 bit differ"));
        assert!(text.contains("first at bit 0"));
        assert_eq!(describe(&a, &a), "identical");
    }
}
