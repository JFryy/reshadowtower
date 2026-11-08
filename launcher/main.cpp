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
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include "model.hpp"
#include "artwork.hpp"
#include "bindings.hpp"
#include <filesystem>

using launcher::Settings;
struct Result { int code = -1; std::string text; };
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

// Runs one launcher action (setup, play or save) on a worker thread and hands back its result.
class ActionRunner {
public:
    struct Completion { std::string action; Result result; };
    ActionRunner(std::string python, std::string backend, std::string workspace)
        : python_(std::move(python)), backend_(std::move(backend)), workspace_(std::move(workspace)),
          workspacePath_(std::filesystem::u8path(workspace_)) {}
    ActionRunner(const ActionRunner&) = delete;
    ActionRunner& operator=(const ActionRunner&) = delete;
    ~ActionRunner() { if (worker_.joinable()) worker_.join(); }

    bool busy() {
        std::lock_guard<std::mutex> lock(mutex_);
        return busy_;
    }
    std::string action() {
        std::lock_guard<std::mutex> lock(mutex_);
        return action_;
    }
    // The worker uses copies of settings and bindings taken now, never the live UI state.
    void start(const std::string& action, const Settings& settings, const launcher::Bindings& bindings,
               std::vector<std::string> args = {}) {
        if (worker_.joinable()) worker_.join();
        {
            std::lock_guard<std::mutex> lock(mutex_);
            busy_ = true;
            completed_ = false;
            action_ = action;
        }
        worker_ = std::thread([this, action, args = std::move(args), settings, bindings] {
            Result result;
            try { result = perform(action, args, settings, bindings); }
            catch (const std::exception& e) { result = {-1, e.what()}; }
            std::lock_guard<std::mutex> lock(mutex_);
            result_ = std::move(result);
            completed_ = true;
        });
    }
    // Returns a finished action once and clears the busy state.
    std::optional<Completion> takeCompletion() {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!completed_) return std::nullopt;
        completed_ = false;
        busy_ = false;
        return Completion{action_, result_};
    }

private:
    Result perform(const std::string& action, const std::vector<std::string>& args, const Settings& settings,
                   const launcher::Bindings& bindings) const {
        if (action == "setup") {
            std::vector<std::string> command{python_, backend_, "--workspace", workspace_};
            command.insert(command.end(), args.begin(), args.end());
            Result result = run(command, workspace_);
            if (result.code == 0 && !launcher::ready(workspacePath_)) return {-1, "Setup finished but build is not ready"};
            return result;
        }
        if (action == "play") {
            if (!launcher::ready(workspacePath_)) return {-1, "Build is missing or changed"};
            launcher::save(workspacePath_, settings);
            launcher::saveBindings(workspacePath_, bindings);
            return run({launcher::executable(workspacePath_).u8string(), "--no-launcher", "--game",
                        (workspacePath_ / "game.toml").u8string()}, workspace_, &settings);
        }
        launcher::save(workspacePath_, settings);
        launcher::saveBindings(workspacePath_, bindings);
        return {0, "Settings saved"};
    }

    const std::string python_, backend_, workspace_;
    const std::filesystem::path workspacePath_;
    std::mutex mutex_;
    bool busy_ = false, completed_ = false;
    std::string action_;
    Result result_;
    std::thread worker_;
};

// Follows the setup stage markers the backend writes to launcher-process.log.
struct SetupProgress {
    std::filesystem::path log;
    std::streamoff start = 0;
    Uint64 updated = 0;
    std::string stage;

    void begin() {
        std::ifstream input(log, std::ios::binary | std::ios::ate);
        start = input ? static_cast<std::streamoff>(input.tellg()) : 0;
        stage = "Starting setup";
    }
    void poll() {
        if (SDL_GetTicks() - updated <= 300) return;
        updated = SDL_GetTicks();
        std::ifstream input(log, std::ios::binary);
        if (!input) return;
        input.seekg(start);
        std::string line;
        while (std::getline(input, line))
            if (auto parsed = launcher::setupStage(line); !parsed.empty()) stage = std::move(parsed);
    }
};

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

