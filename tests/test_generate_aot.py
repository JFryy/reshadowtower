import base64
import io
import json
import os
from pathlib import Path
import struct
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
            (root / "game.toml").write_text('[game]\ndisc = "disc/game.cue"\n')
            runtime = root / "runtime.json"
            runtime.write_text(json.dumps([capture(0x80002000)]))
            framework = root / "framework"
            emitter = root / "psxrecomp-game"

            def complete(command, **kwargs):
                if command[1].endswith("compile_overlays.py"):
                    kwargs["stdout"].write("PSX_SHARD_RESULT ok=1 failed=0 skipped=0\n")
                return SimpleNamespace(returncode=0)

            with mock.patch.object(generate_aot, "ROOT", root), \
                 mock.patch.object(generate_aot, "framework_root", return_value=framework), \
                 mock.patch.object(generate_aot, "find_recompiler", return_value=emitter), \
                 mock.patch.object(generate_aot, "area_module_records",
                                   return_value=[capture(0x801EB000)]) as areas, \
                 mock.patch.object(generate_aot.subprocess, "run", side_effect=complete) as run, \
                 mock.patch.object(sys, "stdout", new_callable=io.StringIO):
                self.assertEqual(generate_aot.run(SimpleNamespace(
                    out_dir=output, jobs=1, runtime_captures=runtime)), 0)
            self.assertEqual(areas.call_args.args, (framework, root / "disc/game.cue"))
            compiled = json.loads((output / "filtered-captures.json").read_text())
            self.assertEqual([c["load_addr"] for c in compiled], ["0x801EB000", "0x80002000"])
            self.assertEqual(run.call_args_list[0].args[0], [
                "cmake", f"-DPSXRECOMP_ROOT={framework}",
                "-P", str(root / "cmake/generate_codegen_hash.cmake"),
            ])
            self.assertTrue(run.call_args_list[0].kwargs["check"])
            self.assertTrue(run.call_args_list[1].args[0][1].endswith("extract_generic.py"))
            self.assertTrue(run.call_args_list[2].args[0][1].endswith("compile_overlays.py"))


def capture(load_addr):
    return {"load_addr": f"0x{load_addr:08X}",
            "bytes_b64": base64.b64encode(bytes(16)).decode()}


class AreaCodeBlockTests(unittest.TestCase):
    def test_blocks_run_from_code_sector_to_next_data_sector(self):
        sector = generate_aot.SECTOR
        table = struct.pack("<4I", 0x00010009, (3 << 16) | 1, (6 << 16) | 4, 0)
        archive = bytearray(9 * sector)
        archive[:len(table)] = table
        for index in range(9):
            archive[index * sector] = archive[index * sector] or index
        blocks = generate_aot.area_code_blocks(bytes(archive))
        self.assertEqual([len(b) // sector for b in blocks], [1, 3])
        self.assertEqual(blocks[0], bytes(archive[3 * sector:4 * sector]))
        self.assertEqual(blocks[1], bytes(archive[6 * sector:9 * sector]))

    def test_out_of_range_entries_are_ignored(self):
        table = struct.pack("<3I", 1, (40 << 16) | 1, 0)
        archive = table + bytes(generate_aot.SECTOR * 2 - len(table))
        self.assertEqual(generate_aot.area_code_blocks(archive), [])


if __name__ == "__main__":
    unittest.main()
