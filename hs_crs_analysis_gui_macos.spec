# -*- mode: python ; coding: utf-8 -*-
#
# macOS (Apple Silicon) PyInstaller spec for HS-MOSAIC.
#
# Produces a native arm64 ``HS-MOSAIC.app`` bundle. GPU acceleration on Apple
# Silicon is provided by PyTorch's Metal (MPS) backend: the standard PyPI macOS
# torch wheel already includes MPS, and ``collect_dynamic_libs("torch")`` below
# bundles the torch dylibs into the app, so the shipped .app runs on the GPU
# automatically (no separate index URL or CUDA needed).
#
# Build with the companion ``build_macos.sh`` script, which creates a native
# arm64 build environment first. Building under an x86_64 (Rosetta) Python will
# silently produce an x86_64 app and can trigger torch/NumPy ABI mismatches.

import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

project_root = Path(SPECPATH).resolve()

# Keep the bundle version in sync with pyproject.toml so we do not hardcode it.
_app_version = "0.0.0"
try:
    _pyproject = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    _m = re.search(r'^version\s*=\s*"([^"]+)"', _pyproject, re.MULTILINE)
    if _m:
        _app_version = _m.group(1)
except Exception:
    pass

# Optional app icon. macOS needs a .icns (the bundled logo is a Windows .ico).
_icns = project_root / "hs_mosaic" / "assets" / "HS-MOSAIC-logo.icns"
icon_arg = str(_icns) if _icns.exists() else None

datas = []
datas += collect_data_files("qtawesome")
datas += collect_data_files("pyqtgraph")
datas += collect_data_files("hs_mosaic", subdir="assets")

binaries = []
binaries += collect_dynamic_libs("torch")  # ships the MPS-capable torch dylibs

excludes = [
    "torchvision",
    "torchaudio",
    "PySide2",
    "PySide6",
    "PyQt6",
]

a = Analysis(
    ["hs_mosaic/app.py"],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "hs_mosaic",
        "hs_mosaic.app",
        "hs_mosaic.composite_image",
        "hs_mosaic.widgets",
        "hs_mosaic.widgets.torch_nmf",
        "hs_mosaic.widgets.nnls_pytorch",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HS_MOSAIC",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",        # native Apple Silicon build
    codesign_identity=None,     # set to your "Developer ID Application: ..." to sign
    entitlements_file=None,
    icon=icon_arg,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="HS_MOSAIC",
)

app = BUNDLE(
    coll,
    name="HS-MOSAIC.app",
    icon=icon_arg,
    bundle_identifier="org.hsmosaic.app",
    info_plist={
        "CFBundleShortVersionString": _app_version,
        "CFBundleVersion": _app_version,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.3",  # Metal/MPS requires macOS 12.3+
    },
)
