#include <SDL3/SDL.h>
#include <SDL3/SDL_opengl.h>
#include "imgui.h"
#include "imgui_impl_sdl3.h"
#include "imgui_impl_opengl3.h"

#include <array>
#include <cmath>
#include <fstream>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "model.hpp"
#include "artwork.hpp"
#include "bindings.hpp"
#include <filesystem>

using launcher::Settings;
struct Result { int code = -1; std::string text; };
struct State {
    std::mutex mutex;
    bool busy = false, completed = false;
    std::string action, message;
    Result result;
};
static Result run(const std::vector<std::string>& parts, const std::string& workspace, const Settings* settings = nullptr) {
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
    if (settings) {
        env = SDL_CreateEnvironment(true);
        if (!env) {
            const std::string error = SDL_GetError();
            SDL_DestroyProperties(props);
            SDL_CloseIO(log);
            return {-1, "Cannot prepare game environment: " + error};
        }
        for (const auto& entry : launcher::gameEnvironment(*settings)) {
            if (!SDL_SetEnvironmentVariable(env, entry.first.c_str(), entry.second.c_str(), true)) {
                const std::string error = SDL_GetError();
                SDL_DestroyEnvironment(env);
                SDL_DestroyProperties(props);
                SDL_CloseIO(log);
                return {-1, "Cannot configure " + entry.first + ": " + error};
            }
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
    return {0, settings ? "Game closed. Ready to play." : "Disc setup complete."};
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
// Apply a neutral, high-contrast visual style at the display's UI scale.
static void styleLauncher(float scale) {
    auto& style = ImGui::GetStyle();
    ImGui::StyleColorsDark();
    style.WindowPadding = ImVec2(24, 22);
    style.FramePadding = ImVec2(12, 9);
    style.ItemSpacing = ImVec2(12, 12);
    style.WindowRounding = 0;
    style.ChildRounding = 10;
    style.FrameRounding = 5;
    style.GrabRounding = 4;
    style.FrameBorderSize = 1;
    style.Colors[ImGuiCol_WindowBg] = ImVec4(.065f, .073f, .082f, 1);
    style.Colors[ImGuiCol_ChildBg] = ImVec4(.085f, .095f, .107f, 1);
    style.Colors[ImGuiCol_Text] = ImVec4(.91f, .92f, .93f, 1);
    style.Colors[ImGuiCol_TextDisabled] = ImVec4(.57f, .61f, .65f, 1);
    style.Colors[ImGuiCol_Border] = ImVec4(.20f, .23f, .26f, .65f);
    style.Colors[ImGuiCol_FrameBg] = ImVec4(.12f, .14f, .16f, 1);
    style.Colors[ImGuiCol_FrameBgHovered] = ImVec4(.19f, .22f, .25f, 1);
    style.Colors[ImGuiCol_FrameBgActive] = ImVec4(.23f, .27f, .30f, 1);
    style.Colors[ImGuiCol_Button] = ImVec4(.18f, .22f, .25f, 1);
    style.Colors[ImGuiCol_ButtonHovered] = ImVec4(.25f, .31f, .35f, 1);
    style.Colors[ImGuiCol_ButtonActive] = ImVec4(.30f, .37f, .41f, 1);
    style.Colors[ImGuiCol_Header] = ImVec4(.19f, .24f, .28f, 1);
    style.Colors[ImGuiCol_HeaderHovered] = ImVec4(.23f, .29f, .33f, 1);
    style.Colors[ImGuiCol_HeaderActive] = ImVec4(.28f, .35f, .39f, 1);
    style.Colors[ImGuiCol_CheckMark] = ImVec4(.72f, .80f, .78f, 1);
    style.Colors[ImGuiCol_SliderGrab] = ImVec4(.55f, .67f, .66f, 1);
    style.Colors[ImGuiCol_SliderGrabActive] = ImVec4(.72f, .82f, .80f, 1);
    style.ScaleAllSizes(scale);
}

static void hint(const char* text) {
    ImGui::PushStyleColor(ImGuiCol_Text, ImGui::GetStyleColorVec4(ImGuiCol_TextDisabled));
    ImGui::TextWrapped("%s", text);
    ImGui::PopStyleColor();
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
    SDL_Window* window = SDL_CreateWindow("Shadow Tower", 960, 700, SDL_WINDOW_OPENGL | SDL_WINDOW_RESIZABLE | SDL_WINDOW_HIGH_PIXEL_DENSITY);
    if (!window) { SDL_Log("Cannot create launcher window: %s", SDL_GetError()); SDL_Quit(); return 1; }
    SDL_SetWindowMinimumSize(window, 760, 600);
    SDL_GLContext context = SDL_GL_CreateContext(window);
    if (!context) { SDL_Log("Cannot create launcher OpenGL context: %s", SDL_GetError()); SDL_DestroyWindow(window); SDL_Quit(); return 1; }
    SDL_GL_MakeCurrent(window, context);
    SDL_GL_SetSwapInterval(1);
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGui::GetIO().IniFilename = nullptr;
    ImGui::GetIO().ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    const float pixelDensity = std::max(SDL_GetWindowPixelDensity(window), 1.0f);
    const float uiScale = std::clamp(SDL_GetWindowDisplayScale(window) / pixelDensity, 1.0f, 3.0f);
    SDL_SetWindowMinimumSize(window, static_cast<int>(760 * uiScale), static_cast<int>(600 * uiScale));
    SDL_SetWindowSize(window, static_cast<int>(960 * uiScale), static_cast<int>(700 * uiScale));
    styleLauncher(uiScale);
    ImFontConfig fontConfig;
    fontConfig.SizePixels = 17.0f * uiScale * pixelDensity;
    ImGui::GetIO().FontGlobalScale = 1.0f / pixelDensity;
    ImGui::GetIO().Fonts->AddFontDefault(&fontConfig);
    ImGui_ImplSDL3_InitForOpenGL(window, context);
    ImGui_ImplOpenGL3_Init("#version 330");
    Settings settings;
    launcher::Bindings bindings;
    std::string message;
    bool settingsLoaded = true;
    const auto workspacePath = std::filesystem::u8path(workspace);
    try { settings = launcher::load(workspacePath); bindings = launcher::loadBindings(workspacePath); }
    catch (const std::exception& e) {
        settingsLoaded = false;
        message = "Cannot load preferences. Correct the reported file and restart.\n" + std::string(e.what());
    }
    bool ready = launcher::ready(workspacePath), running = true;
    int page = ready ? 0 : 4;
    bool dirty = false, confirmClose = false, closeAfterSave = false;
    std::array<char, 4096> disc{}, bios{};
    BrowseResult discBrowse, biosBrowse;
    Artwork artwork;
    const auto artworkPath = workspacePath / "assets/setup/boxart.tga";
    try {
        artwork.load(artworkPath);
    } catch (const std::exception& error) {
        if (!message.empty()) message += "\n";
        message += error.what();
    }
    int dialogs = 0;
    State state;
    state.message = message;
    std::thread worker;
    std::streamoff setupLogStart = 0;
    Uint64 progressUpdated = 0;
    std::string setupStage;
    auto start = [&](const std::string& label, std::vector<std::string> args = {}) {
        if (worker.joinable()) worker.join();
        if (label == "setup") {
            std::ifstream log(workspacePath / "launcher-process.log", std::ios::binary | std::ios::ate);
            setupLogStart = log ? static_cast<std::streamoff>(log.tellg()) : 0;
            setupStage = "Starting setup";
        }
        { std::lock_guard<std::mutex> lock(state.mutex); state.busy = true; state.completed = false; state.action = label; state.message = label + "..."; }
        worker = std::thread([&, label, args = std::move(args), snapshot = settings, bindingsSnapshot = bindings] {
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
                        launcher::saveBindings(workspacePath, bindingsSnapshot);
                        result = run({launcher::executable(workspacePath).u8string(), "--no-launcher", "--game", (workspacePath / "game.toml").u8string()}, workspace, &snapshot);
                    }
                } else {
                    launcher::save(workspacePath, snapshot);
                    launcher::saveBindings(workspacePath, bindingsSnapshot);
                    result = {0, "Settings saved"};
                }
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
                if (!busy && !dialogs) {
                    if (dirty) confirmClose = true;
                    else running = false;
                }
                continue;
            }
            ImGui_ImplSDL3_ProcessEvent(&event);
        }
        bool busy;
        std::string action;
        {
            std::lock_guard<std::mutex> lock(state.mutex);
            if (state.completed) {
                state.completed = false;
                state.busy = false;
                if (closeAfterSave) {
                    if (state.result.code == 0) running = false;
                    closeAfterSave = false;
                }
                if (state.result.code == 0 && state.action != "setup") dirty = false;
                if (state.action == "setup") ready = launcher::ready(workspacePath);
                state.message = state.result.text.empty() ? (state.result.code == 0 ? "Done" : "Action failed") : state.result.text;
                if (state.result.code != 0 && state.action == "setup")
                    state.message += "\nSetup details: " + workspace + "/launcher-actions.log";
            }
            busy = state.busy;
            action = state.action;
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
        if (busy && action == "setup" && SDL_GetTicks() - progressUpdated > 300) {
            progressUpdated = SDL_GetTicks();
            std::ifstream log(workspacePath / "launcher-process.log", std::ios::binary);
            if (log) {
                log.seekg(setupLogStart);
                std::string line;
                while (std::getline(log, line)) {
                    if (line == "Verifying the disc...") setupStage = "1 / 3  Verifying disc";
                    else if (line == "Generating game code...") setupStage = "2 / 3  Generating game code";
                    else if (line == "Building the game...") setupStage = "3 / 3  Building game";
                }
            }
        }
        ImGui_ImplOpenGL3_NewFrame();
        ImGui_ImplSDL3_NewFrame();
        ImGui::NewFrame();
        ImGui::SetNextWindowPos(ImVec2(0, 0));
        ImGui::SetNextWindowSize(ImGui::GetIO().DisplaySize);
        ImGui::Begin("Launcher", nullptr, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoResize);
        ImGui::TextUnformatted("SHADOW TOWER");
        ImGui::SameLine();
        ImGui::TextDisabled(" /  PC EDITION");
        ImGui::Spacing();
        ImGui::Separator();
        const float footerHeight = 88 * uiScale;
        ImGui::BeginChild("Navigation", ImVec2(150 * uiScale, -footerHeight));
        const char* pages[] = {"Play", "Graphics", "Audio", "Controls", "Disc setup"};
        for (int i = 0; i < 5; ++i) {
            if (ImGui::Selectable(pages[i], page == i, 0, ImVec2(0, 38 * uiScale))) page = i;
        }
        ImGui::Spacing();
        ImGui::Separator();
        ImGui::Spacing();
        hint(ready ? "Game installed" : "Setup required");
        if (dirty) hint("Unsaved changes");
        ImGui::EndChild();
        ImGui::SameLine();
        ImGui::BeginChild("Content", ImVec2(0, -footerHeight), ImGuiChildFlags_Borders);
        ImGui::BeginDisabled(busy || dialogs != 0);
        if (page == 0) {
            ImGui::TextUnformatted("Return to the depths.");
            hint("Shadow Tower, running natively on your PC.");
            ImGui::Spacing();
            const ImVec2 artSize(ImGui::GetContentRegionAvail().x, 230 * uiScale);
            const ImVec2 origin = ImGui::GetCursorScreenPos();
            auto* draw = ImGui::GetWindowDrawList();
            draw->AddRectFilled(origin, ImVec2(origin.x + artSize.x, origin.y + artSize.y), IM_COL32(17, 22, 27, 255), 8 * uiScale);
            if (artwork.texture) {
                const float sourceAspect = static_cast<float>(artwork.width) / artwork.height;
                const float targetAspect = artSize.x / artSize.y;
                ImVec2 uv0(0, 0), uv1(1, 1);
                if (sourceAspect > targetAspect) { const float crop = targetAspect / sourceAspect; uv0.x = (1 - crop) / 2; uv1.x = (1 + crop) / 2; }
                else { const float crop = sourceAspect / targetAspect; uv0.y = (1 - crop) / 2; uv1.y = (1 + crop) / 2; }
                draw->AddImageRounded(static_cast<ImTextureID>(artwork.texture), origin,
                    ImVec2(origin.x + artSize.x, origin.y + artSize.y), uv0, uv1, IM_COL32(195, 205, 210, 255), 8 * uiScale);
            } else {
                // Fallback illustration when the packaged cover cannot be loaded.
                const float center = origin.x + artSize.x * .64f;
                for (int i = 0; i < 6; ++i) {
                    const float half = (56 - i * 5) * uiScale;
                    const float top = origin.y + (190 - i * 28) * uiScale;
                    draw->AddRectFilled(ImVec2(center - half, top), ImVec2(center + half, origin.y + artSize.y), IM_COL32(30 + i * 3, 38 + i * 3, 44 + i * 3, 255));
                }
                draw->AddText(ImVec2(origin.x + 20 * uiScale, origin.y + 185 * uiScale), IM_COL32(155, 169, 178, 255), "DESCEND INTO THE UNKNOWN");
            }
            ImGui::Dummy(artSize);
            ImGui::BeginDisabled(!ready || !settingsLoaded);
            if (ImGui::Button("Play game", ImVec2(170 * uiScale, 44 * uiScale))) start("play");
            ImGui::EndDisabled();
            if (!ready) { hint("Use Disc setup to verify your disc and install the game."); }
            else hint(settings.widescreen ? "Widescreen gameplay. Menus stretch to fill." : "Original 4:3 presentation.");
        } else if (page == 1) {
            ImGui::BeginDisabled(!settingsLoaded);
            ImGui::TextUnformatted("Graphics");
            hint("Changes apply the next time you launch the game.");
            ImGui::Spacing();
            dirty |= ImGui::Checkbox("Widescreen (experimental)", &settings.widescreen);
            ImGui::BeginDisabled(!settings.widescreen);
            ImGui::SetNextItemWidth(160 * uiScale);
            dirty |= ImGui::Combo("Aspect ratio", &settings.wideRatio, "16:9\0" "21:9\0");
            ImGui::EndDisabled();
            hint(settings.widescreen ? "More scenery is rendered at the sides; menus stretch to fill. Some edge geometry may be incomplete." : "Original 4:3 presentation. Your wide-ratio preference is remembered.");
            int displayMode = settings.fullscreen ? 1 : 0;
            ImGui::SetNextItemWidth(210 * uiScale);
            if (ImGui::Combo("Display mode", &displayMode, "Windowed\0Fullscreen (desktop)\0")) {
                settings.fullscreen = displayMode == 1;
                dirty = true;
            }
            int preset = static_cast<int>(launcher::graphicsPreset(settings));
            ImGui::SetNextItemWidth(210 * uiScale);
            if (ImGui::Combo("Quality preset", &preset, "Original / performance\0Balanced\0High quality\0Custom\0")) {
                launcher::applyGraphicsPreset(settings, static_cast<launcher::GraphicsPreset>(preset));
                dirty = true;
            }
            ImGui::SetNextItemWidth(210 * uiScale);
            dirty |= ImGui::SliderInt("Resolution scale", &settings.scale, 1, 4, "%dx");
            dirty |= ImGui::Checkbox("Texture filtering", &settings.filter);
            dirty |= ImGui::Checkbox("Geometry correction", &settings.geometry);
            dirty |= ImGui::Checkbox("Perspective-correct textures", &settings.perspective);
            if (ImGui::CollapsingHeader("Frame pacing")) {
                dirty |= ImGui::Checkbox("VSync", &settings.vsync);
                hint("Synchronize presentation when the display timing supports it. The runtime uses its own pacer otherwise; disabling this does not unlock game speed.");
                dirty |= ImGui::Checkbox("Low-latency input", &settings.lowLatency);
                hint("Poll input closer to the game's input read to reduce delay.");
            }
            if (ImGui::CollapsingHeader("Post-processing")) {
                auto& fx = settings.postFx;
                dirty |= ImGui::Checkbox("Enable post-processing", &fx.enabled);
                hint("Off by default. Effects apply to the whole game image, including its HUD and menus, on the next launch.");
                int effectPreset = static_cast<int>(launcher::postFxPreset(fx));
                ImGui::SetNextItemWidth(210 * uiScale);
                if (ImGui::Combo("Effect preset", &effectPreset, "Original (off)\0Subtle\0CRT\0Custom\0")) {
                    launcher::applyPostFxPreset(fx, static_cast<launcher::PostFxPreset>(effectPreset));
                    dirty = true;
                }
                ImGui::BeginDisabled(!fx.enabled);
                const auto effect = [&](const char* label, float& value, float low, float high, const char* format) {
                    ImGui::SetNextItemWidth(210 * uiScale);
                    dirty |= ImGui::SliderFloat(label, &value, low, high, format, ImGuiSliderFlags_AlwaysClamp);
                };
                ImGui::TextUnformatted("Color grading");
                effect("Exposure", fx.exposure, -2.f, 2.f, "%+.2f stops");
                effect("Contrast", fx.contrast, .5f, 1.5f, "%.2fx");
                effect("Saturation", fx.saturation, 0.f, 2.f, "%.2fx");
                ImGui::TextUnformatted("Texture and glow");
                effect("Film grain", fx.grain, 0.f, .2f, "%.3f");
                effect("Dithering", fx.dither, 0.f, 1.f, "%.2f");
                effect("Bloom", fx.bloom, 0.f, 1.f, "%.2f");
                hint("Zero disables each effect. Bloom adds a subtle glow around bright pixels; it is not HDR lighting.");
                ImGui::TextUnformatted("CRT presentation");
                effect("Scanlines", fx.scanlines, 0.f, 1.f, "%.2f");
                effect("RGB mask", fx.mask, 0.f, 1.f, "%.2f");
                effect("Curvature", fx.curvature, 0.f, .2f, "%.2f");
                ImGui::EndDisabled();
            }
            ImGui::EndDisabled();
        } else if (page == 2) {
            ImGui::BeginDisabled(!settingsLoaded);
            ImGui::TextUnformatted("Audio");
            hint("Master volume for the game. Changes apply on the next launch.");
            ImGui::Spacing();
            ImGui::SetNextItemWidth(250 * uiScale);
            dirty |= ImGui::SliderInt("Volume", &settings.volume, 0, 100, "%d%%");
            ImGui::EndDisabled();
        } else if (page == 3) {
            ImGui::BeginDisabled(!settingsLoaded);
            ImGui::TextUnformatted("Controls");
            hint("Keyboard and mouse, or a connected controller.");
            ImGui::Spacing();
            ImGui::TextWrapped("W / S  Move forward / back\nA / D  Strafe\nE  Interact\nF  Attack\nTab  Open menu\nC  Back / cancel");
            ImGui::Spacing();
            hint("Click the game window to capture the mouse. Escape releases it.");
            float sensitivity = static_cast<float>(settings.mouseSensitivity);
            ImGui::SetNextItemWidth(230 * uiScale);
            if (ImGui::SliderFloat("Mouse sensitivity", &sensitivity, .05f, 10.f, "%.2fx", ImGuiSliderFlags_Logarithmic)) {
                settings.mouseSensitivity = static_cast<double>(sensitivity);
                dirty = true;
            }
            if (ImGui::Button("Reset mouse sensitivity")) { settings.mouseSensitivity = 1.0; dirty = true; }
            if (ImGui::CollapsingHeader("Controller bindings")) {
                hint("Physical buttons use SDL / Xbox names. These map to the original PlayStation controls. Device-specific input.ini overrides take precedence.");
                if (ImGui::BeginTable("Bindings", 2, ImGuiTableFlags_SizingStretchSame)) {
                    for (size_t i = 0; i < launcher::bindingKeys.size(); ++i) {
                        ImGui::TableNextColumn();
                        ImGui::PushID(static_cast<int>(i));
                        ImGui::TextUnformatted(launcher::bindingLabels[i]);
                        ImGui::SetNextItemWidth(-1);
                        const auto& value = bindings.sources[i];
                        if (ImGui::BeginCombo("##source", value.empty() ? "Unbound" : value.c_str())) {
                            for (const char* source : launcher::bindingSources) {
                                const bool selected = value == source;
                                if (ImGui::Selectable(*source ? source : "Unbound", selected)) {
                                    bindings.sources[i] = source;
                                    dirty = true;
                                }
                                if (selected) ImGui::SetItemDefaultFocus();
                            }
                            ImGui::EndCombo();
                        }
                        ImGui::PopID();
                    }
                    ImGui::EndTable();
                }
                if (ImGui::Button("Restore default controller bindings")) { bindings = launcher::Bindings{}; dirty = true; }
            }
            ImGui::EndDisabled();
        } else {
            ImGui::TextUnformatted("Disc setup");
            hint("Use your Shadow Tower (USA) disc image. Verification and installation run locally, without downloads.");
            ImGui::Spacing();
            ImGui::TextUnformatted("Disc image");
            ImGui::SetNextItemWidth(-120 * uiScale);
            ImGui::InputText("##Disc path", disc.data(), disc.size());
            ImGui::SameLine();
            if (ImGui::Button("Browse##disc")) {
                ++dialogs;
                static const SDL_DialogFileFilter filters[] = {{"Disc images", "cue;bin;iso;chd"}};
                SDL_ShowOpenFileDialog(browseCallback, &discBrowse, window, filters, 1, nullptr, false);
            }
            ImGui::TextUnformatted("BIOS (optional)");
            ImGui::SetNextItemWidth(-120 * uiScale);
            ImGui::InputText("##BIOS path", bios.data(), bios.size());
            ImGui::SameLine();
            if (ImGui::Button("Browse##bios")) { ++dialogs; SDL_ShowOpenFileDialog(browseCallback, &biosBrowse, window, nullptr, 0, nullptr, false); }
            hint("Leave blank to use bundled OpenBIOS. Existing saves are not removed.");
            ImGui::Spacing();
            ImGui::BeginDisabled(!disc[0]);
            if (ImGui::Button(ready ? "Rebuild game" : "Install game", ImVec2(170 * uiScale, 44 * uiScale))) {
                std::vector<std::string> args{"setup", "--disc", disc.data()};
                if (bios[0]) { args.push_back("--bios"); args.push_back(bios.data()); }
                start("setup", std::move(args));
            }
            ImGui::EndDisabled();
            hint("Setup progress and detailed errors are recorded in launcher-actions.log.");
        }
        ImGui::EndDisabled();
        ImGui::EndChild();
        ImGui::Separator();
        ImGui::BeginDisabled(busy || dialogs != 0 || !settingsLoaded || !dirty);
        if (ImGui::Button("Save settings")) start("save");
        ImGui::EndDisabled();
        ImGui::SameLine();
        ImGui::BeginChild("Status", ImVec2(0, 0));
        if (busy) {
            const char* frames[] = {".  ", ".. ", "..."};
            ImGui::Text("%s%s", action == "setup" ? setupStage.c_str() : action == "play" ? "Game running" : "Saving", frames[static_cast<int>(ImGui::GetTime() * 3) % 3]);
        } else if (!message.empty()) ImGui::TextWrapped("%s", message.c_str());
        else hint("Settings save automatically when you press Play.");
        ImGui::EndChild();
        ImGui::End();
        if (confirmClose) { ImGui::OpenPopup("Unsaved changes"); confirmClose = false; }
        if (ImGui::BeginPopupModal("Unsaved changes", nullptr, ImGuiWindowFlags_AlwaysAutoResize)) {
            ImGui::TextUnformatted("Save your settings before closing?");
            if (ImGui::Button("Save and close")) { closeAfterSave = true; start("save"); ImGui::CloseCurrentPopup(); }
            ImGui::SameLine();
            if (ImGui::Button("Discard")) { running = false; ImGui::CloseCurrentPopup(); }
            ImGui::SameLine();
            if (ImGui::Button("Cancel")) ImGui::CloseCurrentPopup();
            ImGui::EndPopup();
        }
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
    artwork.clear();
    ImGui_ImplOpenGL3_Shutdown();
    ImGui_ImplSDL3_Shutdown();
    ImGui::DestroyContext();
    SDL_GL_DestroyContext(context);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}