// Disc and BIOS paths for setup, filled by typing or by asynchronous file dialogs.
struct SetupForm {
    std::array<char, 4096> disc{}, bios{};
    BrowseResult discBrowse, biosBrowse;
    int dialogs = 0;

    void applyBrowseResults(std::string& message) {
        apply(discBrowse, disc, message);
        apply(biosBrowse, bios, message);
    }

private:
    void apply(BrowseResult& result, std::array<char, 4096>& path, std::string& message) {
        std::lock_guard<std::mutex> lock(result.mutex);
        if (!result.pending) return;
        if (result.selected.size() >= path.size()) message = "Selected path is too long. Move the disc to a shorter path.";
        else if (!result.selected.empty()) SDL_strlcpy(path.data(), result.selected.c_str(), path.size());
        if (!result.error.empty()) { message = result.error; result.error.clear(); }
        result.pending = false;
        --dialogs;
    }
};

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

// State every settings page reads; dirty is set when a page changes a setting.
struct PageContext {
    Settings& settings;
    bool& dirty;
    bool settingsLoaded;
    bool ready;
    float uiScale;
};

static void drawArtwork(const Artwork& artwork, float uiScale) {
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
}

// Returns true when the player pressed Play.
static bool drawPlayPage(const PageContext& ui, const Artwork& artwork) {
    ImGui::TextUnformatted("Return to the depths.");
    hint("Shadow Tower, running natively on your PC.");
    ImGui::Spacing();
    drawArtwork(artwork, ui.uiScale);
    ImGui::BeginDisabled(!ui.ready || !ui.settingsLoaded);
    const bool play = ImGui::Button("Play game", ImVec2(170 * ui.uiScale, 44 * ui.uiScale));
    ImGui::EndDisabled();
    if (!ui.ready) hint("Use Disc setup to verify your disc and install the game.");
    else hint(ui.settings.widescreen ? "Wider 3D view. HUD and menus stretch to fill." : "Original 4:3 presentation.");
    return play;
}

static void effectSlider(const PageContext& ui, const char* key) {
    const auto& field = launcher::postFxField(key);
    ImGui::SetNextItemWidth(210 * ui.uiScale);
    ui.dirty |= ImGui::SliderFloat(field.label, &(ui.settings.postFx.*field.member), field.range.low, field.range.high,
                                   field.format, ImGuiSliderFlags_AlwaysClamp);
}

static void drawPostProcessing(const PageContext& ui) {
    auto& fx = ui.settings.postFx;
    ui.dirty |= ImGui::Checkbox("Enable post-processing", &fx.enabled);
    hint("Off by default. Effects apply to the whole game image, including its HUD and menus, on the next launch.");
    int effectPreset = static_cast<int>(launcher::postFxPreset(fx));
    ImGui::SetNextItemWidth(210 * ui.uiScale);
    if (ImGui::Combo("Effect preset", &effectPreset, "Original (off)\0Subtle\0CRT\0Custom\0")) {
        launcher::applyPostFxPreset(fx, static_cast<launcher::PostFxPreset>(effectPreset));
        ui.dirty = true;
    }
    ImGui::BeginDisabled(!fx.enabled);
    ImGui::TextUnformatted("Anti-aliasing and detail");
    ui.dirty |= ImGui::Checkbox("FXAA", &fx.fxaa);
    effectSlider(ui, "sharpen");
    hint("FXAA smooths image edges. Sharpening restores local contrast; both also affect text and menus.");
    ImGui::TextUnformatted("Color grading");
    effectSlider(ui, "exposure");
    effectSlider(ui, "contrast");
    effectSlider(ui, "saturation");
    ImGui::TextUnformatted("Texture and glow");
    effectSlider(ui, "grain");
    effectSlider(ui, "dither");
    effectSlider(ui, "bloom");
    hint("Zero disables each effect. Bloom adds a subtle glow around bright pixels; it is not HDR lighting.");
    ImGui::TextUnformatted("CRT presentation");
    effectSlider(ui, "scanlines");
    effectSlider(ui, "mask");
    effectSlider(ui, "curvature");
    ImGui::EndDisabled();
}

