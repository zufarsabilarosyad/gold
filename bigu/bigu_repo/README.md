# bigu

Arbitrary-precision **unsigned** integers for Rust, with **zero dependencies**.

`bigu` is a single self-contained crate that implements the classical bignum
algorithms directly on a little-endian vector of `u32` limbs. There is no
`num-bigint`, no `gmp`, no build script, and no `unsafe` — the crate is
`#![forbid(unsafe_code)]` throughout.

## Why it exists

Most projects that need big integers reach for `num-bigint`, and they should.
`bigu` exists for the cases where a dependency is the thing you are trying to
avoid: vendored builds, teaching material, constrained review processes, or
anywhere you want the whole numeric stack to be a few thousand lines you can
actually read end to end.

The trade is deliberate. `bigu` is not trying to beat GMP. It is trying to be
correct, exact, and small enough to audit in an afternoon.

## The design constraint that shapes everything

**Exact integer arithmetic, with no floating point anywhere on the main paths.**

Every result is computed from integer operations only. Division is Knuth's
Algorithm D, radix conversion is repeated chunked division, and square roots use
integer Newton iteration — not `f64::sqrt` scaled up and rounded. This matters
because floating point silently loses precision above 2^53, which is exactly the
range a bignum library exists to serve.

One honest exception remains: `BigU::sqrt` has a single-limb fast path that
routes through `f64::sqrt` to get a starting estimate. The estimate is then
corrected by exact integer steps until it is provably the true floor root, so
the *result* is still exact — but the float is genuinely there, and calling it
"no floats anywhere" would be a lie. It is the one spot in the crate that does
not meet the constraint on its own terms.

## Quickstart

```rust
use bigu::BigU;
use std::str::FromStr;

// Parse a value far beyond u128, then do exact arithmetic on it.
let a = BigU::from_str("340282366920938463463374607431768211456").unwrap(); // 2^128
let b = BigU::from(2u32);

let (quotient, remainder) = a.div_rem(&b).unwrap();
assert!(remainder.is_zero());
assert_eq!(quotient.to_str_radix(16).unwrap(), "80000000000000000000000000000000");

// Formatting honours the full format spec.
assert_eq!(format!("{:#x}", BigU::from(48879u32)), "0xbeef");
assert_eq!(format!("{:>10}", BigU::from(42u32)), "        42");
assert_eq!(format!("{:08b}", BigU::from(5u32)), "00000101");
```

### Modular arithmetic

```rust
use bigu::BigU;

let base = BigU::from(4u32);
let exp = BigU::from(13u32);
let modulus = BigU::from(497u32);
assert_eq!(base.modpow(&exp, &modulus).unwrap(), BigU::from(445u32));

// 3 * 4 == 12 == 1 (mod 11)
assert_eq!(BigU::from(3u32).modinv(&BigU::from(11u32)).unwrap(), BigU::from(4u32));

// Values sharing a factor with the modulus have no inverse.
assert!(BigU::from(6u32).modinv(&BigU::from(9u32)).is_err());
```

### Fast modular arithmetic

`modpow` reduces with Knuth division on every step, which is correct but pays
for a full multi-limb division each time. When the same modulus is reused —
which is the situation in every exponentiation and every protocol built on one —
`ModRing` analyses it once and never divides again. Montgomery reduction
(Montgomery 1985) is selected automatically for an odd modulus, Barrett
reduction (Barrett 1986) for everything else.

Elements borrow their ring, and every operation checks that both sides agree on
the modulus *and* on the strategy. Montgomery elements are stored in a shifted
domain, so mixing the two representations would give a wrong answer rather than
a detectable one — hence the check.

```rust
use bigu::{BigU, ModRing, Reduction};

let ring = ModRing::new(&BigU::from(497u32)).unwrap();
assert_eq!(ring.reduction(), Reduction::Montgomery); // 497 is odd
assert_eq!(ring.pow(&BigU::from(4u32), &BigU::from(13u32)), BigU::from(445u32));

let a = ring.elem(&BigU::from(400u32));
let b = ring.elem(&BigU::from(300u32));
assert_eq!((&a * &b).value(), BigU::from(223u32)); // 120000 mod 497
assert!((&a * &a.inv().unwrap()).is_one());

// An even modulus cannot be reduced Montgomery-style, and says so.
assert!(ModRing::with_reduction(&BigU::from(1024u32), Reduction::Montgomery).is_err());
assert_eq!(
    ModRing::new(&BigU::from(1024u32)).unwrap().reduction(),
    Reduction::Barrett
);

// Elements of different rings refuse to combine.
let other = ModRing::new(&BigU::from(11u32)).unwrap();
assert!(a.checked_add(&other.elem(&BigU::one())).is_err());
```

### Multi-modular arithmetic

`CrtBasis` holds a set of pairwise-coprime moduli plus the constants Garner's
algorithm needs, so a wide value can be split into narrow residues, worked on
channel by channel, and reconstructed exactly.

```rust
use bigu::{BigU, CrtBasis};

// Sun Tzu: a number leaving 2 mod 3, 3 mod 5 and 2 mod 7 is 23.
let basis = CrtBasis::new(&[BigU::from(3u32), BigU::from(5u32), BigU::from(7u32)]).unwrap();
assert_eq!(basis.product(), &BigU::from(105u32));
let residues = [BigU::from(2u32), BigU::from(3u32), BigU::from(2u32)];
assert_eq!(basis.reconstruct(&residues).unwrap(), BigU::from(23u32));

// Round-tripping any value below the product is exact.
assert_eq!(basis.reconstruct(&basis.reduce(&BigU::from(88u32))).unwrap(), BigU::from(88u32));

// Moduli sharing a factor have no unique reconstruction, so the basis is refused.
assert!(CrtBasis::new(&[BigU::from(6u32), BigU::from(10u32)]).is_err());
```

