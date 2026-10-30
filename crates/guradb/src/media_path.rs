//! Root-anchored, no-follow Unix opens; no directory discovery or writes.
use crate::{Error, Result};
use std::{
    ffi::CString,
    fs::{File, OpenOptions},
    io::Read,
    os::{
        fd::{AsRawFd, FromRawFd},
        unix::fs::OpenOptionsExt,
    },
    path::Path,
};

fn child(parent: &File, name: &str, directory: bool) -> Result<File> {
    let name = CString::new(name).map_err(|_| Error::new("media_invalid", "invalid media name"))?;
    let flags = libc::O_RDONLY
        | libc::O_CLOEXEC
        | libc::O_NOFOLLOW
        | libc::O_NONBLOCK
        | if directory { libc::O_DIRECTORY } else { 0 };
    // SAFETY: parent is live, name is NUL terminated, flags are read-only. The
    // returned owned descriptor is immediately wrapped once and closed by RAII.
    let fd = unsafe { libc::openat(parent.as_raw_fd(), name.as_ptr(), flags) };
    if fd < 0 {
        return Err(Error::new(
            "media_invalid",
            "media is missing, linked or unavailable",
        ));
    }
    // SAFETY: successful openat returns a fresh descriptor owned by this call.
    Ok(unsafe { File::from_raw_fd(fd) })
}

pub fn read(root: &Path, file_name: &str, expected_size: usize) -> Result<Vec<u8>> {
    read_typed(root, "images", file_name, expected_size)
}
pub(crate) fn read_typed(
    root: &Path,
    directory: &str,
    file_name: &str,
    expected_size: usize,
) -> Result<Vec<u8>> {
    if !matches!(directory, "images" | "audio" | "videos")
        || file_name.contains('/')
        || file_name.contains("..")
    {
        return Err(Error::new("media_invalid", "invalid media path"));
    }
    let root = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(root)
        .map_err(|_| Error::new("media_invalid", "media root is unavailable or linked"))?;
    let directory = child(&root, directory, true)?;
    let file = child(&directory, file_name, false)?;
    let metadata = file
        .metadata()
        .map_err(|_| Error::new("media_invalid", "cannot inspect media"))?;
    if !metadata.is_file() {
        return Err(Error::new("media_invalid", "media must be a regular file"));
    }
    if metadata.len() > super::media::MEDIA_LIMIT as u64 {
        return Err(Error::new("resource_limit", "media exceeds 512 KiB"));
    }
    if metadata.len() != expected_size as u64 {
        return Err(Error::new(
            "media_changed",
            "media size differs from bound input",
        ));
    }
    let mut bytes = Vec::new();
    file.take((super::media::MEDIA_LIMIT + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| Error::new("media_invalid", "cannot read media"))?;
    if bytes.len() > super::media::MEDIA_LIMIT {
        return Err(Error::new("resource_limit", "media exceeds 512 KiB"));
    }
    if bytes.len() != expected_size {
        return Err(Error::new(
            "media_changed",
            "media size changed while reading",
        ));
    }
    Ok(bytes)
}
