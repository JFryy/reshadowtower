import hashlib
import io
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import dependencies


class DependencyTests(unittest.TestCase):
    def make_framework(self, source: Path) -> None:
        for name in dependencies.REQUIRED_FILES:
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("source", encoding="utf-8")

    def test_pins_cover_framework_and_nested_libraries(self):
        pins = dependencies.dependency_pins()
        self.assertEqual([pin["path"] for pin in pins],
                         ["", "lib/recomp-net", "lib/retcomm-rbengine"])
        for pin in pins:
            self.assertRegex(pin["revision"], r"^[0-9a-f]{40}$")
            self.assertRegex(pin["sha256"], r"^[0-9a-f]{64}$")

    def test_explicit_sources_do_not_fetch_or_require_git(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "framework"
            self.make_framework(source)
            with mock.patch.dict(os.environ, {"PSXRECOMP_ROOT": str(source)}), \
                 mock.patch.object(dependencies.subprocess, "run") as run:
                self.assertEqual(dependencies.framework_root(Path(directory)), source)
            run.assert_not_called()

    def test_incomplete_override_fails_without_fetching(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            with mock.patch.dict(os.environ, {"PSXRECOMP_ROOT": str(source)}), \
                 mock.patch.object(dependencies.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "missing runtime/runtime.cmake"):
                    dependencies.framework_root(source)
            run.assert_not_called()

    def test_bundled_release_sources_are_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = project / "psxrecomp"
            self.make_framework(source)
            with mock.patch.dict(os.environ, {}, clear=True), \
                 mock.patch.object(dependencies.subprocess, "run") as run:
                self.assertEqual(dependencies.framework_root(project), source)
            run.assert_not_called()

    def test_developer_bootstrap_uses_shared_cmake_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / ".git").mkdir()
            source = project / "build-dependencies/_deps/psxrecomp-src"
            self.make_framework(source)
            (project / "build-dependencies/psxrecomp-source-dir.txt").write_text(
                str(source) + "\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True), \
                 mock.patch.object(dependencies.subprocess, "run") as run:
                self.assertEqual(dependencies.framework_root(project), source)
            command = run.call_args.args[0]
            self.assertEqual(command,
                             ["cmake", "-S", str(project / "cmake/dependencies"),
                              "-B", str(project / "build-dependencies"), "-G", "Ninja",
                              "-DPSXRECOMP_ROOT="])
            self.assertNotIn("PSXRECOMP_ROOT", run.call_args.kwargs["env"])

    def write_inventory_archive(self, project: Path, names: tuple[str, ...]) -> dict[str, str]:
        revision = "1" * 40
        archive = project / "build-dependencies/dependency-archives/psxrecomp" / (revision + ".tar.gz")
        archive.parent.mkdir(parents=True)
        with tarfile.open(archive, "w:gz") as output:
            for name in names:
                entry = tarfile.TarInfo(name)
                entry.size = 6
                output.addfile(entry, io.BytesIO(b"source"))
        return {"name": "psxrecomp", "revision": revision, "path": "",
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}

    def test_inventory_uses_verified_archive_paths_without_fetching(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            pin = self.write_inventory_archive(project, ("source/runtime/source.c",))
            pin["path"] = "lib/recomp-net"
            with mock.patch.object(dependencies, "dependency_pins", return_value=[pin]), \
                 mock.patch.object(dependencies, "fetch_framework") as fetch:
                self.assertEqual(dependencies.framework_inventory(project),
                                 {Path("lib/recomp-net/runtime/source.c")})
            fetch.assert_not_called()

    def test_inventory_rejects_changed_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            pin = self.write_inventory_archive(project, ("source/runtime/source.c",))
            pin["sha256"] = "0" * 64
            with mock.patch.object(dependencies, "dependency_pins", return_value=[pin]):
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    dependencies.framework_inventory(project)

    def test_inventory_rejects_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            pin = self.write_inventory_archive(project, ("source/../../private",))
            with mock.patch.object(dependencies, "dependency_pins", return_value=[pin]):
                with self.assertRaisesRegex(ValueError, "Unsafe dependency archive path"):
                    dependencies.framework_inventory(project)


if __name__ == "__main__":
    unittest.main()
