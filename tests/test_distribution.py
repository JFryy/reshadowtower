import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_bundled_sdl
import package_release


class DistributionTests(unittest.TestCase):
    def test_changed_sources_or_binaries_cannot_be_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build = root / "host"
            emitters = root / "emitters"
            build.mkdir()
            emitters.mkdir()
            paths = {"psxrecomp-game": emitters / "psxrecomp-game",
                     "psxrecomp-bios": emitters / "psxrecomp-bios"}
            paths["shadowtower-launcher"] = build / "shadowtower-launcher"
            for path in paths.values():
                path.write_bytes(b"built binary")
            from bundled_toolchain import PINS
            metadata = {"source_fingerprint": "original", "platform": "linux-x64",
                        "toolchain_sha256": PINS["linux-x64"][1],
                        "binaries": {name: package_release.file_hash(path) for name, path in paths.items()}}
            sdl = root / "bundled-sdl"
            sdl.mkdir()
            (sdl / "libSDL3.a").write_bytes(b"static SDL")
            metadata["sdl"] = {"archive_sha256": build_bundled_sdl.SHA256,
                               "prefix": str(sdl.resolve()), "files": build_bundled_sdl.hashes(sdl)}
            (build / "release-build.json").write_text(json.dumps(metadata))
            args = SimpleNamespace(build=build, emitters=emitters, platform="linux-x64")
            with mock.patch.object(package_release, "source_fingerprint", return_value="changed"):
                with self.assertRaisesRegex(ValueError, "Sources changed"):
                    package_release.validate_build(args)
            with mock.patch.object(package_release, "source_fingerprint", return_value="original"):
                package_release.validate_build(args)
                paths["psxrecomp-game"].write_bytes(b"different binary")
                with self.assertRaisesRegex(ValueError, "Binary differs"):
                    package_release.validate_build(args)
                paths["psxrecomp-game"].write_bytes(b"built binary")
                paths["shadowtower-launcher"].write_bytes(b"tampered launcher")
                with self.assertRaisesRegex(ValueError, "Binary differs"):
                    package_release.validate_build(args)
                paths["shadowtower-launcher"].write_bytes(b"built binary")
                (sdl / "libSDL3.a").write_bytes(b"tampered SDL")
                with self.assertRaisesRegex(ValueError, "Bundled SDL files differ"):
                    package_release.validate_build(args)

    def test_source_export_keeps_vendor_headers_but_excludes_game_code(self):
        root = package_release.ROOT
        paths = [root / "psxrecomp/generated/private_game.c",
                 root / "psxrecomp/recompiler/lib/rabbitizer/include/generated/InstrId_enum.h",
                 root / "psxrecomp/recompiler/tests/test.cpp",
                 root / "psxrecomp/bios/openbios.bin",
                 root / "psxrecomp/bios/SCPH1001.BIN"]
        with mock.patch.object(package_release, "PROJECT_FILES", ()), \
             mock.patch.object(package_release, "tracked_files", side_effect=lambda repo: paths if repo.name == "psxrecomp" else []):
            exported = list(package_release.source_files())
        self.assertEqual([path for path in exported if "launcher" not in path.parts], paths[1:4])
        self.assertTrue(any(path.name == "CMakeLists.txt" and "launcher" in path.parts for path in exported))
        self.assertFalse(any("recomp-ui" in path.parts for path in exported))


if __name__ == "__main__":
    unittest.main()
