import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import launcher_backend as backend


class LauncherBackendTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="shadow tower ")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "tools").mkdir()
        (self.root / "tools/release_cli.py").touch()
        (self.root / "game.toml").touch()
        self.disc = self.root / "Shadow Tower (USA).cue"
        self.disc.touch()

    def test_setup_uses_offline_cli_and_separate_arguments(self):
        with mock.patch.object(backend.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run, \
             mock.patch.object(sys, "stdout", new_callable=io.StringIO):
            backend.setup(self.root, self.disc)
        calls = run.call_args_list
        self.assertEqual([call.args[0][2] for call in calls], ["verify-disc", "generate", "rebuild"])
        self.assertIn(str(self.disc), calls[1].args[0])
        self.assertIn("--no-toolchain-download", calls[1].args[0])
        self.assertIn("--force-prepare", calls[1].args[0])
        self.assertIn(str(self.root / "build-release"), calls[2].args[0])
        for call in calls:
            self.assertEqual(call.kwargs["cwd"], self.root)
            self.assertNotIn("shell", call.kwargs)

    def test_verification_failure_does_not_generate_or_build(self):
        with mock.patch.object(backend.subprocess, "run", return_value=SimpleNamespace(returncode=2)) as run, \
             mock.patch.object(sys, "stdout", new_callable=io.StringIO):
            with self.assertRaisesRegex(RuntimeError, "Verifying the disc failed.*launcher-actions.log"):
                backend.setup(self.root, self.disc)
        self.assertEqual(run.call_count, 1)

    def test_missing_disc_does_not_start_setup(self):
        with mock.patch.object(backend.subprocess, "run") as run:
            with self.assertRaises(FileNotFoundError):
                backend.setup(self.root, self.root / "missing.cue")
        run.assert_not_called()

    def test_optional_bios_is_passed_only_to_generation(self):
        bios = self.root / "my BIOS.bin"
        bios.touch()
        with mock.patch.object(backend.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run, \
             mock.patch.object(sys, "stdout", new_callable=io.StringIO):
            backend.setup(self.root, self.disc, bios)
        self.assertIn(str(bios), run.call_args_list[1].args[0])
        self.assertNotIn(str(bios), run.call_args_list[2].args[0])


if __name__ == "__main__":
    unittest.main()
