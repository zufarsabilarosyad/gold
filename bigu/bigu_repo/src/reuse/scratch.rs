//! The borrow-use-return handle over a [`LimbPool`].
//!
//! A pool is only a saving if buffers actually come back, and the one place they
//! reliably fail to come back is the error path. A routine that draws a buffer,
//! hits [`Error::DivByZero`](crate::Error::DivByZero) halfway through and leaves
//! with `?` has skipped its own `recycle` call, and auditing every early return
//! for that is exactly the discipline that rots.
//!
//! [`Scratch`] moves the obligation into the type system. It borrows the pool,
//! carries the buffer, derefs to it so the caller works with an ordinary
//! `Vec<Limb>`, and returns it in `Drop` — which runs on the `?` path, on a
//! plain early `return`, and on unwind, without a line of `unsafe`. That last
//! point is not a preference: the crate is `#![forbid(unsafe_code)]`, so a
//! hand-rolled guard holding a raw pointer back to the pool was never on offer.
//!
//! The handle takes `&mut LimbPool`, because giving the buffer back needs
//! mutable access to the pool at drop time. One scratch is live per pool at a
//! time; a routine needing two working buffers takes one and splits it.

use core::ops::{Deref, DerefMut};

use super::pool::LimbPool;
use crate::Limb;

/// A limb buffer borrowed from a [`LimbPool`], returned when it drops.
///
/// ```
/// let mut pool = bigu::reuse::LimbPool::new();
/// {
///     let mut s = pool.scratch(4);
///     s.push(7);
///     assert_eq!(s.len(), 1);
/// } // returned here
/// assert_eq!(pool.stored_buffers(), 1);
/// ```
#[derive(Debug)]
pub struct Scratch<'p> {
    pool: &'p mut LimbPool,
    /// `None` only after [`Scratch::detach`] has taken the buffer away.
    buf: Option<Vec<Limb>>,
}

impl LimbPool {
    /// Borrows a scratch buffer of at least `n` limbs, empty on arrival and
    /// returned to the pool when the handle drops, however the scope is left.
    ///
    /// ```
    /// let mut pool = bigu::reuse::LimbPool::new();
    /// let s = pool.scratch(16);
    /// assert!(s.is_empty() && s.capacity() >= 16);
    /// ```
    pub fn scratch(&mut self, n: usize) -> Scratch<'_> {
        let buf = self.take(n);
        Scratch { pool: self, buf: Some(buf) }
    }
}

impl Scratch<'_> {
    /// Takes the buffer out of the handle, opting out of recycling.
    ///
    /// This is the escape hatch for the case where the scratch buffer *becomes*
    /// the result: the limbs are wanted by the caller, so handing them back to
    /// the pool would be wrong.
    ///
    /// ```
    /// let mut pool = bigu::reuse::LimbPool::new();
    /// let mut s = pool.scratch(4);
    /// s.push(3);
    /// assert_eq!(s.detach(), vec![3u32]);
    /// assert_eq!(pool.stored_buffers(), 0);
    /// ```
    pub fn detach(mut self) -> Vec<Limb> {
        self.buf.take().unwrap_or_default()
    }
}

impl Deref for Scratch<'_> {
    type Target = Vec<Limb>;

    fn deref(&self) -> &Vec<Limb> {
        // `buf` is only ever `None` inside `detach`, which consumes the handle.
        self.buf.as_ref().expect("scratch buffer already detached")
    }
}

impl DerefMut for Scratch<'_> {
    fn deref_mut(&mut self) -> &mut Vec<Limb> {
        self.buf.as_mut().expect("scratch buffer already detached")
    }
}

impl Drop for Scratch<'_> {
    fn drop(&mut self) {
        if let Some(buf) = self.buf.take() {
            self.pool.recycle(buf);
        }
    }
}

/// Runs `f` with a scratch buffer of at least `n` limbs and returns its result.
///
/// The buffer goes back to the pool before this returns, including when `f`
/// leaves early through `?` — the shape most of the arithmetic core wants, a
/// working buffer whose lifetime is exactly one fallible operation.
///
/// ```
/// use bigu::reuse::{with_scratch, LimbPool};
/// use bigu::Error;
///
/// let mut pool = LimbPool::new();
/// let sum = with_scratch(&mut pool, 8, |buf| {
///     buf.extend_from_slice(&[1, 2, 3]);
///     buf.iter().map(|&l| l as u64).sum::<u64>()
/// });
/// assert_eq!(sum, 6);
///
/// // The failing path recycles just the same.
/// let failed: Result<(), Error> = with_scratch(&mut pool, 8, |buf| {
///     buf.push(1);
///     Err(Error::DivByZero)
/// });
/// assert_eq!(failed, Err(Error::DivByZero));
/// assert_eq!(pool.stored_buffers(), 1);
/// ```
pub fn with_scratch<R, F>(pool: &mut LimbPool, n: usize, f: F) -> R
where
    F: FnOnce(&mut Vec<Limb>) -> R,
{
    let mut scratch = pool.scratch(n);
    f(&mut scratch)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::error::{Error, Result};

    /// A fallible routine shaped like the arithmetic core's: draw a buffer,
    /// fail partway, leave through an early return.
    fn fallible(pool: &mut LimbPool, fail: bool) -> Result<Limb> {
        let mut s = pool.scratch(32);
        s.push(5);
        if fail {
            return Err(Error::Underflow);
        }
        Ok(s[0])
    }

    #[test]
    fn the_buffer_returns_on_the_error_path() {
        let mut pool = LimbPool::new();
        assert_eq!(fallible(&mut pool, true), Err(Error::Underflow));
        assert_eq!(pool.stored_buffers(), 1);
        assert_eq!(fallible(&mut pool, false), Ok(5));
        assert_eq!(pool.stored_buffers(), 1);
        assert_eq!(pool.metrics().pool_hits, 1, "the second call reused it");
    }

    #[test]
    fn a_detached_buffer_does_not_come_back() {
        let mut pool = LimbPool::new();
        let mut s = pool.scratch(4);
        s.extend_from_slice(&[1, 2]);
        assert_eq!(s.len(), 2);
        assert_eq!(s.detach(), vec![1 as Limb, 2]);
        assert_eq!(pool.stored_buffers(), 0);
        assert!(pool.metrics().limbs_outstanding >= 4, "still charged");
    }

    #[test]
    fn nested_scopes_reuse_one_buffer_in_sequence() {
        let mut pool = LimbPool::new();
        for _ in 0..10 {
            let mut s = pool.scratch(64);
            s.resize(64, 1);
            assert_eq!(s.iter().copied().max(), Some(1 as Limb));
        }
        assert_eq!(pool.stored_buffers(), 1);
        assert_eq!((pool.metrics().pool_hits, pool.metrics().pool_misses), (9, 1));
    }

    #[test]
    fn an_unwinding_closure_still_returns_the_buffer() {
        let mut pool = LimbPool::new();
        let caught: std::thread::Result<()> =
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                with_scratch(&mut pool, 8, |buf| {
                    buf.push(1);
                    panic!("mid-operation");
                })
            }));
        assert!(caught.is_err());
        assert_eq!(pool.stored_buffers(), 1);
    }
}
