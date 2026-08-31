//! Sizing policy: how large a limb buffer should be before it is written to.
//!
//! The crate already presizes. `add_limbs` reserves `long.len() + 1`,
//! `mul_schoolbook` reserves `a.len() + b.len()`, the radix renderer reserves a
//! digit bound. Those numbers are right, but each lives at its call site as an
//! unexplained expression, so the reasoning is rederived in every module and
//! nothing can be retuned in one place. This states the policy once, as named
//! functions with the bound written down beside them.
//!
//! The hints are *upper* bounds, never guesses. A sum of an `a`-limb and a
//! `b`-limb value is at most `max(a, b) + 1` limbs, because the carry out of the
//! top column is at most one; a product is at most `a + b`; a quotient of an
//! `n`-limb value by a `d`-limb one is at most `n - d + 1`. Overshooting costs a
//! few unused limbs, undershooting costs a reallocation and a copy in the middle
//! of the hot loop, so the asymmetry is deliberate.
//!
//! Values built incrementally — a running product, an accumulating digit string
//! — cannot be bounded ahead of time, so they get a growth factor instead: three
//! halves rather than the doubling `Vec` uses on its own, because these buffers
//! are large and a 1.5x ladder wastes about half as much at the top. Growth with
//! no matching release is a ratchet, so [`fit`] hands back capacity beyond
//! [`SLACK_FACTOR`] times the length.

use crate::Limb;

/// Numerator of the growth factor for incrementally built values.
pub const GROWTH_NUMERATOR: usize = 3;

/// Denominator of the growth factor for incrementally built values.
pub const GROWTH_DENOMINATOR: usize = 2;

/// Capacity beyond this multiple of the length counts as slack.
pub const SLACK_FACTOR: usize = 2;

/// Slack below this many limbs is never worth a reallocation to reclaim.
pub const SLACK_FLOOR: usize = 8;

/// Upper bound on the limb count of the sum of an `a`-limb and a `b`-limb value:
/// the carry out of the top column is at most one, so one limb past the wider
/// operand always suffices.
///
/// ```
/// use bigu::reuse::capacity::sum_hint;
///
/// assert_eq!((sum_hint(4, 4), sum_hint(9, 2), sum_hint(0, 0)), (5, 10, 1));
/// ```
pub fn sum_hint(a: usize, b: usize) -> usize {
    a.max(b) + 1
}

/// Upper bound on the limb count of the product of an `a`-limb and a `b`-limb
/// value. A zero operand makes the product zero, which needs no storage at all.
///
/// ```
/// use bigu::reuse::capacity::product_hint;
///
/// assert_eq!((product_hint(3, 5), product_hint(7, 0)), (8, 0));
/// ```
pub fn product_hint(a: usize, b: usize) -> usize {
    if a == 0 || b == 0 {
        0
    } else {
        a + b
    }
}

/// Upper bound on the limb count of `n`-limb divided by `d`-limb. A divisor
/// wider than the dividend gives a zero quotient, and a zero divisor has no
/// quotient at all; both report zero rather than underflowing.
///
/// ```
/// use bigu::reuse::capacity::quotient_hint;
///
/// assert_eq!((quotient_hint(10, 4), quotient_hint(3, 9), quotient_hint(5, 0)), (7, 0, 0));
/// ```
pub fn quotient_hint(n: usize, d: usize) -> usize {
    if d == 0 || d > n {
        0
    } else {
        n - d + 1
    }
}

/// Upper bound on the digit count of an `n`-limb value rendered in `radix`.
///
/// Every digit carries at least `floor(log2(radix))` bits, so dividing the bit
/// width by that floor can only overshoot. Matching the bound the radix renderer
/// already uses keeps one answer in the crate rather than two.
///
/// ```
/// use bigu::reuse::capacity::radix_digits_hint;
///
/// // 2^32 - 1 is ten decimal digits; the bound overshoots but never under.
/// assert!(radix_digits_hint(1, 10) >= 10);
/// assert_eq!((radix_digits_hint(1, 16), radix_digits_hint(0, 10)), (9, 1));
/// ```
pub fn radix_digits_hint(n: usize, radix: u32) -> usize {
    let per_digit = (Limb::BITS - 1 - radix.max(2).leading_zeros()) as usize;
    n * Limb::BITS as usize / per_digit + 1
}

