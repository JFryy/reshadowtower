#pragma once
#include <SDL3/SDL_opengl.h>
#include <filesystem>
#include <fstream>
#include <vector>
#include <stdexcept>
#define STB_IMAGE_IMPLEMENTATION
#define STBI_MAX_DIMENSIONS 4096
#define STBI_ONLY_TGA
#include "stb_image.h"

// Decode the packaged cover artwork and upload it to the launcher texture.
class Artwork {
public:
    GLuint texture = 0;
    int width = 0, height = 0;
    Artwork() = default;
    Artwork(const Artwork&) = delete;
    Artwork& operator=(const Artwork&) = delete;
    ~Artwork() { clear(); }
    void clear() {
        if (texture) glDeleteTextures(1, &texture);
        texture = 0;
        width = height = 0;
    }
    void load(const std::filesystem::path& path) {
        std::ifstream file(path, std::ios::binary | std::ios::ate);
        if (!file) throw std::runtime_error("Cannot read artwork: " + path.u8string());
        const auto size = file.tellg();
        if (size <= 0 || size > 32 * 1024 * 1024)
            throw std::runtime_error("Packaged cover has an invalid size. Restore the complete release assets.");
        std::vector<unsigned char> bytes(static_cast<size_t>(size));
        file.seekg(0);
        if (!file.read(reinterpret_cast<char*>(bytes.data()), size))
            throw std::runtime_error("Cannot finish reading artwork. Check the file and retry.");
        int w, h, channels;
        auto* pixels = stbi_load_from_memory(bytes.data(), static_cast<int>(bytes.size()), &w, &h, &channels, 4);
        if (!pixels) throw std::runtime_error("Cannot decode the packaged TGA cover. Restore the complete release assets.");
        GLuint next = 0;
        glGenTextures(1, &next);
        glBindTexture(GL_TEXTURE_2D, next);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
        stbi_image_free(pixels);
        if (!next || glGetError() != GL_NO_ERROR) {
            if (next) glDeleteTextures(1, &next);
            throw std::runtime_error("Cannot upload the cover to the graphics device. Check your OpenGL driver and restart.");
        }
        clear();
        texture = next; width = w; height = h;
    }
};
