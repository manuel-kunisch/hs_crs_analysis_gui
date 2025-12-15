# What this provides:
#   1) RollingBallCorrectionController (QObject)
#      - apply(img) to correct 2D (y,x) or 3D (z,y,x) images
#      - load_reference_fit(img) to estimate dx,dy,sigma_x,sigma_y (+amp/offset) from a reference TIFF
#      - stores a reference MODEL (not just a field), supports anisotropic sigma_x / sigma_y
#      - snapshot() for thread-safe use in stitching workers
#
#   2) RollingBallCorrectionWidget (QWidget)
#      - Button: "Load reference TIFF…" -> opens preview dialog with crosshair
#      - OK in preview dialog:
#           * stores the fitted MODEL in the controller
#           * updates GUI immediately with dx/dy and sigma_x/sigma_y
#           * shows selected filename
#      - Button: "Show reference fit preview…" reopens the exact fit preview
#      - Button: "Preview last applied field…" shows last field used in apply()
#
# Typical integration:
#   self.illum_corr = RollingBallCorrectionController()
#   self.illum_widget = RollingBallCorrectionWidget(self.illum_corr)
#   # In your load pipeline OR per-tile in stitching:
#   img = self.illum_corr.apply(img)
#
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Callable, Dict

import numpy as np
from PyQt5 import QtCore, QtWidgets
import pyqtgraph as pg

try:
    from scipy.ndimage import gaussian_filter
except Exception:  # pragma: no cover
    gaussian_filter = None

try:
    from scipy.optimize import curve_fit
except Exception:  # pragma: no cover
    curve_fit = None


# --------------------------
# Config / Model
# --------------------------

@dataclass
class GaussianReferenceModel:
    # stored relative to the reference image center:
    dx_px: float
    dy_px: float
    sigma_x_px: float
    sigma_y_px: float

    # semantics:
    # amp    -> correction strength (0..inf). 1 is typical. >1 exaggerates correction.
    # offset -> gaussian floor in [0..1). 0 means pure gaussian. >0 prevents extreme gains.
    amp: float = 1.0
    offset: float = 0.0

    # reference image shape used for scaling when new shapes differ:
    ref_shape_yx: Tuple[int, int] = (512, 512)


@dataclass
class RollingBallConfig:
    enabled: bool = False

    # Modes kept for compatibility:
    # "reference": use stored GaussianReferenceModel (recommended for stitching)
    # "blur": estimate per image by large blur (no model)
    # "gaussfit": estimate per image by blur -> gaussian fit (no stored reference)
    mode: str = "reference"

    # used to compute fit-input background field (large blur), for fitting
    estimation_blur_sigma_x_px: float = 80.0
    estimation_blur_sigma_y_px: float = 80.0
    downsample: int = 2
    eps: float = 1e-6

    # normalize correction factor
    # "median" | "mean" | "center"
    normalize_to: str = "center"

    # clamp gain
    max_gain: float = 3.0
    clip_output: bool = True


# --------------------------
# Utility
# --------------------------

def _dtype_max(img: np.ndarray) -> Optional[float]:
    if np.issubdtype(img.dtype, np.integer):
        return float(np.iinfo(img.dtype).max)
    return None


def _as_2d_float(img: np.ndarray) -> np.ndarray:
    """Accept 2D (y,x) or 3D (z,y,x). Returns float32 2D by averaging z if needed."""
    if img.ndim == 2:
        return img.astype(np.float32, copy=False)
    if img.ndim == 3:
        return np.mean(img.astype(np.float32, copy=False), axis=0)
    raise ValueError(f"Expected 2D or 3D array, got shape {img.shape}")


def _downsample_2d(a: np.ndarray, factor: int) -> np.ndarray:
    if factor <= 1:
        return a
    return a[::factor, ::factor]


def _upsample_nearest(a: np.ndarray, shape: Tuple[int, int], factor: int) -> np.ndarray:
    if factor <= 1:
        # if factor==1 and shape differs, do a simple nearest resize by repeat+crop based on ratios
        # (rarely needed; reference mode rebuilds analytically)
        if a.shape == shape:
            return a
        # nearest resize by index mapping
        src_h, src_w = a.shape
        dst_h, dst_w = shape
        yy = (np.linspace(0, src_h - 1, dst_h)).astype(np.int32)
        xx = (np.linspace(0, src_w - 1, dst_w)).astype(np.int32)
        return a[yy[:, None], xx[None, :]].astype(np.float32)
    up = np.repeat(np.repeat(a, factor, axis=0), factor, axis=1)
    return up[:shape[0], :shape[1]].astype(np.float32)


def _compute_center_offsets_from_xy(x0: float, y0: float, shape_yx: Tuple[int, int]) -> Tuple[float, float]:
    h, w = shape_yx
    cx = (w - 1) / 2.0
    cy = (h - 1) / 2.0
    return (x0 - cx, y0 - cy)


def _center_xy_from_offsets(dx: float, dy: float, shape_yx: Tuple[int, int]) -> Tuple[float, float]:
    h, w = shape_yx
    cx = (w - 1) / 2.0
    cy = (h - 1) / 2.0
    return (cx + dx, cy + dy)


def _gauss1d(x, a, x0, s, c):
    return a * np.exp(-0.5 * ((x - x0) / (s + 1e-12)) ** 2) + c


