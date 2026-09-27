#!/usr/bin/env python3
"""Adapt the pinned ImGui backend for title-local first-run music."""
from __future__ import annotations

import argparse
from pathlib import Path


def replace(source: str, anchor: str, replacement: str) -> str:
    if source.count(anchor) != 1:
        raise ValueError(f"Setup UI integration changed at {anchor!r}; review the framework pin.")
    return source.replace(anchor, replacement)


def prepare(source: str) -> str:
    source = replace(source, '#include "launcher_backend.h"',
                     '#include "launcher_backend.h"\n#include "setup_music.h"')
    source = replace(source, 'static void draw_setup_progress_modal(LauncherModel* m, const LauncherTheme& th) {',
                     'static SetupMusic* g_setup_music = nullptr;\n\n'
                     'static void draw_setup_music_controls() {\n'
                     '    if (!g_setup_music) return;\n'
                     '    bool muted = g_setup_music->muted();\n'
                     '    if (ImGui::Checkbox("Mute setup music", &muted)) g_setup_music->set_muted(muted);\n'
                     '    if (!g_setup_music->error().empty())\n'
                     '        ImGui::TextWrapped("Setup music: %s", g_setup_music->error().c_str());\n'
                     '}\n\n'
                     'static void draw_setup_progress_modal(LauncherModel* m, const LauncherTheme& th) {')
    for following in ('noun', 'game'):
        anchor = ('    const float wrap_x = ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x;\n'
                  f'    const char* {following} =')
        source = replace(source, anchor, '    draw_setup_music_controls();\n' + anchor)
    source = replace(source, '    while (m->action == LNG_ACTION_NONE && !p->should_quit) {',
                     '    // Only the actual first-run wizard starts music; other rebuild modals do not.\n'
                     '    std::unique_ptr<SetupMusic> setup_music;\n'
                     '    const bool first_run_music = m->setup_wizard_supported && m->setup_wizard_open;\n'
                     '    while (m->action == LNG_ACTION_NONE && !p->should_quit) {\n'
                     '        if (first_run_music && (m->setup_wizard_open || m->setup_preparing)) {\n'
                     '            if (!setup_music) setup_music.reset(new SetupMusic(asset("assets/setup/music.wav").c_str()));\n'
                     '            setup_music->tick();\n'
                     '        } else setup_music.reset();\n'
                     '        g_setup_music = setup_music.get();')
    source = replace(source, '    launcher_texture_free(&g_memcard);',
                     '    g_setup_music = nullptr;\n    setup_music.reset();\n    launcher_texture_free(&g_memcard);')
    source = replace(source, '#include <atomic>', '#include <atomic>\n#include <memory>')
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.source.read_text(encoding='utf-8-sig'))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result, encoding='utf-8')


if __name__ == '__main__':
    main()
