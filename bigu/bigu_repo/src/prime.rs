//! Primality testing and integer factorization.
//!
//! Three layers cooperate, cheapest first:
//!
//! * trial division against every prime below 1000 ([`SMALL_PRIMES`]), which
//!   settles small inputs outright and strips the easy factors off large ones;
//! * a strong probable-prime (Miller-Rabin) test, run over the fixed base set
//!   [`MR_BASES`] — the first thirteen primes, which is *proven* to have no
//!   composite survivors below [`DETERMINISTIC_PRIME_BOUND`];
//! * Brent's variant of Pollard's rho to split the composite cofactor that
//!   survives trial division.
//!
//! Everything is exact integer work: no floating point appears on any path
//! here, and every modular step routes through the panic-free
//! [`BigU::div_rem`].

use crate::bigu::BigU;
use crate::{DoubleLimb, Limb};

/// Every prime below 1000, used for trial division.
///
/// The bound is a deliberate trade: it is cheap enough to run unconditionally
/// yet removes the overwhelming majority of composites before the far more
/// expensive Miller-Rabin and rho stages ever start.
pub const SMALL_PRIMES: [u32; 168] = [
    2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97,
    101, 103, 107, 109, 113, 127, 131, 137, 139, 149, 151, 157, 163, 167, 173, 179, 181, 191, 193,
    197, 199, 211, 223, 227, 229, 233, 239, 241, 251, 257, 263, 269, 271, 277, 281, 283, 293, 307,
    311, 313, 317, 331, 337, 347, 349, 353, 359, 367, 373, 379, 383, 389, 397, 401, 409, 419, 421,
    431, 433, 439, 443, 449, 457, 461, 463, 467, 479, 487, 491, 499, 503, 509, 521, 523, 541, 547,
    557, 563, 569, 571, 577, 587, 593, 599, 601, 607, 613, 617, 619, 631, 641, 643, 647, 653, 659,
    661, 673, 677, 683, 691, 701, 709, 719, 727, 733, 739, 743, 751, 757, 761, 769, 773, 787, 797,
    809, 811, 821, 823, 827, 829, 839, 853, 857, 859, 863, 877, 881, 883, 887, 907, 911, 919, 929,
    937, 941, 947, 953, 967, 971, 977, 983, 991, 997,
];

/// The Miller-Rabin bases used by [`BigU::is_prime`]: the first thirteen primes.
pub const MR_BASES: [u32; 13] = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41];

/// Decimal form of the bound below which [`BigU::is_prime`] is *exact*.
///
/// No composite below this value is a strong probable prime to all of
/// [`MR_BASES`] simultaneously, so under it the test decides primality outright
/// rather than merely making it overwhelmingly likely. The value is
/// `3317044064679887385961981`, a published result (Sorenson and Webster).
pub const DETERMINISTIC_PRIME_BOUND: &str = "3317044064679887385961981";

/// Remainder of a limb slice by one nonzero limb, without building a quotient.
///
/// Trial division only ever wants the remainder, and skipping the quotient
/// vector avoids an allocation per candidate prime.
fn rem_small(a: &[Limb], divisor: Limb) -> Limb {
    debug_assert!(divisor != 0);
    let mut rem: DoubleLimb = 0;
    for i in (0..a.len()).rev() {
        rem = ((rem << 32) | a[i] as DoubleLimb) % divisor as DoubleLimb;
    }
    rem as Limb
}

/// True when the value equals the single-limb constant `v`.
fn eq_limb(x: &BigU, v: Limb) -> bool {
    x.limbs.len() == 1 && x.limbs[0] == v
}

impl BigU {
    /// Returns the smallest prime factor of `self` that is below 1000, or
    /// `None` when no such factor exists.
    ///
    /// A prime under the bound reports *itself*, since a prime's smallest prime
    /// factor is the prime. `0` and `1` have no prime factors and both yield
    /// `None`, as does any value whose factors all sit at or above 1000.
    pub fn small_factor(&self) -> Option<u32> {
        if self.limbs.is_empty() || eq_limb(self, 1) {
            return None;
        }
        SMALL_PRIMES
            .iter()
            .copied()
            .find(|&p| rem_small(&self.limbs, p) == 0)
    }

