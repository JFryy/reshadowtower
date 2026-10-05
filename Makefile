.DEFAULT_GOAL := help

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
PYTHON ?= python3
JOBS ?= 4
LAUNCHER_BUILD_DIR ?= $(ROOT)/build-launcher
APPIMAGE ?= $(wildcard $(ROOT)/dist/artifacts/ReShadowTower-*-x86_64.AppImage)
EXEEXT := $(if $(filter Windows_NT,$(OS)),.exe,)

.PHONY: help build build-launcher run launcher run-dev run-package play test

help:
	@printf '%s\n' \
		'make run            Build and open the current graphical launcher' \
		'make launcher       Alias for run' \
		'make run-dev        Alias for run' \
		'make run-package    Open an existing AppImage (may be an older build)' \
		'make build          Generate and build the game from your disc' \
		'make build-launcher Build only the graphical launcher' \
		'make play           Start the built game without the launcher' \
		'make test           Run the asset-free test suite' \
		'' \
		'Packaged launcher: APPIMAGE=/path/to/ReShadowTower.AppImage' \
		'Source launcher: JOBS=4 PYTHON=python3 LAUNCHER_BUILD_DIR=build-launcher'

build:
	cd "$(ROOT)" && ./scripts/build.sh

build-launcher:
	@framework_root=$$(cd "$(ROOT)" && "$(PYTHON)" tools/dependencies.py) && \
		cmake -S "$(ROOT)/launcher" -B "$(LAUNCHER_BUILD_DIR)" -G Ninja \
			-DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
			-DPSXRECOMP_ROOT="$$framework_root"
	cmake --build "$(LAUNCHER_BUILD_DIR)" --target shadowtower-launcher --parallel "$(JOBS)"

run-package:
	@test "$(words $(APPIMAGE))" -eq 1 || { \
		echo 'Expected one AppImage in dist/artifacts/. Use make run-package APPIMAGE=/path/to/ReShadowTower.AppImage.' >&2; \
		exit 1; \
	}
	@test -x "$(APPIMAGE)" || { \
		echo 'AppImage missing or not executable. Check APPIMAGE and run chmod +x on it.' >&2; \
		exit 1; \
	}
	"$(APPIMAGE)"

run launcher run-dev: build-launcher
	@python_path=$$(command -v "$(PYTHON)") && \
		cd "$(ROOT)" && \
		"$(LAUNCHER_BUILD_DIR)/shadowtower-launcher$(EXEEXT)" \
			--python "$$python_path" \
			--backend "$(ROOT)/tools/launcher_backend.py" \
			--workspace "$(ROOT)"

play:
	cd "$(ROOT)" && ./scripts/run.sh

test:
	cd "$(ROOT)" && "$(PYTHON)" tools/run_tests.py
