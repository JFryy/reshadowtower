# Place your Shadow Tower disc dump here

Supply your own **Shadow Tower (USA), SLUS-00863** BIN/CUE dump. Other regions
are not supported. No game files are provided, and no retail BIOS is needed.

Place these two files directly in this directory, not inside a ZIP or subfolder:

```text
disc/
  README.md
  Shadow Tower (USA).bin
  Shadow Tower (USA).cue
```

The CUE's `FILE` entry must reference the BIN filename exactly:

```text
FILE "Shadow Tower (USA).bin" BINARY
```

Keep the rest of your dump's CUE contents unchanged. Renaming another format
(such as ISO or CHD) to `.bin` does not convert it to a supported BIN/CUE dump.

From the repository root, with the [build dependencies](../README.md#setup)
installed, run:

```bash
./scripts/build.sh
./scripts/run.sh
```

On Windows, use the MSYS2 MINGW64 terminal. The build extracts `SLUS_008.63`
automatically; you do not need to supply it separately. Keep the BIN/CUE files
here after building, since the game still needs them at runtime.

Everything in this directory except this README is ignored by Git. Do not
force-add or upload your game files.