static void drawGraphicsPage(const PageContext& ui) {
    auto& settings = ui.settings;
    ImGui::BeginDisabled(!ui.settingsLoaded);
    ImGui::TextUnformatted("Graphics");
    hint("Changes apply the next time you launch the game.");
    ImGui::Spacing();
    ui.dirty |= ImGui::Checkbox("Widescreen (experimental)", &settings.widescreen);
    ImGui::BeginDisabled(!settings.widescreen);
    ImGui::SetNextItemWidth(160 * ui.uiScale);
    ui.dirty |= ImGui::Combo("Aspect ratio", &settings.wideRatio, "16:9\0" "21:9\0");
    ImGui::EndDisabled();
    hint(settings.widescreen ? "Wider 3D projection into the original-width framebuffer. HUD and menus stretch to fill. Increase resolution scale for a sharper image." : "Original 4:3 presentation. Your wide-ratio preference is remembered.");
    int displayMode = settings.fullscreen ? 1 : 0;
    ImGui::SetNextItemWidth(210 * ui.uiScale);
    if (ImGui::Combo("Display mode", &displayMode, "Windowed\0Fullscreen (desktop)\0")) {
        settings.fullscreen = displayMode == 1;
        ui.dirty = true;
    }
    int preset = static_cast<int>(launcher::graphicsPreset(settings));
    ImGui::SetNextItemWidth(210 * ui.uiScale);
    if (ImGui::Combo("Quality preset", &preset, "Original / performance\0Balanced\0High quality\0Custom\0")) {
        launcher::applyGraphicsPreset(settings, static_cast<launcher::GraphicsPreset>(preset));
        ui.dirty = true;
    }
    ImGui::SetNextItemWidth(210 * ui.uiScale);
    ui.dirty |= ImGui::SliderInt("Resolution scale", &settings.scale, launcher::scaleRange.low, launcher::scaleRange.high,
                                 "%dx", ImGuiSliderFlags_AlwaysClamp);
    hint("Scales above 4x consume quadratically more GPU memory; hardware may fall back to a lower scale.");
    ui.dirty |= ImGui::Checkbox("World texture filtering", &settings.filter);
    ImGui::SetNextItemWidth(210 * ui.uiScale);
    int outputFilter = settings.outputFiltering ? 1 : 0;
    if (ImGui::Combo("Output filtering", &outputFilter, "Nearest\0Linear\0")) {
        settings.outputFiltering = outputFilter == 1;
        ui.dirty = true;
    }
    ImGui::BeginDisabled(!settings.outputFiltering);
    ImGui::SetNextItemWidth(210 * ui.uiScale);
    ui.dirty |= ImGui::Combo("FMV filtering", &settings.fmvFilter, "Nearest\0Bilinear\0Sharp\0Bicubic\0");
    ImGui::EndDisabled();
    hint("FMV filtering requires linear output filtering. Your FMV choice is remembered when output filtering is off.");
    ui.dirty |= ImGui::Checkbox("Geometry correction", &settings.geometry);
    ui.dirty |= ImGui::Checkbox("Perspective-correct textures", &settings.perspective);
    if (ImGui::CollapsingHeader("Frame pacing")) {
        ui.dirty |= ImGui::Checkbox("VSync", &settings.vsync);
        hint("Synchronize presentation when the display timing supports it. The runtime uses its own pacer otherwise; disabling this does not unlock game speed.");
        ui.dirty |= ImGui::Checkbox("Low-latency input", &settings.lowLatency);
        hint("Poll input closer to the game's input read to reduce delay.");
    }
    if (ImGui::CollapsingHeader("Post-processing")) drawPostProcessing(ui);
    ImGui::EndDisabled();
}