def _estimate_blur_field(a2: np.ndarray, cfg: RollingBallConfig) -> np.ndarray:
    if gaussian_filter is None:
        raise RuntimeError("scipy.ndimage.gaussian_filter not available. Install SciPy.")
    ds = max(1, int(cfg.downsample))
    a_ds = _downsample_2d(a2, ds)

    sigma_y = float(cfg.estimation_blur_sigma_y_px) / ds
    sigma_x = float(cfg.estimation_blur_sigma_x_px) / ds
    b_ds = gaussian_filter(a_ds, sigma=(sigma_y, sigma_x), mode="nearest").astype(np.float32)

    b = _upsample_nearest(b_ds, a2.shape, ds).astype(np.float32)
    return b


def _estimate_gaussian_params_from_field(b: np.ndarray) -> Tuple[float, float, float, float]:
    """
    Estimate (dx, dy, sigma_x, sigma_y) from a smooth field b.
    Uses curve_fit if available; falls back to moment-based estimates.
    """
    h, w = b.shape

    prof_x = b.mean(axis=0).astype(np.float64)
    prof_y = b.mean(axis=1).astype(np.float64)

    # baseline
    c0x = float(np.percentile(prof_x, 5))
    c0y = float(np.percentile(prof_y, 5))
    px = np.maximum(prof_x - c0x, 0.0)
    py = np.maximum(prof_y - c0y, 0.0)

    # center guess
    x0 = float(np.argmax(prof_x))
    y0 = float(np.argmax(prof_y))

    # moment sigma fallback
    def _moment_sigma(p: np.ndarray, x0_: float) -> float:
        xx = np.arange(p.size, dtype=np.float64)
        s = p.sum()
        if s <= 1e-12:
            return max(1.0, 0.35 * p.size)
        var = (p * (xx - x0_) ** 2).sum() / s
        return float(np.sqrt(max(var, 1.0)))

    sx_m = _moment_sigma(px, x0)
    sy_m = _moment_sigma(py, y0)

    if curve_fit is not None:
        xx = np.arange(w, dtype=np.float32)
        yy = np.arange(h, dtype=np.float32)
        a0x = float(np.max(prof_x) - c0x)
        a0y = float(np.max(prof_y) - c0y)

        try:
            popt_x, _ = curve_fit(_gauss1d, xx, prof_x, p0=[a0x, x0, sx_m, c0x], maxfev=4000)
            popt_y, _ = curve_fit(_gauss1d, yy, prof_y, p0=[a0y, y0, sy_m, c0y], maxfev=4000)
            _, x0f, sxf, _ = popt_x
            _, y0f, syf, _ = popt_y
            x0 = float(x0f)
            y0 = float(y0f)
            sx = float(max(1e-3, abs(sxf)))
            sy = float(max(1e-3, abs(syf)))
        except Exception:
            sx, sy = sx_m, sy_m
    else:
        sx, sy = sx_m, sy_m

    dx, dy = _compute_center_offsets_from_xy(x0, y0, (h, w))
    return float(dx), float(dy), float(sx), float(sy)


def _make_gaussian_field(shape_yx: Tuple[int, int],
                         dx_px: float, dy_px: float,
                         sigma_x_px: float, sigma_y_px: float) -> np.ndarray:
    """
    Normalized 2D gaussian with peak ~1 at (x0,y0). No amplitude/offset here.
    """
    h, w = shape_yx
    x0, y0 = _center_xy_from_offsets(dx_px, dy_px, shape_yx)

    xx = np.arange(w, dtype=np.float32)
    yy = np.arange(h, dtype=np.float32)
    X, Y = np.meshgrid(xx, yy)

    sx = max(1e-6, float(sigma_x_px))
    sy = max(1e-6, float(sigma_y_px))

    g = np.exp(
        -0.5 * ((X - x0) / sx) ** 2
        -0.5 * ((Y - y0) / sy) ** 2
    ).astype(np.float32)

    return g


def _make_gaussian_field_from_model(target_shape_yx: Tuple[int, int],
                                    model: GaussianReferenceModel) -> np.ndarray:
    """
    Scale model from reference shape -> target shape using normalized (N-1) scaling.
    Preserves relative center position and stretches independently in x/y.
    """
    th, tw = target_shape_yx
    rh, rw = model.ref_shape_yx

    # reference absolute center + fitted center in reference coords
    cx_ref = (rw - 1) / 2.0
    cy_ref = (rh - 1) / 2.0
    x0_ref = cx_ref + float(model.dx_px)
    y0_ref = cy_ref + float(model.dy_px)

    # scale in normalized pixel coordinates
    sx_scale = (tw - 1) / max(1.0, (rw - 1))
    sy_scale = (th - 1) / max(1.0, (rh - 1))

    x0 = x0_ref * sx_scale
    y0 = y0_ref * sy_scale

    sigma_x = max(1e-6, float(model.sigma_x_px) * sx_scale)
    sigma_y = max(1e-6, float(model.sigma_y_px) * sy_scale)

    # convert to dx/dy in target coords
    cx_t = (tw - 1) / 2.0
    cy_t = (th - 1) / 2.0
    dx_t = x0 - cx_t
    dy_t = y0 - cy_t

    return _make_gaussian_field((th, tw), dx_t, dy_t, sigma_x, sigma_y)


