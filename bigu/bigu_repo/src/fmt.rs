//! The standard formatting traits.
//!
//! All five render through [`fmt::Formatter::pad_integral`], which is what
//! supplies the `#` prefix, the `+` sign, zero padding and every fill, width and
//! alignment combination. Writing the digits (or the prefix) straight to the
//! formatter instead would honour none of that: `{:>20}` and `{:08x}` would
//! silently come back unpadded. So the code here only produces the digits and
//! lets the formatter place them.

use core::fmt;

use crate::bigu::BigU;
use crate::radix::{DIGITS_LOWER, DIGITS_UPPER};

/// Digits for one of the four radixes the standard traits cover, so the radix
/// is always supported and the rendering cannot fail.
fn digits(v: &BigU, radix: u32, alphabet: &'static [u8; 36]) -> String {
    v.render(radix, alphabet)
        .expect("2, 8, 10 and 16 are supported radixes")
}

impl fmt::Display for BigU {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.pad_integral(true, "", &digits(self, 10, DIGITS_LOWER))
    }
}

impl fmt::LowerHex for BigU {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.pad_integral(true, "0x", &digits(self, 16, DIGITS_LOWER))
    }
}

impl fmt::UpperHex for BigU {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // The primitives keep the prefix lowercase even in the uppercase form.
        f.pad_integral(true, "0x", &digits(self, 16, DIGITS_UPPER))
    }
}

impl fmt::Binary for BigU {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.pad_integral(true, "0b", &digits(self, 2, DIGITS_LOWER))
    }
}

impl fmt::Octal for BigU {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.pad_integral(true, "0o", &digits(self, 8, DIGITS_LOWER))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use core::str::FromStr;

    fn b(s: &str) -> BigU {
        BigU::from_str(s).unwrap()
    }

    #[test]
    fn plain_forms_match_primitives() {
        let n = 43981u32;
        let v = BigU::from(n);
        assert_eq!(format!("{v}"), format!("{n}"));
        assert_eq!(format!("{v:x}"), format!("{n:x}"));
        assert_eq!(format!("{v:X}"), format!("{n:X}"));
        assert_eq!(format!("{v:b}"), format!("{n:b}"));
        assert_eq!(format!("{v:o}"), format!("{n:o}"));
    }

    #[test]
    fn alternate_forms_carry_the_prefix() {
        let n = 43981u32;
        let v = BigU::from(n);
        assert_eq!(format!("{v:#x}"), format!("{n:#x}"));
        assert_eq!(format!("{v:#X}"), format!("{n:#X}"));
        assert_eq!(format!("{v:#b}"), format!("{n:#b}"));
        assert_eq!(format!("{v:#o}"), format!("{n:#o}"));
        // Display has no prefix even in the alternate form.
        assert_eq!(format!("{v:#}"), format!("{n:#}"));
    }

    #[test]
    fn width_and_alignment_are_honoured() {
        let n = 43981u32;
        let v = BigU::from(n);
        assert_eq!(format!("{v:>20}"), format!("{n:>20}"));
        assert_eq!(format!("{v:<20}"), format!("{n:<20}"));
        assert_eq!(format!("{v:^20}"), format!("{n:^20}"));
        assert_eq!(format!("{v:*^12}"), format!("{n:*^12}"));
        assert_eq!(format!("{v:-<12}"), format!("{n:-<12}"));
        // The default alignment for an integer is right.
        assert_eq!(format!("{v:12}"), format!("{n:12}"));
    }

    #[test]
    fn zero_padding_is_honoured() {
        let n = 43981u32;
        let v = BigU::from(n);
        assert_eq!(format!("{v:08}"), format!("{n:08}"));
        assert_eq!(format!("{v:08x}"), format!("{n:08x}"));
        assert_eq!(format!("{v:08X}"), format!("{n:08X}"));
        assert_eq!(format!("{v:024b}"), format!("{n:024b}"));
        assert_eq!(format!("{v:08o}"), format!("{n:08o}"));
    }

