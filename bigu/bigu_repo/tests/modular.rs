//! Integration tests for the modular reduction engine, the ring type and the
//! CRT basis.
//!
//! Two kinds of evidence are collected here. The known-answer tests use values
//! published elsewhere — the Wikipedia RSA worked example, Sun Tzu's remainder
//! problem, Euler's factorization of the fifth Fermat number, the Carmichael
//! numbers, Fermat's little theorem — so a self-consistent-but-wrong
//! implementation cannot pass them. The differential tests then compare every
//! ring operation against the crate's existing division-based path over
//! thousands of seeded pseudo-random cases.

use std::str::FromStr;

use bigu::{BigU, CrtBasis, Error, ModRing, Reduction};

/// xorshift64*, seeded explicitly so every failure is reproducible.
struct Rng(u64);

impl Rng {
    fn new(seed: u64) -> Rng {
        Rng(seed | 1)
    }

    fn next_u64(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }

    /// A value with `limbs` 32-bit limbs, top limb forced nonzero.
    fn big(&mut self, limbs: usize) -> BigU {
        let mut v = BigU::zero();
        for _ in 0..limbs {
            v = (v << 32) + BigU::from(self.next_u64() as u32);
        }
        if v.is_zero() {
            BigU::one()
        } else {
            v
        }
    }

    /// A value in `[1, bound)`.
    fn below(&mut self, bound: &BigU) -> BigU {
        let limbs = bound.bit_len().div_ceil(32) as usize + 1;
        let candidate = &self.big(limbs) % bound;
        if candidate.is_zero() {
            BigU::one()
        } else {
            candidate
        }
    }
}

fn big(s: &str) -> BigU {
    BigU::from_str(s).unwrap()
}

// ---------------------------------------------------------------------------
// Construction and strategy selection
// ---------------------------------------------------------------------------

#[test]
fn zero_modulus_is_rejected_by_every_constructor() {
    assert_eq!(ModRing::new(&BigU::zero()).unwrap_err(), Error::DivByZero);
    assert_eq!(
        ModRing::with_reduction(&BigU::zero(), Reduction::Montgomery).unwrap_err(),
        Error::DivByZero
    );
    assert_eq!(
        ModRing::with_reduction(&BigU::zero(), Reduction::Barrett).unwrap_err(),
        Error::DivByZero
    );
}

#[test]
fn odd_moduli_pick_montgomery_and_even_moduli_pick_barrett() {
    assert_eq!(
        ModRing::new(&BigU::from(97u32)).unwrap().reduction(),
        Reduction::Montgomery
    );
    assert_eq!(
        ModRing::new(&BigU::from(96u32)).unwrap().reduction(),
        Reduction::Barrett
    );
    // One is odd, so the trivial ring is a Montgomery ring.
    assert_eq!(
        ModRing::new(&BigU::one()).unwrap().reduction(),
        Reduction::Montgomery
    );
}

#[test]
fn montgomery_refuses_an_even_modulus() {
    let err = ModRing::with_reduction(&BigU::from(1024u32), Reduction::Montgomery).unwrap_err();
    assert_eq!(err, Error::EvenModulus);
    // Barrett accepts the same modulus without complaint.
    let ring = ModRing::with_reduction(&BigU::from(1024u32), Reduction::Barrett).unwrap();
    assert_eq!(ring.elem(&BigU::from(2049u32)).value(), BigU::one());
}

#[test]
fn barrett_can_be_forced_on_an_odd_modulus() {
    let ring = ModRing::with_reduction(&BigU::from(97u32), Reduction::Barrett).unwrap();
    assert_eq!(ring.reduction(), Reduction::Barrett);
    assert_eq!(ring.elem(&BigU::from(200u32)).value(), BigU::from(6u32));
}

