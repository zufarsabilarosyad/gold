//! String input and output in any radix from 2 through 36.
//!
//! Both directions work a chunk at a time rather than a digit at a time. Every
//! radix has a largest power that still fits in a single limb — `10^9` for
//! decimal, `16^7` for hex — so parsing folds that many ASCII digits into one
//! limb before touching the big value, and rendering peels the same number of
//! digits off per short division. That is a constant-factor win on top of the
//! same quadratic shape.
//!
//! A power-of-two radix skips the arithmetic entirely: each digit is a fixed
//! run of bits, so converting is only repacking between 32-bit limbs and
//! `bits`-wide digits. Octal and base 32 do not divide the limb evenly, so the
//! repacking runs through a rolling accumulator rather than assuming digits stay
//! inside a limb. This is the path the `{:x}`, `{:b}` and `{:o}` formatting
//! traits take.
//!
//! Above a size threshold the other radixes switch to divide and conquer. A tower
//! of powers `radix^(chunk_digits * 2^i)` is built by repeated squaring, and the
//! value (or digit string) is split in half against the largest power below it,
//! so the big divisions shrink geometrically instead of stepping down one chunk
//! at a time. The low half is always emitted at its full width — dropping its
//! leading zeros there would slide every higher digit down one place.

use core::str::FromStr;

use crate::bigu::BigU;
use crate::div::div_rem_small;
use crate::error::{Error, Result};
use crate::mul::mul_add_small;
use crate::{Limb, MAX_RADIX, MIN_RADIX};

/// Lowercase digit alphabet covering radixes up to 36.
pub(crate) const DIGITS_LOWER: &[u8; 36] = b"0123456789abcdefghijklmnopqrstuvwxyz";

/// Uppercase alphabet, used by the `UpperHex` rendering.
pub(crate) const DIGITS_UPPER: &[u8; 36] = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";

/// Limb count at or above which rendering splits instead of stepping.
const RENDER_SPLIT_LIMBS: usize = 20;

/// Number of whole chunks a digit string may hold before parsing splits.
const PARSE_SPLIT_CHUNKS: usize = 8;

/// Bits per digit when the radix is a power of two, where conversion is pure
/// bit repacking and needs no arithmetic at all.
fn pow2_bits(radix: u32) -> Option<u32> {
    if radix.is_power_of_two() {
        Some(radix.trailing_zeros())
    } else {
        None
    }
}

/// Repacks the limbs straight into digits, least significant first. Octal and
/// base 32 straddle limb boundaries, so the limbs feed a rolling accumulator
/// that never holds more than 32 pending bits and cannot overflow the window.
fn render_pow2(v: &BigU, bits: u32, alphabet: &[u8; 36]) -> Vec<u8> {
    let mask = (1u64 << bits) - 1;
    let mut out = Vec::with_capacity(digit_bound(v.bit_len(), 1 << bits));
    let mut acc = 0u64;
    let mut acc_bits = 0u32;
    for &limb in &v.limbs {
        acc |= (limb as u64) << acc_bits;
        acc_bits += Limb::BITS;
        while acc_bits >= bits {
            out.push(alphabet[(acc & mask) as usize]);
            acc >>= bits;
            acc_bits -= bits;
        }
    }
    // Whatever is left is the top partial digit.
    while acc != 0 {
        out.push(alphabet[(acc & mask) as usize]);
        acc >>= bits;
    }
    // The drain above emits a full limb's worth of digits at a time, so the top
    // of the number can carry zero digits that must not survive as leading
    // zeros. The value is nonzero here, so a significant digit always remains.
    while out.len() > 1 && out.last() == Some(&alphabet[0]) {
        out.pop();
    }
    out
}

/// The parsing counterpart: packs digit values back into limbs from the least
/// significant end.
fn parse_pow2(digits: &[u8], bits: u32) -> Vec<Limb> {
    let mut limbs = Vec::with_capacity(digits.len() * bits as usize / Limb::BITS as usize + 1);
    let mut acc = 0u64;
    let mut acc_bits = 0u32;
    for &d in digits.iter().rev() {
        acc |= (d as u64) << acc_bits;
        acc_bits += bits;
        if acc_bits >= Limb::BITS {
            limbs.push(acc as Limb);
            acc >>= Limb::BITS;
            acc_bits -= Limb::BITS;
        }
    }
    if acc != 0 {
        limbs.push(acc as Limb);
    }
    limbs
}

