#pragma once

#include <SDL3/SDL.h>
#include <string>

// Owns a looping WAV stream and one SDL audio subsystem reference.
class SetupMusic {
public:
    explicit SetupMusic(const char* path);
    ~SetupMusic();
    SetupMusic(const SetupMusic&) = delete;
    SetupMusic& operator=(const SetupMusic&) = delete;

    void tick();
    void set_muted(bool muted);
    bool muted() const { return muted_; }
    const std::string& error() const { return error_; }

private:
    void fail(const char* message);
    void cleanup();
    SDL_AudioStream* stream_ = nullptr;
    Uint8* wav_ = nullptr;
    Uint32 length_ = 0;
    Uint32 position_ = 0;
    bool audio_initialized_ = false;
    bool muted_ = false;
    std::string error_;
};
