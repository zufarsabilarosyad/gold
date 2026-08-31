//! Integration tests for `BigQ`: differential checks against a naive
//! reduce-after-the-fact rational model, plus decimal-expansion oracles.

use bigu::{BigI, BigQ, BigU};
use std::str::FromStr;

/// Splitmix-ish generator, same shape the other suites use.
struct Lcg(u64);
impl Lcg {
    fn next(&mut self) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        self.0
    }
    fn next_q(&mut self) -> BigQ {
        let n = (self.next() as i64) >> 20;
        let d = ((self.next() >> 40) as i64).max(1);
        BigQ::new(BigI::from(n), BigI::from(d)).unwrap()
    }
}

fn q(s: &str) -> BigQ {
    BigQ::from_str(s).unwrap()
}

/// Naive model: form the textbook cross products, reduce once at the end via
/// the public constructor. Any disagreement with the Knuth path is a bug in
/// the cross-gcd bookkeeping.
fn naive_add(a: &BigQ, b: &BigQ) -> BigQ {
    let bd = BigI::from_biguint(b.denom().clone());
    let ad = BigI::from_biguint(a.denom().clone());
    let num = &(a.numer() * &bd) + &(b.numer() * &ad);
    BigQ::new(num, &ad * &bd).unwrap()
}

fn naive_mul(a: &BigQ, b: &BigQ) -> BigQ {
    let num = a.numer() * b.numer();
    let den = BigI::from_biguint(a.denom() * b.denom());
    BigQ::new(num, den).unwrap()
}

#[test]
fn knuth_paths_match_the_naive_model() {
    let mut g = Lcg(0xB16_0001);
    for _ in 0..500 {
        let a = g.next_q();
        let b = g.next_q();
        assert_eq!(&a + &b, naive_add(&a, &b));
        assert_eq!(&a * &b, naive_mul(&a, &b));
        assert_eq!(&(&a - &b) + &b, a);
        if !b.is_zero() {
            assert_eq!(&(&a / &b) * &b, a);
        }
    }
}

#[test]
fn results_are_always_in_lowest_terms() {
    let mut g = Lcg(0xB16_0002);
    for _ in 0..300 {
        let a = g.next_q();
        let b = g.next_q();
        for v in [&a + &b, &a - &b, &a * &b] {
            assert_eq!(v.numer().magnitude().gcd(v.denom()), BigU::one());
            assert!(!v.denom().is_zero());
            if v.is_zero() {
                assert_eq!(v.denom(), &BigU::one());
            }
        }
    }
}

#[test]
fn ordering_agrees_with_decimal_expansion() {
    let mut g = Lcg(0xB16_0003);
    for _ in 0..200 {
        let a = g.next_q();
        let b = g.next_q();
        // 40 places is far beyond the resolution of these operands, so the
        // string comparison of expansions is a faithful ordering oracle for
        // same-sign pairs of equal integer-part width.
        if a.signum() == 1 && b.signum() == 1 {
            let (da, db) = (a.to_decimal(40), b.to_decimal(40));
            if da.len() == db.len() {
                assert_eq!(a.cmp(&b), da.cmp(&db), "{a} vs {b}");
            }
        }
    }
}

#[test]
fn decimal_expansion_matches_long_division() {
    // 1/7 repeats with period 6: 0.142857 142857 ...
    assert_eq!(q("1/7").to_decimal(12), "0.142857142857");
    // 22/7 rounds at the cut, not truncates.
    assert_eq!(q("22/7").to_decimal(4), "3.1429");
    assert_eq!(q("-22/7").to_decimal(4), "-3.1429");
    // Terminating expansions come out exact and zero-padded.
    assert_eq!(q("1/8").to_decimal(6), "0.125000");
    assert_eq!(q("5").to_decimal(0), "5");
}

#[test]
fn round_trip_through_strings() {
    let mut g = Lcg(0xB16_0004);
    for _ in 0..200 {
        let a = g.next_q();
        assert_eq!(BigQ::from_str(&format!("{a}")).unwrap(), a);
    }
}

#[test]
fn big_operands_stay_exact() {
    // (2^128 + 1) / 2^128, minus 1, is exactly 1 / 2^128 — a value no float
    // can represent. 2^128 = 340282366920938463463374607431768211456.
    let big = BigU::from_str("340282366920938463463374607431768211456").unwrap();
    let a = BigQ::new(
        BigI::from_biguint(&big + &BigU::one()),
        BigI::from_biguint(big.clone()),
    )
    .unwrap();
    let tiny = &a - &BigQ::one();
    assert_eq!(tiny.numer(), &BigI::one());
    assert_eq!(tiny.denom(), &big);
    assert!(tiny.is_terminating());
    assert_eq!(tiny.to_decimal(45), "0.000000000000000000000000000000000000002938736");
}
