#include "setup_music.h"

#include <algorithm>
#include <cstdio>

namespace {
constexpr float music_gain = 0.25f;
constexpr int sample_rate = 44100;
constexpr int channels = 2;
constexpr int bytes_per_sample = 2;
constexpr int chunk_bytes = sample_rate * channels * bytes_per_sample / 4;
}

void SetupMusic::cleanup() {
    if (stream_) {
        SDL_DestroyAudioStream(stream_);
        stream_ = nullptr;
    }
    if (wav_) {
        SDL_free(wav_);
        wav_ = nullptr;
    }
    length_ = 0;
    position_ = 0;
    if (audio_initialized_) {
        SDL_QuitSubSystem(SDL_INIT_AUDIO);
        audio_initialized_ = false;
    }
}

void SetupMusic::fail(const char* message) {
    error_ = std::string(message) + ": " + SDL_GetError();
    std::fprintf(stderr, "Setup music: %s\n", error_.c_str());
    cleanup();
}

SetupMusic::SetupMusic(const char* path) {
    if (!SDL_InitSubSystem(SDL_INIT_AUDIO)) {
        fail("Cannot initialize audio");
        return;
    }
    audio_initialized_ = true;
    SDL_AudioSpec spec;
    if (!SDL_LoadWAV(path, &spec, &wav_, &length_)) {
        fail("Cannot load music");
        return;
    }
    if (spec.format != SDL_AUDIO_S16LE || spec.channels != channels || spec.freq != sample_rate || !length_) {
        error_ = "Music must be PCM16 44.1 kHz stereo";
        std::fprintf(stderr, "Setup music: %s\n", error_.c_str());
        cleanup();
        return;
    }
    stream_ = SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, &spec, nullptr, nullptr);
    if (!stream_) {
        fail("Cannot open audio device");
        return;
    }
    if (!SDL_SetAudioStreamGain(stream_, music_gain) || !SDL_ResumeAudioStreamDevice(stream_)) {
        fail("Cannot start playback");
    }
}

SetupMusic::~SetupMusic() {
    cleanup();
}

void SetupMusic::set_muted(bool muted) {
    muted_ = muted;
    if (stream_ && !SDL_SetAudioStreamGain(stream_, muted ? 0.0f : music_gain)) {
        fail("Cannot change music volume");
    }
}

void SetupMusic::tick() {
    if (!stream_) return;
    // Keep at most half a second buffered, feeding at most one chunk per frame.
    const int queued = SDL_GetAudioStreamQueued(stream_);
    if (queued < 0) {
        fail("Cannot inspect music queue");
        return;
    }
    if (queued >= chunk_bytes) return;
    const int count = static_cast<int>(std::min<Uint32>(chunk_bytes, length_ - position_));
    if (!SDL_PutAudioStreamData(stream_, wav_ + position_, count)) {
        fail("Cannot queue music");
        return;
    }
    position_ += count;
    if (position_ == length_) position_ = 0;
}
