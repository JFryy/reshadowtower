#include "setup_music.h"
#include "setup_music_ui.h"

#include <cassert>
#include <string>

static void test_playback(const char* path) {
    assert(!SDL_WasInit(SDL_INIT_AUDIO));
    {
        SetupMusic music(path);
        assert(music.error().empty());
        assert(SDL_WasInit(SDL_INIT_AUDIO));
        // The fixture is shorter than this playback period, exercising looping.
        for (int i = 0; i < 12; ++i) {
            music.tick();
            SDL_Delay(10);
        }
        music.set_muted(true);
        assert(music.muted());
        music.set_muted(false);
        assert(!music.muted());
        assert(music.error().empty());
    }
    assert(!SDL_WasInit(SDL_INIT_AUDIO));

    assert(SDL_InitSubSystem(SDL_INIT_AUDIO));
    {
        SetupMusic music(path);
        assert(music.error().empty());
        music.tick();
    }
    assert(SDL_WasInit(SDL_INIT_AUDIO)); // Preserve another audio user's reference.
    SDL_QuitSubSystem(SDL_INIT_AUDIO);

    {
        SetupMusic missing((std::string(path) + ".missing").c_str());
        assert(!missing.error().empty());
        missing.tick();
    }
    assert(!SDL_WasInit(SDL_INIT_AUDIO));
}

static void test_setup_lifetime(const char* path) {
    {
        SetupMusicUI setup(true, path);
        setup.update(true, false);
        assert(SDL_WasInit(SDL_INIT_AUDIO));
        setup.update(false, true); // Keep music during generation/rebuild.
        assert(SDL_WasInit(SDL_INIT_AUDIO));
        setup.update(false, false);
        assert(!SDL_WasInit(SDL_INIT_AUDIO));
        setup.update(true, false);
        setup.stop(); // Stop before gameplay, even while the launcher stays alive.
        assert(!SDL_WasInit(SDL_INIT_AUDIO));
        setup.update(true, false);
    }
    assert(!SDL_WasInit(SDL_INIT_AUDIO)); // Also clean up when setup is cancelled.
    SetupMusicUI gameplay(false, path);
    gameplay.update(true, true);
    assert(!SDL_WasInit(SDL_INIT_AUDIO));
}

int main(int argc, char** argv) {
    assert(argc == 2);
    test_playback(argv[1]);
    test_setup_lifetime(argv[1]);
}