#[test]
fn the_trivial_ring_collapses_everything_to_zero() {
    for reduction in [Reduction::Montgomery, Reduction::Barrett] {
        let ring = ModRing::with_reduction(&BigU::one(), reduction).unwrap();
        let a = ring.elem(&big("123456789012345678901234567890"));
        assert!(a.is_zero());
        assert!(ring.one().is_zero());
        // Zero is the multiplicative identity of the trivial ring.
        assert!(ring.one().is_one());
        assert_eq!(a.pow(&BigU::from(5u32)).value(), BigU::zero());
    }
}

#[test]
fn ring_reports_its_modulus_and_displays_its_strategy() {
    let ring = ModRing::new(&BigU::from(97u32)).unwrap();
    assert_eq!(ring.modulus(), &BigU::from(97u32));
    assert_eq!(ring.to_string(), "Z/97Z [Montgomery]");
    let barrett = ModRing::with_reduction(&BigU::from(97u32), Reduction::Barrett).unwrap();
    assert_eq!(barrett.to_string(), "Z/97Z [Barrett]");
    assert_eq!(format!("{}", Reduction::Barrett), "Barrett");
    assert!(format!("{:?}", ring).contains("ModRing"));
}

// ---------------------------------------------------------------------------
// Ring identity: elements must not mix
// ---------------------------------------------------------------------------

#[test]
fn elements_of_different_moduli_cannot_be_combined() {
    let seven = ModRing::new(&BigU::from(7u32)).unwrap();
    let eleven = ModRing::new(&BigU::from(11u32)).unwrap();
    let a = seven.elem(&BigU::from(3u32));
    let b = eleven.elem(&BigU::from(3u32));

    assert_eq!(a.checked_add(&b).unwrap_err(), Error::ModulusMismatch);
    assert_eq!(a.checked_sub(&b).unwrap_err(), Error::ModulusMismatch);
    assert_eq!(a.checked_mul(&b).unwrap_err(), Error::ModulusMismatch);
    // Equal residues, different rings: not equal.
    assert!(a != b);
}

#[test]
fn elements_of_the_same_modulus_but_different_engines_cannot_be_combined() {
    // Same modulus, different internal representation — mixing these would give
    // a wrong answer rather than an error, so the check must catch it.
    let mont = ModRing::with_reduction(&BigU::from(97u32), Reduction::Montgomery).unwrap();
    let barr = ModRing::with_reduction(&BigU::from(97u32), Reduction::Barrett).unwrap();
    assert!(!mont.is_compatible(&barr));
    let a = mont.elem(&BigU::from(5u32));
    let b = barr.elem(&BigU::from(5u32));
    assert_eq!(a.checked_mul(&b).unwrap_err(), Error::ModulusMismatch);
    // The residues agree even though the elements are incompatible.
    assert_eq!(a.value(), b.value());
}

#[test]
fn separately_built_rings_with_the_same_modulus_are_compatible() {
    let one = ModRing::new(&BigU::from(97u32)).unwrap();
    let two = ModRing::new(&BigU::from(97u32)).unwrap();
    assert!(one.is_compatible(&two));
    assert_eq!(one, two);
    let a = one.elem(&BigU::from(40u32));
    let b = two.elem(&BigU::from(60u32));
    assert_eq!(a.checked_add(&b).unwrap().value(), BigU::from(3u32));
    assert_eq!(a.ring().modulus(), &BigU::from(97u32));
}

#[test]
#[should_panic(expected = "different rings")]
fn the_add_operator_panics_across_rings() {
    let seven = ModRing::new(&BigU::from(7u32)).unwrap();
    let eleven = ModRing::new(&BigU::from(11u32)).unwrap();
    let _ = &seven.elem(&BigU::one()) + &eleven.elem(&BigU::one());
}

#[test]
#[should_panic(expected = "different rings")]
fn the_sub_operator_panics_across_rings() {
    let seven = ModRing::new(&BigU::from(7u32)).unwrap();
    let eleven = ModRing::new(&BigU::from(11u32)).unwrap();
    let _ = &seven.elem(&BigU::one()) - &eleven.elem(&BigU::one());
}

