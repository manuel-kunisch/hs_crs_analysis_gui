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
from typing import Optional, Tuple, Callable

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

    # intensity scale:
    amp: float
    offset: float

    # reference image shape used for scaling when new shapes differ
    ref_shape_yx: Tuple[int, int]


@dataclass
class RollingBallConfig:
    enabled: bool = False

    # "blur": estimate field per image by large blur
    # "gaussfit": estimate per image by blur -> gaussian fit (anisotropic)
    # "reference": use stored GaussianReferenceModel
    mode: str = "blur"

    # used to compute the *fit-input* / background field (large blur)
    # (this is NOT the illumination sigma; it’s just the smoothing for the estimate)
    estimation_blur_sigma_x_px: float = 80.0
    estimation_blur_sigma_y_px: float = 80.0
    downsample: int = 2
    eps: float = 1e-6

    # normalize correction factor to keep global intensity stable
    # "median" | "mean" | "center"
    normalize_to: str = "median"

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
        return a
    up = np.repeat(np.repeat(a, factor, axis=0), factor, axis=1)
    return up[:shape[0], :shape[1]]


def _gauss1d(x, a, x0, s, c):
    return a * np.exp(-0.5 * ((x - x0) / (s + 1e-12)) ** 2) + c


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


def _make_gaussian_field(shape_yx: Tuple[int, int],
                         dx_px: float, dy_px: float,
                         sigma_x_px: float, sigma_y_px: float,
                         amp: float, offset: float) -> np.ndarray:
    h, w = shape_yx
    x0, y0 = _center_xy_from_offsets(dx_px, dy_px, shape_yx)
    xx = np.arange(w, dtype=np.float32)
    yy = np.arange(h, dtype=np.float32)
    X, Y = np.meshgrid(xx, yy)
    sx = max(1e-6, float(sigma_x_px))
    sy = max(1e-6, float(sigma_y_px))
    g = float(amp) * np.exp(
        -0.5 * ((X - x0) / sx) ** 2
        -0.5 * ((Y - y0) / sy) ** 2
    ) + float(offset)
    return g.astype(np.float32)


def _make_gaussian_field_from_model(target_shape_yx: Tuple[int, int],
                                    model: GaussianReferenceModel) -> np.ndarray:
    """
    If target shape differs from model.ref_shape_yx, scale dx/dy and sigma_x/sigma_y
    by width/height ratios (keeps the same relative illumination geometry).
    """
    th, tw = target_shape_yx
    rh, rw = model.ref_shape_yx

    if (th, tw) == (rh, rw):
        dx, dy = model.dx_px, model.dy_px
        sx, sy = model.sigma_x_px, model.sigma_y_px
        amp, off = model.amp, model.offset
        return _make_gaussian_field((th, tw), dx, dy, sx, sy, amp, off)

    sx_scale = tw / max(1, rw)
    sy_scale = th / max(1, rh)

    dx = model.dx_px * sx_scale
    dy = model.dy_px * sy_scale
    sx = model.sigma_x_px * sx_scale
    sy = model.sigma_y_px * sy_scale

    # amp/offset stay in intensity units, do not scale
    return _make_gaussian_field((th, tw), dx, dy, sx, sy, model.amp, model.offset)


def _estimate_blur_field(a2: np.ndarray, cfg: RollingBallConfig) -> np.ndarray:
    if gaussian_filter is None:
        raise RuntimeError("scipy.ndimage.gaussian_filter not available. Install SciPy.")
    ds = max(1, int(cfg.downsample))
    a_ds = _downsample_2d(a2, ds)

    # scipy expects sigma in (y,x)
    sigma_y = float(cfg.estimation_blur_sigma_y_px) / ds
    sigma_x = float(cfg.estimation_blur_sigma_x_px) / ds
    b_ds = gaussian_filter(a_ds, sigma=(sigma_y, sigma_x), mode="nearest").astype(np.float32)

    b = _upsample_nearest(b_ds, a2.shape, ds).astype(np.float32)
    return b


