import logging
import json
import os

import sys
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore, Qt
from pyqtgraph.dockarea import DockArea, Dock

from hs_mosaic.composite_image import dtype, max_dtype_val
from hs_mosaic.widgets import theme
from hs_mosaic.widgets.data_managers import ImageLoader
from hs_mosaic.widgets.hs_image_view import RamanImageView
from hs_mosaic.widgets.roi_manager_pg import ROIManager
from hs_mosaic.widgets.spectral_axis import (
    INDEX_UNIT,
    is_index_unit,
    normalize_spectral_unit,
    spectral_axis_label,
    spectral_unit_display,
    spectral_unit_suffix,
)

logger = logging.getLogger('Data Manager')


class DataWidget(QtWidgets.QWidget):
    """
    Main class to manage raw data handling
    """
    request_binning_signal = QtCore.pyqtSignal(int)
    # Pixel readout under the cursor, formatted for the main-window status bar
    hover_info_signal = QtCore.pyqtSignal(str)

    # Fill colors of the three draggable RGB band regions on the timeline
    RGB_FILLS = ((235, 70, 70, 60), (70, 200, 90, 60), (80, 130, 255, 70))

    def __init__(self, img=None, init_roi_plot_widget=False, color_manager=None):
        super().__init__()
        # widgets initialized in other methods 
        self.show_processed_image_check = None
        self.projection_mode_combo = None
        self.auto_play_button = None
        self.auto_play_speed_spinbox = None
        self.image_selection_slider = None
        self.lut_combo_box = None
        self.overview_dock = None
        self.raman_raw_image_view = None
        self.image_view_dock = None
        self.dock_area = None
        self.linescan_dock = None
        self.dock_area_widget = None
        self.roi_avg_lines = None
        self.roi_avg_plot_wid = None
        self.roi_plot_dock = None
        self.dock_area_layout = None
        self.image = img
        self._binning_factor: int = 1
        # Cached false-colour composite RGB(A) from the result viewer.
        # Populated whenever CompositeImageViewWidget.compositeImageChanged
        # fires; consumed by the "Composite from analysis" projection mode.
        self._cached_composite_rgb: np.ndarray | None = None
        self.layout = QtWidgets.QVBoxLayout(self)
        self.setLayout(self.layout)

        self.color_manager = color_manager
        # Initialize the widgets
        self.init_dock_area()

        # Dock with overview images is left out for the sake of covenience, here multiple image views are shown
        # self.init_overview_dock()

        # Initialize the toolbar with widgets to modify the image view
        self.init_toolbar()

        if init_roi_plot_widget:
            self.roi_manager.plot_roi_signal.connect(self.plot_roi_average)
            self.roi_manager.remove_roi_plot_signal.connect(self.remove_plot_roi)
            self.init_roi_avg_plot()

        # set the current colormap to the selected one in the toolbar
        self.update_lut(self.lut_combo_box.currentIndex())

    def nframes(self):
        return self.image.shape[0]

    def init_roi_avg_plot(self):
        self.roi_plot_dock = None
        self.roi_avg_plot_wid = pg.PlotWidget(title="ROI Average Plot")
        self.roi_avg_plot_wid.addLegend()
        # Add labels to the PlotWidget
        self.roi_avg_plot_wid.setLabel('bottom', text=spectral_axis_label("cm⁻¹"))
        self.roi_avg_plot_wid.setLabel('left', text='Intensity [a.u.]')
        self.roi_avg_lines = dict()

    def init_dock_area(self):
        self.dock_area_widget = QtWidgets.QWidget(self)  # Placeholder widget to contain the DockArea
        self.layout.addWidget(self.dock_area_widget)

        self.dock_area_layout = QtWidgets.QVBoxLayout(self.dock_area_widget)  # Layout for the placeholder widget
        self.dock_area = DockArea()
        self.dock_area_layout.addWidget(self.dock_area)

        self.linescan_dock = Dock("Linescan", size=(42, 720))
        self.linescan_dock.setStretch(42, 720)
        self.image_view_dock = Dock("Image", size=(900, 900))
        self.image_view_dock.setStretch(900, 900)
        # Adding the docks to the DockArea()


        self.dock_area.addDock(self.image_view_dock, 'top')
        self.dock_area.addDock(self.linescan_dock, 'left', self.image_view_dock)
        # give image view dock more space; the bottom row (seed spectra +
        # ROI table) keeps a workable share of the height
        self.image_view_dock.setStretch(900, 560)

        # linescan_dock.hideTitleBar()
        line_plot_widget = pg.PlotWidget(title="Linsecan")
        self.linescan_dock.addWidget(line_plot_widget)

        # Add Plot item to show axis labels
        plot = pg.PlotItem(title='ImView')
        plot.setTitle()
        plot.setLabel(axis='left', text='y [px]')
        plot.setLabel(axis='bottom', text='x [px]')
        self.raman_raw_image_view = RamanImageView(view=plot, discreteTimeLine=True, roi_plot_widget=line_plot_widget)  # Create a pg.ImageView() object
        self.raman_raw_image_view.view.setDefaultPadding(0)
        self.raman_raw_image_view.setColorMap(pg.colormap.get('plasma'))
        self.raman_raw_image_view.ui.roiBtn.setText("Linescan")
        self.raman_raw_image_view.ui.roiBtn.toggled.connect(self.set_linescan_visible)

        # To hide the Linescan ROI hide the dock...

        # Disable the ROI menu
        # self.raman_raw_image_view.ui.roiBtn.hide()
        # Connect ROI selection change event
        self.raman_raw_image_view.roi.sigRegionChanged.connect(self.update_plot)
        # self.image_item = image_file  # Create a sample image

        # Setting the size of the image view
        self.image_view_dock.addWidget(self.raman_raw_image_view, 0, 0, 16, 16)

        # Initialize the ROI manager and give it access to the image view
        self.roi_manager = ROIManager(self.raman_raw_image_view, color_manager=self.color_manager)
        # add the ROI manager widgets to the dock area
        self.dock_area.addDock(self.roi_manager.roi_table_dock, "bottom")
        self.dock_area.addDock(self.roi_manager.roi_plot_dock, "left", self.roi_manager.roi_table_dock)
        self.roi_manager.roi_table_dock.setStretch(810, 440)
        self.roi_manager.roi_plot_dock.setStretch(560, 440)
        self.roi_manager.processed_data_signal.connect(lambda data:
                                                       self.callback_processed_img(
                                                           self.show_processed_image_check.isChecked(), data))
        self.set_linescan_visible(False)
        self._init_band_regions()
        self._init_hover_readout()

    def _init_band_regions(self):
        """Draggable band-selection regions on the timeline below the image.

        One neutral region for "Band average" mode and three tinted ones for
        "RGB composite" mode, all in frame-index coordinates (the timeline
        x-axis). Rendering is debounced so dragging stays fluid on big stacks.
        """
        timeline_plot = self.raman_raw_image_view.ui.roiPlot
        self.band_region = pg.LinearRegionItem(
            brush=(255, 255, 255, 26), hoverBrush=(255, 255, 255, 48),
            pen=pg.mkPen(theme.INK_2),
        )
        self.band_region.setZValue(15)
        self.band_region.hide()
        timeline_plot.addItem(self.band_region)
        self.rgb_regions = []
        for fill, name in zip(self.RGB_FILLS, "RGB"):
            region = pg.LinearRegionItem(
                brush=fill, hoverBrush=fill[:3] + (fill[3] + 40,),
                pen=pg.mkPen(fill[:3]),
            )
            region.setZValue(15)
            region.hide()
            label = pg.InfLineLabel(region.lines[0], text=name, position=0.85,
                                    anchors=[(-0.2, 0.5), (-0.2, 0.5)], color=theme.INK_2)
            region.hs_label = label
            timeline_plot.addItem(region)
            self.rgb_regions.append(region)
        self._regions_initialized = False
        self._band_mean_cache = {}
        self._range_render_timer = QtCore.QTimer(self, singleShot=True, interval=40)
        self._range_render_timer.timeout.connect(self._render_range_mode)
        for region in (self.band_region, *self.rgb_regions):
            region.sigRegionChanged.connect(self._schedule_range_render)

    def _init_hover_readout(self):
        """Live pixel readout + spectrum-under-cursor (throttled to ~30 Hz)."""
        self._hover_proxy = pg.SignalProxy(
            self.raman_raw_image_view.scene.sigMouseMoved,
            rateLimit=30, slot=self._on_image_hover,
        )
        self._hover_inside_image = False

    def set_linescan_visible(self, visible: bool):
        self.linescan_dock.setVisible(visible)
        self.raman_raw_image_view.ui.roiBtn.blockSignals(True)
        self.raman_raw_image_view.ui.roiBtn.setChecked(visible)
        self.raman_raw_image_view.ui.roiBtn.blockSignals(False)
        self.raman_raw_image_view.roiClicked()

    def init_overview_dock(self):
        self.overview_dock = Dock("Overview", size=(150, 300))
        self.dock_area.addDock(self.overview_dock, 'bottom', self.linescan_dock)

        self.overview_image_views = []

        for i in range(2):
            for j in range(2):
                image_view = pg.ImageView()
                self.overview_dock.addWidget(image_view, i, j)
                self.overview_image_views.append(image_view)

        self.image_selection_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        if self.image is not None:
            self.image_selection_slider.setRange(0, self.image.shape[0] - 1)
            self.image_selection_slider.valueChanged.connect(self.update_overview_images)
            # self.overview_dock.addWidget(self.image_selection_slider, 'bottom')

        self.update_overview_images()  # Call this to display initial images

    def set_spectral_units(self, unit: str):
        unit = normalize_spectral_unit(unit)
        self.roi_manager.spectral_units = unit
        self.roi_manager.roi_plotter.set_spectral_units(unit)
        self.raman_raw_image_view.set_spectral_units(unit)
        if self.roi_avg_plot_wid is not None:
            has_custom_labels = bool(getattr(self.roi_manager.roi_plotter, "axis_labels", None))
            self.roi_avg_plot_wid.setLabel(
                'bottom',
                text='Channel' if has_custom_labels else spectral_axis_label(unit),
            )

    def set_spectral_axis_labels(self, labels):
        self.raman_raw_image_view.set_axis_labels(labels)
        self.roi_manager.roi_plotter.set_axis_labels(labels)
        self.roi_manager.axis_labels = None if labels is None else [str(label) for label in labels]
        if self.roi_avg_plot_wid is not None:
            self.roi_avg_plot_wid.setLabel(
                'bottom',
                text='Channel' if labels is not None else spectral_axis_label(self.roi_manager.spectral_units),
            )

    def init_toolbar(self):
        """One compact control row under the image view."""
        # Display mode: how the spectral stack is collapsed into the shown image
        self.projection_mode_combo = QtWidgets.QComboBox(self)
        mode_items = [
            ("Single band", "none",
             "Browse single bands with the timeline slider below the image."),
            ("Band average", "band_range",
             "Mean image of a wavenumber window.\n"
             "Drag the shaded region on the timeline to choose the bands."),
            ("RGB composite", "rgb",
             "False-color composite of three band windows.\n"
             "Drag the R/G/B regions on the timeline to choose them."),
            ("Average (all bands)", "average", "Mean over the whole stack."),
            ("Max projection", "max", "Per-pixel maximum over the whole stack."),
            ("Min projection", "min", "Per-pixel minimum over the whole stack."),
            ("Composite (from analysis)", "composite",
             "Mirror the false-color composite shown in the result viewer.\n"
             "Updates live whenever colors or histograms change there."),
        ]
        for label, data, tip in mode_items:
            self.projection_mode_combo.addItem(label, data)
            self.projection_mode_combo.setItemData(
                self.projection_mode_combo.count() - 1, tip, QtCore.Qt.ToolTipRole)
        self.projection_mode_combo.setToolTip("Display mode of the image view")
        self.projection_mode_combo.currentIndexChanged.connect(self.on_projection_mode_changed)

        self.lut_combo_box = QtWidgets.QComboBox(self)
        self.lut_combo_box.addItems(['grey', 'thermal', 'flame', 'yellowy', 'bipolar', 'spectrum', 'cyclic', 'greyclip',
                                     'viridis', 'inferno', 'plasma', 'magma', "red", "green", "blue", "yellow",
                                     "orange", "purple", "pink", "magenta", "custom"])
        self.lut_combo_box.setCurrentIndex(2)
        self.lut_combo_box.setToolTip("Lookup table (colormap) of the image")
        self.lut_combo_box.currentIndexChanged.connect(self.update_lut)

        def _tool_button(icon_name, tooltip, slot=None, checkable=False, checked=False):
            button = QtWidgets.QToolButton(self)
            button.setIcon(theme.icon(icon_name))
            button.setToolTip(tooltip)
            button.setCheckable(checkable)
            button.setChecked(checked)
            if slot is not None:
                button.clicked.connect(slot)
            return button

        autoscale_button = _tool_button(
            'mdi.contrast-box', "Auto contrast: refit the display levels to the current image (A)",
            slot=lambda: self.autoscale_image(),
        )

        self.auto_play_button = QtWidgets.QToolButton(self)
        self.auto_play_button.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        self.auto_play_button.setCheckable(True)
        self.auto_play_button.setChecked(False)
        self.auto_play_button.clicked.connect(
            lambda checked: self.raman_raw_image_view.set_playing(checked)
        )

        self.auto_play_speed_spinbox = QtWidgets.QDoubleSpinBox(self)
        self.auto_play_speed_spinbox.setRange(0.5, 60.0)
        self.auto_play_speed_spinbox.setSingleStep(0.5)
        self.auto_play_speed_spinbox.setDecimals(1)
        self.auto_play_speed_spinbox.setValue(self.raman_raw_image_view.fps)
        self.auto_play_speed_spinbox.setSuffix(" fps")
        self.auto_play_speed_spinbox.setToolTip("Playback speed of the band sweep")
        self.auto_play_speed_spinbox.valueChanged.connect(self.raman_raw_image_view.set_playback_fps)
        self.raman_raw_image_view.playback_state_changed.connect(self.sync_auto_play_button)

        self.hover_spectrum_button = _tool_button(
            'mdi.chart-bell-curve-cumulative',
            "Hover spectrum: show the spectrum under the cursor in the seed-spectra plot",
            checkable=True, checked=True,
        )
        self.hover_spectrum_button.toggled.connect(self._on_hover_spectrum_toggled)

        self.seed_pixels_button = _tool_button(
            'mdi.scatter-plot',
            "Seed pixels: mark the pixels whose mean spectrum seeds each\n"
            "resonance-driven component (components without a ROI).\n"
            "Updates live with the resonance table; drawn in component colors.",
            checkable=True, checked=True,
        )
        self.seed_pixels_button.toggled.connect(
            lambda checked: self.roi_manager.set_seed_overlay_visible(checked))

        self.show_processed_image_check = QtWidgets.QCheckBox("Processed")
        self.show_processed_image_check.setToolTip(
            "Show the processed (background-subtracted) stack instead of the raw data"
        )
        self.show_processed_image_check.clicked.connect(self.callback_processed_img)

        self.binning_combo_box = QtWidgets.QComboBox(self)
        self.binning_combo_box.addItems(['1', '2', '4', '8', '16'])
        self.binning_combo_box.setCurrentText(str(self._binning_factor))
        self.binning_combo_box.setToolTip("Spatial binning of the loaded data (applies to the analysis too)")
        self.binning_combo_box.currentTextChanged.connect(lambda bin_str: self.request_binning(int(bin_str)))

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(4, 0, 4, 2)
        row.setSpacing(6)
        row.addWidget(QtWidgets.QLabel("Display"))
        row.addWidget(self.projection_mode_combo)
        row.addSpacing(10)
        lut_label = QtWidgets.QLabel()
        lut_label.setPixmap(theme.icon('mdi.palette').pixmap(16, 16))
        lut_label.setToolTip(self.lut_combo_box.toolTip())
        row.addWidget(lut_label)
        row.addWidget(self.lut_combo_box)
        row.addWidget(autoscale_button)
        row.addSpacing(10)
        row.addWidget(self.auto_play_button)
        row.addWidget(self.auto_play_speed_spinbox)
        row.addWidget(self.hover_spectrum_button)
        row.addWidget(self.seed_pixels_button)
        row.addStretch(1)
        row.addWidget(self.show_processed_image_check)
        row.addSpacing(10)
        row.addWidget(QtWidgets.QLabel("Binning"))
        row.addWidget(self.binning_combo_box)
        row_widget = QtWidgets.QWidget()
        row_widget.setMaximumHeight(40)
        row_widget.setLayout(row)

        self.image_view_dock.addWidget(row_widget, row=16, col=0, colspan=16)
        self.sync_auto_play_button(self.raman_raw_image_view.is_playing())

    def sync_auto_play_button(self, is_playing: bool):
        self.auto_play_button.blockSignals(True)
        self.auto_play_button.setChecked(is_playing)
        icon_type = QtWidgets.QStyle.SP_MediaPause if is_playing else QtWidgets.QStyle.SP_MediaPlay
        self.auto_play_button.setIcon(self.style().standardIcon(icon_type))
        self.auto_play_button.setToolTip("Pause autoplay" if is_playing else "Start autoplay")
        self.auto_play_button.blockSignals(False)

    def _current_projection_mode(self) -> str:
        if self.projection_mode_combo is None:
            return "none"
        return str(self.projection_mode_combo.currentData())

    def _set_projection_mode(self, mode: str):
        if self.projection_mode_combo is None:
            return
        idx = self.projection_mode_combo.findData(mode)
        if idx < 0:
            return
        with QtCore.QSignalBlocker(self.projection_mode_combo):
            self.projection_mode_combo.setCurrentIndex(idx)

    def _projection_title(self, mode: str) -> str:
        return {
            "average": "Average of all bands",
            "max": "Max intensity projection",
            "min": "Min intensity projection",
            "composite": "Composite (mirror of result viewer)",
        }.get(mode, "Image")

    # ------------------------------------------------------------------
    # Display modes: band ranges + projections
    # ------------------------------------------------------------------
    def _active_stack(self) -> np.ndarray | None:
        """Stack the display modes and the hover spectrum read from."""
        if (self.show_processed_image_check is not None
                and self.show_processed_image_check.isChecked()
                and self.roi_manager.subtracted_data is not None):
            return self.roi_manager.subtracted_data
        return self.image

    def _spectral_value_text(self, band: int) -> str:
        labels = getattr(self.roi_manager, "axis_labels", None)
        if labels is not None and 0 <= band < len(labels):
            return str(labels[band])
        wavenumbers = self.raman_raw_image_view.wavenumber
        if wavenumbers is not None and 0 <= band < len(wavenumbers):
            unit = getattr(self.raman_raw_image_view, "unit", "")
            if is_index_unit(unit):
                return f"{wavenumbers[band]:g}"
            return f"{wavenumbers[band]:.1f}{spectral_unit_suffix(unit)}"
        return str(band)

    def _range_frames(self, region: pg.LinearRegionItem) -> tuple[int, int]:
        """Inclusive (lo, hi) band indices selected by a timeline region."""
        n_frames = self.nframes() if self.image is not None else 1
        a, b = region.getRegion()
        lo = int(np.clip(round(min(a, b)), 0, n_frames - 1))
        hi = int(np.clip(round(max(a, b)), lo, n_frames - 1))
        return lo, hi

    def _band_mean(self, stack: np.ndarray, lo: int, hi: int) -> np.ndarray:
        """Mean image over bands lo..hi (inclusive), cached per stack + range."""
        key = (id(stack), lo, hi)
        cached = self._band_mean_cache.get(key)
        if cached is not None:
            return cached
        if hi <= lo:
            mean = np.asarray(stack[lo], dtype=np.float32)
        else:
            mean = np.mean(stack[lo:hi + 1], axis=0, dtype=np.float32)
        self._band_mean_cache[key] = mean
        while len(self._band_mean_cache) > 8:
            self._band_mean_cache.pop(next(iter(self._band_mean_cache)))
        return mean

    def _region_desc(self, lo: int, hi: int) -> str:
        if hi <= lo:
            return f"band {lo} ({self._spectral_value_text(lo)})"
        return (f"bands {lo}–{hi} ({self._spectral_value_text(lo)}–{self._spectral_value_text(hi)},"
                f" {hi - lo + 1} bands)")

    def _ensure_region_defaults(self):
        """Place the regions over sensible spans the first time they are used."""
        if self.image is None:
            return
        n = self.nframes()
        bounds = (0, max(0, n - 1))
        for region in (self.band_region, *self.rgb_regions):
            region.setBounds(bounds)
        if self._regions_initialized:
            # clamp existing positions to the new stack
            for region in (self.band_region, *self.rgb_regions):
                lo, hi = region.getRegion()
                with QtCore.QSignalBlocker(region):
                    region.setRegion((np.clip(lo, *bounds), np.clip(hi, *bounds)))
            return
        third = max(1.0, (n - 1) / 3.0)
        with QtCore.QSignalBlocker(self.band_region):
            self.band_region.setRegion((third, 2 * third))
        # R gets the highest bands, B the lowest (spectroscopic convention)
        for k, region in zip((2, 1, 0), self.rgb_regions):
            with QtCore.QSignalBlocker(region):
                region.setRegion((k * third + 0.1 * third, k * third + 0.9 * third))
        self._regions_initialized = True

    def _schedule_range_render(self):
        if not self._range_render_timer.isActive():
            self._range_render_timer.start()

    def _render_range_mode(self, keep_view: bool = True):
        # keep_view=True for the drag-debounce re-renders; a data load passes
        # False so the view range refits the (possibly differently sized) image.
        mode = self._current_projection_mode()
        stack = self._active_stack()
        if stack is None or stack.ndim != 3:
            return
        view = self.raman_raw_image_view
        if mode == "band_range":
            lo, hi = self._range_frames(self.band_region)
            mean = self._band_mean(stack, lo, hi)
            view.title_override = f"Mean of {self._region_desc(lo, hi)}"
            view.setImage(mean, keep_viewbox=keep_view, axes={'x': 1, 'y': 0})
            view.getView().setTitle(view.title_override)
        elif mode == "rgb":
            channels, descs = [], []
            for name, region in zip("RGB", self.rgb_regions):
                lo, hi = self._range_frames(region)
                mean = self._band_mean(stack, lo, hi)
                # robust per-channel normalization so each color fills its range
                sample = mean[::4, ::4]
                high = float(np.percentile(sample, 99.5)) if sample.size else 1.0
                low = float(np.percentile(sample, 1.0)) if sample.size else 0.0
                span = high - low if high > low else 1.0
                channels.append(np.clip((mean - low) / span, 0.0, 1.0))
                descs.append(f"{name}: {self._region_desc(lo, hi)}")
            rgb = np.dstack(channels).astype(np.float32)
            view.title_override = "   ".join(descs)
            view.setImage(rgb, keep_viewbox=keep_view, axes={'x': 1, 'y': 0, 'c': 2},
                          levels=(0.0, 1.0))
            view.getView().setTitle(view.title_override)
        # keep the timeline visible: it hosts the draggable regions
        view.ui.roiPlot.show()

    def display_projection_image(self, mode: str | None = None, keep_view: bool = True):
        mode = self._current_projection_mode() if mode is None else mode
        view = self.raman_raw_image_view
        if mode == "none":
            view.title_override = None
            # "Display Processed Image" stays authoritative in Single band:
            # the projections read the processed stack via _active_stack(),
            # so returning to Single band must not silently show raw data
            # under a still-checked Processed box.
            if (self.show_processed_image_check is not None
                    and self.show_processed_image_check.isChecked()
                    and self.roi_manager.subtracted_data is not None):
                self.display_modified_image(keep_view=keep_view)
            else:
                self.display_raw_image(keep_view=keep_view)
            return
        if mode in ("band_range", "rgb"):
            self._ensure_region_defaults()
            view.stopAutoPlay()
            self._render_range_mode(keep_view)
            return
        if mode == "composite":
            # Mirror the false-colour composite from the result viewer.
            # If no composite is available yet (analysis never ran), fall
            # back to the raw image so the viewer is not left blank.
            rgb = self._cached_composite_rgb
            if rgb is None or rgb.ndim < 3:
                view.title_override = None
                self.display_raw_image(keep_view=keep_view)
                return
            view.stopAutoPlay()
            view.title_override = self._projection_title(mode)
            view.setImage(
                np.asarray(rgb),
                keep_viewbox=keep_view,
                axes={'x': 1, 'y': 0, 'c': 2},  # force rgb mode
                levels=(0, 65535),  # the result viewer's composite is full-scale uint16
            )
            view.getView().setTitle(view.title_override)
            view.ui.roiPlot.show()
            return
        stack = self._active_stack()
        if stack is None:
            return
        if mode == "average":
            projection = np.mean(stack, axis=0, dtype=np.float32)
        elif mode == "max":
            projection = np.max(stack, axis=0)
        elif mode == "min":
            projection = np.min(stack, axis=0)
        else:
            return
        view.stopAutoPlay()
        view.title_override = self._projection_title(mode)
        view.setImage(projection, keep_viewbox=keep_view, axes={'x': 1, 'y': 0})
        view.getView().setTitle(view.title_override)
        view.ui.roiPlot.show()

    def update_composite_mirror(self, rgb_image):
        """
        Slot for `CompositeImageViewWidget.compositeImageChanged`.

        Caches the latest composite RGB(A) image so the "Composite (from
        analysis)" projection mode has something to show, and re-renders
        immediately if that mode is already selected.
        """
        if rgb_image is None:
            self._cached_composite_rgb = None
            return
        arr = np.asarray(rgb_image)
        if arr.ndim < 3:
            return
        self._cached_composite_rgb = arr
        if self._current_projection_mode() == "composite":
            self.display_projection_image("composite", keep_view=True)

    def on_projection_mode_changed(self, *_args):
        mode = self._current_projection_mode()
        previous_mode = getattr(self, "_previous_display_mode", "none")
        self._previous_display_mode = mode
        self._update_mode_ui(mode)
        if self.image is None:
            return
        self.display_projection_image(mode, keep_view=True)
        # one auto-level on mode entry, and again when returning to Single
        # band from ANY mode, so projection-fitted levels never stick to the
        # band display. RGB and the composite mirror fix their own levels.
        if mode == "none":
            if previous_mode != "none":
                self.raman_raw_image_view.autoLevels()
        elif mode not in ("rgb", "composite"):
            self.raman_raw_image_view.autoLevels()

    def _update_mode_ui(self, mode: str):
        """Show/hide the timeline widgets that belong to the current mode."""
        single = mode == "none"
        self.band_region.setVisible(mode == "band_range")
        for region in self.rgb_regions:
            region.setVisible(mode == "rgb")
        timeline = self.raman_raw_image_view.timeLine
        if timeline is not None:
            timeline.setVisible(single)
        for widget in (self.auto_play_button, self.auto_play_speed_spinbox):
            widget.setEnabled(single)
        if not single:
            self.raman_raw_image_view.stopAutoPlay()

    def _on_hover_spectrum_toggled(self, checked: bool):
        if not checked:
            self.roi_manager.roi_plotter.set_cursor_spectrum(None)

    def _on_image_hover(self, args):
        """Status-bar readout + spectrum under the cursor (rate-limited)."""
        view = self.raman_raw_image_view
        item = view.getImageItem()
        item_img = item.image
        if item_img is None:
            return
        pos = args[0]
        p = item.mapFromScene(pos)
        ix, iy = int(np.floor(p.x())), int(np.floor(p.y()))
        # the histogram shares the scene: a cursor outside the image's view
        # box can still map into array bounds and would read phantom pixels
        view_box = item.getViewBox()
        inside = (0 <= ix < item_img.shape[0] and 0 <= iy < item_img.shape[1]
                  and (view_box is None or view_box.sceneBoundingRect().contains(pos)))
        if not inside:
            if self._hover_inside_image:
                self._hover_inside_image = False
                self.hover_info_signal.emit("")
                self.roi_manager.roi_plotter.set_cursor_spectrum(None)
            return
        self._hover_inside_image = True

        # value(s) of the displayed image (mono or RGB)
        sample = item_img[ix, iy]
        if np.ndim(sample) == 0:
            value_text = f"{float(sample):.4g}"
        else:
            value_text = " / ".join(f"{float(v):.3g}" for v in np.ravel(sample)[:3])

        mode = self._current_projection_mode()
        if mode == "none":
            band = view.currentIndex
            shown = f"band {band} @ {self._spectral_value_text(band)}"
        else:
            shown = getattr(view, "title_override", None) or self._projection_title(mode)
        self.hover_info_signal.emit(f"x {ix}   y {iy}   value {value_text}    [{shown}]")

        # live spectrum under the cursor
        if self.hover_spectrum_button.isChecked():
            stack = self._active_stack()
            if stack is not None and stack.ndim == 3 and iy < stack.shape[1] and ix < stack.shape[2]:
                self.roi_manager.roi_plotter.set_cursor_spectrum(stack[:, iy, ix])

    # create new subtracted data
    def callback_processed_img(self, state: bool, data: np.ndarray=None, label_text: str = None):
        # Keep raw, processed, and averaged display paths synchronized in one place.
        # Any change here invalidates cached band means (they read the active stack).
        self._band_mean_cache.clear()
        mode = self._current_projection_mode()
        if mode != "none":
            # computed display modes read the processed stack through
            # _active_stack(), so a re-render covers both toggle directions
            self.display_projection_image(mode, keep_view=True)
            return
        if state:
            if data is not None:
                if not data.size:
                    # callback call with removed subtraction data
                    self.display_raw_image(keep_view=True)
                self.display_modified_image(data, keep_view=True)
                if label_text is not None:
                    self.raman_raw_image_view.getView().setTitle(label_text)
                return
            self.display_modified_image(keep_view=True)
        else:
            self.display_raw_image(keep_view=True)

    def update_overview_images(self):
        if self.image is None:
            return
        selected_image_index = self.image_selection_slider.value()

        for i, image_view in enumerate(self.overview_image_views):
            image = self.image[selected_image_index]
            image_view.setImage(image)


    def update_lut(self, index):
        logger.debug('Updating LUT')
        lut_name = self.lut_combo_box.currentText()
        """ deprecated
        color_dict = {
            "red": (255, 0, 0),
            "green": (0, 255, 0),
            "blue": (0, 0, 255),
            "yellow": (255, 255, 0),
            "orange": (255, 165, 0),
            "purple": (128, 0, 128),
            "pink": (255, 192, 203),
            "magenta": (255, 0, 255)
        }

        if lut_name in color_dict:
            self.raman_raw_image_view.ui.histogram.gradient.loadPreset('grey')
            mono_lut = self.raman_raw_image_view.ui.histogram.gradient.saveState()
            print(mono_lut)
            r, g, b = color_dict[lut_name]

            # Modify the upper tick to the desired color
            tick = mono_lut['ticks'][-1]
            pos = tick[-1][-1]
            c_pos = tick[0]
            new_setting = (int(r), int(g), int(b), int(pos))
            mono_lut['ticks'][-1] = (c_pos, new_setting)

            print(mono_lut)
            self.raman_raw_image_view.ui.histogram.gradient.restoreState(mono_lut)
        """
        try:
            lut_widget = self.raman_raw_image_view.ui.histogram
            lut_widget.gradient.loadPreset(lut_name)
        except KeyError:
            # Own colormap
            if lut_name == 'custom':
                lut_name = None
            self.raman_raw_image_view.setColorMap(self.get_colormap(lut_name))
        return
        # Access the HistogramLUTWidget associated with the image view


    def get_colormap(self, color=None):
        if color is None:
            # Open a QColorDialog to choose a color for colormap
            color = Qt.QColorDialog.getColor()
            if not color.isValid():
                logger.debug('Invalid color choice')
                return
            qcolor = pg.mkColor(color.name())
            # Convert QColor to QColor object
            colormap_color = pg.Color(qcolor.red(), qcolor.green(), qcolor.blue())
        else:
            # Predefined choices
            color_dict = {
                "red": (255, 0, 0),
                "green": (0, 255, 0),
                "blue": (0, 0, 255),
                "yellow": (255, 255, 0),
                "orange": (255, 165, 0),
                "purple": (128, 0, 128),
                "pink": (255, 192, 203),
                "magenta": (255, 0, 255)
            }
            r, g, b = color_dict[color]
            colormap_color = pg.Color(r, g, b)

        # Modify the upper tick of histogram to the desired color
        return pg.ColorMap(pos=[0, 1], color=[(0,0,0), colormap_color])


    def autoscale_image(self):
        self.raman_raw_image_view.autoLevels()

    def update_img(self, img: np.ndarray, preserve_channel: bool = False):
        self.image = img
        self._band_mean_cache.clear()
        # the composite mirror belongs to the previous dataset/binning; clear it
        self._cached_composite_rgb = None
        self._ensure_region_defaults()
        logger.info("Updating ROI manager data")
        self.roi_manager.update_data(img)
        mode = self._current_projection_mode()
        if not preserve_channel and mode == "none":
            self.raman_raw_image_view.request_single_autoplay_cycle(reset_to_start=True)
        # pass data to ROI manager, calculate the subtracted data etc.
        if self.show_processed_image_check.isChecked():
            self.callback_processed_img(True)
        elif mode != "none":
            self.display_projection_image(keep_view=preserve_channel)
        else:
            self.display_raw_image(keep_view=preserve_channel)
        if not preserve_channel and mode != "rgb":
            # a new dataset: refit the display levels with robust percentiles
            # so a few hot pixels cannot flatten the histogram range
            # (RGB mode keeps its fixed 0..1 levels from per-channel normalization)
            self.raman_raw_image_view.autoLevels()

    def display_raw_image(self, keep_view=True):
        logger.info('Displaying image')
        self.raman_raw_image_view.setImage(self.image[...], keep_viewbox=keep_view)


    def display_modified_image(self, modified_data: np.ndarray = None, keep_view=False):
        """
        abstract function to display a modified image e.g. background subtracted of the current data.

        modified_data: np.ndarray of the same shape as the raw image except axis 0 (frames) can vary
        """
        if modified_data is not None:
            if not modified_data.size:
                self.display_raw_image(keep_view)
            else:
                self.raman_raw_image_view.setImage(modified_data[...], keep_viewbox=keep_view)
            return

        # call without arguments to display the subtracted data
        if self.roi_manager.subtracted_data is not None:
            logger.info('Displaying subtracted data')
            logger.debug('Subtracted data shape: %s', self.roi_manager.subtracted_data.shape)
            self.raman_raw_image_view.setImage(self.roi_manager.subtracted_data[...], keep_viewbox=keep_view)
            return

        self.display_raw_image(keep_view)

    def update_plot(self):
        """
        selected_roi, coords = self.raman_raw_image_view.roi.getArrayRegion(self.raman_raw_image_view.imageItem.image,
                                                                  self.raman_raw_image_view.imageItem,
                                                                  returnMappedCoords=True)
        print(coords)‚

        # Get the indices of the pixels within the ROI
        # Crop the image stack using the indices of the ROI
        cropped_stack = image_file[:, coords.astype(int)]1
        """
        pass

    def update_wavenumbers(self, wavenumbers):
        self.raman_raw_image_view.wavenumber = wavenumbers
        logger.debug('Image View Wavenumbers', wavenumbers)
        self.raman_raw_image_view.update_timeline_ticks()

    def plot_roi_average(self, roi_id, z_data, label):
        # Create a new dock
        if self.roi_plot_dock is None:
            self.roi_plot_dock = Dock("ROI Average Plot", size=(500, 300), closable=True)
            # Set attribute to None when closed
            self.roi_plot_dock.sigClosed.connect(lambda: setattr(self, 'roi_plot_dock', None))
            # Add the dock to the dock area
            self.dock_area.addDock(self.roi_plot_dock, 'right', self.roi_manager.roi_table_dock)
            self.roi_plot_dock.addWidget(self.roi_avg_plot_wid)
        self.roi_avg_plot_wid.setLabel(
            'left',
            text='Normalized intensity' if getattr(self.roi_manager, "normalize_roi_plot_to_unity", False) else 'Intensity [a.u.]',
        )

        roi_index = self.roi_manager.roi_id_idx.get(roi_id)
        roi_pen = self.roi_manager.rois[roi_index].pen

        if roi_id in self.roi_avg_lines and self.roi_avg_lines[roi_id]:
            line_item = self.roi_avg_lines[roi_id]
            self.roi_avg_plot_wid.removeItem(line_item)
        # Plot against the spectral axis only if it matches the data length.
        x_values = self.raman_raw_image_view.wavenumber
        if x_values is None or len(x_values) != len(z_data):
            logger.warning(
                "ROI plot axis length mismatch (%s vs %s). Falling back to channel indices.",
                None if x_values is None else len(x_values),
                len(z_data),
            )
            x_values = np.arange(len(z_data))
        l = self.roi_avg_plot_wid.plot(x_values, z_data, pen=roi_pen, name=label)

        self.roi_avg_lines[roi_id] = l
        # Add any additional configurations you need
        # ...

        # Show the dock
        self.roi_plot_dock.show()

    def request_binning(self, binning_factor: int):
        # requests to bin the image and adjusts the view range accordingly
        view = self.raman_raw_image_view.getView()
        view_range = view.viewRange()
        old_binning = self._binning_factor
        self.request_binning_signal.emit(binning_factor)
        scale = old_binning / binning_factor
        self.sync_binning_ui(binning_factor)
        view.setXRange(view_range[0][0] * scale, view_range[0][1] * scale)
        view.setYRange(view_range[1][0] * scale, view_range[1][1] * scale)

    def sync_binning_ui(self, binning_factor: int):
        self._binning_factor = int(binning_factor)
        if self.binning_combo_box is None:
            return

        bin_text = str(self._binning_factor)
        with QtCore.QSignalBlocker(self.binning_combo_box):
            if self.binning_combo_box.findText(bin_text) < 0:
                self.binning_combo_box.addItem(bin_text)
            self.binning_combo_box.setCurrentText(bin_text)

    def remove_plot_roi(self, roi_id):
        if roi_id in self.roi_avg_lines and self.roi_avg_lines[roi_id]:
            line_item = self.roi_avg_lines[roi_id]
            self.roi_avg_plot_wid.removeItem(line_item)


