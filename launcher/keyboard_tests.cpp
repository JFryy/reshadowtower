#include "keyboard.hpp"
#include <chrono>
#include <fstream>
#include <iterator>
#include <stdexcept>

static void require(bool condition, const char* what) {
    if (!condition) throw std::runtime_error(std::string("Launcher keyboard check failed: ") + what);
}

static std::string read(const std::filesystem::path& file) {
    std::ifstream in(file);
    return std::string((std::istreambuf_iterator<char>(in)), {});
}

int main() {
    namespace fs = std::filesystem;
    auto dir = fs::temp_directory_path() / ("launcher-keyboard-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    fs::create_directories(dir / "build-release");
    auto file = dir / "build-release/keybinds.ini";
    try {
        const auto defaults = launcher::defaultKeyboard();
        require(defaults.keys[0] == launcher::KeyPair{"W", "Up"} && defaults.keys[16] == launcher::KeyPair{"A", ""},
                "default layout");
        require(defaults.mouse[0] == "triangle" && defaults.mouse[1] == "square", "default mouse buttons");
        require(launcher::loadKeyboard(dir).keys == defaults.keys, "missing file loads the default layout");

        // The framework's generated file has never been edited, so it shows the Shadow Tower layout.
        {
            std::ofstream out(file);
            out << "# generated\n[player1]\n";
            for (const auto& row : shadowtower_button_rows)
                out << row.key << " = " << (row.framework ? row.framework : "None") << "\n";
            out << "ls_up = Up\n\n[player2]\nup = I\n";
        }
        require(launcher::loadKeyboard(dir).keys == defaults.keys, "untouched framework file migrates");

        // Saving writes both sections and keeps everything else.
        auto keyboard = launcher::loadKeyboard(dir);
        keyboard.keys[1].alt.clear();
        keyboard.mouse[1].clear();
        launcher::saveKeyboard(dir, keyboard);
        auto text = read(file);
        require(text.find("# generated\n[player1]\nup = W, Up\ndown = S\n") == 0, "player1 rewritten in place");
        require(text.find("ls_up = Up\n") != std::string::npos, "unmanaged keys kept");
        require(text.find("[player2]\nup = I\n") != std::string::npos, "other players kept");
        require(text.find("r1 = None\n") != std::string::npos, "unbound written as None");
        require(text.find("[shadowtower]\nstrafe_left = A\nstrafe_right = D\nmouse_left = triangle\nmouse_right = None\n")
                    != std::string::npos, "action section appended");
        auto loaded = launcher::loadKeyboard(dir);
        require(loaded.keys == keyboard.keys && loaded.mouse == keyboard.mouse, "round trip");

        // An edited file is kept even when its keys match the framework defaults.
        { std::ofstream out(file); out << "[player1]\ntriangle = A\n[shadowtower]\nmouse_left = Cross\nmouse_right = nope\n"; }
        loaded = launcher::loadKeyboard(dir);
        require(loaded.keys[7] == launcher::KeyPair{"A", ""} && loaded.keys[0] == launcher::KeyPair{"Up", ""},
                "edited file kept");
        require(loaded.mouse[0] == "cross" && loaded.mouse[1] == "square", "mouse names and invalid values");

        // Assigning a key used elsewhere swaps; reserved keys are refused.
        keyboard = launcher::defaultKeyboard();
        auto notice = launcher::assignKey(keyboard, 7, 0, "E");
        require(keyboard.keys[7].primary == "E" && keyboard.keys[4] == launcher::KeyPair{"F", "X"}, "swap");
        require(notice == "E moved from Interact (Cross), which now uses F.", "swap notice");
        notice = launcher::assignKey(keyboard, 0, 1, "W");
        require(keyboard.keys[0] == launcher::KeyPair{"W", ""}, "same key twice in a row");
        notice = launcher::assignKey(keyboard, 0, 0, "Escape");
        require(!notice.empty() && keyboard.keys[0].primary == "W", "reserved key refused");
        launcher::clearKey(keyboard, 15, 0);
        require(keyboard.keys[15] == launcher::KeyPair{"Right Shift", ""}, "clearing primary promotes second key");
        notice = launcher::assignKey(keyboard, 0, 0, "Keypad ,");
        require(!notice.empty() && keyboard.keys[0].primary == "W", "key names with commas refused");
        keyboard = launcher::defaultKeyboard();
        launcher::assignKey(keyboard, 6, 1, "W");
        require(keyboard.keys[0] == launcher::KeyPair{"Up", ""}, "swapped-out primary promotes second key");

        keyboard.keys[0].primary = "W\n[player1]";
        bool rejected = false;
        try { launcher::saveKeyboard(dir, keyboard); } catch (const std::invalid_argument&) { rejected = true; }
        require(rejected, "newline rejected");
    } catch (...) { fs::remove_all(dir); throw; }
    fs::remove_all(dir);
}
