import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "generate_aot", ROOT / "tools" / "generate_aot.py"
)
generate_aot = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(generate_aot)


class RecompilerDiscoveryTests(unittest.TestCase):
    def test_windows_uses_exe_and_linux_uses_unsuffixed_emitter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            emitters = root / "build-recompiler"
            emitters.mkdir()
            linux = emitters / "psxrecomp-game"
            windows = emitters / "psxrecomp-game.exe"
            linux.touch()
            windows.touch()

            self.assertEqual(generate_aot.find_recompiler(root, windows=False), linux)
            self.assertEqual(generate_aot.find_recompiler(root, windows=True), windows)

    def test_packaged_emitters_are_found_on_both_platforms(self):
        for windows in (False, True):
            with self.subTest(windows=windows), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                emitter = root / "psxrecomp/recompiler/build" / (
                    "psxrecomp-game.exe" if windows else "psxrecomp-game"
                )
                emitter.parent.mkdir(parents=True)
                emitter.touch()
                self.assertEqual(generate_aot.find_recompiler(root, windows=windows), emitter)

    def test_missing_windows_emitter_has_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            expected = Path(directory) / "build-recompiler" / "psxrecomp-game.exe"
            with self.assertRaisesRegex(FileNotFoundError, "missing emitter") as raised:
                generate_aot.find_recompiler(Path(directory), windows=True)
            self.assertIn(str(expected), str(raised.exception))


class BuildScriptTests(unittest.TestCase):
    def test_player_build_disables_debug_tools_on_linux_and_mingw(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("scripts", "disc", "psxrecomp/runtime", "bin"):
                (root / name).mkdir(parents=True)
            (root / "scripts/build.sh").write_bytes((ROOT / "scripts/build.sh").read_bytes())
            (root / "disc/Shadow Tower (USA).cue").touch()
            (root / "psxrecomp/runtime/runtime.cmake").touch()
            # Stub generation and compilation, not the player build script.
            for name in (
                "bin/python3", "psxrecomp/tools/ci/build_emitters.sh",
                "psxrecomp/tools/regen_bios.sh",
            ):
                stub = root / name
                stub.parent.mkdir(parents=True, exist_ok=True)
                stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
                stub.chmod(0o755)
            cmake = root / "bin/cmake"
            cmake.write_text(
                '#!/usr/bin/env bash\nprintf "%s\\n" "$@" >> "$CAPTURE"\n',
                encoding="utf-8",
            )
            cmake.chmod(0o755)
            capture = root / "arguments"
            env = os.environ.copy()
            env["PATH"] = f"{root / 'bin'}:{env['PATH']}"
            env["CAPTURE"] = str(capture)
            for msystem in ("", "MINGW64"):
                with self.subTest(msystem=msystem):
                    env["MSYSTEM"] = msystem
                    capture.unlink(missing_ok=True)
                    subprocess.run(["bash", str(root / "scripts/build.sh")], check=True, env=env)
                    arguments = capture.read_text(encoding="utf-8").splitlines()
                    self.assertIn("-DCMAKE_BUILD_TYPE=Release", arguments)
                    self.assertIn("-DPSX_DEBUG_TOOLS=OFF", arguments)
                    self.assertNotIn("-DPSX_DEBUG_TOOLS=ON", arguments)
                    self.assertIn("--build", arguments)


class RunScriptTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name in ("scripts", "build-release", "bin"):
            (self.root / name).mkdir()
        (self.root / "scripts/run.sh").write_bytes((ROOT / "scripts/run.sh").read_bytes())
        uname = self.root / "bin/uname"
        uname.write_text("#!/usr/bin/env bash\necho MINGW64_NT-10.0\n", encoding="utf-8")
        uname.chmod(0o755)
        self.env = os.environ.copy()
        self.env["PATH"] = f"{self.root / 'bin'}:{self.env['PATH']}"

    def test_mingw_exe_receives_fixed_and_forwarded_arguments(self):
        capture = self.root / "arguments"
        runtime = self.root / "build-release/Shadow_Tower_Recompiled.exe"
        runtime.write_text(
            '#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$CAPTURE"\n',
            encoding="utf-8",
        )
        runtime.chmod(0o755)
        self.env["CAPTURE"] = str(capture)
        subprocess.run(
            ["bash", str(self.root / "scripts/run.sh"), "--flag", "two words"],
            check=True, env=self.env,
        )
        self.assertEqual(capture.read_text(encoding="utf-8").splitlines(), [
            "--game", str(self.root / "game.toml"),
            "--disc", str(self.root / "disc/Shadow Tower (USA).cue"),
            "--no-launcher", "--flag", "two words",
        ])

    def test_missing_mingw_exe_fails_without_launching(self):
        completed = subprocess.run(
            ["bash", str(self.root / "scripts/run.sh")],
            text=True, capture_output=True, env=self.env,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("Shadow_Tower_Recompiled.exe", completed.stderr)


if __name__ == "__main__":
    unittest.main()
