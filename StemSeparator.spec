# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

# Locate the demucs package and bundle its remote/ data folder
import demucs
remote_dir = Path(demucs.__file__).parent / "remote"

block_cipher = None
base_path = Path(SPECPATH)

# Locate bundled ffmpeg binary
ffmpeg_path = "/usr/bin/ffmpeg"

a = Analysis(
    [str(base_path / 'src' / 'separator.py')],
    pathex=[str(base_path), str(base_path / 'src')],
    binaries=[(ffmpeg_path, '.')],
    datas=[(str(remote_dir), 'demucs/remote')],
    hiddenimports=[
        'numpy.core.multiarray',
        'numpy.core._multiarray_umath',
        'scipy',
        'scipy.io',
        'scipy.io.wavfile',
        'demucs.apply',
        'demucs.audio',
        'demucs.pretrained',
        'demucs.hdemucs',
        'demucs.htdemucs',
        'demucs.solver',
        'demucs.utils',
        'demucs.states',
        'demucs.repo',
        'demucs.distrib',
        'torch',
        'torchaudio',
        'tqdm',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='StemSeparator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
