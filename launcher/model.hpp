#pragma once
#include <exception>
#include "toml.hpp"
#include "psx_sha256.h"
#include <algorithm>
#include <array>
#include <filesystem>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <limits>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace launcher {
namespace fs = std::filesystem;
struct PostFx {
    bool enabled = false;
    float exposure = 0, contrast = 1, saturation = 1, grain = 0, dither = 0;
    float bloom = 0, scanlines = 0, mask = 0, curvature = 0;
};
inline bool validPostFx(const PostFx& p) {
    const auto valid = [](float value, float low, float high) {
        return std::isfinite(value) && value >= low && value <= high;
    };
    return valid(p.exposure, -2, 2) && valid(p.contrast, .5f, 1.5f) &&
           valid(p.saturation, 0, 2) && valid(p.grain, 0, .2f) &&
           valid(p.dither, 0, 1) && valid(p.bloom, 0, 1) &&
           valid(p.scanlines, 0, 1) && valid(p.mask, 0, 1) && valid(p.curvature, 0, .2f);
}
enum class PostFxPreset { original, subtle, crt, custom };
inline PostFxPreset postFxPreset(const PostFx& p) {
    if (!p.enabled && p.exposure == 0 && p.contrast == 1 && p.saturation == 1 &&
        p.grain == 0 && p.dither == 0 && p.bloom == 0 && p.scanlines == 0 &&
        p.mask == 0 && p.curvature == 0) return PostFxPreset::original;
    if (p.enabled && p.exposure == 0 && p.contrast == 1.05f && p.saturation == .9f &&
        p.grain == .015f && p.dither == .1f && p.bloom == .08f &&
        p.scanlines == 0 && p.mask == 0 && p.curvature == 0) return PostFxPreset::subtle;
    if (p.enabled && p.exposure == 0 && p.contrast == 1.05f && p.saturation == 1 &&
        p.grain == .02f && p.dither == .25f && p.bloom == .08f &&
        p.scanlines == .3f && p.mask == .15f && p.curvature == .04f) return PostFxPreset::crt;
    return PostFxPreset::custom;
}
inline void applyPostFxPreset(PostFx& p, PostFxPreset preset) {
    switch (preset) {
    case PostFxPreset::original: p = PostFx{}; break;
    case PostFxPreset::subtle:
        p = PostFx{}; p.enabled = true; p.contrast = 1.05f; p.saturation = .9f;
        p.grain = .015f; p.dither = .1f; p.bloom = .08f; break;
    case PostFxPreset::crt:
        p = PostFx{}; p.enabled = true; p.contrast = 1.05f; p.grain = .02f;
        p.dither = .25f; p.bloom = .08f; p.scanlines = .3f; p.mask = .15f;
        p.curvature = .04f; break;
    case PostFxPreset::custom: break;
    }
}
struct Settings {
    int wideRatio = 0, scale = 3, volume = 100;
    bool widescreen = false, fullscreen = false, filter = true, geometry = true, perspective = true;
    bool vsync = true, lowLatency = true;
    double mouseSensitivity = 1.0;
    PostFx postFx;
};
// Translate launcher preferences into overrides consumed by the game runtime.
inline std::array<std::pair<std::string, std::string>, 5> gameEnvironment(const Settings& s) {
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
             {"SHADOWTOWER_POSTFX", postFx}}};
}
// Presets alter only graphics quality; custom values and display preferences survive.
enum class GraphicsPreset { performance, balanced, quality, custom };
inline GraphicsPreset graphicsPreset(const Settings& s) {
    if (s.scale == 1 && !s.filter && !s.geometry && !s.perspective) return GraphicsPreset::performance;
    if (s.scale == 2 && s.filter && s.geometry && !s.perspective) return GraphicsPreset::balanced;
    if (s.scale == 4 && s.filter && s.geometry && s.perspective) return GraphicsPreset::quality;
    return GraphicsPreset::custom;
}
inline void applyGraphicsPreset(Settings& s, GraphicsPreset preset) {
    switch (preset) {
    case GraphicsPreset::performance: s.scale = 1; s.filter = s.geometry = s.perspective = false; break;
    case GraphicsPreset::balanced: s.scale = 2; s.filter = s.geometry = true; s.perspective = false; break;
    case GraphicsPreset::quality: s.scale = 4; s.filter = s.geometry = s.perspective = true; break;
    case GraphicsPreset::custom: break;
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
        if (scale >= 1 && scale <= 4) s.scale = scale;
        s.fullscreen = toml::find_or(v, "fullscreen", s.fullscreen);
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
        const double sensitivity = toml::find_or(options, "mouse_sensitivity", s.mouseSensitivity);
        if (std::isfinite(sensitivity) && sensitivity >= 0.05 && sensitivity <= 10.0)
            s.mouseSensitivity = sensitivity;
    }
    if (root.contains("post_processing") && root.at("post_processing").is_table()) {
        const auto& p = root.at("post_processing");
        s.postFx.enabled = toml::find_or(p, "enabled", s.postFx.enabled);
        const auto field = [&](const char* key, float& target, float low, float high) {
            const double value = toml::find_or(p, key, static_cast<double>(target));
            if (std::isfinite(value) && value >= low && value <= high) target = static_cast<float>(value);
        };
        field("exposure", s.postFx.exposure, -2, 2);
        field("contrast", s.postFx.contrast, .5f, 1.5f);
        field("saturation", s.postFx.saturation, 0, 2);
        field("grain", s.postFx.grain, 0, .2f);
        field("dither", s.postFx.dither, 0, 1);
        field("bloom", s.postFx.bloom, 0, 1);
        field("scanlines", s.postFx.scanlines, 0, 1);
        field("mask", s.postFx.mask, 0, 1);
        field("curvature", s.postFx.curvature, 0, .2f);
    }
    if (root.contains("audio") && root.at("audio").is_table()) {
        const int volume = toml::find_or(root.at("audio"), "volume", s.volume);
        if (volume >= 0 && volume <= 100) s.volume = volume;
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
// Replace only launcher-owned preferences, preserving other TOML fields.
inline void save(const fs::path& workspace, const Settings& s) {
    if (s.wideRatio < 0 || s.wideRatio > 1 || s.scale < 1 || s.scale > 4 || s.volume < 0 || s.volume > 100 ||
        !std::isfinite(s.mouseSensitivity) || s.mouseSensitivity < 0.05 || s.mouseSensitivity > 10.0 ||
        !validPostFx(s.postFx))
        throw std::invalid_argument("Invalid settings range");
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
    v["supersampling"] = s.scale;
    v["fullscreen"] = s.fullscreen;
    v["texture_filtering"] = s.filter ? "bilinear" : "nearest";
    v["geometry_correction"] = s.geometry;
    v["perspective_texturing"] = s.perspective;
    doc["audio"]["volume"] = s.volume;
    auto& p = doc["post_processing"];
    p["enabled"] = s.postFx.enabled;
    p["exposure"] = static_cast<double>(s.postFx.exposure);
    p["contrast"] = static_cast<double>(s.postFx.contrast);
    p["saturation"] = static_cast<double>(s.postFx.saturation);
    p["grain"] = static_cast<double>(s.postFx.grain);
    p["dither"] = static_cast<double>(s.postFx.dither);
    p["bloom"] = static_cast<double>(s.postFx.bloom);
    p["scanlines"] = static_cast<double>(s.postFx.scanlines);
    p["mask"] = static_cast<double>(s.postFx.mask);
    p["curvature"] = static_cast<double>(s.postFx.curvature);
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
