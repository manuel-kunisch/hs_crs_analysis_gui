"""Qt front-end for :mod:`hs_mosaic.widgets.unmixing_diagnostics`.

Provides one non-modal dialog with two tabs:

``Dataset``
    How many components the data can support at all: singular value
    spectrum, estimated noise floor and the resulting ``K_eff``.

``Separability``
    Whether a given set of component spectra can actually be told apart --
    per-component ``eta``, the noise/error amplification it implies, and the
    pairwise cosine similarity matrix.

The dialog pulls its data through callables rather than snapshots, so the same
instance can be opened from the analysis widget, the ROI manager and the result
viewer and always shows current state.

Also exposes ``rank_badge`` and ``separability_badge``, which render the
same information as a short coloured one-liner for inline status labels.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets

from hs_mosaic.widgets.unmixing_diagnostics import (
    ETA_CRITICAL,
    ETA_GOOD,
    MIN_NOISE_PIXELS,
    RankEstimate,
    Separability,
    effective_rank,
    effective_rank_from_cube,
    estimate_noise_sigma,
    estimate_snr,
    max_sparse_components,
    separability,
)

_NOISE_EPS = 1e-12

# Verdict -> (table row tint, badge text colour). Alpha keeps the tint readable
# on both the light and the dark palette.
_VERDICT_COLORS = {
    "good": (QtGui.QColor(60, 160, 90, 70), "#3faa60"),
    "marginal": (QtGui.QColor(210, 160, 40, 80), "#d0a030"),
    "critical": (QtGui.QColor(200, 70, 70, 80), "#d05050"),
    "empty": (QtGui.QColor(128, 128, 128, 60), "#909090"),
}

_TABLE_COLUMNS = [
    ("Component", "Component name from the ROI table"),
    ("eta", "Fraction of this spectrum no combination of the others can imitate.\n"
            "1 = orthogonal, 0 = not separable."),
    ("1/eta", "Noise and calibration-error amplification when solving for abundances"),
    ("Closest to", "Component it is most similar to"),
    ("max cos", "Cosine similarity with that component"),
    ("SNR for 10%", "Raw SNR needed for ~10 % abundance accuracy"),
    ("Verdict", f"good: eta >= {ETA_GOOD}   marginal: eta >= {ETA_CRITICAL}   critical: below"),
]


def _fmt(value: float, digits: int = 3) -> str:
    """Format a float, rendering non-finite values as an infinity sign."""
    if value is None or not np.isfinite(value):
        return "∞"
    return f"{value:.{digits}f}"


def _fmt_snr(value: float) -> str:
    if value is None or not np.isfinite(value):
        return "∞"
    if value >= 1e4:
        return f"{value:.0e}"
    return f"{value:.0f}"


def _cube_fingerprint(cube: np.ndarray) -> tuple:
    """Cheap identity for caching: shape, dtype and a strided checksum."""
    arr = np.asarray(cube)
    stride = max(1, arr.size // 4096)
    sample = arr.reshape(-1)[::stride]
    return (arr.shape, str(arr.dtype), float(np.nansum(sample.astype(np.float64))))


# ---------------------------------------------------------------------------
# Inline badges
# ---------------------------------------------------------------------------

def rank_badge(rank: RankEstimate | None, n_components: int | None = None) -> tuple[str, str]:
    """Short ``(text, css_colour)`` summary of an effective-rank estimate."""
    if rank is None:
        return ("K_eff: not computed", _VERDICT_COLORS["empty"][1])
    k = rank.k_eff
    text = f"K_eff ≈ {k}"
    if not rank.has_noise_estimate:
        text += " (variance only)"
        return (text, _VERDICT_COLORS["marginal"][1])
    if n_components is None:
        return (text, _VERDICT_COLORS["good"][1])
    if n_components > k:
        return (f"{text} — {n_components} requested ⚠", _VERDICT_COLORS["critical"][1])
    return (f"{text} — {n_components} requested", _VERDICT_COLORS["good"][1])


def separability_badge(sep: Separability | None) -> tuple[str, str]:
    """Short ``(text, css_colour)`` summary of a separability result."""
    if sep is None or sep.n_components == 0:
        return ("separability: no spectra", _VERDICT_COLORS["empty"][1])
    worst = int(np.argmin(np.where(sep.empty, np.inf, sep.eta)))
    eta_min = sep.eta_min
    if not np.isfinite(eta_min):
        return ("separability: no valid spectra", _VERDICT_COLORS["empty"][1])
    verdict = sep.verdict(worst)
    text = f"min η = {eta_min:.3f} ({sep.labels[worst]})"
    if sep.overdetermined:
        text += f" — {sep.n_components} components > {sep.n_channels} channels ⚠"
    elif verdict == "critical":
        text += " ⚠"
    return (text, _VERDICT_COLORS[verdict][1])


def apply_badge(label: QtWidgets.QLabel, text_color: tuple[str, str]) -> None:
    """Write a ``(text, colour)`` badge into an existing ``QLabel``."""
    text, color = text_color
    label.setText(text)
    label.setStyleSheet(f"color: {color};")


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class UnmixingDiagnosticsDialog(QtWidgets.QDialog):
    """Non-modal diagnostics window shared by all call sites.

    Parameters
    ----------
    cube_getter
        Returns the spectral cube shaped ``(channels, height, width)``, or
        ``None`` when no data is loaded.
    spectra_getter
        Returns ``(H, source_name)`` where ``H`` is shaped
        ``(n_components, n_channels)``. ``H`` may be ``None``.
    label_getter
        Maps a 0-based component index to a display name.
    color_getter
        Maps a 0-based component index to an RGBA tuple, used to tint the
        component names so they match the rest of the GUI.
    noise_getter
        Returns ``{"sigma": per-channel vector, "label": str, "n_pixels": int}``
        measured from a user-marked noise/background region, or ``None`` when no
        such region exists. When available, the Dataset tab offers it as the
        noise source and whitens the data with it before the rank test.
    """

    DATASET_TAB = 0
    SEPARABILITY_TAB = 1

    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        cube_getter: Callable[[], np.ndarray | None] | None = None,
        spectra_getter: Callable[[], tuple[np.ndarray | None, str]] | None = None,
        label_getter: Callable[[int], str] | None = None,
        color_getter: Callable[[int], tuple] | None = None,
        noise_getter: Callable[[], dict | None] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Unmixing Diagnostics")
        self.setModal(False)
        self.resize(880, 640)

        self._cube_getter = cube_getter
        self._spectra_getter = spectra_getter
        self._label_getter = label_getter or (lambda i: f"Component {i + 1}")
        self._color_getter = color_getter

        self._noise_getter = noise_getter
        # Per-source cache: source -> (cube_fp, sigma_fp, estimate, snr).
        self._rank_cache: dict[str, tuple] = {}
        self._immerkaer_cache: tuple[tuple, float] | None = None
        # None = auto-pick (prefer the ROI estimate when one exists); a string
        # is a sticky user choice from the combo box.
        self._noise_source: str | None = None
        self._last_noise_info: dict | None = None
        self._last_snr: float = float("nan")
        self._updating_noise_combo = False
        self._last_separability: Separability | None = None

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_dataset_tab(), "Dataset")
        self.tabs.addTab(self._build_separability_tab(), "Separability")

        buttons = QtWidgets.QHBoxLayout()
        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.setToolTip("Recompute both tabs from the current data")
        self.refresh_button.clicked.connect(lambda: self.refresh(force=True))
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.close)
        buttons.addWidget(self.refresh_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.tabs)
        layout.addLayout(buttons)
        self.setLayout(layout)

    # -- construction -------------------------------------------------------

    def _build_dataset_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)

        self.rank_headline = QtWidgets.QLabel("Not computed yet.")
        font = self.rank_headline.font()
        font.setPointSize(max(11, font.pointSize() + 3))
        font.setBold(True)
        self.rank_headline.setFont(font)
        layout.addWidget(self.rank_headline)

        self.rank_subline = QtWidgets.QLabel("")
        self.rank_subline.setWordWrap(True)
        layout.addWidget(self.rank_subline)

        source_row = QtWidgets.QHBoxLayout()
        source_row.addWidget(QtWidgets.QLabel("Noise estimate:"))
        self.noise_source_combo = QtWidgets.QComboBox()
        self.noise_source_combo.setToolTip(
            "Automatic: per-channel Immerkaer estimate from image smoothness.\n"
            "Background ROI: per-channel standard deviation of the pixels inside\n"
            "the ROIs marked as Background in the ROI Manager; the data is then\n"
            "whitened channel by channel, which is the statistically correct\n"
            "variant when channels have different gains or exposure times."
        )
        self.noise_source_combo.currentIndexChanged.connect(self._on_noise_source_changed)
        source_row.addWidget(self.noise_source_combo)
        source_row.addStretch(1)
        layout.addLayout(source_row)

        self.scree_plot = pg.PlotWidget()
        self.scree_plot.setLabel("left", "Singular value")
        self.scree_plot.setLabel("bottom", "Component index")
        self.scree_plot.setLogMode(x=False, y=True)
        self.scree_plot.showGrid(x=True, y=True, alpha=0.3)
        self.scree_plot.addLegend()
        layout.addWidget(self.scree_plot, stretch=1)

        self.rank_details = QtWidgets.QLabel("")
        self.rank_details.setWordWrap(True)
        self.rank_details.setTextFormat(QtCore.Qt.RichText)
        layout.addWidget(self.rank_details)
        return page

    def _build_separability_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)

        self.sep_headline = QtWidgets.QLabel("Not computed yet.")
        font = self.sep_headline.font()
        font.setPointSize(max(11, font.pointSize() + 3))
        font.setBold(True)
        self.sep_headline.setFont(font)
        layout.addWidget(self.sep_headline)

        self.sep_subline = QtWidgets.QLabel("")
        self.sep_subline.setWordWrap(True)
        layout.addWidget(self.sep_subline)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        self.sep_table = QtWidgets.QTableWidget(0, len(_TABLE_COLUMNS))
        self.sep_table.setHorizontalHeaderLabels([c[0] for c in _TABLE_COLUMNS])
        for col, (_, tip) in enumerate(_TABLE_COLUMNS):
            self.sep_table.horizontalHeaderItem(col).setToolTip(tip)
        self.sep_table.horizontalHeader().setStretchLastSection(True)
        self.sep_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.sep_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.sep_table.verticalHeader().setVisible(False)
        splitter.addWidget(self.sep_table)

        heat_container = QtWidgets.QWidget()
        heat_layout = QtWidgets.QVBoxLayout(heat_container)
        heat_layout.setContentsMargins(0, 0, 0, 0)
        heat_layout.addWidget(QtWidgets.QLabel("<b>Pairwise cosine similarity</b>"))
        self.cosine_plot = pg.PlotWidget()
        self.cosine_plot.setAspectLocked(True)
        self.cosine_plot.invertY(True)
        self.cosine_image = pg.ImageItem()
        self.cosine_plot.addItem(self.cosine_image)
        heat_layout.addWidget(self.cosine_plot)
        self.cosine_hint = QtWidgets.QLabel(
            "Bright off-diagonal cells are pairs that look alike in the current channels."
        )
        self.cosine_hint.setWordWrap(True)
        heat_layout.addWidget(self.cosine_hint)
        splitter.addWidget(heat_container)
        splitter.setSizes([520, 340])

        layout.addWidget(splitter, stretch=1)

        self.sep_rules = QtWidgets.QLabel("")
        self.sep_rules.setWordWrap(True)
        self.sep_rules.setTextFormat(QtCore.Qt.RichText)
        layout.addWidget(self.sep_rules)
        return page

    # -- public API ---------------------------------------------------------

    def open_on(self, tab_index: int) -> None:
        """Show the dialog on a given tab, refreshing it first."""
        self.tabs.setCurrentIndex(tab_index)
        self.refresh()
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh(self, force: bool = False) -> None:
        """Recompute both tabs. Cached SVD results are reused unless ``force``."""
        self._refresh_dataset(force=force)
        self._refresh_separability()

    def current_rank(self, force: bool = False) -> RankEstimate | None:
        """Effective-rank estimate for the current cube and noise source.

        Cached per source against the cube content and, for the ROI source,
        against the sigma vector, so moving the background ROI invalidates the
        estimate but touching unrelated seeds does not.
        """
        cube = self._current_cube()
        if cube is None:
            self._last_snr = float("nan")
            return None
        fingerprint = _cube_fingerprint(cube)
        noise_info = self._noise_roi_info(cube)
        self._last_noise_info = noise_info
        source = self._active_noise_source(noise_info is not None)
        sigma_fp = self._sigma_fingerprint(noise_info["sigma"]) if source == "roi" else None

        cached = self._rank_cache.get(source)
        if not force and cached is not None and cached[0] == fingerprint and cached[1] == sigma_fp:
            self._last_snr = cached[3]
            return cached[2]

        if source == "roi":
            data_2d = np.moveaxis(cube, 0, -1).reshape(-1, cube.shape[0])
            estimate = effective_rank(
                data_2d,
                noise_sigma=noise_info["sigma"],
                noise_sigma_samples=noise_info["n_pixels"],
            )
            snr = estimate_snr(cube, estimate.noise_sigma)
        else:
            estimate = effective_rank_from_cube(cube)
            snr = estimate_snr(cube, estimate.noise_sigma)
        self._rank_cache[source] = (fingerprint, sigma_fp, estimate, snr)
        self._last_snr = snr
        return estimate

    def cached_rank(self) -> RankEstimate | None:
        """Return the cached estimate only if it still matches the current state.

        Never triggers an SVD; the inline badges must stay cheap. The check
        covers the cube content (strided checksum, ~4096 samples) and, for the
        ROI noise source, the sigma vector, so a newly loaded dataset or a
        moved background ROI simply reports "not computed" instead of showing
        stale numbers.
        """
        if self._cube_getter is None:
            return None
        cube = self._current_cube()
        if cube is None:
            return None
        noise_info = self._noise_roi_info(cube)
        source = self._active_noise_source(noise_info is not None)
        cached = self._rank_cache.get(source)
        if cached is None:
            return None
        sigma_fp = self._sigma_fingerprint(noise_info["sigma"]) if source == "roi" else None
        if cached[0] != _cube_fingerprint(cube) or cached[1] != sigma_fp:
            return None
        return cached[2]

    def current_snr(self) -> float:
        """Global SNR estimate matching the last rank estimate."""
        return self._last_snr

    # -- noise sources --------------------------------------------------------

    def _current_cube(self) -> np.ndarray | None:
        cube = self._cube_getter() if self._cube_getter else None
        if cube is None:
            return None
        cube = np.asarray(cube)
        return cube if cube.ndim == 3 else None

    def _noise_roi_info(self, cube: np.ndarray) -> dict | None:
        """Validated per-channel sigma from the noise getter, or ``None``."""
        if self._noise_getter is None:
            return None
        try:
            info = self._noise_getter()
        except Exception:  # pragma: no cover - getter is app code
            return None
        if not info:
            return None
        sigma = np.asarray(info.get("sigma"), dtype=np.float64).ravel()
        # The sigma vector must match the cube it is meant to whiten.
        if sigma.size != cube.shape[0] or not np.isfinite(sigma).any():
            return None
        return {
            "sigma": sigma,
            "label": str(info.get("label", "background ROI")),
            "n_pixels": int(info.get("n_pixels", 0)),
        }

    def _active_noise_source(self, roi_available: bool) -> str:
        """Resolve which noise source drives the rank estimate right now."""
        if self._noise_source == "auto":
            return "auto"
        if self._noise_source == "roi":
            return "roi" if roi_available else "auto"
        # No explicit choice yet: prefer the ROI estimate when one exists.
        return "roi" if roi_available else "auto"

    @staticmethod
    def _sigma_fingerprint(sigma: np.ndarray) -> tuple:
        """Hashable identity for a sigma vector (NaN-stable)."""
        arr = np.asarray(sigma, dtype=np.float64)
        return tuple(np.where(np.isfinite(arr), np.round(arr, 9), -1.0).tolist())

    def _immerkaer_sigma(self, cube: np.ndarray) -> float:
        """Immerkaer noise level of the cube, cached, for comparison display."""
        fingerprint = _cube_fingerprint(cube)
        if self._immerkaer_cache is not None and self._immerkaer_cache[0] == fingerprint:
            return self._immerkaer_cache[1]
        sigma = estimate_noise_sigma(cube)
        self._immerkaer_cache = (fingerprint, sigma)
        return sigma

    def _on_noise_source_changed(self, index: int) -> None:
        if self._updating_noise_combo:
            return
        data = self.noise_source_combo.itemData(index)
        if data:
            self._noise_source = str(data)
            self._refresh_dataset()

    def current_separability(self) -> Separability | None:
        """Separability of the spectra currently offered by ``spectra_getter``."""
        if self._spectra_getter is None:
            return None
        H, _ = self._spectra_getter()
        if H is None:
            return None
        H = np.asarray(H)
        if H.ndim != 2 or H.shape[0] == 0:
            return None
        labels = [self._label_getter(i) for i in range(H.shape[0])]
        return separability(H, labels=labels)

    # -- rendering ----------------------------------------------------------

    def _refresh_dataset(self, force: bool = False) -> None:
        estimate = self.current_rank(force=force)
        self._populate_noise_combo()
        self.scree_plot.clear()
        if estimate is None:
            self.rank_headline.setText("No dataset loaded.")
            self.rank_subline.setText("")
            self.rank_details.setText("")
            return

        text, color = rank_badge(estimate, self._requested_components())
        self.rank_headline.setText(text)
        self.rank_headline.setStyleSheet(f"color: {color};")
        self.scree_plot.setLabel(
            "left", "Singular value (whitened)" if estimate.whitened else "Singular value"
        )

        sv = estimate.singular_values
        idx = np.arange(1, sv.size + 1)
        floor = max(np.min(sv[sv > 0]) if np.any(sv > 0) else 1e-6, 1e-12)
        safe_sv = np.maximum(sv, floor)
        self.scree_plot.plot(
            idx, safe_sv, pen=pg.mkPen("#4a90d9", width=2),
            symbol="o", symbolSize=7, symbolBrush="#4a90d9", name="Singular values",
        )
        if estimate.has_noise_estimate and np.isfinite(estimate.noise_threshold):
            line = pg.InfiniteLine(
                pos=np.log10(max(estimate.noise_threshold, floor)),
                angle=0,
                pen=pg.mkPen("#d05050", width=2, style=QtCore.Qt.DashLine),
                label="noise floor",
                labelOpts={"position": 0.05, "color": "#d05050"},
            )
            self.scree_plot.addItem(line)

        if estimate.has_noise_estimate:
            subline = (
                f"{estimate.k_noise} of {sv.size} singular values rise above the estimated "
                f"noise floor. Components beyond that fit noise, not signal."
            )
            if estimate.whitened:
                subline += (
                    " Each channel was divided by its own noise level before the test "
                    "(whitening), so unequal channel gains cannot fake a component."
                )
            self.rank_subline.setText(subline)
        else:
            self.rank_subline.setText(
                "No noise estimate available - showing explained-variance criteria only."
            )

        var = estimate.k_variance
        var_text = "&nbsp;&nbsp;".join(
            f"{int(level * 1000) / 10:g}% variance: <b>{k}</b>" for level, k in sorted(var.items())
        )
        snr = self.current_snr()
        snr_text = f"{snr:.0f}" if np.isfinite(snr) else "n/a"
        max_sparse = max_sparse_components(estimate.n_channels)

        noise_text, noise_warnings = self._describe_noise_estimates(estimate)
        warning_html = "".join(
            f"<br><span style='color: #d0a030;'>⚠ {w}</span>" for w in noise_warnings
        )
        self.rank_details.setText(
            f"{estimate.n_pixels:,} pixels &times; {estimate.n_channels} channels"
            f" &nbsp;|&nbsp; {noise_text}"
            f" &nbsp;|&nbsp; global SNR ≈ {snr_text}<br>"
            f"{var_text}<br>"
            f"<i>With {estimate.n_channels} channels: at most {estimate.n_channels} components "
            f"for arbitrary mixtures. Beyond that, only pixels containing at most "
            f"{max_sparse} components stay uniquely solvable.</i>"
            f"{warning_html}"
        )

    def _describe_noise_estimates(self, estimate: RankEstimate) -> tuple[str, list[str]]:
        """Noise part of the details line, plus warnings.

        Always shows the active estimate and, when both exist, the other one
        for comparison. The two estimators fail in opposite directions
        (image texture inflates the automatic one, signal-dependent noise makes
        a dark region optimistic), so a large gap between them is itself a
        finding worth surfacing.
        """
        warnings: list[str] = []
        info = self._last_noise_info
        cube = self._current_cube()

        if estimate.whitened and info is not None:
            text = (
                f"noise σ ≈ {_fmt(estimate.noise_sigma, 2)} "
                f"(background ROI, {info['n_pixels']:,} px, per channel)"
            )
            roi_sigma = float(estimate.noise_sigma)
            immerkaer_sigma = self._immerkaer_sigma(cube) if cube is not None else float("nan")
            if np.isfinite(immerkaer_sigma):
                text += f" &nbsp;·&nbsp; Immerkær ≈ {_fmt(immerkaer_sigma, 2)}"
            if info["n_pixels"] < MIN_NOISE_PIXELS:
                warnings.append(
                    f"Only {info['n_pixels']} noise pixels; the estimate is statistically "
                    f"shaky below {MIN_NOISE_PIXELS}. Enlarge the background ROI."
                )
        else:
            text = f"noise σ ≈ {_fmt(estimate.noise_sigma, 2)} (Immerkær)"
            immerkaer_sigma = float(estimate.noise_sigma)
            roi_sigma = float(np.nanmedian(info["sigma"])) if info is not None else float("nan")
            if np.isfinite(roi_sigma):
                text += f" &nbsp;·&nbsp; background ROI ≈ {_fmt(roi_sigma, 2)}"

        # Disagreement between the two estimators. The direction says which
        # failure it is: a hotter ROI means the "empty" region has structure,
        # a hotter automatic estimate means signal-dependent noise (or texture).
        if (np.isfinite(roi_sigma) and np.isfinite(immerkaer_sigma)
                and min(roi_sigma, immerkaer_sigma) > _NOISE_EPS):
            ratio = max(roi_sigma, immerkaer_sigma) / min(roi_sigma, immerkaer_sigma)
            if ratio > 2.0 and roi_sigma > immerkaer_sigma:
                warnings.append(
                    f"The background ROI reports {ratio:.1f}× more noise than the automatic "
                    f"estimate; the region likely contains structure. Consider moving it."
                )
            elif ratio > 2.0:
                warnings.append(
                    f"The automatic estimate reports {ratio:.1f}× more noise than the background "
                    f"ROI; the noise is likely signal-dependent, so the ROI-based K_eff is "
                    f"optimistic and the automatic one is the safer number."
                )
        return text, warnings

    def _populate_noise_combo(self) -> None:
        """Rebuild the noise-source combo to match the current availability."""
        info = self._last_noise_info
        roi_available = info is not None
        active = self._active_noise_source(roi_available)

        self._updating_noise_combo = True
        try:
            self.noise_source_combo.clear()
            self.noise_source_combo.addItem("Automatic (Immerkær)", "auto")
            if roi_available:
                self.noise_source_combo.addItem(
                    f"Background ROI: {info['label']} ({info['n_pixels']:,} px)", "roi"
                )
            index = self.noise_source_combo.findData(active)
            self.noise_source_combo.setCurrentIndex(max(index, 0))
            self.noise_source_combo.setEnabled(roi_available)
        finally:
            self._updating_noise_combo = False

    def _refresh_separability(self) -> None:
        sep = self.current_separability()
        self._last_separability = sep
        source = ""
        if self._spectra_getter is not None:
            try:
                _, source = self._spectra_getter()
            except Exception:  # pragma: no cover - defensive, getter is app code
                source = ""

        self.sep_table.setRowCount(0)
        if sep is None:
            self.sep_headline.setText("No component spectra available.")
            self.sep_headline.setStyleSheet("")
            self.sep_subline.setText(
                "Define H seeds in the ROI manager or run an analysis, then reopen this tab."
            )
            self.sep_rules.setText("")
            self.cosine_image.clear()
            return

        text, color = separability_badge(sep)
        self.sep_headline.setText(text)
        self.sep_headline.setStyleSheet(f"color: {color};")
        self.sep_subline.setText(
            f"Source: {source or 'unknown'} — {sep.n_components} components "
            f"over {sep.n_channels} channels."
        )

        snr = self.current_snr()
        rows = sep.summary_rows(snr=snr if np.isfinite(snr) else None)
        self.sep_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            tint = _VERDICT_COLORS[row["verdict"]][0]
            values = [
                row["label"],
                _fmt(row["eta"]),
                _fmt(row["amplification"], 1),
                row["worst_partner_label"],
                _fmt(row["max_cosine"]),
                _fmt_snr(row["required_snr"]),
                row["verdict"],
            ]
            for c, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(str(value))
                if c > 0:
                    item.setTextAlignment(QtCore.Qt.AlignCenter)
                item.setBackground(tint)
                if c == 0 and self._color_getter is not None:
                    try:
                        rgba = self._color_getter(row["index"])
                        item.setForeground(QtGui.QColor(*rgba[:3]))
                    except Exception:  # pragma: no cover - colour lookup is cosmetic
                        pass
                if "predicted_precision" in row and c == 5:
                    item.setToolTip(
                        f"At the estimated SNR of {snr:.0f} this component's abundance is "
                        f"accurate to about {row['predicted_precision'] * 100:.0f} %."
                    )
                self.sep_table.setItem(r, c, item)
        self.sep_table.resizeColumnsToContents()

        self._draw_cosine_matrix(sep)

        rules = []
        if sep.overdetermined:
            rules.append(
                f"<b>{sep.n_components} components exceed {sep.n_channels} channels.</b> "
                f"The spectra are necessarily linearly dependent, so mixed pixels have no "
                f"unique solution - this only works where pixels are near-pure."
            )
        if sep.eta_min < ETA_CRITICAL:
            worst = int(np.argmin(np.where(sep.empty, np.inf, sep.eta)))
            rules.append(
                f"<b>{sep.labels[worst]}</b> is nearly a combination of the others "
                f"(η = {sep.eta_min:.3f}). Noise <i>and</i> any error in its spectrum are "
                f"amplified about {1 / max(sep.eta_min, 1e-9):.0f}×. An extra channel that "
                f"separates it will help far more than a brighter one."
            )
        rules.append(f"Condition number of the spectral matrix: {_fmt(sep.condition_number, 1)}")
        self.sep_rules.setText("<br>".join(rules))

    def _draw_cosine_matrix(self, sep: Separability) -> None:
        matrix = np.abs(np.asarray(sep.cosine_matrix, dtype=np.float64))
        self.cosine_image.setImage(matrix.T, levels=(0.0, 1.0))
        self.cosine_image.setLookupTable(
            pg.colormap.get("inferno").getLookupTable(0.0, 1.0, 256)
        )
        ticks = [[(i + 0.5, sep.labels[i]) for i in range(sep.n_components)]]
        for axis_name in ("bottom", "left"):
            axis = self.cosine_plot.getAxis(axis_name)
            axis.setTicks(ticks)
        self.cosine_plot.setXRange(0, sep.n_components, padding=0.02)
        self.cosine_plot.setYRange(0, sep.n_components, padding=0.02)

    def _requested_components(self) -> int | None:
        """Number of components the user currently asks for, if discoverable."""
        if self._spectra_getter is None:
            return None
        try:
            H, _ = self._spectra_getter()
        except Exception:  # pragma: no cover - defensive
            return None
        if H is None:
            return None
        return int(np.asarray(H).shape[0])
