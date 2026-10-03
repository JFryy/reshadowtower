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
import dependencies


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
            metadata = {"source_fingerprint": "original", "dependency_pins": dependencies.dependency_pins(), "platform": "linux-x64",
                        "toolchain_sha256": PINS["linux-x64"][1],
                        "binaries": {name: package_release.file_hash(path) for name, path in paths.items()}}
            sdl = root / "bundled-sdl"
            sdl.mkdir()
            (sdl / "libSDL3.a").write_bytes(b"static SDL")
            metadata["sdl"] = {"archive_sha256": build_bundled_sdl.SHA256,
                               "prefix": str(sdl.resolve()), "files": build_bundled_sdl.hashes(sdl)}
            imgui = root / "imgui"
            for name in package_release.IMGUI_FILES:
                path = imgui / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"ImGui source")
            (build / "imgui-source-dir.txt").write_text(str(imgui) + "\n")
            metadata["imgui"] = package_release.imgui_hashes(imgui)
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
                (sdl / "libSDL3.a").write_bytes(b"static SDL")
                (imgui / "imgui.cpp").write_bytes(b"tampered ImGui")
                with self.assertRaisesRegex(ValueError, "ImGui sources differ"):
                    package_release.validate_build(args)

    def test_imgui_hashes_require_build_inputs_but_ignore_unused_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            for name in package_release.IMGUI_FILES:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"ImGui source")
            (source / "imgui_demo.cpp").write_bytes(b"unused demo")
            hashes = package_release.imgui_hashes(source)
            self.assertEqual(set(hashes), set(package_release.IMGUI_FILES))
            self.assertIn("LICENSE.txt", hashes)
            (source / "imgui.h").unlink()
            with self.assertRaises(FileNotFoundError):
                package_release.imgui_hashes(source)

    def test_source_export_keeps_vendor_headers_but_excludes_game_code(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(dependencies, "framework_inventory") as inventory:
            framework = Path(directory) / "external-framework"
            names = ("generated/private_game.c", "recompiler/include/generated/InstrId_enum.h",
                         "recompiler/tests/test.cpp", "bios/openbios.bin", "bios/SCPH1001.BIN",
                         "build-output/file.cpp", "CMakeFiles/cache.cpp", "saves/card.mcd",
                         ".git", ".gitmodules", "__pycache__/module.pyc", "CMakeCache.txt",
                     "cmake-build-debug/output.c")
            inventory.return_value = {Path(name) for name in names}
            for name in (*names, ".env", "credentials.txt", "recompiler/private-data.json"):
                path = framework / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"source")
            exported = dict(package_release.source_files(framework))
            self.assertEqual(exported[framework / "recompiler/include/generated/InstrId_enum.h"],
                             Path("psxrecomp/recompiler/include/generated/InstrId_enum.h"))
            self.assertIn(framework / "bios/openbios.bin", exported)
            for name in (".env", "credentials.txt", "recompiler/private-data.json"):
                self.assertNotIn(framework / name, exported)
            for name in ("generated/private_game.c", "bios/SCPH1001.BIN",
                         "build-output/file.cpp", "CMakeFiles/cache.cpp", "saves/card.mcd",
                         ".git", ".gitmodules", "__pycache__/module.pyc", "CMakeCache.txt",
                         "cmake-build-debug/output.c"):
                self.assertNotIn(framework / name, exported)
            self.assertIn((package_release.ROOT / "launcher/artwork.hpp", Path("launcher/artwork.hpp")),
                          exported.items())
            first = package_release.source_fingerprint(framework)
            relocated = Path(directory) / "relocated"
            framework.rename(relocated)
            self.assertEqual(first, package_release.source_fingerprint(relocated))
            (relocated / "recompiler/tests/test.cpp").write_bytes(b"tampered")
            self.assertNotEqual(first, package_release.source_fingerprint(relocated))
            linked_source = relocated / "recompiler/tests/test.cpp"
            with mock.patch.object(Path, "is_symlink", autospec=True,
                                   side_effect=lambda path: path == linked_source):
                with self.assertRaisesRegex(ValueError, "symlink"):
                    list(package_release.framework_sources(relocated))

    def test_dependency_pins_must_match_build(self):
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            (build / "release-build.json").write_text(json.dumps({
                "source_fingerprint": "original", "dependency_pins": []}))
            with mock.patch.object(package_release, "source_fingerprint", return_value="original"):
                with self.assertRaisesRegex(ValueError, "Dependency pins"):
                    package_release.validate_build(SimpleNamespace(build=build))

    def test_launcher_keeps_fixed_cover_and_retro_font(self):
        root = package_release.ROOT
        source = (root / "launcher/main.cpp").read_text()
        self.assertIn('workspacePath / "assets/setup/boxart.tga"', source)
        self.assertIn("AddFontDefault(&fontConfig)", source)
        self.assertNotIn("Choose artwork", source)
        self.assertNotIn("artBrowse", source)
        self.assertIn("assets/setup/boxart.tga", package_release.PROJECT_FILES)

    def test_native_build_explicitly_disables_upstream_ui_without_submodule(self):
        root = package_release.ROOT
        self.assertFalse((root / ".gitmodules").exists())
        cmake = (root / "CMakeLists.txt").read_text()
        disable = cmake.index("set(PSX_RECOMP_UI OFF CACHE BOOL")
        upstream = cmake.index('include("${PSXRECOMP_ROOT}/runtime/runtime.cmake")')
        self.assertLess(disable, upstream)
        self.assertNotIn("cmake/setup.cmake", cmake)
        for path in package_release.PROJECT_FILES:
            self.assertTrue((root / path).is_file(), path)


if __name__ == "__main__":
    unittest.main()
