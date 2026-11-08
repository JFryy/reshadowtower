#pragma once
#include <exception>
#include "toml.hpp"
#include "psx_sha256.h"
#include "render_scale.h"
#include "settings_ranges.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <filesystem>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <limits>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace launcher {
namespace fs = std::filesystem;
// Inclusive bounds and default for one setting. Floating-point values must also be finite.
template <typename T> struct Range {
    T low, high, fallback;
    bool contains(T value) const {
        if constexpr (std::is_floating_point_v<T>) {
            if (!std::isfinite(value)) return false;
        }
        return value >= low && value <= high;
    }
};
inline constexpr Range<int> volumeRange{SHADOWTOWER_VOLUME_MIN, SHADOWTOWER_VOLUME_MAX, SHADOWTOWER_VOLUME_DEFAULT};
inline constexpr Range<int> scaleRange{1, SHADOWTOWER_MAX_INTERNAL_SCALE, 3};
inline constexpr int maxRenderScale = scaleRange.high;
inline constexpr Range<double> mouseSensitivityRange{SHADOWTOWER_MOUSE_SENSITIVITY_MIN,
    SHADOWTOWER_MOUSE_SENSITIVITY_MAX, SHADOWTOWER_MOUSE_SENSITIVITY_DEFAULT};
inline constexpr Range<double> stickSensitivityRange{SHADOWTOWER_STICK_SENSITIVITY_MIN,
    SHADOWTOWER_STICK_SENSITIVITY_MAX, SHADOWTOWER_STICK_SENSITIVITY_DEFAULT};
inline constexpr Range<double> stickDeadzoneRange{SHADOWTOWER_STICK_DEADZONE_MIN,
    SHADOWTOWER_STICK_DEADZONE_MAX, SHADOWTOWER_STICK_DEADZONE_DEFAULT};
inline constexpr Range<float> unitEffectRange{SHADOWTOWER_POSTFX_UNIT_MIN, SHADOWTOWER_POSTFX_UNIT_MAX, 0.f};
inline constexpr std::array<const char*, 4> fmvFilters = {"nearest", "bilinear", "sharp", "bicubic"};

struct PostFx {
    bool enabled = false;
    float exposure = SHADOWTOWER_POSTFX_EXPOSURE_DEFAULT, contrast = SHADOWTOWER_POSTFX_CONTRAST_DEFAULT;
    float saturation = SHADOWTOWER_POSTFX_SATURATION_DEFAULT, grain = 0, dither = 0;
    float bloom = 0, scanlines = 0, mask = 0, curvature = 0;
    bool fxaa = false;
    float sharpen = 0;
};
// Every adjustable post-processing strength: settings.toml key, UI label and format, and bounds.
struct PostFxField {
    const char* key;
    const char* label;
    const char* format;
    float PostFx::*member;
    Range<float> range;
};
inline constexpr std::array<PostFxField, 10> postFxFields = {{
    {"sharpen", "Adaptive sharpening", "%.2f", &PostFx::sharpen, unitEffectRange},
    {"exposure", "Exposure", "%+.2f stops", &PostFx::exposure,
     {SHADOWTOWER_POSTFX_EXPOSURE_MIN, SHADOWTOWER_POSTFX_EXPOSURE_MAX, SHADOWTOWER_POSTFX_EXPOSURE_DEFAULT}},
    {"contrast", "Contrast", "%.2fx", &PostFx::contrast,
     {SHADOWTOWER_POSTFX_CONTRAST_MIN, SHADOWTOWER_POSTFX_CONTRAST_MAX, SHADOWTOWER_POSTFX_CONTRAST_DEFAULT}},
    {"saturation", "Saturation", "%.2fx", &PostFx::saturation,
     {SHADOWTOWER_POSTFX_SATURATION_MIN, SHADOWTOWER_POSTFX_SATURATION_MAX, SHADOWTOWER_POSTFX_SATURATION_DEFAULT}},
    {"grain", "Film grain", "%.3f", &PostFx::grain, {SHADOWTOWER_POSTFX_GRAIN_MIN, SHADOWTOWER_POSTFX_GRAIN_MAX, 0.f}},
    {"dither", "Dithering", "%.2f", &PostFx::dither, unitEffectRange},
    {"bloom", "Bloom", "%.2f", &PostFx::bloom, unitEffectRange},
    {"scanlines", "Scanlines", "%.2f", &PostFx::scanlines, unitEffectRange},
    {"mask", "RGB mask", "%.2f", &PostFx::mask, unitEffectRange},
    {"curvature", "Curvature", "%.2f", &PostFx::curvature,
     {SHADOWTOWER_POSTFX_CURVATURE_MIN, SHADOWTOWER_POSTFX_CURVATURE_MAX, 0.f}},
}};
inline const PostFxField& postFxField(const char* key) {
    for (const auto& field : postFxFields)
        if (std::string_view(field.key) == key) return field;
    throw std::logic_error(std::string("Unknown post-processing field ") + key);
}