static void drawAudioPage(const PageContext& ui) {
    ImGui::BeginDisabled(!ui.settingsLoaded);
    ImGui::TextUnformatted("Audio");
    hint("Master volume for the game. Changes apply on the next launch.");
    ImGui::Spacing();
    ImGui::SetNextItemWidth(250 * ui.uiScale);
    ui.dirty |= ImGui::SliderInt("Volume", &ui.settings.volume, launcher::volumeRange.low, launcher::volumeRange.high,
                                 "%d%%", ImGuiSliderFlags_AlwaysClamp);
    ImGui::EndDisabled();
}

// Edit a double-valued setting with a float slider; scale converts stored values to displayed ones.
static void rangeSlider(const PageContext& ui, const char* label, double& value, const launcher::Range<double>& range,
                        const char* format, ImGuiSliderFlags flags, double scale = 1) {
    float shown = static_cast<float>(value * scale);
    ImGui::SetNextItemWidth(230 * ui.uiScale);
    if (ImGui::SliderFloat(label, &shown, static_cast<float>(range.low * scale), static_cast<float>(range.high * scale),
                           format, flags | ImGuiSliderFlags_AlwaysClamp)) {
        value = static_cast<double>(shown) / scale;
        ui.dirty = true;
    }
}

static void drawBindings(const PageContext& ui, launcher::Bindings& bindings) {
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
                        ui.dirty = true;
                    }
                    if (selected) ImGui::SetItemDefaultFocus();
                }
                ImGui::EndCombo();
            }
            ImGui::PopID();
        }
        ImGui::EndTable();
    }
    if (ImGui::Button("Restore default controller bindings")) { bindings = launcher::Bindings{}; ui.dirty = true; }
}

static void drawControlsPage(const PageContext& ui, launcher::Bindings& bindings) {
    auto& settings = ui.settings;
    ImGui::BeginDisabled(!ui.settingsLoaded);
    ImGui::TextUnformatted("Controls");
    hint("Keyboard and mouse, or a connected controller.");
    ImGui::Spacing();
    ImGui::TextWrapped("W / S  Move forward / back\nA / D  Strafe\nE  Interact\nF  Attack\nTab  Open menu\nC  Back / cancel");
    ImGui::Spacing();
    hint("Click the game window to capture the mouse. Escape releases it.");
    rangeSlider(ui, "Mouse sensitivity", settings.mouseSensitivity, launcher::mouseSensitivityRange, "%.2fx",
                ImGuiSliderFlags_Logarithmic);
    if (ImGui::Button("Reset mouse sensitivity")) {
        settings.mouseSensitivity = launcher::mouseSensitivityRange.fallback;
        ui.dirty = true;
    }
    ImGui::Spacing();
    hint("On a controller, the right stick turns and looks up and down.");
    rangeSlider(ui, "Stick sensitivity", settings.stickSensitivity, launcher::stickSensitivityRange, "%.2fx",
                ImGuiSliderFlags_Logarithmic);
    rangeSlider(ui, "Stick deadzone", settings.stickDeadzone, launcher::stickDeadzoneRange, "%.0f%%",
                ImGuiSliderFlags_None, 100);
    if (ImGui::Button("Reset stick settings")) {
        settings.stickSensitivity = launcher::stickSensitivityRange.fallback;
        settings.stickDeadzone = launcher::stickDeadzoneRange.fallback;
        ui.dirty = true;
    }
    if (ImGui::CollapsingHeader("Controller bindings")) drawBindings(ui, bindings);
    ImGui::EndDisabled();
}