### Primality and factorization

```rust
use bigu::BigU;

// 2^127 - 1 is the Mersenne prime M127.
let m127 = BigU::from(2u32).pow(127) - BigU::one();
assert!(m127.is_prime());

// 2^11 - 1 == 2047 == 23 * 89, which fools a base-2 test on its own.
let m11 = BigU::from(2u32).pow(11) - BigU::one();
assert!(m11.is_strong_probable_prime(&BigU::from(2u32)));
assert!(!m11.is_prime());

assert_eq!(BigU::from(7u32).next_prime(), BigU::from(11u32));
assert_eq!(BigU::from(11u32).prev_prime(), Some(BigU::from(7u32)));

// 360 == 2^3 * 3^2 * 5
let factors = BigU::from(360u32).factor();
assert_eq!(factors[0], (BigU::from(2u32), 3));
assert_eq!(factors[1], (BigU::from(3u32), 2));
assert_eq!(factors[2], (BigU::from(5u32), 1));

// Everything derived from the factorization comes along for free.
assert_eq!(BigU::from(9u32).euler_phi(), BigU::from(6u32));
assert_eq!(BigU::from(12u32).divisor_count(), BigU::from(6u32));
```

### Exact rationals

```rust
use bigu::{BigI, BigQ};
use std::str::FromStr;

// Fractions stay exact: 1/3 + 1/6 == 1/2, no floating point anywhere.
let sum = &BigQ::from_str("1/3").unwrap() + &BigQ::from_str("1/6").unwrap();
assert_eq!(sum, BigQ::from_str("1/2").unwrap());

// Denominators of the form 2^a * 5^b terminate; everything else repeats.
let eighth = BigQ::new(BigI::from(1u32), BigI::from(8u32)).unwrap();
assert!(eighth.is_terminating());
assert_eq!(eighth.to_decimal(3), "0.125");
assert!(!BigQ::from_str("1/7").unwrap().is_terminating());
assert_eq!(BigQ::from_str("22/7").unwrap().to_decimal(4), "3.1429");

// Ties round to even, so 5/2 and 7/2 both land on an even integer.
assert_eq!(BigQ::from_str("5/2").unwrap().round_half_even(), BigI::from(2u32));
assert_eq!(BigQ::from_str("7/2").unwrap().round_half_even(), BigI::from(4u32));
```

## What is implemented

| Area | Approach |
| --- | --- |
| Add / subtract | Carry and borrow propagation through `u64` accumulators |
| Multiply | Schoolbook, escalating to Karatsuba above 32 limbs |
| Divide | Knuth Algorithm D (TAOCP Vol. 2, §4.3.1) with `q-hat` correction and add-back |
| Radix conversion | Chunked division, recursive divide-and-conquer for large values, direct bit repacking for power-of-two bases |
| Formatting | `{}`, `{:x}`, `{:X}`, `{:b}`, `{:o}` with full width / fill / align / zero-pad support |
| Bitwise | `&`, `|`, `^`, shifts, single-bit read and write |
| Modular | `modpow` (square-and-multiply), `modinv` (extended Euclid), `gcd`, `lcm` |
| Fast modular | `ModRing` with a precomputed Montgomery (odd modulus) or Barrett (any modulus) reducer, elements typed to their ring, Montgomery-ladder exponentiation |
| Multi-modular | `CrtBasis` over pairwise-coprime moduli, reconstruction by Garner's algorithm |
| Primality | Trial division, then deterministic Miller-Rabin over the first 13 primes |
| Factorization | Trial division, then Brent's variant of Pollard's rho |
| Number theory | Euler totient, divisor count and divisor enumeration, all derived from the factorization |
| Roots and logs | Integer Newton `sqrt`, `is_perfect_square`, `ilog` |
| Rationals | `BigQ` kept normalized (lowest terms, sign on the numerator); exact arithmetic, `floor`/`ceil`/`trunc`/`round_half_even`, terminating-decimal detection, `to_decimal` at any precision |

## Correctness notes worth knowing

**A strict canonical form is maintained at all times.** There are never trailing
zero limbs, and zero is the empty limb vector. This is what makes `Eq`, `Ord`
and `Hash` behave as plain integer comparisons rather than representation
comparisons.

**`is_prime` is exact below a published bound.** It runs Miller-Rabin over the
first thirteen primes, which is proven to have no composite survivors below
`3317044064679887385961981` (available as `bigu::DETERMINISTIC_PRIME_BOUND`).
Above that bound the answer is a strong probable prime result — overwhelmingly
likely, but not proof.

**`factor` is a working factorizer, not a fast one.** Pollard's rho scales with
the square root of the smallest remaining factor, so a semiprime built from two
large primes will not finish in reasonable time. This is a property of the
algorithm, not a bug.

**Panicking versus checked operations.** The operators (`-`, `/`, `%`) panic on
underflow and division by zero, matching the primitive integer types. Every one
of them has a non-panicking counterpart — `checked_sub`, `div_rem` — that
returns `Result` instead. The `Error` enum is a flat set of leaf errors with no
`From` glue to outside error types, which is what keeps the crate
dependency-free.

## License

Dual-licensed under MIT or Apache-2.0, at your option.
