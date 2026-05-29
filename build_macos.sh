#!/usr/bin/env bash
#
# Build a native Apple Silicon (arm64) HS-MOSAIC.app and package it into a .dmg.
#
# GPU acceleration: the macOS PyPI torch wheel includes the Metal (MPS) backend,
# so installing torch here is all that is needed for GPU acceleration on M-series
# Macs. The .spec bundles the torch dylibs into the .app.
#
# Usage:
#   chmod +x build_macos.sh
#   ./build_macos.sh                # builds version from pyproject.toml
#   ./build_macos.sh 0.9.5          # override the version label on the .dmg
#
# Requirements:
#   - A native arm64 Python 3.10+ (NOT x86_64 under Rosetta).
#   - Xcode command line tools (for iconutil / hdiutil / codesign).
#   - Optional: `brew install create-dmg` for a nicer drag-to-Applications DMG.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# Version: argument wins, else read from pyproject.toml.
if [[ "${1:-}" != "" ]]; then
    VERSION="$1"
else
    VERSION="$(sed -n 's/^version *= *"\(.*\)"/\1/p' pyproject.toml | head -1)"
    VERSION="${VERSION:-0.0.0}"
fi
echo ">> Building HS-MOSAIC v${VERSION} for Apple Silicon"

# --- 0) Refuse to build under Rosetta / x86_64 -------------------------------
python3 - <<'PY'
import platform, sys
if platform.machine() != "arm64":
    sys.exit(
        "ERROR: this Python is '%s', not arm64.\n"
        "Use a native Apple Silicon Python (e.g. arm64 Homebrew python3 or an\n"
        "arm64 conda env). Building under Rosetta produces an x86_64 app and can\n"
        "cause torch/NumPy ABI mismatches." % platform.machine()
    )
print(">> OK: native arm64 Python", platform.python_version())
PY

# --- 1) Fresh native build environment ---------------------------------------
VENV="$ROOT/.venv-build-macos"
python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt pyinstaller pillow
# macOS PyPI torch wheel ships with MPS (Metal) GPU support built in.
python -m pip install --upgrade torch

# --- 2) Verify MPS GPU acceleration is present -------------------------------
python - <<'PY'
import torch
mps_built = getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_built()
mps_ok = mps_built and torch.backends.mps.is_available()
print(">> torch:", torch.__version__)
print(">> MPS built:", mps_built, "| MPS available:", mps_ok)
if not mps_built:
    raise SystemExit("ERROR: this torch wheel has no MPS backend; install the "
                     "standard macOS torch wheel (pip install torch).")
# is_available() can be False on macOS < 12.3 or in some CI; that is fine for
# building, the shipped app will use MPS on a capable machine.
PY

# --- 3) Best-effort: generate the .icns app icon -----------------------------
# Optional and non-fatal. Prefers a high-res PNG (hs_mosaic/assets/HS-MOSAIC-logo.png),
# falls back to the bundled Windows .ico. A non-square logo is centered on a
# transparent square canvas so macOS does not distort it.
python - <<'PY' || echo ">> (icon generation skipped; using default app icon)"
import subprocess, tempfile
from pathlib import Path
icns = Path("hs_mosaic/assets/HS-MOSAIC-logo.icns")
if icns.exists():
    raise SystemExit(0)
src = None
for cand in ("HS-MOSAIC-logo.png", "HS-MOSAIC-logo.ico"):
    p = Path("hs_mosaic/assets") / cand
    if p.exists():
        src = p
        break
if src is None:
    raise SystemExit(0)
from PIL import Image
img = Image.open(src).convert("RGBA")
# macOS app icons are square. Pad a non-square logo onto a transparent square
# canvas (centered) instead of stretching it.
w, h = img.size
side = max(w, h)
if w != h:
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - w) // 2, (side - h) // 2), img)
    img = canvas
base = img.resize((1024, 1024), Image.LANCZOS)
with tempfile.TemporaryDirectory() as d:
    iconset = Path(d) / "icon.iconset"
    iconset.mkdir()
    for s in (16, 32, 64, 128, 256, 512):
        base.resize((s, s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
        base.resize((s * 2, s * 2), Image.LANCZOS).save(iconset / f"icon_{s}x{s}@2x.png")
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)], check=True)
print(">> Generated", icns, "from", src)
PY

# --- 4) Build the .app --------------------------------------------------------
python -m PyInstaller --noconfirm --clean hs_crs_analysis_gui_macos.spec

APP="$ROOT/dist/HS-MOSAIC.app"
if [[ ! -d "$APP" ]]; then
    echo "ERROR: expected $APP was not produced." >&2
    exit 1
fi

# --- 5) Package into a .dmg ---------------------------------------------------
DMG="$ROOT/dist/HS_MOSAIC_AppleSilicon_v${VERSION}.dmg"
rm -f "$DMG"
if command -v create-dmg >/dev/null 2>&1; then
    create-dmg \
        --volname "HS-MOSAIC ${VERSION}" \
        --app-drop-link 450 160 \
        --icon "HS-MOSAIC.app" 150 160 \
        --window-size 640 320 \
        "$DMG" "$APP"
else
    echo ">> create-dmg not found (brew install create-dmg for a nicer layout); using hdiutil."
    hdiutil create -volname "HS-MOSAIC ${VERSION}" -srcfolder "$APP" -ov -format UDZO "$DMG"
fi

echo ""
echo ">> Done: $DMG"
echo ">> The app/DMG is UNSIGNED. See build_macos.sh header and the docs for"
echo ">> Gatekeeper notes (codesign + notarize, or the xattr quarantine workaround)."
