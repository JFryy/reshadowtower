#pragma once
// Keyboard and mouse-button bindings in keybinds.ini, laid out by keyboard_bindings.h.
#include "bindings.hpp"
#include "keyboard_bindings.h"
#include <utility>

namespace launcher {
// Up to two keys for one row; an empty name is unbound.
struct KeyPair {
    std::string primary, alt;
    bool operator==(const KeyPair& other) const { return primary == other.primary && alt == other.alt; }
};
inline constexpr size_t buttonRowCount = SHADOWTOWER_BUTTON_ROWS;
inline constexpr size_t keyRowCount = SHADOWTOWER_BUTTON_ROWS + SHADOWTOWER_STRAFE_ROWS;
inline constexpr size_t mouseRowCount = SHADOWTOWER_MOUSE_ROWS;
struct Keyboard {
    std::array<KeyPair, keyRowCount> keys;          // [player1] buttons, then [shadowtower] strafe rows
    std::array<std::string, mouseRowCount> mouse;   // PlayStation button key per captured mouse button; empty = none
};
inline const ShadowTowerKeyRow& keyRow(size_t row) {
    return row < buttonRowCount ? shadowtower_button_rows[row] : shadowtower_strafe_rows[row - buttonRowCount];
}
namespace keyboard_detail {
inline std::string text(const char* value) { return value ? value : ""; }
inline bool same(const std::string& a, const std::string& b) {
    return binding_detail::lower(a) == binding_detail::lower(b);
}
inline std::string keyName(std::string value) {
    value = binding_detail::trim(value);
    return same(value, "None") ? "" : value;
}
inline KeyPair parse(const std::string& value) {
    auto comma = value.find(',');
    if (comma == std::string::npos) return {keyName(value), ""};
    return {keyName(value.substr(0, comma)), keyName(value.substr(comma + 1))};
}
inline std::string format(const KeyPair& keys) {
    std::string value = keys.primary.empty() ? "None" : keys.primary;
    return keys.alt.empty() ? value : value + ", " + keys.alt;
}
inline bool isButton(const std::string& name) {
    for (const auto& row : shadowtower_button_rows)
        if (same(name, row.key)) return true;
    return false;
}
inline fs::path file(const fs::path& workspace) { return workspace / "build-release/keybinds.ini"; }
// Set key = value lines inside [section], appending missing keys and the section itself.
inline void setSection(std::vector<std::string>& lines, const std::string& section,
                       const std::vector<std::pair<std::string, std::string>>& values) {
    std::vector<bool> found(values.size());
    std::string current;
    size_t end = lines.size();
    bool present = false;
    for (size_t i = 0; i < lines.size(); ++i) {
        auto text = binding_detail::trim(lines[i]);
        if (!text.empty() && text.front() == '[') {
            current = binding_detail::lower(binding_detail::trim(text.substr(1, text.find(']') - 1)));
            if (current == section) {
                present = true;
                end = i + 1;
            }
            continue;
        }
        if (current != section) continue;
        if (!text.empty()) end = i + 1;
        auto eq = text.find('=');
        if (text.empty() || text.front() == '#' || text.front() == ';' || eq == std::string::npos) continue;
        auto key = binding_detail::lower(binding_detail::trim(text.substr(0, eq)));
        for (size_t v = 0; v < values.size(); ++v) {
            if (key != values[v].first) continue;
            lines[i] = values[v].first + " = " + values[v].second;
            found[v] = true;
        }
    }
    std::vector<std::string> missing;
    for (size_t v = 0; v < values.size(); ++v)
        if (!found[v]) missing.push_back(values[v].first + " = " + values[v].second);
    if (!present) {
        if (!lines.empty() && !binding_detail::trim(lines.back()).empty()) lines.push_back("");
        lines.push_back("[" + section + "]");
        end = lines.size();
    }
    lines.insert(lines.begin() + static_cast<std::ptrdiff_t>(end), missing.begin(), missing.end());
}
}
inline Keyboard defaultKeyboard() {
    Keyboard result;
    for (size_t row = 0; row < keyRowCount; ++row)
        result.keys[row] = {keyboard_detail::text(keyRow(row).primary), keyboard_detail::text(keyRow(row).alt)};
    for (size_t row = 0; row < mouseRowCount; ++row)
        result.mouse[row] = shadowtower_mouse_rows[row].primary;
    return result;
}
// Reads keybinds.ini the way the runtime does: a file whose [player1] still holds the
// framework's generated defaults and has no [shadowtower] section shows the Shadow Tower layout.
inline Keyboard loadKeyboard(const fs::path& workspace) {
    using namespace keyboard_detail;
    Keyboard result = defaultKeyboard();
    for (size_t row = 0; row < buttonRowCount; ++row) result.keys[row] = {text(keyRow(row).framework), ""};
    bool hasActions = false;
    std::string section;
    for (const auto& line : binding_detail::lines(file(workspace))) {
        auto entry = binding_detail::trim(line);
        if (entry.empty() || entry.front() == '#' || entry.front() == ';') continue;
        if (entry.front() == '[') {
            section = binding_detail::lower(binding_detail::trim(entry.substr(1, entry.find(']') - 1)));
            hasActions |= section == "shadowtower";
            continue;
        }
        auto eq = entry.find('=');
        if (eq == std::string::npos) continue;
        auto key = binding_detail::lower(binding_detail::trim(entry.substr(0, eq)));
        auto value = entry.substr(eq + 1);
        size_t first = 0, last = 0;
        if (section == "player1") last = buttonRowCount;
        if (section == "shadowtower") {
            first = buttonRowCount;
            last = keyRowCount;
        }
        for (size_t row = first; row < last; ++row)
            if (key == keyRow(row).key) result.keys[row] = parse(value);
        if (section != "shadowtower") continue;
        for (size_t row = 0; row < mouseRowCount; ++row) {
            auto button = keyName(value);
            if (key == shadowtower_mouse_rows[row].key && (button.empty() || isButton(button)))
                result.mouse[row] = binding_detail::lower(button);
        }
    }
    if (hasActions) return result;
    for (size_t row = 0; row < buttonRowCount; ++row)
        if (!same(result.keys[row].primary, text(keyRow(row).framework)) || !result.keys[row].alt.empty())
            return result;
    return defaultKeyboard();
}
inline void saveKeyboard(const fs::path& workspace, const Keyboard& keyboard) {
    using namespace keyboard_detail;
    for (const auto& keys : keyboard.keys)
        for (const auto& name : {keys.primary, keys.alt})
            if (name.find_first_of(",\r\n") != std::string::npos)
                throw std::invalid_argument("Invalid keyboard binding: " + name);
    for (const auto& button : keyboard.mouse)
        if (!button.empty() && !isButton(button)) throw std::invalid_argument("Invalid mouse binding: " + button);
    std::vector<std::pair<std::string, std::string>> player, actions;
    for (size_t row = 0; row < keyRowCount; ++row)
        (row < buttonRowCount ? player : actions).emplace_back(keyRow(row).key, format(keyboard.keys[row]));
    for (size_t row = 0; row < mouseRowCount; ++row)
        actions.emplace_back(shadowtower_mouse_rows[row].key, keyboard.mouse[row].empty() ? "None" : keyboard.mouse[row]);
    auto path = file(workspace);
    auto lines = binding_detail::lines(path);
    setSection(lines, "player1", player);
    setSection(lines, "shadowtower", actions);
    binding_detail::writeLines(path, lines);
}
inline bool reservedKey(const std::string& key) {
    if (key.find(',') != std::string::npos) return true;
    for (const char* reserved : shadowtower_reserved_keys)
        if (keyboard_detail::same(key, reserved)) return true;
    return false;
}
// Clear one key; a cleared primary takes the row's second key.
inline void clearKey(Keyboard& keyboard, size_t row, int slot) {
    auto& keys = keyboard.keys[row];
    if (slot) keys.alt.clear();
    else keys.primary = std::exchange(keys.alt, std::string());
}
// Bind key to row/slot. A row already using the key takes this slot's previous key instead.
// Returns a message for the player, empty when nothing else changed.
inline std::string assignKey(Keyboard& keyboard, size_t row, int slot, const std::string& key) {
    if (reservedKey(key)) return key + " is reserved and cannot be bound.";
    auto& target = slot ? keyboard.keys[row].alt : keyboard.keys[row].primary;
    const std::string previous = target;
    std::string notice;
    for (size_t other = 0; other < keyRowCount; ++other) {
        for (int otherSlot = 0; otherSlot < 2; ++otherSlot) {
            auto& name = otherSlot ? keyboard.keys[other].alt : keyboard.keys[other].primary;
            if ((other == row && otherSlot == slot) || !keyboard_detail::same(name, key)) continue;
            name = other == row ? std::string() : previous;
            if (other != row)
                notice = key + " moved from " + keyRow(other).label +
                         (previous.empty() ? ", which is now unbound." : ", which now uses " + previous + ".");
        }
    }
    target = key;
    for (size_t other = 0; other < keyRowCount; ++other)
        if (keyboard.keys[other].primary.empty()) clearKey(keyboard, other, 0);
    return notice;
}
}