def _compute_factor_from_gaussian(
    g: np.ndarray,
    cfg: RollingBallConfig,
    strength: float,
    floor: float,
    center_xy: Optional[Tuple[float, float]] = None,
) -> np.ndarray:
    """
    g: normalized gaussian peak ~1 at its center.
    floor: [0..1) mixes in a constant floor to avoid huge edge amplification:
           g_eff = floor + (1-floor)*g

    factor_raw = target / g_eff
    factor = 1 + strength*(factor_raw - 1)
    """
    g = g.astype(np.float32, copy=False)
    floor = float(np.clip(floor, 0.0, 0.999))
    g_eff = floor + (1.0 - floor) * g

    # choose target
    if cfg.normalize_to == "mean":
        target = float(np.mean(g_eff))
    elif cfg.normalize_to == "median":
        target = float(np.median(g_eff))
    else:  # "center"
        if center_xy is None:
            cy, cx = g_eff.shape[0] // 2, g_eff.shape[1] // 2
        else:
            cx = int(np.clip(round(center_xy[0]), 0, g_eff.shape[1] - 1))
            cy = int(np.clip(round(center_xy[1]), 0, g_eff.shape[0] - 1))
        target = float(g_eff[cy, cx])

    raw = target / (g_eff + float(cfg.eps))

    # strength blend
    s = float(strength)
    factor = 1.0 + s * (raw - 1.0)

    # clamp
    mg = float(cfg.max_gain) if cfg.max_gain is not None else 0.0
    if mg > 0:
        factor = np.clip(factor, 1.0 / mg, mg)

    return factor.astype(np.float32)


# --------------------------
# Thread-safe snapshot
# --------------------------

@dataclass(frozen=True)
class RollingBallSnapshot:
    cfg: RollingBallConfig
    reference_model: Optional[GaussianReferenceModel]

    def apply(self, img: np.ndarray) -> np.ndarray:
        if not self.cfg.enabled:
            return img

        a2 = _as_2d_float(img)
        shape_yx = a2.shape

        # --- reference model path (recommended) ---
        if self.cfg.mode == "reference" and self.reference_model is not None:
            g = _make_gaussian_field_from_model(shape_yx, self.reference_model)
            center_xy = _center_xy_from_offsets(self.reference_model.dx_px, self.reference_model.dy_px, self.reference_model.ref_shape_yx)
            # NOTE: center_xy above is in REF coords. For factor we want target coords center.
            # We recompute center_xy in TARGET coords:
            cx_t, cy_t = _center_xy_from_offsets(
                *(_compute_center_offsets_from_xy(*_center_xy_from_offsets(self.reference_model.dx_px, self.reference_model.dy_px, self.reference_model.ref_shape_yx),
                                                  self.reference_model.ref_shape_yx)),
                shape_yx
            )
            # The above is too fancy; just compute target center directly:
            # Use normalized scaling via _make_gaussian_field_from_model itself:
            # We'll approximate center as argmax of g (fast enough).
            yy, xx = np.unravel_index(int(np.argmax(g)), g.shape)
            center_xy_t = (float(xx), float(yy))

            factor = _compute_factor_from_gaussian(
                g, self.cfg,
                strength=float(self.reference_model.amp),
                floor=float(self.reference_model.offset),
                center_xy=center_xy_t
            )
        else:
            # --- legacy modes: blur / gaussfit ---
            fit_input = _estimate_blur_field(a2, self.cfg)
            if self.cfg.mode == "gaussfit":
                dx, dy, sx, sy = _estimate_gaussian_params_from_field(fit_input)
                tmp_model = GaussianReferenceModel(dx_px=dx, dy_px=dy, sigma_x_px=sx, sigma_y_px=sy,
                                                   amp=1.0, offset=0.0, ref_shape_yx=fit_input.shape)
                g = _make_gaussian_field_from_model(shape_yx, tmp_model)
                yy, xx = np.unravel_index(int(np.argmax(g)), g.shape)
                factor = _compute_factor_from_gaussian(g, self.cfg, strength=1.0, floor=0.0, center_xy=(float(xx), float(yy)))
            else:
                # "blur": use the blurred field directly like before
                field = fit_input
                denom = field + float(self.cfg.eps)
                if self.cfg.normalize_to == "mean":
                    target = float(np.mean(field))
                elif self.cfg.normalize_to == "center":
                    cy, cx = shape_yx[0] // 2, shape_yx[1] // 2
                    target = float(field[cy, cx])
                else:
                    target = float(np.median(field))
                factor = (target / denom).astype(np.float32)
                mg = float(self.cfg.max_gain) if self.cfg.max_gain is not None else 0.0
                if mg > 0:
                    factor = np.clip(factor, 1.0 / mg, mg).astype(np.float32)

        out_dtype = img.dtype
        out_max = _dtype_max(img)

        if img.ndim == 2:
            out = img.astype(np.float32, copy=False) * factor
        elif img.ndim == 3:
            out = img.astype(np.float32, copy=False) * factor[None, :, :]
        else:
            raise ValueError(f"Expected 2D or 3D array, got shape {img.shape}")

        if self.cfg.clip_output and out_max is not None:
            out = np.clip(out, 0, out_max)

        return out.astype(out_dtype, copy=False)


# --------------------------
# Controller
# --------------------------

