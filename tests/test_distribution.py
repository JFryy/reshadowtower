import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_bundled_sdl
import make_distribution
import package_release


class DistributionTests(unittest.TestCase):
    def test_unverified_packager_is_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            tool = Path(directory) / "tool"
            tool.write_bytes(b"wrong download")
            with mock.patch.object(subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    make_distribution.make_appimage(Path(directory), Path(directory) / "output", tool)
                run.assert_not_called()

    def test_appimage_uses_verified_embedded_runtime_without_downloading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tool = root / "tool"
            tool.write_bytes(b"runtime!filesystem")
            digest = hashlib.sha256(tool.read_bytes()).hexdigest()

            def check_command(command, **kwargs):
                runtime = Path(command[command.index("--runtime-file") + 1])
                self.assertEqual(runtime.read_bytes(), b"runtime!")
                self.assertEqual(kwargs["env"]["ARCH"], "x86_64")

            with mock.patch.object(make_distribution, "APPIMAGETOOL_SHA256", digest), \
                 mock.patch.object(subprocess, "check_output", return_value="8\n"), \
                 mock.patch.object(subprocess, "run", side_effect=check_command):
                make_distribution.make_appimage(root, root / "output", tool)

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

    def test_setup_media_and_adapter_are_exported(self):
        with mock.patch.object(package_release, "tracked_files", return_value=[]):
            exported = {p.relative_to(package_release.ROOT).as_posix()
                        for p in package_release.source_files()}
        for name in ("assets/setup/music.wav", "assets/setup/boxart.tga",
                     "src/setup_music.cpp", "src/setup_music.h", "tools/prepare_setup_ui.py"):
            self.assertIn(name, exported)
        self.assertNotIn("handoff.md", exported)

    def test_staged_assets_merge_with_source_media_and_are_hashed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            host, emitters = root / "host", root / "emitters"
            (host / "assets/setup").mkdir(parents=True)
            (host / "assets/setup/music.wav").write_bytes(b"music")
            (host / "assets/img").mkdir()
            (host / "assets/img/boxart.tga").write_bytes(b"cover")
            (host / "mods/bundled").mkdir(parents=True)
            (host / "Shadow_Tower_Recompiled.exe").write_bytes(b"host")
            emitters.mkdir()
            for name in ("psxrecomp-game.exe", "psxrecomp-bios.exe"):
                (emitters / name).write_bytes(b"emitter")
            launcher = root / "ReShadowTower.exe"
            launcher.write_bytes(b"launcher")

            def extract(archive, destination, digest):
                (destination / "bin").mkdir(parents=True)
                (destination / "python").mkdir()
                for name in ("cmake", "ninja", "clang", "clang++"):
                    (destination / "bin" / (name + ".exe")).write_bytes(b"tool")
                (destination / "python/python.exe").write_bytes(b"python")
                (destination / "retcomm-toolchain.json").write_text("{}")

            def sources(destination):
                (destination / "assets/setup").mkdir(parents=True)
                (destination / "assets/setup/music.wav").write_bytes(b"music")
                (destination / "psxrecomp/runtime/include").mkdir(parents=True)

            args = SimpleNamespace(build=host, emitters=emitters, platform="windows-x64",
                                   windows_launcher=launcher, toolchain_archive=root / "archive.zip",
                                   output=root / "package")
            with mock.patch("bundled_toolchain.extract_verified", side_effect=extract), \
                 mock.patch.object(package_release, "copy_sources", side_effect=sources), \
                 mock.patch.object(subprocess, "check_output", return_value="1234abcd"):
                package_release.stage(args)
            metadata = json.loads((args.output / "release.json").read_text())
            for name in ("assets/setup/music.wav", "assets/img/boxart.tga"):
                self.assertEqual(metadata["files"][name],
                                 package_release.file_hash(args.output / "payload" / name))

    def test_installer_never_deletes_user_data(self):
        source = (package_release.ROOT / "packaging/windows/ReShadowTower.iss").read_text()
        self.assertIn("PrivilegesRequired=lowest", source)
        self.assertIn("UsePreviousAppDir=no", source)
        self.assertNotIn("[UninstallDelete]", source)
        self.assertNotIn("[Registry]", source)
        self.assertNotIn("[Run]", source)
        self.assertIn(r"{localappdata}\Programs\ReShadowTower\{#AppVersion}", source)


if __name__ == "__main__":
    unittest.main()
