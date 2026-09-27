/* Connect Shadow Tower to the framework's disc-first setup host. */
#include "codegen_setup.h"
#include "psxrecomp_codegen_host.h"

static const PsxrecompCodegenHostConfig kCodegenConfig = {
    .display_name = "Shadow Tower Recompiled",
    .project_root_env = "SHADOWTOWER_PROJECT_ROOT",
    .build_dir_env = "SHADOWTOWER_BUILD_DIR",
    .force_setup_env = "SHADOWTOWER_FORCE_SETUP",
    .psxrecomp_cli_relpath = "tools/release_cli.py",
    .seed_cfg_relpath = "game.toml",
    .game_toml_relpath = "game.toml",
    .gen_marker_relpath = "generated/SLUS_008.63_dispatch.c",
    .build_dir_name = "build-release",
    .cmake_target = "psx-runtime",
    .exe_basename = "Shadow_Tower_Recompiled",
    .prepare_note = "Supply your own Shadow Tower (USA) disc. Setup generates game code and OpenBIOS locally, then builds the playable game.",
    .prepare_note_windows = "Supply your own Shadow Tower (USA) disc. Setup generates and builds the game locally using the included tools.",
};

void psx_game_codegen_setup_apply(RecompLauncherCGameInfo* gi) {
    psxrecomp_codegen_host_apply(gi, &kCodegenConfig);
    gi->pgo_optimize_with_progress = NULL;
    gi->rebuild_busy_status = "Building the playable game...";
    gi->rebuild_success_status = "Build complete. Starting the game...";
}

void psx_game_codegen_relaunch_or_exit(const char* disc_path) {
    psxrecomp_codegen_host_relaunch_or_exit(disc_path);
}

void psx_game_codegen_forward_if_built(int argc, char** argv) {
    psxrecomp_codegen_host_forward_if_built(&kCodegenConfig, argc, argv);
}