class RollingBallCorrectionController(QtCore.QObject):
    configChanged = QtCore.pyqtSignal()
    referenceChanged = QtCore.pyqtSignal()
    lastApplyChanged = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = RollingBallConfig()

        self._reference_model: Optional[GaussianReferenceModel] = None
        self._reference_filename: str = ""

        # Reference preview payload (raw image + fit-input blur)
        self._ref_preview_raw: Optional[np.ndarray] = None
        self._ref_preview_fit_input: Optional[np.ndarray] = None

        # last preview fields from apply()
        self._last_gaussian: Optional[np.ndarray] = None
        self._last_factor: Optional[np.ndarray] = None

    # ---- snapshot ----
    def snapshot(self) -> RollingBallSnapshot:
        cfg_copy = RollingBallConfig(**self.cfg.__dict__)
        model_copy = None
        if self._reference_model is not None:
            m = self._reference_model
            model_copy = GaussianReferenceModel(
                dx_px=m.dx_px, dy_px=m.dy_px,
                sigma_x_px=m.sigma_x_px, sigma_y_px=m.sigma_y_px,
                amp=m.amp, offset=m.offset,
                ref_shape_yx=m.ref_shape_yx,
            )
        return RollingBallSnapshot(cfg=cfg_copy, reference_model=model_copy)

    # ---- reference info ----
    def reference_filename(self) -> str:
        return self._reference_filename

    def reference_model(self) -> Optional[GaussianReferenceModel]:
        return self._reference_model

    def has_reference_image(self) -> bool:
        return bool(self._reference_filename) and self._ref_preview_fit_input is not None

    def get_reference_preview_payload(self):
        return (self._ref_preview_raw, self._ref_preview_fit_input)

    # ---- model management ----
    def ensure_model(self, ref_shape_yx: Tuple[int, int]) -> GaussianReferenceModel:
        """
        Ensure there is a model. If none exists, create a default one using ref_shape_yx.
        """
        if self._reference_model is None:
            self._reference_model = GaussianReferenceModel(
                dx_px=0.0, dy_px=0.0,
                sigma_x_px=max(1.0, 0.35 * ref_shape_yx[1]),
                sigma_y_px=max(1.0, 0.35 * ref_shape_yx[0]),
                amp=1.0, offset=0.0,
                ref_shape_yx=tuple(ref_shape_yx),
            )
            self.referenceChanged.emit()
        return self._reference_model

    def set_model(self, model: GaussianReferenceModel):
        self._reference_model = model
        self.referenceChanged.emit()

    def clear_reference_image(self, keep_model: bool = True):
        """
        Clear only the loaded reference TIFF payload (raw/fit-input/filename).
        Keeps model by default (so you fall back to manual/synthetic workflow).
        """
        self._reference_filename = ""
        self._ref_preview_raw = None
        self._ref_preview_fit_input = None
        if not keep_model:
            self._reference_model = None
        self.referenceChanged.emit()

    # ---- reference fit ----
    def load_reference_fit(self, img: np.ndarray, filename: str = "") -> GaussianReferenceModel:
        """
        Build fit-input (blur field), estimate dx/dy/sigma_x/sigma_y, create/update model.
        Model amp/offset are preserved if a model already exists (user strength/floor).
        """
        a2 = _as_2d_float(img)
        fit_input = _estimate_blur_field(a2, self.cfg)

        dx, dy, sx, sy = _estimate_gaussian_params_from_field(fit_input)

        prev_amp = 1.0
        prev_floor = 0.0
        if self._reference_model is not None:
            prev_amp = float(self._reference_model.amp)
            prev_floor = float(self._reference_model.offset)

        self._reference_model = GaussianReferenceModel(
            dx_px=dx, dy_px=dy,
            sigma_x_px=sx, sigma_y_px=sy,
            amp=prev_amp,
            offset=prev_floor,
            ref_shape_yx=fit_input.shape,
        )

        self._reference_filename = filename or self._reference_filename
        self._ref_preview_raw = img
        self._ref_preview_fit_input = fit_input

        self.referenceChanged.emit()
        return self._reference_model

    # ---- apply ----
    def apply(self, img: np.ndarray) -> np.ndarray:
        if not self.cfg.enabled:
            return img

        snap = self.snapshot()
        out = snap.apply(img)

        # store last factor/gaussian for preview
        a2 = _as_2d_float(img)
        shape_yx = a2.shape

        if self.cfg.mode == "reference" and self._reference_model is not None:
            g = _make_gaussian_field_from_model(shape_yx, self._reference_model)
            yy, xx = np.unravel_index(int(np.argmax(g)), g.shape)
            factor = _compute_factor_from_gaussian(
                g, self.cfg,
                strength=float(self._reference_model.amp),
                floor=float(self._reference_model.offset),
                center_xy=(float(xx), float(yy))
            )
            self._last_gaussian = g
            self._last_factor = factor
        else:
            self._last_gaussian = None
            self._last_factor = None

        self.lastApplyChanged.emit()
        return out

    def last_gaussian(self) -> Optional[np.ndarray]:
        return self._last_gaussian

    def last_factor(self) -> Optional[np.ndarray]:
        return self._last_factor


# --------------------------
# Preview dialog with crosshair + histogram
# --------------------------

