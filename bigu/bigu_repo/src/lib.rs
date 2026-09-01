//! `bigu` — *big-int-lite, unsigned*.
//!
//! A small, self-contained, arbitrary-precision **unsigned** integer type
//! implemented entirely on top of `std`, with no third-party dependencies.
//!
//! The value is stored as a little-endian vector of base-`2^32` limbs ([`u32`]),
//! using [`u64`] intermediates for carry and borrow propagation. The crate
//! implements the core bignum algorithms directly:
//!
//! * carry/borrow addition and subtraction,
//! * schoolbook multiplication that escalates to Karatsuba above a tunable
//!   limb threshold,
//! * Knuth's Algorithm D (TAOCP Vol. 2, §4.3.1) for multi-limb long division,
//! * bidirectional string conversion for any radix in `2..=36`, chunked to a
//!   limb's worth of digits at a time and split recursively once the operand is
//!   large enough to pay for it,
//! * bitwise and, or, xor over the limb vectors,
//! * Miller-Rabin primality testing over a fixed base set, backed by trial
//!   division and Pollard's rho for factorization,
//! * a modular reduction engine with Montgomery and Barrett reducers behind a
//!   `ModRing` whose elements cannot silently mix moduli, plus a Garner CRT
//!   basis on top of it.
//!
//! The standard formatting traits are implemented on top of the radix
//! conversion, so `{}`, `{:x}`, `{:X}`, `{:b}` and `{:o}` all accept the full
//! format spec — width, fill, alignment, zero padding and the `#` prefix.
//!
//! A strict canonical form is maintained at all times: there are never trailing
//! zero limbs, and the value zero is represented by an empty limb vector.
//!
//! Four subsystems sit around that arithmetic core rather than inside it, each
//! writing down a decision the core only ever made implicitly. [`intake`] is the
//! text layer: it scans, signs, un-prefixes and bounds a string, with a position
//! attached to every complaint, before a digit reaches the parser. [`wire`] is
//! the byte layer: endianness, field width, sign envelope and framing, composed
//! into one [`Encoding`](wire::Encoding) a caller holds the way they hold a
//! `ModRing`. [`reuse`] is the lifecycle layer: pooled limb buffers, in-place
//! assignment, cached ring setup and a ceiling on outstanding storage, none of
//! which may change an answer. [`audit`] is read-only: it describes a value's
//! representation, checks its canonical form and prices its storage, and never
//! hands a number back.
//!
//! # Example
//!
//! ```
//! use bigu::BigU;
//! use std::str::FromStr;
//!
//! let a = BigU::from_str("340282366920938463463374607431768211456").unwrap(); // 2^128
//! let b = BigU::from(2u32);
//! let (q, r) = a.div_rem(&b).unwrap();
//! assert!(r.is_zero());
//! assert_eq!(q.to_str_radix(16).unwrap(), "80000000000000000000000000000000");
//! ```

#![forbid(unsafe_code)]

// Compile the README's examples as doctests so the quickstart cannot rot.
#[cfg(doctest)]
#[doc = include_str!("../README.md")]
struct ReadmeDoctests;

mod add_sub;
pub mod audit;
mod bigi;
mod bigu;
mod bitops;
mod cmp;
mod div;
mod error;
mod fmt;
pub mod intake;
mod modring;
mod mul;
pub mod poly;
mod prime;
mod radix;
mod ratio;
pub mod reuse;
mod shift;
pub mod wire;

pub use crate::bigi::BigI;
pub use crate::bigu::BigU;
pub use crate::error::{Error, Result};
pub use crate::modring::{CrtBasis, ModInt, ModRing, Reduction};
pub use crate::poly::{AlgebraicNumber, Poly};
pub use crate::ratio::BigQ;
pub use crate::prime::{DETERMINISTIC_PRIME_BOUND, MR_BASES, SMALL_PRIMES};

/// The storage limb: values are kept as base-`2^32` digits.
pub(crate) type Limb = u32;

/// The wide intermediate used for carry, borrow and product accumulation.
pub(crate) type DoubleLimb = u64;

/// Number of value bits in a single [`Limb`].
pub(crate) const LIMB_BITS: u32 = 32;

/// Smallest radix accepted by the string routines.
pub(crate) const MIN_RADIX: u32 = 2;

/// Largest radix accepted by the string routines.
pub(crate) const MAX_RADIX: u32 = 36;