class _NumericEntry(QtWidgets.QDoubleSpinBox):
    """
    QDoubleSpinBox with a QLineEdit-like API:
      - .text() returns a plain numeric string (no suffix)
      - .setText("800.0") works
    """
    def __init__(self, value=0.0, decimals=2, minimum=200.0, maximum=5000.0, step=1.0, width=70):
        super().__init__()
        self.setRange(minimum, maximum)
        self.setDecimals(decimals)
        self.setSingleStep(step)
        self.setValue(float(value))
        self.setKeyboardTracking(False)
        self.setAlignment(QtCore.Qt.AlignRight)
        # self.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.setFixedWidth(width)

    def text(self) -> str:  # keep compatibility with old QLineEdit usage
        v = float(self.value())
        s = f"{v:.{self.decimals()}f}"
        s = s.rstrip("0").rstrip(".")
        return s

    def setText(self, s: str):  # keep compatibility with old QLineEdit usage
        try:
            self.setValue(float(s))
        except Exception:
            # ignore bad input instead of crashing
            pass


class WavenumberLoadDialog(QtWidgets.QDialog):
    """
    Helper window to manually enter or load spectral-axis values from a file.
    """

    def __init__(self, target_length, current_data=None, parent=None):
        super().__init__(parent)
        self.target_length = target_length
        self.loaded_data = current_data
        self.loaded_labels = None
        self.setWindowTitle("Load Custom Spectral Axis")
        self.resize(400, 500)
        self.init_ui()

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Instructions
        info = QtWidgets.QLabel(
            f"Enter or load <b>{self.target_length}</b> values or labels.<br>"
            "Accepted formats: CSV, single column text, space-separated.<br>"
            "Examples: <i>2850, 2930, 3010</i> or <i>DAPI, FITC, Cy5</i>."
        )
        info.setTextFormat(QtCore.Qt.RichText)
        layout.addWidget(info)

        # Text Area
        self.text_edit = QtWidgets.QPlainTextEdit()
        self.text_edit.setPlaceholderText("Paste numeric values or labels here (one per line)...")
        if self.loaded_data is not None:
            # Pre-fill with current data if available
            text_str = "\n".join([str(x) for x in self.loaded_data])
            self.text_edit.setPlainText(text_str)
        layout.addWidget(self.text_edit)

        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        load_btn = QtWidgets.QPushButton("Load from File...")
        load_btn.clicked.connect(self.load_from_file)
        btn_layout.addWidget(load_btn)

        btn_layout.addStretch()

        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        self.apply_btn = QtWidgets.QPushButton("Apply")
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self.validate_and_accept)

        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self.apply_btn)
        layout.addLayout(btn_layout)

        # Status Label
        self.status_label = QtWidgets.QLabel("")
        layout.addWidget(self.status_label)

    def load_from_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open Spectral Axis File", "", "Text Files (*.txt *.csv *.dat);;All Files (*)"
        )
        if path:
            try:
                # Try loading with numpy, usually robust for csv/txt
                data = np.loadtxt(path, delimiter=None)  # Auto-detect whitespace/delimiter usually works
                # If comma separated explicitly without spaces, loadtxt might fail without delimiter arg,
                # but usually it's fine.
                self.text_edit.setPlainText("\n".join([str(x) for x in data.flatten()]))
            except Exception as e:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        self.text_edit.setPlainText(f.read())
                except Exception:
                    QtWidgets.QMessageBox.warning(self, "Load Error", f"Could not parse file:\n{e}")

    def validate_and_accept(self):
        text = self.text_edit.toPlainText()
        # Replace commas with newlines to handle CSV pastes
        text = text.replace(";", "\n")

        try:
            tokens = [
                part.strip()
                for raw_line in text.splitlines()
                for part in raw_line.split(",")
                if part.strip()
            ]

            if len(tokens) == 0:
                raise ValueError("No data entered.")

            if len(tokens) != self.target_length:
                resp = QtWidgets.QMessageBox.question(
                    self, "Dimension Mismatch",
                    f"You provided {len(tokens)} points, but the image has {self.target_length} frames.\n"
                    "Do you want to apply this anyway? (This may cause errors in processing)",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
                )
                if resp != QtWidgets.QMessageBox.Yes:
                    return

            numeric_values = []
            all_numeric = True
            for token in tokens:
                try:
                    numeric_values.append(float(token))
                except ValueError:
                    all_numeric = False
                    break

            if all_numeric:
                self.loaded_data = np.asarray(numeric_values, dtype=np.float32)
                self.loaded_labels = None
            else:
                self.loaded_data = np.arange(len(tokens), dtype=np.float32)
                self.loaded_labels = tokens
            self.accept()

        except Exception as e:
            self.status_label.setText(f"<font color='red'>Error: {e}</font>")


