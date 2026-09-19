#!/usr/bin/env python3
"""Run the asset-free test suite, treating unavailable coverage as a failure."""
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        print(
            "Test coverage incomplete: skipped tests are not a pass. "
            "Install the dependencies listed in README.md and provide "
            "an OpenGL 3.3 context (or use Xvfb with Mesa).",
            file=sys.stderr,
        )
        return 1
    if result.testsRun == 0:
        print("No tests discovered; check the tests directory.", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