#[test]
#[should_panic(expected = "different rings")]
fn the_mul_operator_panics_across_rings() {
    let seven = ModRing::new(&BigU::from(7u32)).unwrap();
    let eleven = ModRing::new(&BigU::from(11u32)).unwrap();
    let _ = &seven.elem(&BigU::one()) * &eleven.elem(&BigU::one());
}

// ---------------------------------------------------------------------------
// Known answers from published sources
// ---------------------------------------------------------------------------

#[test]
fn the_textbook_modular_exponentiation_example_matches() {
    // 4^13 mod 497 == 445, the worked example in every treatment of
    // square-and-multiply.
    for reduction in [Reduction::Montgomery, Reduction::Barrett] {
        let ring = ModRing::with_reduction(&BigU::from(497u32), reduction).unwrap();
        assert_eq!(
            ring.pow(&BigU::from(4u32), &BigU::from(13u32)),
            BigU::from(445u32)
        );
    }
    assert_eq!(
        BigU::from(4u32)
            .modpow_fast(&BigU::from(13u32), &BigU::from(497u32))
            .unwrap(),
        BigU::from(445u32)
    );
}

#[test]
fn the_textbook_rsa_example_round_trips() {
    // p = 61, q = 53, n = 3233, e = 17, d = 413; encrypting 65 gives 2790.
    let ring = ModRing::new(&BigU::from(3233u32)).unwrap();
    let message = BigU::from(65u32);
    let cipher = ring.pow(&message, &BigU::from(17u32));
    assert_eq!(cipher, BigU::from(2790u32));
    assert_eq!(ring.pow(&cipher, &BigU::from(413u32)), message);
    // The private exponent is the inverse of e modulo the Carmichael function
    // lambda(n) = lcm(60, 52) = 780, not modulo phi(n) = 3120.
    let lambda = ModRing::new(&BigU::from(780u32)).unwrap();
    assert_eq!(
        lambda.elem(&BigU::from(17u32)).inv().unwrap().value(),
        BigU::from(413u32)
    );
    let phi = ModRing::new(&BigU::from(3120u32)).unwrap();
    assert_eq!(
        phi.elem(&BigU::from(17u32)).inv().unwrap().value(),
        BigU::from(2753u32)
    );
}

#[test]
fn euler_factor_of_the_fifth_fermat_number_is_found_modularly() {
    // F5 = 2^32 + 1 = 641 * 6700417 (Euler, 1732).
    let f5 = big("4294967297");
    let ring = ModRing::new(&BigU::from(641u32)).unwrap();
    assert!(ring.elem(&f5).is_zero());
    let (q, r) = f5.div_rem(&BigU::from(641u32)).unwrap();
    assert!(r.is_zero());
    assert_eq!(q, BigU::from(6700417u32));
}

#[test]
fn fermats_little_theorem_holds_for_a_large_prime() {
    // 2^127 - 1 is the Mersenne prime M127, so a^(p-1) == 1 for every a < p.
    let p = BigU::from(2u32).pow(127) - BigU::one();
    let ring = ModRing::new(&p).unwrap();
    let exp = &p - &BigU::one();
    for a in [2u32, 3, 5, 7, 1234567, 4294967295] {
        assert_eq!(ring.pow(&BigU::from(a), &exp), BigU::one());
    }
}

#[test]
fn carmichael_numbers_satisfy_the_fermat_congruence_but_are_composite() {
    // 561, 1105 and 1729 are the first three Carmichael numbers: a^n == a for
    // every a, yet all three are composite.
    for n in [561u32, 1105, 1729] {
        let modulus = BigU::from(n);
        let ring = ModRing::new(&modulus).unwrap();
        assert!(!modulus.is_prime());
        for a in 2u32..40 {
            let a = BigU::from(a);
            assert_eq!(ring.pow(&a, &modulus), &a % &modulus);
        }
    }
}

