//! Ceilings applied before anything is allocated.
//!
//! `from_str_radix` opens with `Vec::with_capacity(s.len())` and then folds the
//! digits into limbs. Both steps are proportional to the input, and nothing in
//! between asks whether the input is a size this program wants to handle. Hand
//! it a megabyte of digits from a socket and it will faithfully build the
//! number — several times over, since the subquadratic path also allocates a
//! tower of powers on the way.
//!
//! The cheapest place to say no is here, where the digit count is known and no
//! buffer exists yet. A digit count converts to a bit count with nothing but the
//! radix, so both caps come off the same integer. The conversion has to be an
//! over-estimate, never an under-estimate: a bound that read low would let a
//! value slip past a bit cap the caller believed in. `log2(radix)` is computed
//! in fixed point by repeated squaring and rounded up, so the answer is at most
//! a bit or two above the truth and never below it.
//!
//! This is one half of a memory cap. The other half is the reuse budget, which
//! bounds what the arithmetic may allocate once a value exists; this bounds what
//! text is allowed to become a value at all. Nothing here folds a digit into a
//! value — only counts are touched.

use crate::intake::diagnostic::{Diagnostic, Rule};
use crate::intake::span::Span;

/// Fractional bits carried by the fixed-point logarithm.
const LOG2_FRAC: u32 = 20;

/// Digit ceiling used by [`Limits::default`]: a megabyte of digits is already
/// far past any plausible hand-written or configured number.
pub const DEFAULT_MAX_DIGITS: usize = 1 << 20;

/// Bit ceiling used by [`Limits::default`], set above what the digit cap implies
/// for decimal so that the digit cap is the one that speaks first.
pub const DEFAULT_MAX_BITS: u64 = 1 << 24;

/// `floor(log2(radix) * 2^LOG2_FRAC)`.
///
/// The integer part is the position of the top set bit; the fraction comes from
/// squaring the normalized mantissa once per output bit, which is the classic
/// binary-logarithm recurrence and needs nothing from floating point.
fn log2_fixed(radix: u32) -> u64 {
    let int_part = (u32::BITS - 1 - radix.leading_zeros()) as u64;
    let mut acc = int_part << LOG2_FRAC;
    let one = 1u128 << 32;
    let mut x = ((radix as u128) << 32) >> int_part; // mantissa in [1, 2), Q32
    let mut bit = 1u64 << (LOG2_FRAC - 1);
    while bit != 0 {
        x = (x * x) >> 32;
        if x >= one << 1 {
            x >>= 1;
            acc |= bit;
        }
        bit >>= 1;
    }
    acc
}

/// An upper bound on the bit length of any `digits`-digit number in `radix`.
///
/// Never reads lower than the true bit length, which is the property the caps
/// depend on. A radix below two is treated as two.
///
/// ```
/// # use bigu::intake::limits::bits_for_digits;
/// assert!(bits_for_digits(3, 10) >= 10); // 999 needs ten bits
/// assert_eq!(bits_for_digits(8, 16), 32); // a hex digit is exactly four
/// ```
pub fn bits_for_digits(digits: usize, radix: u32) -> u64 {
    let radix = radix.max(2);
    if radix.is_power_of_two() {
        // Each digit is a whole number of bits, so the bound is exact and needs
        // no slack — which matters, because a caller capping at 32 bits means
        // eight hex digits to fit, not seven.
        let per = radix.trailing_zeros() as u128;
        return (digits as u128 * per).min(u64::MAX as u128) as u64;
    }
    // The +1 on the logarithm turns the floor into a ceiling, and the +1 on the
    // product covers the fractional part the shift discards.
    let scaled = (digits as u128) * (log2_fixed(radix) as u128 + 1);
    ((scaled >> LOG2_FRAC) + 1).min(u64::MAX as u128) as u64
}

/// The two ceilings, checked together before construction.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Limits {
    /// Most digits the intake will accept, separators already removed.
    pub max_digits: usize,
    /// Most bits the resulting value may occupy, as the digits imply.
    pub max_bits: u64,
}

impl Limits {
    /// Builds an explicit pair of ceilings.
    ///
    /// ```
    /// # use bigu::intake::Limits;
    /// assert_eq!(Limits::new(64, 256).max_digits, 64);
    /// ```
    pub fn new(max_digits: usize, max_bits: u64) -> Limits {
        Limits { max_digits, max_bits }
    }

    /// Ceilings that never fire, for callers that trust their input.
    ///
    /// ```
    /// # use bigu::intake::{Limits, Span};
    /// assert!(Limits::unlimited().check(1 << 30, 10, Span::at(0)).is_ok());
    /// ```
    pub fn unlimited() -> Limits {
        Limits { max_digits: usize::MAX, max_bits: u64::MAX }
    }

