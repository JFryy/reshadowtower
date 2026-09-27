#include "setup_music_ui.h"

#include "imgui.h"

SetupMusicUI::SetupMusicUI(bool first_run, const char* path)
    : first_run_(first_run), path_(path) {}

void SetupMusicUI::update(bool wizard_open, bool preparing) {
    if (!first_run_ || (!wizard_open && !preparing)) {
        stop();
        return;
    }
    if (!music_) {
        music_ = std::make_unique<SetupMusic>(path_.c_str());
    }
    music_->tick();
}

void SetupMusicUI::draw_controls() {
    if (!music_) return;

    bool muted = music_->muted();
    if (ImGui::Checkbox("Mute setup music", &muted)) {
        music_->set_muted(muted);
    }
    if (!music_->error().empty()) {
        ImGui::TextWrapped("Setup music: %s", music_->error().c_str());
    }
}

void SetupMusicUI::stop() {
    music_.reset();
}