#[test]
fn a_quadratic_residue_matches_eulers_criterion() {
    // For an odd prime p, a^((p-1)/2) is 1 for a residue and p-1 otherwise.
    let p = BigU::from(101u32);
    let ring = ModRing::new(&p).unwrap();
    let exp = BigU::from(50u32);
    // 4 = 2^2 is a residue; 2 is not a residue modulo 101.
    assert_eq!(ring.pow(&BigU::from(4u32), &exp), BigU::one());
    assert_eq!(ring.pow(&BigU::from(2u32), &exp), BigU::from(100u32));
}

#[test]
fn sun_tzu_remainder_problem() {
    // "There are certain things whose number is unknown. Divided by 3 the
    // remainder is 2, by 5 the remainder is 3, by 7 the remainder is 2."
    let basis = CrtBasis::new(&[BigU::from(3u32), BigU::from(5u32), BigU::from(7u32)]).unwrap();
    let residues = [BigU::from(2u32), BigU::from(3u32), BigU::from(2u32)];
    assert_eq!(basis.reconstruct(&residues).unwrap(), BigU::from(23u32));
    assert_eq!(basis.product(), &BigU::from(105u32));
}

#[test]
fn brahmagupta_basket_of_eggs() {
    // Remainder 1 when counted in groups of 2..6, and exactly divisible by 7:
    // the smallest such count is 301.
    let basis = CrtBasis::new(&[
        BigU::from(3u32),
        BigU::from(4u32),
        BigU::from(5u32),
        BigU::from(7u32),
    ])
    .unwrap();
    let residues = [
        BigU::from(1u32),
        BigU::from(1u32),
        BigU::from(1u32),
        BigU::zero(),
    ];
    let x = basis.reconstruct(&residues).unwrap();
    assert_eq!(x, BigU::from(301u32));
    assert!(&x % &BigU::from(2u32) == BigU::one());
    assert!(&x % &BigU::from(6u32) == BigU::one());
}

// ---------------------------------------------------------------------------
// Differential tests against the existing division-based path
// ---------------------------------------------------------------------------

/// Every ring operation compared against the crate's naive `%` path.
fn differential_over(modulus: &BigU, reduction: Reduction, seed: u64, cases: usize) {
    let ring = ModRing::with_reduction(modulus, reduction).unwrap();
    let mut rng = Rng::new(seed);
    for _ in 0..cases {
        let a = rng.below(modulus);
        let b = rng.below(modulus);
        let ea = ring.elem(&a);
        let eb = ring.elem(&b);

        // Round trip through the internal representation.
        assert_eq!(ea.value(), &a % modulus);

        assert_eq!((&ea + &eb).value(), &(&a + &b) % modulus);
        assert_eq!((&ea * &eb).value(), &(&a * &b) % modulus);
        assert_eq!(ea.square().value(), &(&a * &a) % modulus);

        let expected_sub = if a >= b {
            &(&a - &b) % modulus
        } else {
            &(&(&a + modulus) - &b) % modulus
        };
        assert_eq!((&ea - &eb).value(), expected_sub);

        // Negation is the additive inverse.
        assert!((&ea + &(-&ea)).is_zero());

        // Exponentiation against the existing modpow.
        let e = BigU::from(rng.next_u64() % 4096);
        assert_eq!(ea.pow(&e).value(), a.modpow(&e, modulus).unwrap());
    }
}

#[test]
fn montgomery_agrees_with_division_on_single_limb_moduli() {
    // Straddles the limb boundary: just under, at, and just over 2^32.
    for m in ["4294967295", "4294967291", "4294967297", "2147483647"] {
        differential_over(&big(m), Reduction::Montgomery, 0xC0FFEE, 60);
    }
}

