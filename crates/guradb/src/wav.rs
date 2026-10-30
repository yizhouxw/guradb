//! Strict complete PCM16 RIFF/WAVE; no decoder, resampling or inference.
use crate::{Error, Result};
use serde::Serialize;
#[derive(Serialize)]
pub struct Audio {
    pub encoding: &'static str,
    pub sample_rate: u32,
    pub channels: u16,
    pub bits_per_sample: u16,
    pub frames: usize,
}
fn invalid() -> Error {
    Error::new("invalid_media_format", "unsupported or malformed PCM16 WAV")
}
pub fn inspect(bytes: &[u8]) -> Result<Audio> {
    if bytes.len() < 44
        || bytes.get(..4) != Some(b"RIFF")
        || bytes.get(8..16) != Some(b"WAVEfmt ")
        || bytes.get(36..40) != Some(b"data")
    {
        return Err(invalid());
    }
    let u16at = |at| u16::from_le_bytes([bytes[at], bytes[at + 1]]);
    let u32at = |at| u32::from_le_bytes([bytes[at], bytes[at + 1], bytes[at + 2], bytes[at + 3]]);
    let channels = u16at(22);
    let rate = u32at(24);
    let align = u16at(32);
    let data = u32at(40) as usize;
    if u32at(4) as usize != bytes.len() - 8
        || u32at(16) != 16
        || u16at(20) != 1
        || !matches!(channels, 1 | 2)
        || rate != 44100
        || u16at(34) != 16
        || align != channels * 2
        || u32at(28) != rate * u32::from(align)
        || data == 0
        || !data.is_multiple_of(usize::from(align))
        || data.checked_add(44) != Some(bytes.len())
    {
        return Err(invalid());
    }
    Ok(Audio {
        encoding: "pcm_s16le",
        sample_rate: rate,
        channels,
        bits_per_sample: 16,
        frames: data / usize::from(align),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    fn pcm() -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend(b"RIFF");
        bytes.extend(44u32.to_le_bytes());
        bytes.extend(b"WAVEfmt ");
        bytes.extend(16u32.to_le_bytes());
        bytes.extend(1u16.to_le_bytes());
        bytes.extend(2u16.to_le_bytes());
        bytes.extend(44100u32.to_le_bytes());
        bytes.extend(176400u32.to_le_bytes());
        bytes.extend(4u16.to_le_bytes());
        bytes.extend(16u16.to_le_bytes());
        bytes.extend(b"data");
        bytes.extend(8u32.to_le_bytes());
        for sample in [i16::MIN, 0, 1, i16::MAX] {
            bytes.extend(sample.to_le_bytes());
        }
        bytes
    }
    #[test]
    fn complete_pcm_metadata_and_payload_are_unchanged() {
        let bytes = pcm();
        let audio = inspect(&bytes).unwrap();
        assert_eq!(audio.frames, 2);
        assert_eq!(audio.channels, 2);
        assert_eq!(audio.sample_rate, 44100);
        assert_eq!(&bytes[44..], &[0, 128, 0, 0, 1, 0, 255, 127]);
    }
    #[test]
    fn wrong_container_fmt_rate_alignment_chunks_and_truncation_refuse() {
        let bytes = pcm();
        for (at, replacement) in [
            (0, b'X'),
            (8, b'X'),
            (12, b'X'),
            (16, 18),
            (20, 3),
            (22, 3),
            (24, 0),
            (28, 0),
            (32, 2),
            (34, 8),
            (36, b'X'),
            (40, 7),
            (4, 43),
        ] {
            let mut bad = bytes.clone();
            bad[at] = replacement;
            assert!(inspect(&bad).is_err(), "accepted bad offset {at}");
        }
        assert!(inspect(&bytes[..bytes.len() - 1]).is_err());
        let mut extra = bytes;
        extra.extend(b"JUNK");
        assert!(inspect(&extra).is_err());
    }
}
