"""Exercise setup audio with real SDL's dummy driver, without game assets or a display."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
import wave


ROOT = Path(__file__).resolve().parents[1]
IMGUI = ROOT / "recomp-ui/src/third_party/imgui"


class SetupMusicAudioTests(unittest.TestCase):
    def test_playback_and_setup_lifecycle(self):
        flags = shlex.split(subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", "sdl3"], text=True))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            track = root / "short.wav"
            with wave.open(str(track), "wb") as wav:
                wav.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
                wav.writeframes(b"\0" * (1764 * 4))
            executable = root / "setup_music_test"
            subprocess.run(
                ["c++", "-std=c++17", "-Isrc", f"-I{IMGUI}",
                 "src/setup_music.cpp", "src/setup_music_ui.cpp", "tests/setup_music_test.cpp",
                 *(str(IMGUI / name) for name in (
                     "imgui.cpp", "imgui_draw.cpp", "imgui_tables.cpp", "imgui_widgets.cpp")),
                 *flags, "-o", str(executable)],
                cwd=ROOT, check=True,
            )
            subprocess.run([str(executable), str(track)], check=True,
                           env={**os.environ, "SDL_AUDIO_DRIVER": "dummy"})


if __name__ == "__main__":
    unittest.main()
