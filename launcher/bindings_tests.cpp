#include "bindings.hpp"
#include <stdexcept>
#include <chrono>
#include <fstream>
#include <iterator>

static void require(bool condition) {
    if (!condition) throw std::runtime_error("Launcher bindings check failed");
}

int main() {
    namespace fs = std::filesystem;
    auto dir = fs::temp_directory_path() / ("launcher-bindings-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    fs::create_directories(dir / "build-release");
    try {
        auto defaults = launcher::loadBindings(dir);
        require(defaults.sources[0] == "dpup" && defaults.sources[15] == "back");
        auto file = dir / "build-release/input.ini";
        { std::ofstream out(file); out << "; keep\n[mapping]\ncross = a,b ; note\ncross = x\nother = custom\n[mapping.ABC]\ncross = y\n"; }
        auto bindings = launcher::loadBindings(dir);
        require(bindings.sources[4] == "x");
        bindings.sources[4] = "leftx-,a";
        bindings.sources[0] = "righty+";
        launcher::saveBindings(dir, bindings);
        require(launcher::loadBindings(dir).sources == bindings.sources);
        std::ifstream in(file);
        std::string text((std::istreambuf_iterator<char>(in)), {});
        require(text.find("cross = leftx-,a ; note") != std::string::npos);
        require(text.find("other = custom") != std::string::npos);
        require(text.find("[mapping.ABC]\ncross = y") != std::string::npos);
        bindings.sources[0] = "a\n[controller]\nenabled=false";
        bool rejected = false;
        try { launcher::saveBindings(dir, bindings); } catch (const std::invalid_argument&) { rejected = true; }
        require(rejected && launcher::loadBindings(dir).sources[0] == "righty+");
    } catch (...) { fs::remove_all(dir); throw; }
    fs::remove_all(dir);
}
