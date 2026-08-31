//! End-to-end checks for primality testing and factorization.
//!
//! The oracle here is a plain sieve of Eratosthenes over `u64`, built
//! independently of anything in the crate, so agreement between the two is real
//! evidence rather than a restatement of the implementation.

use bigu::BigU;
use std::str::FromStr;

fn b(s: &str) -> BigU {
    BigU::from_str(s).unwrap()
}

/// Sieve of Eratosthenes: `out[i]` is true exactly when `i` is prime.
fn sieve(limit: usize) -> Vec<bool> {
    let mut is_p = vec![true; limit + 1];
    is_p[0] = false;
    if limit >= 1 {
        is_p[1] = false;
    }
    let mut p = 2usize;
    while p * p <= limit {
        if is_p[p] {
            let mut m = p * p;
            while m <= limit {
                is_p[m] = false;
                m += p;
            }
        }
        p += 1;
    }
    is_p
}

#[test]
fn is_prime_matches_a_sieve_to_fifty_thousand() {
    let limit = 50_000usize;
    let is_p = sieve(limit);
    for n in 0..=limit {
        assert_eq!(
            BigU::from(n as u64).is_prime(),
            is_p[n],
            "primality disagreement at {n}"
        );
    }
}

#[test]
fn next_prime_walks_the_sieve_in_order() {
    let limit = 20_000usize;
    let is_p = sieve(limit);
    // Collect the primes the crate reports by repeatedly stepping forward, and
    // compare the whole sequence against the sieve's.
    let expected: Vec<usize> = (0..=limit).filter(|&i| is_p[i]).collect();

    let mut walked = Vec::new();
    let mut cur = BigU::zero();
    loop {
        cur = cur.next_prime();
        let as_u64 = u64::try_from(&cur).unwrap() as usize;
        if as_u64 > limit {
            break;
        }
        walked.push(as_u64);
    }
    assert_eq!(walked, expected, "next_prime sequence diverged");
}

#[test]
fn prev_prime_walks_the_sieve_backwards() {
    let limit = 5_000usize;
    let is_p = sieve(limit);
    let mut expected: Vec<usize> = (0..limit).filter(|&i| is_p[i]).collect();
    expected.reverse();

    let mut walked = Vec::new();
    let mut cur = BigU::from(limit as u64);
    while let Some(p) = cur.prev_prime() {
        walked.push(u64::try_from(&p).unwrap() as usize);
        cur = p;
    }
    assert_eq!(walked, expected, "prev_prime sequence diverged");
}

#[test]
fn factorization_multiplies_back_across_a_wide_range() {
    for n in 2u64..3_000 {
        let v = BigU::from(n);
        let factors = v.factor();
        assert!(!factors.is_empty(), "{n} must have factors");
        let mut product = BigU::one();
        let mut last: Option<BigU> = None;
        for (p, e) in &factors {
            assert!(p.is_prime(), "{p:?} is not prime (factor of {n})");
            assert!(*e >= 1, "exponent must be positive");
            if let Some(prev) = &last {
                assert!(prev < p, "factors of {n} are not ascending");
            }
            last = Some(p.clone());
            product = &product * &p.pow(*e);
        }
        assert_eq!(product, v, "factors of {n} do not multiply back");
    }
}

#[test]
fn factorization_agrees_with_naive_trial_division() {
    // An independent factorizer, written the obvious way.
    fn naive(mut n: u64) -> Vec<(u64, u32)> {
        let mut out = Vec::new();
        let mut d = 2u64;
        while d * d <= n {
            if n % d == 0 {
                let mut c = 0;
                while n % d == 0 {
                    n /= d;
                    c += 1;
                }
                out.push((d, c));
            }
            d += 1;
        }
        if n > 1 {
            out.push((n, 1));
        }
        out
    }

    for n in [
        2u64,
        97,
        360,
        1024,
        999_983,
        1_000_000,
        123_456_789,
        4_294_967_295,
        1_000_000_007,
        600_851_475_143,
    ] {
        let got: Vec<(u64, u32)> = BigU::from(n)
            .factor()
            .into_iter()
            .map(|(p, e)| (u64::try_from(&p).unwrap(), e))
            .collect();
        assert_eq!(got, naive(n), "factorization mismatch for {n}");
    }
}

#[test]
fn large_known_primes_and_their_neighbours() {
    // Mersenne primes M89, M107 and M127, each well past a u128.
    for p in [89u32, 107, 127] {
        let m = BigU::from(2u32).pow(p) - BigU::one();
        assert!(m.is_prime(), "M{p} must be prime");
        // A Mersenne prime is odd, so both neighbours are even composites.
        assert!(!(&m + &BigU::one()).is_prime());
        assert!(!(m.checked_sub(&BigU::one()).unwrap()).is_prime());
    }
}

#[test]
fn a_large_semiprime_is_composite_and_splits() {
    // Both factors are above the trial-division bound, so the sieve cannot help
    // and Miller-Rabin has to carry the verdict.
    let p = b("1000003");
    let q = b("1000033");
    let n = &p * &q;
    assert!(!n.is_prime());
    assert_eq!(n.factor(), vec![(p, 1), (q, 1)]);
}

