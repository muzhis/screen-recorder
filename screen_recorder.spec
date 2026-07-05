# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path.cwd()
resource_dir = project_root / "screen_recorder" / "resources"
ffmpeg = resource_dir / "ffmpeg.exe"
ffmpeg_binaries = [(str(ffmpeg), "screen_recorder/resources")]
ffmpeg_binaries.extend((str(path), "screen_recorder/resources") for path in resource_dir.glob("*.dll"))

a = Analysis(
    ["screen_recorder/main.py"],
    pathex=[str(project_root)],
    binaries=ffmpeg_binaries,
    datas=[],
    hiddenimports=[
        "pyaudiowpatch",
        "sounddevice",
        "mss",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ScreenRecorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ScreenRecorder",
)
