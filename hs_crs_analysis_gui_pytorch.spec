# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


project_root = Path(SPECPATH).resolve()

datas = []
datas += collect_data_files("qtawesome")
datas += collect_data_files("pyqtgraph")
datas += collect_data_files("hs_mosaic", subdir="assets")

binaries = []
binaries += collect_dynamic_libs("torch")

hiddenimports = [
    "hs_mosaic",
    "hs_mosaic.app",
    "hs_mosaic.composite_image",
    "hs_mosaic.widgets",
    "hs_mosaic.widgets.torch_devices",
    "hs_mosaic.widgets.torch_nmf",
    "hs_mosaic.widgets.nnls_pytorch",
]

# Optional DirectML plugin (GPU acceleration on AMD Radeon / any DirectX-12
# GPU on Windows). Bundled only when it is installed in the build environment,
# i.e. when build_windows_pytorch.ps1 was run with -DirectML. DirectML.dll
# lives inside the package, the native extension next to it in site-packages.
try:
    import torch_directml  # noqa: F401
except Exception:
    pass
else:
    binaries += collect_dynamic_libs("torch_directml")
    datas += collect_data_files("torch_directml")
    hiddenimports += ["torch_directml", "torch_directml_native"]

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
    hiddenimports=hiddenimports,
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
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "hs_mosaic" / "assets" / "HS-MOSAIC-logo.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="HS_MOSAIC_PyTorch",
)
