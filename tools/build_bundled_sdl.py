#!/usr/bin/env python3
"""Build the pinned SDL source with the upstream XInput2 fix and bundled tools."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
URL = "https://github.com/libsdl-org/SDL/releases/download/release-3.4.10/SDL3-3.4.10.tar.gz"
SHA256 = "12b34280415ec8418c864408b93d008a20a6530687ee613d60bfbd20411f2785"
PATCH = ROOT / "packaging/linux/sdl-xinput2.patch"
DEPS = ROOT / "packaging/linux/sdl-build-deps.json"


def download_inputs(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    inputs = [(URL, SHA256, directory / 'SDL3-3.4.10.tar.gz')]
    deps = directory / 'sdl-build-deps'
    deps.mkdir(exist_ok=True)
    inputs.extend((entry['url'], entry['sha256'], deps / Path(entry['url']).name)
                  for entry in json.loads(DEPS.read_text()).values())
    for url, digest, path in inputs:
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            continue
        if not url.startswith('https://'):
            raise ValueError(f'Non-HTTPS dependency: {url}')
        temporary = path.with_suffix(path.suffix + '.tmp')
        urllib.request.urlretrieve(url, temporary)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
            temporary.unlink()
            raise ValueError(f'SHA256 mismatch: {url}')
        temporary.replace(path)


def extract_deps(directory: Path, sdk: Path) -> None:
    entries = json.loads(DEPS.read_text())
    archives = [(directory / Path(entry['url']).name, entry['sha256'])
                for entry in entries.values()]
    for path, digest in archives:
        if not path.is_file():
            raise FileNotFoundError(f'Missing pinned SDL build input {path}; run tools/build_bundled_sdl.py --download-inputs {directory.parent}')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f'SDL build input SHA256 mismatch: {path}')
    sdk.mkdir(parents=True)
    for path, _ in archives:
        data = path.read_bytes()
        if not data.startswith(b'!<arch>\n'):
            raise ValueError(f'Invalid Debian archive: {path}')
        pos = 8
        while pos < len(data):
            header = data[pos:pos + 60]
            if len(header) != 60 or header[58:60] != b'`\n':
                raise ValueError(f'Invalid Debian archive header: {path}')
            size = int(header[48:58])
            name = header[:16].decode('ascii').strip().rstrip('/')
            payload = data[pos + 60:pos + 60 + size]
            if len(payload) != size:
                raise ValueError(f'Truncated Debian archive: {path}')
            if name.startswith('data.tar.'):
                with tarfile.open(fileobj=io.BytesIO(payload), mode='r:*') as tar:
                    for member in tar:
                        target = (sdk / member.name).resolve()
                        if not target.is_relative_to(sdk.resolve()):
                            raise ValueError(f'Unsafe Debian archive entry: {member.name}')
                    tar.extractall(sdk, filter='data')
                break
            pos += 60 + size + size % 2
        else:
            raise ValueError(f'Missing Debian data archive: {path}')


def hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Unexpected symlink in static SDL SDK: {path}')
        if path.is_file():
            with path.open('rb') as source:
                result[path.relative_to(root).as_posix()] = hashlib.file_digest(source, 'sha256').hexdigest()
    return result


def extract(archive: Path, destination: Path) -> Path:
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError("SDL archive SHA256 mismatch")
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            parts = Path(member.name).parts
            if (not parts or parts[0] != 'SDL3-3.4.10' or
                    any(part in ('..', '.') for part in parts) or
                    not (member.isfile() or member.isdir())):
                raise ValueError(f"Unsafe SDL archive entry: {member.name}")
        tar.extractall(destination, filter='data')
    return destination / 'SDL3-3.4.10'


def build(archive: Path, output: Path, pack: Path, env: dict[str, str]) -> Path:
    source = extract(archive, output / 'sdl-source')
    subprocess.run(['git', '-C', str(source), 'apply', '--check', str(PATCH)], check=True)
    subprocess.run(['git', '-C', str(source), 'apply', str(PATCH)], check=True)
    sdk = output / 'sdl-build-sdk'
    extract_deps(archive.parent / 'sdl-build-deps', sdk)
    env = {**env, 'PKG_CONFIG_LIBDIR': ':'.join(str(sdk / p) for p in
           ('usr/lib/x86_64-linux-gnu/pkgconfig', 'usr/share/pkgconfig')),
           'PKG_CONFIG_SYSROOT_DIR': str(sdk), 'PKG_CONFIG_PATH': ''}
    prefix = output / 'bundled-sdl'
    cmake = str(pack / 'bin/cmake')
    options = [f'-DCMAKE_C_COMPILER={pack / "bin/clang"}', f'-DCMAKE_CXX_COMPILER={pack / "bin/clang++"}',
               f'-DCMAKE_MAKE_PROGRAM={pack / "bin/ninja"}', f'-DCMAKE_SYSROOT={pack / "sysroot"}',
               f'-DCMAKE_INSTALL_PREFIX={prefix}', f'-DCMAKE_FIND_ROOT_PATH={sdk};{pack / "sysroot"}',
               f'-DCMAKE_REQUIRED_INCLUDES={sdk / "usr/include"}',
               '-DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY', '-DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY',
               '-DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ONLY', '-DCMAKE_BUILD_TYPE=Release', '-DSDL_SHARED=OFF',
               '-DSDL_STATIC=ON', '-DSDL_TEST=OFF', '-DSDL_TESTS=OFF', '-DSDL_EXAMPLES=OFF',
               '-DSDL_WAYLAND=OFF', '-DSDL_X11=ON', '-DSDL_OPENGL=ON', '-DSDL_ALSA=ON',
               '-DSDL_PULSEAUDIO=ON', '-DSDL_PIPEWIRE=OFF', '-DSDL_LIBUDEV=ON']
    subprocess.run([cmake, '-S', str(source), '-B', str(output / 'sdl-build'), '-G', 'Ninja', *options], env=env, check=True)
    cache = (output / 'sdl-build/CMakeCache.txt').read_text()
    for feature in ('SDL_X11', 'SDL_X11_XINPUT', 'SDL_OPENGL', 'SDL_ALSA', 'SDL_PULSEAUDIO', 'SDL_LIBUDEV'):
        if f'{feature}:BOOL=ON' not in cache:
            raise ValueError(f'SDL required feature not enabled: {feature}')
    config = (output / 'sdl-build/include-config-release/build_config/SDL_build_config.h').read_text()
    for feature in ('SDL_VIDEO_DRIVER_X11_XINPUT2', 'SDL_VIDEO_OPENGL', 'SDL_VIDEO_OPENGL_GLX', 'HAVE_LIBUDEV_H',
                    'SDL_AUDIO_DRIVER_ALSA', 'SDL_AUDIO_DRIVER_PULSEAUDIO'):
        if f'#define {feature} 1' not in config:
            raise ValueError(f'SDL required feature not compiled: {feature}')
    subprocess.run([cmake, '--build', str(output / 'sdl-build'), '--parallel', '4'], env=env, check=True)
    subprocess.run([cmake, '--install', str(output / 'sdl-build')], env=env, check=True)
    shutil.copy2(source / 'LICENSE.txt', prefix / 'LICENSE.txt')
    shutil.copy2(PATCH, prefix / 'sdl-xinput2.patch')
    return prefix


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download-inputs', type=Path, required=True)
    try:
        download_inputs(parser.parse_args().download_inputs)
    except (OSError, ValueError) as error:
        parser.exit(1, f'SDL build input download failed: {error}\n')
