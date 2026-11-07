## Summary

<!-- Describe what this pull request changes and why. Focus on behaviour, not a file-by-file list. -->

## Related issues

<!-- Use "Closes #123" if this fully resolves an issue, or "Refs #123" if it is partial. -->

## Type of change

- [ ] Bug fix
- [ ] New feature or enhancement
- [ ] Performance improvement
- [ ] Refactor with no behaviour change
- [ ] Build, packaging, or CI
- [ ] Documentation

## Areas affected

- [ ] Launcher
- [ ] Rendering and video
- [ ] Audio
- [ ] Input and controls
- [ ] Game logic and runtime hooks
- [ ] Disc setup and verification
- [ ] Build, packaging, and release tooling
- [ ] PSXRecomp framework pins (`cmake/dependencies.json`)

## Changes

<!-- List the notable changes, including anything reviewers should look at closely. -->

-

## Validation

### Automated

- [ ] `python3 tools/run_tests.py` passes with no skipped tests
- [ ] New or updated tests cover the change, or the reason they do not is explained below

### Manual

<!-- Describe in-game or launcher testing. Delete this section if the change cannot affect runtime behaviour. -->

| | |
| --- | --- |
| Build type | <!-- AppImage, Windows installer, source build (Linux / MSYS2) --> |
| Platform | <!-- OS, GPU, driver; native Windows or Wine --> |
| Disc image | <!-- USA or USA with UNDUB v1.0 --> |
| Scenarios tested | <!-- Areas visited, menus used, settings changed --> |

### Known gaps

<!-- Anything not tested, platforms not covered, or follow-up work. Write "None" if there are none. -->

## Screenshots or recordings

<!-- Required for visual changes. Include before and after where possible. Delete if not applicable. -->

## Compatibility

- [ ] Existing memory card saves load and work
- [ ] Existing `settings.toml` and `input.ini` files are read correctly, or migration is handled
- [ ] Save state incompatibility, if any, is noted above

## Checklist

- [ ] The change is focused on a single concern
- [ ] Code follows the style of the surrounding files
- [ ] Framework fixes are submitted upstream and pinned, not applied only in a local `PSXRECOMP_ROOT`
- [ ] Documentation is updated where behaviour or setup changed
- [ ] No disc images, extracted game files, generated code, BIOS dumps, memory cards, or save states are included
