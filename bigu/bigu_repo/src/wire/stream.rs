//! [`Read`] and [`Write`] adapters over the frame layout.
//!
//! Framing in memory is a slicing problem; framing on a stream is a *waiting*
//! problem. A reader does not have the whole record when it starts: it has to
//! pull the fixed head, then pull the length prefix a byte at a time because
//! the prefix's own width is not known until its last byte arrives, then pull
//! exactly the declared payload and no more. That sequence is easy to write
//! subtly wrong, and every wrong version is a resynchronization bug that only
//! shows up under a partial read.
//!
//! Two properties are deliberate. Everything here returns [`io::Result`] and
//! never the crate's own `Result`: `error.rs` says in as many words that no
//! variant wraps another error and that there is no `From` glue to outside
//! error types, so the conversion happens *here*, at the boundary, as an
//! [`io::ErrorKind::InvalidData`] carrying the crate error as its source. And
//! every read takes a **ceiling**: a declared length is an instruction from the
//! other end of a socket to allocate, and one that is not bounded by the caller
//! is a way for a peer to exhaust the process. A frame declaring more than the
//! ceiling is refused before a single payload byte is read.

use std::io::{self, Read, Write};

use crate::bigu::BigU;
use crate::error::Error;
use crate::wire::codec::Encoding;
use crate::wire::frame;
use crate::wire::varint::MAX_VARINT_LEN;

/// A payload ceiling for callers with no better number: one mebibyte, which is
/// far more than any sane integer field and far less than a memory exhaustion.
pub const DEFAULT_CEILING: usize = 1 << 20;

/// Turns a crate error into the `InvalidData` an [`io`] caller expects.
fn invalid(err: Error) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, err)
}

/// Writes one framed unsigned value and returns how many bytes went out.
///
/// The frame is written whether or not `enc` itself is framed: the framing is
/// what makes the stream walkable, so it is not optional here.
///
/// ```
/// use bigu::{BigU, wire::{Encoding, stream::write_framed}};
/// let mut out = Vec::new();
/// let n = write_framed(&mut out, &Encoding::new(), &BigU::from(70000u32)).unwrap();
/// assert_eq!(n, out.len());
/// assert_eq!(&out[..2], b"BU");
/// ```
pub fn write_framed<W: Write>(writer: &mut W, enc: &Encoding, value: &BigU) -> io::Result<usize> {
    let bytes = enc.with_frame(true).encode(value).map_err(invalid)?;
    writer.write_all(&bytes)?;
    Ok(bytes.len())
}

/// Pulls one whole frame off the stream, header included, or `None` at a clean
/// end of stream.
///
/// A frame whose declared payload exceeds `ceiling` is refused before the
/// payload is read; a stream that ends part way through a frame is
/// [`io::ErrorKind::UnexpectedEof`].
///
/// ```
/// use bigu::wire::{frame::{frame, Kind}, stream::read_frame_bytes};
/// let blob = frame(Kind::Unsigned, &[1, 2, 3]);
/// let mut src = &blob[..];
/// assert_eq!(read_frame_bytes(&mut src, 64).unwrap().unwrap(), blob);
/// assert!(read_frame_bytes(&mut src, 64).unwrap().is_none()); // clean end
/// // The same frame with a tiny ceiling is refused.
/// assert!(read_frame_bytes(&mut &blob[..], 2).is_err());
/// ```
pub fn read_frame_bytes<R: Read>(reader: &mut R, ceiling: usize) -> io::Result<Option<Vec<u8>>> {
    let mut head = [0u8; 4];
    if reader.read(&mut head[..1])? == 0 {
        return Ok(None);
    }
    reader.read_exact(&mut head[1..])?;
    let mut out = head.to_vec();
    // The length prefix ends at the first byte with a clear top bit, so it has
    // to be pulled one byte at a time; its width is not knowable in advance.
    let mut byte = [0u8; 1];
    loop {
        reader.read_exact(&mut byte)?;
        out.push(byte[0]);
        if byte[0] & 0x80 == 0 {
            break;
        }
        if out.len() - 4 >= MAX_VARINT_LEN {
            return Err(invalid(Error::Overflow));
        }
    }
    let header = frame::peek(&out).map_err(invalid)?;
    if header.payload_len > ceiling {
        return Err(invalid(Error::Overflow));
    }
    out.resize(header.total_len(), 0);
    reader.read_exact(&mut out[header.header_len..])?;
    Ok(Some(out))
}

/// Reads one framed unsigned value written by [`write_framed`].
///
/// ```
/// use bigu::{BigU, wire::{Encoding, stream::{read_framed, write_framed}}};
/// let enc = Encoding::new();
/// let mut buf = Vec::new();
/// write_framed(&mut buf, &enc, &BigU::from(123456u32)).unwrap();
/// let mut src = &buf[..];
/// assert_eq!(read_framed(&mut src, &enc, 64).unwrap(), BigU::from(123456u32));
/// ```
pub fn read_framed<R: Read>(reader: &mut R, enc: &Encoding, ceiling: usize) -> io::Result<BigU> {
    match read_frame_bytes(reader, ceiling)? {
        Some(bytes) => enc.with_frame(true).decode(&bytes).map_err(invalid),
        None => Err(io::Error::new(io::ErrorKind::UnexpectedEof, "stream ended before a frame")),
    }
}