#[test]
fn montgomery_agrees_with_division_on_multi_limb_moduli() {
    let mut rng = Rng::new(0x5EED_1234);
    for limbs in [2usize, 3, 5, 8] {
        let m = rng.big(limbs) | BigU::one();
        differential_over(&m, Reduction::Montgomery, 0xABCD_0000 + limbs as u64, 25);
    }
}

#[test]
fn barrett_agrees_with_division_on_even_moduli() {
    let mut rng = Rng::new(0x1234_5EED);
    for limbs in [1usize, 2, 4, 7] {
        let mut m = rng.big(limbs);
        if &m % &BigU::from(2u32) == BigU::one() {
            m = &m + &BigU::one();
        }
        differential_over(&m, Reduction::Barrett, 0xFEED_0000 + limbs as u64, 25);
    }
}

#[test]
fn barrett_agrees_with_division_on_powers_of_two() {
    // Powers of two are the worst case for a reciprocal estimate: the quotient
    // lands exactly on a limb boundary.
    for exp in [1u32, 31, 32, 33, 64, 65, 128] {
        let m = BigU::from(2u32).pow(exp);
        differential_over(&m, Reduction::Barrett, 0x7000 + exp as u64, 20);
    }
}

#[test]
fn both_engines_agree_with_each_other_over_many_seeds() {
    // The two reducers are independent implementations, so agreeing on an odd
    // modulus is a real cross-check.
    let mut rng = Rng::new(0xDEAD_BEEF);
    let mut checks = 0usize;
    for limbs in [1usize, 2, 3, 6] {
        let m = rng.big(limbs) | BigU::one();
        let mont = ModRing::with_reduction(&m, Reduction::Montgomery).unwrap();
        let barr = ModRing::with_reduction(&m, Reduction::Barrett).unwrap();
        for _ in 0..200 {
            let a = rng.below(&m);
            let b = rng.below(&m);
            let e = BigU::from(rng.next_u64());
            assert_eq!(
                mont.elem(&a).checked_mul(&mont.elem(&b)).unwrap().value(),
                barr.elem(&a).checked_mul(&barr.elem(&b)).unwrap().value()
            );
            assert_eq!(mont.pow(&a, &e), barr.pow(&a, &e));
            checks += 1;
        }
    }
    assert_eq!(checks, 800);
}

#[test]
fn ring_axioms_hold_over_random_triples() {
    let mut rng = Rng::new(0x0BAD_C0DE);
    let m = big("115792089237316195423570985008687907853269984665640564039457584007913129639747");
    let ring = ModRing::new(&m).unwrap();
    for _ in 0..400 {
        let a = ring.elem(&rng.below(&m));
        let b = ring.elem(&rng.below(&m));
        let c = ring.elem(&rng.below(&m));

        // Associativity and commutativity of both operations.
        assert_eq!(&(&a + &b) + &c, &a + &(&b + &c));
        assert_eq!(&(&a * &b) * &c, &a * &(&b * &c));
        assert_eq!(&a + &b, &b + &a);
        assert_eq!(&a * &b, &b * &a);
        // Distributivity ties them together.
        assert_eq!(&a * &(&b + &c), &(&a * &b) + &(&a * &c));
        // Identities and inverses.
        assert_eq!(&a + &ring.zero(), a);
        assert_eq!(&a * &ring.one(), a);
        assert_eq!(&(&a - &b) + &b, a);
        assert!((&a * &ring.zero()).is_zero());
    }
}

#[test]
fn exponent_laws_hold_over_random_cases() {
    let mut rng = Rng::new(0x1357_9BDF);
    let m = big("340282366920938463463374607431768211507");
    let ring = ModRing::new(&m).unwrap();
    for _ in 0..120 {
        let a = ring.elem(&rng.below(&m));
        let i = BigU::from(rng.next_u64() % 512);
        let j = BigU::from(rng.next_u64() % 512);
        // a^i * a^j == a^(i+j)
        assert_eq!(&a.pow(&i) * &a.pow(&j), a.pow(&(&i + &j)));
        // (a^i)^j == a^(i*j)
        assert_eq!(a.pow(&i).pow(&j), a.pow(&(&i * &j)));
    }
}

