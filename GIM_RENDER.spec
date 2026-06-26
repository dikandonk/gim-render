# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for GIM RENDER."""

import sys
from pathlib import Path

block_cipher = None

added_files = []
if (Path(__file__).parent / "efek").exists():
    added_files.append(("efek", "efek"))
if (Path(__file__).parent / "assets").exists():
    added_files.append(("assets", "assets"))

hidden_imports = [
    "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFilter", "PIL.ImageFont",
    "librosa", "numpy", "scipy", "scipy.signal",
    "moviepy", "moviepy.editor", "moviepy.video", "moviepy.audio",
    "mutagen", "mutagen.mp3", "mutagen.id3",
    "tqdm", "tkinter",
    "pillow_heif",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
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

exe_name = "GIM_RENDER"
if sys.platform == "win32":
    exe_name += ".exe"

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=exe_name,
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
)

app = BUNDLE(
    exe,
    name=f"{exe_name}.app",
    icon=None,
    bundle_identifier="com.gimblong.render",
)
