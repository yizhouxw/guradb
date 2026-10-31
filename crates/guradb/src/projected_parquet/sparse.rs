//! No file, HTTP, zero fill, or whole-source fallback exists in this reader.
use bytes::Bytes;
use parquet::{
    errors::{ParquetError, Result},
    file::reader::{ChunkReader, Length},
};
use std::{
    io::{self, Read},
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
};

#[derive(Clone)]
pub(super) struct Sparse {
    pub length: u64,
    pub segments: Vec<(u64, Bytes)>,
    pub read_calls: Arc<AtomicUsize>,
}
pub(super) struct SliceRead {
    bytes: Bytes,
    position: usize,
}
impl Read for SliceRead {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        if out.is_empty() {
            return Ok(0);
        }
        if self.position == self.bytes.len() {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "unavailable sparse bytes",
            ));
        }
        let count = out.len().min(self.bytes.len() - self.position);
        out[..count].copy_from_slice(&self.bytes[self.position..self.position + count]);
        self.position += count;
        Ok(count)
    }
}
impl Length for Sparse {
    fn len(&self) -> u64 {
        self.length
    }
}
impl Sparse {
    fn slice(&self, start: u64, length: Option<usize>) -> Result<Bytes> {
        for (offset, bytes) in &self.segments {
            if let Some(begin) = start
                .checked_sub(*offset)
                .and_then(|n| usize::try_from(n).ok())
            {
                if begin < bytes.len() {
                    let end = length
                        .and_then(|n| begin.checked_add(n))
                        .unwrap_or(bytes.len());
                    if end <= bytes.len() && length.is_none_or(|n| end - begin == n) {
                        return Ok(bytes.slice(begin..end));
                    }
                }
            }
        }
        Err(ParquetError::EOF("unavailable sparse bytes".into()))
    }
}
impl ChunkReader for Sparse {
    type T = SliceRead;
    fn get_read(&self, start: u64) -> Result<Self::T> {
        self.read_calls.fetch_add(1, Ordering::Relaxed);
        Ok(SliceRead {
            bytes: self.slice(start, None)?,
            position: 0,
        })
    }
    fn get_bytes(&self, start: u64, length: usize) -> Result<Bytes> {
        self.slice(start, Some(length))
    }
}
