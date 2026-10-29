"""Check only changed Rust files with the existing pinned container toolchain."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from cargo import IMAGE  # One toolchain/image authority, shared with Cargo checks.


def main(paths):
    if not paths:
        raise ValueError("core rustfmt needs changed Rust files")
    for name in paths:
        path = ROOT/name
        if (not name.startswith("crates/") or not name.endswith(".rs") or path.is_symlink()
                or not path.resolve().is_relative_to(ROOT) or not path.is_file()):
            raise ValueError("core rustfmt requires existing repository Rust sources")
    subprocess.run(["docker", "build", "-q", "-t", IMAGE, "-f", "tools/m0/Dockerfile", "."],
                   cwd=ROOT, check=True)
    return subprocess.run(["docker", "run", "--rm", "-v", f"{ROOT}:/workspace", "-w", "/workspace",
        IMAGE, "rustfmt", "--edition", "2021", "--check", "--config", "skip_children=true", *paths],
        cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