// Returns the backend arguments when the player starts setup.
static std::optional<std::vector<std::string>> drawSetupPage(const PageContext& ui, SetupForm& form, SDL_Window* window) {
    ImGui::TextUnformatted("Disc setup");
    hint("Use your Shadow Tower disc image. Verification and installation run locally, without downloads.");
    hint("Accepted images:");
    hint("  - Shadow Tower (USA), SLUS-00863");
    hint("  - Shadow Tower (USA) with the UNDUB v1.0 patch applied");
    ImGui::Spacing();
    ImGui::TextUnformatted("Disc image");
    ImGui::SetNextItemWidth(-120 * ui.uiScale);
    ImGui::InputText("##Disc path", form.disc.data(), form.disc.size());
    ImGui::SameLine();
    if (ImGui::Button("Browse##disc")) {
        ++form.dialogs;
        static const SDL_DialogFileFilter filters[] = {{"Disc images", "cue;bin;iso;chd"}};
        SDL_ShowOpenFileDialog(browseCallback, &form.discBrowse, window, filters, 1, nullptr, false);
    }
    ImGui::TextUnformatted("BIOS (optional)");
    ImGui::SetNextItemWidth(-120 * ui.uiScale);
    ImGui::InputText("##BIOS path", form.bios.data(), form.bios.size());
    ImGui::SameLine();
    if (ImGui::Button("Browse##bios")) {
        ++form.dialogs;
        SDL_ShowOpenFileDialog(browseCallback, &form.biosBrowse, window, nullptr, 0, nullptr, false);
    }
    hint("Leave blank to use bundled OpenBIOS. Existing saves are not removed.");
    ImGui::Spacing();
    std::optional<std::vector<std::string>> args;
    ImGui::BeginDisabled(!form.disc[0]);
    if (ImGui::Button(ui.ready ? "Rebuild game" : "Install game", ImVec2(170 * ui.uiScale, 44 * ui.uiScale))) {
        args = std::vector<std::string>{"setup", "--disc", form.disc.data()};
        if (form.bios[0]) { args->push_back("--bios"); args->push_back(form.bios.data()); }
    }
    ImGui::EndDisabled();
    hint("Setup progress and detailed errors are recorded in launcher-actions.log.");
    return args;
}

static void drawNavigation(int& page, bool ready, bool dirty, float uiScale, float footerHeight) {
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
}

static void drawStatus(bool busy, const std::string& action, const std::string& setupStage, const std::string& message) {
    ImGui::BeginChild("Status", ImVec2(0, 0));
    if (busy) {
        const char* frames[] = {".  ", ".. ", "..."};
        ImGui::Text("%s%s", action == "setup" ? setupStage.c_str() : action == "play" ? "Game running" : "Saving",
                    frames[static_cast<int>(ImGui::GetTime() * 3) % 3]);
    } else if (!message.empty()) ImGui::TextWrapped("%s", message.c_str());
    else hint("Settings save automatically when you press Play.");
    ImGui::EndChild();
}

