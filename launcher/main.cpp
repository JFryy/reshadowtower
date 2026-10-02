#include <SDL3/SDL.h>
#include <SDL3/SDL_opengl.h>
#include "imgui.h"
#include "imgui_impl_sdl3.h"
#include "imgui_impl_opengl3.h"

#include <array>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "model.hpp"
#include <filesystem>

using launcher::Settings;
struct Result { int code = -1; std::string text; };
struct State {
    std::mutex mutex;
    bool busy = false, completed = false;
    std::string action, message;
    Result result;
};
static Result run(const std::vector<std::string>& parts, const std::string& workspace, int volume = -1) {
    std::vector<const char*> args;
    for (const auto& part : parts) args.push_back(part.c_str());
    args.push_back(nullptr);
    const auto logPath = std::filesystem::u8path(workspace) / "launcher-process.log";
    SDL_IOStream* log = SDL_IOFromFile(logPath.u8string().c_str(), "ab");
    if (!log) return {-1, "Cannot open launcher-process.log: " + std::string(SDL_GetError())};
    SDL_PropertiesID props = SDL_CreateProperties();
    SDL_SetPointerProperty(props, SDL_PROP_PROCESS_CREATE_ARGS_POINTER, args.data());
    SDL_SetStringProperty(props, SDL_PROP_PROCESS_CREATE_WORKING_DIRECTORY_STRING, workspace.c_str());
    SDL_SetNumberProperty(props, SDL_PROP_PROCESS_CREATE_STDOUT_NUMBER, SDL_PROCESS_STDIO_REDIRECT);
    SDL_SetPointerProperty(props, SDL_PROP_PROCESS_CREATE_STDOUT_POINTER, log);
    SDL_SetBooleanProperty(props, SDL_PROP_PROCESS_CREATE_STDERR_TO_STDOUT_BOOLEAN, true);
    SDL_Environment* env = nullptr;
    if (volume >= 0) {
        env = SDL_CreateEnvironment(true);
        if (!env || !SDL_SetEnvironmentVariable(env, "SHADOWTOWER_VOLUME", std::to_string(volume).c_str(), true)) {
            const std::string error = SDL_GetError();
            if (env) SDL_DestroyEnvironment(env);
            SDL_DestroyProperties(props);
            SDL_CloseIO(log);
            return {-1, "Cannot configure game volume: " + error};
        }
        SDL_SetPointerProperty(props, SDL_PROP_PROCESS_CREATE_ENVIRONMENT_POINTER, env);
    }
    SDL_Process* process = SDL_CreateProcessWithProperties(props);
    SDL_DestroyProperties(props);
    if (env) SDL_DestroyEnvironment(env);
    if (!process) {
        const std::string error = SDL_GetError();
        SDL_CloseIO(log);
        return {-1, "Cannot start process: " + error};
    }
    int code = -1;
    const bool waited = SDL_WaitProcess(process, true, &code);
    const std::string error = waited ? "" : SDL_GetError();
    SDL_DestroyProcess(process);
    SDL_CloseIO(log);
    if (!waited) return {-1, "Cannot wait for process: " + error};
    if (code != 0) return {code, "Process exited with code " + std::to_string(code) + ". See " + logPath.u8string()};
    return {0, volume >= 0 ? "Game closed. Ready to play." : "Disc setup complete."};
}
struct BrowseResult {
    std::mutex mutex;
    std::string selected;
    bool pending = false;
    std::string error;
};
static void browseCallback(void* userdata, const char* const* files, int) {
    auto* result = static_cast<BrowseResult*>(userdata);
    std::lock_guard<std::mutex> lock(result->mutex);
    result->selected.clear();
    result->error.clear();
    if (!files) result->error = SDL_GetError();
    else if (files[0]) result->selected = files[0];
    result->pending = true;
}
int main(int argc, char** argv) {
    if (argc == 3 && !std::strcmp(argv[1], "--error")) {
        if (!SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "ReShadowTower", argv[2], nullptr)) {
            SDL_Log("%s\nCannot show error dialog: %s", argv[2], SDL_GetError());
            return 1;
        }
        return 0;
    }
    std::string python, backend, workspace;
    for (int i = 1; i < argc; i += 2) {
        if (i + 1 >= argc) return 2;
        if (!std::strcmp(argv[i], "--python")) python = argv[i + 1];
        else if (!std::strcmp(argv[i], "--backend")) backend = argv[i + 1];
        else if (!std::strcmp(argv[i], "--workspace")) workspace = argv[i + 1];
        else return 2;
    }
    if (python.empty() || backend.empty() || workspace.empty()) {
        SDL_Log("Usage: shadowtower-launcher --python PATH --backend PATH --workspace PATH");
        return 2;
    }
    try { workspace = std::filesystem::absolute(std::filesystem::u8path(workspace)).u8string(); }
    catch (const std::exception& error) { SDL_Log("Invalid workspace: %s", error.what()); return 1; }
    if (!SDL_Init(SDL_INIT_VIDEO)) { SDL_Log("SDL initialization failed: %s", SDL_GetError()); return 1; }
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 3);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_CORE);
    SDL_Window* window = SDL_CreateWindow("Shadow Tower", 680, 540, SDL_WINDOW_OPENGL | SDL_WINDOW_RESIZABLE);
    if (!window) { SDL_Log("Cannot create launcher window: %s", SDL_GetError()); SDL_Quit(); return 1; }
    SDL_GLContext context = SDL_GL_CreateContext(window);
    if (!context) { SDL_Log("Cannot create launcher OpenGL context: %s", SDL_GetError()); SDL_DestroyWindow(window); SDL_Quit(); return 1; }
    SDL_GL_MakeCurrent(window, context);
    SDL_GL_SetSwapInterval(1);
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGui::GetIO().IniFilename = nullptr;
    ImGui::GetIO().ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    ImGui::StyleColorsDark();
    ImGui::GetStyle().WindowPadding = ImVec2(18, 16);
    ImGui::GetStyle().ItemSpacing = ImVec2(10, 10);
    ImGui_ImplSDL3_InitForOpenGL(window, context);
    ImGui_ImplOpenGL3_Init("#version 330");
    Settings settings;
    std::string message;
    bool settingsLoaded = true;
    const auto workspacePath = std::filesystem::u8path(workspace);
    try { settings = launcher::load(workspacePath); }
    catch (const std::exception& e) {
        settingsLoaded = false;
        message = "Cannot load settings. Correct the file and restart.\n" + std::string(e.what());
    }
    bool ready = launcher::ready(workspacePath), running = true;
    bool selectSetup = !ready;
    std::array<char, 4096> disc{}, bios{};
    BrowseResult discBrowse, biosBrowse;
    int dialogs = 0;
    State state;
    state.message = message;
    std::thread worker;
    auto start = [&](const std::string& label, std::vector<std::string> args = {}) {
        if (worker.joinable()) worker.join();
        { std::lock_guard<std::mutex> lock(state.mutex); state.busy = true; state.completed = false; state.action = label; state.message = label + "..."; }
        worker = std::thread([&, label, args = std::move(args), snapshot = settings] {
            Result result;
            try {
                if (label == "setup") {
                    std::vector<std::string> command{python, backend, "--workspace", workspace};
                    command.insert(command.end(), args.begin(), args.end());
                    result = run(command, workspace);
                    if (result.code == 0 && !launcher::ready(workspacePath)) result = {-1, "Setup finished but build is not ready"};
                } else if (label == "play") {
                    if (!launcher::ready(workspacePath)) result = {-1, "Build is missing or changed"};
                    else {
                        launcher::save(workspacePath, snapshot);
                        result = run({launcher::executable(workspacePath).u8string(), "--no-launcher", "--game", (workspacePath / "game.toml").u8string()}, workspace, snapshot.volume);
                    }
                } else { launcher::save(workspacePath, snapshot); result = {0, "Settings saved"}; }
            } catch (const std::exception& e) { result = {-1, e.what()}; }
            std::lock_guard<std::mutex> lock(state.mutex);
            state.result = std::move(result);
            state.completed = true;
        });
    };
    while (running) {
        SDL_Event event;
        while (SDL_PollEvent(&event)) {
            bool busy;
            { std::lock_guard<std::mutex> lock(state.mutex); busy = state.busy; }
            if (event.type == SDL_EVENT_QUIT || event.type == SDL_EVENT_WINDOW_CLOSE_REQUESTED) {
                if (!busy && !dialogs) running = false;
                continue;
            }
            ImGui_ImplSDL3_ProcessEvent(&event);
        }
        bool busy;
        {
            std::lock_guard<std::mutex> lock(state.mutex);
            if (state.completed) {
                state.completed = false;
                state.busy = false;
                if (state.action == "setup") ready = launcher::ready(workspacePath);
                state.message = state.result.text.empty() ? (state.result.code == 0 ? "Done" : "Action failed") : state.result.text;
                if (state.result.code != 0 && state.action == "setup")
                    state.message += "\nSetup details: " + workspace + "/launcher-actions.log";
            }
            busy = state.busy;
            message = state.message;
        }
        auto applyBrowse = [&](BrowseResult& result, std::array<char, 4096>& path) {
            std::lock_guard<std::mutex> lock(result.mutex);
            if (result.pending) {
                if (result.selected.size() >= path.size()) message = "Selected path is too long. Move the disc to a shorter path.";
                else if (!result.selected.empty()) SDL_strlcpy(path.data(), result.selected.c_str(), path.size());
                if (!result.error.empty()) { message = result.error; result.error.clear(); }
                result.pending = false;
                --dialogs;
            }
        };
        applyBrowse(discBrowse, disc);
        applyBrowse(biosBrowse, bios);
        { std::lock_guard<std::mutex> lock(state.mutex); state.message = message; }
        ImGui_ImplOpenGL3_NewFrame();
        ImGui_ImplSDL3_NewFrame();
        ImGui::NewFrame();
        ImGui::SetNextWindowPos(ImVec2(0, 0));
        ImGui::SetNextWindowSize(ImGui::GetIO().DisplaySize);
        ImGui::Begin("Launcher", nullptr, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoResize);
        ImGui::Dummy(ImVec2(0, 12));
        ImGui::TextUnformatted("SHADOW TOWER");
        ImGui::Separator();
        ImGui::BeginDisabled(busy || dialogs != 0);
        if (ImGui::BeginTabBar("Pages")) {
            if (ImGui::BeginTabItem("Play")) {
                ImGui::TextUnformatted(ready ? "Ready to play" : "Disc setup required");
                ImGui::BeginDisabled(!ready || !settingsLoaded);
                if (ImGui::Button("Play", ImVec2(160, 36))) start("play");
                ImGui::EndDisabled();
                ImGui::EndTabItem();
            }
            if (ImGui::BeginTabItem("Settings")) {
                ImGui::BeginDisabled(!settingsLoaded);
                ImGui::TextWrapped("Save settings, or press Play to save and launch. Changes apply on the next game launch.");
                ImGui::Checkbox("Widescreen (experimental)", &settings.widescreen);
                ImGui::BeginDisabled(!settings.widescreen);
                ImGui::Combo("Wide ratio", &settings.wideRatio, "16:9\0" "21:9\0");
                ImGui::EndDisabled();
                if (!settings.widescreen) ImGui::TextUnformatted("Original 4:3 presentation");
                ImGui::Checkbox("Fullscreen", &settings.fullscreen);
                ImGui::SliderInt("Resolution scale", &settings.scale, 1, 4, "%dx");
                ImGui::SliderInt("Volume", &settings.volume, 0, 100);
                ImGui::Checkbox("Texture filtering", &settings.filter);
                ImGui::Checkbox("Geometry correction", &settings.geometry);
                ImGui::Checkbox("Perspective textures", &settings.perspective);
                if (settings.widescreen)
                    ImGui::TextWrapped("Experimental: menus and scenery at the edges may not display correctly. Switch to 4:3 if needed.");
                if (ImGui::Button("Save settings")) start("save");
                ImGui::EndDisabled();
                ImGui::EndTabItem();
            }
            if (ImGui::BeginTabItem("Disc setup", nullptr, selectSetup ? ImGuiTabItemFlags_SetSelected : 0)) {
                selectSetup = false;
                ImGui::TextWrapped("Select your Shadow Tower (USA) disc. Setup verifies it and builds the game locally, without downloads.");
                ImGui::TextUnformatted("Disc image");
                ImGui::SetNextItemWidth(-130);
                ImGui::InputText("##Disc path", disc.data(), disc.size());
                ImGui::SameLine();
                if (ImGui::Button("Browse disc")) { ++dialogs; SDL_ShowOpenFileDialog(browseCallback, &discBrowse, window, nullptr, 0, nullptr, false); }
                ImGui::TextUnformatted("BIOS (optional; uses bundled OpenBIOS when blank)");
                ImGui::SetNextItemWidth(-130);
                ImGui::InputText("##BIOS path", bios.data(), bios.size());
                ImGui::SameLine();
                if (ImGui::Button("Browse BIOS")) { ++dialogs; SDL_ShowOpenFileDialog(browseCallback, &biosBrowse, window, nullptr, 0, nullptr, false); }
                ImGui::BeginDisabled(!disc[0]);
                if (ImGui::Button("Build game")) {
                    std::vector<std::string> args{"setup", "--disc", disc.data()};
                    if (bios[0]) { args.push_back("--bios"); args.push_back(bios.data()); }
                    start("setup", std::move(args));
                }
                ImGui::EndDisabled();
                ImGui::EndTabItem();
            }
            ImGui::EndTabBar();
        }
        ImGui::EndDisabled();
        ImGui::Separator();
        ImGui::TextWrapped("%s", message.c_str());
        ImGui::End();
        ImGui::Render();
        int pixelWidth = 0, pixelHeight = 0;
        SDL_GetWindowSizeInPixels(window, &pixelWidth, &pixelHeight);
        glViewport(0, 0, pixelWidth, pixelHeight);
        glClearColor(0.10f, 0.10f, 0.11f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());
        SDL_GL_SwapWindow(window);
    }
    if (worker.joinable()) worker.join();
    ImGui_ImplOpenGL3_Shutdown();
    ImGui_ImplSDL3_Shutdown();
    ImGui::DestroyContext();
    SDL_GL_DestroyContext(context);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}
