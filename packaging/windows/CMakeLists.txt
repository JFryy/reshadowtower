cmake_minimum_required(VERSION 3.16)
project(ReShadowTowerLauncher LANGUAGES C)

if(NOT WIN32)
    message(FATAL_ERROR "ReShadowTower launcher requires Windows")
endif()

add_executable(ReShadowTower WIN32 launcher.c)
target_compile_definitions(ReShadowTower PRIVATE UNICODE _UNICODE)
if(MSVC)
    target_link_options(ReShadowTower PRIVATE /ENTRY:wWinMainCRTStartup)
else()
    target_link_options(ReShadowTower PRIVATE -municode)
endif()
