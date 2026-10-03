import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT / "tools"))
import launch_release as launcher
import release_cli as cli


class ReleaseLauncherTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_new_release_preserves_existing_saves_and_workspace(self):
        root = self.root
        payload = root / "payload"
        payload.mkdir()
        (payload / "game.toml").write_text('[runtime]\nmemcard_dir = "saves"\n')
        data = root / "data"
        first = launcher.prepare_workspace(payload, data, "a" * 64)
        save = data / "saves/card1.mcd"
        save.write_bytes(b"existing save")
        (first / "settings.toml").write_text("player settings")
        second = launcher.prepare_workspace(payload, data, "b" * 64)
        self.assertNotEqual(first, second)
        self.assertEqual(save.read_bytes(), b"existing save")
        self.assertEqual((first / "settings.toml").read_text(), "player settings")
        self.assertIn((data / "saves").resolve().as_posix(), (second / "game.toml").read_text())
        self.assertEqual(launcher.prepare_workspace(payload, data, "a" * 64), first)
        self.assertIn('memcard_dir = "saves"', (payload / "game.toml").read_text())

    def test_failed_install_does_not_publish_workspace(self):
        root = self.root
        payload = root / "payload"
        payload.mkdir()
        (payload / "game.toml").write_text("invalid config")
        with self.assertRaisesRegex(ValueError, "save-directory"):
            launcher.prepare_workspace(payload, root / "data", "a" * 64)
        self.assertFalse((root / "data/releases" / ("a" * 64)).exists())

    def test_interrupted_or_modified_build_reopens_setup(self):
        workspace = self.root
        self.assertFalse(launcher.built_game_ready(workspace))
        binary = workspace / "build-release" / ("Shadow_Tower_Recompiled.exe" if launcher.os.name == "nt" else "Shadow_Tower_Recompiled")
        binary.parent.mkdir()
        binary.write_bytes(b"complete build")
        self.assertFalse(launcher.built_game_ready(workspace))
        (workspace / ".build-ready").write_text(hashlib.sha256(binary.read_bytes()).hexdigest())
        self.assertTrue(launcher.built_game_ready(workspace))
        binary.write_bytes(b"interrupted rebuild")
        self.assertFalse(launcher.built_game_ready(workspace))

    def test_child_does_not_inherit_appimage_resource_paths(self):
        root = self.root
        payload = root / "payload"
        payload.mkdir()
        config = b'[runtime]\nmemcard_dir = "saves"\n'
        (payload / "game.toml").write_bytes(config)
        (root / "toolchain").mkdir()
        metadata = {"platform": "windows-x64" if launcher.os.name == "nt" else "linux-x64",
                    "files": {"game.toml": hashlib.sha256(config).hexdigest()},
                    "toolchain_sha256": "a" * 64, "toolchain_files": {}}
        (root / "release.json").write_text(json.dumps(metadata))
        inherited = {"APPIMAGE": "/downloads/game.AppImage", "APPDIR": "/tmp/.mount_game",
                     "ARGV0": "game.AppImage", "OWD": "/downloads"}
        with mock.patch.dict(launcher.os.environ, inherited), \
             mock.patch.object(launcher.subprocess, "run") as run:
            workspace, env = launcher.prepare_launch(root, root / "data")
            for key, value in inherited.items():
                self.assertNotIn(key, env)
                self.assertEqual(launcher.os.environ[key], value)
            self.assertEqual(env["SHADOWTOWER_PROJECT_ROOT"], str(workspace))
            for call in run.call_args_list:
                self.assertNotIn("APPIMAGE", call.kwargs["env"])

    def test_session_lock_prevents_concurrent_launches(self):
        data = self.root
        with launcher.session_lock(data):
            with self.assertRaisesRegex(RuntimeError, "already running"):
                with launcher.session_lock(data):
                    self.fail("Second launch acquired the save lock")
        with launcher.session_lock(data):
            pass

    def test_invalid_toolchain_is_not_installed(self):
        root = self.root
        source = root / "toolchain"
        source.mkdir()
        (source / "compiler").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "integrity"):
            launcher.prepare_toolchain(source, root / "data", "a" * 64, {"compiler": "0" * 64})
        self.assertFalse((root / "data/toolchains" / ("a" * 64)).exists())

    def test_unlisted_payload_files_are_rejected(self):
        root = self.root
        (root / "unexpected.py").write_text("not in manifest")
        with self.assertRaisesRegex(ValueError, "unlisted"):
            launcher.verify_payload(root, {})

    @unittest.skipIf(launcher.os.name == "nt", "Windows wrapper shows bootstrap errors")
    def test_bootstrap_failure_uses_native_error_dialog(self):
        with mock.patch.object(launcher, "__file__", str(self.root / "launch_release.py")), \
             mock.patch.object(launcher, "data_directory", return_value=self.root / "data"), \
             mock.patch.object(launcher, "prepare_launch", side_effect=ValueError("integrity check failed")), \
             mock.patch.object(launcher.subprocess, "run") as run, \
             mock.patch.object(sys, "stderr", new_callable=io.StringIO):
            self.assertEqual(launcher.main(), 1)
        self.assertEqual(run.call_args.args[0][:2], [str(self.root / "shadowtower-launcher"), "--error"])
        self.assertIn("integrity check failed", run.call_args.args[0][2])

    def test_bootstrap_always_opens_native_launcher(self):
        env = {"RETCOMM_PYTHON": "/bundled/python"}
        with mock.patch.object(launcher.subprocess, "run") as run:
            launcher.run_launcher(self.root, self.root / "workspace", env, io.StringIO())
        command = run.call_args.args[0]
        self.assertEqual(Path(command[0]).stem, "shadowtower-launcher")
        self.assertIn("--workspace", command)
        self.assertIn(str(self.root / "workspace/tools/launcher_backend.py"), command)
        self.assertNotIn("--launcher", command)
        self.assertEqual(run.call_args.kwargs["env"], env)

    def test_rebuild_disables_downloads_and_cleanup(self):
        args = cli.command_arguments(["rebuild", "--prune-after", "build-intermediates"])
        self.assertIn("--no-toolchain-download", args)
        self.assertNotIn("--prune-after", args)
        self.assertIn("--cmake-extra=-DPSX_SDL3_FETCH=OFF", args)
        self.assertIn("--cmake-extra=-DFETCHCONTENT_FULLY_DISCONNECTED=ON", args)
        self.assertIn(f"--cmake-extra=-DPSXRECOMP_ROOT={cli.ROOT / 'psxrecomp'}", args)
        with self.assertRaises(ValueError):
            cli.command_arguments(["ensure-toolchain", "--download"])

    @unittest.skipIf(launcher.os.name == "nt", "Linux uses the patched SDL SDK")
    def test_linux_rebuild_requires_and_selects_packaged_sdl(self):
        root = self.root
        pack = root / "toolchain"
        (pack / "bin").mkdir(parents=True)
        for name in ("clang", "clang++", "cmake", "ninja"):
            (pack / "bin" / name).touch()
        executable = root / "build-release/Shadow_Tower_Recompiled"
        executable.parent.mkdir()
        executable.write_bytes(b"compiled game")
        with mock.patch.object(cli, "ROOT", root), \
             mock.patch.object(sys, "argv", ["release_cli.py", "rebuild"]), \
             mock.patch.dict(cli.os.environ, {"SHADOWTOWER_BUNDLED_TOOLCHAIN": str(pack)}), \
             mock.patch.object(cli.subprocess, "run", return_value=types.SimpleNamespace(returncode=0)) as run, \
             mock.patch.object(sys, "stderr", new_callable=io.StringIO) as error:
            self.assertEqual(cli.main(), 1)
            self.assertIn("Reinstall the complete release", error.getvalue())
            run.assert_not_called()
            sdk = root / "bundled-sdl/lib/cmake/SDL3"
            sdk.mkdir(parents=True)
            (sdk / "SDL3Config.cmake").touch()
            self.assertEqual(cli.main(), 0)
            self.assertIn(f"--cmake-extra=-DSDL3_DIR={sdk}", run.call_args.args[0])
            self.assertIn("--no-toolchain-download", run.call_args.args[0])
            self.assertTrue(launcher.built_game_ready(root))


if __name__ == "__main__":
    unittest.main()
