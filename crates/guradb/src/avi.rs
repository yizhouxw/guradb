//! Bounded AVI 1.0 with one complete, uncompressed BGR24 video stream.
//! Layout follows Microsoft's AVI RIFF and BITMAPINFOHEADER references.
use crate::{Error, Result};
use serde::Serialize;

#[derive(Serialize)]
pub struct Video {
    pub container: &'static str,
    pub encoding: &'static str,
    pub width: u32,
    pub height: u32,
    pub row_order: &'static str,
    pub row_stride: usize,
    pub frames: usize,
    pub rate_num: u32,
    pub rate_den: u32,
    pub duration_num: usize,
    pub duration_den: u32,
}
fn invalid() -> Error {
    Error::new(
        "invalid_media_format",
        "unsupported or malformed AVI BGR24 video",
    )
}
fn word(bytes: &[u8], at: usize) -> Result<u32> {
    let end = at.checked_add(4).ok_or_else(invalid)?;
    Ok(u32::from_le_bytes(
        bytes
            .get(at..end)
            .ok_or_else(invalid)?
            .try_into()
            .map_err(|_| invalid())?,
    ))
}
fn short(bytes: &[u8], at: usize) -> Result<u16> {
    let end = at.checked_add(2).ok_or_else(invalid)?;
    Ok(u16::from_le_bytes(
        bytes
            .get(at..end)
            .ok_or_else(invalid)?
            .try_into()
            .map_err(|_| invalid())?,
    ))
}
struct Chunk<'a> {
    id: &'a [u8],
    body: &'a [u8],
    start: usize,
}
fn chunks<'a>(bytes: &'a [u8], base: usize, count: &mut usize) -> Result<Vec<Chunk<'a>>> {
    let mut result = Vec::new();
    let mut at = 0usize;
    while at < bytes.len() {
        *count += 1;
        if *count > 128 {
            return Err(invalid());
        }
        let begin = at.checked_add(8).ok_or_else(invalid)?;
        let size = word(bytes, at.checked_add(4).ok_or_else(invalid)?)? as usize;
        let end = begin.checked_add(size).ok_or_else(invalid)?;
        let next = end.checked_add(size & 1).ok_or_else(invalid)?;
        if next > bytes.len() {
            return Err(invalid());
        }
        result.push(Chunk {
            id: bytes.get(at..at + 4).ok_or_else(invalid)?,
            body: bytes.get(begin..end).ok_or_else(invalid)?,
            start: base.checked_add(at).ok_or_else(invalid)?,
        });
        at = next;
    }
    Ok(result)
}
fn list_type<'a>(c: &Chunk<'a>) -> Result<&'a [u8]> {
    if c.id != b"LIST" {
        return Err(invalid());
    }
    c.body.get(..4).ok_or_else(invalid)
}
fn children<'a>(c: &Chunk<'a>, count: &mut usize) -> Result<Vec<Chunk<'a>>> {
    chunks(
        c.body.get(4..).ok_or_else(invalid)?,
        c.start.checked_add(12).ok_or_else(invalid)?,
        count,
    )
}
fn headers<'a>(header: &Chunk<'a>, count: &mut usize) -> Result<(&'a [u8], &'a [u8], &'a [u8])> {
    let mut main = None;
    let mut stream = None;
    for c in children(header, count)? {
        match c.id {
            b"avih" if main.is_none() && stream.is_none() && c.body.len() == 56 => {
                main = Some(c.body)
            }
            b"LIST" if main.is_some() && stream.is_none() && list_type(&c)? == b"strl" => {
                stream = Some(c)
            }
            b"JUNK" => (),
            _ => return Err(invalid()),
        }
    }
    let stream = stream.ok_or_else(invalid)?;
    let mut h = None;
    let mut format = None;
    for c in children(&stream, count)? {
        match c.id {
            b"strh" if h.is_none() && format.is_none() && c.body.len() == 56 => h = Some(c.body),
            b"strf" if h.is_some() && format.is_none() && c.body.len() == 40 => {
                format = Some(c.body)
            }
            b"JUNK" => (),
            _ => return Err(invalid()),
        }
    }
    Ok((
        main.ok_or_else(invalid)?,
        h.ok_or_else(invalid)?,
        format.ok_or_else(invalid)?,
    ))
}
pub fn inspect(bytes: &[u8]) -> Result<Video> {
    if bytes.len() > crate::media::MEDIA_LIMIT
        || bytes.get(..4) != Some(b"RIFF")
        || bytes.get(8..12) != Some(b"AVI ")
        || (word(bytes, 4)? as usize).checked_add(8) != Some(bytes.len())
    {
        return Err(invalid());
    }
    let mut count = 0;
    let top = chunks(bytes.get(12..).ok_or_else(invalid)?, 12, &mut count)?;
    let (mut header, mut movie, mut index) = (None, None, None);
    let mut info_seen = false;
    for c in top {
        match c.id {
            b"LIST" => match list_type(&c)? {
                b"hdrl" if header.is_none() && movie.is_none() && index.is_none() => {
                    header = Some(c)
                }
                b"movi" if header.is_some() && movie.is_none() && index.is_none() => {
                    movie = Some(c)
                }
                b"INFO" if header.is_some() && movie.is_none() && !info_seen => {
                    for item in children(&c, &mut count)? {
                        if !item.id.is_ascii() || matches!(item.id, b"LIST" | b"RIFF") {
                            return Err(invalid());
                        }
                    }
                    info_seen = true;
                }
                _ => return Err(invalid()),
            },
            b"idx1" if movie.is_some() && index.is_none() => index = Some(c),
            b"JUNK" if index.is_none() => (),
            _ => return Err(invalid()),
        }
    }
    let header = header.ok_or_else(invalid)?;
    let movie = movie.ok_or_else(invalid)?;
    let index = index.ok_or_else(invalid)?;
    let (main, stream, format) = headers(&header, &mut count)?;
    let width = word(format, 4)? as i32;
    let signed_height = word(format, 8)? as i32;
    let height = signed_height.checked_abs().ok_or_else(invalid)?;
    if !(1..=320).contains(&width)
        || !(1..=240).contains(&height)
        || word(format, 0)? != 40
        || short(format, 12)? != 1
        || short(format, 14)? != 24
        || word(format, 16)? != 0
        || word(format, 32)? != 0
        || word(format, 36)? != 0
    {
        return Err(invalid());
    }
    let width = width as u32;
    let height = height as u32;
    let stride = (width as usize * 3).checked_add(3).ok_or_else(invalid)? & !3;
    let frame_bytes = stride.checked_mul(height as usize).ok_or_else(invalid)?;
    if ![0, frame_bytes as u32].contains(&word(format, 20)?) {
        return Err(invalid());
    }
    let rate = word(stream, 24)?;
    let frames = word(stream, 32)? as usize;
    let flags = word(main, 12)?;
    if stream.get(..4) != Some(b"vids")
        || ![&b"\0\0\0\0"[..], &b"DIB "[..]].contains(&stream.get(4..8).ok_or_else(invalid)?)
        || word(stream, 8)? != 0
        || word(stream, 12)? != 0
        || word(stream, 16)? != 0
        || word(stream, 20)? != 1
        || !(1..=30).contains(&rate)
        || word(stream, 28)? != 0
        || !(1..=30).contains(&frames)
        || word(stream, 44)? != 0
        || short(stream, 48)? != 0
        || short(stream, 50)? != 0
        || short(stream, 52)? != width as u16
        || short(stream, 54)? != height as u16
        || word(main, 0)? != 1_000_000 / rate
        || word(main, 8)? != 0
        || flags & 0x10 == 0
        || flags & !0x910 != 0
        || word(main, 16)? as usize != frames
        || word(main, 20)? != 0
        || word(main, 24)? != 1
        || word(main, 32)? != width
        || word(main, 36)? != height
        || main.get(40..56).is_none_or(|b| b.iter().any(|v| *v != 0))
    {
        return Err(invalid());
    }
    let data = children(&movie, &mut count)?;
    if data.len() != frames || index.body.len() != frames.checked_mul(16).ok_or_else(invalid)? {
        return Err(invalid());
    }
    for (i, frame) in data.iter().enumerate() {
        let at = i * 16;
        let offset = frame
            .start
            .checked_sub(movie.start.checked_add(8).ok_or_else(invalid)?)
            .ok_or_else(invalid)?;
        if !matches!(frame.id, b"00dc" | b"00db")
            || frame.body.len() != frame_bytes
            || index.body.get(at..at + 4) != Some(frame.id)
            || word(index.body, at + 4)? != 0x10
            || word(index.body, at + 8)? as usize != offset
            || word(index.body, at + 12)? as usize != frame_bytes
        {
            return Err(invalid());
        }
    }
    Ok(Video {
        container: "avi",
        encoding: "bgr24",
        width,
        height,
        row_order: if signed_height < 0 {
            "top_down"
        } else {
            "bottom_up"
        },
        row_stride: stride,
        frames,
        rate_num: rate,
        rate_den: 1,
        duration_num: frames,
        duration_den: rate,
    })
}