#[test]
fn pow_matches_modpow_on_boundary_exponents() {
    let m = big("18446744073709551629");
    let ring = ModRing::new(&m).unwrap();
    let a = BigU::from(3u32);
    for e in [
        BigU::zero(),
        BigU::one(),
        BigU::from(2u32),
        BigU::from(u32::MAX),
        BigU::from(u64::MAX),
        &m - &BigU::one(),
    ] {
        assert_eq!(ring.pow(&a, &e), a.modpow(&e, &m).unwrap());
    }
    // Zero to the zero follows the crate's 0^0 == 1 convention.
    assert_eq!(ring.pow(&BigU::zero(), &BigU::zero()), BigU::one());
}

#[test]
fn modpow_fast_matches_modpow_over_random_cases() {
    let mut rng = Rng::new(0x2468_ACE0);
    for _ in 0..200 {
        let m = rng.big(2);
        let a = rng.big(3);
        let e = BigU::from(rng.next_u64() % 1024);
        assert_eq!(
            a.modpow_fast(&e, &m).unwrap(),
            a.modpow(&e, &m).unwrap(),
            "mismatch for {a}^{e} mod {m}"
        );
    }
    assert_eq!(
        BigU::one()
            .modpow_fast(&BigU::one(), &BigU::zero())
            .unwrap_err(),
        Error::DivByZero
    );
}

// ---------------------------------------------------------------------------
// Inversion
// ---------------------------------------------------------------------------

#[test]
fn inverses_multiply_back_to_one() {
    let mut rng = Rng::new(0x1111_2222);
    let p = big("170141183460469231731687303715884105727"); // M127, prime
    let ring = ModRing::new(&p).unwrap();
    for _ in 0..60 {
        let a = ring.elem(&rng.below(&p));
        let inv = a.inv().unwrap();
        assert!((&a * &inv).is_one());
    }
}

#[test]
fn inverse_fails_when_a_factor_is_shared() {
    let ring = ModRing::new(&BigU::from(9u32)).unwrap();
    assert_eq!(
        ring.elem(&BigU::from(6u32)).inv().unwrap_err(),
        Error::NotInvertible
    );
    // Zero is never invertible in a nontrivial ring.
    assert_eq!(ring.zero().inv().unwrap_err(), Error::NotInvertible);
    // But it is in the trivial ring, where zero is the identity.
    let trivial = ModRing::new(&BigU::one()).unwrap();
    assert!(trivial.zero().inv().unwrap().is_zero());
}

#[test]
fn inversion_works_through_the_barrett_engine_too() {
    let ring = ModRing::with_reduction(&BigU::from(780u32), Reduction::Barrett).unwrap();
    let e = ring.elem(&BigU::from(17u32));
    assert_eq!(e.inv().unwrap().value(), BigU::from(413u32));
    assert!((&e * &e.inv().unwrap()).is_one());
}

// ---------------------------------------------------------------------------
// Element bookkeeping
// ---------------------------------------------------------------------------

#[test]
fn elements_reduce_oversized_inputs_on_entry() {
    let ring = ModRing::new(&BigU::from(97u32)).unwrap();
    let huge = big("999999999999999999999999999999999999999999");
    assert_eq!(ring.elem(&huge).value(), &huge % &BigU::from(97u32));
    assert_eq!(ring.elem(&BigU::zero()).value(), BigU::zero());
    assert!(ring.elem(&BigU::from(97u32)).is_zero());
}