class WavenumberWidget(QtWidgets.QWidget):
    wavenumbers_changed = QtCore.pyqtSignal(np.ndarray)
    save_settings_requested = QtCore.pyqtSignal()

    def __init__(self, n_frames=100, **kwargs):
        super().__init__()
        self.n_frames = int(n_frames)
        self.wavenumbers = None
        self.custom_wavenumbers = None  # Store custom array
        self.custom_axis_labels = None
        self.beam_mode = 0  # 0: pump is variable, 1: stokes is variable

        self.init_ui(**kwargs)
        self.update_wavenums()

    def init_ui(self, max_width=70):
        main_layout = QtWidgets.QVBoxLayout(self)  # Changed to Vertical to stack Mode select on top
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(5)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        # --- Top Bar: Source Selector ---
        top_bar = QtWidgets.QHBoxLayout()
        top_bar.setContentsMargins(10, 5, 10, 0)
        top_bar.addWidget(QtWidgets.QLabel("Source:"))

        self.source_combo = QtWidgets.QComboBox()
        self.source_combo.addItems(["Calculated (Pump/Stokes)", "Custom / Manual"])
        self.source_combo.currentIndexChanged.connect(self.on_source_changed)
        top_bar.addWidget(self.source_combo)

        self.custom_unit_combo = QtWidgets.QComboBox()
        self.custom_unit_combo.addItems(["cm⁻¹", "nm", "Index"])
        self.custom_unit_combo.setFixedWidth(78)
        self.custom_unit_combo.currentIndexChanged.connect(self.update_wavenums)

        top_bar.addSpacing(15)

        top_bar.addWidget(QtWidgets.QLabel("Unit:"))
        top_bar.addWidget(self.custom_unit_combo)
        top_bar.addStretch()

        self.save_axis_btn = QtWidgets.QPushButton("Save wavelength.json...")
        self.save_axis_btn.setToolTip(
            "Save the current spectral-axis settings as wavelength.json for automatic loading with this dataset."
        )
        self.save_axis_btn.clicked.connect(self.save_settings_requested.emit)
        top_bar.addWidget(self.save_axis_btn)

        main_layout.addLayout(top_bar)

        # --- Stacked Widget for Modes ---
        self.stack = QtWidgets.QStackedWidget()
        self.stack.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        main_layout.addWidget(self.stack)

        # PAGE 1: Calculated (Existing Logic)
        self.page_calc = QtWidgets.QWidget()
        self.page_calc.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        calc_layout = QtWidgets.QHBoxLayout(self.page_calc)
        calc_layout.setContentsMargins(10, 8, 10, 8)
        calc_layout.setSpacing(10)
        calc_layout.setAlignment(QtCore.Qt.AlignTop)

        self.pump_beam_group = QtWidgets.QGroupBox("Pump Beam")
        self.pump_beam_group.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        var_beam_layout = QtWidgets.QGridLayout(self.pump_beam_group)
        var_beam_layout.setHorizontalSpacing(10)
        var_beam_layout.setVerticalSpacing(6)

        self.min_max_checkbox = QtWidgets.QCheckBox("Min/Max")
        self.stepsize_checkbox = QtWidgets.QCheckBox("Stepsize")

        button_group = QtWidgets.QButtonGroup(self)
        button_group.setExclusive(True)
        button_group.addButton(self.min_max_checkbox)
        button_group.addButton(self.stepsize_checkbox)
        self.min_max_checkbox.setChecked(True)

        var_beam_layout.addWidget(self.min_max_checkbox, 0, 0, 1, 2)
        var_beam_layout.addWidget(self.stepsize_checkbox, 1, 0, 1, 2)

        self.min_wavelength_entry = _NumericEntry(value=800.0, decimals=2, width=max_width)
        self.max_wavelength_entry = _NumericEntry(value=830.0, decimals=2, width=max_width)
        self.stepsize_entry = _NumericEntry(value=30.0, decimals=3, minimum=0.001, maximum=5000.0, step=0.5,
                                            width=max_width)
        self.stepsize_entry.setEnabled(False)

        var_beam_layout.addWidget(QtWidgets.QLabel("Min:"), 0, 2)
        var_beam_layout.addWidget(self.min_wavelength_entry, 0, 3)
        var_beam_layout.addWidget(QtWidgets.QLabel("nm"), 0, 4)  # Simplified unit label
        var_beam_layout.addWidget(QtWidgets.QLabel("Max:"), 0, 5)
        var_beam_layout.addWidget(self.max_wavelength_entry, 0, 6)
        var_beam_layout.addWidget(QtWidgets.QLabel("nm"), 0, 7)
        var_beam_layout.addWidget(QtWidgets.QLabel("Step:"), 1, 2)
        var_beam_layout.addWidget(self.stepsize_entry, 1, 3)
        var_beam_layout.addWidget(QtWidgets.QLabel("nm"), 1, 4)

        calc_layout.addWidget(self.pump_beam_group)

        # Swap Button
        swap_button = QtWidgets.QToolButton()
        swap_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        swap_button.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_BrowserReload))
        swap_button.setToolTip("Swap which beam is tuned (Pump ↔ Stokes)")
        swap_button.clicked.connect(self.swap_beams)
        calc_layout.addWidget(swap_button)

        # Stokes Group
        self.stokes_beam_group = QtWidgets.QGroupBox("Stokes Beam")
        self.stokes_beam_group.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        fixed_beam_layout = QtWidgets.QGridLayout(self.stokes_beam_group)
        fixed_beam_layout.setHorizontalSpacing(10)
        fixed_beam_layout.setVerticalSpacing(6)

        fixed_label = QtWidgets.QLabel("λ<sub>fixed</sub> =")
        fixed_label.setTextFormat(QtCore.Qt.RichText)
        fixed_beam_layout.addWidget(fixed_label, 0, 0)

        self.fixed_entry = _NumericEntry(value=1064.0, decimals=2, width=max_width)
        fixed_beam_layout.addWidget(self.fixed_entry, 0, 1)
        fixed_beam_layout.addWidget(QtWidgets.QLabel("nm"), 0, 2)

        self.custom_unit_combo.currentTextChanged.connect(
            lambda unit: self.fixed_entry.setEnabled(normalize_spectral_unit(unit) == "cm⁻¹")
        )
        calc_layout.addWidget(self.stokes_beam_group)

        # Add Page 1 to stack
        self.stack.addWidget(self.page_calc)

        # PAGE 2: Custom (New)
        self.page_custom = QtWidgets.QWidget()
        self.page_custom.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        custom_layout = QtWidgets.QHBoxLayout(self.page_custom)
        custom_layout.setContentsMargins(10, 8, 10, 8)
        custom_layout.setAlignment(QtCore.Qt.AlignTop)

        custom_group = QtWidgets.QGroupBox("Custom Spectral Axis")
        custom_group.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        cg_layout = QtWidgets.QHBoxLayout(custom_group)

        self.btn_load_custom = QtWidgets.QPushButton("Edit / Load Axis...")
        self.btn_load_custom.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_FileDialogDetailedView))
        self.btn_load_custom.clicked.connect(self.open_custom_dialog)

        self.btn_remove_custom = QtWidgets.QPushButton("Remove")
        self.btn_remove_custom.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_TrashIcon))
        self.btn_remove_custom.clicked.connect(self.clear_custom_data)
        self.btn_remove_custom.setEnabled(False)

        self.custom_status_label = QtWidgets.QLabel("No data loaded.")
        self.custom_status_label.setStyleSheet("color: gray; font-style: italic;")

        cg_layout.addWidget(self.btn_load_custom)
        cg_layout.addWidget(self.btn_remove_custom)
        cg_layout.addWidget(self.custom_status_label)
        cg_layout.addStretch()

        custom_layout.addWidget(custom_group)
        self.stack.addWidget(self.page_custom)

        # --- Info Group (Shared at bottom) ---
        info_box = QtWidgets.QGroupBox("Info")
        info_layout = QtWidgets.QVBoxLayout(info_box)
        info_layout.setSpacing(4)
        info_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)

        self.min_label = QtWidgets.QLabel("Min: — cm⁻¹")
        self.max_label = QtWidgets.QLabel("Max: — cm⁻¹")
        self.num_label = QtWidgets.QLabel(f"Frames: {self.n_frames}")

        info_layout.addWidget(self.min_label)
        # info_layout.addSpacing(15)
        info_layout.addWidget(self.max_label)
        # info_layout.addSpacing(15)
        info_layout.addWidget(self.num_label)
        info_layout.addStretch()

        # info_layout.addLayout(info_row)

        # Warning label for mismatches
        self.warn_label = QtWidgets.QLabel("")
        self.warn_label.setStyleSheet("color: red; font-weight: bold;")
        self.warn_label.setVisible(False)
        info_layout.addWidget(self.warn_label)

        # Wrap Info in a widget to add to main VBox
        calc_layout.addWidget(info_box)
        main_layout.addStretch(1)

        # --- Connections ---
        self.min_max_checkbox.stateChanged.connect(self.on_min_max_checked)
        self.stepsize_checkbox.stateChanged.connect(self.on_stepsize_checked)

        self.min_wavelength_entry.textChanged.connect(self.update_wavenums)
        self.max_wavelength_entry.textChanged.connect(self.update_wavenums)
        self.stepsize_entry.textChanged.connect(self.update_wavenums)
        self.fixed_entry.textChanged.connect(self.update_wavenums)

    def on_source_changed(self, index):
        self.stack.setCurrentIndex(index)
        if index == 1 and not self.has_custom_source_data() and not is_index_unit(self.custom_unit_combo.currentText()):
            self._set_unit_combo(INDEX_UNIT)
        self.update_wavenums()

    def open_custom_dialog(self):
        current_data = self.custom_axis_labels if self.custom_axis_labels is not None else self.custom_wavenumbers
        dlg = WavenumberLoadDialog(target_length=self.n_frames, current_data=current_data, parent=self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.custom_wavenumbers = dlg.loaded_data
            self.custom_axis_labels = dlg.loaded_labels
            if self.custom_axis_labels is not None:
                self._set_unit_combo(INDEX_UNIT)
            self.update_wavenums()

    def clear_custom_data(self):
        self.custom_wavenumbers = None
        self.custom_axis_labels = None
        self.source_combo.setCurrentIndex(0)  # switches to Calculated mode and calls update_wavenums

    def on_min_max_checked(self, state):
        if state == QtCore.Qt.Checked:
            with QtCore.QSignalBlocker(self.stepsize_checkbox):
                self.stepsize_checkbox.setChecked(False)
            self.min_wavelength_entry.setEnabled(True)
            self.max_wavelength_entry.setEnabled(True)
            self.stepsize_entry.setEnabled(False)
            self.update_wavenums()

    def on_stepsize_checked(self, state):
        if state == QtCore.Qt.Checked:
            with QtCore.QSignalBlocker(self.min_max_checkbox):
                self.min_max_checkbox.setChecked(False)
            self.min_wavelength_entry.setEnabled(True)
            self.max_wavelength_entry.setEnabled(False)
            self.stepsize_entry.setEnabled(True)
            self.update_wavenums()

    def swap_beams(self):
        pump_label = self.pump_beam_group.title()
        stokes_label = self.stokes_beam_group.title()
        self.pump_beam_group.setTitle(stokes_label)
        self.stokes_beam_group.setTitle(pump_label)
        self.beam_mode = (self.beam_mode + 1) % 2
        self.update_wavenums()

    def set_nframes(self, n_frames):
        self.n_frames = int(n_frames)
        self.update_wavenums()

    def is_custom_source_active(self) -> bool:
        return self.source_combo.currentIndex() == 1

    def has_custom_source_data(self) -> bool:
        return self.custom_wavenumbers is not None or self.custom_axis_labels is not None

    def _unit_combo_index(self, unit: str | None) -> int:
        wanted = normalize_spectral_unit(unit)
        for idx in range(self.custom_unit_combo.count()):
            if normalize_spectral_unit(self.custom_unit_combo.itemText(idx)) == wanted:
                return idx
        return -1

    def _set_unit_combo(self, unit: str | None) -> bool:
        idx = self._unit_combo_index(unit)
        if idx < 0 or idx == self.custom_unit_combo.currentIndex():
            return False
        self.custom_unit_combo.setCurrentIndex(idx)
        return True

    def warn_and_switch_from_custom_source(self, parent: QtWidgets.QWidget | None = None) -> bool:
        if not self.is_custom_source_active() or not self.has_custom_source_data():
            return False

        QtWidgets.QMessageBox.warning(
            parent or self,
            "Custom Spectral Axis Disabled",
            "A new dataset was loaded while 'Custom / Manual' spectral-axis mode was active.\n\n"
            "Custom points are dataset-specific and may not match the new data. "
            "The spectral axis was switched back to 'Calculated (Pump/Stokes)'.\n\n"
            "Reload or edit custom points again if this dataset needs a manual axis.",
        )
        self.source_combo.setCurrentIndex(0)
        return True

    def update_wavenums(self):
        channels = max(1, int(self.n_frames))
        is_custom = (self.source_combo.currentIndex() == 1)

        unit_key = normalize_spectral_unit(self.custom_unit_combo.currentText())
        if (
                is_custom
                and (self.custom_wavenumbers is None or self.custom_axis_labels is not None)
                and unit_key != INDEX_UNIT
        ):
            idx = self._unit_combo_index(INDEX_UNIT)
            if idx >= 0:
                with QtCore.QSignalBlocker(self.custom_unit_combo):
                    self.custom_unit_combo.setCurrentIndex(idx)
                unit_key = INDEX_UNIT
        suffix = spectral_unit_suffix(unit_key)

        if is_custom:
            self.btn_remove_custom.setEnabled(self.has_custom_source_data())
            if self.custom_wavenumbers is None:
                self.wavenumbers = np.arange(channels, dtype=np.float32)
                self.custom_axis_labels = None
                self.custom_status_label.setText("Default: Indices")
                # Fallback labels
                self.min_label.setText(f"Min: {float(np.min(self.wavenumbers)):.0f}")
                self.max_label.setText(f"Max: {float(np.max(self.wavenumbers)):.0f}")
                self.warn_label.setVisible(False)
            else:
                self.wavenumbers = self.custom_wavenumbers
                if self.custom_axis_labels is not None:
                    self.custom_status_label.setText(f"Loaded: {len(self.custom_axis_labels)} labels")
                else:
                    self.custom_status_label.setText(f"Loaded: {len(self.wavenumbers)} pts")

                if len(self.wavenumbers) != channels:
                    self.warn_label.setText(f"Size Mismatch: {len(self.wavenumbers)} vs {channels}")
                    self.warn_label.setVisible(True)
                else:
                    self.warn_label.setVisible(False)

                if len(self.wavenumbers) > 0:
                    if self.custom_axis_labels is not None:
                        self.min_label.setText(f"First: {self.custom_axis_labels[0]}")
                        self.max_label.setText(f"Last: {self.custom_axis_labels[-1]}")
                    else:
                        self.min_label.setText(f"Min: {float(np.min(self.wavenumbers)):.2f}{suffix}")
                        self.max_label.setText(f"Max: {float(np.max(self.wavenumbers)):.2f}{suffix}")

        else:
            # --- Calculated Logic ---
            self.warn_label.setVisible(False)
            self.custom_axis_labels = None

            # 1. Get Range
            minimum = float(self.min_wavelength_entry.value())
            if self.min_max_checkbox.isChecked():
                maximum = float(self.max_wavelength_entry.value())
                # ... (swap logic same as before) ...
                if maximum < minimum:
                    minimum, maximum = maximum, minimum
                    with QtCore.QSignalBlocker(self.min_wavelength_entry), QtCore.QSignalBlocker(
                            self.max_wavelength_entry):
                        self.min_wavelength_entry.setValue(minimum)
                        self.max_wavelength_entry.setValue(maximum)

                if channels > 1:
                    stepsize = (maximum - minimum) / (channels - 1)
                else:
                    stepsize = 0.0
                with QtCore.QSignalBlocker(self.stepsize_entry):
                    self.stepsize_entry.setValue(stepsize)
            else:
                stepsize = float(self.stepsize_entry.value())
                maximum = minimum + stepsize * (channels - 1)
                with QtCore.QSignalBlocker(self.max_wavelength_entry):
                    self.max_wavelength_entry.setValue(maximum)

            # 2. Calculate Axis
            # Check if we are doing Raman (Fixed enabled) or Hyperspectral (Fixed disabled)
            if unit_key == INDEX_UNIT:
                self.wavenumbers = np.arange(channels, dtype=np.float32)
            elif unit_key != "nm":
                # --- RAMAN MODE (cm-1) ---
                fixed_wavelength = float(self.fixed_entry.value())

                # Convert nm to cm: factor 1e-7
                lambdas_cm = np.linspace(minimum * 1e-7, maximum * 1e-7, channels, dtype=np.float64)
                fixed_k = 1.0 / (fixed_wavelength * 1e-7)

                k_var = np.reciprocal(lambdas_cm)
                k_fix = np.full(channels, fixed_k, dtype=np.float64)

                if not self.beam_mode:  # 0: pump variable
                    self.wavenumbers = (k_var - k_fix).astype(np.float32)
                else:  # 1: stokes variable
                    self.wavenumbers = (k_fix - k_var).astype(np.float32)
            else:
                # --- HYPERSPECTRAL MODE (nm) ---
                # Just output the tunable range directly in nm
                self.wavenumbers = np.linspace(minimum, maximum, channels, dtype=np.float32)

            # 3. Update Info Box
            if unit_key == INDEX_UNIT:
                self.min_label.setText(f"Min: {float(np.min(self.wavenumbers)):.0f}")
                self.max_label.setText(f"Max: {float(np.max(self.wavenumbers)):.0f}")
            else:
                self.min_label.setText(f"Min: {float(np.min(self.wavenumbers)):.2f}{suffix}")
                self.max_label.setText(f"Max: {float(np.max(self.wavenumbers)):.2f}{suffix}")

        self.num_label.setText(f"Frames: {self.n_frames}")
        self.wavenumbers_changed.emit(self.wavenumbers)

    def export_wavelength_metadata(self) -> dict:
        """Return a wavelength.json-compatible representation of the current axis settings."""
        unit = spectral_unit_display(self.custom_unit_combo.currentText())
        meta = {
            "spectral_unit": unit,
        }

        if self.is_custom_source_active():
            values = self.wavenumbers
            if values is None:
                values = np.arange(max(1, int(self.n_frames)), dtype=np.float32)
            meta["custom_values"] = [float(value) for value in np.asarray(values, dtype=float).ravel()]
            if self.custom_axis_labels is not None:
                meta["custom_labels"] = [str(label) for label in self.custom_axis_labels]
            return meta

        meta["tuned_beam"] = "pump" if self.beam_mode == 0 else "stokes"
        meta["fixed_beam_nm"] = float(self.fixed_entry.value())
        meta["tuned_min_nm"] = float(self.min_wavelength_entry.value())
        if self.min_max_checkbox.isChecked():
            meta["tuned_max_nm"] = float(self.max_wavelength_entry.value())
        else:
            meta["tuned_step_nm"] = float(self.stepsize_entry.value())
        return meta

    def save_wavelength_json(self, default_path: str | None = None):
        if not default_path:
            default_path = os.path.join(os.getcwd(), "wavelength.json")

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save wavelength.json",
            default_path,
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"

        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.export_wavelength_metadata(), fh, indent=2)
                fh.write("\n")
        except Exception as exc:
            logger.exception("Failed to save wavelength metadata to %s", path)
            QtWidgets.QMessageBox.critical(self, "Save failed", f"Could not save wavelength.json:\n{exc}")
            return

        QtWidgets.QMessageBox.information(self, "Saved wavelength.json", f"Saved spectral-axis settings to:\n{path}")

    def apply_wavelength_meta(self, meta: dict, n_frames: int):
        custom_values = meta.get("custom_values")
        custom_labels = meta.get("custom_labels")
        spectral_unit = meta.get("spectral_unit")

        if custom_values is not None or custom_labels is not None:
            self.n_frames = int(n_frames)

            widgets = [
                self.source_combo,
                self.custom_unit_combo,
            ]
            for w in widgets:
                w.blockSignals(True)

            if spectral_unit is not None:
                self._set_unit_combo(spectral_unit)
            elif custom_labels is not None:
                self._set_unit_combo(INDEX_UNIT)

            self.source_combo.setCurrentIndex(1)
            self.stack.setCurrentIndex(1)

            if custom_values is None and custom_labels is not None:
                self.custom_wavenumbers = np.arange(len(custom_labels), dtype=np.float32)
            elif custom_values is not None:
                self.custom_wavenumbers = np.asarray(custom_values, dtype=np.float32)
            else:
                self.custom_wavenumbers = None

            self.custom_axis_labels = None if custom_labels is None else [str(value) for value in custom_labels]

            for w in widgets:
                w.blockSignals(False)

            self.update_wavenums()
            return

        tuned_beam = meta.get("tuned_beam", "pump").lower()
        tuned_min = meta.get("tuned_min_nm")
        tuned_max = meta.get("tuned_max_nm")
        tuned_step = meta.get("tuned_step_nm")
        fixed_nm = meta.get("fixed_beam_nm")
        spectral_unit = meta.get("spectral_unit")

        desired_mode = 0 if tuned_beam == "pump" else 1
        if self.beam_mode != desired_mode:
            self.swap_beams()

        self.n_frames = int(n_frames)

        widgets = [
            self.source_combo,
            self.custom_unit_combo,
            self.min_wavelength_entry,
            self.max_wavelength_entry,
            self.stepsize_entry,
            self.fixed_entry,
            self.min_max_checkbox,
            self.stepsize_checkbox,
        ]
        for w in widgets:
            w.blockSignals(True)

        if spectral_unit is not None:
            self._set_unit_combo(spectral_unit)

        self.source_combo.setCurrentIndex(0)
        self.stack.setCurrentIndex(0)

        if fixed_nm is not None:
            self.fixed_entry.setValue(float(fixed_nm))

        if tuned_min is not None:
            self.min_wavelength_entry.setValue(float(tuned_min))
        if tuned_max is not None:
            self.max_wavelength_entry.setValue(float(tuned_max))

        # choose mode
        if tuned_min is not None and tuned_max is not None:
            self.min_max_checkbox.setChecked(True)
            self.stepsize_checkbox.setChecked(False)
            self.min_wavelength_entry.setEnabled(True)
            self.max_wavelength_entry.setEnabled(True)
            self.stepsize_entry.setEnabled(False)
        else:
            self.min_max_checkbox.setChecked(False)
            self.stepsize_checkbox.setChecked(True)
            if tuned_step is not None:
                self.stepsize_entry.setValue(float(tuned_step))
            self.min_wavelength_entry.setEnabled(True)
            self.max_wavelength_entry.setEnabled(False)
            self.stepsize_entry.setEnabled(True)

        for w in widgets:
            w.blockSignals(False)

        self.update_wavenums()

    def export_state(self) -> dict:
        """Serialize full spectral-axis UI state (not just the derived axis array)."""
        return {
            "version": 1,   # new version with min_nm/max_nm etc.
            "n_frames": int(self.n_frames),

            # UI choices
            "source_index": int(self.source_combo.currentIndex()),  # 0=Calculated, 1=Custom
            "unit": spectral_unit_display(self.custom_unit_combo.currentText()),
            "beam_mode": int(self.beam_mode),  # 0/1

            # calculated-mode inputs (still useful to store even if custom)
            "calc_mode": "minmax" if self.min_max_checkbox.isChecked() else "stepsize",
            "min_nm": float(self.min_wavelength_entry.value()),
            "max_nm": float(self.max_wavelength_entry.value()),
            "step_nm": float(self.stepsize_entry.value()),
            "fixed_nm": float(self.fixed_entry.value()),

            # custom-mode payload
            "custom_values": None if self.custom_wavenumbers is None else self.custom_wavenumbers.tolist(),
            "custom_labels": None if self.custom_axis_labels is None else list(self.custom_axis_labels),
        }

    def import_state(self, state: dict, preserve_current_n_frames: bool = False) -> str | None:
        """Restore spectral-axis UI state. Calls update_wavenums() exactly once at the end."""
        if not isinstance(state, dict) or not state:
            return None

        # Backward-compat
        if "lambda_min" in state and "min_nm" not in state:
            state = {
                "version": 0,
                "n_frames": state.get("n_frames", self.n_frames),
                "source_index": 0,
                "unit": state.get("unit", "cm⁻¹"),
                "beam_mode": state.get("mode", self.beam_mode),
                "calc_mode": "minmax",
                "min_nm": float(state.get("lambda_min", 800.0)),
                "max_nm": float(state.get("lambda_max", 830.0)),
                "step_nm": float(state.get("step_nm", self.stepsize_entry.value())),
                "fixed_nm": float(state.get("fixed_nm", self.fixed_entry.value())),
                "custom_values": None,
            }

        warning_message = None
        effective_frame_count = int(self.n_frames)

        # --- block widget signals while restoring ---
        blockers = [
            QtCore.QSignalBlocker(self.source_combo),
            QtCore.QSignalBlocker(self.custom_unit_combo),
            QtCore.QSignalBlocker(self.min_max_checkbox),
            QtCore.QSignalBlocker(self.stepsize_checkbox),
            QtCore.QSignalBlocker(self.min_wavelength_entry),
            QtCore.QSignalBlocker(self.max_wavelength_entry),
            QtCore.QSignalBlocker(self.stepsize_entry),
            QtCore.QSignalBlocker(self.fixed_entry),
        ]

        # restore frame count (only matters if no image is loaded yet)
        if not preserve_current_n_frames:
            try:
                effective_frame_count = int(state.get("n_frames", self.n_frames))
            except Exception:
                effective_frame_count = int(self.n_frames)
        self.n_frames = int(effective_frame_count)

        custom_vals = state.get("custom_values", None)
        custom_labels = state.get("custom_labels", None)
        custom_length = None
        if custom_vals is not None:
            try:
                custom_length = len(custom_vals)
            except Exception:
                custom_length = None
        elif custom_labels is not None:
            try:
                custom_length = len(custom_labels)
            except Exception:
                custom_length = None

        source_index = int(state.get("source_index", 0))
        if custom_length is not None and custom_length != self.n_frames:
            warning_message = (
                f"Preset custom spectral axis has {custom_length} points, "
                f"but the current dataset has {self.n_frames} frames. "
                f"Falling back to calculated axis."
            )
            custom_vals = None
            custom_labels = None
            source_index = 0

        # restore source + unit
        self.source_combo.setCurrentIndex(source_index)
        self.stack.setCurrentIndex(source_index)

        unit = state.get("unit", INDEX_UNIT if custom_labels is not None else "cm⁻¹")
        uidx = self._unit_combo_index(unit)
        if uidx >= 0:
            self.custom_unit_combo.setCurrentIndex(uidx)

        # restore beam mode (don’t spam swap_beams(); just set)
        try:
            self.beam_mode = int(state.get("beam_mode", self.beam_mode))
        except Exception:
            pass

        # restore numeric inputs
        for key, widget in [
            ("min_nm", self.min_wavelength_entry),
            ("max_nm", self.max_wavelength_entry),
            ("step_nm", self.stepsize_entry),
            ("fixed_nm", self.fixed_entry),
        ]:
            if key in state and state[key] is not None:
                try:
                    widget.setValue(float(state[key]))
                except Exception:
                    pass

        # restore calc mode
        calc_mode = state.get("calc_mode", "minmax")
        if calc_mode == "stepsize":
            self.min_max_checkbox.setChecked(False)
            self.stepsize_checkbox.setChecked(True)
            self.min_wavelength_entry.setEnabled(True)
            self.max_wavelength_entry.setEnabled(False)
            self.stepsize_entry.setEnabled(True)
        else:
            self.min_max_checkbox.setChecked(True)
            self.stepsize_checkbox.setChecked(False)
            self.min_wavelength_entry.setEnabled(True)
            self.max_wavelength_entry.setEnabled(True)
            self.stepsize_entry.setEnabled(False)

        # restore custom array
        if custom_vals is None and custom_labels is None:
            self.custom_wavenumbers = None
            self.custom_axis_labels = None
        else:
            if custom_vals is not None:
                self.custom_wavenumbers = np.asarray(custom_vals, dtype=np.float32)
            elif custom_labels is not None:
                self.custom_wavenumbers = np.arange(len(custom_labels), dtype=np.float32)
            self.custom_axis_labels = None if custom_labels is None else [str(v) for v in custom_labels]

        del blockers  # unblock

        # compute + emit once
        self.update_wavenums()
        return warning_message


