# Stem Separator

A cross-platform desktop app that separates an audio file into two stems:

- **vocals** — the vocal track
- **music** — the instrumental backing track (drums + bass + other)

Built on [Demucs](https://github.com/facebookresearch/demucs) (Meta AI). Supports GUI and CLI modes.

## Quick start (source)

```bash
python3 src/separator.py                    # GUI mode
python3 src/separator.py input.mp3          # CLI mode
python3 src/separator.py input.mp3 -o ./out # specify output folder
```

## Windows

Download `StemSeparator_Setup.exe` or `StemSeparator.exe` from the [Releases](https://github.com/pkircher29/stem-separator/releases) page.

Run the installer, then open the app, pick an audio file, and click **Separate**.

## Linux / macOS

```bash
./build.sh
./dist/StemSeparator input.mp3
```

## Output files

For an input named `song.mp3`, the app creates:

```
output_dir/
├── song_vocals.wav
└── song_music.wav
```

## CLI options

```
usage: separator.py [-h] [-o OUTPUT] [-m MODEL] [-d DEVICE] input

positional arguments:
  input                 Audio file to separate

options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Output folder (default: same as input)
  -m MODEL, --model MODEL
                        Demucs model (default: htdemucs)
  -d DEVICE, --device DEVICE
                        cpu or cuda (default: cpu)
```

## License

MIT
