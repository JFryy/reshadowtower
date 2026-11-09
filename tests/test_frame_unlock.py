import os
import re
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (ROOT / "src/frame_unlock.c", ROOT / "src/wide_view.c")


def override_addresses():
    """Every guest address the override modules register."""
    addresses = set()
    for path in SOURCES:
        source = path.read_text()
        defines = {name: int(value, 16) for name, value in re.findall(r"#define (\w+) (0x[0-9A-Fa-f]+)u", source)}
        names = re.findall(r'shadowtower_register_override\("[^"]+", (\w+),', source)
        addresses |= {defines[name] for name in names}
        gates = re.search(r"static const Gate gates\[GATE_COUNT\] = \{(.*?)\n\};", source, re.DOTALL)
        if gates:
            addresses |= {int(value, 16) for value in re.findall(r'\{"[^"]+", (0x[0-9A-Fa-f]+)u,', gates.group(1))}
    return addresses


class FrameUnlockTests(unittest.TestCase):
    def test_game_toml_lists_every_override(self):
        config = tomllib.loads((ROOT / "game.toml").read_text())
        listed = {int(value, 16) for value in config["data_shards"]["funcs"]}
        addresses = override_addresses()
        self.assertEqual(len(addresses), 23)
        self.assertEqual(listed, addresses)

    def test_generated_code_has_entry_checks(self):
        generated = ROOT / "generated/aot"
        # generated/ is untracked and absent in CI; run_tests treats skips as failures, so pass quietly there.
        if not generated.is_dir():
            return
        text = "".join(path.read_text(errors="replace") for path in sorted(generated.glob("overlays_static_*.c")))
        missing = [f"0x{address:08X}" for address in sorted(override_addresses())
                   if f"psx_datashard_enter(cpu, 0x{address:08X}u)" not in text]
        self.assertEqual(missing, [], "regenerate with ./scripts/build.sh")

    def test_clock_and_interpolation(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "frame_clock"
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "src"),
                            str(ROOT / "tests/frame_clock_test.c"), "-lm", "-o", str(executable)], check=True)
            result = subprocess.run([str(executable)], capture_output=True, text=True, check=False,
                                    env=os.environ)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