    /// A bit ceiling with the digit ceiling derived from it, so a caller can say
    /// "nothing wider than a 4096-bit key" and mean it in every radix.
    ///
    /// ```
    /// # use bigu::intake::{Limits, Span};
    /// let l = Limits::of_bits(32);
    /// assert!(l.check(8, 16, Span::at(0)).is_ok());
    /// assert!(l.check(9, 16, Span::at(0)).is_err());
    /// ```
    pub fn of_bits(max_bits: u64) -> Limits {
        // Binary is the least dense radix, so its digit count is the loosest one
        // that can still respect the bit ceiling.
        Limits { max_digits: max_bits.min(usize::MAX as u64) as usize, max_bits }
    }

    /// Rejects a digit count that is too long, or too wide once converted.
    /// `span` is the region the digits occupy, so the report can point at the
    /// input rather than merely complain about its size.
    ///
    /// ```
    /// # use bigu::intake::{Limits, Span};
    /// let l = Limits::new(4, 1024);
    /// assert!(l.check(4, 10, Span::new(0, 4)).is_ok());
    /// assert!(l.check(5, 10, Span::new(0, 5)).is_err());
    /// ```
    pub fn check(&self, digits: usize, radix: u32, span: Span) -> Result<(), Diagnostic> {
        if digits > self.max_digits {
            let rule = Rule::DigitCap { found: digits, max: self.max_digits };
            return Err(Diagnostic::new(rule, span));
        }
        let bits = bits_for_digits(digits, radix);
        if bits > self.max_bits {
            return Err(Diagnostic::new(Rule::BitCap { found: bits, max: self.max_bits }, span));
        }
        Ok(())
    }
}

impl Default for Limits {
    fn default() -> Limits {
        Limits { max_digits: DEFAULT_MAX_DIGITS, max_bits: DEFAULT_MAX_BITS }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::BigU;

    #[test]
    fn power_of_two_radixes_are_exact() {
        assert_eq!(bits_for_digits(10, 2), 10);
        assert_eq!(bits_for_digits(8, 16), 32);
        assert_eq!(bits_for_digits(4, 8), 12);
        assert_eq!(bits_for_digits(0, 16), 0);
        // No digits in a general radix still reports a bit, which no cap worth
        // setting will reject.
        assert_eq!(bits_for_digits(0, 10), 1);
    }

    #[test]
    fn the_bound_never_reads_low() {
        // The widest value with n digits is radix^n - 1, written as n copies of
        // the top digit; its real bit length must never exceed the estimate.
        let alphabet = b"0123456789abcdefghijklmnopqrstuvwxyz";
        for radix in [2u32, 3, 8, 10, 16, 36] {
            let ch = alphabet[(radix - 1) as usize] as char;
            for digits in [1usize, 2, 5, 17, 64, 200] {
                let value = BigU::from_str_radix(&ch.to_string().repeat(digits), radix).unwrap();
                assert!(
                    value.bit_len() <= bits_for_digits(digits, radix),
                    "radix {radix}, {digits} digits"
                );
            }
        }
    }

    #[test]
    fn the_bound_is_not_wildly_loose() {
        // Two hundred decimal digits are 665 bits; more than a couple of bits of
        // slack would make a bit cap useless.
        let est = bits_for_digits(200, 10);
        assert!((665..=667).contains(&est), "estimate was {est}");
    }

    #[test]
    fn digit_cap_fires_first_and_names_the_numbers() {
        let l = Limits::new(3, u64::MAX);
        let err = l.check(4, 10, Span::new(0, 4)).unwrap_err();
        assert_eq!(err.rule, Rule::DigitCap { found: 4, max: 3 });
        assert_eq!(err.span, Span::new(0, 4));
        assert!(l.check(3, 10, Span::new(0, 3)).is_ok());
    }

    #[test]
    fn bit_cap_catches_a_dense_radix_the_digit_cap_would_miss() {
        // Sixteen digits pass the digit cap in either base, but sixteen hex
        // digits are sixty-four bits and sixteen binary digits are sixteen.
        let l = Limits::new(16, 32);
        assert!(l.check(16, 2, Span::at(0)).is_ok());
        assert!(matches!(
            l.check(16, 16, Span::at(0)).unwrap_err().rule,
            Rule::BitCap { max: 32, .. }
        ));
    }

    #[test]
    fn the_presets_behave() {
        let l = Limits::default();
        assert!(l.check(80, 10, Span::at(0)).is_ok());
        assert!(l.check(DEFAULT_MAX_DIGITS + 1, 10, Span::at(0)).is_err());
        assert_eq!(l, Limits::new(DEFAULT_MAX_DIGITS, DEFAULT_MAX_BITS));
        assert!(Limits::unlimited().check(usize::MAX, 36, Span::at(0)).is_ok());
    }
}
