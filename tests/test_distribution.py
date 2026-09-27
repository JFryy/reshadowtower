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
            paths = {"Shadow_Tower_Recompiled": build / "Shadow_Tower_Recompiled",
                     "psxrecomp-game": emitters / "psxrecomp-game",
                     "psxrecomp-bios": emitters / "psxrecomp-bios"}
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
                               "prefix": str(sdl), "files": build_bundled_sdl.hashes(sdl)}
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
        self.assertEqual(exported, paths[1:4])

    def test_setup_source_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "setup-sources.txt"
            host = str(root / "setup/psxrecomp_codegen_host.c")
            for extra in ("src/modern_controls.c", ""):
                manifest.write_text(host + "\n" + extra + "\n")
                package_release.validate_sources(manifest, root)
            for extra, message in (("generated/aot/overlays_static.c", "generated code"),
                                   ("psxrecomp/generated/SCPH1001_full.c", "generated code"),
                                   ("psxrecomp/host/psxrecomp_codegen_host.c", "unrestricted")):
                manifest.write_text(host + "\n" + extra + "\n")
                with self.assertRaisesRegex(ValueError, message):
                    package_release.validate_sources(manifest, root)
            manifest.write_text("src/modern_controls.c\n")
            with self.assertRaisesRegex(ValueError, "first-run"):
                package_release.validate_sources(manifest, root)
            manifest.unlink()
            with self.assertRaisesRegex(ValueError, "Missing"):
                package_release.validate_sources(manifest, root)


if __name__ == "__main__":
    unittest.main()