/// An iterator over the frames of a stream, yielding each one as raw bytes.
///
/// Raw bytes rather than decoded values, because a stream may carry more than
/// one [`frame::Kind`]: hand the item to [`Encoding::decode`], to
/// [`frame::decode_ratio`] or to [`frame::unframe`] once its header says which.
/// Iteration stops at a clean end of stream and reports anything else as an
/// error item.
pub struct Frames<R> {
    reader: R,
    ceiling: usize,
}

/// Builds a [`Frames`] iterator with an explicit payload ceiling.
///
/// ```
/// use bigu::{BigU, wire::{Encoding, stream::{frames, write_framed}}};
/// let enc = Encoding::new();
/// let mut buf = Vec::new();
/// for n in [1u32, 300, 70000] {
///     write_framed(&mut buf, &enc, &BigU::from(n)).unwrap();
/// }
/// let values: Vec<BigU> = frames(&buf[..], 64)
///     .map(|f| enc.with_frame(true).decode(&f.unwrap()).unwrap())
///     .collect();
/// assert_eq!(values, vec![BigU::from(1u32), BigU::from(300u32), BigU::from(70000u32)]);
/// ```
pub fn frames<R: Read>(reader: R, ceiling: usize) -> Frames<R> {
    Frames { reader, ceiling }
}

impl<R: Read> Iterator for Frames<R> {
    type Item = io::Result<Vec<u8>>;

    fn next(&mut self) -> Option<io::Result<Vec<u8>>> {
        match read_frame_bytes(&mut self.reader, self.ceiling) {
            Ok(Some(bytes)) => Some(Ok(bytes)),
            Ok(None) => None,
            Err(err) => Some(Err(err)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::wire::frame::Kind;

    #[test]
    fn a_stream_of_frames_round_trips() {
        let enc = Encoding::new();
        let mut buf = Vec::new();
        let values: Vec<BigU> = (0..5).map(|i| BigU::from(2u32).pow(i * 17)).collect();
        for v in &values {
            write_framed(&mut buf, &enc, v).unwrap();
        }
        let read: Vec<BigU> = frames(&buf[..], DEFAULT_CEILING)
            .map(|f| enc.with_frame(true).decode(&f.unwrap()).unwrap())
            .collect();
        assert_eq!(read, values);
    }

    #[test]
    fn a_truncated_frame_is_unexpected_eof() {
        let enc = Encoding::new();
        let mut buf = Vec::new();
        write_framed(&mut buf, &enc, &BigU::from(70000u32)).unwrap();
        buf.pop();
        let err = read_framed(&mut &buf[..], &enc, DEFAULT_CEILING).unwrap_err();
        assert_eq!(err.kind(), io::ErrorKind::UnexpectedEof);
    }

    #[test]
    fn an_empty_stream_yields_nothing_but_read_framed_complains() {
        let empty: &[u8] = &[];
        assert_eq!(frames(empty, DEFAULT_CEILING).count(), 0);
        let err = read_framed(&mut &empty[..], &Encoding::new(), 16).unwrap_err();
        assert_eq!(err.kind(), io::ErrorKind::UnexpectedEof);
    }

    #[test]
    fn a_declared_length_above_the_ceiling_is_refused() {
        let enc = Encoding::new();
        let mut buf = Vec::new();
        write_framed(&mut buf, &enc, &BigU::from(2u32).pow(4000)).unwrap();
        let err = read_framed(&mut &buf[..], &enc, 16).unwrap_err();
        assert_eq!(err.kind(), io::ErrorKind::InvalidData);
        // The same frame under a fitting ceiling reads fine.
        assert!(read_framed(&mut &buf[..], &enc, DEFAULT_CEILING).is_ok());
    }

    #[test]
    fn a_corrupt_header_is_invalid_data_not_eof() {
        let mut buf = frame::frame(Kind::Unsigned, &[1, 2, 3]);
        buf[0] = b'?';
        let err = read_framed(&mut &buf[..], &Encoding::new(), 64).unwrap_err();
        assert_eq!(err.kind(), io::ErrorKind::InvalidData);
    }

    #[test]
    fn an_error_item_does_not_end_iteration_silently() {
        let mut buf = frame::frame(Kind::Unsigned, &[1]);
        buf.extend_from_slice(b"BU\x01\x01"); // a second frame, cut off
        let items: Vec<_> = frames(&buf[..], DEFAULT_CEILING).collect();
        assert_eq!(items.len(), 2);
        assert!(items[0].is_ok());
        assert!(items[1].is_err());
    }
}