enum class CloseChoice { none, saveAndClose, discard };
static CloseChoice drawCloseDialog(bool& confirmClose) {
    if (confirmClose) { ImGui::OpenPopup("Unsaved changes"); confirmClose = false; }
    CloseChoice choice = CloseChoice::none;
    if (ImGui::BeginPopupModal("Unsaved changes", nullptr, ImGuiWindowFlags_AlwaysAutoResize)) {
        ImGui::TextUnformatted("Save your settings before closing?");
        if (ImGui::Button("Save and close")) { choice = CloseChoice::saveAndClose; ImGui::CloseCurrentPopup(); }
        ImGui::SameLine();
        if (ImGui::Button("Discard")) { choice = CloseChoice::discard; ImGui::CloseCurrentPopup(); }
        ImGui::SameLine();
        if (ImGui::Button("Cancel")) ImGui::CloseCurrentPopup();
        ImGui::EndPopup();
    }
    return choice;
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
    try {
        message = launcher::setAsideCorruptSettings(workspacePath);
        settings = launcher::load(workspacePath);
        bindings = launcher::loadBindings(workspacePath);
    }
    catch (const std::exception& e) {
        settingsLoaded = false;
        if (!message.empty()) message += "\n";
        message += "Cannot load preferences. Correct the reported file and restart.\n" + std::string(e.what());
    }
    bool ready = launcher::ready(workspacePath), running = true;
    int page = ready ? 0 : 4;
    bool dirty = false, confirmClose = false, closeAfterSave = false;
    SetupForm form;
    Artwork artwork;
    try {
        artwork.load(workspacePath / "assets/setup/boxart.tga");
    } catch (const std::exception& error) {
        if (!message.empty()) message += "\n";
        message += error.what();
    }
    {
        ActionRunner runner(python, backend, workspace);
        SetupProgress progress{workspacePath / "launcher-process.log"};
        const auto start = [&](const std::string& action, std::vector<std::string> args = {}) {
            if (action == "setup") progress.begin();
            runner.start(action, settings, bindings, std::move(args));
        };
        while (running) {
            SDL_Event event;
            while (SDL_PollEvent(&event)) {
                if (event.type == SDL_EVENT_QUIT || event.type == SDL_EVENT_WINDOW_CLOSE_REQUESTED) {
                    if (!runner.busy() && !form.dialogs) {
                        if (dirty) confirmClose = true;
                        else running = false;
                    }
                    continue;
                }
                ImGui_ImplSDL3_ProcessEvent(&event);
            }
            if (const auto done = runner.takeCompletion()) {
                const Result& result = done->result;
                if (closeAfterSave) {
                    if (result.code == 0) running = false;
                    closeAfterSave = false;
                }
                if (result.code == 0 && done->action != "setup") dirty = false;
                if (done->action == "setup") ready = launcher::ready(workspacePath);
                message = result.text.empty() ? (result.code == 0 ? "Done" : "Action failed") : result.text;
                if (result.code != 0 && done->action == "setup")
                    message += "\nSetup details: " + workspace + "/launcher-actions.log";
            }
            const bool busy = runner.busy();
            const std::string action = runner.action();
            form.applyBrowseResults(message);
            if (busy && action == "setup") progress.poll();

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
            drawNavigation(page, ready, dirty, uiScale, footerHeight);
            ImGui::SameLine();
            ImGui::BeginChild("Content", ImVec2(0, -footerHeight), ImGuiChildFlags_Borders);
            ImGui::BeginDisabled(busy || form.dialogs != 0);
            const PageContext ui{settings, dirty, settingsLoaded, ready, uiScale};
            switch (page) {
            case 0: if (drawPlayPage(ui, artwork)) start("play"); break;
            case 1: drawGraphicsPage(ui); break;
            case 2: drawAudioPage(ui); break;
            case 3: drawControlsPage(ui, bindings); break;
            default:
                if (auto args = drawSetupPage(ui, form, window)) start("setup", std::move(*args));
                break;
            }
            ImGui::EndDisabled();
            ImGui::EndChild();
            ImGui::Separator();
            ImGui::BeginDisabled(busy || form.dialogs != 0 || !settingsLoaded || !dirty);
            if (ImGui::Button("Save settings")) start("save");
            ImGui::EndDisabled();
            ImGui::SameLine();
            drawStatus(busy, action, progress.stage, message);
            ImGui::End();
            switch (drawCloseDialog(confirmClose)) {
            case CloseChoice::saveAndClose: closeAfterSave = true; start("save"); break;
            case CloseChoice::discard: running = false; break;
            case CloseChoice::none: break;
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
    }
    artwork.clear();
    ImGui_ImplOpenGL3_Shutdown();
    ImGui_ImplSDL3_Shutdown();
    ImGui::DestroyContext();
    SDL_GL_DestroyContext(context);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}
