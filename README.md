# GhostTrax

GhostTrax turns a regular song file into a karaoke package:

- an instrumental MP3 with the vocals removed
- a vocals-only MP3 for reference/checking
- a synchronized CD+G (`.cdg`) lyric file with word-by-word highlighting
- a plain text lyric dump
- one zip containing the finished karaoke track

It is meant to make karaoke tracks that can be loaded by CDG/MP3 karaoke players, including the companion project:

https://github.com/pkircher29/ghost-trax-player

## What it does

Given an audio file, GhostTrax runs three stages:

1. Stem separation
   - Uses Demucs to split the original song into vocals and instrumental backing.

2. Word transcription
   - Uses Faster-Whisper to transcribe the isolated vocal stem with word timestamps.

3. CDG rendering
   - Writes a CD+G packet stream at 300 packets/second.
   - Lyrics are rendered with a bundled DejaVu Sans Bold font so output is consistent across Windows and Linux.
   - Words change color as they become active.

This is an AI-assisted karaoke generator. The output quality depends on the source recording, the separation model, and transcription accuracy. It is good at creating usable tracks quickly; it is not a replacement for hand-authored commercial karaoke timing.

## Output package

For an input like:

```text
Ella_Langley_I_Gotta_Quit_11043315.mp3
```

with prefix `KV`, ID `11043315`, and the default filename schema, GhostTrax creates:

```text
KV11043315 - Ella Langley - I Gotta Quit.zip
├── KV11043315 - Ella Langley - I Gotta Quit.mp3
├── KV11043315 - Ella Langley - I Gotta Quit.cdg
├── KV11043315 - Ella Langley - I Gotta Quit(vocals).mp3
└── KV11043315 - Ella Langley - I Gotta Quit.txt
```

File meanings:

- `.mp3` — instrumental backing track, named exactly like the `.cdg` for karaoke-player compatibility
- `.cdg` — synchronized karaoke graphics
- `(vocals).mp3` — isolated vocal stem, useful for checking the transcription
- `.txt` — detected lyrics as plain text

## Windows install

Download the latest Windows artifacts from GitHub Actions or Releases:

- `GhostTrax_Setup.exe` — installer
- `GhostTrax.exe` — standalone executable

Install/run it, choose an input song, set the output folder, then click:

```text
Make Karaoke Zip
```

The first run can take a while because the AI models are large and CPU-heavy.

## Source install

Requirements:

- Python 3.12
- ffmpeg and ffprobe available on PATH
- enough disk space for temporary WAV/stem files
- CPU works; CUDA is faster if you have a compatible GPU/PyTorch setup

Linux/WSL setup:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg python3 python3-pip

python3 -m pip install --upgrade pip
python3 -m pip install torch==2.6.0+cpu torchaudio==2.6.0+cpu --index-url https://download.pytorch.org/whl/cpu
python3 -m pip install demucs faster-whisper scipy pillow pyinstaller
```

Run the GUI:

```bash
python3 src/separator.py
```

For playback, see the companion project [GhostTrax Player](https://github.com/pkircher29/ghost-trax-player).

## Licensing & Authentication

Ghost-Trax is a paid standalone program. On startup, it performs licensing checks:
- It looks for local credentials at `~/.ghosttrax/license.json`.
- If missing or invalid, the app displays a Tkinter login dialog (GUI mode) or command-line prompt (CLI mode) requesting your **Email** and **API Host Token** (copied from your Auto-KJ account dashboard).
- The credentials are validated via the cloud server's `/api/verify-license` gateway. 
- Authorized tiers include: `GHOST-TRAX` (standalone), `VIP PASS`, `VIP QUAD`, and `INFINITE PLAY` (lifetime).
- Upon successful validation, the license state is cached locally in `~/.ghosttrax/license.json` for offline usage.

Run from CLI:

```bash
python3 src/separator.py input.mp3 -o output_dir --prefix KV --id 11043315 --artist "Ella Langley" --title "I Gotta Quit"
```

## CLI options

### Single file processing

```text
usage: separator.py [-h] [-o OUTPUT] [--prefix PREFIX] [--id SONG_ID]
                    [--schema SCHEMA] [--artist ARTIST] [--title TITLE]
                    [--stem-model STEM_MODEL]
                    [--whisper-model {small,medium,large-v3}]
                    [--device {cpu,cuda}]
                    input

