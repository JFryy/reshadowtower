#!/usr/bin/env python3
"""Connect title-owned setup music to the pinned ImGui backend."""
from __future__ import annotations

import argparse
from pathlib import Path


# The adapter only threads a session-owned controller through the UI calls.
REPLACEMENTS = (
    ('#include "launcher_backend.h"',
     '#include "launcher_backend.h"\n#include "setup_music_ui.h"', 1),
    ('draw_setup_progress_modal(LauncherModel* m, const LauncherTheme& th)',
     'draw_setup_progress_modal(LauncherModel* m, const LauncherTheme& th, SetupMusicUI& music)', 1),
    ('draw_setup_wizard_modal(LauncherModel* m, const LauncherTheme& th)',
     'draw_setup_wizard_modal(LauncherModel* m, const LauncherTheme& th, SetupMusicUI& music)', 1),
    ('draw_ui(LauncherModel* m, const LauncherTheme& th, int logical_w, int logical_h)',
     'draw_ui(LauncherModel* m, const LauncherTheme& th, int logical_w, int logical_h, SetupMusicUI& music)', 1),
    ('draw_setup_progress_modal(m, th);', 'draw_setup_progress_modal(m, th, music);', 3),
    ('draw_setup_wizard_modal(m, th);', 'draw_setup_wizard_modal(m, th, music);', 1),
    ('    const float wrap_x = ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x;\n    const char* noun =',
     '    music.draw_controls();\n'
     '    const float wrap_x = ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x;\n    const char* noun =', 1),
    ('    const float wrap_x = ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x;\n    const char* game =',
     '    music.draw_controls();\n'
     '    const float wrap_x = ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x;\n    const char* game =', 1),
    ('    while (m->action == LNG_ACTION_NONE && !p->should_quit) {',
     '    SetupMusicUI setup_music(m->setup_wizard_supported && m->setup_wizard_open,\n'
     '                             asset("assets/setup/music.wav").c_str());\n'
     '    while (m->action == LNG_ACTION_NONE && !p->should_quit) {\n'
     '        setup_music.update(m->setup_wizard_open, m->setup_preparing);', 1),
    ('draw_ui(m, *th, p->logical_w, p->logical_h);',
     'draw_ui(m, *th, p->logical_w, p->logical_h, setup_music);', 1),
    ('    launcher_boot_timing_mark("rui:action_requested");',
     '    setup_music.stop();\n    launcher_boot_timing_mark("rui:action_requested");', 1),
)


def prepare(source: str) -> str:
    for anchor, replacement, count in REPLACEMENTS:
        if source.count(anchor) != count:
            raise ValueError(f"Setup UI integration changed at {anchor!r}; review the framework pin.")
        source = source.replace(anchor, replacement)
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.source.read_text(encoding="utf-8-sig"))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result, encoding="utf-8")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Setup UI preparation failed: {error}\n")


if __name__ == "__main__":
    main()