enum class PostFxPreset { original, subtle, crt, custom };
// The values each named preset applies; detection compares against the same table.
inline PostFx postFxPresetValues(PostFxPreset preset) {
    PostFx p;
    switch (preset) {
    case PostFxPreset::subtle:
        p.enabled = true; p.contrast = 1.05f; p.saturation = .9f;
        p.grain = .015f; p.dither = .1f; p.bloom = .08f; break;
    case PostFxPreset::crt:
        p.enabled = true; p.contrast = 1.05f; p.grain = .02f; p.dither = .25f;
        p.bloom = .08f; p.scanlines = .3f; p.mask = .15f; p.curvature = .04f; break;
    case PostFxPreset::original:
    case PostFxPreset::custom: break;
    }
    return p;
}
inline bool samePostFx(const PostFx& a, const PostFx& b) {
    if (a.enabled != b.enabled || a.fxaa != b.fxaa) return false;
    for (const auto& field : postFxFields)
        if (a.*field.member != b.*field.member) return false;
    return true;
}
inline PostFxPreset postFxPreset(const PostFx& p) {
    for (const auto preset : {PostFxPreset::original, PostFxPreset::subtle, PostFxPreset::crt})
        if (samePostFx(p, postFxPresetValues(preset))) return preset;
    return PostFxPreset::custom;
}
inline void applyPostFxPreset(PostFx& p, PostFxPreset preset) {
    if (preset != PostFxPreset::custom) p = postFxPresetValues(preset);
}

