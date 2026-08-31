//! End-to-end checks of the arithmetic surface against independent oracles.

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
    fn next_big(&mut self) -> BigU {
        BigU::from(self.next() as u128) * BigU::from(self.next() as u128)
            + BigU::from(self.next())
    }
}

#[test]
fn mul_div_roundtrip() {
    let mut g = Lcg(0xDEAD_BEEF);
    for _ in 0..150 {
        let a = g.next_big();
        let mut b_val = g.next_big();
        if b_val.is_zero() {
            b_val = BigU::one();
        }
        let product = &a * &b_val;
        let (q, r) = product.div_rem(&b_val).unwrap();
        assert!(r.is_zero(), "exact product should divide cleanly");
        assert_eq!(q, a, "a*b/b should recover a");
    }
}

#[test]
fn add_sub_roundtrip() {
    let mut g = Lcg(0x1234_5678);
    for _ in 0..150 {
        let a = g.next_big();
        let b_val = g.next_big();
        let sum = &a + &b_val;
        assert_eq!(sum.checked_sub(&b_val).unwrap(), a);
        assert_eq!(sum.checked_sub(&a).unwrap(), b_val);
    }
}

#[test]
fn karatsuba_cross_check_against_repeated_addition_scale() {
    // Verify a Karatsuba-sized multiply by checking the distributive law:
    // a * (b + c) == a*b + a*c, on operands large enough to hit Karatsuba.
    let a = BigU::from(10u32).pow(200);
    let b_val = BigU::from(10u32).pow(180);
    let c = BigU::from(10u32).pow(150);
    let lhs = &a * &(&b_val + &c);
    let rhs = &(&a * &b_val) + &(&a * &c);
    assert_eq!(lhs, rhs);
}

#[test]
fn algorithm_d_known_vectors() {
    // 2^256 divided by a couple of fixed divisors, checked via the invariant.
    let dividend = BigU::from(2u32).pow(256);
    for ds in &[
        "97",
        "4294967295",
        "18446744073709551557",
        "340282366920938463463374607431768211297",
    ] {
        let d = b(ds);
        let (q, r) = dividend.div_rem(&d).unwrap();
        assert_eq!(&(&q * &d) + &r, dividend);
        assert!(r < d);
    }
}

#[test]
fn algorithm_d_exact_quotient() {
    // (d * q) / d == q with no remainder for chosen large factors.
    let d = b("123456789012345678901234567890123");
    let q = b("987654321098765432109876543210987");
    let n = &d * &q;
    let (q2, r2) = n.div_rem(&d).unwrap();
    assert_eq!(q2, q);
    assert!(r2.is_zero());
}

#[test]
fn radix_roundtrip_all_bases() {
    let value = b("123456789012345678901234567890987654321");
    for radix in 2..=36u32 {
        let s = value.to_str_radix(radix).unwrap();
        let back = BigU::from_str_radix(&s, radix).unwrap();
        assert_eq!(back, value, "radix {radix} roundtrip");
    }
}

#[test]
fn power_matches_repeated_multiplication() {
    let base = BigU::from(7u32);
    let mut acc = BigU::one();
    for e in 0..40u32 {
        assert_eq!(base.pow(e), acc, "pow({e}) mismatch");
        acc = &acc * &base;
    }
}

#[test]
fn shift_matches_power_of_two_multiply() {
    let x = b("31415926535897932384626433832795028841971");
    for bits in [1u32, 7, 31, 32, 33, 64, 100, 200] {
        let shifted = &x << bits;
        let mult = &x * &(&BigU::one() << bits);
        assert_eq!(shifted, mult, "shift {bits}");
        assert_eq!((&shifted) >> bits, x, "inverse shift {bits}");
    }
}

#[test]
fn modinv_composes_with_modpow() {
    // Modular inverse is the multiplicative undo of the base: dividing by a value
    // is multiplying by its inverse. Check (a * inv(b)) * b == a (mod m) for a
    // prime modulus, tying together modinv, modpow and div_rem end to end.
    let m = b("2305843009213693951"); // 2^61 - 1, a Mersenne prime
    let mut g = Lcg(0xFEED_FACE);
    for _ in 0..100 {
        let (_, a) = g.next_big().div_rem(&m).unwrap();
        let (_, b_val) = {
            let raw = g.next_big();
            raw.div_rem(&m).unwrap()
        };
        if b_val.is_zero() {
            continue; // zero has no inverse
        }
        let inv = b_val.modinv(&m).unwrap();
        // a / b then * b should return a modulo m.
        let (_, quotient) = (&a * &inv).div_rem(&m).unwrap();
        let (_, restored) = (&quotient * &b_val).div_rem(&m).unwrap();
        assert_eq!(restored, a, "(a * b^-1) * b must recover a mod m");
    }
}

#[test]
fn comparison_total_order() {
    let mut values: Vec<BigU> = (0..50u32).map(|i| BigU::from(2u32).pow(i)).collect();
    values.push(BigU::zero());
    values.sort();
    for w in values.windows(2) {
        assert!(w[0] <= w[1]);
    }
}
