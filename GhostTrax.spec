# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

# Locate the demucs package and bundle its remote/ data folder
import demucs
remote_dir = Path(demucs.__file__).parent / "remote"

base_path = Path(SPECPATH).resolve()
font_file = base_path / "src" / "assets" / "DejaVuSans-Bold.ttf"
font_license = base_path / "src" / "assets" / "DejaVuSans-LICENSE.txt"

block_cipher = None

hiddenimports_common = [
    'typing',
    'scipy',
    'scipy.io',
    'scipy.io.wavfile',
    'faster_whisper',
    'demucs',
    'demucs.pretrained',
    'demucs.model',
    'demucs.utils',
    'demucs.audio',
    'demucs.apply',
    'demucs.separator',
    'torch',
    'torchaudio',
    'numpy.core.multiarray',
    'numpy.core._multiarray_umath',
    'numpy.core.numeric',
]

a = Analysis(
    [str(base_path / 'src' / 'separator.py')],
    pathex=[str(base_path), str(base_path / 'src')],
    binaries=[],
    datas=[(str(remote_dir), 'demucs/remote'), (str(font_file), 'src/assets'), (str(font_license), 'src/assets')],
    hiddenimports=hiddenimports_common,
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
    name='GhostTrax',
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
)