class DataHandler(QtWidgets.QWidget):
    """
    Main widget for data handling combining the image loader and wavenumber widget
    """
    def __init__(self, update_image_callback: callable, analysis_widget: QtWidgets.QWidget = None, default_binning:int = 2,
                 normalize: bool = True):
        super().__init__()
        self._normalize = normalize
        self.loader_widget = ImageLoader(self.new_image_loaded, parent=self)
        self.wavenumber_widget = WavenumberWidget()
        self.update_image_callback = update_image_callback
        # add the widget to the loader grid
        analysis_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.loader_widget.main_grid_layout.addWidget(analysis_widget, 2, 0, 4, 6, alignment=QtCore.Qt.AlignTop | QtCore.Qt.AlignBottom)

        self.loader_dock = Dock("Data", size=(360, 720))
        self.loader_dock.setStretch(360, 720)
        self.loader_dock.addWidget(self.loader_widget, 1, 0, 1, 1)
        self.loader_dock.addWidget(self.wavenumber_widget, 0, 0, 1, 1)
        self.slice_selector_widget = QtWidgets.QWidget()
        self.slice_selector_widget.hide()
        slice_layout = QtWidgets.QHBoxLayout(self.slice_selector_widget)
        slice_layout.setContentsMargins(6, 4, 6, 4)
        slice_layout.setSpacing(8)
        self.slice_axis_title_label = QtWidgets.QLabel("Slice:")
        self.slice_selector_spinbox = QtWidgets.QSpinBox()
        self.slice_selector_spinbox.setMinimum(1)
        self.slice_selector_spinbox.setMaximum(1)
        self.slice_selector_spinbox.setValue(1)
        self.slice_selector_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slice_selector_slider.setMinimum(0)
        self.slice_selector_slider.setMaximum(0)
        self.slice_selector_slider.setTickInterval(1)
        self.slice_selector_slider.setTickPosition(QtWidgets.QSlider.TicksBothSides)
        slice_layout.addWidget(self.slice_axis_title_label)
        slice_layout.addWidget(self.slice_selector_spinbox)
        slice_layout.addWidget(self.slice_selector_slider, stretch=1)
        self.loader_dock.addWidget(self.slice_selector_widget, 2, 0, 1, 1)

        self.slice_selector_spinbox.valueChanged.connect(
            lambda value: self._set_current_slice_index(int(value) - 1)
        )
        self.slice_selector_slider.valueChanged.connect(self._set_current_slice_index)

        self._binning_factor = default_binning
        self._source_image = None   # canonical image used for analysis, before spatial binning
        self._analysis_image = None  # 3D or 4D image after spatial binning
        self._display_image = None   # 3D image currently shown in the raw-data widget
        self._suspend_custom_axis_warning = True
        self._current_slice_index = 0
        self._slice_axis_label = "Slice"
        self.wavenumber_widget.save_settings_requested.connect(self.save_wavelength_json)

    def save_wavelength_json(self):
        current_path = getattr(self.loader_widget, "current_path", None)
        if current_path:
            default_dir = os.path.dirname(current_path)
        else:
            default_dir = os.getcwd()
        default_path = os.path.join(default_dir, "wavelength.json")
        self.wavenumber_widget.save_wavelength_json(default_path)

    class _AxisRoleDialog(QtWidgets.QDialog):
        def __init__(self, shape: tuple[int, ...], parent: QtWidgets.QWidget | None = None):
            super().__init__(parent)
            self.setWindowTitle("Interpret 4D Stack")
            layout = QtWidgets.QVBoxLayout(self)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(10)

            info = QtWidgets.QLabel(
                "A 4D stack was detected. Choose which axis contains the spectral channels and "
                "which axis represents the outer z/time dimension."
            )
            info.setWordWrap(True)
            layout.addWidget(info)

            axis_options = [(f"Axis {i} (size {shape[i]})", i) for i in range(len(shape))]

            form = QtWidgets.QFormLayout()
            form.setLabelAlignment(QtCore.Qt.AlignRight)
            self.spectral_combo = QtWidgets.QComboBox()
            self.slice_combo = QtWidgets.QComboBox()
            for label, axis in axis_options:
                self.spectral_combo.addItem(label, axis)
                self.slice_combo.addItem(label, axis)
            # Most microscopy-style 4D inputs arrive as (z/time, channel, y, x),
            # so default to "outer axis first, spectral axis second".
            spectral_default = 1 if len(shape) > 1 else 0
            slice_default = 0
            self.spectral_combo.setCurrentIndex(spectral_default)
            self.slice_combo.setCurrentIndex(slice_default)

            self.slice_kind_combo = QtWidgets.QComboBox()
            self.slice_kind_combo.addItem("Z slices", "Z")
            self.slice_kind_combo.addItem("Time points", "Time")

            form.addRow("Spectral axis:", self.spectral_combo)
            form.addRow("Outer axis:", self.slice_combo)
            form.addRow("Outer axis meaning:", self.slice_kind_combo)
            layout.addLayout(form)

            buttons = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
            )
            buttons.accepted.connect(self._accept_if_valid)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

        def _accept_if_valid(self):
            if self.spectral_combo.currentData() == self.slice_combo.currentData():
                QtWidgets.QMessageBox.warning(
                    self,
                    "Invalid axis assignment",
                    "The spectral axis and the outer z/time axis must be different.",
                )
                return
            self.accept()

        def selection(self) -> tuple[int, int, str]:
            return (
                int(self.spectral_combo.currentData()),
                int(self.slice_combo.currentData()),
                str(self.slice_kind_combo.currentData()),
            )

    def _interpret_loaded_image(self, image: np.ndarray) -> tuple[np.ndarray, int]:
        if image.ndim == 3:
            self._slice_axis_label = "Slice"
            self._current_slice_index = 0
            return image, image.shape[0]

        if image.ndim != 4:
            raise ValueError(
                f"Only 3D hyperspectral stacks or 4D channel+z/time stacks are supported, got shape {image.shape}."
            )

        dialog = self._AxisRoleDialog(image.shape, parent=self)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            raise RuntimeError("4D stack loading cancelled by user.")

        spectral_axis, slice_axis, slice_kind = dialog.selection()
        remaining_axes = [axis for axis in range(image.ndim) if axis not in {slice_axis, spectral_axis}]
        if len(remaining_axes) != 2:
            raise ValueError(f"Could not determine the two spatial axes for 4D image shape {image.shape}.")

        canonical = np.transpose(image, (slice_axis, spectral_axis, remaining_axes[0], remaining_axes[1]))
        self._slice_axis_label = slice_kind
        self._current_slice_index = 0
        logger.info(
            "Interpreted 4D stack %s as (%s, channel, y, x) using slice axis %s and spectral axis %s.",
            image.shape,
            slice_kind.lower(),
            slice_axis,
            spectral_axis,
        )
        return canonical, canonical.shape[1]

    def _update_slice_selector(self):
        if self._analysis_image is None or self._analysis_image.ndim != 4:
            self.slice_selector_widget.hide()
            return

        n_slices = int(self._analysis_image.shape[0])
        self.slice_axis_title_label.setText(f"{self._slice_axis_label}:")

        self.slice_selector_spinbox.blockSignals(True)
        self.slice_selector_spinbox.setMaximum(max(1, n_slices))
        self.slice_selector_spinbox.setValue(self._current_slice_index + 1)
        self.slice_selector_spinbox.blockSignals(False)

        self.slice_selector_slider.blockSignals(True)
        self.slice_selector_slider.setMaximum(max(0, n_slices - 1))
        self.slice_selector_slider.setValue(self._current_slice_index)
        self.slice_selector_slider.blockSignals(False)
        self.slice_selector_widget.show()

    def _set_current_slice_index(self, index: int):
        if self._analysis_image is None or self._analysis_image.ndim != 4:
            return

        index = int(np.clip(index, 0, self._analysis_image.shape[0] - 1))
        if index == self._current_slice_index and self._display_image is not None:
            return

        self._current_slice_index = index
        self._display_image = self._analysis_image[index]
        self._update_slice_selector()
        self.update_image_callback(self._display_image, preserve_channel=True)

    def _apply_binning_to_canonical_image(self):
        if self._source_image is None:
            self._analysis_image = None
            self._display_image = None
            self._update_slice_selector()
            return

        if self._binning_factor == 1:
            self._analysis_image = self._source_image
        elif self._source_image.ndim == 3:
            self._analysis_image = self.bin_image_3d(self._source_image, self._binning_factor)
        elif self._source_image.ndim == 4:
            self._analysis_image = np.stack(
                [self.bin_image_3d(volume, self._binning_factor) for volume in self._source_image],
                axis=0,
            )
        else:
            raise ValueError(f"Unsupported canonical image dimensionality: {self._source_image.ndim}")

        if self._analysis_image.ndim == 4:
            self._current_slice_index = int(np.clip(self._current_slice_index, 0, self._analysis_image.shape[0] - 1))
            self._display_image = self._analysis_image[self._current_slice_index]
        else:
            self._current_slice_index = 0
            self._display_image = self._analysis_image

        self._update_slice_selector()

    def new_image_loaded(self, image: np.ndarray, preserve_channel: bool = False):
        logger.info('New image loaded')

        # --- normalize (if requested) ---
        if self._normalize:
            logger.info('Normalizing loaded image to %s dynamic range.', max_dtype_val)
            image = np.multiply(image, max_dtype_val / np.amax(image, axis=None))
            image = image.astype(dtype)
            logger.info('Image normalized')

        # Only NaN/Inf are unsafe for downstream math; exact zeros are valid
        # input for NMF/NNLS (constraint is >= 0, not > 0) and are preserved.
        if np.isnan(image).any() or np.isinf(image).any():
            logger.warning('Loaded image contains NaN or Inf values, which may cause issues in further processing.')
            image = np.nan_to_num(image, nan=0.0, posinf=0.0, neginf=0.0)
            logger.warning('NaN and Inf values replaced with 0.0.')

        try:
            self._source_image, n_frames = self._interpret_loaded_image(image)
        except RuntimeError:
            logger.info("4D image loading cancelled by user.")
            return
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Unsupported image shape", str(exc))
            logger.warning("Could not interpret loaded image shape %s: %s", image.shape, exc)
            return

        # --- binning ---
        if self._binning_factor != 1:
            logger.warning('Binning factor is not 1, image will be binned')
        self._apply_binning_to_canonical_image()

        # update physical units with *final* image shape
        self.loader_widget.physical_units_manager.update_image_dimensions(self._display_image.shape[1:])

        # --- wavelength / wavenumber handling ---
        wavelength_meta = self.loader_widget.wavelength_meta

        # only if no wavelength.json comes with the new dataset a warning has to be issued
        if wavelength_meta is None and not self._suspend_custom_axis_warning:
            self.wavenumber_widget.warn_and_switch_from_custom_source(parent=self)

        if wavelength_meta is not None:
            logger.info("Applying wavelength metadata to WavenumberWidget")
            self.wavenumber_widget.apply_wavelength_meta(wavelength_meta, n_frames)
        else:
            # still keep the widget in sync with the frame count
            self.wavenumber_widget.set_nframes(n_frames)

        # push image to the rest of the pipeline
        self.update_image_callback(self._display_image, preserve_channel=preserve_channel)

    def get_dock_widget(self):
        return self.loader_dock

    def get_current_binning(self) -> int:
        return self._binning_factor

    def set_binning(self, bin_factor: int):
        """Set binning factor and re-bin the image."""
        if bin_factor < 1:
            raise ValueError("Binning factor must be >= 1")
        if self._binning_factor != bin_factor:
            self._binning_factor = bin_factor
            self.apply_binning()  # Re-bin image

    def apply_binning(self):
        """Apply binning to the image and update the image view."""
        logger.info('Calculating binned image with factor %i'%self._binning_factor)
        self._apply_binning_to_canonical_image()
        if self._display_image is not None:
            self.loader_widget.physical_units_manager.update_image_dimensions(self._display_image.shape[1:])
            self.update_image_callback(self._display_image)


    def get_image(self):
        """Return the binned image (widgets only see binned data)."""
        return self._display_image

    def get_analysis_image(self):
        """Return the current analysis image: 3D for standard data, 4D for multi-slice data."""
        return self._analysis_image

    def get_current_slice_index(self) -> int:
        return self._current_slice_index

    def set_current_slice_index(self, index: int):
        if self._analysis_image is None or self._analysis_image.ndim != 4:
            self._current_slice_index = 0
            return
        self._set_current_slice_index(index)

    def get_slice_axis_label(self) -> str:
        return self._slice_axis_label

    def has_multi_slice_axis(self) -> bool:
        return self._analysis_image is not None and self._analysis_image.ndim == 4

    @staticmethod
    def bin_image_3d(image: np.ndarray, bin_factor: int, axis_order: dict= {'z': 0, 'y': 1, 'x': 2}):
        """ Bins a 3d image stack by averaging adjacent pixels in non-overlapping bin_factor x bin_factor x bin_factor blocks.
        Args:
            image (np.ndarray): Input image as a 3D NumPy array.
            bin_factor (int): The binning factor (e.g., 2 for 2×2×2 binning, 4 for 4×4×4 binning).
            axis_order (dict): Dictionary mapping axis names to their indices in the image array.
        Returns:
            np.ndarray: Binned image with reduced resolution.
        """
        # possibly reshape the input image to match the axis order
        if axis_order is not {'z': 0, 'y': 1, 'x': 2}:
            image = np.moveaxis(image, [0, 1, 2], [axis_order['z'], axis_order['y'], axis_order['x']])
        # pass each frame to the bin_image function
        logger.debug('Binning 3D image with shape %s and factor %s.', image.shape, bin_factor)
        return np.stack([DataHandler.bin_image(frame, bin_factor) for frame in image])


    @staticmethod
    def bin_image(image, bin_factor):
        """Bins the image by averaging adjacent pixels in non-overlapping bin_factor x bin_factor blocks.

        Args:
            image (np.ndarray): Input image as a 2D NumPy array.
            bin_factor (int): The binning factor (e.g., 2 for 2×2 binning, 4 for 4×4 binning).

        Returns:
            np.ndarray: Binned image with reduced resolution.
        """
        h, w = image.shape
        bh, bw = h // bin_factor, w // bin_factor  # New shape after binning

        # Crop image to nearest multiple of bin_factor (avoid out-of-bounds issues)
        image_cropped = image[:bh * bin_factor, :bw * bin_factor]

        # Reshape into (bh, bin_factor, bw, bin_factor) and compute mean along binning axes
        return image_cropped.reshape(bh, bin_factor, bw, bin_factor).mean(axis=(1, 3))


if __name__ == '__main__':
    import sys
    import matplotlib.pyplot as plt
    import logging

    logging.basicConfig(level=logging.INFO)
    app = QtWidgets.QApplication(sys.argv)
    handler = DataHandler(lambda img: print(img.shape))
    handler.loader_widget.load_tiff(
        '../example_data/2016_05_13_Nematode_K11_60mW_816,7nm_60mW_1064nm_PMT804_HyperwaveVar.mat_COR_Channel1.tif')

    print(handler.loader_widget.image)
    handler.set_binning(2)
    handler.apply_binning()
    print(handler.loader_widget.image.shape)
    # test binning
    slice_of_interest = 30
    plt.subplot(121)
    plt.imshow(handler.get_image()[slice_of_interest, ...])

    # apply binning
    handler.set_binning(2)
    handler.apply_binning()
    plt.subplot(122)
    plt.imshow(handler.get_image()[slice_of_interest, ...])
    plt.show()
    # app.exec_()
    print(handler.get_image().shape)