#[test]
fn zero_and_one_behave_as_identities() {
    for reduction in [Reduction::Montgomery, Reduction::Barrett] {
        let ring = ModRing::with_reduction(&BigU::from(4294967291u32), reduction).unwrap();
        assert!(ring.zero().is_zero());
        assert!(ring.one().is_one());
        assert_eq!(ring.one().value(), BigU::one());
        assert!(!ring.zero().is_one());
        let a = ring.elem(&BigU::from(123456789u32));
        assert_eq!((&a - &a).value(), BigU::zero());
        assert_eq!((&a * &ring.one()).value(), a.value());
        assert_eq!((-&ring.zero()).value(), BigU::zero());
    }
}

#[test]
fn display_and_debug_show_the_ordinary_residue() {
    let ring = ModRing::new(&BigU::from(97u32)).unwrap();
    let a = ring.elem(&BigU::from(200u32));
    assert_eq!(a.to_string(), "6");
    assert!(format!("{a:?}").contains("ModInt"));
    let cloned = a.clone();
    assert_eq!(cloned, a);
}

// ---------------------------------------------------------------------------
// CRT basis
// ---------------------------------------------------------------------------

#[test]
fn a_basis_rejects_degenerate_input() {
    assert_eq!(CrtBasis::new(&[]).unwrap_err(), Error::EmptyBasis);
    assert_eq!(
        CrtBasis::new(&[BigU::from(3u32), BigU::zero()]).unwrap_err(),
        Error::DivByZero
    );
    // 6 and 10 share the factor 2.
    assert_eq!(
        CrtBasis::new(&[BigU::from(6u32), BigU::from(10u32)]).unwrap_err(),
        Error::NotCoprime
    );
}

#[test]
fn a_single_modulus_basis_is_plain_reduction() {
    let basis = CrtBasis::new(&[BigU::from(97u32)]).unwrap();
    assert_eq!(basis.len(), 1);
    assert!(!basis.is_empty());
    assert_eq!(basis.moduli(), &[BigU::from(97u32)]);
    let residues = basis.reduce(&BigU::from(200u32));
    assert_eq!(residues, vec![BigU::from(6u32)]);
    assert_eq!(basis.reconstruct(&residues).unwrap(), BigU::from(6u32));
}

#[test]
fn reduce_and_reconstruct_round_trip_over_random_values() {
    let moduli = vec![
        big("4294967291"),
        big("4294967279"),
        big("4294967231"),
        big("4294967197"),
    ];
    let basis = CrtBasis::new(&moduli).unwrap();
    let mut rng = Rng::new(0x9999_7777);
    for _ in 0..500 {
        let x = rng.below(basis.product());
        let residues = basis.reduce(&x);
        assert_eq!(basis.reconstruct(&residues).unwrap(), x);
    }
}

#[test]
fn reconstruction_is_congruent_to_every_residue() {
    let basis = CrtBasis::new(&[
        BigU::from(11u32),
        BigU::from(13u32),
        BigU::from(17u32),
        BigU::from(19u32),
    ])
    .unwrap();
    let mut rng = Rng::new(0x4242_4242);
    for _ in 0..300 {
        let residues: Vec<BigU> = basis.moduli().iter().map(|m| rng.below(m)).collect();
        let x = basis.reconstruct(&residues).unwrap();
        assert!(x < *basis.product());
        for (r, m) in residues.iter().zip(basis.moduli()) {
            assert_eq!(&x % m, r % m);
        }
    }
}

#[test]
fn residues_larger_than_their_modulus_are_accepted() {
    let basis = CrtBasis::new(&[BigU::from(3u32), BigU::from(5u32), BigU::from(7u32)]).unwrap();
    // 2 + 105, 3 + 105, 2 + 105 all reduce back to the Sun Tzu residues.
    let shifted = [BigU::from(107u32), BigU::from(108u32), BigU::from(107u32)];
    assert_eq!(basis.reconstruct(&shifted).unwrap(), BigU::from(23u32));
}