struct Settings {
    int wideRatio = 0, scale = scaleRange.fallback, volume = volumeRange.fallback, fmvFilter = 0;
    bool outputFiltering = false;
    bool widescreen = false, fullscreen = false, filter = true, geometry = true, perspective = true;
    bool vsync = true, lowLatency = true;
    double mouseSensitivity = mouseSensitivityRange.fallback;
    double stickSensitivity = stickSensitivityRange.fallback, stickDeadzone = stickDeadzoneRange.fallback;
    PostFx postFx;
};
// Name the first out-of-range setting, or return an empty string when all are valid.
inline std::string invalidSetting(const Settings& s) {
    const auto describe = [](const char* name, auto value, auto low, auto high) {
        std::ostringstream out;
        out.imbue(std::locale::classic());
        out << name << " is " << value << "; allowed range is " << low << " to " << high;
        return out.str();
    };
    if (s.wideRatio < 0 || s.wideRatio > 1) return describe("Aspect ratio", s.wideRatio, 0, 1);
    if (!scaleRange.contains(s.scale)) return describe("Resolution scale", s.scale, scaleRange.low, scaleRange.high);
    if (s.fmvFilter < 0 || s.fmvFilter >= static_cast<int>(fmvFilters.size()))
        return describe("FMV filtering", s.fmvFilter, 0, fmvFilters.size() - 1);
    if (!volumeRange.contains(s.volume)) return describe("Volume", s.volume, volumeRange.low, volumeRange.high);
    const std::pair<const char*, std::pair<double, Range<double>>> doubles[] = {
        {"Mouse sensitivity", {s.mouseSensitivity, mouseSensitivityRange}},
        {"Stick sensitivity", {s.stickSensitivity, stickSensitivityRange}},
        {"Stick deadzone", {s.stickDeadzone, stickDeadzoneRange}},
    };
    for (const auto& [name, entry] : doubles)
        if (!entry.second.contains(entry.first)) return describe(name, entry.first, entry.second.low, entry.second.high);
    for (const auto& field : postFxFields)
        if (!field.range.contains(s.postFx.*field.member))
            return describe(field.label, s.postFx.*field.member, field.range.low, field.range.high);
    return {};
}
// Translate launcher preferences into overrides consumed by the game runtime.
inline std::array<std::pair<std::string, std::string>, 9> gameEnvironment(const Settings& s) {
    std::string postFx = "0";
    if (s.postFx.enabled) {
        std::ostringstream out;
        out.imbue(std::locale::classic());
        out << std::setprecision(std::numeric_limits<float>::max_digits10)
            << "1," << s.postFx.exposure << ',' << s.postFx.contrast << ','
            << s.postFx.saturation << ',' << s.postFx.grain << ',' << s.postFx.dither
            << ',' << s.postFx.bloom << ',' << s.postFx.scanlines << ','
            << s.postFx.mask << ',' << s.postFx.curvature;
        postFx = out.str();
    }
    return {{{"SHADOWTOWER_VOLUME", std::to_string(s.volume)},
             {"PSX_VSYNC", s.vsync ? "1" : "0"},
             {"PSX_LOW_LATENCY_INPUT", s.lowLatency ? "1" : "0"},
             {"SHADOWTOWER_MOUSE_SENSITIVITY", std::to_string(s.mouseSensitivity)},
             {"SHADOWTOWER_POSTFX", postFx},
             {"SHADOWTOWER_FXAA", s.postFx.enabled && s.postFx.fxaa ? "1" : "0"},
             {"SHADOWTOWER_SHARPEN", s.postFx.enabled ? std::to_string(s.postFx.sharpen) : "0"},
             {"SHADOWTOWER_STICK_SENSITIVITY", std::to_string(s.stickSensitivity)},
             {"SHADOWTOWER_STICK_DEADZONE", std::to_string(s.stickDeadzone)}}};
}
// Presets alter only graphics quality; custom values and display preferences survive.
enum class GraphicsPreset { performance, balanced, quality, custom };
struct GraphicsPresetValues {
    GraphicsPreset preset;
    int scale;
    bool filter, geometry, perspective;
};
inline constexpr std::array<GraphicsPresetValues, 3> graphicsPresets = {{
    {GraphicsPreset::performance, 1, false, false, false},
    {GraphicsPreset::balanced, 2, true, true, false},
    {GraphicsPreset::quality, 4, true, true, true},
}};
inline GraphicsPreset graphicsPreset(const Settings& s) {
    for (const auto& values : graphicsPresets)
        if (s.scale == values.scale && s.filter == values.filter && s.geometry == values.geometry &&
            s.perspective == values.perspective) return values.preset;
    return GraphicsPreset::custom;
}
inline void applyGraphicsPreset(Settings& s, GraphicsPreset preset) {
    for (const auto& values : graphicsPresets) {
        if (values.preset != preset) continue;
        s.scale = values.scale;
        s.filter = values.filter;
        s.geometry = values.geometry;
        s.perspective = values.perspective;
    }
}
// Parse through a filesystem-aware stream so Unicode Windows paths work.
inline toml::value parse(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("Cannot read " + path.u8string());
    return toml::parse(input, path.u8string());
}
inline void overlay(Settings& s, const toml::value& root) {
    if (root.contains("video") && root.at("video").is_table()) {
        const auto& v = root.at("video");
        auto str = [&](const char* key, const char* fallback) { return toml::find_or<std::string>(v, key, fallback); };
        if (v.contains("aspect_ratio")) {
            const auto aspect = str("aspect_ratio", "4:3");
            s.widescreen = aspect == "16:9" || aspect == "21:9";
            if (s.widescreen) s.wideRatio = aspect == "21:9" ? 1 : 0;
        }
        const int scale = toml::find_or(v, "supersampling", s.scale);
        if (scaleRange.contains(scale)) s.scale = scale;
        s.fullscreen = toml::find_or(v, "fullscreen", s.fullscreen);
        s.outputFiltering = toml::find_or(v, "antialiasing", s.outputFiltering);
        const auto fmv = str("fmv_filter", fmvFilters[s.fmvFilter]);
        for (size_t i = 0; i < fmvFilters.size(); ++i)
            if (fmv == fmvFilters[i]) s.fmvFilter = static_cast<int>(i);
        const auto filter = str("texture_filtering", s.filter ? "bilinear" : "nearest");
        if (filter == "bilinear" || filter == "nearest") s.filter = filter == "bilinear";
        s.geometry = toml::find_or(v, "geometry_correction", s.geometry);
        s.perspective = toml::find_or(v, "perspective_texturing", s.perspective);
    }
    if (!s.widescreen && root.contains("launcher") && root.at("launcher").is_table()) {
        const auto ratio = toml::find_or<std::string>(root.at("launcher"), "widescreen_ratio", "16:9");
        if (ratio == "16:9" || ratio == "21:9") s.wideRatio = ratio == "21:9" ? 1 : 0;
    }
    if (root.contains("launcher") && root.at("launcher").is_table()) {
        const auto& options = root.at("launcher");
        s.vsync = toml::find_or(options, "vsync", s.vsync);
        s.lowLatency = toml::find_or(options, "low_latency", s.lowLatency);
        const auto ranged = [&](const char* key, double& target, const Range<double>& range) {
            const double value = toml::find_or(options, key, target);
            if (range.contains(value)) target = value;
        };
        ranged("mouse_sensitivity", s.mouseSensitivity, mouseSensitivityRange);
        ranged("stick_sensitivity", s.stickSensitivity, stickSensitivityRange);
        ranged("stick_deadzone", s.stickDeadzone, stickDeadzoneRange);
    }
    if (root.contains("post_processing") && root.at("post_processing").is_table()) {
        const auto& p = root.at("post_processing");
        s.postFx.enabled = toml::find_or(p, "enabled", s.postFx.enabled);
        s.postFx.fxaa = toml::find_or(p, "fxaa", s.postFx.fxaa);
        for (const auto& field : postFxFields) {
            float& target = s.postFx.*field.member;
            const double value = toml::find_or(p, field.key, static_cast<double>(target));
            if (std::isfinite(value) && value >= field.range.low && value <= field.range.high)
                target = static_cast<float>(value);
        }
    }
    if (root.contains("audio") && root.at("audio").is_table()) {
        const int volume = toml::find_or(root.at("audio"), "volume", s.volume);
        if (volumeRange.contains(volume)) s.volume = volume;
    }
}
// Layer user preferences over the title's defaults.
inline Settings load(const fs::path& workspace) {
    Settings s;
    overlay(s, parse(workspace / "game.toml"));
    const auto file = workspace / "build-release/settings.toml";
    if (fs::exists(file)) overlay(s, parse(file));
    return s;
}
// Move an unparseable settings.toml aside so defaults load and Play stays usable.
// Returns a notice for the user, or an empty string when the file was fine or absent.
inline std::string setAsideCorruptSettings(const fs::path& workspace) {
    const auto file = workspace / "build-release/settings.toml";
    if (!fs::exists(file)) return {};
    std::string error;
    try {
        parse(file);
        return {};
    } catch (const toml::syntax_error& e) {
        error = e.what();
    }
    auto aside = file;
    aside += ".corrupt-" + std::to_string(std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::system_clock::now().time_since_epoch()).count());
    fs::rename(file, aside);
    return "settings.toml could not be parsed, so it was moved to " + aside.filename().u8string() +
           " and defaults were loaded.\n" + error;
}
// Read a setup stage marker ("[setup 2/3] Generating game code") written by
// tools/launcher_backend.py. Returns the status text, or empty for other lines.
inline std::string setupStage(std::string_view line) {
    while (!line.empty() && (line.back() == '\r' || line.back() == '\n')) line.remove_suffix(1);
    constexpr std::string_view prefix = "[setup ";
    if (line.substr(0, prefix.size()) != prefix) return {};
    line.remove_prefix(prefix.size());
    const auto slash = line.find('/');
    const auto close = line.find("] ");
    if (slash == std::string_view::npos || close == std::string_view::npos || slash == 0 || slash + 1 >= close)
        return {};
    const auto digits = [](std::string_view text) {
        return std::all_of(text.begin(), text.end(), [](char c) { return c >= '0' && c <= '9'; });
    };
    const auto step = line.substr(0, slash), total = line.substr(slash + 1, close - slash - 1);
    const auto label = line.substr(close + 2);
    if (!digits(step) || !digits(total) || label.empty()) return {};
    return std::string(step) + " / " + std::string(total) + "  " + std::string(label);
}
// Replace only launcher-owned preferences, preserving other TOML fields.
inline void save(const fs::path& workspace, const Settings& s) {
    if (const auto problem = invalidSetting(s); !problem.empty())
        throw std::invalid_argument("Cannot save settings: " + problem + ".");
    const auto file = workspace / "build-release/settings.toml";
    toml::value doc = fs::exists(file) ? parse(file) : toml::value(toml::table{});
    if (!doc.contains("video")) doc["video"] = toml::table{};
    if (!doc.contains("audio")) doc["audio"] = toml::table{};
    if (!doc.contains("launcher")) doc["launcher"] = toml::table{};
    if (!doc.contains("post_processing")) doc["post_processing"] = toml::table{};
    auto& v = doc["video"];
    v["renderer"] = "opengl";
    const char* ratio = s.wideRatio == 1 ? "21:9" : "16:9";
    v["aspect_ratio"] = s.widescreen ? ratio : "4:3";
    doc["launcher"]["widescreen_ratio"] = ratio;
    doc["launcher"]["vsync"] = s.vsync;
    doc["launcher"]["low_latency"] = s.lowLatency;
    doc["launcher"]["mouse_sensitivity"] = s.mouseSensitivity;
    doc["launcher"]["stick_sensitivity"] = s.stickSensitivity;
    doc["launcher"]["stick_deadzone"] = s.stickDeadzone;
    v["supersampling"] = s.scale;
    v["fullscreen"] = s.fullscreen;
    v["antialiasing"] = s.outputFiltering;
    v["fmv_filter"] = fmvFilters[s.fmvFilter];
    v["texture_filtering"] = s.filter ? "bilinear" : "nearest";
    v["geometry_correction"] = s.geometry;
    v["perspective_texturing"] = s.perspective;
    doc["audio"]["volume"] = s.volume;
    auto& p = doc["post_processing"];
    p["enabled"] = s.postFx.enabled;
    p["fxaa"] = s.postFx.fxaa;
    for (const auto& field : postFxFields) p[field.key] = static_cast<double>(s.postFx.*field.member);
    fs::create_directories(file.parent_path());
    auto temporary = file;
    temporary += ".tmp";
    try {
        { std::ofstream out(temporary, std::ios::binary | std::ios::trunc);
          out.exceptions(std::ios::badbit | std::ios::failbit);
          out << toml::format(doc) << '\n'; out.close(); }
#ifdef _WIN32
        if (!MoveFileExW(temporary.c_str(), file.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
            throw std::system_error(GetLastError(), std::system_category(), "Cannot replace settings.toml");
#else
        fs::rename(temporary, file);
#endif
    } catch (...) {
        std::error_code cleanupError;
        fs::remove(temporary, cleanupError);
        throw;
    }
}
inline fs::path executable(const fs::path& workspace) {
#ifdef _WIN32
    return workspace / "build-release/Shadow_Tower_Recompiled.exe";
#else
    return workspace / "build-release/Shadow_Tower_Recompiled";
#endif
}
// A build is playable only after setup records its executable's exact digest.
inline bool ready(const fs::path& workspace) {
    std::ifstream stamp(workspace / ".build-ready");
    std::string expected;
    if (!(stamp >> expected) || expected.size() != 64 ||
        !std::all_of(expected.begin(), expected.end(), [](char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); })) return false;
    std::ifstream file(executable(workspace), std::ios::binary);
    if (!file) return false;
    psx_sha256_ctx ctx;
    psx_sha256_init(&ctx);
    std::array<char, 65536> buffer{};
    while (file) {
        file.read(buffer.data(), buffer.size());
        psx_sha256_update(&ctx, reinterpret_cast<const uint8_t*>(buffer.data()), static_cast<size_t>(file.gcount()));
    }
    if (!file.eof()) return false;
    uint8_t digest[32]; psx_sha256_final(&ctx, digest);
    constexpr char hex[] = "0123456789abcdef";
    std::string actual;
    for (auto byte : digest) { actual += hex[byte >> 4]; actual += hex[byte & 15]; }
    return expected == actual;
}
}