def _estimate_gaussian_model_from_field(b: np.ndarray) -> Tuple[GaussianReferenceModel, np.ndarray, Tuple[float, float]]:
    """
    Given a smooth illumination field b (fit-input), estimate:
      - anisotropic Gaussian model parameters (dx,dy,sigma_x,sigma_y,amp,offset)
      - gaussian field from that model
      - fitted center (x0,y0)
    Fallback: argmax center + heuristic sigmas if curve_fit unavailable.
    """
    h, w = b.shape

    # intensity scale (robust-ish)
    offset = float(np.percentile(b, 5))
    amp = float(np.max(b) - offset)
    if amp <= 0:
        amp = float(np.max(b))
        offset = 0.0

    # fallback center from maximum
    yy_max, xx_max = np.unravel_index(int(np.argmax(b)), b.shape)
    x0_fallback, y0_fallback = float(xx_max), float(yy_max)

    # fallback sigma guess
    sigma_x_fallback = max(1.0, 0.35 * w)
    sigma_y_fallback = max(1.0, 0.35 * h)

    if curve_fit is None:
        dx, dy = _compute_center_offsets_from_xy(x0_fallback, y0_fallback, (h, w))
        model = GaussianReferenceModel(
            dx_px=dx, dy_px=dy,
            sigma_x_px=sigma_x_fallback, sigma_y_px=sigma_y_fallback,
            amp=amp, offset=offset,
            ref_shape_yx=(h, w),
        )
        g = _make_gaussian_field_from_model((h, w), model)
        return model, g, (x0_fallback, y0_fallback)

    xx = np.arange(w, dtype=np.float32)
    yy = np.arange(h, dtype=np.float32)
    prof_x = b.mean(axis=0)
    prof_y = b.mean(axis=1)

    # initial guesses
    c0x = float(np.percentile(prof_x, 5))
    c0y = float(np.percentile(prof_y, 5))
    a0x = float(np.max(prof_x) - c0x)
    a0y = float(np.max(prof_y) - c0y)
    x0 = float(np.argmax(prof_x))
    y0 = float(np.argmax(prof_y))
    sx0 = sigma_x_fallback
    sy0 = sigma_y_fallback

    try:
        popt_x, _ = curve_fit(_gauss1d, xx, prof_x, p0=[a0x, x0, sx0, c0x], maxfev=4000)
        popt_y, _ = curve_fit(_gauss1d, yy, prof_y, p0=[a0y, y0, sy0, c0y], maxfev=4000)

        _, x0f, sxf, _ = popt_x
        _, y0f, syf, _ = popt_y

        dx, dy = _compute_center_offsets_from_xy(float(x0f), float(y0f), (h, w))
        model = GaussianReferenceModel(
            dx_px=float(dx),
            dy_px=float(dy),
            sigma_x_px=float(max(1e-3, abs(sxf))),
            sigma_y_px=float(max(1e-3, abs(syf))),
            amp=float(amp),
            offset=float(offset),
            ref_shape_yx=(h, w),
        )
        g = _make_gaussian_field_from_model((h, w), model)
        return model, g, (float(x0f), float(y0f))

    except Exception:
        dx, dy = _compute_center_offsets_from_xy(x0_fallback, y0_fallback, (h, w))
        model = GaussianReferenceModel(
            dx_px=dx, dy_px=dy,
            sigma_x_px=sigma_x_fallback, sigma_y_px=sigma_y_fallback,
            amp=amp, offset=offset,
            ref_shape_yx=(h, w),
        )
        g = _make_gaussian_field_from_model((h, w), model)
        return model, g, (x0_fallback, y0_fallback)


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

        if self.cfg.mode == "reference" and self.reference_model is not None:
            field = _make_gaussian_field_from_model(shape_yx, self.reference_model)
        else:
            fit_input = _estimate_blur_field(a2, self.cfg)
            if self.cfg.mode == "gaussfit":
                model, field, _ = _estimate_gaussian_model_from_field(fit_input)
            else:
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

        # clamp gain
        mg = float(self.cfg.max_gain) if self.cfg.max_gain is not None else 0.0
        if mg > 0:
            # restrict factor to [1/mg, mg]
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

        # Stored preview payload so you can reopen the fit dialog later:
        self._ref_preview_raw: Optional[np.ndarray] = None
        self._ref_preview_fit_input: Optional[np.ndarray] = None
        self._ref_preview_field: Optional[np.ndarray] = None
        self._ref_preview_center_xy: Optional[Tuple[float, float]] = None

        # last used field (from apply)
        self._last_field: Optional[np.ndarray] = None

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

    def has_reference_preview(self) -> bool:
        return self._ref_preview_fit_input is not None and self._ref_preview_field is not None and self._ref_preview_center_xy is not None

    def get_reference_preview_payload(self):
        return (self._ref_preview_raw, self._ref_preview_fit_input, self._ref_preview_field, self._ref_preview_center_xy)

    # ---- core API ----
    def clear_reference(self):
        self._reference_model = None
        self._reference_filename = ""
        self._ref_preview_raw = None
        self._ref_preview_fit_input = None
        self._ref_preview_field = None
        self._ref_preview_center_xy = None
        self.referenceChanged.emit()

    def load_reference_fit(self, img: np.ndarray, filename: str = "") -> Tuple[GaussianReferenceModel, np.ndarray, np.ndarray, Tuple[float, float]]:
        """
        Build fit-input (blur field), estimate anisotropic Gaussian model from it.
        Returns: (model, gauss_field, fit_input, center_xy)
        """
        a2 = _as_2d_float(img)
        fit_input = _estimate_blur_field(a2, self.cfg)
        model, gauss_field, center_xy = _estimate_gaussian_model_from_field(fit_input)

        # store
        self._reference_model = model
        self._reference_filename = filename or self._reference_filename

        self._ref_preview_raw = img
        self._ref_preview_fit_input = fit_input
        self._ref_preview_field = gauss_field
        self._ref_preview_center_xy = center_xy

        self.referenceChanged.emit()
        return model, gauss_field, fit_input, center_xy

    def apply(self, img: np.ndarray) -> np.ndarray:
        if not self.cfg.enabled:
            return img

        snap = self.snapshot()
        out = snap.apply(img)

        # store last used field for preview
        a2 = _as_2d_float(img)
        shape_yx = a2.shape
        if self.cfg.mode == "reference" and self._reference_model is not None:
            self._last_field = _make_gaussian_field_from_model(shape_yx, self._reference_model)
        else:
            fit_input = _estimate_blur_field(a2, self.cfg)
            if self.cfg.mode == "gaussfit":
                _, field, _ = _estimate_gaussian_model_from_field(fit_input)
                self._last_field = field
            else:
                self._last_field = fit_input

        self.lastApplyChanged.emit()
        return out

    def last_field(self) -> Optional[np.ndarray]:
        return self._last_field