/// Maps a single ASCII byte to its digit value in the given radix.
fn digit_value(byte: u8, radix: u32) -> Option<u32> {
    let v = match byte {
        b'0'..=b'9' => (byte - b'0') as u32,
        b'a'..=b'z' => (byte - b'a') as u32 + 10,
        b'A'..=b'Z' => (byte - b'A') as u32 + 10,
        _ => return None,
    };
    if v < radix {
        Some(v)
    } else {
        None
    }
}

/// The largest power of `radix` that still fits in a limb, and how many digits
/// that power spans.
fn chunk(radix: u32) -> (Limb, u32) {
    let mut power = radix as u64;
    let mut digits = 1u32;
    while power * radix as u64 <= Limb::MAX as u64 {
        power *= radix as u64;
        digits += 1;
    }
    (power as Limb, digits)
}

/// Upper bound on how many digits `bits` bits occupy in `radix`. Only used to
/// presize buffers, so overshooting is harmless.
fn digit_bound(bits: u64, radix: u32) -> usize {
    // Every digit carries at least floor(log2(radix)) bits.
    let per_digit = (Limb::BITS - 1 - radix.leading_zeros()) as u64;
    (bits / per_digit) as usize + 1
}

/// Grows `powers` so that index `level` exists, where `powers[i]` is
/// `radix^(chunk_digits * 2^i)`. Each entry is the square of the previous one.
fn tower_up_to(powers: &mut Vec<BigU>, level: usize, base: Limb) {
    if powers.is_empty() {
        powers.push(BigU::from(base));
    }
    while powers.len() <= level {
        let next = {
            let last = &powers[powers.len() - 1];
            last * last
        };
        powers.push(next);
    }
}

/// Pushes the digits of a value already known to fit in one limb, least
/// significant first, stopping at the last significant digit.
fn push_limb_digits(mut v: Limb, radix: u32, alphabet: &[u8; 36], out: &mut Vec<u8>) {
    while v != 0 {
        out.push(alphabet[(v % radix) as usize]);
        v /= radix;
    }
}

/// Same as [`push_limb_digits`] but always pushes exactly `width` digits, zero
/// padded on the high side.
fn push_limb_digits_padded(
    mut v: Limb,
    radix: u32,
    width: u32,
    alphabet: &[u8; 36],
    out: &mut Vec<u8>,
) {
    for _ in 0..width {
        out.push(alphabet[(v % radix) as usize]);
        v /= radix;
    }
}

/// Everything the two rendering walks need to carry around.
struct Render<'a> {
    radix: u32,
    chunk_div: Limb,
    chunk_digits: u32,
    alphabet: &'a [u8; 36],
    powers: Vec<BigU>,
}

impl Render<'_> {
    /// Emits `v` at its natural width, least significant digit first. `v` must
    /// be below `powers[level]`.
    fn emit_top(&mut self, v: &BigU, level: usize, out: &mut Vec<u8>) {
        if level == 0 {
            push_limb_digits(low_limb(v), self.radix, self.alphabet, out);
            return;
        }
        let split = self.powers[level - 1].clone();
        let (hi, lo) = v.div_rem(&split).expect("tower entries are nonzero");
        if hi.is_zero() {
            // The whole value lives in the low half; no padding, since nothing
            // above it will be emitted.
            self.emit_top(&lo, level - 1, out);
        } else {
            self.emit_padded(&lo, level - 1, out);
            self.emit_top(&hi, level - 1, out);
        }
    }

    /// Emits `v` at exactly `chunk_digits * 2^level` digits, zero padded.
    fn emit_padded(&mut self, v: &BigU, level: usize, out: &mut Vec<u8>) {
        if level == 0 {
            push_limb_digits_padded(
                low_limb(v),
                self.radix,
                self.chunk_digits,
                self.alphabet,
                out,
            );
            return;
        }
        let split = self.powers[level - 1].clone();
        let (hi, lo) = v.div_rem(&split).expect("tower entries are nonzero");
        self.emit_padded(&lo, level - 1, out);
        self.emit_padded(&hi, level - 1, out);
    }
}

/// The single limb of a value that is known to be below `2^32`.
fn low_limb(v: &BigU) -> Limb {
    debug_assert!(v.limbs.len() <= 1);
    v.limbs.first().copied().unwrap_or(0)
}

/// Steps down through the value one chunk at a time, emitting digits least
/// significant first.
fn render_linear(v: &BigU, radix: u32, alphabet: &[u8; 36]) -> Vec<u8> {
    let (chunk_div, chunk_digits) = chunk(radix);
    let mut out = Vec::with_capacity(digit_bound(v.bit_len(), radix));
    let mut limbs = v.limbs.clone();
    while !limbs.is_empty() {
        let (q, rem) = div_rem_small(&limbs, chunk_div);
        limbs = q;
        if limbs.is_empty() {
            // Leading chunk: only its significant digits, so the rendering has
            // no leading zeros.
            push_limb_digits(rem, radix, alphabet, &mut out);
        } else {
            push_limb_digits_padded(rem, radix, chunk_digits, alphabet, &mut out);
        }
    }
    out
}

