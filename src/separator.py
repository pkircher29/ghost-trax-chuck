import os
import re
import sys
import argparse
import tempfile
import subprocess
import threading
from pathlib import Path

# Try to import demucs; if not available we print instructions
try:
    from demucs.apply import apply_model
    from demucs.audio import AudioFile, save_audio
    from demucs.pretrained import get_model
    from demucs.model import load_model
    DEMUCS_AVAILABLE = True
except Exception:
    DEMUCS_AVAILABLE = False


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
    """Remove characters that might break filesystem paths."""
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def ensure_wav(input_path: Path, work_dir: Path, ffmpeg: str) -> Path:
    """Convert input to 16-bit 44.1kHz mono or stereo WAV for Demucs."""
    wav_path = work_dir / (sanitize_filename(input_path.stem) + "_converted.wav")
    cmd = [
        ffmpeg,
        "-y",
        "-i", str(input_path),
        "-ac", "2",
        "-ar", "44100",
        "-sample_fmt", "s16",
        str(wav_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {result.stderr}")
    return wav_path


def separate_file(
    input_path: Path,
    output_dir: Path,
    model: str = "htdemucs",
    device: str = "cpu",
    progress_callback=None,
) -> tuple[Path, Path]:
    """Separate input audio into vocals.wav and music.wav."""
    if not DEMUCS_AVAILABLE:
        raise RuntimeError(
            "demucs is not installed. Install it with: pip install demucs"
        )

    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = get_ffmpeg_path()

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        wav_path = ensure_wav(input_path, work_dir, ffmpeg)

        if progress_callback:
            progress_callback("Loading Demucs model...")

        model_obj = get_model(model)
        model_obj.to(device)

        if progress_callback:
            progress_callback("Separating stems...")

        audio = AudioFile(wav_path).read(streams=0, channels=2)
        sources = apply_model(model_obj, audio, device=device, progress=True)

        # sources shape: (sources, channels, time)
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

        base_name = sanitize_filename(input_path.stem)
        vocals_path = output_dir / f"{base_name}_vocals.wav"
        music_path = output_dir / f"{base_name}_music.wav"

        save_audio(vocals, str(vocals_path), samplerate=sample_rate)
        if music is not None:
            save_audio(music, str(music_path), samplerate=sample_rate)

        return vocals_path, music_path


def run_cli():
    parser = argparse.ArgumentParser(description="Stem Separator")
    parser.add_argument("input", help="Audio file to separate")
    parser.add_argument("-o", "--output", help="Output folder (default: same as input)")
    parser.add_argument("-m", "--model", default="htdemucs", help="Demucs model (default: htdemucs)")
    parser.add_argument("-d", "--device", default="cpu", choices=["cpu", "cuda"], help="Device (default: cpu)")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output) if args.output else input_path.parent

    def progress(msg: str):
        print(msg)

    print(f"Separating: {input_path}")
    print(f"Output folder: {output_dir}")
    print(f"Model: {args.model}, Device: {args.device}")

    vocals, music = separate_file(
        input_path,
        output_dir,
        model=args.model,
        device=args.device,
        progress_callback=progress,
    )

    print(f"\nDone:")
    print(f"  vocals: {vocals}")
    print(f"  music:  {music}")


def run_gui():
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError:
        print("tkinter is not installed. Run in CLI mode.", file=sys.stderr)
        sys.exit(1)

    if not DEMUCS_AVAILABLE:
        messagebox.showerror(
            "Missing Dependency",
            "demucs is not installed.\n\nInstall it with:\npip install demucs",
        )
        sys.exit(1)

    root = tk.Tk()
    root.title("Stem Separator")
    root.geometry("600x300")

    input_var = tk.StringVar()
    output_var = tk.StringVar()
    status_var = tk.StringVar(value="Ready")
    model_var = tk.StringVar(value="htdemucs")
    device_var = tk.StringVar(value="cpu")

    padding = {"padx": 10, "pady": 5}

    # Input file
    frame = ttk.Frame(root)
    frame.pack(fill=tk.X, **padding)
    ttk.Label(frame, text="Input file:").pack(side=tk.LEFT)
    ttk.Entry(frame, textvariable=input_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

    def browse_input():
        path = filedialog.askopenfilename(
            title="Select audio file",
            filetypes=[
                ("Audio files", "*.mp3 *.wav *.flac *.m4a *.ogg *.wma *.aac"),
                ("All files", "*.*"),
            ],
        )
        if path:
            input_var.set(path)
            if not output_var.get():
                output_var.set(str(Path(path).parent))

    ttk.Button(frame, text="Browse…", command=browse_input).pack(side=tk.LEFT)

    # Output folder
    frame = ttk.Frame(root)
    frame.pack(fill=tk.X, **padding)
    ttk.Label(frame, text="Output folder:").pack(side=tk.LEFT)
    ttk.Entry(frame, textvariable=output_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

    def browse_output():
        folder = filedialog.askdirectory()
        if folder:
            output_var.set(folder)

    ttk.Button(frame, text="Browse…", command=browse_output).pack(side=tk.LEFT)

    # Options
    frame = ttk.Frame(root)
    frame.pack(fill=tk.X, **padding)
    ttk.Label(frame, text="Model:").pack(side=tk.LEFT)
    model_combo = ttk.Combobox(frame, textvariable=model_var, values=["htdemucs", "htdemucs_ft", "mdx_extra", "mdx_extra_q"], state="readonly", width=15)
    model_combo.pack(side=tk.LEFT, padx=5)
    ttk.Label(frame, text="Device:").pack(side=tk.LEFT, padx=(20, 0))
    device_combo = ttk.Combobox(frame, textvariable=device_var, values=["cpu", "cuda"], state="readonly", width=10)
    device_combo.pack(side=tk.LEFT, padx=5)

    # Status
    status_label = ttk.Label(root, textvariable=status_var)
    status_label.pack(**padding)

    # Separate button
    separate_btn = ttk.Button(root, text="Separate", padding=10)
    separate_btn.pack(pady=20)

    def do_separate():
        input_path = Path(input_var.get())
        output_dir = Path(output_var.get()) if output_var.get() else input_path.parent

        if not input_path.exists():
            messagebox.showerror("Error", f"File not found: {input_path}")
            return

        separate_btn.config(state=tk.DISABLED)
        status_var.set("Starting...")

        def worker():
            try:
                def progress(msg: str):
                    root.after(0, lambda: status_var.set(msg))

                vocals, music = separate_file(
                    input_path,
                    output_dir,
                    model=model_var.get(),
                    device=device_var.get(),
                    progress_callback=progress,
                )
                root.after(0, lambda: status_var.set(f"Done: {vocals.name}, {music.name}"))
                root.after(0, lambda: messagebox.showinfo("Done", f"vocals: {vocals}\nmusic: {music}"))
            except Exception as e:
                root.after(0, lambda: status_var.set(f"Error: {e}"))
                root.after(0, lambda err=e: messagebox.showerror("Error", str(err)))
            finally:
                root.after(0, lambda: separate_btn.config(state=tk.NORMAL))

        threading.Thread(target=worker, daemon=True).start()

    separate_btn.config(command=do_separate)

    root.mainloop()


def main():
    if len(sys.argv) > 1:
        run_cli()
    else:
        run_gui()


if __name__ == "__main__":
    main()
