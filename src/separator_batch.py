#!/usr/bin/env python3
"""Batch processing wrapper for GhostTrax.

Usage:
    python separator_batch.py --batch input_folder/ output_folder/
    python separator_batch.py --batch input_folder/ output_folder/ --concurrent 2
"""

import sys
import argparse
import json
import time
from pathlib import Path
from typing import List, Optional

# Import from main module
from separator import make_karaoke_zip, parse_filename, DEFAULT_PREFIX, DEFAULT_SCHEMA


def find_audio_files(input_dir: Path, extensions: tuple = (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".wma", ".aac")) -> List[Path]:
    """Find all audio files in directory."""
    files = []
    for ext in extensions:
        files.extend(input_dir.rglob(f"*{ext}"))
    return sorted(files)


def process_batch(
    input_files: List[Path],
    output_dir: Path,
    prefix: str = DEFAULT_PREFIX,
    schema: str = DEFAULT_SCHEMA,
    stem_model: str = "htdemucs",
    whisper_model: str = "medium",
    device: str = "cpu",
    status_callback=None,
) -> List[Path]:
    """Process multiple files in sequence."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results = []
    for i, input_path in enumerate(input_files):
        try:
            if status_callback:
                status_callback(f"[{i+1}/{len(input_files)}] Processing {input_path.name}...")
            
            zip_path = make_karaoke_zip(
                input_path=input_path,
                output_dir=output_dir,
                prefix=prefix,
                schema=schema,
                stem_model=stem_model,
                whisper_model=whisper_model,
                device=device,
                progress_callback=lambda msg: status_callback(msg) if status_callback else None,
            )
            results.append(zip_path)
            
            if status_callback:
                status_callback(f"Done: {zip_path.name}")
        except Exception as e:
            if status_callback:
                status_callback(f"Error processing {input_path.name}: {e}")
    
    return results


def run_batch():
    parser = argparse.ArgumentParser(description="GhostTrax Batch Processor")
    parser.add_argument("input", help="Input folder or list file")
    parser.add_argument("output", help="Output folder")
    parser.add_argument("--list", action="store_true", help="Input file is a text list of paths")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="Manufacturer prefix")
    parser.add_argument("--schema", default=DEFAULT_SCHEMA, help="Output filename schema")
    parser.add_argument("--stem-model", default="htdemucs", help="Demucs model")
    parser.add_argument("--whisper-model", default="medium", choices=["small", "medium", "large-v3"], help="Whisper model")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"], help="Device")
    parser.add_argument("--quiet", action="store_true", help="Only print errors")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.list:
        # Read from list file
        with open(input_path, "r") as f:
            input_files = [Path(line.strip()) for line in f if line.strip()]
    elif input_path.is_dir():
        input_files = find_audio_files(input_path)
    else:
        print(f"Error: {input_path} is not a folder", file=sys.stderr)
        sys.exit(1)

    if not input_files:
        print("No audio files found", file=sys.stderr)
        sys.exit(1)

    if not args.quiet:
        print(f"Processing {len(input_files)} files...")

    def status(msg: str):
        print(msg)

    start_time = time.time()
    results = process_batch(
        input_files=input_files,
        output_dir=output_dir,
        prefix=args.prefix,
        schema=args.schema,
        stem_model=args.stem_model,
        whisper_model=args.whisper_model,
        device=args.device,
        status_callback=status if not args.quiet else None,
    )
    
    elapsed = time.time() - start_time
    print(f"\nCompleted {len(results)}/{len(input_files)} files in {elapsed:.1f}s")
    
    if results:
        print("\nOutput files:")
        for r in results:
            print(f"  {r}")


if __name__ == "__main__":
    run_batch()