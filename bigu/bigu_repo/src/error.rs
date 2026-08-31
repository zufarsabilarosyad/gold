//! Error types for the crate.
//!
//! Every fallible public entry point returns [`Result`], whose error half is
//! the single crate-wide [`Error`] enum. The variants are leaf errors: none
//! wraps another error and there is no `From` glue to outside error types,
//! which keeps the crate dependency-free.

use core::fmt;

/// The set of error conditions that the public API can report.
///
/// `Error` is cheap to clone and compare, which makes it convenient to assert
/// on in tests and to bubble up through application code.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error {
    /// A division or remainder was requested with a zero divisor.
    DivByZero,
    /// An unsigned subtraction would have produced a negative result.
    Underflow,
    /// A parse routine was handed a string with no usable digits.
    EmptyString,
    /// A character was not a valid digit for the requested radix.
    InvalidDigit {
        /// The offending character.
        ch: char,
        /// The radix that rejected it.
        radix: u32,
    },
    /// A radix outside the supported `2..=36` range was supplied.
    UnsupportedRadix(u32),
    /// A narrowing conversion lost information because the value was too large.
    Overflow,
    /// A modular inverse was requested for a value that shares a factor with the
    /// modulus, so no inverse exists.
    NotInvertible,
    /// Montgomery reduction was requested for an even modulus, which the
    /// algorithm cannot represent: it needs the modulus coprime to a power of
    /// two.
    EvenModulus,
    /// Two modular values were combined that do not belong to the same ring, or
    /// a residue vector did not match the basis it was handed to.
    ModulusMismatch,
    /// A set of moduli that must be pairwise coprime contained two entries
    /// sharing a factor.
    NotCoprime,
    /// A basis was requested over an empty set of moduli.
    EmptyBasis,
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::DivByZero => f.write_str("division by zero"),
            Error::Underflow => f.write_str("unsigned subtraction underflow"),
            Error::EmptyString => f.write_str("cannot parse an empty string"),
            Error::InvalidDigit { ch, radix } => {
                write!(f, "invalid digit {ch:?} for radix {radix}")
            }
            Error::UnsupportedRadix(r) => {
                write!(f, "unsupported radix {r}; must be in 2..=36")
            }
            Error::Overflow => f.write_str("value does not fit in the target type"),
            Error::NotInvertible => f.write_str("value has no modular inverse"),
            Error::EvenModulus => {
                f.write_str("Montgomery reduction requires an odd modulus")
            }
            Error::ModulusMismatch => f.write_str("values do not share a modulus"),
            Error::NotCoprime => f.write_str("moduli are not pairwise coprime"),
            Error::EmptyBasis => f.write_str("cannot build a basis with no moduli"),
        }
    }
}

impl std::error::Error for Error {}

/// Convenience alias for results produced by this crate.
pub type Result<T> = core::result::Result<T, Error>;
