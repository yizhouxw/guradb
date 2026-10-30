//! Small synthetic DIB: two-by-two top-down BGR pixels, one frame at 5 fps.
//! Public Sintel truth is independently decoded outside this private fixture.
fn word(out: &mut [u8], at: usize, value: u32) {
    out[at..at + 4].copy_from_slice(&value.to_le_bytes());
}
fn chunk(id: &[u8; 4], body: &[u8]) -> Vec<u8> {
    let mut out = id.to_vec();
    out.extend((body.len() as u32).to_le_bytes());
    out.extend(body);
    if body.len() % 2 == 1 {
        out.push(0);
    }
    out
}
fn list(kind: &[u8; 4], parts: Vec<Vec<u8>>) -> Vec<u8> {
    let mut body = kind.to_vec();
    for part in parts {
        body.extend(part);
    }
    chunk(b"LIST", &body)
}
pub fn small() -> Vec<u8> {
    let mut main = [0; 56];
    word(&mut main, 0, 200_000);
    word(&mut main, 12, 0x10);
    word(&mut main, 16, 1);
    word(&mut main, 24, 1);
    word(&mut main, 32, 2);
    word(&mut main, 36, 2);
    let mut stream = [0; 56];
    stream[..4].copy_from_slice(b"vids");
    stream[4..8].copy_from_slice(b"DIB ");
    word(&mut stream, 20, 1);
    word(&mut stream, 24, 5);
    word(&mut stream, 32, 1);
    stream[52..54].copy_from_slice(&2u16.to_le_bytes());
    stream[54..56].copy_from_slice(&2u16.to_le_bytes());
    let mut format = [0; 40];
    word(&mut format, 0, 40);
    word(&mut format, 4, 2);
    word(&mut format, 8, (-2i32) as u32);
    format[12..14].copy_from_slice(&1u16.to_le_bytes());
    format[14..16].copy_from_slice(&24u16.to_le_bytes());
    word(&mut format, 20, 16);
    // Red, white / blue, green; each six-byte row has two padding bytes.
    let pixels = [0, 0, 255, 255, 255, 255, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0];
    let mut index = [0; 16];
    index[..4].copy_from_slice(b"00db");
    word(&mut index, 4, 0x10);
    word(&mut index, 8, 4);
    word(&mut index, 12, 16);
    let mut body = b"AVI ".to_vec();
    body.extend(list(
        b"hdrl",
        vec![
            chunk(b"avih", &main),
            list(
                b"strl",
                vec![chunk(b"strh", &stream), chunk(b"strf", &format)],
            ),
        ],
    ));
    body.extend(list(b"movi", vec![chunk(b"00db", &pixels)]));
    body.extend(chunk(b"idx1", &index));
    chunk(b"RIFF", &body)
}
