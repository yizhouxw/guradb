from importlib.metadata import version
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


def pins(path):
    result = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        name, pinned = line.split("==")
        result[name.lower().replace("_", "-")] = pinned
    return result


class DependencyTests(unittest.TestCase):
    def test_direct_pins_match_resolved_lock(self):
        direct = pins(ROOT / "requirements-dev.txt")
        locked = pins(ROOT / "requirements-dev.lock")
        for name, pinned in direct.items():
            self.assertEqual(locked.get(name), pinned)

    def test_executing_environment_matches_locked_tools(self):
        for name, pinned in {**pins(ROOT / "requirements-dev.lock"), **pins(ROOT / "requirements-m0.lock")}.items():
            with self.subTest(package=name):
                self.assertEqual(version(name), pinned, "install requirements-dev.lock in the active venv")


if __name__ == "__main__":
    unittest.main()
