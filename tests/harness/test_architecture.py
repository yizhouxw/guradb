import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from harnesslib.architecture import cycles, lint
from harnesslib.policy import HarnessError, files, load


class ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.policy, self.architecture, *_ = load(ROOT)

    def write(self, root, path, content):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def fixture(self, root):
        self.write(root, "Cargo.toml", '[workspace]\nmembers = ["modules/storage", "modules/query"]\n'
                   '[workspace.dependencies]\nbackend = { path = "modules/query", package = "query" }\n')
        for module in ("storage", "query"):
            self.write(root, f"modules/{module}/Cargo.toml", f'[package]\nname = "{module}"\nversion = "0.1.0"\n')
            self.write(root, f"modules/{module}/src/lib.rs", "pub fn entry() {}\n")

    def test_upward_dependency_rejected_for_each_cargo_dependency_kind(self):
        for table in ("dependencies", "dev-dependencies", "build-dependencies", "target.'cfg(unix)'.dependencies"):
            with self.subTest(table=table), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root)
                with (root / "modules/storage/Cargo.toml").open("a") as stream:
                    stream.write(f'[{table}]\nbackend = {{ workspace = true }}\n')
                with self.assertRaisesRegex(HarnessError, "storage -> query"):
                    lint(root, self.policy, self.architecture)

    def test_allowed_dependency_and_alias_are_resolved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            with (root / "modules/query/Cargo.toml").open("a") as stream:
                stream.write('[dependencies]\nlocal_store = { path = "../storage", package = "storage" }\n')
            lint(root, self.policy, self.architecture)

    def test_dependency_cycles_even_inside_one_module_are_rejected(self):
        with self.assertRaises(HarnessError):
            cycles({"a": {"b"}, "b": {"a"}})

    def test_unknown_source_and_oversized_source_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "engine.py", "print('not owned')\n")
            with self.assertRaisesRegex(HarnessError, "unowned"):
                lint(root, self.policy, self.architecture)
            (root / "engine.py").unlink()
            self.write(root, "modules/query/src/huge.rs", "// line\n" * 601)
            with self.assertRaisesRegex(HarnessError, "exceeds"):
                lint(root, self.policy, self.architecture)

    def test_python_real_edges_cycles_and_unknown_imports_fail(self):
        cases = [
            ('modules/storage/objects.py', 'from modules.query.service import execute\n', 'storage -> query'),
            ('modules/query/service.py', 'import mystery_package\n', 'undeclared external'),
            ('modules/query/service.py', "__import__('os')\n", 'dynamic code'),
            ('modules/query/service.py', 'import modules.query.missing\n', 'unresolved local'),
        ]
        for path, source, message in cases:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.write(root, 'modules/query/service.py', 'import json\n')
                self.write(root, path, source)
                with self.assertRaisesRegex(HarnessError, message):
                    lint(root, self.policy, self.architecture)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, 'modules/query/a.py', 'from modules.query.b import entry\n')
            self.write(root, 'modules/query/b.py', 'from modules.query.a import entry\n')
            with self.assertRaisesRegex(HarnessError, 'dependency cycle'):
                lint(root, self.policy, self.architecture)

    def test_importlib_metadata_only_direct_version_read_is_safe(self):
        valid = "import importlib.metadata\nvalue = importlib.metadata.version('psycopg')\n"
        unsafe = [
            "import importlib\nimportlib.import_module('modules.query.hidden')\n",
            "import importlib.util\n",
            "from importlib import metadata\n",
            "from importlib.metadata import version\n",
            "import importlib.metadata as metadata\nmetadata.version('x')\n",
            "import importlib.metadata\ngetattr(importlib, 'import_module')('x')\n",
            "import importlib.metadata\nvalue = importlib.metadata\n",
            "import importlib.metadata\nvalue = importlib.metadata.version\n",
            "import importlib.metadata\nimportlib.metadata.version = lambda x: x\n",
            "import importlib.metadata\nimportlib.metadata.distribution('x')\n",
            "import importlib.metadata\n__import__('modules.query.hidden')\n",
        ]
        for source in [valid] + unsafe:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.write(root, 'modules/query/service.py', source)
                if source == valid:
                    lint(root, self.policy, self.architecture)
                else:
                    with self.assertRaisesRegex(HarnessError, 'importlib|dynamic code'):
                        lint(root, self.policy, self.architecture)

    def test_generated_root_data_does_not_hide_nested_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "data/ignored.py", "fixture\n")
            self.write(root, "modules/query/src/data/real.rs", "pub struct Data;\n")
            observed = [path.relative_to(root).as_posix() for path in files(root, set(self.policy["ignored_directories"]))]
            self.assertEqual(observed, ["modules/query/src/data/real.rs"])

    def test_symlink_cannot_hide_production_source(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as elsewhere:
            root = Path(directory)
            (root / "engine").symlink_to(elsewhere, target_is_directory=True)
            with self.assertRaisesRegex(HarnessError, "symlink"):
                files(root, set(self.policy["ignored_directories"]))


if __name__ == "__main__":
    unittest.main()
