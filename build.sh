#!/bin/bash
# build.sh — Build StemSeparator single-file executable.

set -euo pipefail

cd "$(dirname "$0")"

# Clean old builds
rm -rf build dist

# Make sure ffmpeg is available to bundle
if ! command -v ffmpeg &> /dev/null; then
    echo "Error: ffmpeg not found in PATH. Please install ffmpeg."
    exit 1
fi

# Install pyinstaller if missing
if ! python3 -m PyInstaller --version &> /dev/null; then
    echo "Installing PyInstaller..."
    pip3 install --user pyinstaller
fi

# Build single-file executable
python3 -m PyInstaller StemSeparator.spec --clean

echo "Build complete. Output: dist/StemSeparator"
ls -lh dist/
