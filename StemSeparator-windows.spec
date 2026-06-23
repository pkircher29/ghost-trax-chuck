# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

block_cipher = None
base_path = Path(SPECPATH)

# ffmpeg.exe must be placed next to this spec before building
ffmpeg_path = str(base_path / 'ffmpeg.exe')

a = Analysis(
    [str(base_path / 'src' / 'separator.py')],
    pathex=[str(base_path), str(base_path / 'src')],
    binaries=[(ffmpeg_path, '.')],
    datas=[],
    hiddenimports=[
        'demucs.apply',
        'demucs.audio',
        'demucs.pretrained',
        'demucs.model',
        'demucs.hdemucs',
        'demucs.solver',
        'demucs.utils',
        'torch',
        'torchaudio',
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
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
