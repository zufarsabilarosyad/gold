//! End-to-end checks of the radix conversion and formatting surface, against
//! primitive integers where the values fit and against round trips where they
//! do not.

use bigu::BigU;
use std::str::FromStr;

fn b(s: &str) -> BigU {
    BigU::from_str(s).unwrap()
}

/// Small deterministic generator so the tests are reproducible without any
/// dependency on a random crate.
struct Lcg(u64);
impl Lcg {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        self.0
    }
    fn next_big(&mut self, limbs: usize) -> BigU {
        let mut v = BigU::zero();
        for _ in 0..limbs {
            v = &(&v << 32) + &BigU::from(self.next() as u32);
        }
        v
    }
}

#[test]
fn formatting_agrees_with_u128_across_specs() {
    let mut g = Lcg(0x5EED_1234);
    for _ in 0..200 {
        let x = (g.next() as u128) << 64 | g.next() as u128;
        let v = BigU::from(x);
        assert_eq!(format!("{v}"), format!("{x}"));
        assert_eq!(format!("{v:x}"), format!("{x:x}"));
        assert_eq!(format!("{v:X}"), format!("{x:X}"));
        assert_eq!(format!("{v:b}"), format!("{x:b}"));
        assert_eq!(format!("{v:o}"), format!("{x:o}"));
        assert_eq!(format!("{v:#x}"), format!("{x:#x}"));
        assert_eq!(format!("{v:>45}"), format!("{x:>45}"));
        assert_eq!(format!("{v:<45}"), format!("{x:<45}"));
        assert_eq!(format!("{v:^45}"), format!("{x:^45}"));
        assert_eq!(format!("{v:045}"), format!("{x:045}"));
        assert_eq!(format!("{v:#042x}"), format!("{x:#042x}"));
        assert_eq!(format!("{v:+50}"), format!("{x:+50}"));
        assert_eq!(format!("{v:.^140b}"), format!("{x:.^140b}"));
    }
}

#[test]
fn parsing_agrees_with_u128_across_bases() {
    let mut g = Lcg(0xC0FF_EE99);
    for _ in 0..200 {
        let x = (g.next() as u128) << 64 | g.next() as u128;
        assert_eq!(BigU::from_str(&x.to_string()).unwrap(), BigU::from(x));
        assert_eq!(BigU::from_str_radix(&format!("{x:x}"), 16).unwrap(), BigU::from(x));
        assert_eq!(BigU::from_str_radix(&format!("{x:b}"), 2).unwrap(), BigU::from(x));
        assert_eq!(BigU::from_str_radix(&format!("{x:o}"), 8).unwrap(), BigU::from(x));
        // The alternate forms feed straight back through the prefix parser.
        assert_eq!(BigU::from_str_prefixed(&format!("{x:#x}")).unwrap(), BigU::from(x));
        assert_eq!(BigU::from_str_prefixed(&format!("{x:#b}")).unwrap(), BigU::from(x));
        assert_eq!(BigU::from_str_prefixed(&format!("{x:#o}")).unwrap(), BigU::from(x));
    }
}

#[test]
fn radix_roundtrip_across_sizes_and_bases() {
    // Sizes span both the stepping and the splitting paths in each direction.
    let mut g = Lcg(0xFACE_B00C);
    for limbs in [1usize, 2, 5, 19, 20, 21, 40, 100] {
        let v = g.next_big(limbs);
        for radix in 2..=36u32 {
            let s = v.to_str_radix(radix).unwrap();
            assert_eq!(BigU::from_str_radix(&s, radix).unwrap(), v, "{limbs} limbs, radix {radix}");
            let up = v.to_str_radix_upper(radix).unwrap();
            assert_eq!(up, s.to_uppercase(), "{limbs} limbs, radix {radix} case");
            assert_eq!(BigU::from_str_radix(&up, radix).unwrap(), v);
            // A rendering never carries a leading zero unless it is just "0".
            assert!(s == "0" || !s.starts_with('0'), "leading zero at radix {radix}");
        }
    }
}

#[test]
fn decimal_roundtrip_on_powers_of_ten() {
    // Powers of ten are the worst case for chunked rendering: every digit below
    // the leading one is a zero that has to survive the chunk padding.
    for e in 0u32..300 {
        let v = BigU::from(10u32).pow(e);
        let expected = format!("1{}", "0".repeat(e as usize));
        assert_eq!(v.to_str_radix(10).unwrap(), expected, "10^{e}");
        assert_eq!(b(&expected), v, "parse 10^{e}");
    }
}

#[test]
fn repunit_roundtrip_across_lengths() {
    // Every digit significant, at lengths straddling each chunk and split
    // boundary.
    for len in 1..400usize {
        let s = "1".repeat(len);
        let v = b(&s);
        assert_eq!(v.to_str_radix(10).unwrap(), s, "length {len}");
    }
}

#[test]
fn conversion_survives_a_very_large_value() {
    // Well past every threshold in both directions.
    let mut v = b("31415926535897932384626433832795028841971693993751058209749445923078164062862");
    for _ in 0..5 {
        v = &v * &v;
    }
    assert!(v.bit_len() > 100 * 32, "value should be past every threshold");
    for radix in [2u32, 3, 10, 16, 36] {
        let s = v.to_str_radix(radix).unwrap();
        assert_eq!(BigU::from_str_radix(&s, radix).unwrap(), v, "radix {radix}");
    }
    // The decimal rendering agrees with what Display produces.
    assert_eq!(v.to_string(), v.to_str_radix(10).unwrap());
}

#[test]
fn arithmetic_identities_survive_a_string_roundtrip() {
    // Values that pass through text must still satisfy the arithmetic they came
    // from, which ties the conversion back to the rest of the crate.
    let mut g = Lcg(0x1BAD_C0DE);
    for _ in 0..50 {
        let a = g.next_big(25);
        let c = g.next_big(12);
        let product = &a * &c;
        let text = product.to_str_radix(10).unwrap();
        let restored = b(&text);
        assert_eq!(restored, product);
        let (q, r) = restored.div_rem(&c).unwrap();
        assert_eq!(q, a);
        assert!(r.is_zero());
    }
}

#[test]
fn formatted_output_parses_back_for_wide_values() {
    // Padded and prefixed output of a value far wider than any primitive must
    // still be readable once the padding is stripped.
    let v = BigU::from(7u32).pow(300);
    let padded = format!("{v:0>500}");
    assert_eq!(padded.len(), 500);
    assert_eq!(b(&padded), v, "zero padding must not change the value");

    let hex = format!("{v:#x}");
    assert_eq!(BigU::from_str_prefixed(&hex).unwrap(), v);
    let hex_padded = format!("{v:#0800x}");
    assert_eq!(hex_padded.len(), 800);
    assert_eq!(BigU::from_str_prefixed(&hex_padded).unwrap(), v);
}