    /// Returns `true` when `self` is a strong probable prime to the given base,
    /// i.e. when `base` fails to prove `self` composite.
    ///
    /// This is the single Miller-Rabin round. Writing `self - 1` as `d * 2^s`
    /// with `d` odd, the base is a *witness* to compositeness unless `base^d`
    /// is `1` or some `base^(d * 2^r)` with `r < s` is `-1`. Bases that are
    /// `0`, `1` or `-1` modulo `self` carry no information and are reported as
    /// non-witnesses, so passing them never falsely condemns a prime.
    ///
    /// A `true` answer is evidence, not proof: `2047 == 23 * 89` is a strong
    /// probable prime to base 2. Use [`BigU::is_prime`], which runs the whole
    /// of [`MR_BASES`], to decide primality.
    pub fn is_strong_probable_prime(&self, base: &BigU) -> bool {
        if self.limbs.is_empty() || eq_limb(self, 1) {
            return false;
        }
        if eq_limb(self, 2) {
            return true;
        }
        // Even values above two are composite and no base is needed to say so.
        if !self.bit(0) {
            return false;
        }

        let n_minus_1 = self.checked_sub(&BigU::one()).expect("self >= 2");
        // `self` is odd and above two, so `n - 1` is even and nonzero.
        let s = n_minus_1
            .trailing_zeros()
            .expect("n - 1 is nonzero for odd n > 2");
        // A value with more than 2^32 trailing zeros cannot be held in memory.
        let d = n_minus_1.shr_ref(s as u32);

        // Reduce the base; 0, 1 and n-1 say nothing about n either way.
        let (_, a) = base.div_rem(self).expect("self >= 2 is nonzero");
        if a.limbs.is_empty() || eq_limb(&a, 1) || a == n_minus_1 {
            return true;
        }

        let mut x = a.modpow(&d, self).expect("modulus is nonzero");
        if eq_limb(&x, 1) || x == n_minus_1 {
            return true;
        }
        // Square up through the remaining s-1 levels looking for -1.
        for _ in 1..s {
            x = (&x * &x).div_rem(self).expect("modulus is nonzero").1;
            if x == n_minus_1 {
                return true;
            }
        }
        false
    }

    /// Returns `true` when `self` is prime.
    ///
    /// `0` and `1` are not prime, `2` is. Below
    /// [`DETERMINISTIC_PRIME_BOUND`] the answer is exact; above it the value has
    /// passed every base in [`MR_BASES`], which makes a composite result
    /// vanishingly unlikely but not impossible.
    ///
    /// Trial division runs first, so a value with any factor below 1000 is
    /// rejected without a single modular exponentiation.
    ///
    /// ```
    /// use bigu::BigU;
    /// assert!(BigU::from(97u32).is_prime());
    /// assert!(!BigU::from(1u32).is_prime());
    /// // 2^31 - 1 is the Mersenne prime M31.
    /// assert!((BigU::from(2u32).pow(31) - BigU::one()).is_prime());
    /// // 2^11 - 1 == 2047 == 23 * 89 is not, despite fooling base 2 alone.
    /// assert!(!(BigU::from(2u32).pow(11) - BigU::one()).is_prime());
    /// ```
    pub fn is_prime(&self) -> bool {
        if self.limbs.is_empty() || eq_limb(self, 1) {
            return false;
        }
        // A trial-division hit is conclusive either way: the value is prime
        // exactly when it *is* the factor that was found.
        if let Some(f) = self.small_factor() {
            return eq_limb(self, f);
        }
        MR_BASES
            .iter()
            .all(|&a| self.is_strong_probable_prime(&BigU::from(a)))
    }

    /// Returns the smallest prime strictly greater than `self`.
    ///
    /// Every value below `2` maps to `2`, the smallest prime of all. The search
    /// steps through odd candidates only, so it never tests an even number
    /// beyond the initial `2`.
    ///
    /// ```
    /// use bigu::BigU;
    /// assert_eq!(BigU::zero().next_prime(), BigU::from(2u32));
    /// assert_eq!(BigU::from(7u32).next_prime(), BigU::from(11u32));
    /// ```
    pub fn next_prime(&self) -> BigU {
        let two = BigU::from(2u32);
        if self < &two {
            return two;
        }
        // Step to the next odd candidate above `self`; from 2 that is 3.
        let mut cand = self + &BigU::one();
        if !cand.bit(0) {
            cand = &cand + &BigU::one();
        }
        while !cand.is_prime() {
            cand = &cand + &two;
        }
        cand
    }

