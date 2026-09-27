#pragma once

#include "setup_music.h"

#include <memory>
#include <string>

// Owns music and its controls for one first-run launcher session.
class SetupMusicUI {
public:
    SetupMusicUI(bool first_run, const char* path);

    void update(bool wizard_open, bool preparing);
    void draw_controls();
    void stop();

private:
    const bool first_run_;
    const std::string path_;
    std::unique_ptr<SetupMusic> music_;
};