#[test]
fn a_wrong_residue_count_is_an_error() {
    let basis = CrtBasis::new(&[BigU::from(3u32), BigU::from(5u32)]).unwrap();
    assert_eq!(
        basis.reconstruct(&[BigU::one()]).unwrap_err(),
        Error::ModulusMismatch
    );
    let ring = ModRing::new(&BigU::from(3u32)).unwrap();
    assert_eq!(
        basis
            .reconstruct_ints(&[ring.elem(&BigU::one())])
            .unwrap_err(),
        Error::ModulusMismatch
    );
}

#[test]
fn multi_modular_multiplication_reconstructs_the_true_product() {
    // Compute a product entirely in the residue channels and rebuild it. This
    // is the whole point of the CRT layer, and the answer is checked against
    // ordinary big-integer multiplication.
    let moduli = vec![
        big("4294967291"),
        big("4294967279"),
        big("4294967231"),
        big("4294967197"),
        big("4294967189"),
    ];
    let basis = CrtBasis::new(&moduli).unwrap();
    let rings = basis.rings().unwrap();
    assert_eq!(rings.len(), 5);

    let mut rng = Rng::new(0x1A2B_3C4D);
    for _ in 0..80 {
        let a = rng.big(2);
        let b = rng.big(2);
        let product = &a * &b;
        assert!(product < *basis.product());

        let channels: Vec<_> = rings
            .iter()
            .map(|r| r.elem(&a).checked_mul(&r.elem(&b)).unwrap())
            .collect();
        assert_eq!(basis.reconstruct_ints(&channels).unwrap(), product);
    }
}

#[test]
fn reconstruct_ints_rejects_channels_from_the_wrong_ring() {
    let basis = CrtBasis::new(&[BigU::from(3u32), BigU::from(5u32)]).unwrap();
    let three = ModRing::new(&BigU::from(3u32)).unwrap();
    let seven = ModRing::new(&BigU::from(7u32)).unwrap();
    let channels = [three.elem(&BigU::one()), seven.elem(&BigU::one())];
    assert_eq!(
        basis.reconstruct_ints(&channels).unwrap_err(),
        Error::ModulusMismatch
    );
}

#[test]
fn bases_compare_and_display() {
    let small = CrtBasis::new(&[BigU::from(3u32), BigU::from(5u32)]).unwrap();
    let large = CrtBasis::new(&[BigU::from(3u32), BigU::from(5u32), BigU::from(7u32)]).unwrap();
    let same = CrtBasis::new(&[BigU::from(3u32), BigU::from(5u32)]).unwrap();
    assert_eq!(small, same);
    assert!(small != large);
    assert!(small < large);
    assert_eq!(large.to_string(), "CRT basis of 3 moduli, range 105");
    assert!(format!("{small:?}").contains("CrtBasis"));
    assert_eq!(small.clone().len(), 2);
}

#[test]
fn a_basis_of_one_bit_moduli_still_reconstructs() {
    // A modulus of 1 is coprime to everything and contributes nothing.
    let basis = CrtBasis::new(&[BigU::one(), BigU::from(5u32)]).unwrap();
    assert_eq!(basis.product(), &BigU::from(5u32));
    assert_eq!(
        basis
            .reconstruct(&[BigU::zero(), BigU::from(3u32)])
            .unwrap(),
        BigU::from(3u32)
    );
}

// ---------------------------------------------------------------------------
// Error surface
// ---------------------------------------------------------------------------

#[test]
fn the_new_errors_render_readable_messages() {
    assert_eq!(
        Error::EvenModulus.to_string(),
        "Montgomery reduction requires an odd modulus"
    );
    assert_eq!(
        Error::ModulusMismatch.to_string(),
        "values do not share a modulus"
    );
    assert_eq!(
        Error::NotCoprime.to_string(),
        "moduli are not pairwise coprime"
    );
    assert_eq!(
        Error::EmptyBasis.to_string(),
        "cannot build a basis with no moduli"
    );
}