positional arguments:
  input                 Audio file to process

options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Output folder (default: same as input)
  --prefix PREFIX       Manufacturer prefix
  --id SONG_ID          Song ID
  --schema SCHEMA       Output filename schema
  --artist ARTIST       Override artist
  --title TITLE         Override title
  --stem-model STEM_MODEL
                        Demucs model
  --whisper-model {small,medium,large-v3}
                        Whisper model
  --device {cpu,cuda}
```

### Batch processing

```text
usage: separator.py --batch [-h] [--list] [--prefix PREFIX] [--schema SCHEMA]
                           [--stem-model STEM_MODEL]
                           [--whisper-model {small,medium,large-v3}]
                           [--device {cpu,cuda}]
                           input [output]

positional arguments:
  input                 Input folder or text file with file paths
  output                Output folder (default: same as input)

options:
  -h, --help            show this help message and exit
  --list                Input is a text file with one path per line
  --prefix PREFIX       Manufacturer prefix
  --schema SCHEMA       Output filename schema
  --stem-model STEM_MODEL
                        Demucs model
  --whisper-model {small,medium,large-v3}
                        Whisper model
  --device {cpu,cuda}   Device
```

Batch examples:
```bash
# Process all audio files in a folder
python3 src/separator.py --batch /path/to/songs/

# Process from a file list (one path per line)
python3 src/separator.py --batch --list song_list.txt /output/
```

## Performance

The optimized CDG renderer (Chuck branch) includes:
- **75x faster rendering** - dirty tile tracking instead of full-screen comparisons
- Renders only at word boundaries, skips silent gaps
- On CPU without GPU: ~1-2 seconds per song for CDG generation (vs ~100s before)

## Building executables

Linux:

```bash
./build.sh
./dist/GhostTrax input.mp3
```

Windows builds are produced by GitHub Actions using `build-windows.bat`, PyInstaller, ffmpeg, ffprobe, and NSIS.

Manual Windows build outline:

```powershell
python -m pip install --upgrade pip
python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple/
python -m pip install demucs faster-whisper "scipy<1.15" pillow pyinstaller
choco install nsis -y
.\build-windows.bat
```

## Tests and renderer checks

Run the lightweight renderer regression tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Generate the bundled sample CDG:

```bash
PYTHONPATH=src python3 src/cdg_renderer.py
```

The renderer test suite specifically guards against the broken fake `8x16` bitmap font regression where every glyph was vertically duplicated. GhostTrax now uses a bundled TrueType font for deterministic CDG lyric rendering.

## Troubleshooting

### The app takes a long time

That is normal on CPU. Demucs and Whisper are heavy. A full song can take several minutes.

### `ffmpeg` or `ffprobe` is missing

Install ffmpeg and make sure it is on PATH. Packaged Windows builds bundle ffmpeg/ffprobe, but source runs expect system tools unless you place binaries next to the app.

### Lyrics are wrong

Check the `(vocals).mp3` file. If the vocal isolation is messy, Whisper will hallucinate or miss words. Try a cleaner source file or a larger Whisper model.

### Timing is a little off

Word timings come from Whisper. They are usually usable, but not hand-authored. For show-critical tracks, preview the generated zip before using it live.

### CDG text looks doubled, tiny, or unreadable

You are probably running an old build from commit `e21cbdd` or earlier. Use a build after `68ca016`, which restored real font rendering and added regression tests.

## Project layout

```text
src/separator.py          Main GUI/CLI pipeline
src/cdg_renderer.py       CDG packet renderer
src/naming.py             Filename parsing/output naming
src/assets/               Bundled renderer font and license
tests/                    Lightweight renderer regression tests
GhostTrax.spec            Linux PyInstaller build spec
GhostTrax-windows.spec    Windows PyInstaller build spec
installer.nsi             NSIS installer definition
```

## License

GhostTrax is MIT licensed.

The bundled DejaVu Sans Bold font is included under its own license in:

```text
src/assets/DejaVuSans-LICENSE.txt
```
