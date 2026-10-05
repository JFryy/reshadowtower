"""Safety checks for locally supplied toolchain archives."""

import hashlib
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from bundled_toolchain import extract_verified  # noqa: E402


class BundledToolchainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "bundle.zip"
        self.destination = self.root / "installed"

    def make_archive(self, entries):
        with zipfile.ZipFile(self.archive, "w") as archive:
            for name, payload, mode in entries:
                info = zipfile.ZipInfo(name)
                # Keep malformed names intact instead of letting ZipInfo normalize them.
                info.filename = name
                info.create_system = 3
                info.external_attr = mode << 16
                archive.writestr(info, payload)
        return hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def test_checksum_failure_makes_no_writes(self):
        self.make_archive([("bin/tool", b"ok", stat.S_IFREG | 0o755)])
        with self.assertRaisesRegex(ValueError, "SHA256"):
            extract_verified(self.archive, self.destination, "0" * 64)
        self.assertEqual(list(self.root.iterdir()), [self.archive])

    def test_traversal_and_absolute_paths(self):
        for name in ("../outside", "/absolute", "C:/drive", "folder\\backslash", "nul\x00suffix"):
            with self.subTest(name=name):
                digest = self.make_archive([(name, b"bad", stat.S_IFREG | 0o644)])
                with zipfile.ZipFile(self.archive) as archive:
                    self.assertEqual(archive.infolist()[0].orig_filename, name)
                with self.assertRaises(ValueError):
                    extract_verified(self.archive, self.destination, digest)
                self.assertFalse(self.destination.exists())

    def test_symlink_escape(self):
        digest = self.make_archive([("bin/escape", b"../../outside", stat.S_IFLNK | 0o777)])
        with self.assertRaisesRegex(ValueError, "Escaping"):
            extract_verified(self.archive, self.destination, digest)
        self.assertFalse(self.destination.exists())

    def test_existing_destination_preserved(self):
        digest = self.make_archive([("tool", b"new", stat.S_IFREG | 0o755)])
        self.destination.mkdir()
        (self.destination / "tool").write_bytes(b"old")
        with self.assertRaises(FileExistsError):
            extract_verified(self.archive, self.destination, digest)
        self.assertEqual((self.destination / "tool").read_bytes(), b"old")

    def test_valid_archive(self):
        entries = [("bin/tool", b"hello", stat.S_IFREG | 0o755)]
        if sys.platform != "win32":
            entries.append(("bin/alias", b"tool", stat.S_IFLNK | 0o777))
        digest = self.make_archive(entries)
        extract_verified(self.archive, self.destination, digest)
        self.assertEqual((self.destination / "bin/tool").read_bytes(), b"hello")
        if sys.platform != "win32":
            self.assertEqual((self.destination / "bin/alias").read_bytes(), b"hello")
            self.assertTrue((self.destination / "bin/alias").is_symlink())
            self.assertTrue((self.destination / "bin/tool").stat().st_mode & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