# --------------------------
# Preview dialog with crosshair
# --------------------------

class CorrectionPreviewDialog(QtWidgets.QDialog):
    """
    Preview what was fitted on a reference image:
      - Raw image
      - Fit input (blurred)
      - Fitted Gaussian field
      - Correction factor
    Crosshair at fitted center; also shows dx/dy and sigma_x/sigma_y.
    """
    def __init__(self,
                 raw: np.ndarray,
                 fit_input: np.ndarray,
                 gauss_field: np.ndarray,
                 model: GaussianReferenceModel,
                 center_xy: Tuple[float, float],
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reference fit preview (illumination drop-off)")
        self.resize(1050, 780)

        self._raw2 = _as_2d_float(raw)
        self._fit = fit_input.astype(np.float32, copy=False)
        self._gauss = gauss_field.astype(np.float32, copy=False)

        x0, y0 = center_xy
        dx, dy = model.dx_px, model.dy_px
        sx, sy = model.sigma_x_px, model.sigma_y_px

        eps = 1e-6
        target = float(np.median(self._gauss))
        corr = (target / (self._gauss + eps)).astype(np.float32)

        self._images = {
            "Raw image": self._raw2,
            "Fit input (blurred)": self._fit,
            "Fitted Gaussian field": self._gauss,
            "Correction factor": corr,
        }

        # --- UI ---
        self.combo = QtWidgets.QComboBox()
        self.combo.addItems(list(self._images.keys()))

        self.info = QtWidgets.QLabel(
            f"Center: x0={x0:.2f}, y0={y0:.2f} px   |   "
            f"Offset from image center: Δx={dx:+.2f}, Δy={dy:+.2f} px   |   "
            f"Sigma: σx={sx:.2f} px, σy={sy:.2f} px"
        )

        self.glw = pg.GraphicsLayoutWidget()
        self.vb = self.glw.addViewBox(row=0, col=0)
        self.vb.setAspectLocked(True)
        self.glw.ci.layout.setColumnStretchFactor(0, 10)  # image area
        self.glw.ci.layout.setColumnStretchFactor(1, 2)  # histogram

        self.img_item = pg.ImageItem(axisOrder="row-major")
        self.vb.addItem(self.img_item)

        # --- Histogram / LUT on the right ---
        self.hist = pg.HistogramLUTItem()
        self.hist.setImageItem(self.img_item)  # links histogram + levels to the image
        self.hist.vb.setMouseEnabled(y=True, x=False)  # typical: only vertical zoom/pan
        self.glw.addItem(self.hist, row=0, col=1)  # place it to the right

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

        # Set image + initial levels
        self.img_item.setImage(img, levels=(lo, hi))

        # Ensure histogram knows about the new image range/levels
        self.hist.region.setRegion((lo, hi))

        # Optional: show the actual levels in the info line
        # (append without losing your existing info)
        base = self.info.text().split(" | Levels:")[0]
        self.info.setText(f"{base} | Levels: [{lo:.3g}, {hi:.3g}]")

        self.vb.autoRange()


# --------------------------
# Widget (no "use current", no samples)
# --------------------------

class RollingBallCorrectionWidget(QtWidgets.QWidget):
    """
    UI:
      - Enable checkbox
      - Mode combo (blur / gaussfit / reference)
      - Estimation blur sigma (x,y) used for fit-input
      - Reference model parameters (dx,dy,sigma_x,sigma_y) editable
      - Load reference TIFF -> preview -> OK applies model + updates GUI
      - Shows chosen filename and lets you reopen the preview window
      - Preview last applied field
    """
    def __init__(self, controller: RollingBallCorrectionController, parent=None):
        super().__init__(parent)
        self.ctrl = controller

        # If you still want any “current image” based preview later, you can set this;
        # but per your request, we don’t use it for fitting.
        self.get_current_image_callable: Optional[Callable[[], Optional[np.ndarray]]] = None

        # ---- basic controls ----
        self.enable_cb = QtWidgets.QCheckBox("Enable illumination correction")

        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["blur", "gaussfit", "reference"])

        self.norm_combo = QtWidgets.QComboBox()
        self.norm_combo.addItems(["median", "mean", "center"])

        self.maxgain_spin = QtWidgets.QDoubleSpinBox()
        self.maxgain_spin.setRange(1.0, 100.0)
        self.maxgain_spin.setDecimals(2)
        self.maxgain_spin.setSingleStep(0.25)

        # estimation blur sigma (for fit-input only)
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

        # ---- reference model parameters (editable) ----
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

        # ---- reference file + preview controls ----
        self.ref_path = QtWidgets.QLineEdit()
        self.ref_path.setReadOnly(True)
        self.ref_path.setPlaceholderText("No reference file loaded")

        self.load_ref_btn = QtWidgets.QPushButton("Load reference TIFF…")
        self.show_ref_preview_btn = QtWidgets.QPushButton("Fit preview…")
        self.show_ref_preview_btn.setEnabled(False)

        self.clear_ref_btn = QtWidgets.QPushButton("Clear reference")

        self.preview_last_btn = QtWidgets.QPushButton("Preview last applied field…")

        # ---- layout ----
        form = QtWidgets.QFormLayout()
        form.addRow(self.enable_cb)
        form.addRow("Mode", self.mode_combo)
        form.addRow("Normalize to", self.norm_combo)
        form.addRow("Max gain clamp", self.maxgain_spin)

        est_box = QtWidgets.QGroupBox("Estimation (fit-input smoothing)")
        est_form = QtWidgets.QFormLayout(est_box)
        est_form.addRow("Blur sigma X [px]", self.blur_sig_x)
        est_form.addRow("Blur sigma Y [px]", self.blur_sig_y)
        est_form.addRow("Downsample", self.downsample_spin)

        ref_box = QtWidgets.QGroupBox("Reference fit (anisotropic Gaussian model)")
        ref_form = QtWidgets.QFormLayout(ref_box)
        ref_form.addRow("Reference file", self.ref_path)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(self.load_ref_btn)
        btn_row.addWidget(self.show_ref_preview_btn)
        btn_row.addWidget(self.clear_ref_btn)
        btn_wrap = QtWidgets.QWidget()
        btn_wrap.setLayout(btn_row)
        ref_form.addRow(btn_wrap)

        ref_form.addRow("Δx from center [px]", self.dx_spin)
        ref_form.addRow("Δy from center [px]", self.dy_spin)
        ref_form.addRow("σx drop-off [px]", self.sigx_spin)
        ref_form.addRow("σy drop-off [px]", self.sigy_spin)

        layout = QtWidgets.QGridLayout(self)
        layout.addLayout(form, 0, 0)
        layout.addWidget(est_box, 1, 0)
        layout.addWidget(ref_box, 0, 1, 2, 1)
        layout.addWidget(self.preview_last_btn,2 , 0)

        # ---- init ----
        self._sync_from_controller()

        # ---- wiring ----
        self.enable_cb.toggled.connect(self._on_enabled)

        self.mode_combo.currentTextChanged.connect(self._on_mode)
        self.norm_combo.currentTextChanged.connect(self._on_norm)
        self.maxgain_spin.valueChanged.connect(self._on_basic_params)

        self.blur_sig_x.valueChanged.connect(self._on_est_params)
        self.blur_sig_y.valueChanged.connect(self._on_est_params)
        self.downsample_spin.valueChanged.connect(self._on_est_params)

        self.dx_spin.valueChanged.connect(self._on_ref_params)
        self.dy_spin.valueChanged.connect(self._on_ref_params)
        self.sigx_spin.valueChanged.connect(self._on_ref_params)
        self.sigy_spin.valueChanged.connect(self._on_ref_params)

        self.load_ref_btn.clicked.connect(self._load_reference_tiff)
        self.show_ref_preview_btn.clicked.connect(self._show_reference_preview)
        self.clear_ref_btn.clicked.connect(self._clear_reference)
        self.preview_last_btn.clicked.connect(self._preview_last_field)

        self.ctrl.configChanged.connect(self._sync_from_controller)
        self.ctrl.referenceChanged.connect(self._sync_from_controller)

    # -----------------
    # Slots
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

    def _on_ref_params(self):
        """
        If a reference model exists, update it from the GUI edits (dx/dy/sigmas).
        """
        model = self.ctrl.reference_model()
        if model is None:
            return

        new_model = GaussianReferenceModel(
            dx_px=float(self.dx_spin.value()),
            dy_px=float(self.dy_spin.value()),
            sigma_x_px=float(self.sigx_spin.value()),
            sigma_y_px=float(self.sigy_spin.value()),
            amp=float(model.amp),
            offset=float(model.offset),
            ref_shape_yx=model.ref_shape_yx,
        )
        self.ctrl._reference_model = new_model  # keep as drop-in; no extra API needed
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

        # Estimate + store model and preview payload in controller
        try:
            model, gauss_field, fit_input, center_xy = self.ctrl.load_reference_fit(img, filename=fn)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Fit failed", str(e))
            return

        # Open preview and if accepted: apply model + update GUI immediately
        dlg = CorrectionPreviewDialog(
            raw=img,
            fit_input=fit_input,
            gauss_field=gauss_field,
            model=model,
            center_xy=center_xy,
            parent=self,
        )
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            # Apply to GUI immediately:
            self.ref_path.setText(fn)
            self.dx_spin.setValue(float(model.dx_px))
            self.dy_spin.setValue(float(model.dy_px))
            self.sigx_spin.setValue(float(model.sigma_x_px))
            self.sigy_spin.setValue(float(model.sigma_y_px))

            # Switch to reference mode and enable correction (common desired behavior)
            self.mode_combo.setCurrentText("reference")
            self.enable_cb.setChecked(True)

            # (These set via signals above; but ensure controller is synced)
            self.ctrl.cfg.mode = "reference"
            self.ctrl.cfg.enabled = True
            self.ctrl.referenceChanged.emit()
            self.ctrl.configChanged.emit()

        else:
            # If user cancels, keep the model stored but do not auto-enable.
            # You can change this behavior if you prefer.
            pass

    def _show_reference_preview(self):
        if not self.ctrl.has_reference_preview():
            QtWidgets.QMessageBox.information(self, "No preview", "No reference fit available yet.")
            return

        raw, fit_input, gauss_field, center_xy = self.ctrl.get_reference_preview_payload()
        model = self.ctrl.reference_model()
        if raw is None or fit_input is None or gauss_field is None or center_xy is None or model is None:
            QtWidgets.QMessageBox.information(self, "No preview", "Reference preview data is incomplete.")
            return

        dlg = CorrectionPreviewDialog(
            raw=raw,
            fit_input=fit_input,
            gauss_field=gauss_field,
            model=model,
            center_xy=center_xy,
            parent=self,
        )
        dlg.exec_()

    def _clear_reference(self):
        self.ctrl.clear_reference()
        self.ref_path.clear()
        self.ref_path.setPlaceholderText("No reference file loaded")
        self.show_ref_preview_btn.setEnabled(False)

    # -----------------
    # Preview last field
    # -----------------

    def _preview_last_field(self):
        field = self.ctrl.last_field()
        if field is None:
            QtWidgets.QMessageBox.information(self, "Preview", "No field computed yet.\nApply correction to an image first.")
            return

        # fake payload: treat field as both fit_input and gauss_field for visualization
        # center at max or (0,0) if flat
        yy_max, xx_max = np.unravel_index(int(np.argmax(field)), field.shape)
        center_xy = (float(xx_max), float(yy_max))

        # build a temporary model for displaying dx/dy/sigma (only for info text)
        dx, dy = _compute_center_offsets_from_xy(center_xy[0], center_xy[1], field.shape)
        tmp_model = GaussianReferenceModel(
            dx_px=float(dx),
            dy_px=float(dy),
            sigma_x_px=max(1.0, 0.35 * field.shape[1]),
            sigma_y_px=max(1.0, 0.35 * field.shape[0]),
            amp=float(np.max(field) - np.percentile(field, 5)),
            offset=float(np.percentile(field, 5)),
            ref_shape_yx=field.shape,
        )

        dlg = CorrectionPreviewDialog(
            raw=field,
            fit_input=field,
            gauss_field=field,
            model=tmp_model,
            center_xy=center_xy,
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

        try:
            self.enable_cb.setChecked(bool(c.enabled))
            self.mode_combo.setCurrentText(str(c.mode))
            self.norm_combo.setCurrentText(str(c.normalize_to))
            self.maxgain_spin.setValue(float(c.max_gain))

            self.blur_sig_x.setValue(float(c.estimation_blur_sigma_x_px))
            self.blur_sig_y.setValue(float(c.estimation_blur_sigma_y_px))
            self.downsample_spin.setValue(int(c.downsample))

            model = self.ctrl.reference_model()
            if model is not None:
                if self.ctrl.reference_filename():
                    self.ref_path.setText(self.ctrl.reference_filename())
                self.dx_spin.setValue(float(model.dx_px))
                self.dy_spin.setValue(float(model.dy_px))
                self.sigx_spin.setValue(float(model.sigma_x_px))
                self.sigy_spin.setValue(float(model.sigma_y_px))
                self.show_ref_preview_btn.setEnabled(self.ctrl.has_reference_preview())
            else:
                if not self.ref_path.text():
                    self.ref_path.setPlaceholderText("No reference file loaded")
                self.show_ref_preview_btn.setEnabled(False)

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


if __name__ == "__main__":
    import sys

    app = QtWidgets.QApplication(sys.argv)

    ctrl = RollingBallCorrectionController()
    w = RollingBallCorrectionWidget(ctrl)
    w.show()

    sys.exit(app.exec_())