# GhostTrax

A cross-platform desktop app that turns any audio file into a karaoke-style CDG track with separate instrumental and vocal MP3s.

For an input song, GhostTrax produces a single zip containing:

- **`{name}_music.mp3`** — instrumental backing track (vocals removed)
- **`{name}_vocals.mp3`** — isolated vocal track
- **`{name}.cdg`** — synchronized CDG graphics with word-by-word lyric highlighting

Built on [Demucs](https://github.com/facebookresearch/demucs) (Meta AI) and [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper).

## Quick start (source)

Requires Python 3.12, ffmpeg, and dependencies:

```bash
python3 -m pip install torch==2.6.0+cpu torchaudio==2.6.0+cpu --index-url https://download.pytorch.org/whl/cpu
python3 -m pip install demucs scipy faster-whisper pyinstaller

python3 src/separator.py                              # GUI mode
python3 src/separator.py input.mp3                    # CLI mode
```

## Windows

Download `GhostTrax_Setup.exe` or `GhostTrax.exe` from the [Releases](https://github.com/pkircher29/ghost-trax/releases) page.

Run the installer, then open the app, pick an audio file, and click **Make Karaoke Zip**.

## Linux / macOS

```bash
./build.sh
./dist/GhostTrax input.mp3
```

## Output files

For an input named `Ella_Langley_I_Gotta_Quit_11043315.mp3` with prefix `KV`,
ID `11043315`, and the default schema, the app creates:

```
output_dir/
└── KV11043315 - Ella Langley - I Gotta Quit.zip
    ├── KV11043315 - Ella Langley - I Gotta Quit_music.mp3
    ├── KV11043315 - Ella Langley - I Gotta Quit_vocals.mp3
    └── KV11043315 - Ella Langley - I Gotta Quit.cdg
```

The `.cdg` file displays full-screen lyrics on a black background. Words change
color as they become active, so they stay synchronized with the instrumental MP3.

## CLI options

```
usage: separator.py [-h] [-o OUTPUT] [--prefix PREFIX] [--id ID] [--schema SCHEMA]
                    [--artist ARTIST] [--title TITLE] [--stem-model STEM_MODEL]
                    [--whisper-model {small,medium,large-v3}] [--device {cpu,cuda}]
                    input

positional arguments:
  input                 Audio file to process

options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Output folder (default: same as input)
  --prefix PREFIX       Manufacturer prefix (default: KV)
  --id ID               Song ID
  --schema SCHEMA       Output filename schema (default: {prefix}{id} - {artist} - {title})
  --artist ARTIST       Override artist
  --title TITLE         Override title
  --stem-model STEM_MODEL
                        Demucs model (default: htdemucs)
  --whisper-model {small,medium,large-v3}
                        Whisper model for transcription (default: medium)
  --device {cpu,cuda}   cpu or cuda (default: cpu)
```

## License

MIT