class CorrectionPreviewDialog(QtWidgets.QDialog):
    """
    Preview:
      - Raw image (reference TIFF or synthetic)
      - Fit input (blurred, if available)
      - Gaussian model (normalized)
      - Correction factor
    """
    def __init__(self,
                 raw: np.ndarray,
                 fit_input: Optional[np.ndarray],
                 gauss_field: np.ndarray,
                 factor: np.ndarray,
                 model: GaussianReferenceModel,
                 center_xy: Tuple[float, float],
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rolling-ball / inverse-gaussian preview")
        self.resize(1100, 800)

        self._raw2 = _as_2d_float(raw)
        self._fit = fit_input.astype(np.float32, copy=False) if fit_input is not None else None
        self._gauss = gauss_field.astype(np.float32, copy=False)
        self._factor = factor.astype(np.float32, copy=False)

        x0, y0 = center_xy
        dx, dy = model.dx_px, model.dy_px
        sx, sy = model.sigma_x_px, model.sigma_y_px
        strength = model.amp
        floor = model.offset

        self._images: Dict[str, np.ndarray] = {
            "Correction factor": self._factor,
            "Raw image": self._raw2,
            "Gaussian model (normalized)": self._gauss,
        }
        if self._fit is not None:
            self._images["Fit input (blurred)"] = self._fit

        # --- UI ---
        self.combo = QtWidgets.QComboBox()
        self.combo.addItems(list(self._images.keys()))

        self.info = QtWidgets.QLabel(
            f"Center: x0={x0:.2f}, y0={y0:.2f} px   |   "
            f"Δx={dx:+.2f}, Δy={dy:+.2f} px   |   "
            f"σx={sx:.2f}, σy={sy:.2f} px   |   "
            f"Strength={strength:.2f}   |   Floor={floor:.3f}"
        )

        self.glw = pg.GraphicsLayoutWidget()
        self.vb = self.glw.addViewBox(row=0, col=0)
        self.vb.setAspectLocked(True)

        self.img_item = pg.ImageItem(axisOrder="row-major")
        self.vb.addItem(self.img_item)

        # histogram / LUT on the right
        self.hist = pg.HistogramLUTItem()
        self.hist.setImageItem(self.img_item)
        self.glw.addItem(self.hist, row=0, col=1)

        # optional sizing
        try:
            self.glw.ci.layout.setColumnStretchFactor(0, 10)
            self.glw.ci.layout.setColumnStretchFactor(1, 2)
        except Exception:
            pass

        # crosshair
        self.vline = pg.InfiniteLine(angle=90, movable=False)
        self.hline = pg.InfiniteLine(angle=0, movable=False)
        self.vb.addItem(self.vline)
        self.vb.addItem(self.hline)
        self.vline.setPos(float(x0))
        self.hline.setPos(float(y0))

        self.btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.btns.accepted.connect(self.accept)
        self.btns.rejected.connect(self.reject)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("View:"))
        top.addWidget(self.combo, 1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.info)
        layout.addWidget(self.glw, 1)
        layout.addWidget(self.btns)

        self.combo.currentTextChanged.connect(self._update_view)
        self._update_view(self.combo.currentText())

    def _update_view(self, name: str):
        img = self._images[name]
        lo = float(np.nanpercentile(img, 1))
        hi = float(np.nanpercentile(img, 99))
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            lo, hi = float(np.nanmin(img)), float(np.nanmax(img))

        self.img_item.setImage(img, levels=(lo, hi))
        try:
            self.hist.region.setRegion((lo, hi))
        except Exception:
            pass

        base = self.info.text().split(" | Levels:")[0]
        self.info.setText(f"{base} | Levels: [{lo:.3g}, {hi:.3g}]")
        self.vb.autoRange()


# --------------------------
# Widget
# --------------------------

