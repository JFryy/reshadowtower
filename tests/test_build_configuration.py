"""Asset-free regression tests for mod catalog configuration, not a full build."""

from pathlib import Path
import re
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_CMAKE = REPO_ROOT / "CMakeLists.txt"
RUNTIME_CMAKE = REPO_ROOT / "psxrecomp" / "runtime" / "runtime.cmake"


def _extract_function(source: str, signature: str) -> str:
    start = source.find(signature)
    if start == -1:
        raise AssertionError(f"extraction anchor changed: missing {signature!r}")
    end = source.find("endfunction()", start)
    if end == -1:
        raise AssertionError(
            f"extraction anchor changed: no endfunction() after {signature!r}"
        )
    return source[start : end + len("endfunction()")]


def _extract_runtime_call(source: str) -> str:
    match = re.search(r"(?m)^psxrecomp_add_game_runtime\s*\(", source)
    if not match:
        raise AssertionError(
            "extraction anchor changed: root psxrecomp_add_game_runtime(...) call missing"
        )
    depth = 0
    for index in range(match.start(), len(source)):
        if source[index] == "(":
            depth += 1
        elif source[index] == ")":
            depth -= 1
            if depth == 0:
                return source[match.start() : index + 1]
    raise AssertionError(
        "extraction anchor changed: unterminated root psxrecomp_add_game_runtime(...) call"
    )


class BuildConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root_source = ROOT_CMAKE.read_text(encoding="utf-8-sig")
        runtime_source = RUNTIME_CMAKE.read_text(encoding="utf-8-sig")
        cls.runtime_call = _extract_runtime_call(root_source)
        cls.stage_function = _extract_function(
            runtime_source, "function(_psxrt_stage_mod_catalog target preloaded_dir)"
        )

    def _configure(self, runtime_call: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            source_dir = Path(directory) / "source"
            build_dir = Path(directory) / "build"
            source_dir.mkdir()
            nonexistent_framework = Path(directory) / "nonexistent-framework"
            harness = f"""cmake_minimum_required(VERSION 3.20)
project(ModCatalogConfigurationRegression LANGUAGES NONE)
set(PSXRECOMP_ROOT \"{nonexistent_framework.as_posix()}\")
{self.stage_function}

function(psxrecomp_add_game_runtime target)
    cmake_parse_arguments(PARSED \"\" \"PRELOADED_MODS_DIR\" \"\" ${{ARGN}})
    add_custom_target(${{target}})
    _psxrt_stage_mod_catalog(${{target}} \"${{PARSED_PRELOADED_MODS_DIR}}\")
endfunction()

{runtime_call}
"""
            (source_dir / "CMakeLists.txt").write_text(harness, encoding="utf-8")
            return subprocess.run(
                ["cmake", "-S", str(source_dir), "-B", str(build_dir)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

    def test_root_runtime_declaration_configures_without_mod_assets(self):
        result = self._configure(self.runtime_call)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_missing_preloaded_mods_directory_is_rejected(self):
        changed_call, replacements = re.subn(
            r"(?m)^(\s*PRELOADED_MODS_DIR\s+)(?:\"[^\"]*\"|\S+)",
            r'\1"${CMAKE_CURRENT_SOURCE_DIR}/definitely-missing-mods"',
            self.runtime_call,
        )
        self.assertEqual(
            replacements,
            1,
            "extraction anchor changed: expected one PRELOADED_MODS_DIR argument",
        )
        result = self._configure(changed_call)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("is not a directory", result.stdout)


if __name__ == "__main__":
    unittest.main()
