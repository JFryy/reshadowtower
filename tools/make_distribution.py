#!/usr/bin/env python3
"""Turn an offline package into a Linux AppImage or Windows installer."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from release_common import file_hash

ROOT = Path(__file__).resolve().parents[1]
APPIMAGETOOL_URL = "https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
APPIMAGETOOL_SHA256 = "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
INNO_URL = "https://github.com/jrsoftware/issrc/releases/download/is-7_1_0/innosetup-7.1.0-x64.exe"
INNO_SHA256 = "0362a383ed217d4c4239b5933866dd96d3eb2102737da92f80f6057a4b40df2f"


def verify_tool(path: Path, expected: str) -> None:
    if file_hash(path) != expected:
        raise ValueError(f"Packaging tool SHA-256 mismatch: {path}")


def make_appimage(package: Path, output: Path, tool: Path) -> None:
    verify_tool(tool, APPIMAGETOOL_SHA256)
    tool.chmod(tool.stat().st_mode | 0o100)
    with tempfile.TemporaryDirectory(prefix="reshadow-appimage-") as directory:
        # Reuse the pinned tool's own runtime rather than let appimagetool fetch
        # an unpinned type2-runtime release during packaging.
        offset = int(subprocess.check_output([str(tool), "--appimage-offset"], text=True).strip())
        if not 0 < offset < tool.stat().st_size:
            raise ValueError("Invalid runtime offset in pinned appimagetool.")
        runtime = Path(directory) / "runtime"
        with tool.open("rb") as source:
            runtime.write_bytes(source.read(offset))
        env = os.environ.copy()
        env["ARCH"] = "x86_64"
        subprocess.run([str(tool), "--appimage-extract-and-run", "--no-appstream",
                        "--runtime-file", str(runtime), "--mksquashfs-opt", "-processors",
                        "--mksquashfs-opt", "4", str(package), str(output)], check=True, env=env)


def make_installer(package: Path, output: Path, tool: Path, version: str) -> None:
    verify_tool(tool, INNO_SHA256)
    with tempfile.TemporaryDirectory(prefix="reshadow-inno-") as directory:
        compiler = Path(directory) / "compiler"
        subprocess.run([str(tool), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                        "/CURRENTUSER", "/NOICONS", f"/DIR={compiler}"], check=True)
        subprocess.run([str(compiler / "ISCC.exe"), f"/DPackageDir={package}",
                        f"/DAppVersion={version}", f"/DOutputDir={output.parent}",
                        str(ROOT / "packaging/windows/ReShadowTower.iss")], check=True)
    if not output.is_file():
        raise ValueError(f"Installer compiler did not produce {output.name}.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--tool", type=Path, required=True, help="Pinned appimagetool AppImage or Inno Setup installer")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        package = args.package.resolve()
        metadata = json.loads((package / "release.json").read_text(encoding="utf-8"))
        version = metadata["version"]
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ValueError("VERSION must be MAJOR.MINOR.PATCH.")
        platform = metadata["platform"]
        if platform == "linux-x64" and sys.platform.startswith("linux"):
            name = f"ReShadowTower-{version}-x86_64.AppImage"
        elif platform == "windows-x64" and os.name == "nt":
            name = f"ReShadowTower-{version}-windows-x64-setup.exe"
        else:
            raise ValueError("Build the distribution on its native operating system.")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        output = args.output_dir.resolve() / name
        if output.exists():
            raise ValueError(f"Refusing to overwrite {output}")
        if platform == "linux-x64":
            make_appimage(package, output, args.tool.resolve())
        else:
            make_installer(package, output, args.tool.resolve(), version)
        digest = file_hash(output)
        output.with_name(output.name + ".sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")
        print(output)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"Distribution build failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