class RollingBallCorrectionWidget(QtWidgets.QWidget):
    """
    UI logic:
    - Load reference TIFF -> fit -> preview -> OK applies fit parameters to UI and keeps model.
    - No TIFF -> user sets parameters + synthetic preview size -> preview works (synthetic raw).
    - User can always tweak dx/dy/sigmas/strength afterwards; preview uses CURRENT model.
    """
    def __init__(self, controller: RollingBallCorrectionController, parent=None):
        super().__init__(parent)
        self.ctrl = controller

        # ---- controls ----
        self.enable_cb = QtWidgets.QCheckBox("Enable illumination correction")

        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["reference", "blur", "gaussfit"])

        self.norm_combo = QtWidgets.QComboBox()
        self.norm_combo.addItems(["center", "median", "mean"])

        self.maxgain_spin = QtWidgets.QDoubleSpinBox()
        self.maxgain_spin.setRange(1.0, 100.0)
        self.maxgain_spin.setDecimals(2)
        self.maxgain_spin.setSingleStep(0.25)

        # estimation blur sigma (for fitting only)
        self.blur_sig_x = QtWidgets.QDoubleSpinBox()
        self.blur_sig_x.setRange(1.0, 5000.0)
        self.blur_sig_x.setDecimals(1)
        self.blur_sig_x.setSingleStep(5.0)

        self.blur_sig_y = QtWidgets.QDoubleSpinBox()
        self.blur_sig_y.setRange(1.0, 5000.0)
        self.blur_sig_y.setDecimals(1)
        self.blur_sig_y.setSingleStep(5.0)

        self.downsample_spin = QtWidgets.QSpinBox()
        self.downsample_spin.setRange(1, 32)

        # synthetic reference canvas (manual/no-TIFF preview)
        self.syn_w = QtWidgets.QSpinBox()
        self.syn_w.setRange(16, 20000)
        self.syn_w.setValue(512)
        self.syn_h = QtWidgets.QSpinBox()
        self.syn_h.setRange(16, 20000)
        self.syn_h.setValue(512)

        # model parameters
        self.dx_spin = QtWidgets.QDoubleSpinBox()
        self.dx_spin.setRange(-100000.0, 100000.0)
        self.dx_spin.setDecimals(2)
        self.dx_spin.setSingleStep(0.5)

        self.dy_spin = QtWidgets.QDoubleSpinBox()
        self.dy_spin.setRange(-100000.0, 100000.0)
        self.dy_spin.setDecimals(2)
        self.dy_spin.setSingleStep(0.5)

        self.sigx_spin = QtWidgets.QDoubleSpinBox()
        self.sigx_spin.setRange(0.1, 200000.0)
        self.sigx_spin.setDecimals(2)
        self.sigx_spin.setSingleStep(1.0)

        self.sigy_spin = QtWidgets.QDoubleSpinBox()
        self.sigy_spin.setRange(0.1, 200000.0)
        self.sigy_spin.setDecimals(2)
        self.sigy_spin.setSingleStep(1.0)

        # strength (what you called amplitude)
        self.strength_spin = QtWidgets.QDoubleSpinBox()
        self.strength_spin.setRange(0.0, 50.0)
        self.strength_spin.setDecimals(3)
        self.strength_spin.setSingleStep(0.1)
        self.strength_spin.setToolTip("0 = no correction, 1 = normal, >1 = stronger (brighter edges).")

        # gaussian floor (optional; keeps gains sane)
        self.floor_spin = QtWidgets.QDoubleSpinBox()
        self.floor_spin.setRange(0.0, 0.999)
        self.floor_spin.setDecimals(4)
        self.floor_spin.setSingleStep(0.01)
        self.floor_spin.setToolTip("Mixes in a constant floor: g_eff = floor + (1-floor)*g. Prevents extreme gains.")

        # reference file + actions
        self.ref_path = QtWidgets.QLineEdit()
        self.ref_path.setReadOnly(True)
        self.ref_path.setPlaceholderText("No reference TIFF loaded (manual model)")

        self.load_ref_btn = QtWidgets.QPushButton("Load reference TIFF…")
        self.preview_btn = QtWidgets.QPushButton("Preview model…")
        self.clear_ref_btn = QtWidgets.QPushButton("Clear reference TIFF")

        self.preview_last_btn = QtWidgets.QPushButton("Preview last applied factor…")

        # ---- layout ----
        form = QtWidgets.QFormLayout()
        form.addRow(self.enable_cb)
        form.addRow("Mode", self.mode_combo)
        form.addRow("Normalize to", self.norm_combo)
        form.addRow("Max gain clamp", self.maxgain_spin)

        est_box = QtWidgets.QGroupBox("Fit-input smoothing (used for fitting reference TIFF)")
        est_form = QtWidgets.QFormLayout(est_box)
        est_form.addRow("Blur sigma X [px]", self.blur_sig_x)
        est_form.addRow("Blur sigma Y [px]", self.blur_sig_y)
        est_form.addRow("Downsample", self.downsample_spin)

        ref_box = QtWidgets.QGroupBox("Reference / Model")
        ref_form = QtWidgets.QFormLayout(ref_box)

        ref_form.addRow("Reference TIFF", self.ref_path)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(self.load_ref_btn)
        btn_row.addWidget(self.preview_btn)
        btn_row.addWidget(self.clear_ref_btn)
        btn_wrap = QtWidgets.QWidget()
        btn_wrap.setLayout(btn_row)
        ref_form.addRow(btn_wrap)

        syn_row = QtWidgets.QHBoxLayout()
        syn_row.addWidget(QtWidgets.QLabel("W"))
        syn_row.addWidget(self.syn_w)
        syn_row.addSpacing(10)
        syn_row.addWidget(QtWidgets.QLabel("H"))
        syn_row.addWidget(self.syn_h)
        syn_wrap = QtWidgets.QWidget()
        syn_wrap.setLayout(syn_row)
        ref_form.addRow("Synthetic preview size", syn_wrap)

        ref_form.addRow("Δx from center [px]", self.dx_spin)
        ref_form.addRow("Δy from center [px]", self.dy_spin)
        ref_form.addRow("σx drop-off [px]", self.sigx_spin)
        ref_form.addRow("σy drop-off [px]", self.sigy_spin)
        ref_form.addRow("Strength (amplitude)", self.strength_spin)
        ref_form.addRow("Floor (optional)", self.floor_spin)

        layout = QtWidgets.QGridLayout(self)
        layout.addLayout(form, 0, 0)
        layout.addWidget(est_box, 1, 0)
        layout.addWidget(ref_box, 0, 1, 2, 1)
        layout.addWidget(self.preview_last_btn, 2, 0)

        # ---- init sync ----
        self._sync_from_controller()

        # ---- wiring ----
        self.enable_cb.toggled.connect(self._on_enabled)
        self.mode_combo.currentTextChanged.connect(self._on_mode)
        self.norm_combo.currentTextChanged.connect(self._on_norm)
        self.maxgain_spin.valueChanged.connect(self._on_basic_params)

        self.blur_sig_x.valueChanged.connect(self._on_est_params)
        self.blur_sig_y.valueChanged.connect(self._on_est_params)
        self.downsample_spin.valueChanged.connect(self._on_est_params)

        self.syn_w.valueChanged.connect(self._on_synth_size_changed)
        self.syn_h.valueChanged.connect(self._on_synth_size_changed)

        self.dx_spin.valueChanged.connect(self._on_model_params)
        self.dy_spin.valueChanged.connect(self._on_model_params)
        self.sigx_spin.valueChanged.connect(self._on_model_params)
        self.sigy_spin.valueChanged.connect(self._on_model_params)
        self.strength_spin.valueChanged.connect(self._on_model_params)
        self.floor_spin.valueChanged.connect(self._on_model_params)

        self.load_ref_btn.clicked.connect(self._load_reference_tiff)
        self.preview_btn.clicked.connect(self._preview_model)
        self.clear_ref_btn.clicked.connect(self._clear_reference_tiff)
        self.preview_last_btn.clicked.connect(self._preview_last_factor)

        self.ctrl.configChanged.connect(self._sync_from_controller)
        self.ctrl.referenceChanged.connect(self._sync_from_controller)

    # -----------------
    # Slots (config)
    # -----------------

    def _on_enabled(self, checked: bool):
        self.ctrl.cfg.enabled = bool(checked)
        self.ctrl.configChanged.emit()

    def _on_mode(self, txt: str):
        self.ctrl.cfg.mode = str(txt).strip().lower()
        self.ctrl.configChanged.emit()

    def _on_norm(self, txt: str):
        self.ctrl.cfg.normalize_to = str(txt).strip().lower()
        self.ctrl.configChanged.emit()

    def _on_basic_params(self):
        self.ctrl.cfg.max_gain = float(self.maxgain_spin.value())
        self.ctrl.configChanged.emit()

    def _on_est_params(self):
        self.ctrl.cfg.estimation_blur_sigma_x_px = float(self.blur_sig_x.value())
        self.ctrl.cfg.estimation_blur_sigma_y_px = float(self.blur_sig_y.value())
        self.ctrl.cfg.downsample = int(self.downsample_spin.value())
        self.ctrl.configChanged.emit()

    def _on_synth_size_changed(self):
        """
        If no reference TIFF is loaded, synthetic size defines model.ref_shape_yx basis.
        """
        if self.ctrl.has_reference_image():
            return
        model = self.ctrl.reference_model()
        if model is None:
            return
        new_shape = (int(self.syn_h.value()), int(self.syn_w.value()))
        if tuple(model.ref_shape_yx) != tuple(new_shape):
            model.ref_shape_yx = tuple(new_shape)
            self.ctrl.referenceChanged.emit()

    # -----------------
    # Model param edits
    # -----------------

    def _on_model_params(self):
        """
        Update/create model from GUI edits.
        If no reference TIFF is loaded, model.ref_shape_yx is taken from synthetic W/H.
        """
        model = self.ctrl.reference_model()

        if model is None:
            ref_shape = (int(self.syn_h.value()), int(self.syn_w.value()))
            model = self.ctrl.ensure_model(ref_shape)

        # If no reference image, keep ref_shape in sync with synthetic size:
        if not self.ctrl.has_reference_image():
            model.ref_shape_yx = (int(self.syn_h.value()), int(self.syn_w.value()))

        model.dx_px = float(self.dx_spin.value())
        model.dy_px = float(self.dy_spin.value())
        model.sigma_x_px = float(self.sigx_spin.value())
        model.sigma_y_px = float(self.sigy_spin.value())
        model.amp = float(self.strength_spin.value())
        model.offset = float(self.floor_spin.value())

        self.ctrl.referenceChanged.emit()

    # -----------------
    # Reference workflow
    # -----------------

    def _load_reference_tiff(self):
        try:
            import tifffile as tiff
        except Exception:
            QtWidgets.QMessageBox.warning(
                self, "Missing dependency",
                "tifffile is not installed. Install it (pip install tifffile) to load reference TIFFs."
            )
            return

        fn, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select reference TIFF", "", "TIFF (*.tif *.tiff)")
        if not fn:
            return

        try:
            img = tiff.imread(fn)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Load failed", f"Could not read TIFF:\n{e}")
            return

        try:
            model = self.ctrl.load_reference_fit(img, filename=fn)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Fit failed", str(e))
            return

        # put fitted params into UI (but do not overwrite strength/floor)
        self._sync_from_controller()

        # show preview; if accepted -> enable and switch to reference mode
        dlg = self._build_preview_dialog_from_current_model()
        if dlg is None:
            return
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.enable_cb.setChecked(True)
            self.mode_combo.setCurrentText("reference")
            self.ctrl.cfg.enabled = True
            self.ctrl.cfg.mode = "reference"
            self.ctrl.configChanged.emit()

    def _clear_reference_tiff(self):
        # keep model, just clear TIFF payload
        self.ctrl.clear_reference_image(keep_model=True)
        # ensure model ref basis from synthetic size
        m = self.ctrl.reference_model()
        if m is not None:
            m.ref_shape_yx = (int(self.syn_h.value()), int(self.syn_w.value()))
            self.ctrl.referenceChanged.emit()

    # -----------------
    # Preview
    # -----------------

    def _build_preview_dialog_from_current_model(self) -> Optional[CorrectionPreviewDialog]:
        model = self.ctrl.reference_model()
        if model is None:
            # create a model from current params
            ref_shape = (int(self.syn_h.value()), int(self.syn_w.value()))
            model = self.ctrl.ensure_model(ref_shape)
            model.dx_px = float(self.dx_spin.value())
            model.dy_px = float(self.dy_spin.value())
            model.sigma_x_px = float(self.sigx_spin.value())
            model.sigma_y_px = float(self.sigy_spin.value())
            model.amp = float(self.strength_spin.value())
            model.offset = float(self.floor_spin.value())
            if not self.ctrl.has_reference_image():
                model.ref_shape_yx = (int(self.syn_h.value()), int(self.syn_w.value()))
                self.ctrl.referenceChanged.emit()

        raw, fit_input = self.ctrl.get_reference_preview_payload()

        if raw is not None and fit_input is not None:
            # preview in reference coordinate system (fit_input shape)
            shape = fit_input.shape
            g = _make_gaussian_field_from_model(shape, model)
            yy, xx = np.unravel_index(int(np.argmax(g)), g.shape)
            factor = _compute_factor_from_gaussian(
                g, self.ctrl.cfg,
                strength=float(model.amp),
                floor=float(model.offset),
                center_xy=(float(xx), float(yy))
            )
            center_xy = (float(xx), float(yy))
            return CorrectionPreviewDialog(
                raw=raw,
                fit_input=fit_input,
                gauss_field=g,
                factor=factor,
                model=model,
                center_xy=center_xy,
                parent=self,
            )

        # synthetic preview (no reference TIFF)
        h = int(self.syn_h.value())
        w = int(self.syn_w.value())
        shape = (h, w)

        # ensure model basis equals synthetic basis for meaningful preview
        model.ref_shape_yx = shape

        g = _make_gaussian_field_from_model(shape, model)
        yy, xx = np.unravel_index(int(np.argmax(g)), g.shape)
        factor = _compute_factor_from_gaussian(
            g, self.ctrl.cfg,
            strength=float(model.amp),
            floor=float(model.offset),
            center_xy=(float(xx), float(yy))
        )

        # make a synthetic "raw" that looks like a vignetted image
        synthetic_raw = (g * 65535.0).astype(np.uint16)

        return CorrectionPreviewDialog(
            raw=synthetic_raw,
            fit_input=None,
            gauss_field=g,
            factor=factor,
            model=model,
            center_xy=(float(xx), float(yy)),
            parent=self,
        )

    def _preview_model(self):
        dlg = self._build_preview_dialog_from_current_model()
        if dlg is None:
            return
        dlg.exec_()

    def _preview_last_factor(self):
        f = self.ctrl.last_factor()
        g = self.ctrl.last_gaussian()
        if f is None or g is None:
            QtWidgets.QMessageBox.information(self, "Preview", "No reference-mode factor computed yet.\nApply correction to an image first.")
            return

        # make a synthetic raw for display
        synthetic_raw = (g * 65535.0).astype(np.uint16)
        yy, xx = np.unravel_index(int(np.argmax(g)), g.shape)

        model = self.ctrl.reference_model()
        if model is None:
            model = GaussianReferenceModel(dx_px=0, dy_px=0, sigma_x_px=1, sigma_y_px=1, amp=1, offset=0, ref_shape_yx=g.shape)

        dlg = CorrectionPreviewDialog(
            raw=synthetic_raw,
            fit_input=None,
            gauss_field=g,
            factor=f,
            model=model,
            center_xy=(float(xx), float(yy)),
            parent=self,
        )
        dlg.exec_()

    # -----------------
    # Sync UI
    # -----------------

    def _sync_from_controller(self):
        c = self.ctrl.cfg

        self.enable_cb.blockSignals(True)
        self.mode_combo.blockSignals(True)
        self.norm_combo.blockSignals(True)
        self.maxgain_spin.blockSignals(True)
        self.blur_sig_x.blockSignals(True)
        self.blur_sig_y.blockSignals(True)
        self.downsample_spin.blockSignals(True)

        self.dx_spin.blockSignals(True)
        self.dy_spin.blockSignals(True)
        self.sigx_spin.blockSignals(True)
        self.sigy_spin.blockSignals(True)
        self.strength_spin.blockSignals(True)
        self.floor_spin.blockSignals(True)
        self.syn_w.blockSignals(True)
        self.syn_h.blockSignals(True)

        try:
            self.enable_cb.setChecked(bool(c.enabled))
            self.mode_combo.setCurrentText(str(c.mode))
            self.norm_combo.setCurrentText(str(c.normalize_to))
            self.maxgain_spin.setValue(float(c.max_gain))

            self.blur_sig_x.setValue(float(c.estimation_blur_sigma_x_px))
            self.blur_sig_y.setValue(float(c.estimation_blur_sigma_y_px))
            self.downsample_spin.setValue(int(c.downsample))

            model = self.ctrl.reference_model()
            if self.ctrl.has_reference_image():
                self.ref_path.setText(self.ctrl.reference_filename())
            else:
                self.ref_path.setText("Manual / synthetic (no reference TIFF loaded)")

            if model is not None:
                # if no reference image, keep synthetic size in sync with model basis
                if not self.ctrl.has_reference_image():
                    self.syn_h.setValue(int(model.ref_shape_yx[0]))
                    self.syn_w.setValue(int(model.ref_shape_yx[1]))

                self.dx_spin.setValue(float(model.dx_px))
                self.dy_spin.setValue(float(model.dy_px))
                self.sigx_spin.setValue(float(model.sigma_x_px))
                self.sigy_spin.setValue(float(model.sigma_y_px))
                self.strength_spin.setValue(float(model.amp))
                self.floor_spin.setValue(float(model.offset))
            else:
                # defaults
                self.syn_h.setValue(int(self.syn_h.value()))
                self.syn_w.setValue(int(self.syn_w.value()))

        finally:
            self.enable_cb.blockSignals(False)
            self.mode_combo.blockSignals(False)
            self.norm_combo.blockSignals(False)
            self.maxgain_spin.blockSignals(False)
            self.blur_sig_x.blockSignals(False)
            self.blur_sig_y.blockSignals(False)
            self.downsample_spin.blockSignals(False)

            self.dx_spin.blockSignals(False)
            self.dy_spin.blockSignals(False)
            self.sigx_spin.blockSignals(False)
            self.sigy_spin.blockSignals(False)
            self.strength_spin.blockSignals(False)
            self.floor_spin.blockSignals(False)
            self.syn_w.blockSignals(False)
            self.syn_h.blockSignals(False)


# --------------------------
# Demo
# --------------------------

if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)

    ctrl = RollingBallCorrectionController()
    w = RollingBallCorrectionWidget(ctrl)
    w.show()

    sys.exit(app.exec_())