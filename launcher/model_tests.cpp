#include "model.hpp"
#include <stdexcept>
#include <chrono>
#include <fstream>

static void require(bool condition) {
    if (!condition) throw std::runtime_error("Launcher model check failed");
}

int main() {
    namespace fs = std::filesystem;
    const auto root = fs::temp_directory_path() / ("launcher-model-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    fs::create_directories(root / "build-release");
    try {
        { std::ofstream(root / "game.toml") << "[video]\naspect_ratio = '4:3'\nsupersampling = 3\n";
          std::ofstream(root / "build-release/settings.toml") << "[video]\naspect_ratio = 'invalid'\nsupersampling = 6\nunknown = 99\n[audio]\nvolume = 35\nother = 'kept'\n"; }
        auto s = launcher::load(root);
        require(!s.widescreen && s.wideRatio == 0 && s.scale == 3 && s.volume == 35);
        s.widescreen = true; s.wideRatio = 0; s.scale = 4; s.volume = 75;
        launcher::save(root, s);
        const auto doc = launcher::parse(root / "build-release/settings.toml");
        require(toml::find<int>(doc, "video", "unknown") == 99);
        require(toml::find<std::string>(doc, "audio", "other") == "kept");
        require(launcher::load(root).widescreen && launcher::load(root).wideRatio == 0 && launcher::load(root).volume == 75);
        require(toml::find<std::string>(doc, "video", "aspect_ratio") == "16:9");
        s.fullscreen = true; s.filter = false; s.geometry = false; s.perspective = false;
        s.wideRatio = 1; s.volume = 0;
        launcher::save(root, s);
        const auto saved = launcher::load(root);
        require(saved.widescreen && saved.wideRatio == 1 && saved.fullscreen && saved.volume == 0);
        require(!saved.filter && !saved.geometry && !saved.perspective);
        s.widescreen = false;
        launcher::save(root, s);
        require(!launcher::load(root).widescreen && launcher::load(root).wideRatio == 1);
        require(toml::find<std::string>(launcher::parse(root / "build-release/settings.toml"), "video", "aspect_ratio") == "4:3");
        s = launcher::load(root);
        s.widescreen = true;
        launcher::save(root, s);
        require(toml::find<std::string>(launcher::parse(root / "build-release/settings.toml"), "video", "aspect_ratio") == "21:9");
        s.scale = 6;
        bool rejected = false;
        try { launcher::save(root, s); } catch (const std::invalid_argument&) { rejected = true; }
        require(rejected);
        require(!launcher::ready(root));
        std::ofstream(root / "build-release/settings.toml") << "[broken";
        bool malformedRejected = false;
        try { launcher::save(root, launcher::Settings{}); }
        catch (const std::exception&) { malformedRejected = true; }
        require(malformedRejected);
        std::ifstream broken(root / "build-release/settings.toml");
        std::string preserved;
        std::getline(broken, preserved);
        require(preserved == "[broken");
        std::ofstream(root / "build-release" / launcher::executable(root).filename()) << "abc";
        std::ofstream(root / ".build-ready") << "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n";
        require(launcher::ready(root));
        std::ofstream(root / "build-release" / launcher::executable(root).filename(), std::ios::app) << "x";
        require(!launcher::ready(root));
    } catch (...) { fs::remove_all(root); throw; }
    fs::remove_all(root);
}
