#pragma once
#include <algorithm>
#include <array>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace launcher {
namespace fs = std::filesystem;
inline constexpr std::array<const char*, 16> bindingKeys = {
    "up", "down", "left", "right", "cross", "circle", "square", "triangle",
    "l1", "r1", "l2", "r2", "l3", "r3", "start", "select"
};
inline constexpr std::array<const char*, 16> bindingLabels = {
    "Up", "Down", "Left", "Right", "Cross", "Circle", "Square", "Triangle",
    "L1", "R1", "L2", "R2", "L3", "R3", "Start", "Select"
};
inline constexpr std::array<const char*, 25> bindingSources = {
    "a", "b", "x", "y", "back", "start", "leftshoulder", "rightshoulder",
    "lefttrigger", "righttrigger", "leftstick", "rightstick", "dpup", "dpdown",
    "dpleft", "dpright", "leftx-", "leftx+", "lefty-", "lefty+",
    "rightx-", "rightx+", "righty-", "righty+", ""
};
struct Bindings {
    std::array<std::string, 16> sources = {
        "dpup", "dpdown", "dpleft", "dpright", "a", "b", "x", "y",
        "leftshoulder", "rightshoulder", "lefttrigger", "righttrigger",
        "leftstick", "rightstick", "start", "back"
    };
};
namespace binding_detail {
inline std::string trim(std::string s) {
    auto first = s.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return {};
    return s.substr(first, s.find_last_not_of(" \t\r\n") - first + 1);
}
inline std::string lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return s;
}
inline std::string section(const std::string& line, const std::string& current) {
    auto text = trim(line.substr(0, line.find_first_of(";#")));
    if (text.size() >= 2 && text.front() == '[' && text.back() == ']')
        return lower(trim(text.substr(1, text.size() - 2)));
    return current;
}
inline int keyIndex(const std::string& line) {
    auto text = line.substr(0, line.find_first_of(";#"));
    auto eq = text.find('=');
    if (eq == std::string::npos) return -1;
    auto key = lower(trim(text.substr(0, eq)));
    for (size_t i = 0; i < bindingKeys.size(); ++i)
        if (key == bindingKeys[i]) return static_cast<int>(i);
    return -1;
}
inline std::vector<std::string> lines(const fs::path& file) {
    std::ifstream in(file, std::ios::binary);
    if (!in) {
        if (fs::exists(file)) throw std::runtime_error("Cannot read input.ini");
        return {};
    }
    std::vector<std::string> result;
    std::string line;
    while (std::getline(in, line)) result.push_back(line);
    if (!in.eof()) throw std::runtime_error("Cannot read input.ini");
    return result;
}
}
inline Bindings loadBindings(const fs::path& workspace) {
    Bindings result;
    std::string section;
    for (const auto& line : binding_detail::lines(workspace / "build-release/input.ini")) {
        section = binding_detail::section(line, section);
        if (section != "mapping") continue;
        int index = binding_detail::keyIndex(line);
        if (index < 0) continue;
        auto text = line.substr(0, line.find_first_of(";#"));
        result.sources[index] = binding_detail::trim(text.substr(text.find('=') + 1));
    }
    return result;
}
inline void saveBindings(const fs::path& workspace, const Bindings& bindings) {
    for (const auto& value : bindings.sources)
        if (value.find_first_of("\r\n;#") != std::string::npos)
            throw std::invalid_argument("Invalid controller binding value");
    auto file = workspace / "build-release/input.ini";
    auto original = binding_detail::lines(file);
    auto current = loadBindings(workspace);
    std::array<bool, 16> changed{};
    for (size_t i = 0; i < changed.size(); ++i) changed[i] = bindings.sources[i] != current.sources[i];
    std::array<bool, 16> found{};
    std::string section;
    bool hasMapping = false;
    size_t insertAt = original.size();
    for (size_t i = 0; i < original.size(); ++i) {
        auto next = binding_detail::section(original[i], section);
        if (next != section && section == "mapping") insertAt = i;
        section = next;
        if (section != "mapping") continue;
        hasMapping = true;
        int index = binding_detail::keyIndex(original[i]);
        if (index < 0 || !changed[index]) continue;
        found[index] = true;
        auto eq = original[i].find('=');
        auto comment = original[i].find_first_of(";#", eq + 1);
        auto prefix = original[i].substr(0, eq + 1);
        auto suffix = comment == std::string::npos ? "" : original[i].substr(comment);
        original[i] = prefix + " " + bindings.sources[index] + (suffix.empty() ? "" : " " + suffix);
    }
    if (!hasMapping) {
        if (!original.empty() && !original.back().empty()) original.push_back("");
        original.push_back("[mapping]");
        insertAt = original.size();
    }
    std::vector<std::string> missing;
    for (size_t i = 0; i < found.size(); ++i)
        if (changed[i] && !found[i]) missing.push_back(std::string(bindingKeys[i]) + " = " + bindings.sources[i]);
    original.insert(original.begin() + static_cast<std::ptrdiff_t>(insertAt), missing.begin(), missing.end());
    fs::create_directories(file.parent_path());
    auto temporary = file;
    temporary += ".tmp";
    try {
        std::ofstream out(temporary, std::ios::binary | std::ios::trunc);
        out.exceptions(std::ios::badbit | std::ios::failbit);
        for (const auto& line : original) out << line << '\n';
        out.close();
#ifdef _WIN32
        if (!MoveFileExW(temporary.c_str(), file.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
            throw std::system_error(GetLastError(), std::system_category(), "Cannot replace input.ini");
#else
        fs::rename(temporary, file);
#endif
    } catch (...) {
        std::error_code ignored;
        fs::remove(temporary, ignored);
        throw;
    }
}
}
