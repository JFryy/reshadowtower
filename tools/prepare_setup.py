#!/usr/bin/env python3
"""Adapt the pinned setup host to use only the package's read-only toolchain."""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_function(source: str, start: str, end: str, replacement: str) -> str:
    if source.count(start) != 1 or source.count(end) != 1:
        raise ValueError(f"Setup integration changed at {start}; review the framework pin.")
    first = source.index(start)
    last = source.index(end, first)
    return source[:first] + replacement + "\n\n" + source[last:]


def prepare(source: str) -> str:
    source = replace_function(source, "static int resolve_toolchain_bin(char* out, size_t cap) {",
        "static void activate_toolchain_path(void) {", '''static int resolve_toolchain_bin(char* out, size_t cap) {
    const char* pack = getenv("SHADOWTOWER_BUNDLED_TOOLCHAIN");
    return pack && pack[0] && resolve_toolchain_bin_under(pack, out, cap);
}''')
    source = replace_function(source, "static int host_toolchain_is_ready(void) {",
        "/* Fill *out with the installed pack's version string", '''static int host_toolchain_is_ready(void) {
    activate_toolchain_path();
    return g_toolchain_bin[0] && host_portable_cmake_ready();
}''')
    source = replace_function(source, "static int host_ensure_toolchain_with_progress(\n",
        "static int host_ensure_toolchain(", '''static int host_ensure_toolchain_with_progress(
    int download, const char* zip_path, char* err_msg, size_t err_cap,
    RecompLauncherCPrepareProgressFn on_progress, void* progress_ctx) {
    (void)download; (void)zip_path; (void)on_progress; (void)progress_ctx;
    if (host_toolchain_is_ready()) return 1;
    snprintf(err_msg, err_cap,
        "Bundled compiler is missing or cannot run. Re-extract the complete ReShadowTower package; no system tools were changed.");
    return 0;
}''')
    source = replace_function(source, "static int host_toolchain_update_available(char* local_ver, size_t local_cap,",
        "/* Download or offline-install cmake-clang-v1", '''static int host_toolchain_update_available(char* local_ver, size_t local_cap,
                                           char* remote_ver, size_t remote_cap) {
    if (local_ver && local_cap) local_ver[0] = '\\0';
    if (remote_ver && remote_cap) remote_ver[0] = '\\0';
    return 0;
}''')
    start = '#if defined(_WIN32)\n    if (on_progress)\n        on_progress(progress_ctx, 0.4f,'
    end = '#else\n    if (on_progress)\n        on_progress(progress_ctx, 0.05f,'
    source = replace_function(source, start, end, '''#if defined(_WIN32)
    char command[8192];
    int length = snprintf(command, sizeof(command),
        "\\\"%s\\\" \\\"%s\\\" rebuild --project-root \\\"%s\\\" --config \\\"%s\\\" "
        "--build-dir \\\"%s\\\" --target \\\"%s\\\" --exe-basename \\\"%s\\\" "
        "--no-pgo --json-progress",
        g_python, g_cli_path, g_project_root, g_game_toml, g_build_dir,
        g_cmake_target, g_exe_basename);
    if (length < 0 || (size_t)length >= sizeof(command)) {
        snprintf(err_msg, err_cap, "Build command is too long; use a shorter data-directory path.");
        return 0;
    }
    if (!run_cli_win(command, on_progress, progress_ctx, err_msg, err_cap,
                     "ReShadowTower build")) return 0;
    if (!path_is_file(g_exe_path)) {
        snprintf(err_msg, err_cap, "Build completed without the playable executable.");
        return 0;
    }
    snprintf(out_exe_path, out_cap, "%s", g_exe_path);
    return 1;
''')
    # Keep the bootstrap alive through Windows forwarding/relaunch, just as execv
    # does on Linux, so its user-data lock covers both setup and gameplay.
    wait_anchor = '        CloseHandle(pi.hThread);\n        CloseHandle(pi.hProcess);\n        ExitProcess(0);'
    if source.count(wait_anchor) != 2:
        raise ValueError("Setup relaunch integration changed; review the framework pin.")
    source = source.replace(wait_anchor,
        '        WaitForSingleObject(pi.hProcess, INFINITE);\n'
        '        DWORD child_code = 1;\n'
        '        GetExitCodeProcess(pi.hProcess, &child_code);\n'
        '        CloseHandle(pi.hThread);\n'
        '        CloseHandle(pi.hProcess);\n'
        '        ExitProcess(child_code);')
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.source.read_text(encoding="utf-8-sig"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result, encoding="utf-8")


if __name__ == "__main__":
    main()