    /// Returns the largest prime strictly less than `self`, or `None` when
    /// there is none (that is, whenever `self <= 2`).
    ///
    /// ```
    /// use bigu::BigU;
    /// assert_eq!(BigU::from(11u32).prev_prime(), Some(BigU::from(7u32)));
    /// assert_eq!(BigU::from(2u32).prev_prime(), None);
    /// ```
    pub fn prev_prime(&self) -> Option<BigU> {
        let two = BigU::from(2u32);
        if self <= &two {
            return None;
        }
        if self == &BigU::from(3u32) {
            return Some(two);
        }
        // From here the answer is an odd number at least 3, and 3 is prime, so
        // the walk below always terminates before the subtraction can underflow.
        let mut cand = self.checked_sub(&BigU::one()).expect("self > 2");
        if !cand.bit(0) {
            cand = cand.checked_sub(&BigU::one()).expect("cand >= 3");
        }
        loop {
            if cand.is_prime() {
                return Some(cand);
            }
            cand = cand.checked_sub(&two).expect("3 is prime, so the walk stops");
        }
    }

    /// Returns `true` when `self` and `other` share no factor beyond `1`.
    ///
    /// `1` is coprime to everything including `0`, and `0` is coprime only to
    /// `1`, both of which follow from `gcd` directly.
    pub fn is_coprime(&self, other: &BigU) -> bool {
        eq_limb(&self.gcd(other), 1)
    }

    /// Returns the complete prime factorization of `self` as `(prime, exponent)`
    /// pairs in ascending order of prime.
    ///
    /// `0` and `1` have no prime factors and both yield an empty vector.
    /// Multiplying the factors back out always reproduces `self`, and every
    /// returned base satisfies [`BigU::is_prime`].
    ///
    /// Small factors come off by trial division; whatever survives is split by
    /// [`BigU::pollard_rho`] and the pieces are recursively factored until all
    /// of them are prime. Rho's running time scales with the *square root of the
    /// smallest remaining factor*, so a semiprime built from two large primes is
    /// genuinely expensive — this is a working factorizer, not a fast one.
    ///
    /// ```
    /// use bigu::BigU;
    /// // 360 == 2^3 * 3^2 * 5
    /// let f = BigU::from(360u32).factor();
    /// assert_eq!(f.len(), 3);
    /// assert_eq!(f[0], (BigU::from(2u32), 3));
    /// assert_eq!(f[2], (BigU::from(5u32), 1));
    /// assert!(BigU::one().factor().is_empty());
    /// ```
    pub fn factor(&self) -> Vec<(BigU, u32)> {
        let mut out: Vec<(BigU, u32)> = Vec::new();
        if self.limbs.is_empty() || eq_limb(self, 1) {
            return out;
        }

        // Strip every factor below 1000, recording multiplicities as we go.
        let mut rest = self.clone();
        for &p in SMALL_PRIMES.iter() {
            if rem_small(&rest.limbs, p) != 0 {
                continue;
            }
            let bp = BigU::from(p);
            let mut count = 0u32;
            while rem_small(&rest.limbs, p) == 0 {
                rest = rest.div_rem(&bp).expect("p is nonzero").0;
                count += 1;
            }
            out.push((bp, count));
            if eq_limb(&rest, 1) {
                return out;
            }
        }

        // The cofactor now has no factor below 1000, so it is either prime or a
        // product of primes all at or above 1009.
        let mut large: Vec<BigU> = Vec::new();
        split_into_primes(rest, &mut large);
        large.sort();
        for prime in large {
            match out.last_mut() {
                Some((p, count)) if *p == prime => *count += 1,
                _ => out.push((prime, 1)),
            }
        }
        out
    }

    /// Returns Euler's totient of `self`: how many integers in `1..=self` are
    /// coprime to it.
    ///
    /// `phi(1)` is `1` — the single value `1` is coprime to itself — and `phi(0)`
    /// is defined here as `0`, since the empty range has nothing to count. For a
    /// prime `p` the answer is `p - 1`, and for a prime power `phi(p^e)` is
    /// `p^(e-1) * (p - 1)`; the general case follows because `phi` is
    /// multiplicative over coprime parts.
    ///
    /// This is the exponent that makes Euler's theorem work: for any `a` coprime
    /// to `n`, `a.modpow(n.euler_phi(), n)` is `1`.
    ///
    /// ```
    /// use bigu::BigU;
    /// assert_eq!(BigU::from(1u32).euler_phi(), BigU::from(1u32));
    /// assert_eq!(BigU::from(9u32).euler_phi(), BigU::from(6u32));
    /// // A prime leaves every smaller positive value coprime to it.
    /// assert_eq!(BigU::from(97u32).euler_phi(), BigU::from(96u32));
    /// ```
    pub fn euler_phi(&self) -> BigU {
        if self.limbs.is_empty() {
            return BigU::zero();
        }
        let mut result = BigU::one();
        for (p, e) in self.factor() {
            let p_minus_1 = p.checked_sub(&BigU::one()).expect("a prime is at least 2");
            result = &result * &(&p.pow(e - 1) * &p_minus_1);
        }
        result
    }