    #[test]
    fn zero_padding_sits_inside_the_prefix() {
        // `0x0000abcd`, not `00000xabcd`: the fill belongs between the prefix
        // and the digits.
        let n = 43981u32;
        let v = BigU::from(n);
        assert_eq!(format!("{v:#010x}"), format!("{n:#010x}"));
        assert_eq!(format!("{v:#010X}"), format!("{n:#010X}"));
        assert_eq!(format!("{v:#026b}"), format!("{n:#026b}"));
        assert_eq!(format!("{v:#010o}"), format!("{n:#010o}"));
        assert_eq!(format!("{v:#010x}"), "0x0000abcd");
    }

    #[test]
    fn sign_flag_is_honoured() {
        let n = 43981u32;
        let v = BigU::from(n);
        assert_eq!(format!("{v:+}"), format!("{n:+}"));
        assert_eq!(format!("{v:+12}"), format!("{n:+12}"));
        assert_eq!(format!("{v:+012}"), format!("{n:+012}"));
        assert_eq!(format!("{v:+#x}"), format!("{n:+#x}"));
    }

    #[test]
    fn width_below_the_value_does_not_truncate() {
        let n = 43981u32;
        let v = BigU::from(n);
        assert_eq!(format!("{v:2}"), format!("{n:2}"));
        assert_eq!(format!("{v:1x}"), format!("{n:1x}"));
        assert_eq!(format!("{v:>0}"), format!("{n:>0}"));
    }

    #[test]
    fn zero_formats_like_a_primitive_zero() {
        let n = 0u32;
        let v = BigU::zero();
        assert_eq!(format!("{v}"), format!("{n}"));
        assert_eq!(format!("{v:x}"), format!("{n:x}"));
        assert_eq!(format!("{v:#x}"), format!("{n:#x}"));
        assert_eq!(format!("{v:08}"), format!("{n:08}"));
        assert_eq!(format!("{v:>6b}"), format!("{n:>6b}"));
        assert_eq!(format!("{v:#06x}"), format!("{n:#06x}"));
        assert_eq!(format!("{v:+}"), format!("{n:+}"));
    }

    #[test]
    fn multilimb_values_match_u128_formatting() {
        let mut x: u128 = 0xACE1_2345_6789;
        for _ in 0..100 {
            x = x.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            let v = BigU::from(x);
            assert_eq!(format!("{v}"), format!("{x}"));
            assert_eq!(format!("{v:x}"), format!("{x:x}"));
            assert_eq!(format!("{v:X}"), format!("{x:X}"));
            assert_eq!(format!("{v:b}"), format!("{x:b}"));
            assert_eq!(format!("{v:o}"), format!("{x:o}"));
            assert_eq!(format!("{v:>50}"), format!("{x:>50}"));
            assert_eq!(format!("{v:#040x}"), format!("{x:#040x}"));
            assert_eq!(format!("{v:*^45o}"), format!("{x:*^45o}"));
        }
    }

    #[test]
    fn padding_counts_digits_of_a_big_value() {
        // A value far wider than any primitive still pads to the requested
        // width and never loses digits.
        let v = BigU::from(10u32).pow(60);
        let text = format!("{v:>70}");
        assert_eq!(text.len(), 70);
        assert!(text.ends_with(&v.to_str_radix(10).unwrap()));
        assert_eq!(text.trim_start(), v.to_str_radix(10).unwrap());
        // Zero padding of the same value.
        let padded = format!("{v:070}");
        assert_eq!(padded.len(), 70);
        assert_eq!(b(&padded), v);
    }

    #[test]
    fn upper_and_lower_hex_differ_only_in_case() {
        let v = b("123456789012345678901234567890123456789");
        assert_eq!(format!("{v:X}"), format!("{v:x}").to_uppercase());
        // The prefix itself stays lowercase, so only the digits flip case.
        assert_eq!(
            format!("{v:#X}"),
            format!("0x{}", format!("{v:x}").to_uppercase())
        );
    }

    #[test]
    fn debug_is_unaffected_by_the_spec() {
        // Debug renders its own wrapper and is not an integer formatting impl.
        assert_eq!(format!("{:?}", BigU::from(42u32)), "BigU(42)");
        assert_eq!(format!("{:?}", BigU::zero()), "BigU(0)");
    }
}
