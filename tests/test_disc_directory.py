"""Verify that disc placement instructions are visible to Git, but assets are not."""
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DiscDirectoryTests(unittest.TestCase):
    def test_only_disc_readme_is_trackable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            (root / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
            disc = root / "disc"
            disc.mkdir()
            (disc / "README.md").write_bytes((ROOT / "disc/README.md").read_bytes())
            for name in (
                "Shadow Tower (USA).bin", "Shadow Tower (USA).cue", "SLUS_008.63",
                "dump.iso", "dump.chd", "notes.txt", "nested/README.md",
            ):
                path = disc / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            result = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard", "--", "disc/"],
                cwd=root, text=True, capture_output=True, check=True,
            )
            self.assertEqual(result.stdout.splitlines(), ["disc/README.md"])


if __name__ == "__main__":
    unittest.main()