    /// Returns how many positive divisors `self` has, including `1` and itself.
    ///
    /// A value whose factorization is `p1^e1 * ... * pk^ek` has
    /// `(e1 + 1) * ... * (ek + 1)` divisors, since each prime independently
    /// contributes an exponent anywhere in `0..=ei`. `1` has exactly one
    /// divisor; `0` is reported as `0` because it is divisible by everything.
    pub fn divisor_count(&self) -> BigU {
        if self.limbs.is_empty() {
            return BigU::zero();
        }
        let mut count = BigU::one();
        for (_, e) in self.factor() {
            count = &count * &BigU::from(e + 1);
        }
        count
    }

    /// Returns every positive divisor of `self` in ascending order.
    ///
    /// `1` yields `[1]` and `0` yields an empty vector, matching
    /// [`BigU::divisor_count`]. The list is built by taking each prime power in
    /// turn and multiplying it across the divisors found so far, so its length
    /// is exactly `divisor_count` — which grows fast, so this is only sensible
    /// for values with a modest factorization.
    ///
    /// ```
    /// use bigu::BigU;
    /// let d = BigU::from(12u32).divisors();
    /// let want: Vec<BigU> = [1u32, 2, 3, 4, 6, 12].iter().map(|&v| BigU::from(v)).collect();
    /// assert_eq!(d, want);
    /// ```
    pub fn divisors(&self) -> Vec<BigU> {
        if self.limbs.is_empty() {
            return Vec::new();
        }
        let mut out = vec![BigU::one()];
        for (p, e) in self.factor() {
            // Scale the divisors found so far by every power of this prime.
            let base = out.clone();
            let mut power = BigU::one();
            for _ in 0..e {
                power = &power * &p;
                out.extend(base.iter().map(|d| d * &power));
            }
        }
        out.sort();
        out
    }

    /// Finds one nontrivial factor of the composite `self` using Brent's
    /// variant of Pollard's rho, or `None` when `self` is `0`, `1` or prime.
    ///
    /// The returned factor is strictly between `1` and `self` but is *not*
    /// necessarily prime — it is whatever the cycle detection happened to
    /// expose. Use [`BigU::factor`] for a full factorization.
    ///
    /// The iteration follows `x -> x^2 + c` modulo `self`, batching the
    /// difference product so that only one gcd is needed per block of steps.
    /// A block whose gcd collapses to `self` is replayed one step at a time,
    /// and an exhausted polynomial is retried with the next `c`, so the search
    /// keeps making progress rather than reporting a failure as success.
    pub fn pollard_rho(&self) -> Option<BigU> {
        if self.limbs.is_empty() || eq_limb(self, 1) {
            return None;
        }
        // Even numbers are split for free, and rho is famously bad at 4.
        if !self.bit(0) {
            return Some(BigU::from(2u32));
        }
        if self.is_prime() {
            return None;
        }

        let one = BigU::one();
        // Try successive polynomials; a given `c` can dead-end on this modulus.
        for c_seed in 1u32..=64 {
            if let Some(f) = self.rho_attempt(&BigU::from(c_seed)) {
                if f != one && &f != self {
                    return Some(f);
                }
            }
        }
        None
    }

    /// One pass of Brent's rho for a fixed polynomial constant `c`.
    fn rho_attempt(&self, c: &BigU) -> Option<BigU> {
        // Batch size for the deferred gcd; 128 keeps the gcd count low without
        // letting a whole cycle slip past unnoticed.
        const BATCH: u64 = 128;

        let one = BigU::one();
        let mut y = BigU::from(2u32);
        let mut g = one.clone();
        let mut r: u64 = 1;
        let mut q = one.clone();
        let mut x = y.clone();
        let mut ys = y.clone();

        while g == one {
            x = y.clone();
            for _ in 0..r {
                y = self.rho_step(&y, c);
            }
            let mut k: u64 = 0;
            while k < r && g == one {
                ys = y.clone();
                for _ in 0..BATCH.min(r - k) {
                    y = self.rho_step(&y, c);
                    // Accumulate |x - y| into the running product so a single
                    // gcd covers the whole batch.
                    let diff = abs_diff(&x, &y);
                    q *= &diff;
                    q %= self;
                }
                g = q.gcd(self);
                k += BATCH;
            }
            r *= 2;
            // A batch that swallowed the whole modulus needs a finer replay.
            if r > (1u64 << 40) {
                return None;
            }
        }

        if &g == self {
            // Back off and step one at a time to recover the factor the batch
            // hid by multiplying two of them together.
            loop {
                ys = self.rho_step(&ys, c);
                g = abs_diff(&x, &ys).gcd(self);
                if g != one {
                    break;
                }
            }
        }
        if &g == self {
            None
        } else {
            Some(g)
        }
    }

