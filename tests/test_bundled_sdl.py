"""Focused checks for the pinned stock SDL Wayland build."""

import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_bundled_sdl as sdl  # noqa: E402


CACHE_FEATURES = ('SDL_WAYLAND', 'SDL_WAYLAND_LIBDECOR', 'SDL_X11', 'SDL_X11_XINPUT',
                  'SDL_OPENGL', 'SDL_ALSA', 'SDL_PULSEAUDIO', 'SDL_LIBUDEV')
COMPILED_FEATURES = ('SDL_VIDEO_DRIVER_WAYLAND', 'SDL_VIDEO_OPENGL_EGL', 'HAVE_LIBDECOR_H',
                     'SDL_VIDEO_DRIVER_X11', 'SDL_VIDEO_DRIVER_X11_XINPUT2',
                     'SDL_VIDEO_OPENGL', 'SDL_VIDEO_OPENGL_GLX', 'HAVE_LIBUDEV_H',
                     'SDL_AUDIO_DRIVER_ALSA', 'SDL_AUDIO_DRIVER_PULSEAUDIO')


class BundledSDLTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_stock_archive_pin_and_extraction_validation(self):
        self.assertEqual(sdl.URL, 'https://github.com/libsdl-org/SDL/releases/download/release-3.4.16/SDL3-3.4.16.tar.gz')
        self.assertEqual(sdl.SHA256, '7322236cd12090c3eb40b9728be4d49c76f66ad17d04369584d4ecad5cf77c68')
        self.assertEqual(sdl.SDL_DIRECTORY, 'SDL3-3.4.16')
        archive = self.root / 'SDL3-3.4.16.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            payload = b'stock source'
            member = tarfile.TarInfo('SDL3-3.4.16/LICENSE.txt')
            member.size = len(payload)
            tar.addfile(member, io.BytesIO(payload))
        destination = self.root / 'source'
        with mock.patch.object(sdl, 'file_hash', return_value='wrong'):
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                sdl.extract(archive, destination)
        self.assertFalse(destination.exists())
        with mock.patch.object(sdl, 'file_hash', return_value=sdl.SHA256):
            source = sdl.extract(archive, destination)
        self.assertEqual(source, destination / sdl.SDL_DIRECTORY)
        self.assertEqual((source / 'LICENSE.txt').read_bytes(), b'stock source')
        with mock.patch.object(sdl, 'file_hash', return_value=sdl.SHA256):
            with self.assertRaises(FileExistsError):
                sdl.extract(archive, destination)

    def run_build(self, missing=None):
        output = self.root / 'output'
        source = output / 'sdl-source' / sdl.SDL_DIRECTORY
        source.mkdir(parents=True)
        (source / 'LICENSE.txt').write_text('stock')
        sdk = output / 'sdl-build-sdk'
        scanner = sdk / 'usr/bin/wayland-scanner'
        scanner.parent.mkdir(parents=True)
        scanner.touch()
        build_dir = output / 'sdl-build'
        config = build_dir / 'include-config-release/build_config/SDL_build_config.h'

        def configure(command, **kwargs):
            if '-S' in command:
                config.parent.mkdir(parents=True)
                (build_dir / 'CMakeCache.txt').write_text(''.join(f'{name}:BOOL=ON\n' for name in CACHE_FEATURES))
                config.write_text(''.join(f'#define {name} 1\n' for name in COMPILED_FEATURES if name != missing))
            elif '--install' in command:
                (output / 'bundled-sdl').mkdir()

        with (mock.patch.object(sdl, 'extract', return_value=source) as extract,
              mock.patch.object(sdl, 'extract_deps') as extract_deps,
              mock.patch.object(sdl.subprocess, 'run', side_effect=configure) as run):
            if missing:
                with self.assertRaisesRegex(ValueError, f'SDL required feature not compiled: {missing}'):
                    sdl.build(self.root / 'SDL3-3.4.16.tar.gz', output, self.root / 'pack', {'KEEP': 'yes'})
            else:
                self.assertEqual(sdl.build(self.root / 'SDL3-3.4.16.tar.gz', output,
                                           self.root / 'pack', {'KEEP': 'yes'}), output / 'bundled-sdl')
            extract.assert_called_once_with(self.root / 'SDL3-3.4.16.tar.gz', output / 'sdl-source')
            extract_deps.assert_called_once_with(self.root / 'sdl-build-deps', sdk)
            return run.call_args_list, scanner, sdk, source

    def test_stock_wayland_configuration_without_patch(self):
        calls, scanner, sdk, source = self.run_build()
        self.assertEqual(len(calls), 3)
        command = calls[0].args[0]
        self.assertEqual(command[:7], [str(self.root / 'pack/bin/cmake'), '-S', str(source),
                                       '-B', str(self.root / 'output/sdl-build'), '-G', 'Ninja'])
        self.assertIn(f'-DWAYLAND_SCANNER={scanner}', command)
        for option in ('-DSDL_WAYLAND=ON', '-DSDL_WAYLAND_LIBDECOR=ON'):
            self.assertIn(option, command)
        self.assertFalse(any('patch' in str(arg).lower() for call in calls for arg in call.args[0]))
        env = calls[0].kwargs['env']
        self.assertEqual(env['PKG_CONFIG_SYSROOT_DIR'], str(sdk))
        self.assertEqual(env['PKG_CONFIG_PATH'], '')
        self.assertEqual(env['KEEP'], 'yes')
        self.assertTrue(all(call.kwargs['check'] for call in calls))

    def test_configured_wayland_without_compiled_driver_fails_before_build(self):
        calls, _, _, _ = self.run_build(missing='SDL_VIDEO_DRIVER_WAYLAND')
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
