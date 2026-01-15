# -*- mode: python ; coding: utf-8 -*-
# vi: ft=python
from PyInstaller.utils.hooks import copy_metadata

datas = [
    ("back/src/echoroo/migrations", "echoroo/migrations"),
    ("back/src/echoroo/statics", "echoroo/statics"),
    ("back/src/echoroo/user_guide", "echoroo/user_guide"),
    ("back/alembic.ini", "."),
]

datas += copy_metadata("numpy", recursive=True)

a = Analysis(
    ["back/app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "app",
        "aiosqlite",
        "colorama",
        "logging.config",
        "passlib.handlers.bcrypt",
        "rasterio",
        "rasterio.sample",
        "rasterio._shim",
        "rasterio.control",
        "rasterio.crs",
        "rasterio.vrt",
        "rasterio._features",
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
    a.binaries,
    a.datas,
    [],
    name="echoroo",
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