/// Splits the value against the largest tower power below it and recurses.
fn render_split(v: &BigU, radix: u32, alphabet: &[u8; 36]) -> Vec<u8> {
    let (chunk_div, chunk_digits) = chunk(radix);
    let mut state = Render {
        radix,
        chunk_div,
        chunk_digits,
        alphabet,
        powers: Vec::new(),
    };

    // Climb the tower until it overtakes the value; that level is the one whose
    // width bounds the whole rendering.
    tower_up_to(&mut state.powers, 0, state.chunk_div);
    let mut level = 0;
    while &state.powers[level] <= v {
        tower_up_to(&mut state.powers, level + 1, state.chunk_div);
        level += 1;
    }

    let mut out = Vec::with_capacity(digit_bound(v.bit_len(), radix));
    state.emit_top(v, level, &mut out);
    out
}

/// Folds a validated digit-value slice into limbs, a chunk at a time.
fn fold_linear(d: &[u8], radix: u32, chunk_div: Limb, chunk_digits: u32) -> Vec<Limb> {
    let mut limbs: Vec<Limb> = Vec::new();
    let mut pending: Limb = 0;
    let mut pending_len = 0u32;
    for &dv in d {
        // `pending` stays below chunk_div, which fits a limb by construction.
        pending = pending * radix + dv as Limb;
        pending_len += 1;
        if pending_len == chunk_digits {
            limbs = mul_add_small(&limbs, chunk_div, pending);
            pending = 0;
            pending_len = 0;
        }
    }
    if pending_len != 0 {
        limbs = mul_add_small(&limbs, radix.pow(pending_len), pending);
    }
    limbs
}

/// Parses a validated digit-value slice, splitting it in half at a tower
/// boundary once it is long enough to pay for the recombining multiply.
fn parse_digits(
    d: &[u8],
    radix: u32,
    chunk_div: Limb,
    chunk_digits: u32,
    powers: &mut Vec<BigU>,
) -> BigU {
    if d.len() <= chunk_digits as usize * PARSE_SPLIT_CHUNKS {
        return BigU::from_limbs(fold_linear(d, radix, chunk_div, chunk_digits));
    }

    // Largest tower level whose digit width still leaves something above it.
    let mut level = 0;
    while (chunk_digits as usize) << (level + 1) < d.len() {
        level += 1;
    }
    tower_up_to(powers, level, chunk_div);

    let low_len = (chunk_digits as usize) << level;
    let cut = d.len() - low_len;
    let hi = parse_digits(&d[..cut], radix, chunk_div, chunk_digits, powers);
    let lo = parse_digits(&d[cut..], radix, chunk_div, chunk_digits, powers);
    &(&hi * &powers[level]) + &lo
}

impl BigU {
    /// Parses `s` as an unsigned integer written in `radix`.
    ///
    /// Underscores are accepted as digit separators and ignored. The radix must
    /// be in `2..=36`, otherwise [`Error::UnsupportedRadix`] is returned. An
    /// input with no actual digits yields [`Error::EmptyString`], and a stray
    /// character yields [`Error::InvalidDigit`].
    pub fn from_str_radix(s: &str, radix: u32) -> Result<BigU> {
        if !(MIN_RADIX..=MAX_RADIX).contains(&radix) {
            return Err(Error::UnsupportedRadix(radix));
        }
        if s.is_empty() {
            return Err(Error::EmptyString);
        }

        // Validate and translate up front so the numeric passes below never have
        // to think about separators or bad input.
        let mut digits = Vec::with_capacity(s.len());
        for ch in s.chars() {
            if ch == '_' {
                continue;
            }
            // Only ASCII can be a base-36 digit; reject anything else cleanly.
            let byte = if ch.is_ascii() { ch as u8 } else { 0xFF };
            match digit_value(byte, radix) {
                Some(d) => digits.push(d as u8),
                None => return Err(Error::InvalidDigit { ch, radix }),
            }
        }
        if digits.is_empty() {
            return Err(Error::EmptyString);
        }

        // Leading zeros carry no value and only make the split pick a deeper
        // level than the number needs.
        let start = digits.iter().position(|&d| d != 0).unwrap_or(digits.len());
        let significant = &digits[start..];
        if significant.is_empty() {
            return Ok(BigU::zero());
        }

        // A power-of-two radix carries a whole number of bits per digit, so the
        // digits repack into limbs directly with no multiplication.
        if let Some(bits) = pow2_bits(radix) {
            return Ok(BigU::from_limbs(parse_pow2(significant, bits)));
        }

        let (chunk_div, chunk_digits) = chunk(radix);
        let mut powers = Vec::new();
        Ok(parse_digits(
            significant,
            radix,
            chunk_div,
            chunk_digits,
            &mut powers,
        ))
    }

