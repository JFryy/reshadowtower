import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import generate_aot
from generate_aot import find_recompiler


class RecompilerDiscoveryTests(unittest.TestCase):
    def test_local_and_packaged_emitters_on_both_platforms(self):
        for directory in ("build-recompiler", "psxrecomp/recompiler/build"):
            for windows in (False, True):
                with self.subTest(directory=directory, windows=windows), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary).resolve()
                    emitter = root / directory / ("psxrecomp-game.exe" if windows else "psxrecomp-game")
                    emitter.parent.mkdir(parents=True)
                    emitter.touch()
                    self.assertEqual(find_recompiler(root, windows=windows), emitter)

    def test_resolved_framework_emitter(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary).resolve()
            root = temporary_root / "project"
            framework = temporary_root / "framework"
            name = "psxrecomp-game.exe" if os.name == "nt" else "psxrecomp-game"
            emitter = framework / "recompiler/build" / name
            emitter.parent.mkdir(parents=True)
            emitter.touch()
            self.assertEqual(find_recompiler(root, framework=framework), emitter)

    def test_missing_emitter_reports_expected_path(self):
        with tempfile.TemporaryDirectory() as directory:
            expected = Path(directory).resolve() / "build-recompiler/psxrecomp-game.exe"
            with self.assertRaisesRegex(FileNotFoundError, "missing emitter") as raised:
                find_recompiler(Path(directory).resolve(), windows=True)
            self.assertIn(str(expected), str(raised.exception))


class CodegenHashOrderTests(unittest.TestCase):
    def test_hash_is_generated_before_extraction_and_aot_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "aot"
            output.mkdir()
            (output / "disc-captures.json").write_text("[]")
            framework = root / "framework"
            emitter = root / "psxrecomp-game"

            def complete(command, **kwargs):
                if command[1].endswith("compile_overlays.py"):
                    kwargs["stdout"].write("PSX_SHARD_RESULT ok=1 failed=0 skipped=0\n")
                return SimpleNamespace(returncode=0)

            with mock.patch.object(generate_aot, "ROOT", root), \
                 mock.patch.object(generate_aot, "framework_root", return_value=framework), \
                 mock.patch.object(generate_aot, "find_recompiler", return_value=emitter), \
                 mock.patch.object(generate_aot.subprocess, "run", side_effect=complete) as run, \
                 mock.patch.object(sys, "stdout", new_callable=io.StringIO):
                self.assertEqual(generate_aot.run(SimpleNamespace(out_dir=output, jobs=1)), 0)
            self.assertEqual(run.call_args_list[0].args[0], [
                "cmake", f"-DPSXRECOMP_ROOT={framework}",
                "-P", str(root / "cmake/generate_codegen_hash.cmake"),
            ])
            self.assertTrue(run.call_args_list[0].kwargs["check"])
            self.assertTrue(run.call_args_list[1].args[0][1].endswith("extract_generic.py"))
            self.assertTrue(run.call_args_list[2].args[0][1].endswith("compile_overlays.py"))


if __name__ == "__main__":
    unittest.main()
