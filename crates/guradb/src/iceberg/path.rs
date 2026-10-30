//! Component-anchored local relocation; never opens a URI as a host path.
use super::invalid;
use crate::{Error, Result};
use std::{
    ffi::CString,
    fs::File,
    io::Read,
    os::fd::{AsRawFd, FromRawFd},
    path::Path,
};

pub fn relative(value: &str) -> Result<()> {
    components(value, 16)
}
fn components(value: &str, depth: usize) -> Result<()> {
    if value.is_empty()
        || value.len() > 4096
        || !value.is_ascii()
        || value.starts_with('/')
        || value
            .bytes()
            .any(|b| b <= 32 || b >= 127 || b"%?#\\:\0".contains(&b))
    {
        return Err(invalid());
    }
    let parts: Vec<_> = value.split('/').collect();
    if parts.len() > depth
        || parts
            .iter()
            .any(|p| p.is_empty() || p.len() > 255 || *p == "." || *p == "..")
    {
        return Err(invalid());
    }
    Ok(())
}
fn absolute(value: &str, root: bool) -> Result<String> {
    if value.len() > 4096 {
        return Err(invalid());
    }
    let value = value.strip_prefix("file://").unwrap_or(value);
    if !value.starts_with('/') || value.starts_with("//") {
        return Err(invalid());
    }
    let value = if root {
        value.strip_suffix('/').unwrap_or(value)
    } else {
        value
    };
    components(
        value.strip_prefix('/').ok_or_else(invalid)?,
        if root { 16 } else { 32 },
    )?;
    Ok(value.to_string())
}
pub fn logical_root(value: &str) -> Result<String> {
    absolute(value, true)
}
pub fn relocate(logical: &str, reference: &str) -> Result<String> {
    let reference = absolute(reference, false)?;
    let relative_path = reference
        .strip_prefix(logical)
        .and_then(|p| p.strip_prefix('/'))
        .ok_or_else(invalid)?;
    relative(relative_path)?;
    Ok(relative_path.to_string())
}
fn child(parent: &File, name: &str, directory: bool) -> Result<File> {
    let name = CString::new(name).map_err(|_| invalid())?;
    let flags = libc::O_RDONLY
        | libc::O_CLOEXEC
        | libc::O_NOFOLLOW
        | libc::O_NONBLOCK
        | if directory { libc::O_DIRECTORY } else { 0 };
    // SAFETY: parent remains live, name is terminated, successful fd is owned once.
    let fd = unsafe { libc::openat(parent.as_raw_fd(), name.as_ptr(), flags) };
    if fd < 0 {
        return Err(invalid());
    }
    Ok(unsafe { File::from_raw_fd(fd) })
}
pub struct Root(File);
impl Root {
    pub fn open(path: &Path) -> Result<Self> {
        let value = path.to_str().ok_or_else(invalid)?;
        if value.len() > 4096 || !value.starts_with('/') || value.starts_with("//") {
            return Err(invalid());
        }
        relative(value.strip_prefix('/').ok_or_else(invalid)?)?;
        let mut directory = File::open("/").map_err(|_| invalid())?;
        for part in value[1..].split('/') {
            directory = child(&directory, part, true)?;
        }
        Ok(Self(directory))
    }
    pub fn read(&self, path: &str, limit: usize) -> Result<Vec<u8>> {
        relative(path)?;
        let mut parts = path.split('/').peekable();
        let mut directory = self.0.try_clone().map_err(|_| invalid())?;
        while let Some(part) = parts.next() {
            let file = child(&directory, part, parts.peek().is_some())?;
            if parts.peek().is_some() {
                directory = file;
                continue;
            }
            let metadata = file.metadata().map_err(|_| invalid())?;
            if !metadata.is_file() {
                return Err(invalid());
            }
            if metadata.len() > limit as u64 {
                return Err(Error::new(
                    "resource_limit",
                    "Iceberg file exceeds byte budget",
                ));
            }
            let mut bytes = Vec::new();
            file.take((limit + 1) as u64)
                .read_to_end(&mut bytes)
                .map_err(|_| invalid())?;
            if bytes.len() > limit {
                return Err(Error::new(
                    "resource_limit",
                    "Iceberg file exceeds byte budget",
                ));
            }
            if bytes.len() as u64 != metadata.len() {
                return Err(Error::new(
                    "source_changed",
                    "Iceberg file changed during read",
                ));
            }
            return Ok(bytes);
        }
        Err(invalid())
    }
}
