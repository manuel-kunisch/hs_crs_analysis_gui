"""Seed definitions and the parameter set for a scripted NNMF run.

Every field here maps onto a control the HS-MOSAIC GUI exposes for custom
(seeded) NNMF, so a script can reproduce a GUI run without opening it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Sequence

import numpy as np
from scipy.ndimage import gaussian_filter1d

# Canonical W-seed modes accepted by MultivariateAnalyzer.set_W_seed_mode.
W_SEED_MODES = ("nnls", "selective_score", "h_weighted", "average", "empty")


@dataclass
class Roi:
    """A spatial seed: the mean spectrum inside a region becomes the H seed.

    Give the region as one of

    * ``rect=(y0, x0, height, width)``  -- the GUI's rectangular ROI
    * ``pixels=[(y, x), ...]``          -- explicit coordinate indices
    * ``mask=<bool (Y, X) array>``      -- an arbitrary region

    ``sigma`` / ``scale`` / ``offset`` mirror the ROI table columns
    (Gaussian sigma, Scale, Offset). Several ROIs on the same component are
    averaged, exactly like ``get_roi_mean_curves`` does in the GUI.
    """

    component: int
    rect: tuple[int, int, int, int] | None = None
    pixels: Sequence[tuple[int, int]] | np.ndarray | None = None
    mask: np.ndarray | None = None
    name: str = ""
    is_background: bool = False
    sigma: float = 0.0
    scale: float = 1.0
    offset: float = 0.0
    use_subtracted: bool = True

    @classmethod
    def from_center(cls, component: int, y: int, x: int, size: int = 9, **kwargs) -> "Roi":
        """Square ROI of ``size`` px centred on the pixel index ``(y, x)``."""
        half = int(size) // 2
        return cls(component=component, rect=(int(y) - half, int(x) - half, int(size), int(size)), **kwargs)

    def indices(self, shape_yx: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
        """Pixel indices of this ROI, clipped to the image."""
        height, width = shape_yx
        if self.mask is not None:
            mask = np.asarray(self.mask, dtype=bool)
            if mask.shape != shape_yx:
                raise ValueError(f"ROI mask shape {mask.shape} does not match image {shape_yx}.")
            return np.nonzero(mask)
        if self.pixels is not None:
            pixels = np.asarray(self.pixels, dtype=int).reshape(-1, 2)
            rows = np.clip(pixels[:, 0], 0, height - 1)
            cols = np.clip(pixels[:, 1], 0, width - 1)
            return rows, cols
        if self.rect is not None:
            y0, x0, roi_h, roi_w = (int(v) for v in self.rect)
            y0, x0 = max(y0, 0), max(x0, 0)
            y1, x1 = min(y0 + roi_h, height), min(x0 + roi_w, width)
            if y1 <= y0 or x1 <= x0:
                raise ValueError(f"ROI {self.label} lies outside the image {shape_yx}.")
            rows, cols = np.mgrid[y0:y1, x0:x1]
            return rows.ravel(), cols.ravel()
        raise ValueError(f"ROI {self.label} defines no region (set rect, pixels or mask).")

    def spectrum(self, stack: np.ndarray) -> np.ndarray:
        """Mean spectrum over the region, with the ROI table's post-processing.

        Same order of operations as ``ROIManager.get_roi_average``:
        mean -> offset (clip negatives) -> scale -> Gaussian smoothing.
        """
        rows, cols = self.indices(stack.shape[1:])
        spectrum = np.asarray(stack[:, rows, cols], dtype=np.float64).mean(axis=1)
        if self.offset:
            spectrum = spectrum + float(self.offset)
            spectrum[spectrum < 0] = 0.0
        if self.scale != 1.0:
            spectrum = spectrum * float(self.scale)
        if self.sigma and self.sigma > 0:
            spectrum = gaussian_filter1d(spectrum, float(self.sigma))
        return spectrum

    @property
    def label(self) -> str:
        return self.name or f"component {self.component}"

    @property
    def n_pixels_hint(self) -> str:
        if self.rect is not None:
            return f"rect(y0={self.rect[0]}, x0={self.rect[1]}, h={self.rect[2]}, w={self.rect[3]})"
        if self.pixels is not None:
            return f"{len(np.asarray(self.pixels).reshape(-1, 2))} pixels"
        return "mask"


@dataclass
class SpectralSeed:
    """A spectral seed: a resonance window feeds the W seed of a component.

    Equivalent to one row of the GUI's resonance table. Only used when
    ``NNMFParams.spectral_seeds`` is non-empty; H seeds still come from ROIs,
    VCA or the analyzer's fallbacks.
    """

    component: int
    wavenumber: float
    width: float
    use_subtracted: bool = True

    def as_info(self) -> dict[str, Any]:
        return {
            "Component": int(self.component),
            "Wavenumber": float(self.wavenumber),
            "Width": float(self.width),
            "Use subtracted data": bool(self.use_subtracted),
        }


@dataclass
class VcaParams:
    """Vertex Component Analysis settings for unsupervised H seeds."""

    enabled: bool = False
    n_endmembers: int | None = None  # defaults to n_components
    seed: int | None = 0
    clip_negative: bool = True
    use_subtracted: bool = False


@dataclass
class NNMFParams:
    """Everything the GUI lets you set for a custom-init NNMF run."""

    n_components: int = 3

    # --- initialization -------------------------------------------------
    # 'random' -> plain NMF with random init (GUI: custom init unchecked)
    # 'custom' -> seeded NNMF (GUI: custom init checked)
    init: str = "custom"
    rois: list[Roi] = field(default_factory=list)
    spectral_seeds: list[SpectralSeed] = field(default_factory=list)
    h_seeds: dict[int, np.ndarray] = field(default_factory=dict)
    fixed_w_seeds: dict[int, np.ndarray] = field(default_factory=dict)
    vca: VcaParams = field(default_factory=VcaParams)
    # Components to flag as non-resonant background (GUI: ROI 'Background'
    # checkbox). Background components are seeded from raw instead of
    # background-subtracted data. ROIs with is_background=True are added
    # to this set automatically.
    background_components: tuple[int, ...] = ()

    # --- W seed estimation (GUI: "W seed from H" block) ------------------
    w_seed_mode: str = "nnls"
    w_seed_downsample: int = 4
    normalize_w_seed: bool = True
    overwrite_w_from_h: bool = True
    normalize_h_to_unity: bool = True

    # --- solver ----------------------------------------------------------
    solver: str = "mu"          # 'mu' or 'cd'
    backend: str = "gpu"        # 'gpu' (torch, falls back to CPU torch) or 'cpu' (sklearn)
    max_iter: int = 500
    tol: float = 1e-4
    patience: int = 1
    use_compile: bool = False
    nnls_max_iter: int = 500
    nnls_tol: float = 1e-4

    # --- data preparation -------------------------------------------------
    # Optional background ROI: its mean spectrum is subtracted from the stack
    # to build the "subtracted data" the seed estimation can use (GUI:
    # the ROI 'Subtract' checkbox). The NNMF itself always runs on raw data.
    background_roi: Roi | None = None

    def validate(self) -> None:
        if self.init not in {"random", "custom"}:
            raise ValueError("init must be 'random' or 'custom'.")
        if self.w_seed_mode not in W_SEED_MODES:
            raise ValueError(f"w_seed_mode must be one of {W_SEED_MODES}, got {self.w_seed_mode!r}.")
        if self.solver not in {"mu", "cd"}:
            raise ValueError("solver must be 'mu' or 'cd'.")
        if self.backend not in {"gpu", "cpu"}:
            raise ValueError("backend must be 'gpu' or 'cpu'.")
        if self.n_components < 1:
            raise ValueError("n_components must be >= 1.")
        for roi in self.rois:
            if not 0 <= roi.component < self.n_components:
                raise ValueError(
                    f"ROI '{roi.label}' targets component {roi.component}, "
                    f"outside 0..{self.n_components - 1}."
                )
        for component in self.h_seeds:
            if not 0 <= int(component) < self.n_components:
                raise ValueError(f"h_seeds key {component} is outside 0..{self.n_components - 1}.")

    def describe(self) -> dict[str, Any]:
        """JSON-serialisable summary for the run log / sidecar."""
        summary = {
            key: value
            for key, value in asdict(self).items()
            if key not in {"rois", "spectral_seeds", "h_seeds", "fixed_w_seeds", "vca", "background_roi"}
        }
        summary["vca"] = asdict(self.vca)
        summary["rois"] = [
            {
                "component": roi.component,
                "name": roi.name,
                "region": roi.n_pixels_hint,
                "is_background": roi.is_background,
                "sigma": roi.sigma,
                "scale": roi.scale,
                "offset": roi.offset,
            }
            for roi in self.rois
        ]
        summary["spectral_seeds"] = [seed.as_info() for seed in self.spectral_seeds]
        summary["h_seeds"] = sorted(int(k) for k in self.h_seeds)
        summary["fixed_w_seeds"] = sorted(int(k) for k in self.fixed_w_seeds)
        summary["background_roi"] = None if self.background_roi is None else self.background_roi.n_pixels_hint
        return summary