    /// Parses a string that carries its own base prefix: `0x` for hexadecimal,
    /// `0b` for binary, `0o` for octal, and plain decimal otherwise.
    ///
    /// This is the inverse of the alternate formatting forms, so
    /// `format!("{:#x}", v)` and friends round trip back through it.
    ///
    /// ```
    /// use bigu::BigU;
    /// let v = BigU::from(48879u32);
    /// assert_eq!(BigU::from_str_prefixed(&format!("{:#x}", v)).unwrap(), v);
    /// assert_eq!(BigU::from_str_prefixed("0b1010").unwrap(), BigU::from(10u32));
    /// assert_eq!(BigU::from_str_prefixed("42").unwrap(), BigU::from(42u32));
    /// ```
    pub fn from_str_prefixed(s: &str) -> Result<BigU> {
        // The prefix bytes are ASCII, so slicing past them stays on a character
        // boundary.
        let (radix, rest) = match s.as_bytes() {
            [b'0', b'x' | b'X', ..] => (16, &s[2..]),
            [b'0', b'b' | b'B', ..] => (2, &s[2..]),
            [b'0', b'o' | b'O', ..] => (8, &s[2..]),
            _ => (10, s),
        };
        BigU::from_str_radix(rest, radix)
    }

    /// Renders the value as a string in `radix`, using lowercase letters for the
    /// digits above nine.
    ///
    /// The radix must be in `2..=36`, otherwise [`Error::UnsupportedRadix`] is
    /// returned. Zero renders as `"0"`.
    pub fn to_str_radix(&self, radix: u32) -> Result<String> {
        self.render(radix, DIGITS_LOWER)
    }

    /// Uppercase counterpart of [`BigU::to_str_radix`].
    ///
    /// ```
    /// use bigu::BigU;
    /// assert_eq!(BigU::from(48879u32).to_str_radix_upper(16).unwrap(), "BEEF");
    /// ```
    pub fn to_str_radix_upper(&self, radix: u32) -> Result<String> {
        self.render(radix, DIGITS_UPPER)
    }

    /// Shared rendering entry point; the formatting traits reach it directly so
    /// they can pick an alphabet without a second pass over the string.
    pub(crate) fn render(&self, radix: u32, alphabet: &[u8; 36]) -> Result<String> {
        if !(MIN_RADIX..=MAX_RADIX).contains(&radix) {
            return Err(Error::UnsupportedRadix(radix));
        }
        if self.is_zero() {
            return Ok("0".to_string());
        }

        let mut out = if let Some(bits) = pow2_bits(radix) {
            render_pow2(self, bits, alphabet)
        } else if self.limbs.len() >= RENDER_SPLIT_LIMBS {
            render_split(self, radix, alphabet)
        } else {
            render_linear(self, radix, alphabet)
        };
        // Both walks build least significant digit first.
        out.reverse();
        Ok(String::from_utf8(out).expect("digit bytes are ASCII"))
    }
}

impl FromStr for BigU {
    type Err = Error;
    fn from_str(s: &str) -> Result<BigU> {
        BigU::from_str_radix(s, 10)
    }
}