/// The next capacity for a value that has outgrown `current`, never smaller than
/// `current + 1` so growth cannot stall.
///
/// ```
/// use bigu::reuse::capacity::grow;
///
/// assert_eq!((grow(64), grow(1), grow(0)), (96, 2, 1));
/// ```
pub fn grow(current: usize) -> usize {
    let scaled = current.saturating_mul(GROWTH_NUMERATOR) / GROWTH_DENOMINATOR;
    scaled.max(current + 1)
}

/// Releases capacity from a value that has stopped growing. Only reallocates
/// when the spare room clears both [`SLACK_FACTOR`] and [`SLACK_FLOOR`], so
/// calling this on every value in a loop is safe: tight buffers are left alone
/// and a handful of spare limbs is never worth a copy.
///
/// ```
/// use bigu::reuse::capacity::fit;
///
/// let mut v: Vec<u32> = Vec::with_capacity(1024);
/// v.extend_from_slice(&[1, 2, 3]);
/// fit(&mut v);
/// assert_eq!(v, vec![1, 2, 3]);
/// assert!(v.capacity() < 1024);
/// ```
pub fn fit(buf: &mut Vec<Limb>) {
    let (len, cap) = (buf.len(), buf.capacity());
    if cap > len.saturating_mul(SLACK_FACTOR) && cap - len > SLACK_FLOOR {
        buf.shrink_to_fit();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bigu::BigU;

    #[test]
    fn sum_and_product_hints_cover_the_worst_case() {
        // Two four-limb values whose sum spills into a fifth limb, and a square
        // that fills every limb the product bound reserves.
        let a = BigU::from(u128::MAX);
        assert_eq!((&a + &a).limbs.len(), 5);
        assert_eq!(sum_hint(4, 4), 5);
        let b = BigU::from(u64::MAX);
        assert_eq!(product_hint(2, 2), 4);
        assert!((&b * &b).limbs.len() <= product_hint(2, 2));
    }

    #[test]
    fn quotient_hint_never_underflows_on_a_wide_divisor() {
        let edges = [(0, 0), (0, 1), (1, 1), (2, 8)].map(|(n, d)| quotient_hint(n, d));
        assert_eq!(edges, [0, 0, 1, 0]);
    }

    #[test]
    fn radix_hint_is_never_short_of_the_real_rendering() {
        let v = BigU::from(u128::MAX);
        for radix in [2u32, 3, 8, 10, 16, 36] {
            let rendered = v.to_str_radix(radix).unwrap();
            assert!(
                radix_digits_hint(4, radix) >= rendered.len(),
                "radix {radix}: bound {} < actual {}",
                radix_digits_hint(4, radix),
                rendered.len()
            );
        }
    }

    #[test]
    fn growth_always_advances_even_from_zero_and_one() {
        let mut n = 0;
        for _ in 0..8 {
            let next = grow(n);
            assert!(next > n, "growth stalled at {n}");
            n = next;
        }
    }

    #[test]
    fn fit_releases_gross_slack_and_leaves_tight_buffers_alone() {
        let mut tight: Vec<Limb> = vec![1, 2, 3, 4];
        let before = tight.capacity();
        fit(&mut tight);
        assert_eq!(tight.capacity(), before);

        let mut small: Vec<Limb> = Vec::with_capacity(SLACK_FLOOR);
        fit(&mut small);
        assert_eq!(small.capacity(), SLACK_FLOOR, "a few limbs are not slack");

        let mut huge: Vec<Limb> = Vec::with_capacity(4096);
        huge.extend_from_slice(&[7, 7]);
        fit(&mut huge);
        assert_eq!(huge, vec![7 as Limb, 7]);
        assert!(huge.capacity() < 4096);
    }
}