    /// One `x -> x^2 + c (mod self)` step of the rho iteration.
    fn rho_step(&self, x: &BigU, c: &BigU) -> BigU {
        let mut next = x * x;
        next += c;
        next %= self;
        next
    }
}

/// Absolute difference of two unsigned values, whichever way round they sit.
fn abs_diff(a: &BigU, b: &BigU) -> BigU {
    if a >= b {
        a.checked_sub(b).expect("a >= b")
    } else {
        b.checked_sub(a).expect("b > a")
    }
}

/// Splits `n` all the way down to primes, appending them to `out`.
///
/// `n` must have no factor below 1000, which is what the trial-division stage
/// in [`BigU::factor`] guarantees.
fn split_into_primes(n: BigU, out: &mut Vec<BigU>) {
    if n.limbs.len() == 1 && n.limbs[0] == 1 {
        return;
    }
    if n.is_prime() {
        out.push(n);
        return;
    }
    match n.pollard_rho() {
        Some(d) => {
            let q = n.div_rem(&d).expect("rho returns a nonzero factor").0;
            split_into_primes(d, out);
            split_into_primes(q, out);
        }
        // Rho gave up; keeping the composite is still an honest answer about the
        // product, so surface it rather than silently dropping the cofactor.
        None => out.push(n),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::str::FromStr;

    fn b(s: &str) -> BigU {
        BigU::from_str(s).unwrap()
    }

    /// Reference primality by trial division, for cross-checking small values.
    fn naive_prime(n: u64) -> bool {
        if n < 2 {
            return false;
        }
        let mut d = 2u64;
        while d * d <= n {
            if n % d == 0 {
                return false;
            }
            d += 1;
        }
        true
    }

    #[test]
    fn rem_small_matches_div_rem() {
        for s in ["0", "1", "1000000007", "340282366920938463463374607431768211455"] {
            let v = b(s);
            for d in [1u32, 2, 3, 7, 97, 65537, 0xFFFF_FFFF] {
                let want = v.div_rem(&BigU::from(d)).unwrap().1;
                assert_eq!(BigU::from(rem_small(&v.limbs, d)), want, "{s} % {d}");
            }
        }
    }

    #[test]
    fn is_prime_agrees_with_trial_division_below_10000() {
        for n in 0u64..10_000 {
            assert_eq!(
                BigU::from(n).is_prime(),
                naive_prime(n),
                "disagreement at {n}"
            );
        }
    }

    #[test]
    fn zero_and_one_are_not_prime() {
        assert!(!BigU::zero().is_prime());
        assert!(!BigU::one().is_prime());
        assert!(BigU::from(2u32).is_prime());
        assert!(BigU::from(3u32).is_prime());
        assert!(!BigU::from(4u32).is_prime());
    }

    #[test]
    fn carmichael_numbers_are_caught() {
        // Fermat's test passes these for every coprime base; Miller-Rabin must
        // still call them composite.
        for &n in &[561u64, 1105, 1729, 2465, 2821, 6601, 8911, 41041, 62745] {
            assert!(!BigU::from(n).is_prime(), "Carmichael {n} reported prime");
        }
    }

    #[test]
    fn strong_pseudoprimes_fool_their_own_base_only() {
        // 2047 == 23 * 89 is the smallest strong pseudoprime to base 2.
        let n = BigU::from(2047u32);
        assert!(n.is_strong_probable_prime(&BigU::from(2u32)));
        assert!(!n.is_strong_probable_prime(&BigU::from(3u32)));
        assert!(!n.is_prime());

        // 121 == 11^2 is the smallest strong pseudoprime to base 3.
        let n = BigU::from(121u32);
        assert!(n.is_strong_probable_prime(&BigU::from(3u32)));
        assert!(!n.is_prime());

        // 1373653 is the smallest composite that survives both base 2 and 3.
        let n = BigU::from(1_373_653u32);
        assert!(n.is_strong_probable_prime(&BigU::from(2u32)));
        assert!(n.is_strong_probable_prime(&BigU::from(3u32)));
        assert!(!n.is_prime());

        // 3215031751 survives bases 2, 3, 5 and 7 together.
        let n = BigU::from(3_215_031_751u64);
        for base in [2u32, 3, 5, 7] {
            assert!(n.is_strong_probable_prime(&BigU::from(base)), "base {base}");
        }
        assert!(!n.is_prime());
    }

    #[test]
    fn uninformative_bases_never_condemn_a_prime() {
        // 0, 1 and n-1 carry no information and must not read as witnesses.
        let n = BigU::from(97u32);
        for base in [0u32, 1, 96, 97, 98] {
            assert!(
                n.is_strong_probable_prime(&BigU::from(base)),
                "base {base} wrongly condemned a prime"
            );
        }
    }

    #[test]
    fn mersenne_primes_and_composites() {
        // 2^p - 1 is prime for these exponents and composite for the others.
        for p in [2u32, 3, 5, 7, 13, 17, 19, 31, 61, 89, 107, 127] {
            let m = BigU::from(2u32).pow(p) - BigU::one();
            assert!(m.is_prime(), "M{p} should be prime");
        }
        for p in [11u32, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71, 73] {
            let m = BigU::from(2u32).pow(p) - BigU::one();
            assert!(!m.is_prime(), "M{p} should be composite");
        }
    }

    #[test]
    fn known_large_primes() {
        // A published 39-digit prime (2^127 - 1) and two well known primes.
        assert!(b("170141183460469231731687303715884105727").is_prime());
        assert!(b("1000000007").is_prime());
        assert!(b("4294967291").is_prime()); // largest prime below 2^32
                                             // One more than a prime is even here, so check a neighbouring composite.
        assert!(!b("170141183460469231731687303715884105729").is_prime());
    }

    #[test]
    fn products_of_two_large_primes_are_composite() {
        // A semiprime has no small factor, so this exercises the Miller-Rabin
        // stage rather than trial division.
        let p = b("1000000007");
        let q = b("1000000009");
        let n = &p * &q;
        assert!(n.small_factor().is_none(), "semiprime must dodge the sieve");
        assert!(!n.is_prime());
    }

    #[test]
    fn small_factor_finds_the_least_prime_divisor() {
        assert_eq!(BigU::from(2u32).small_factor(), Some(2));
        assert_eq!(BigU::from(97u32).small_factor(), Some(97));
        assert_eq!(BigU::from(15u32).small_factor(), Some(3));
        assert_eq!(BigU::from(1001u32).small_factor(), Some(7));
        assert_eq!(BigU::zero().small_factor(), None);
        assert_eq!(BigU::one().small_factor(), None);
        // 1009 is the smallest prime at or above the table bound.
        assert_eq!(BigU::from(1009u32).small_factor(), None);
        assert_eq!(b("1000000007").small_factor(), None);
    }

    #[test]
    fn next_prime_small_sequence() {
        // next_prime is strictly greater, so a prime maps to the one after it.
        let expected = [2u32, 2, 3, 5, 5, 7, 7, 11, 11, 11, 11, 13, 13];
        for (n, &want) in expected.iter().enumerate() {
            assert_eq!(
                BigU::from(n as u32).next_prime(),
                BigU::from(want),
                "next_prime({n})"
            );
        }
    }

    #[test]
    fn prev_prime_small_sequence() {
        assert_eq!(BigU::zero().prev_prime(), None);
        assert_eq!(BigU::one().prev_prime(), None);
        assert_eq!(BigU::from(2u32).prev_prime(), None);
        assert_eq!(BigU::from(3u32).prev_prime(), Some(BigU::from(2u32)));
        assert_eq!(BigU::from(4u32).prev_prime(), Some(BigU::from(3u32)));
        assert_eq!(BigU::from(5u32).prev_prime(), Some(BigU::from(3u32)));
        assert_eq!(BigU::from(30u32).prev_prime(), Some(BigU::from(29u32)));
    }

    #[test]
    fn next_and_prev_prime_bracket_each_other() {
        // For any prime p, next_prime(p-1) == p and prev_prime(p+1) == p.
        for p in [11u32, 101, 997, 7919, 104729] {
            let bp = BigU::from(p);
            let below = bp.checked_sub(&BigU::one()).unwrap();
            assert_eq!(below.next_prime(), bp, "next_prime({}) ", p - 1);
            let above = &bp + &BigU::one();
            assert_eq!(above.prev_prime(), Some(bp.clone()), "prev_prime({})", p + 1);
        }
    }

    #[test]
    fn next_prime_crosses_a_limb_boundary() {
        // The first prime above 2^32 is 4294967311.
        let n = BigU::from(1u64 << 32);
        let p = n.next_prime();
        assert_eq!(p, BigU::from(4_294_967_311u64));
        assert!(p.is_prime());
    }

    #[test]
    fn next_prime_is_always_prime_and_greater() {
        let mut seed = 12345u64;
        for _ in 0..40 {
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
            let n = BigU::from(seed >> 40);
            let p = n.next_prime();
            assert!(p > n, "next_prime must strictly increase");
            assert!(p.is_prime(), "next_prime must return a prime");
            // Nothing between n and p may be prime.
            let mut mid = &n + &BigU::one();
            while mid < p {
                assert!(!mid.is_prime(), "missed a prime below {p:?}");
                mid = &mid + &BigU::one();
            }
        }
    }

    #[test]
    fn is_coprime_basics() {
        assert!(BigU::from(9u32).is_coprime(&BigU::from(28u32)));
        assert!(!BigU::from(9u32).is_coprime(&BigU::from(21u32)));
        assert!(BigU::one().is_coprime(&BigU::zero()));
        assert!(!BigU::zero().is_coprime(&BigU::from(5u32)));
        // Distinct primes are always coprime.
        assert!(b("1000000007").is_coprime(&b("1000000009")));
    }

    #[test]
    fn factor_zero_and_one_are_empty() {
        assert!(BigU::zero().factor().is_empty());
        assert!(BigU::one().factor().is_empty());
    }

    #[test]
    fn factor_small_known_values() {
        assert_eq!(BigU::from(2u32).factor(), vec![(BigU::from(2u32), 1)]);
        assert_eq!(BigU::from(97u32).factor(), vec![(BigU::from(97u32), 1)]);
        // 360 == 2^3 * 3^2 * 5
        assert_eq!(
            BigU::from(360u32).factor(),
            vec![
                (BigU::from(2u32), 3),
                (BigU::from(3u32), 2),
                (BigU::from(5u32), 1)
            ]
        );
        // A pure prime power.
        assert_eq!(BigU::from(1024u32).factor(), vec![(BigU::from(2u32), 10)]);
    }

    #[test]
    fn factor_product_reconstructs_the_input() {
        for n in 1u64..600 {
            let v = BigU::from(n);
            let mut product = BigU::one();
            for (p, e) in v.factor() {
                assert!(p.is_prime(), "factor {p:?} of {n} is not prime");
                product = &product * &p.pow(e);
            }
            if n == 1 {
                assert!(product == BigU::one());
            } else {
                assert_eq!(product, v, "factorization of {n} does not multiply back");
            }
        }
    }

    #[test]
    fn factor_is_sorted_and_deduplicated() {
        let v = b("2310"); // 2 * 3 * 5 * 7 * 11
        let f = v.factor();
        assert_eq!(f.len(), 5);
        for w in f.windows(2) {
            assert!(w[0].0 < w[1].0, "factors must be strictly ascending");
        }
    }

    #[test]
    fn factor_semiprime_beyond_the_sieve() {
        // Both factors sit above the trial-division bound, so rho has to work.
        let p = BigU::from(1_000_003u32);
        let q = BigU::from(1_000_033u32);
        let n = &p * &q;
        assert_eq!(n.factor(), vec![(p, 1), (q, 1)]);
    }

    #[test]
    fn factor_mixes_small_and_large_factors() {
        // 2^4 * 3 * 1000003 exercises both stages in one call.
        let big = BigU::from(1_000_003u32);
        let n = &(&BigU::from(16u32) * &BigU::from(3u32)) * &big;
        assert_eq!(
            n.factor(),
            vec![(BigU::from(2u32), 4), (BigU::from(3u32), 1), (big, 1)]
        );
    }

    #[test]
    fn factor_square_of_a_large_prime() {
        // p^2 is the case where rho's cycle can collapse; the retry must cope.
        let p = BigU::from(1_000_003u32);
        let n = &p * &p;
        assert_eq!(n.factor(), vec![(p, 2)]);
    }

    #[test]
    fn pollard_rho_declines_primes_and_units() {
        assert_eq!(BigU::zero().pollard_rho(), None);
        assert_eq!(BigU::one().pollard_rho(), None);
        assert_eq!(BigU::from(97u32).pollard_rho(), None);
        assert_eq!(b("1000000007").pollard_rho(), None);
    }

    #[test]
    fn pollard_rho_returns_a_real_divisor() {
        for n in [
            BigU::from(8051u32),  // 83 * 97
            BigU::from(10403u32), // 101 * 103
            &BigU::from(1_000_003u32) * &BigU::from(1_000_033u32),
        ] {
            let d = n.pollard_rho().expect("composite must split");
            assert!(d > BigU::one() && d < n, "factor out of range");
            assert!(
                n.div_rem(&d).unwrap().1.is_zero(),
                "returned value does not divide n"
            );
        }
    }

    #[test]
    fn deterministic_bound_is_a_parseable_value() {
        let bound = b(DETERMINISTIC_PRIME_BOUND);
        assert!(!bound.is_zero());
        // The documented bound really is above 2^81, the range the base set buys.
        assert!(bound > BigU::from(2u32).pow(81));
    }

    #[test]
    fn euler_phi_known_values() {
        // phi(0) == 0 and phi(1) == 1 by the conventions documented above.
        assert!(BigU::zero().euler_phi().is_zero());
        assert_eq!(BigU::one().euler_phi(), BigU::one());
        // A short prefix of OEIS A000010.
        let want = [1u32, 1, 2, 2, 4, 2, 6, 4, 6, 4, 10, 4, 12, 6, 8, 8, 16, 6, 18, 8];
        for (i, &w) in want.iter().enumerate() {
            let n = i as u32 + 1;
            assert_eq!(BigU::from(n).euler_phi(), BigU::from(w), "phi({n})");
        }
    }

    #[test]
    fn euler_phi_of_a_prime_is_one_less() {
        for p in [97u32, 1009, 65537] {
            let bp = BigU::from(p);
            assert!(bp.is_prime());
            assert_eq!(bp.euler_phi(), BigU::from(p - 1), "phi({p})");
        }
    }

    #[test]
    fn euler_phi_counts_coprime_residues() {
        // Direct definition check: count the coprime values by brute force.
        for n in 1u32..300 {
            let bn = BigU::from(n);
            let counted = (1..=n).filter(|&a| BigU::from(a).is_coprime(&bn)).count();
            assert_eq!(bn.euler_phi(), BigU::from(counted as u32), "phi({n})");
        }
    }

    #[test]
    fn euler_theorem_holds() {
        // a^phi(n) == 1 (mod n) whenever a and n are coprime.
        for n in [10u32, 21, 100, 1001] {
            let bn = BigU::from(n);
            let phi = bn.euler_phi();
            for a in 2u32..30 {
                let ba = BigU::from(a);
                if !ba.is_coprime(&bn) {
                    continue;
                }
                assert_eq!(
                    ba.modpow(&phi, &bn).unwrap(),
                    BigU::one(),
                    "Euler failed for {a}^phi({n})"
                );
            }
        }
    }

    #[test]
    fn divisor_count_and_divisors_agree() {
        assert!(BigU::zero().divisor_count().is_zero());
        assert!(BigU::zero().divisors().is_empty());
        assert_eq!(BigU::one().divisors(), vec![BigU::one()]);

        for n in 1u32..200 {
            let bn = BigU::from(n);
            let d = bn.divisors();
            assert_eq!(bn.divisor_count(), BigU::from(d.len() as u32), "count({n})");
            // Every listed value really divides n, and the list is ascending.
            for w in d.windows(2) {
                assert!(w[0] < w[1], "divisors of {n} not ascending");
            }
            for x in &d {
                assert!(bn.div_rem(x).unwrap().1.is_zero(), "{x:?} does not divide {n}");
            }
            // Brute force the same list straight from the definition.
            let brute: Vec<BigU> = (1..=n)
                .filter(|&c| n % c == 0)
                .map(BigU::from)
                .collect();
            assert_eq!(d, brute, "divisors of {n}");
        }
    }

    #[test]
    fn divisor_count_of_a_prime_power() {
        // 2^10 has exactly 11 divisors: 2^0 through 2^10.
        let n = BigU::from(2u32).pow(10);
        assert_eq!(n.divisor_count(), BigU::from(11u32));
        assert_eq!(n.divisors().len(), 11);
        // A prime has exactly two.
        assert_eq!(BigU::from(97u32).divisor_count(), BigU::from(2u32));
    }

    #[test]
    fn mr_bases_are_the_first_thirteen_primes() {
        assert_eq!(&MR_BASES[..], &SMALL_PRIMES[..13]);
    }
}
