#include "setup_music.h"

#include <algorithm>
#include <cstdio>

void SetupMusic::fail(const char* message) {
    error_ = std::string(message) + ": " + SDL_GetError();
    std::fprintf(stderr, "Setup music: %s\n", error_.c_str());
}

SetupMusic::SetupMusic(const char* path) {
    if (!(SDL_WasInit(SDL_INIT_AUDIO) & SDL_INIT_AUDIO)) {
        if (!SDL_InitSubSystem(SDL_INIT_AUDIO)) {
            fail("Cannot initialize audio");
            return;
        }
        owns_audio_ = true;
    }
    SDL_AudioSpec spec;
    if (!SDL_LoadWAV(path, &spec, &wav_, &length_)) {
        fail("Cannot load music");
        return;
    }
    if (spec.format != SDL_AUDIO_S16LE || spec.channels != 2 || spec.freq != 44100 || !length_) {
        error_ = "Music must be PCM16 44.1 kHz stereo";
        std::fprintf(stderr, "Setup music: %s\n", error_.c_str());
        return;
    }
    stream_ = SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, &spec, nullptr, nullptr);
    if (!stream_) {
        fail("Cannot open audio device");
        return;
    }
    if (!SDL_SetAudioStreamGain(stream_, 0.25f) || !SDL_ResumeAudioStreamDevice(stream_)) {
        fail("Cannot start playback");
        SDL_DestroyAudioStream(stream_);
        stream_ = nullptr;
    }
}

SetupMusic::~SetupMusic() {
    if (stream_) SDL_DestroyAudioStream(stream_);
    if (wav_) SDL_free(wav_);
    if (owns_audio_) SDL_QuitSubSystem(SDL_INIT_AUDIO);
}

void SetupMusic::set_muted(bool muted) {
    muted_ = muted;
    if (stream_ && !SDL_SetAudioStreamGain(stream_, muted ? 0.0f : 0.25f)) {
        fail("Cannot change music volume");
        SDL_DestroyAudioStream(stream_);
        stream_ = nullptr;
    }
}

void SetupMusic::tick() {
    if (!stream_) return;
    // Keep at most half a second buffered, feeding at most one chunk per frame.
    const int queued = SDL_GetAudioStreamQueued(stream_);
    if (queued < 0) {
        fail("Cannot inspect music queue");
        SDL_DestroyAudioStream(stream_);
        stream_ = nullptr;
        return;
    }
    constexpr int chunk = 44100 * 2 * 2 / 4;
    if (queued >= chunk) return;
    const int count = std::min<int>(chunk, length_ - position_);
    if (!SDL_PutAudioStreamData(stream_, wav_ + position_, count)) {
        fail("Cannot queue music");
        SDL_DestroyAudioStream(stream_);
        stream_ = nullptr;
        return;
    }
    position_ += count;
    if (position_ == length_) position_ = 0;
}
