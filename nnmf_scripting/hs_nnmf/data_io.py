"""Loading hyperspectral stacks and spectral axes the way HS-MOSAIC does.

Nothing in here touches the HS-MOSAIC package -- it only mirrors the
conventions used by ``hs_mosaic.widgets.data_managers`` so a scripted run
sees exactly the same numbers as the GUI:

* stacks are ``(bands, Y, X)`` (ImageJ/tifffile convention, spectral axis first)
* TIFFs are brought into the GUI's 16-bit working range
* the spectral axis is rebuilt from a ``wavelength.json`` sidecar
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np
import tifffile

logger = logging.getLogger(__name__)

UINT16_MAX = int(np.iinfo(np.uint16).max)


def data_path(name: str | Path) -> Path:
    """Locate a dataset file without hard-coding an absolute path.

    Search order:

    1. ``name`` as given, absolute or relative to the working directory
    2. ``$HS_NNMF_DATA`` (and one level of subdirectories below it)
    3. ``nnmf_scripting/data/`` (and one level of subdirectories below it)

    So a script can name its dataset and still run on any machine: drop the
    file into ``nnmf_scripting/data/`` or point ``HS_NNMF_DATA`` at wherever
    the measurements live.

    Keep the ``wavelength.json`` sidecar in the same folder as the TIFF --
    :func:`load_dataset` reads the spectral axis from it and silently falls
    back to frame indices when it is missing.
    """
    candidate = Path(name).expanduser()
    if candidate.exists():
        return candidate

    roots: list[Path] = []
    env_root = os.environ.get("HS_NNMF_DATA")
    if env_root:
        roots.append(Path(env_root).expanduser())
    roots.append(Path(__file__).resolve().parents[1] / "data")

    for root in roots:
        direct = root / candidate.name
        if direct.exists():
            return direct
        if root.is_dir():
            for found in sorted(root.rglob(candidate.name)):
                return found

    searched = "\n  ".join(str(root) for root in roots)
    raise FileNotFoundError(
        f"Could not find '{candidate.name}'.\n"
        f"Put it (together with its wavelength.json) into one of:\n  {searched}\n"
        f"or set HS_NNMF_DATA to the folder holding the measurements, "
        f"or give an absolute path."
    )


def load_stack(path: str | Path, to_uint16: bool = True) -> np.ndarray:
    """Load a hyperspectral TIFF as a ``(bands, Y, X)`` stack.

    Mirrors ``ImageManager._prepare_loaded_tiff_dtype``: uint16 input is passed
    through untouched, everything else is shifted/scaled into 0..65535 instead
    of being allowed to wrap around.
    """
    path = Path(path)
    image = np.asarray(tifffile.imread(str(path)))
    if image.ndim != 3:
        raise ValueError(
            f"Expected a 3D (bands, Y, X) stack, got shape {image.shape} from {path.name}."
        )
    logger.info("Loaded %s: shape=%s dtype=%s", path.name, image.shape, image.dtype)
    if not to_uint16 or image.dtype == np.uint16:
        return image

    is_float_input = np.issubdtype(image.dtype, np.floating)
    if np.issubdtype(image.dtype, np.complexfloating):
        logger.warning("Complex TIFF %s: using absolute values.", path.name)
        image = np.abs(image)
        is_float_input = True

    working = np.asarray(image, dtype=np.float32)
    finite = np.isfinite(working)
    if not np.any(finite):
        logger.warning("TIFF %s contains no finite values; returning zeros.", path.name)
        return np.zeros(working.shape, dtype=np.uint16)

    min_val = float(np.min(working[finite]))
    max_val = float(np.max(working[finite]))
    if min_val < 0:
        logger.warning("TIFF %s has negative values (min %.6g); shifting.", path.name, min_val)
        working = working - min_val
        max_val -= min_val
        min_val = 0.0
    working = np.nan_to_num(working, nan=0.0, posinf=max_val, neginf=0.0)
    if max_val <= 0:
        return np.zeros(working.shape, dtype=np.uint16)

    if is_float_input or max_val > UINT16_MAX:
        logger.info("Scaling %s from [%.6g, %.6g] to 0..65535.", path.name, min_val, max_val)
        working = working * (UINT16_MAX / max_val)
    return np.clip(working, 0, UINT16_MAX).astype(np.uint16)


def wavenumbers_from_beams(
    n_frames: int,
    *,
    tuned_min_nm: float,
    tuned_max_nm: float | None = None,
    tuned_step_nm: float | None = None,
    fixed_beam_nm: float,
    tuned_beam: str = "pump",
) -> np.ndarray:
    """Rebuild the CRS wavenumber axis (cm-1) from the two beam wavelengths.

    Same arithmetic as ``WavenumberWidget.update_wavenums`` in Raman mode:
    the tuned beam is sampled linearly in nm and converted to a Raman shift
    against the fixed beam.
    """
    channels = max(1, int(n_frames))
    minimum = float(tuned_min_nm)
    if tuned_max_nm is not None:
        maximum = float(tuned_max_nm)
        if maximum < minimum:
            minimum, maximum = maximum, minimum
    elif tuned_step_nm is not None:
        maximum = minimum + float(tuned_step_nm) * (channels - 1)
    else:
        raise ValueError("Need either tuned_max_nm or tuned_step_nm.")

    lambdas_cm = np.linspace(minimum * 1e-7, maximum * 1e-7, channels, dtype=np.float64)
    k_var = np.reciprocal(lambdas_cm)
    k_fix = 1.0 / (float(fixed_beam_nm) * 1e-7)

    beam = str(tuned_beam).lower()
    if beam not in {"pump", "stokes"}:
        raise ValueError("tuned_beam must be 'pump' or 'stokes'.")
    wavenumbers = (k_var - k_fix) if beam == "pump" else (k_fix - k_var)
    return wavenumbers.astype(np.float32)


def wavenumbers_from_json(path: str | Path, n_frames: int) -> tuple[np.ndarray, str]:
    """Read a HS-MOSAIC ``wavelength.json`` and return ``(wavenumbers, unit)``.

    Supports both flavours the GUI writes: an explicit ``custom_values`` axis
    and the calculated pump/Stokes axis.
    """
    meta = json.loads(Path(path).read_text(encoding="utf-8"))

    custom_values = meta.get("custom_values")
    if custom_values is not None:
        values = np.asarray(custom_values, dtype=np.float32)
        if values.size != n_frames:
            logger.warning(
                "wavelength.json has %s custom values but the stack has %s frames.",
                values.size, n_frames,
            )
        return values, str(meta.get("spectral_unit", "index"))

    wavenumbers = wavenumbers_from_beams(
        n_frames,
        tuned_min_nm=meta["tuned_min_nm"],
        tuned_max_nm=meta.get("tuned_max_nm"),
        tuned_step_nm=meta.get("tuned_step_nm"),
        fixed_beam_nm=meta["fixed_beam_nm"],
        tuned_beam=meta.get("tuned_beam", "pump"),
    )
    return wavenumbers, str(meta.get("spectral_unit", "cm-1"))


def load_dataset(
    tif_path: str | Path,
    wavelength_json: str | Path | None = None,
) -> tuple[np.ndarray, np.ndarray, str]:
    """Load a stack plus its spectral axis.

    ``wavelength_json`` defaults to a ``wavelength.json`` sitting next to the
    TIFF (the sidecar the GUI looks for on load). Without one, the axis falls
    back to frame indices.

    Returns ``(stack (bands, Y, X), wavenumbers (bands,), unit)``.
    """
    tif_path = Path(tif_path)
    stack = load_stack(tif_path)
    n_frames = stack.shape[0]

    if wavelength_json is None:
        candidate = tif_path.parent / "wavelength.json"
        wavelength_json = candidate if candidate.exists() else None

    if wavelength_json is None:
        logger.warning("No wavelength.json found next to %s; using frame indices.", tif_path.name)
        return stack, np.arange(n_frames, dtype=np.float32), "index"

    wavenumbers, unit = wavenumbers_from_json(wavelength_json, n_frames)
    logger.info(
        "Spectral axis from %s: %.1f ... %.1f %s (%s frames)",
        Path(wavelength_json).name, float(wavenumbers[0]), float(wavenumbers[-1]), unit, n_frames,
    )
    return stack, wavenumbers, unit


def band_index(wavenumbers: np.ndarray, target: float) -> int:
    """Index of the band closest to ``target`` (axis may be ascending or not)."""
    return int(np.argmin(np.abs(np.asarray(wavenumbers, dtype=float) - float(target))))
