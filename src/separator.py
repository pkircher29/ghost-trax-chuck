import os
import re
import sys
import json
import zipfile
import argparse
import tempfile
import subprocess
import threading
from pathlib import Path
from typing import List

# Try to import demucs
try:
    from demucs.apply import apply_model
    from demucs.audio import AudioFile, save_audio
    from demucs.pretrained import get_model
    DEMUCS_AVAILABLE = True
except Exception as _demucs_err:
    DEMUCS_AVAILABLE = False
    _DEMUCS_IMPORT_ERROR = str(_demucs_err)

# Try to import faster-whisper
try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except Exception as _whisper_err:
    WHISPER_AVAILABLE = False
    _WHISPER_IMPORT_ERROR = str(_whisper_err)

from naming import (
    parse_filename,
    build_output_name,
    DEFAULT_PREFIX,
    DEFAULT_SCHEMA,
)
from cdg_renderer import (
    Word,
    build_cdg_from_words,
    clean_words_for_display,
    write_lyrics_txt,
)


def get_ffmpeg_path() -> str:
    """Return bundled ffmpeg if present, otherwise system ffmpeg."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent
    bundled = base / "ffmpeg"
    if bundled.exists():
        return str(bundled)
    bundled = base / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    return "ffmpeg"


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def ensure_wav(input_path: Path, work_dir: Path, ffmpeg: str) -> Path:
    """Convert input to 44.1kHz 16-bit stereo WAV for Demucs."""
    wav_path = work_dir / (sanitize_filename(input_path.stem) + "_converted.wav")
    cmd = [
        ffmpeg, "-y", "-i", str(input_path),
        "-ac", "2", "-ar", "44100", "-sample_fmt", "s16",
        str(wav_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {result.stderr}")
    return wav_path


def _save_wav_scipy(tensor, path: str, samplerate: int):
    import scipy.io.wavfile
    import numpy as np
    arr = tensor.detach().cpu().numpy()
    if arr.ndim == 1:
        arr = arr[None, :]
    arr = arr.T
    if arr.dtype != np.int16 and arr.dtype != np.float32:
        arr = np.clip(arr, -1.0, 1.0)
        arr = (arr * 32767).astype(np.int16)
    scipy.io.wavfile.write(path, samplerate, arr)


def separate_stems(
    input_path: Path,
    work_dir: Path,
    model: str = "htdemucs",
    device: str = "cpu",
    progress_callback=None,
) -> tuple[Path, Path]:
    """Separate input into vocals.wav and music.wav in work_dir."""
    if not DEMUCS_AVAILABLE:
        raise RuntimeError("demucs is not installed")

    ffmpeg = get_ffmpeg_path()
    wav_path = ensure_wav(input_path, work_dir, ffmpeg)

    if progress_callback:
        progress_callback("Loading Demucs model...")

    model_obj = get_model(model)
    model_obj.to(device)

    if progress_callback:
        progress_callback("Separating stems...")

    audio = AudioFile(wav_path).read(streams=0, channels=2)
    if audio.dim() == 2:
        audio = audio.unsqueeze(0)
    sources = apply_model(model_obj, audio, device=device, progress=True)

    if sources.dim() == 4:
        sources = sources[0]
    sample_rate = model_obj.samplerate
    stem_names = model_obj.sources

    vocals_idx = stem_names.index("vocals")
    vocals = sources[vocals_idx]

    music = None
    for idx, name in enumerate(stem_names):
        if name == "vocals":
            continue
        if music is None:
            music = sources[idx].clone()
        else:
            music = music + sources[idx]

    base = sanitize_filename(input_path.stem)
    vocals_path = work_dir / f"{base}_vocals.wav"
    music_path = work_dir / f"{base}_music.wav"

    try:
        save_audio(vocals, str(vocals_path), samplerate=sample_rate)
    except Exception:
        _save_wav_scipy(vocals, str(vocals_path), sample_rate)

    if music is not None:
        try:
            save_audio(music, str(music_path), samplerate=sample_rate)
        except Exception:
            _save_wav_scipy(music, str(music_path), sample_rate)

    return vocals_path, music_path


def detect_peak_db(wav_path: Path, ffmpeg: str) -> float:
    """Detect the true peak of a WAV file in dBFS using ffmpeg volumedetect."""
    cmd = [
        ffmpeg, "-y", "-i", str(wav_path),
        "-af", "volumedetect",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    stderr = result.stderr
    # Prefer max_volume (sample peak) for normalization target
    match = re.search(r"max_volume:\s*([-\d.]+)\s*dB", stderr)
    if match:
        return float(match.group(1))
    return 0.0


def normalize_to_mp3(
    wav_path: Path,
    output_path: Path,
    ffmpeg: str,
    progress_callback=None,
) -> Path:
    """Peak-normalize WAV to -1 dB and encode as high-quality MP3."""
    if progress_callback:
        progress_callback(f"Normalizing {wav_path.name}...")

    peak_db = detect_peak_db(wav_path, ffmpeg)
    # max_volume is negative if headroom exists; -1.0 means target peak -1 dBFS
    gain_db = -1.0 - peak_db

    # Safety clamp: never boost more than 20 dB
    gain_db = max(-20.0, min(gain_db, 20.0))

    cmd = [
        ffmpeg, "-y", "-i", str(wav_path),
        "-af", f"volume={gain_db:.4f}dB:precision=double",
        "-ar", "44100", "-ac", "2",
        "-codec:a", "libmp3lame", "-q:a", "0",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg MP3 normalization failed: {result.stderr}")
    return output_path


def transcribe_words(
    vocals_path: Path,
    whisper_model: str = "medium",
    device: str = "cpu",
    progress_callback=None,
) -> List[Word]:
    """Transcribe vocals into word-level timestamps."""
    if not WHISPER_AVAILABLE:
        raise RuntimeError("faster-whisper is not installed")

    if progress_callback:
        progress_callback(f"Loading Whisper model ({whisper_model})...")

    compute_type = "int8" if device == "cpu" else "float16"
    model = WhisperModel(whisper_model, device=device, compute_type=compute_type)

    if progress_callback:
        progress_callback("Transcribing words...")

    segments, _ = model.transcribe(
        str(vocals_path),
        beam_size=5,
        word_timestamps=True,
    )

    words = []
    for segment in segments:
        for word in segment.words or []:
            words.append(Word(
                text=word.word.strip(),
                start=word.start,
                end=word.end,
            ))

    return clean_words_for_display(words)


def get_audio_duration(path: Path, ffmpeg: str) -> float:
    """Get audio duration in seconds using ffprobe."""
    ffprobe = ffmpeg.replace("ffmpeg", "ffprobe")
    cmd = [
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Fallback: use ffmpeg output duration parsing
        return 0.0
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def make_karaoke_zip(
    input_path: Path,
    output_dir: Path,
    prefix: str = DEFAULT_PREFIX,
    song_id: str = "0000",
    schema: str = DEFAULT_SCHEMA,
    artist: str = "",
    title: str = "",
    stem_model: str = "htdemucs",
    whisper_model: str = "medium",
    device: str = "cpu",
    progress_callback=None,
) -> Path:
    """Full pipeline: separate, normalize, transcribe, render CDG, zip."""
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = get_ffmpeg_path()

    # Auto-parse filename if artist/title not provided
    parsed = parse_filename(input_path.name, prefix=prefix)
    if not artist:
        artist = parsed.artist
    if not title:
        title = parsed.title

    base_name = build_output_name(artist, title, prefix, song_id, schema)
    base_name = sanitize_filename(base_name)

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)

        # 1. Separate stems
        vocals_wav, music_wav = separate_stems(
            input_path, work_dir, model=stem_model, device=device,
            progress_callback=progress_callback,
        )

        # 2. Normalize to MP3
        music_mp3 = work_dir / f"{base_name}_music.mp3"
        vocals_mp3 = work_dir / f"{base_name}_vocals.mp3"
        normalize_to_mp3(music_wav, music_mp3, ffmpeg, progress_callback)
        normalize_to_mp3(vocals_wav, vocals_mp3, ffmpeg, progress_callback)

        # 3. Transcribe vocals
        if progress_callback:
            progress_callback("Transcribing lyrics...")
        words = transcribe_words(vocals_wav, whisper_model, device, progress_callback)

        # 4. Render CDG
        duration = get_audio_duration(music_mp3, ffmpeg)
        if duration <= 0:
            duration = get_audio_duration(input_path, ffmpeg)

        cdg_path = work_dir / f"{base_name}.cdg"
        if words:
            build_cdg_from_words(words, duration, cdg_path)
        else:
            # Empty CDG
            build_cdg_from_words([], duration, cdg_path)

        # 5. Write human-readable lyrics text file
        if words:
            txt_path = write_lyrics_txt(words, work_dir / f"{base_name}.txt")
        else:
            txt_path = write_lyrics_txt([], work_dir / f"{base_name}.txt")

        # 6. Zip
        zip_path = output_dir / f"{base_name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(music_mp3, music_mp3.name)
            zf.write(vocals_mp3, vocals_mp3.name)
            zf.write(cdg_path, cdg_path.name)
            zf.write(txt_path, txt_path.name)

        return zip_path


def run_cli():
    parser = argparse.ArgumentParser(description="Stem Separator + Karaoke CDG Maker")
    parser.add_argument("input", help="Audio file to process")
    parser.add_argument("-o", "--output", help="Output folder (default: same as input)")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="Manufacturer prefix")
    parser.add_argument("--id", dest="song_id", default="0000", help="Song ID")
    parser.add_argument("--schema", default=DEFAULT_SCHEMA, help="Output filename schema")
    parser.add_argument("--artist", default="", help="Override artist")
    parser.add_argument("--title", default="", help="Override title")
    parser.add_argument("--stem-model", default="htdemucs", help="Demucs model")
    parser.add_argument("--whisper-model", default="medium", choices=["small", "medium", "large-v3"], help="Whisper model")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output) if args.output else input_path.parent

    def progress(msg: str):
        print(msg)

    zip_path = make_karaoke_zip(
        input_path,
        output_dir,
        prefix=args.prefix,
        song_id=args.song_id,
        schema=args.schema,
        artist=args.artist,
        title=args.title,
        stem_model=args.stem_model,
        whisper_model=args.whisper_model,
        device=args.device,
        progress_callback=progress,
    )

    print(f"\nDone: {zip_path}")


def run_gui():
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError:
        print("tkinter is not installed. Run in CLI mode.", file=sys.stderr)
        sys.exit(1)

    if not DEMUCS_AVAILABLE:
        messagebox.showerror("Missing Dependency", "demucs is not installed.")
        sys.exit(1)

    root = tk.Tk()
    root.title("GhostTrax")
    root.geometry("700x500")

    input_var = tk.StringVar()
    output_var = tk.StringVar()
    prefix_var = tk.StringVar(value=DEFAULT_PREFIX)
    id_var = tk.StringVar(value="0000")
    schema_var = tk.StringVar(value=DEFAULT_SCHEMA)
    artist_var = tk.StringVar()
    title_var = tk.StringVar()
    stem_model_var = tk.StringVar(value="htdemucs")
    whisper_var = tk.StringVar(value="medium")
    device_var = tk.StringVar(value="cpu")
    status_var = tk.StringVar(value="Ready")

    padding = {"padx": 10, "pady": 5}

    def browse_input():
        path = filedialog.askopenfilename(
            title="Select audio file",
            filetypes=[("Audio files", "*.mp3 *.wav *.flac *.m4a *.ogg *.wma *.aac"), ("All files", "*.*")],
        )
        if path:
            input_var.set(path)
            if not output_var.get():
                output_var.set(str(Path(path).parent))
            try:
                parsed = parse_filename(Path(path).name, prefix=prefix_var.get())
                artist_var.set(parsed.artist)
                title_var.set(parsed.title)
                if id_var.get() == "0000":
                    id_var.set(parsed.raw_id)
            except Exception:
                pass

    def browse_output():
        folder = filedialog.askdirectory()
        if folder:
            output_var.set(folder)

    # Input
    frame = ttk.Frame(root)
    frame.pack(fill=tk.X, **padding)
    ttk.Label(frame, text="Input file:").pack(side=tk.LEFT)
    ttk.Entry(frame, textvariable=input_var, width=55).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
    ttk.Button(frame, text="Browse…", command=browse_input).pack(side=tk.LEFT)

    # Output
    frame = ttk.Frame(root)
    frame.pack(fill=tk.X, **padding)
    ttk.Label(frame, text="Output folder:").pack(side=tk.LEFT)
    ttk.Entry(frame, textvariable=output_var, width=55).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
    ttk.Button(frame, text="Browse…", command=browse_output).pack(side=tk.LEFT)

    # Naming
    naming_frame = ttk.LabelFrame(root, text="Output Naming", padding=10)
    naming_frame.pack(fill=tk.X, **padding)

    frame = ttk.Frame(naming_frame)
    frame.pack(fill=tk.X, pady=2)
    ttk.Label(frame, text="Prefix:").pack(side=tk.LEFT)
    ttk.Entry(frame, textvariable=prefix_var, width=6).pack(side=tk.LEFT, padx=5)
    ttk.Label(frame, text="ID:").pack(side=tk.LEFT, padx=(20, 0))
    ttk.Entry(frame, textvariable=id_var, width=12).pack(side=tk.LEFT, padx=5)

    frame = ttk.Frame(naming_frame)
    frame.pack(fill=tk.X, pady=2)
    ttk.Label(frame, text="Artist:").pack(side=tk.LEFT)
    ttk.Entry(frame, textvariable=artist_var, width=25).pack(side=tk.LEFT, padx=5)
    ttk.Label(frame, text="Title:").pack(side=tk.LEFT, padx=(20, 0))
    ttk.Entry(frame, textvariable=title_var, width=25).pack(side=tk.LEFT, padx=5)

    frame = ttk.Frame(naming_frame)
    frame.pack(fill=tk.X, pady=2)
    ttk.Label(frame, text="Schema:").pack(side=tk.LEFT)
    ttk.Entry(frame, textvariable=schema_var, width=50).pack(side=tk.LEFT, padx=5)

    # Options
    opts_frame = ttk.LabelFrame(root, text="Processing Options", padding=10)
    opts_frame.pack(fill=tk.X, **padding)

    frame = ttk.Frame(opts_frame)
    frame.pack(fill=tk.X, pady=2)
    ttk.Label(frame, text="Stem model:").pack(side=tk.LEFT)
    ttk.Combobox(frame, textvariable=stem_model_var, values=["htdemucs", "htdemucs_ft", "mdx_extra", "mdx_extra_q"], state="readonly", width=15).pack(side=tk.LEFT, padx=5)
    ttk.Label(frame, text="Whisper:").pack(side=tk.LEFT, padx=(20, 0))
    ttk.Combobox(frame, textvariable=whisper_var, values=["small", "medium", "large-v3"], state="readonly", width=12).pack(side=tk.LEFT, padx=5)
    ttk.Label(frame, text="Device:").pack(side=tk.LEFT, padx=(20, 0))
    ttk.Combobox(frame, textvariable=device_var, values=["cpu", "cuda"], state="readonly", width=10).pack(side=tk.LEFT, padx=5)

    # Status and button
    status_label = ttk.Label(root, textvariable=status_var)
    status_label.pack(**padding)

    make_btn = ttk.Button(root, text="Make Karaoke Zip", padding=10)
    make_btn.pack(pady=20)

    def do_make():
        input_path = Path(input_var.get())
        output_dir = Path(output_var.get()) if output_var.get() else input_path.parent

        if not input_path.exists():
            messagebox.showerror("Error", f"File not found: {input_path}")
            return

        make_btn.config(state=tk.DISABLED)
        status_var.set("Starting...")

        def worker():
            try:
                def progress(msg: str):
                    root.after(0, lambda: status_var.set(msg))

                zip_path = make_karaoke_zip(
                    input_path,
                    output_dir,
                    prefix=prefix_var.get(),
                    song_id=id_var.get(),
                    schema=schema_var.get(),
                    artist=artist_var.get(),
                    title=title_var.get(),
                    stem_model=stem_model_var.get(),
                    whisper_model=whisper_var.get(),
                    device=device_var.get(),
                    progress_callback=progress,
                )
                root.after(0, lambda: status_var.set(f"Done: {zip_path.name}"))
                root.after(0, lambda: messagebox.showinfo("Done", f"Created:\n{zip_path}"))
            except Exception as e:
                root.after(0, lambda: status_var.set(f"Error: {e}"))
                root.after(0, lambda err=e: messagebox.showerror("Error", str(err)))
            finally:
                root.after(0, lambda: make_btn.config(state=tk.NORMAL))

        threading.Thread(target=worker, daemon=True).start()

    make_btn.config(command=do_make)
    root.mainloop()


def main():
    # PyInstaller windowed builds set sys.stdout/stderr to None on Windows.
    # Redirect to a null writer so any library print() calls don't crash.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    if len(sys.argv) > 1:
        run_cli()
    else:
        run_gui()


if __name__ == "__main__":
    main()