#[test]
fn primality_survives_a_string_roundtrip() {
    // A value's primality must not depend on how it was constructed.
    for s in [
        "170141183460469231731687303715884105727",
        "1000000007",
        "4294967291",
        "561",
        "1373653",
    ] {
        let direct = b(s);
        let viahex = BigU::from_str_radix(&direct.to_str_radix(16).unwrap(), 16).unwrap();
        assert_eq!(direct, viahex);
        assert_eq!(direct.is_prime(), viahex.is_prime(), "{s}");
    }
}

#[test]
fn modinv_exists_for_every_nonzero_residue_of_a_prime() {
    // Ties primality to the modular arithmetic: modulo a prime every nonzero
    // residue is invertible, and modulo a composite some are not.
    let p = BigU::from(1009u32);
    assert!(p.is_prime());
    for a in 1u32..1009 {
        let inv = BigU::from(a).modinv(&p).expect("prime modulus inverts all");
        let prod = (&BigU::from(a) * &inv).div_rem(&p).unwrap().1;
        assert_eq!(prod, BigU::one(), "inverse of {a} mod 1009");
    }

    let composite = BigU::from(1000u32);
    assert!(!composite.is_prime());
    // 10 shares a factor with 1000, so it has no inverse.
    assert!(BigU::from(10u32).modinv(&composite).is_err());
}

#[test]
fn fermat_little_theorem_holds_for_reported_primes() {
    // For a prime p and any a not divisible by p, a^(p-1) == 1 (mod p).
    for p_seed in [101u32, 1009, 65537] {
        let p = BigU::from(p_seed);
        assert!(p.is_prime());
        let exp = p.checked_sub(&BigU::one()).unwrap();
        for a in [2u32, 3, 5, 7, 99] {
            let a = BigU::from(a);
            if !a.is_coprime(&p) {
                continue;
            }
            assert_eq!(
                a.modpow(&exp, &p).unwrap(),
                BigU::one(),
                "Fermat failed for base {a:?} mod {p:?}"
            );
        }
    }
}

#[test]
fn totient_of_a_semiprime_matches_the_closed_form() {
    // For distinct primes p and q, phi(p*q) == (p-1)*(q-1).
    for (p, q) in [(101u32, 103u32), (1009, 1013), (65521, 65537)] {
        let bp = BigU::from(p);
        let bq = BigU::from(q);
        assert!(bp.is_prime() && bq.is_prime());
        let n = &bp * &bq;
        let expected = &bp.checked_sub(&BigU::one()).unwrap() * &bq.checked_sub(&BigU::one()).unwrap();
        assert_eq!(n.euler_phi(), expected, "phi({p}*{q})");
    }
}

#[test]
fn rsa_style_roundtrip_exercises_the_whole_stack() {
    // Primality, factorization-free totient, modular inverse and modular
    // exponentiation all have to agree for this to close.
    let p = b("1000003");
    let q = b("1000033");
    assert!(p.is_prime() && q.is_prime());

    let n = &p * &q;
    let phi = &p.checked_sub(&BigU::one()).unwrap() * &q.checked_sub(&BigU::one()).unwrap();
    assert_eq!(n.euler_phi(), phi, "totient must match the closed form");

    // A standard public exponent, and its inverse as the private one.
    let e = BigU::from(65537u32);
    assert!(e.is_coprime(&phi));
    let d = e.modinv(&phi).expect("e is coprime to phi");
    // e*d == 1 (mod phi) is what makes the round trip work.
    assert_eq!((&e * &d).div_rem(&phi).unwrap().1, BigU::one());

    for message in ["42", "999999999", "123456789012"] {
        let m = b(message);
        assert!(m < n, "message must be reducible");
        let cipher = m.modpow(&e, &n).unwrap();
        let plain = cipher.modpow(&d, &n).unwrap();
        assert_eq!(plain, m, "round trip failed for {message}");
    }
}

#[test]
fn divisors_of_a_highly_composite_number() {
    // 5040 == 2^4 * 3^2 * 5 * 7 has 60 divisors.
    let n = BigU::from(5040u32);
    assert_eq!(n.divisor_count(), BigU::from(60u32));
    let d = n.divisors();
    assert_eq!(d.len(), 60);
    assert_eq!(d[0], BigU::one());
    assert_eq!(d[59], n);
    // The divisors pair up: d[i] * d[59-i] == n.
    for i in 0..60 {
        assert_eq!(&d[i] * &d[59 - i], n, "divisor pairing at {i}");
    }
}

#[test]
fn coprimality_is_consistent_with_factorization() {
    // Two values are coprime exactly when they share no prime factor.
    for (x, y) in [(90u64, 77u64), (90, 84), (1, 0), (36, 36), (1009, 1013)] {
        let bx = BigU::from(x);
        let by = BigU::from(y);
        let fx: Vec<BigU> = bx.factor().into_iter().map(|(p, _)| p).collect();
        let fy: Vec<BigU> = by.factor().into_iter().map(|(p, _)| p).collect();
        let shares = fx.iter().any(|p| fy.contains(p));
        assert_eq!(bx.is_coprime(&by), !shares, "coprimality of {x} and {y}");
    }
}