/// Force the stepping renderer regardless of size, so tests can use it as an
/// independent oracle for the splitting one.
#[cfg(test)]
pub(crate) fn render_linear_forced(v: &BigU, radix: u32) -> String {
    let mut out = render_linear(v, radix, DIGITS_LOWER);
    out.reverse();
    String::from_utf8(out).unwrap()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn b(s: &str) -> BigU {
        BigU::from_str(s).unwrap()
    }

    #[test]
    fn parse_decimal_basic() {
        assert_eq!(BigU::from_str("0").unwrap(), BigU::zero());
        assert_eq!(BigU::from_str("42").unwrap(), BigU::from(42u32));
        assert_eq!(
            BigU::from_str("4294967296").unwrap(),
            BigU::from(0x1_0000_0000u64)
        );
    }

    #[test]
    fn parse_with_underscores() {
        assert_eq!(BigU::from_str_radix("1_000_000", 10).unwrap(), BigU::from(1_000_000u32));
        // Separators may sit anywhere, including in runs and at the edges.
        assert_eq!(BigU::from_str_radix("_1__2_", 10).unwrap(), BigU::from(12u32));
    }

    #[test]
    fn parse_errors() {
        assert_eq!(BigU::from_str(""), Err(Error::EmptyString));
        assert_eq!(BigU::from_str_radix("___", 10), Err(Error::EmptyString));
        assert_eq!(BigU::from_str_radix("12", 1), Err(Error::UnsupportedRadix(1)));
        assert_eq!(BigU::from_str_radix("xy", 37), Err(Error::UnsupportedRadix(37)));
        assert_eq!(
            BigU::from_str_radix("1G", 16),
            Err(Error::InvalidDigit { ch: 'G', radix: 16 })
        );
        assert_eq!(
            BigU::from_str("12a"),
            Err(Error::InvalidDigit { ch: 'a', radix: 10 })
        );
        // A non-ASCII character is rejected as a digit, not silently skipped.
        assert_eq!(
            BigU::from_str("1٢3"),
            Err(Error::InvalidDigit { ch: '٢', radix: 10 })
        );
    }

    #[test]
    fn parse_leading_zeros_are_ignored() {
        assert_eq!(BigU::from_str("0000042").unwrap(), BigU::from(42u32));
        assert!(BigU::from_str("00000").unwrap().is_zero());
        assert_eq!(BigU::from_str_radix("000ff", 16).unwrap(), BigU::from(255u32));
        // A long run of leading zeros in front of a long number must not shift
        // the value or pick a wrong split level.
        let padded = format!("{}{}", "0".repeat(200), "1".repeat(120));
        assert_eq!(b(&padded), b(&"1".repeat(120)));
    }

    #[test]
    fn to_str_radix_basic() {
        assert_eq!(BigU::zero().to_str_radix(10).unwrap(), "0");
        assert_eq!(BigU::from(255u32).to_str_radix(16).unwrap(), "ff");
        assert_eq!(BigU::from(8u32).to_str_radix(2).unwrap(), "1000");
    }

    #[test]
    fn to_str_radix_rejects_bad_radix() {
        assert_eq!(BigU::from(5u32).to_str_radix(0), Err(Error::UnsupportedRadix(0)));
        assert_eq!(BigU::from(5u32).to_str_radix(40), Err(Error::UnsupportedRadix(40)));
        assert_eq!(BigU::zero().to_str_radix(1), Err(Error::UnsupportedRadix(1)));
        // The uppercase variant validates the same way.
        assert_eq!(
            BigU::from(5u32).to_str_radix_upper(37),
            Err(Error::UnsupportedRadix(37))
        );
    }

    #[test]
    fn to_str_radix_upper_matches_lower() {
        let v = b("123456789012345678901234567890");
        for radix in MIN_RADIX..=MAX_RADIX {
            let lower = v.to_str_radix(radix).unwrap();
            let upper = v.to_str_radix_upper(radix).unwrap();
            assert_eq!(upper, lower.to_uppercase(), "radix {radix}");
        }
        assert_eq!(BigU::zero().to_str_radix_upper(16).unwrap(), "0");
    }

    #[test]
    fn to_str_radix_keeps_all_digits_multilimb() {
        // A multi-limb value must not lose or misorder its most-significant
        // digit when rendered.
        let v = BigU::from(2u32).pow(128); // 2^128
        assert_eq!(
            v.to_str_radix(10).unwrap(),
            "340282366920938463463374607431768211456"
        );
        assert_eq!(
            v.to_str_radix(16).unwrap(),
            "100000000000000000000000000000000"
        );
    }

    #[test]
    fn to_str_radix_known_large_decimal() {
        let v = BigU::from_str("123456789012345678901234567890").unwrap();
        assert_eq!(v.to_str_radix(10).unwrap(), "123456789012345678901234567890");
        // Same value in hex, independently checkable.
        assert_eq!(
            v.to_str_radix(16).unwrap(),
            "18ee90ff6c373e0ee4e3f0ad2"
        );
    }

    #[test]
    fn interior_zero_chunks_are_padded() {
        // The classic chunking hazard: an interior chunk of all zeros must keep
        // its full width or every digit above it slides down a place.
        assert_eq!(BigU::from(1_000_000_000u32).to_str_radix(10).unwrap(), "1000000000");
        let v = b("1000000000000000000");
        assert_eq!(v.to_str_radix(10).unwrap(), "1000000000000000000");
        // A one at both ends with a full zero chunk between them.
        let v = b("1000000000000000001");
        assert_eq!(v.to_str_radix(10).unwrap(), "1000000000000000001");
        // Powers of ten straddling several chunk boundaries.
        for e in 0u32..40 {
            let expected = format!("1{}", "0".repeat(e as usize));
            assert_eq!(BigU::from(10u32).pow(e).to_str_radix(10).unwrap(), expected, "10^{e}");
        }
    }

    #[test]
    fn radix_roundtrip_all_bases() {
        let value = BigU::from_str("99887766554433221100998877665544332211").unwrap();
        for radix in MIN_RADIX..=MAX_RADIX {
            let s = value.to_str_radix(radix).unwrap();
            let back = BigU::from_str_radix(&s, radix).unwrap();
            assert_eq!(back, value, "roundtrip failed at radix {radix}");
            // The uppercase spelling parses back to the same value.
            let up = value.to_str_radix_upper(radix).unwrap();
            assert_eq!(BigU::from_str_radix(&up, radix).unwrap(), value, "upper {radix}");
        }
    }

    #[test]
    fn case_insensitive_parse() {
        assert_eq!(
            BigU::from_str_radix("DEADBEEF", 16).unwrap(),
            BigU::from_str_radix("deadbeef", 16).unwrap()
        );
        assert_eq!(BigU::from_str_radix("deadbeef", 16).unwrap(), BigU::from(0xDEADBEEFu32));
    }

    #[test]
    fn display_and_fromstr_roundtrip() {
        let s = "57896044618658097711785492504343953926634992332820282019728792003956564819968";
        let v = BigU::from_str(s).unwrap();
        assert_eq!(v.to_string(), s);
    }

    #[test]
    fn chunk_power_fills_the_limb() {
        // The chosen power must fit a limb while one more digit would not.
        for radix in MIN_RADIX..=MAX_RADIX {
            let (power, digits) = chunk(radix);
            assert_eq!(power as u64, (radix as u64).pow(digits), "radix {radix}");
            assert!(
                (power as u64) * radix as u64 > Limb::MAX as u64,
                "radix {radix} could fit another digit"
            );
        }
        assert_eq!(chunk(10), (1_000_000_000, 9));
        assert_eq!(chunk(16), (0x1000_0000, 7));
        assert_eq!(chunk(2), (0x8000_0000, 31));
    }

    #[test]
    fn digit_bound_never_undershoots() {
        // The presize hint must be an upper bound, or the buffer would grow
        // silently and the estimate would be pointless.
        let values = [
            BigU::one(),
            BigU::from(u64::MAX),
            BigU::from(u128::MAX),
            BigU::from(2u32).pow(500),
            b("123456789012345678901234567890"),
        ];
        for v in &values {
            for radix in MIN_RADIX..=MAX_RADIX {
                let actual = v.to_str_radix(radix).unwrap().len();
                assert!(
                    digit_bound(v.bit_len(), radix) >= actual,
                    "radix {radix} bound too small"
                );
            }
        }
    }

    #[test]
    fn split_render_matches_linear_render() {
        // Values large enough to take the splitting path, cross-checked against
        // the stepping one for every radix.
        let mut v = b("31415926535897932384626433832795028841971693993751");
        for _ in 0..3 {
            v = &v * &v;
        }
        assert!(v.limbs.len() >= RENDER_SPLIT_LIMBS, "test value too small");
        for radix in MIN_RADIX..=MAX_RADIX {
            assert_eq!(
                v.to_str_radix(radix).unwrap(),
                render_linear_forced(&v, radix),
                "split and linear disagree at radix {radix}"
            );
        }
    }

    #[test]
    fn split_render_at_the_threshold() {
        // Sizes straddling the split threshold, including values whose top chunk
        // is a lone digit and values that are exact tower powers.
        for limbs in (RENDER_SPLIT_LIMBS - 3)..(RENDER_SPLIT_LIMBS + 6) {
            let v = &BigU::one() << (limbs as u32 * 32 - 1);
            assert_eq!(v.to_str_radix(10).unwrap(), render_linear_forced(&v, 10));
            let v = &v + &BigU::one();
            assert_eq!(v.to_str_radix(10).unwrap(), render_linear_forced(&v, 10));
            let v = v.checked_sub(&BigU::from(3u32)).unwrap();
            assert_eq!(v.to_str_radix(16).unwrap(), render_linear_forced(&v, 16));
        }
    }

    #[test]
    fn split_render_handles_zero_runs() {
        // A huge power of ten is all zeros below the leading digit, which is
        // exactly what the padded half of the split must preserve.
        for e in [100u32, 199, 200, 201, 500] {
            let v = BigU::from(10u32).pow(e);
            let expected = format!("1{}", "0".repeat(e as usize));
            assert_eq!(v.to_str_radix(10).unwrap(), expected, "10^{e}");
        }
        // Powers of two are all zeros in binary below the top bit.
        let v = &BigU::one() << 1000;
        assert_eq!(v.to_str_radix(2).unwrap(), format!("1{}", "0".repeat(1000)));
    }

    #[test]
    fn split_parse_matches_roundtrip() {
        // Digit strings long enough to trigger the splitting parse, checked by
        // rendering them back.
        let mut v = b("271828182845904523536028747135266249775724709369995");
        for _ in 0..3 {
            v = &v * &v;
        }
        for radix in MIN_RADIX..=MAX_RADIX {
            let s = v.to_str_radix(radix).unwrap();
            assert!(s.len() > 8 * 31, "radix {radix} string too short to split");
            assert_eq!(BigU::from_str_radix(&s, radix).unwrap(), v, "radix {radix}");
        }
    }

    #[test]
    fn split_parse_at_chunk_boundaries() {
        // Digit counts either side of every split boundary, so an off-by-one in
        // the cut point would show up as a wrong value.
        for len in 1..300usize {
            let s = "1".repeat(len);
            let parsed = b(&s);
            assert_eq!(parsed.to_str_radix(10).unwrap(), s, "length {len}");
        }
    }

    #[test]
    fn parse_matches_horner_oracle() {
        // Independent digit-at-a-time accumulation, the definition of the value.
        for radix in [2u32, 7, 10, 16, 36] {
            let digits: Vec<u8> = (0..250u32).map(|i| (i * 37 + 11) as u8 % radix as u8).collect();
            let text: String = digits
                .iter()
                .map(|&d| DIGITS_LOWER[d as usize] as char)
                .collect();
            let mut oracle = BigU::zero();
            for &d in &digits {
                oracle = &(&oracle * &BigU::from(radix)) + &BigU::from(d as u32);
            }
            assert_eq!(BigU::from_str_radix(&text, radix).unwrap(), oracle, "radix {radix}");
        }
    }

    #[test]
    fn parse_matches_primitive_for_u128_values() {
        // Differential check against the primitive parser where the values fit.
        let mut x: u128 = 0x1234_5678_9ABC_DEF0;
        for _ in 0..200 {
            x = x.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            for radix in [2u32, 8, 10, 16, 36] {
                let s = match radix {
                    2 => format!("{x:b}"),
                    8 => format!("{x:o}"),
                    16 => format!("{x:x}"),
                    _ => x.to_string(),
                };
                if radix == 36 {
                    // No primitive formatter for base 36; check the round trip.
                    let v = BigU::from(x);
                    let text = v.to_str_radix(36).unwrap();
                    assert_eq!(BigU::from_str_radix(&text, 36).unwrap(), v);
                    continue;
                }
                assert_eq!(BigU::from_str_radix(&s, radix).unwrap(), BigU::from(x));
                assert_eq!(BigU::from(x).to_str_radix(radix).unwrap(), s);
            }
        }
    }

    #[test]
    fn pow2_bits_identifies_the_fast_radixes() {
        assert_eq!(pow2_bits(2), Some(1));
        assert_eq!(pow2_bits(4), Some(2));
        assert_eq!(pow2_bits(8), Some(3));
        assert_eq!(pow2_bits(16), Some(4));
        assert_eq!(pow2_bits(32), Some(5));
        for radix in [3u32, 6, 10, 15, 20, 36] {
            assert_eq!(pow2_bits(radix), None, "radix {radix}");
        }
    }

    #[test]
    fn pow2_render_matches_generic_render() {
        // The bit-repacking path must agree digit for digit with the arithmetic
        // one, including the radixes whose digits straddle a limb boundary.
        let mut values = vec![
            BigU::one(),
            BigU::from(u32::MAX),
            BigU::from(u64::MAX),
            BigU::from(u128::MAX),
            b("123456789012345678901234567890"),
        ];
        // Single set bits land a digit boundary in every alignment.
        for k in 0..70u32 {
            values.push(&BigU::one() << k);
            values.push(&(&BigU::one() << k) + &BigU::one());
        }
        let mut big = b("31415926535897932384626433832795028841971");
        for _ in 0..3 {
            big = &big * &big;
            values.push(big.clone());
        }
        for v in &values {
            for radix in [2u32, 4, 8, 16, 32] {
                assert_eq!(
                    v.to_str_radix(radix).unwrap(),
                    render_linear_forced(v, radix),
                    "radix {radix} on {v:?}"
                );
            }
        }
    }

    #[test]
    fn pow2_render_has_no_leading_zeros() {
        // Draining a whole limb at a time emits zero digits above the top of the
        // number; they must not survive into the string.
        for k in 0..100u32 {
            let v = &BigU::one() << k;
            for radix in [2u32, 4, 8, 16, 32] {
                let s = v.to_str_radix(radix).unwrap();
                assert!(!s.starts_with('0'), "radix {radix}, 2^{k} rendered {s}");
                assert_eq!(BigU::from_str_radix(&s, radix).unwrap(), v);
            }
        }
        assert_eq!(BigU::zero().to_str_radix(16).unwrap(), "0");
        assert_eq!(BigU::zero().to_str_radix(2).unwrap(), "0");
    }

    #[test]
    fn pow2_roundtrips_across_widths() {
        // Values whose bit length is not a multiple of the digit width exercise
        // the partial top digit in both directions.
        let mut v = BigU::one();
        for k in 1..200u32 {
            v = &(&v << 1) + &BigU::from(k % 2);
            for radix in [2u32, 4, 8, 16, 32] {
                let s = v.to_str_radix(radix).unwrap();
                assert_eq!(BigU::from_str_radix(&s, radix).unwrap(), v, "radix {radix}, k {k}");
                let up = v.to_str_radix_upper(radix).unwrap();
                assert_eq!(BigU::from_str_radix(&up, radix).unwrap(), v);
            }
        }
    }

    #[test]
    fn pow2_parse_ignores_leading_zero_digits() {
        // Leading zeros must not create empty high limbs or shift the value.
        for radix in [2u32, 4, 8, 16, 32] {
            let v = b("98765432109876543210987654321");
            let s = v.to_str_radix(radix).unwrap();
            let padded = format!("{}{}", "0".repeat(97), s);
            assert_eq!(BigU::from_str_radix(&padded, radix).unwrap(), v, "radix {radix}");
        }
    }

    #[test]
    fn from_str_prefixed_bases() {
        assert_eq!(BigU::from_str_prefixed("0xff").unwrap(), BigU::from(255u32));
        assert_eq!(BigU::from_str_prefixed("0XFF").unwrap(), BigU::from(255u32));
        assert_eq!(BigU::from_str_prefixed("0b1010").unwrap(), BigU::from(10u32));
        assert_eq!(BigU::from_str_prefixed("0B1010").unwrap(), BigU::from(10u32));
        assert_eq!(BigU::from_str_prefixed("0o17").unwrap(), BigU::from(15u32));
        assert_eq!(BigU::from_str_prefixed("0O17").unwrap(), BigU::from(15u32));
        // No prefix means decimal, and a bare zero stays a zero.
        assert_eq!(BigU::from_str_prefixed("42").unwrap(), BigU::from(42u32));
        assert!(BigU::from_str_prefixed("0").unwrap().is_zero());
        // Separators still work after the prefix.
        assert_eq!(BigU::from_str_prefixed("0xff_ff").unwrap(), BigU::from(65535u32));
    }

    #[test]
    fn from_str_prefixed_errors() {
        // A prefix with nothing behind it has no digits.
        assert_eq!(BigU::from_str_prefixed("0x"), Err(Error::EmptyString));
        assert_eq!(BigU::from_str_prefixed("0b"), Err(Error::EmptyString));
        assert_eq!(BigU::from_str_prefixed(""), Err(Error::EmptyString));
        // Digits outside the prefixed base are rejected in that base.
        assert_eq!(
            BigU::from_str_prefixed("0b12"),
            Err(Error::InvalidDigit { ch: '2', radix: 2 })
        );
        assert_eq!(
            BigU::from_str_prefixed("0o18"),
            Err(Error::InvalidDigit { ch: '8', radix: 8 })
        );
    }

    #[test]
    fn from_str_prefixed_roundtrips_alternate_formatting() {
        let values = [
            BigU::zero(),
            BigU::one(),
            BigU::from(0xDEAD_BEEFu32),
            BigU::from(u128::MAX),
            b("123456789012345678901234567890"),
        ];
        for v in &values {
            assert_eq!(BigU::from_str_prefixed(&format!("{v:#x}")).unwrap(), *v);
            assert_eq!(BigU::from_str_prefixed(&format!("{v:#b}")).unwrap(), *v);
            assert_eq!(BigU::from_str_prefixed(&format!("{v:#o}")).unwrap(), *v);
            assert_eq!(BigU::from_str_prefixed(&format!("{v}")).unwrap(), *v);
        }
    }
}
