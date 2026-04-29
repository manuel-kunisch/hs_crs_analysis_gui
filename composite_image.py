import logging
import os
import ast

import numpy as np
import pyqtgraph as pg
import tifffile
from PyQt5 import QtGui
from PyQt5.Qt import QObject
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QPointF, QRect, QRectF, QSizeF, QMarginsF
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QHBoxLayout, QSpinBox, QComboBox,
    QPushButton, QColorDialog, QSizePolicy, QGridLayout, QSpacerItem, QSplitter, QSlider, QCheckBox, QFileDialog,
    QMessageBox, QDialog, QDialogButtonBox, QFormLayout)
from pyqtgraph import PlotItem

from contents.color_manager import ComponentColorManager
from contents.custom_pyqt_objects import ImageViewYXC, ImageViewLineRoiYXZ
from contents.fiji_saver import FIJISaver
from contents.scalebar import ScaleBar

max_but_size = (100, 50)
dtype = np.uint16
max_dtype_val = np.iinfo(dtype).max

logger = logging.getLogger("Composite Image Viewer")
auto_min_max = False


# TODO: add table to the widget which allows to disable certain components
class CompositeImageViewWidget(QMainWindow):
    colormap_colors = [
        (255, 0, 0),  # Red
        (0, 255, 0),  # Green
        (0, 0, 255),  # Blue
        (255, 255, 255),  # Greys
        (0, 255, 255),  # Cyan
        (255, 0, 255),  # Magenta
        (255, 255, 0),  # Yellow
        (255, 165, 0),  # Orange
        (128, 0, 128),  # Purple
        (255, 192, 203),  # Pink
    ]
    color_changed_signal = pyqtSignal(int, QColor)
    import_result_component_signal = pyqtSignal(str, int, int)
    def __init__(self, img:np.ndarray = None, spectral_cmps: np.ndarray|None = None,
                 color_manager: ComponentColorManager=None):
        super().__init__()
        self.img = img
        self.img_series = None
        self.color_manager = color_manager
        # sync the colormap colors with the color manager if provided
        if self.color_manager is not None:
            self.colormap_colors = self.color_manager.get_all_colors_rgb()
        self.spectral_cmps = spectral_cmps
        self.spectral_cmps_series = None
        self.spectral_cmps_seed = None
        self.wavenumbers = None
        self.axis_labels = None
        self.result_mode = None
        self.outer_axis_label = "Slice"
        self.current_result_slice_index = 0
        self.fit_info = None
        self.fit_info_series = None
        self.display_w_scale_factor = None
        self.display_w_raw_max = None
        self.scale_w_to_uint16_enabled = True
        self.fiji_saver = FIJISaver(self.img, f'{os.path.join(os.getcwd(), "result.tif")}',
                                    colors=self.colormap_colors, dtype=np.uint16)
        self.custom_model = False
        self.export_scalebar_pixel_size_um = None
        self.export_scalebar_length = 50.0
        self.export_scalebar_unit = "\u00b5m"
        self.export_scalebar_visible = False
        self.update_thread = QThread()
        self.timeout_callbacks = False


        # %% GUI setup
        self.setWindowTitle("ImageViewer with Composite Image and Channels")
        self.setGeometry(100, 100, 900, 900)

        self.central_widget = QWidget(self)
        self.central_widget.setObjectName("resultRoot")
        self.setCentralWidget(self.central_widget)
        self.master_v_layout = QVBoxLayout(self.central_widget)
        self.master_v_layout.setContentsMargins(14, 14, 14, 14)
        self.master_v_layout.setSpacing(12)
        self.central_widget.setStyleSheet("""
            QWidget#resultRoot {
                background-color: #303030;
            }
            QWidget#resultPanel {
                background-color: #383838;
                border: 1px solid #4a4a4a;
                border-radius: 8px;
            }
            QWidget#resultSubpanel {
                background-color: #323232;
                border: 1px solid #505050;
                border-radius: 6px;
            }
            QLabel[role="sectionTitle"] {
                color: #f0f0f0;
                font-size: 14px;
                font-weight: 600;
            }
            QLabel[role="sectionMeta"] {
                color: #a8a8a8;
                font-size: 11px;
            }
            QPushButton, QComboBox, QSpinBox, QSlider, QCheckBox {
                font-size: 11px;
            }
        """)

        # Create a PyqtGraph ImageView widget for the composite image
        self.composite_view = ImageViewYXC()
        self.composite_view.view.setDefaultPadding(0)
        self.composite_view.ui.roiBtn.hide()
        self.composite_view.ui.menuBtn.hide()
        self.composite_view.ui.histogram.setHistogramRange(0, max_dtype_val)
        self.composite_view.ui.histogram.axis.hide()
        self.composite_view.ui.histogram.axis.setRange(0, max_dtype_val)
        self.composite_view.ui.histogram.axis.fixedWidth = 10
        self.composite_view.ui.histogram.axis.setMaximumWidth(10)
        self.composite_view.ui.histogram.setMaximumWidth(96)
        # self.composite_view.ui.histogram.hide()

        # Create a PyqtGraph ImageView widget for individual channels
        self.channel_view = ImageViewLineRoiYXZ(view=PlotItem())
        self.channel_view.view.setDefaultPadding(0)
        self.channel_view.ui.histogram.show()
        self.channel_view.ui.histogram.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.channel_view.ui.histogram.setMinimumWidth(132)
        self.channel_view.ui.histogram.setMaximumWidth(140)
        self.channel_view.ui.histogram.gradient.show()
        self.channel_view.ui.histogram.gradient.setMinimumWidth(16)
        self.channel_view.view.setTitle("Channel Preview")
        self.spectrum_view = pg.PlotWidget(title="Component Spectra", size=(100,300))
        self.spectrum_view.setLabel('left', 'Intensity counts')
        self.spectrum_view.setLabel('bottom', 'Wavenumber (1/cm)')
        self.legend = self.spectrum_view.addLegend()
        self.spectrum_lines = []
        self.seed_lines = []

        self.custom_labels: dict = {}



        export_composite_button = QPushButton("Export Composite")
        export_composite_button.clicked.connect(self.save_data)
        
        # add button to save the H seeds with combobox to select the mode
        save_seeds_button = QPushButton("Save Histogram Preset")
        save_seed_mode_combobox = QComboBox()
        save_seed_mode_combobox.addItem("Results")
        save_seed_mode_combobox.addItem("Seeds")
        save_seed_mode_label = QLabel("Mode:")
        save_seeds_button.clicked.connect(lambda: self.save_preset(mode=save_seed_mode_combobox.currentText().lower()))

        promote_seed_button = QPushButton("Import Result")
        promote_seed_button.setToolTip("Import one NNMF result component into the ROI manager as a dummy seed ROI.")
        promote_seed_button.setEnabled(False)
        promote_seed_target_combobox = QComboBox()
        promote_seed_target_combobox.addItem("H", "h")
        promote_seed_target_combobox.addItem("W", "w")
        promote_seed_target_combobox.addItem("H + W", "both")
        promote_seed_target_label = QLabel("Target:")
        promote_seed_component_label = QLabel("Component:")
        promote_seed_component_spinbox = QSpinBox()
        promote_seed_component_spinbox.setMinimum(1)
        promote_seed_component_spinbox.setMaximum(1)
        promote_seed_component_spinbox.setValue(1)
        promote_seed_button.clicked.connect(
            lambda: self.import_result_component_signal.emit(
                promote_seed_target_combobox.currentData(),
                promote_seed_component_spinbox.value() - 1,
                self.current_result_slice_index,
            )
        )
        self.promote_seed_button = promote_seed_button
        self.promote_seed_target_combobox = promote_seed_target_combobox
        self.promote_seed_component_spinbox = promote_seed_component_spinbox

        save_H_as_csv_button = QPushButton("Save H as CSV")
        save_H_as_csv_button.clicked.connect(self.save_components)

        export_spectra_button = QPushButton("Export Spectra")
        export_spectra_button.clicked.connect(self.export_spectrum_plot)

        # Create a QPushButton for resetting the levels
        reset_levels_button = QPushButton("Reset Black Levels")
        reset_levels_button.clicked.connect(self.reset_levels)

        reset_lut_button = QPushButton("Reset LUT γ Curve")
        reset_lut_button.setToolTip("Reset the current channel LUT to a linear black-to-color ramp.")
        reset_lut_button.clicked.connect(self.reset_current_channel_gamma_curve)

        invert_lut_button = QPushButton("Invert LUT")
        invert_lut_button.setToolTip("Invert the current channel LUT without changing its saved channel color.")
        invert_lut_button.clicked.connect(self.invert_current_channel_lut)

        # %% Buttons to modfiy the false color images
        image_channels = int(self.img.shape[-1]) if self.img is not None and self.img.ndim >= 3 else 1

        # Add a QScrollBar for selecting the channel
        self.channel_slider = QSlider()
        self.channel_slider.setTickPosition(QSlider.TicksBothSides)
        self.channel_slider.setTickInterval(1)
        self.channel_slider.setOrientation(1)  # Horizontal orientation
        self.channel_slider.setMinimum(0)
        self.channel_slider.setMaximum(image_channels - 1)
        self.channel_slider.valueChanged.connect(self.callback_channel)

        # Create a QSpinBox for selecting the channel
        self.channel_spinbox = QSpinBox()
        self.channel_spinbox.setRange(0, image_channels - 1)
        self.channel_spinbox.valueChanged.connect(self.callback_channel)
        channel_label = QLabel("Channel: ")

        # Adjusting the QSpinBox size
        self.channel_spinbox.setMinimumWidth(50)  # Set a minimum width
        self.channel_spinbox.setMaximumWidth(80)  # Limit width for compactness
        self.channel_spinbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)  # Prevent resizing

        # Adjusting the QSlider size
        self.channel_slider.setFixedHeight(22)
        self.channel_slider.setMinimumWidth(220)
        self.channel_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # Allow horizontal stretching

        # Create a QPushButton for choosing a colormap color
        self.color_button = QPushButton("Choose Channel Color")
        self.color_button.clicked.connect(lambda: self.choose_color())

        # add autoscale button for channel view
        autoscale_button = QPushButton("AutoScale")
        autoscale_button.clicked.connect(self.channel_view.autoLevels)

        # Create a ColorButton for choosing the colormap color
        self.color_widget = pg.ColorButton()
        self.color_widget.sigColorChanged.connect(self.callback_color_widget)

        self.show_seeds_check = QCheckBox("Show Seeds")
        self.show_seeds_check.setCheckable(True)
        self.show_seeds_check.clicked.connect(lambda state: self.plot_seeds(self.spectral_cmps_seed) if state else self.plot_seeds(np.array([])))
        self.show_seeds_check.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        for widget in [export_composite_button, save_seeds_button, save_H_as_csv_button, export_spectra_button,
                       reset_levels_button, reset_lut_button, invert_lut_button, save_seed_mode_combobox,
                       promote_seed_button, promote_seed_target_combobox, promote_seed_component_spinbox,
                       self.channel_spinbox, self.color_button, autoscale_button]:
            widget.setMinimumHeight(28)

        composite_header = QWidget()
        composite_header_layout = QHBoxLayout(composite_header)
        composite_header_layout.setContentsMargins(0, 0, 0, 0)
        composite_header_layout.setSpacing(10)
        composite_title = QLabel("Composite Overview")
        composite_title.setProperty("role", "sectionTitle")
        composite_meta = QLabel("Inspect the fused result, adjust colors, and export publication figures.")
        composite_meta.setProperty("role", "sectionMeta")
        composite_meta.setWordWrap(True)
        composite_title_layout = QVBoxLayout()
        composite_title_layout.setContentsMargins(0, 0, 0, 0)
        composite_title_layout.setSpacing(2)
        composite_title_layout.addWidget(composite_title)
        composite_title_layout.addWidget(composite_meta)
        composite_header_layout.addLayout(composite_title_layout, stretch=1)
        dock_hint = QLabel("Dock tip: double-click the dock title to undock or move this panel.")
        dock_hint.setProperty("role", "sectionMeta")
        dock_hint.setWordWrap(True)
        dock_hint.setMaximumWidth(260)
        composite_header_layout.addWidget(dock_hint, alignment=Qt.AlignRight | Qt.AlignVCenter)

        composite_controls_widget = QWidget()
        composite_controls_layout = QHBoxLayout(composite_controls_widget)
        composite_controls_layout.setContentsMargins(0, 0, 0, 0)
        composite_controls_layout.setSpacing(8)
        composite_controls_layout.addWidget(export_composite_button)
        composite_controls_layout.addWidget(save_seeds_button)
        composite_controls_layout.addWidget(save_seed_mode_label)
        composite_controls_layout.addWidget(save_seed_mode_combobox)
        composite_controls_layout.addStretch(1)
        composite_controls_layout.addWidget(reset_levels_button)

        import_seed_title = QLabel("Import Into ROI Manager")
        import_seed_title.setProperty("role", "sectionTitle")
        import_seed_meta = QLabel("Create a dummy ROI row from one NNMF result component.")
        import_seed_meta.setProperty("role", "sectionMeta")
        import_seed_meta.setWordWrap(True)

        import_seed_header = QWidget()
        import_seed_header_layout = QVBoxLayout(import_seed_header)
        import_seed_header_layout.setContentsMargins(0, 0, 0, 0)
        import_seed_header_layout.setSpacing(2)
        import_seed_header_layout.addWidget(import_seed_title)
        import_seed_header_layout.addWidget(import_seed_meta)

        import_seed_controls = QWidget()
        import_seed_controls_layout = QHBoxLayout(import_seed_controls)
        import_seed_controls_layout.setContentsMargins(0, 0, 0, 0)
        import_seed_controls_layout.setSpacing(8)
        import_seed_controls_layout.addWidget(promote_seed_component_label)
        import_seed_controls_layout.addWidget(promote_seed_component_spinbox)
        import_seed_controls_layout.addWidget(promote_seed_target_label)
        import_seed_controls_layout.addWidget(promote_seed_target_combobox)
        import_seed_controls_layout.addWidget(promote_seed_button)
        import_seed_controls_layout.addStretch(1)
        self.fit_summary_widget = QWidget()
        self.fit_summary_widget.setObjectName("resultSubpanel")
        self.fit_summary_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        fit_summary_layout = QVBoxLayout(self.fit_summary_widget)
        fit_summary_layout.setContentsMargins(10, 10, 10, 10)
        fit_summary_layout.setSpacing(6)
        self.fit_summary_title = QLabel("Fit Summary")
        self.fit_summary_title.setProperty("role", "sectionTitle")
        self.fit_summary_label = QLabel("")
        self.fit_summary_label.setProperty("role", "sectionMeta")
        self.fit_summary_label.setWordWrap(True)
        self.fit_summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fit_summary_layout.addWidget(self.fit_summary_title)
        fit_summary_layout.addWidget(self.fit_summary_label)
        fit_summary_layout.addStretch(1)
        self.fit_summary_widget.setMinimumWidth(300)
        self.fit_summary_widget.setMaximumWidth(380)
        self.fit_summary_widget.hide()

        import_seed_panel = QWidget()
        import_seed_panel.setObjectName("resultSubpanel")
        import_seed_panel_layout = QVBoxLayout(import_seed_panel)
        import_seed_panel_layout.setContentsMargins(10, 10, 10, 10)
        import_seed_panel_layout.setSpacing(8)
        import_seed_panel_layout.addWidget(import_seed_header)
        import_seed_panel_layout.addWidget(import_seed_controls)

        composite_panel = QWidget()
        composite_panel.setObjectName("resultPanel")
        composite_panel_layout = QVBoxLayout(composite_panel)
        composite_panel_layout.setContentsMargins(12, 12, 12, 12)
        composite_panel_layout.setSpacing(10)
        composite_panel_layout.addWidget(composite_header)
        composite_content_widget = QWidget()
        composite_content_layout = QHBoxLayout(composite_content_widget)
        composite_content_layout.setContentsMargins(0, 0, 0, 0)
        composite_content_layout.setSpacing(10)
        composite_content_layout.addWidget(self.composite_view, stretch=1)
        composite_content_layout.addWidget(self.fit_summary_widget)
        composite_panel_layout.addWidget(composite_content_widget, stretch=1)
        composite_panel_layout.addWidget(composite_controls_widget)
        composite_panel_layout.addWidget(import_seed_panel)

        channel_controls_widget = QWidget()
        channel_controls_layout = QGridLayout(channel_controls_widget)
        channel_controls_layout.setContentsMargins(0, 0, 0, 0)
        channel_controls_layout.setHorizontalSpacing(8)
        channel_controls_layout.setVerticalSpacing(6)
        self.result_slice_label = QLabel("Slice:")
        self.result_slice_spinbox = QSpinBox()
        self.result_slice_spinbox.setMinimum(1)
        self.result_slice_spinbox.setMaximum(1)
        self.result_slice_spinbox.setValue(1)
        self.result_slice_slider = QSlider(Qt.Horizontal)
        self.result_slice_slider.setMinimum(0)
        self.result_slice_slider.setMaximum(0)
        self.result_slice_slider.setTickInterval(1)
        self.result_slice_slider.setTickPosition(QSlider.TicksBothSides)
        self.result_slice_widget = QWidget()
        result_slice_layout = QHBoxLayout(self.result_slice_widget)
        result_slice_layout.setContentsMargins(0, 0, 0, 0)
        result_slice_layout.setSpacing(8)
        result_slice_layout.addWidget(self.result_slice_label)
        result_slice_layout.addWidget(self.result_slice_spinbox)
        result_slice_layout.addWidget(self.result_slice_slider, stretch=1)
        self.result_slice_widget.hide()
        self.result_slice_spinbox.valueChanged.connect(lambda value: self.update_result_slice(int(value) - 1))
        self.result_slice_slider.valueChanged.connect(self.update_result_slice)
        channel_controls_layout.addWidget(channel_label, 0, 0)
        channel_controls_layout.addWidget(self.channel_spinbox, 0, 1)
        channel_controls_layout.addWidget(self.color_button, 0, 2)
        channel_controls_layout.addWidget(self.color_widget, 0, 3)
        channel_controls_layout.addWidget(autoscale_button, 0, 4)
        channel_controls_layout.addWidget(reset_lut_button, 1, 2)
        channel_controls_layout.addWidget(invert_lut_button, 1, 3)
        channel_controls_layout.addWidget(self.channel_slider, 2, 0, 1, 5)
        channel_controls_layout.addWidget(self.result_slice_widget, 3, 0, 1, 5)
        channel_controls_layout.setColumnStretch(4, 1)

        channel_header = QWidget()
        channel_header_layout = QHBoxLayout(channel_header)
        channel_header_layout.setContentsMargins(0, 0, 0, 0)
        channel_header_layout.setSpacing(8)
        channel_title = QLabel("Channel Preview")
        channel_title.setProperty("role", "sectionTitle")
        channel_meta = QLabel("Browse individual component maps and refine the false color.")
        channel_meta.setProperty("role", "sectionMeta")
        channel_header_layout.addWidget(channel_title)
        channel_header_layout.addWidget(channel_meta, stretch=1)

        channel_panel = QWidget()
        channel_panel.setObjectName("resultPanel")
        channel_panel_layout = QVBoxLayout(channel_panel)
        channel_panel_layout.setContentsMargins(12, 12, 12, 12)
        channel_panel_layout.setSpacing(10)
        channel_panel_layout.addWidget(channel_header)
        channel_panel_layout.addWidget(self.channel_view, stretch=1)
        channel_panel_layout.addWidget(channel_controls_widget)

        spectrum_header = QWidget()
        spectrum_header_layout = QHBoxLayout(spectrum_header)
        spectrum_header_layout.setContentsMargins(0, 0, 0, 0)
        spectrum_header_layout.setSpacing(8)
        spectrum_title = QLabel("Spectral Components")
        spectrum_title.setProperty("role", "sectionTitle")
        spectrum_meta = QLabel("Compare extracted component spectra and optional seed spectra.")
        spectrum_meta.setProperty("role", "sectionMeta")
        spectrum_header_layout.addWidget(spectrum_title)
        spectrum_header_layout.addWidget(spectrum_meta, stretch=1)
        spectrum_header_layout.addWidget(save_H_as_csv_button)
        spectrum_header_layout.addWidget(export_spectra_button)
        spectrum_header_layout.addWidget(self.show_seeds_check, alignment=Qt.AlignRight)

        spectrum_panel = QWidget()
        spectrum_panel.setObjectName("resultPanel")
        spectrum_panel_layout = QVBoxLayout(spectrum_panel)
        spectrum_panel_layout.setContentsMargins(12, 12, 12, 12)
        spectrum_panel_layout.setSpacing(10)
        spectrum_panel_layout.addWidget(spectrum_header)
        spectrum_panel_layout.addWidget(self.spectrum_view, stretch=1)

        self.components_h_splitter = QSplitter(Qt.Horizontal)
        self.components_h_splitter.setChildrenCollapsible(False)
        self.components_h_splitter.setHandleWidth(8)
        self.components_h_splitter.addWidget(composite_panel)
        self.components_h_splitter.addWidget(channel_panel)
        self.components_h_splitter.setStretchFactor(0, 1)
        self.components_h_splitter.setStretchFactor(1, 1)

        self.main_plot_v_splitter = QSplitter(Qt.Vertical)
        self.main_plot_v_splitter.setChildrenCollapsible(False)
        self.main_plot_v_splitter.setHandleWidth(8)
        self.main_plot_v_splitter.addWidget(self.components_h_splitter)
        self.main_plot_v_splitter.addWidget(spectrum_panel)
        self.main_plot_v_splitter.setStretchFactor(0, 3)
        self.main_plot_v_splitter.setStretchFactor(1, 2)
        self.master_v_layout.addWidget(self.main_plot_v_splitter)
        self.main_plot_v_splitter.setSizes([520, 320])
        self.components_h_splitter.setSizes([520, 520])

        # Initialize colormap, levels, and max value state dictionaries
        self.histogram_states = {}

        if self.img is not None:
            self.update_image(self.img)


        # Connect the slot function to histogram level sliders' valueChanged signals
        self.channel_view.getHistogramWidget().item.sigLevelsChanged.connect(self.update_channel_and_composite_levels)
        # Monitor manual LUT changes
        self.channel_view.getHistogramWidget().item.sigLookupTableChanged.connect(self.update_channel_and_composite_levels)
        # hide the gradient ticks
        self.channel_view.getHistogramWidget().gradient.showTicks(True)
        # self.lock_bottom_tick()

    def update_wavenumbers(self, wavenumbers):
        self.wavenumbers = wavenumbers
        self.fiji_saver.wavenumbers = wavenumbers
        self._update_spectrum_axis()
        self.plot_components(self.spectral_cmps_series if self.spectral_cmps_series is not None else self.spectral_cmps)

        # TODO: update plot

    def set_axis_labels(self, labels):
        self.axis_labels = None if labels is None else [str(label) for label in labels]
        self._update_spectrum_axis()
        self.plot_components(self.spectral_cmps_series if self.spectral_cmps_series is not None else self.spectral_cmps)

    def _current_spectral_components(self):
        if self.spectral_cmps_series is not None:
            if self.spectral_cmps_series.ndim == 3:
                return self.spectral_cmps_series[self.current_result_slice_index]
            return None
        return self.spectral_cmps

    def _sync_result_slice_controls(self):
        if self.img_series is None:
            self.result_slice_widget.hide()
            return

        n_slices = int(self.img_series.shape[0])
        self.result_slice_label.setText(f"{self.outer_axis_label}:")

        self.result_slice_spinbox.blockSignals(True)
        self.result_slice_spinbox.setMaximum(max(1, n_slices))
        self.result_slice_spinbox.setValue(self.current_result_slice_index + 1)
        self.result_slice_spinbox.blockSignals(False)

        self.result_slice_slider.blockSignals(True)
        self.result_slice_slider.setMaximum(max(0, n_slices - 1))
        self.result_slice_slider.setValue(self.current_result_slice_index)
        self.result_slice_slider.blockSignals(False)
        self.result_slice_widget.show()

    def _spectral_x_values(self, length: int) -> np.ndarray:
        if self.axis_labels is not None:
            return np.arange(length, dtype=np.float32)
        if self.wavenumbers is not None:
            return self.wavenumbers
        return np.arange(length, dtype=np.float32)

    def _update_spectrum_axis(self):
        axis = self.spectrum_view.getPlotItem().getAxis('bottom')
        if self.axis_labels is None:
            axis.setTicks(None)
            return

        axis.setLabel('Channels')
        step = max(1, len(self.axis_labels) // 8)
        tick_values = [(i, label) for i, label in enumerate(self.axis_labels) if i % step == 0]
        if tick_values:
            axis.setTicks([tick_values])

    def update_label(self, component_number: int, new_label: str):
        # Reverting to the default label should clear the custom label cache.
        default_label = f'Component {component_number}'
        if not new_label or new_label == default_label:
            self.custom_labels.pop(component_number, None)
        else:
            self.custom_labels[component_number] = new_label
        self.refresh_label_overlay(component_number)  # Optional: Re-render or update something
        self.fiji_saver.labels = self.custom_labels

    def set_result_mode(self, mode: str | None):
        self.result_mode = mode
        is_nnmf = mode == "NNMF"
        if hasattr(self, "promote_seed_button"):
            self.promote_seed_button.setEnabled(is_nnmf)
            self.promote_seed_component_spinbox.setEnabled(is_nnmf)
            self.promote_seed_target_combobox.setEnabled(is_nnmf)
            if is_nnmf:
                self.promote_seed_button.setToolTip(
                    "Import one NNMF result component into the ROI manager as a dummy seed ROI."
                )
            else:
                self.promote_seed_button.setToolTip("Result import is only available for NNMF results.")
        self._update_fit_info_label()

    @staticmethod
    def _format_fit_scalar(value) -> str | None:
        if value is None:
            return None
        try:
            scalar = float(value)
        except (TypeError, ValueError):
            return str(value)
        if not np.isfinite(scalar):
            return None
        if scalar == 0:
            return "0"
        magnitude = abs(scalar)
        if magnitude >= 1e4 or magnitude < 1e-3:
            return f"{scalar:.3e}"
        if magnitude >= 100:
            return f"{scalar:.1f}"
        if magnitude >= 10:
            return f"{scalar:.2f}"
        return f"{scalar:.4f}"

    @classmethod
    def _format_relative_error(cls, value) -> str | None:
        formatted = cls._format_fit_scalar(value)
        if formatted is None:
            return None
        try:
            scalar = float(value)
        except (TypeError, ValueError):
            return formatted
        if not np.isfinite(scalar):
            return None
        return f"{formatted} ({scalar * 100:.2f}%)"

    def _current_fit_info(self) -> dict | None:
        if self.fit_info_series is not None:
            if 0 <= self.current_result_slice_index < len(self.fit_info_series):
                info = self.fit_info_series[self.current_result_slice_index]
                return info if isinstance(info, dict) else None
            return None
        return self.fit_info if isinstance(self.fit_info, dict) else None

    def _fit_series_relative_stats(self) -> tuple[float, float, float] | None:
        if not isinstance(self.fit_info_series, list):
            return None
        rel_values = []
        for info in self.fit_info_series:
            if not isinstance(info, dict):
                continue
            rel = info.get("relative_error")
            try:
                rel = float(rel)
            except (TypeError, ValueError):
                continue
            if np.isfinite(rel):
                rel_values.append(rel)
        if not rel_values:
            return None
        rel_array = np.asarray(rel_values, dtype=np.float64)
        return float(np.mean(rel_array)), float(np.min(rel_array)), float(np.max(rel_array))

    def _fit_model_label(self, info: dict) -> str:
        mode = info.get("mode")
        if mode == "seeded_nnmf":
            return "Seeded NNMF"
        if mode == "random_nnmf":
            return "Random NNMF"
        algorithm = str(info.get("algorithm", "")).lower()
        if algorithm == "fixed_h_nnls":
            return "Fixed-H NNLS"
        if "nnls" in algorithm:
            return "NNLS"
        if self.result_mode == "NNMF":
            return "NNMF"
        if self.result_mode:
            return str(self.result_mode)
        return "Fit"

    def _update_fit_info_label(self):
        if not hasattr(self, "fit_summary_label") or not hasattr(self, "fit_summary_widget"):
            return
        info = self._current_fit_info()
        if self.result_mode == "PCA":
            self.fit_summary_label.clear()
            self.fit_summary_widget.hide()
            return

        lines = []
        if info is not None:
            lines = [f"Fit: {self._fit_model_label(info)}"]
            if self.fit_info_series is not None and len(self.fit_info_series) > 1:
                lines.append(f"{self.outer_axis_label}: {self.current_result_slice_index + 1}/{len(self.fit_info_series)}")

            backend = info.get("backend")
            solver = info.get("solver")
            if backend:
                backend_line = f"Backend: {backend}"
                if solver and "NNMF" in lines[0]:
                    backend_line += f" | Solver: {solver}"
                lines.append(backend_line)

            n_iter = info.get("n_iter")
            max_iter = info.get("max_iter")
            if n_iter is not None and max_iter is not None:
                lines.append(f"Iterations until convergence: {n_iter}/{max_iter}")
            elif n_iter is not None:
                lines.append(f"Iterations until convergence: {n_iter}")
            else:
                max_chunk_iter = info.get("max_chunk_iter")
                mean_chunk_iter = info.get("mean_chunk_iter")
                if max_chunk_iter is not None:
                    chunk_line = f"Iterations until convergence: max chunk {max_chunk_iter}"
                    if mean_chunk_iter is not None:
                        chunk_line += f", mean chunk {self._format_fit_scalar(mean_chunk_iter)}"
                    lines.append(chunk_line)
                elif mean_chunk_iter is not None:
                    lines.append(f"Iterations until convergence: mean chunk {self._format_fit_scalar(mean_chunk_iter)}")

            final_error = self._format_fit_scalar(info.get("final_error"))
            if final_error is not None:
                lines.append(f"Absolute error: {final_error}")

            relative_error = self._format_relative_error(info.get("relative_error"))
            if relative_error is not None:
                lines.append(f"Relative error: {relative_error}")

            series_stats = self._fit_series_relative_stats()
            if series_stats is not None and self.fit_info_series is not None and len(self.fit_info_series) > 1:
                mean_rel, min_rel, max_rel = series_stats
                lines.append(
                    "Series relative error: "
                    f"mean {self._format_fit_scalar(mean_rel)}, "
                    f"range {self._format_fit_scalar(min_rel)} to {self._format_fit_scalar(max_rel)}"
                )

        if self.display_w_scale_factor is not None:
            if lines:
                lines.append("")
            scale_text = self._format_fit_scalar(self.display_w_scale_factor)
            raw_max_text = self._format_fit_scalar(self.display_w_raw_max)
            lines.append(f"W display scale a: {scale_text}")
            lines.append(f"Raw W max: {raw_max_text}")
            lines.append("Displayed W' = a W; reconstruct with H/a.")

        if not lines:
            self.fit_summary_label.clear()
            self.fit_summary_widget.hide()
            return

        self.fit_summary_label.setText("\n".join(lines))
        self.fit_summary_widget.show()

    def plot_components(self, spectral_components: np.ndarray):
        """

        Args:
            spectral_components:
                PCs or Matrix H from PCA or NNMF analysis

        Returns:

        """
        self.spectrum_view.clear()
        self.spectrum_lines = []
        self.seed_lines = []
        # Plot each component of H resp. the PCs
        if spectral_components is not None and spectral_components.ndim == 3:
            spectral_components = spectral_components[self.current_result_slice_index]

        self.spectral_cmps = spectral_components
        try:
            num_components = spectral_components.shape[0]
        except AttributeError as e:
            logger.warning(e)
            return
        x_values = self._spectral_x_values(spectral_components.shape[1])
        # self.spectrum_view.setTitle(rf"{'Custom' if self.custom_model else 'Random'} NNMF H Components")
        for i in range(num_components):
            component = spectral_components[i, :]
            name = self.custom_labels.get(i, f'Component {i}') if self.custom_model else f'Component {i}'
            line = self.spectrum_view.plot(x_values, component, pen=pg.mkPen(self.get_color(i)), name=name)
            self.spectrum_lines.append(line)
        if self.custom_model:
            if self.show_seeds_check.isChecked():
                self.plot_seeds(self.spectral_cmps_seed, dashed=True)


    def refresh_label_overlay(self, component_index: int):
        """
        Update the label of a PlotDataItem in the spectrum view without replotting it.
        """
        if not self.spectrum_lines or not (0 <= component_index < len(self.spectrum_lines)):
            return
        line = self.spectrum_lines[component_index]

        # Remove the old legend entry
        self.legend.removeItem(line)
        new_label = self.custom_labels.get(component_index, f'Component {component_index}')
        self.legend.addItem(line, new_label)

        if self.channel_slider.value() == component_index:
            # Update the title of the channel view
            slice_suffix = ""
            if self.img_series is not None:
                slice_suffix = f" | {self.outer_axis_label} {self.current_result_slice_index + 1}"
            self.channel_view.view.setTitle(f"Channel {component_index} {new_label}{slice_suffix}")


    def plot_seeds(self, seeds: np.ndarray, dashed: bool = True):
        # TODO: plot seeds in the spectrum view
        # add button to switch between seeds and components
        if self.seed_lines:
            # remove seed from the spectrum view
            for line in self.seed_lines:
                self.spectrum_view.removeItem(line)
            self.seed_lines = []

        if seeds is None:
            return
        x_values = self._spectral_x_values(seeds.shape[1])
        for i in range(seeds.shape[0]):
            seed = seeds[i, :]
            line = self.spectrum_view.plot(x_values, seed, pen=pg.mkPen(self.get_color(i), style=Qt.DashLine if dashed else Qt.SolidLine),
                                           name=f'Seed {i}')
            self.seed_lines.append(line)
        # raise NotImplementedError("Plotting seeds is not yet implemented,\nPlease do not pass seeds to the result viewer")

    def _scale_w_result_for_display(self, img_file: np.ndarray) -> np.ndarray:
        """
        Scales the received abundance map from image file to uint16
        """
        self.display_w_scale_factor = None
        self.display_w_raw_max = None
        if self.result_mode != "NNMF" or img_file is None:
            return img_file

        working_img = np.asarray(img_file, dtype=np.float32)
        if working_img.size == 0:
            return working_img.astype(dtype)

        working_img = np.nan_to_num(working_img, nan=0.0, posinf=0.0, neginf=0.0)
        working_img = np.maximum(working_img, 0.0)
        raw_max = float(np.max(working_img))
        self.display_w_raw_max = raw_max

        if not self.scale_w_to_uint16_enabled:
            logger.info("Displaying W result without uint16 scaling.")
            return working_img

        scale_factor = 1.0 if raw_max <= 0.0 else float(max_dtype_val) / raw_max

        self.display_w_scale_factor = scale_factor
        logger.info("Scaled displayed W result by factor %.6g to uint16.", scale_factor)
        return np.clip(working_img * scale_factor, 0.0, float(max_dtype_val)).astype(dtype)

    def set_scale_w_to_uint16(self, enabled: bool):
        self.scale_w_to_uint16_enabled = bool(enabled)

    def _channel_histogram_upper_bound(self) -> float:
        if (
                self.result_mode == "NNMF"
                and not self.scale_w_to_uint16_enabled
                and self.display_w_raw_max is not None
                and np.isfinite(self.display_w_raw_max)
                and self.display_w_raw_max > 0
        ):
            return float(self.display_w_raw_max)
        return float(max_dtype_val)

    def update_image(self, img_file: np.ndarray, spectral_axis: int | None = None,
                     spectral_cmps:np.ndarray|None = None,
                     spectral_cmps_seed: np.ndarray|None = None,
                     custom_model: bool = False,
                     update_gamma_curve=False,
                     fit_info: dict | list[dict | None] | None = None,
                     outer_axis_label: str = "Slice"):
        """
        Update the data with new multivariate results of shape (y, x, z)
        Args:
            img_file: np.ndarray
                Img file with order (y, x, z).
                Position of z (spectral info) can be modified using the spectral_axis kwarg.
                Important: Spectral slices must be along the final axis -1 if not specified
            spectral_axis:
            spectral_cmps:
            spectral_cmps_seed:
        Returns:
            None
        """
        self.timeout_callbacks = True
        self.img = self._scale_w_result_for_display(img_file)
        if spectral_axis is not None:
            if spectral_axis != -1:
                self.img = np.moveaxis(self.img, spectral_axis, -1)
        self.outer_axis_label = str(outer_axis_label or "Slice")
        if self.img.ndim == 4:
            self.img_series = self.img
            self.current_result_slice_index = int(np.clip(self.current_result_slice_index, 0, self.img_series.shape[0] - 1))
            self.img = self.img_series[self.current_result_slice_index]
        else:
            self.img_series = None
            self.current_result_slice_index = 0
        self._sync_result_slice_controls()
        self.composite_view.setImage(self.img)
        # adjust slider and scrollbar to max....
        channels = self.img.shape[-1] - 1
        self.channel_slider.setMaximum(channels)
        self.channel_spinbox.setMaximum(channels)

        if update_gamma_curve:
            logger.warning(
                "Ignoring legacy update_gamma_curve request to preserve manually stored gradient positions."
            )
        if channels:
            # Initialize the channel view with all channels and switch to selected afterwards
            for i in range(1, self.img.shape[-1]):
                # triggers channel update!
                self.update_channel_view(i)
            self.update_channel_view(0)
            self.reset_levels()
        else:
            # self.update_channel_view(0)
            self.channel_slider.setValue(0)

        self.spectral_cmps_series = spectral_cmps if spectral_cmps is not None and spectral_cmps.ndim == 3 else None
        self.spectral_cmps = None if self.spectral_cmps_series is not None else spectral_cmps
        self.spectral_cmps_seed = spectral_cmps_seed
        self.custom_model = custom_model
        self.fit_info_series = fit_info if isinstance(fit_info, list) else None
        self.fit_info = None if self.fit_info_series is not None else fit_info
        self._update_fit_info_label()
        result_components = 1
        if spectral_cmps is not None:
            result_components = max(1, int(spectral_cmps.shape[1] if spectral_cmps.ndim == 3 else spectral_cmps.shape[0]))
        self.promote_seed_component_spinbox.setMaximum(result_components)
        self.promote_seed_component_spinbox.setValue(min(self.promote_seed_component_spinbox.value(), result_components))
        if spectral_cmps is not None:
            self.plot_components(spectral_cmps)
        self.timeout_callbacks = False
        # A genuinely new result image should recentre both views, while ordinary
        # channel changes and LUT edits keep the user's current zoom.
        self.composite_view.getView().autoRange(padding=0.02)
        self.channel_view.getView().autoRange(padding=0.02)
        # print('Updated Channel View')

    def update_result_slice(self, slice_index: int):
        if self.img_series is None:
            return
        slice_index = int(np.clip(slice_index, 0, self.img_series.shape[0] - 1))
        if slice_index == self.current_result_slice_index and self.img is not None:
            return

        composite_levels = self._current_composite_levels()
        self.current_result_slice_index = slice_index
        self._sync_result_slice_controls()
        self.img = self.img_series[self.current_result_slice_index]
        composite_view_range = self._capture_viewbox_range(self.composite_view)
        self.composite_view.setImage(self.img, autoLevels=False)
        self._update_fit_info_label()
        self._restore_viewbox_range(self.composite_view, composite_view_range)
        self.update_channel_view(min(self.channel_slider.value(), self.img.shape[-1] - 1))
        self.plot_components(self.spectral_cmps_series if self.spectral_cmps_series is not None else self.spectral_cmps)
        self.update_channel_and_composite_levels(composite_levels=composite_levels)



        """ Threading function """
        # def update_image(self, img_file: np.ndarray, spectral_axis: int | None = None,
        #              spectral_cmps :np.ndarray = None):
        # """
        # Args:
        #     img_file: np.ndarray
        #         Img file with order (y, x, z).
        #         Position of z (spectral info) can be modified using the spectral_axis kwarg.
        #         Important: Spectral slices must be along the final axis -1 if not specified
        # Returns:
        #     None
        # """
        # self.worker = UpdateImageWorker(self, img_file, spectral_axis, spectral_cmps)
        # self.worker.moveToThread(self.update_thread)
        # # Connect pyqt signals
        # self.update_thread.started.connect(self.worker.run)
        # self.worker.finished.connect(self.update_thread.quit)
        # # Connect the finished function to the self.worker
        # self.worker.finished.connect(self.worker.deleteLater)
        #
        # # optional: delete thread after completion with self.thread_analysis.finished.connect(self.thread.deleteLater)
        #
        # logger.info(f'{datetime.now()}: Analysis thread set up')
        # self.update_thread.start()
        # # self.analyze_button.setEnabled(False)
        # logger.info(f'{datetime.now()}: Analysis started')

    def get_color(self, channel: int) -> tuple[int, int, int]:
        if self.color_manager is not None:
            return self.color_manager.get_color_rgb(channel)
        if channel in self.histogram_states:
            histogram_state = self.histogram_states[channel]
            colormap_color = self._extract_channel_color_from_ticks(self._sorted_gradient_ticks(histogram_state))
        else:
            colormap_color = self.colormap_colors[channel % len(self.colormap_colors)]
        return colormap_color

    @staticmethod
    def _normalize_rgba(color, default=(0, 0, 0, 255)) -> tuple[int, int, int, int]:
        try:
            values = tuple(int(v) for v in color)
        except Exception:
            return default
        if len(values) >= 4:
            return values[:4]
        if len(values) == 3:
            return values + (255,)
        return default

    @staticmethod
    def _is_black_rgb(color) -> bool:
        return tuple(color[:3]) == (0, 0, 0)

    @classmethod
    def _sorted_gradient_ticks(cls, histogram_state: dict) -> list[tuple[float, tuple[int, int, int, int]]]:
        gradient = histogram_state.get('gradient', {}) if isinstance(histogram_state, dict) else {}
        raw_ticks = list(gradient.get('ticks', [])) if isinstance(gradient, dict) else []
        normalized_ticks = []
        for raw_tick in sorted(raw_ticks, key=lambda tick: float(tick[0])):
            try:
                pos = float(raw_tick[0])
            except Exception:
                continue
            pos = float(np.clip(pos, 0.0, 1.0))
            rgba = cls._normalize_rgba(raw_tick[1])
            if normalized_ticks and np.isclose(pos, normalized_ticks[-1][0]):
                normalized_ticks[-1] = (pos, rgba)
            else:
                normalized_ticks.append((pos, rgba))
        if not normalized_ticks:
            return [(0.0, (0, 0, 0, 255)), (1.0, (255, 255, 255, 255))]
        if len(normalized_ticks) == 1:
            single_color = normalized_ticks[0][1]
            return [(0.0, single_color), (1.0, single_color)]
        return normalized_ticks

    @classmethod
    def _channel_color_tick_index(cls, ticks: list[tuple[float, tuple[int, int, int, int]]]) -> int:
        if not ticks:
            return 0
        if len(ticks) == 1:
            return 0
        bottom_is_black = cls._is_black_rgb(ticks[0][1])
        top_is_black = cls._is_black_rgb(ticks[-1][1])
        if bottom_is_black != top_is_black:
            return 0 if not bottom_is_black else len(ticks) - 1
        return len(ticks) - 1

    @classmethod
    def _extract_channel_color_from_ticks(
            cls,
            ticks: list[tuple[float, tuple[int, int, int, int]]],
            fallback: tuple[int, int, int] = (255, 255, 255),
    ) -> tuple[int, int, int]:
        if not ticks:
            return fallback
        color_tick = ticks[cls._channel_color_tick_index(ticks)][1]
        return tuple(color_tick[:3])

    def _ensure_channel_histogram_state(self, channel_index: int) -> dict | None:
        histogram_state = self.histogram_states.get(channel_index)
        if histogram_state is not None:
            return histogram_state
        if self.img is None:
            return None
        try:
            levels = self.channel_view.getHistogramWidget().item.getLevels()
        except Exception:
            levels = None
        if levels is None:
            levels = (0.0, self._channel_histogram_upper_bound())
        self.make_color_state(
            channel_index,
            (float(levels[0]), float(levels[1])),
            self.colormap_colors[channel_index % len(self.colormap_colors)],
            colorpos='default',
        )
        return self.histogram_states.get(channel_index)

    def _apply_histogram_ticks_to_channel(
            self,
            channel_index: int,
            ticks: list[tuple[float, tuple[int, int, int, int]]],
    ):
        histogram_state = self._ensure_channel_histogram_state(channel_index)
        if histogram_state is None:
            return
        histogram_state['gradient'] = {
            'mode': 'rgb',
            'ticks': [(float(pos), self._normalize_rgba(color)) for pos, color in ticks],
            'ticksVisible': True,
        }
        if channel_index == self.channel_slider.value():
            self._restore_channel_histogram_widget_state(histogram_state)
        self._refresh_composite_from_histogram_states()
        self._sync_color_button_to_gradient()

    def reset_current_channel_gamma_curve(self):
        if self.img is None:
            return
        channel_index = self.channel_slider.value()
        histogram_state = self._ensure_channel_histogram_state(channel_index)
        if histogram_state is None:
            return
        ticks = self._sorted_gradient_ticks(histogram_state)
        bottom_alpha = ticks[0][1][3]
        top_alpha = ticks[-1][1][3]
        channel_color = tuple(self.colormap_colors[channel_index % len(self.colormap_colors)])
        self._apply_histogram_ticks_to_channel(
            channel_index,
            [
                (0.0, (0, 0, 0, bottom_alpha)),
                (1.0, channel_color + (top_alpha,)),
            ],
        )
        logger.info('Reset LUT curve for channel %s.', channel_index)

    def invert_current_channel_lut(self):
        if self.img is None:
            return
        channel_index = self.channel_slider.value()
        histogram_state = self._ensure_channel_histogram_state(channel_index)
        if histogram_state is None:
            return
        ticks = self._sorted_gradient_ticks(histogram_state)
        inverted_ticks = sorted(
            [(float(np.clip(1.0 - pos, 0.0, 1.0)), color) for pos, color in ticks],
            key=lambda tick: tick[0],
        )
        self._apply_histogram_ticks_to_channel(channel_index, inverted_ticks)
        logger.info('Inverted LUT for channel %s.', channel_index)

    def _restore_channel_histogram_widget_state(self, histogram_state: dict):
        histogram_widget = self.channel_view.getHistogramWidget()
        histogram_widget.restoreState(histogram_state)
        # Tick visibility is stored inside the pyqtgraph gradient state.
        # Force it back on after every restore so the handles remain visible
        # and draggable even if an older hidden state was saved.
        histogram_widget.show()
        histogram_widget.gradient.show()
        histogram_widget.gradient.setMinimumWidth(16)
        histogram_widget.gradient.showTicks(True)
        self.channel_view.ui.histogram.setHistogramRange(0, self._channel_histogram_upper_bound())

    @staticmethod
    def _capture_viewbox_range(image_view) -> tuple[list[float], list[float]] | None:
        try:
            view = image_view.getView()
            return view.viewRange()
        except Exception:
            return None

    @staticmethod
    def _restore_viewbox_range(image_view, view_range):
        if view_range is None:
            return
        try:
            view = image_view.getView()
            view.setXRange(view_range[0][0], view_range[0][1], padding=0)
            view.setYRange(view_range[1][0], view_range[1][1], padding=0)
        except Exception:
            logger.debug('Could not restore image view range.', exc_info=True)

    def update_channel_view(self, channel_index):
        if self.img is None:
            return 
        channel_view_range = self._capture_viewbox_range(self.channel_view)
        self.channel_slider.blockSignals(True)
        self.channel_slider.setValue(channel_index)
        self.channel_slider.blockSignals(False)
        logger.debug('Update Time %i' % channel_index)
        # Get the selected channel
        selected_im = self.img[:, :, channel_index]

        # Update the channel view
        self.channel_view.setImage(selected_im, autoLevels=False)
        self._restore_viewbox_range(self.channel_view, channel_view_range)

        # Apply saved levels and histogram state if available
        if channel_index in self.histogram_states:
            histogram_state = self.histogram_states[channel_index]
            self._restore_channel_histogram_widget_state(histogram_state)
            colormap_color = self._extract_channel_color_from_ticks(
                self._sorted_gradient_ticks(histogram_state),
                fallback=self.colormap_colors[channel_index % len(self.colormap_colors)],
            )
            logger.debug("Channel known")
        else:
            # If levels or histogram state is not available,
            # set default levels and histogram state
            # Choose a predefined colormap color for the first view of each channel from the
            # config file
            colormap_color = self.color_manager.get_color_rgb(channel_index) if self.color_manager is not None\
                else self.colormap_colors[channel_index % len(self.colormap_colors)]
            self.channel_view.autoLevels()
            # self.channel_view.setLevels(0, max_dtype_val)
            # self.channel_view.setLevels(np.amin(selected_im), np.amax(selected_im))
            channel_histogram_max = self._channel_histogram_upper_bound()
            self.channel_view.ui.histogram.setHistogramRange(0, channel_histogram_max)
            self.make_color_state(channel_index, (0, channel_histogram_max), colormap_color, colorpos='default')
            # self.update_levels()
            logger.debug("Channel unknown")
        # Update the QSpinBox with the current channel index
        self.channel_spinbox.blockSignals(True)
        self.channel_spinbox.setValue(channel_index)
        self.channel_spinbox.blockSignals(False)
        # sync the channel spinbox and the promote seed spinbox for convenience
        if hasattr(self, "promote_seed_component_spinbox"):
            self.promote_seed_component_spinbox.blockSignals(True)
            self.promote_seed_component_spinbox.setValue(min(channel_index + 1, self.promote_seed_component_spinbox.maximum()))
            self.promote_seed_component_spinbox.blockSignals(False)
        logger.debug(f'{channel_index =}, {colormap_color =}')
        # Set the color of the ColorButton to match the current colormap color
        self.color_widget.blockSignals(True)
        self.color_widget.setColor(pg.mkColor(colormap_color))
        self.color_widget.blockSignals(False)
        # Update the label to show current channel index
        custom_label = self.custom_labels.get(channel_index)
        suffix = f" {custom_label}" if custom_label else ""
        slice_suffix = ""
        if self.img_series is not None:
            slice_suffix = f" | {self.outer_axis_label} {self.current_result_slice_index + 1}"
        self.channel_view.view.setTitle(f"Channel {channel_index}{suffix}{slice_suffix}")

    def callback_color_widget(self):
        # Get the selected color from the ColorButton
        selected_color = self.color_widget.color()
        self.color_widget.blockSignals(True)
        self.choose_color(selected_color)
        self.color_widget.blockSignals(False)

    def sync_colormap_current_channel_to_widget(self):
        # Get the selected color from the ColorButton
        selected_color = self.color_widget.color()

        # Convert QColor to pg.Color and set it as colormap color
        colormap_color = (selected_color.red(), selected_color.green(), selected_color.blue())
        channel_index = self.channel_slider.value()
        histogram_state = self.histogram_states.get(channel_index)
        if histogram_state is None:
            return

        ticks = self._sorted_gradient_ticks(histogram_state)
        color_tick_index = self._channel_color_tick_index(ticks)
        updated_ticks = []
        for idx, (pos, rgba) in enumerate(ticks):
            if idx == color_tick_index:
                updated_ticks.append((pos, colormap_color + (rgba[3],)))
            else:
                updated_ticks.append((pos, rgba))
        histogram_state['gradient']['ticks'] = updated_ticks

        # update the colormap color for the current channel in the class variable
        self.colormap_colors[channel_index % len(self.colormap_colors)] = colormap_color

        self._restore_channel_histogram_widget_state(histogram_state)

    def update_color_positions(self):
        # get the min and max values for all channels
        if self.img is None:
            return
        logger.info('Updating channel color ranges to match the current image data.')
        for i in range(self.img.shape[-1]):
            histogram_state = self.histogram_states.get(i, None)
            if histogram_state is None:
                logger.debug('No histogram state stored for channel %s. Skipping update.', i)
                continue
            selected_im = self.img[:, :, i]
            amin = np.amin(selected_im)
            amax = np.amax(selected_im)
            # set the colormin and colormax positions to the min and max values of the image
            colormin_pos = amin / max_dtype_val
            colormax_pos = amax / max_dtype_val
            # update the histogram state with the new colormap color

            old_opacity_min = histogram_state['gradient']['ticks'][0][1][3]
            old_opacity_max = histogram_state['gradient']['ticks'][1][1][3]

            histogram_state['gradient']['ticks'][0] = (colormin_pos, (0, 0, 0, old_opacity_min))
            histogram_state['gradient']['ticks'][1] = (colormax_pos, self.colormap_colors[i] + (old_opacity_max,))
            logger.debug('Updated channel %s color positions to %.4f and %.4f.', i, colormin_pos, colormax_pos)

    def set_colormap(self, index: int, color: tuple[int, int, int], change_color_manager=True):
        # Set the colormap color for the specified index

        self.colormap_colors[index % len(self.colormap_colors)] = color


        logger.info(f"Composite Image: Setting colormap color for channel {index} to {color}")
        if self.color_manager:
            if change_color_manager:
                # emits a signal as well
                logger.debug('Propagating channel %s color change to the shared color manager.', index)
                self.color_manager.set_color_rgb(index, color)

        if index == self.channel_slider.value():
            self.color_widget.blockSignals(True)
            self.color_widget.setColor(pg.mkColor(color))
            self.color_widget.blockSignals(False)

        if index in self.histogram_states:
            # Update the histogram state with the new colormap color
            histogram_state = self.histogram_states[index]
            ticks = self._sorted_gradient_ticks(histogram_state)
            color_tick_index = self._channel_color_tick_index(ticks)
            updated_ticks = []
            for idx, (pos, rgba) in enumerate(ticks):
                if idx == color_tick_index:
                    updated_ticks.append((pos, color + (rgba[3],)))
                else:
                    updated_ticks.append((pos, rgba))
            histogram_state['gradient']['ticks'] = updated_ticks
            logger.info(f'Updated colormap color for channel {index}')

        # update the composite image with the new colormap color
        self.update_plot_line_color(index, QColor(*color))
        if index == self.channel_slider.value():
            self.sync_colormap_current_channel_to_widget()
        else:
            self._refresh_composite_from_histogram_states()

        # self.update_channel_and_composite_levels()
        # update is automatically triggered by gradient change

    def save_data(self):
        options = QFileDialog.Options()
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Composite Image",
            "",
            "TIFF Files (*.tif *.tiff);;PNG Files (*.png);;All Files (*)",
            options=options
        )

        if not file_path:
            return

        wants_png = selected_filter.startswith("PNG") or file_path.lower().endswith(".png")
        if wants_png:
            if not file_path.lower().endswith(".png"):
                file_path += ".png"
            self._export_composite_png(file_path)
            return

        if not file_path.lower().endswith((".tif", ".tiff")):
            file_path += ".tif"
        self._save_composite_tiff(file_path)

    def _save_composite_tiff(self, file_path: str):
        if self.img is None:
            return

        if self.img_series is not None:
            # Export the full result stack as an ImageJ hyperstack in (Z/T, C, Y, X) order
            # instead of only the currently displayed slice.
            image_to_save = np.moveaxis(self.img_series, -1, 1)
            outer_axis = 'T' if self.outer_axis_label.lower().startswith('time') else 'Z'
            self.fiji_saver.axes = f'{outer_axis}CYX'
        else:
            image_to_save = np.moveaxis(self.img, -1, 0)
            self.fiji_saver.axes = 'CYX'
        self.fiji_saver.update_image(image_to_save)
        self.fiji_saver.path = file_path
        # luts are referenced via the class variable colormap_colors
        # print(f'colormap colors {self.colormap_colors}, {self.fiji_saver.colormaps}')

        scale_factor_8bit_nbit = 255 / max_dtype_val
        # pass the ranges from the histogram states to the fiji saver in the format list((min1, max1), (min2, max2), ...)
        channel_count = image_to_save.shape[self.fiji_saver.axes.find('C')]
        ranges_nbit = [self.histogram_states[i]['levels'] for i in range(channel_count)]
        # ranges_8bit = [(int(min_ * scale_factor_8bit_nbit), int(max_ * scale_factor_8bit_nbit)) for min_, max_ in ranges_nbit]
        self.fiji_saver.ranges = ranges_nbit
        self.fiji_saver.colormaps = self.color_manager.get_all_colors_rgb() if self.color_manager is not None else self.colormap_colors
        self.fiji_saver.save_composite_image()

    def _export_composite_png(self, file_path: str):
        if self.img is None:
            return

        rgb_image = self._build_composite_export_rgb8()
        if rgb_image is None:
            return

        height, width, _ = rgb_image.shape
        qimage = QtGui.QImage(rgb_image.data, width, height, 3 * width, QtGui.QImage.Format_RGB888).copy()

        include_scalebar = self._prompt_include_scalebar()
        if include_scalebar is None:
            return
        if include_scalebar:
            self._draw_scalebar_on_image(qimage)

        if not qimage.save(file_path, "PNG"):
            logger.error("Failed to save composite PNG export to %s", file_path)
            return
        logger.info("Saved composite PNG export to %s", file_path)

    def _build_composite_export_rgb8(self) -> np.ndarray | None:
        rgb_16 = self.get_rgba()
        if rgb_16 is None:
            return None

        level_min, level_max = self._current_composite_levels()
        denom = max(level_max - level_min, 1.0)
        rgb_scaled = np.clip((rgb_16.astype(np.float32) - level_min) / denom, 0.0, 1.0)
        return np.ascontiguousarray((rgb_scaled * 255.0).astype(np.uint8))

    def _prompt_include_scalebar(self) -> bool | None:
        pixel_size_um = self.export_scalebar_pixel_size_um
        if pixel_size_um is None or not np.isfinite(pixel_size_um) or pixel_size_um <= 0:
            return False

        message_box = QMessageBox(self)
        message_box.setWindowTitle("Composite PNG Export")
        message_box.setText("Include scalebar in the exported PNG?")
        message_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        default_button = QMessageBox.Yes if self.export_scalebar_visible else QMessageBox.No
        message_box.setDefaultButton(default_button)
        reply = message_box.exec_()
        if reply == QMessageBox.Cancel:
            return None
        return reply == QMessageBox.Yes

    def _draw_scalebar_on_image(self, image: QtGui.QImage):
        pixel_size_um = self.export_scalebar_pixel_size_um
        if pixel_size_um is None or not np.isfinite(pixel_size_um) or pixel_size_um <= 0:
            return

        length_um = float(self.export_scalebar_length) * self._unit_to_um_scale(self.export_scalebar_unit)
        if not np.isfinite(length_um) or length_um <= 0:
            return

        width = image.width()
        height = image.height()
        margin = max(12, min(width, height) // 20)
        bar_pixels = int(round(length_um / pixel_size_um))
        bar_pixels = max(1, min(bar_pixels, max(1, width - 2 * margin)))
        line_thickness = max(3, min(width, height) // 180)
        font_size = max(10, min(width, height) // 35)
        label_text = f"{self._format_scalebar_value(self.export_scalebar_length)} {self._normalize_length_unit(self.export_scalebar_unit)}"

        bar_x0 = width - margin - bar_pixels
        bar_x1 = width - margin
        bar_y = height - margin - line_thickness

        painter = QtGui.QPainter(image)
        try:
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setRenderHint(QtGui.QPainter.TextAntialiasing)

            font = painter.font()
            font.setPointSize(font_size)
            painter.setFont(font)
            text_rect = painter.fontMetrics().boundingRect(label_text)

            box_padding = max(6, font_size // 3)
            overlay_height = text_rect.height() + line_thickness + 3 * box_padding
            overlay_top = max(0, bar_y - text_rect.height() - 2 * box_padding)
            overlay_left = max(0, bar_x0 - box_padding)
            overlay_width = min(width - overlay_left, bar_pixels + 2 * box_padding)
            overlay_rect = QRect(overlay_left, overlay_top, overlay_width, overlay_height)

            painter.fillRect(overlay_rect, QColor(0, 0, 0, 140))

            line_pen = QtGui.QPen(QColor(255, 255, 255))
            line_pen.setWidth(line_thickness)
            line_pen.setCapStyle(Qt.FlatCap)
            painter.setPen(line_pen)
            painter.drawLine(bar_x0, bar_y, bar_x1, bar_y)

            painter.setPen(QColor(255, 255, 255))
            text_x = bar_x1 - text_rect.width()
            text_y = bar_y - box_padding
            painter.drawText(text_x, text_y, label_text)
        finally:
            painter.end()

    def export_spectrum_plot(self):
        if self.spectral_cmps is None or len(self.spectrum_lines) == 0:
            QMessageBox.information(self, "Export Spectra", "No spectral plot is available to export.")
            return

        options = QFileDialog.Options()
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Spectral Plot",
            "",
            "PNG Files (*.png);;PDF Files (*.pdf);;All Files (*)",
            options=options
        )
        if not file_path:
            return

        export_options = self._prompt_plot_export_size()
        if export_options is None:
            return
        width, height, transparent_background = export_options

        wants_pdf = selected_filter.startswith("PDF") or file_path.lower().endswith(".pdf")
        if wants_pdf:
            if not file_path.lower().endswith(".pdf"):
                file_path += ".pdf"
            self._export_plot_to_pdf(self.spectrum_view, file_path, width, height)
        else:
            if not file_path.lower().endswith(".png"):
                file_path += ".png"
            self._export_plot_to_png(self.spectrum_view, file_path, width, height, transparent_background)

    def _prompt_plot_export_size(
            self,
            default_width: int = 1800,
            default_height: int = 1200,
    ) -> tuple[int, int, bool] | None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Spectral Plot Export")
        layout = QVBoxLayout(dialog)
        form_layout = QFormLayout()

        width_spinbox = QSpinBox(dialog)
        width_spinbox.setRange(256, 12000)
        width_spinbox.setValue(default_width)
        height_spinbox = QSpinBox(dialog)
        height_spinbox.setRange(256, 12000)
        height_spinbox.setValue(default_height)
        transparent_checkbox = QCheckBox("Transparent background (PNG only)", dialog)

        form_layout.addRow("Width (px):", width_spinbox)
        form_layout.addRow("Height (px):", height_spinbox)
        form_layout.addRow("", transparent_checkbox)
        layout.addLayout(form_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return None
        return width_spinbox.value(), height_spinbox.value(), transparent_checkbox.isChecked()

    def _export_plot_to_png(self, plot_widget: pg.PlotWidget, file_path: str, width: int, height: int):
        image = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32)
        background_color = plot_widget.backgroundBrush().color()
        if not background_color.isValid():
            background_color = QColor(255, 255, 255)
        image.fill(background_color)

        painter = QtGui.QPainter(image)
        try:
            plot_widget.scene().render(painter, QRectF(0, 0, width, height), plot_widget.sceneRect())
        finally:
            painter.end()

        if not image.save(file_path, "PNG"):
            logger.error("Failed to save spectral plot PNG export to %s", file_path)
            return
        logger.info("Saved spectral plot PNG export to %s", file_path)

    def _export_plot_to_pdf(self, plot_widget: pg.PlotWidget, file_path: str, width: int, height: int):
        dpi = 300
        pdf_writer = QtGui.QPdfWriter(file_path)
        pdf_writer.setResolution(dpi)
        pdf_writer.setPageMargins(QMarginsF(0, 0, 0, 0))
        page_width_mm = width / dpi * 25.4
        page_height_mm = height / dpi * 25.4
        pdf_writer.setPageSize(QtGui.QPageSize(QSizeF(page_width_mm, page_height_mm), QtGui.QPageSize.Millimeter))

        painter = QtGui.QPainter(pdf_writer)
        try:
            viewport = painter.viewport()
            plot_widget.scene().render(
                painter,
                QRectF(0, 0, viewport.width(), viewport.height()),
                plot_widget.sceneRect(),
            )
        finally:
            painter.end()
        logger.info("Saved spectral plot PDF export to %s", file_path)

    @staticmethod
    def _normalize_length_unit(unit: str | None) -> str:
        if unit is None:
            return "\u00b5m"
        normalized = str(unit).replace("Â", "").strip()
        if normalized in {"um", "µm"}:
            return "\u00b5m"
        return normalized

    def _unit_to_um_scale(self, unit: str | None) -> float:
        normalized = self._normalize_length_unit(unit).lower()
        if normalized == "nm":
            return 1e-3
        if normalized == "mm":
            return 1e3
        return 1.0

    @staticmethod
    def _format_scalebar_value(value: float) -> str:
        return f"{float(value):g}"

    # Re-define these helpers here to keep export rendering robust across Qt/Python
    # environments and Windows string encoding oddities around the micrometer symbol.
    def _plot_export_source_rect(self, plot_widget: pg.PlotWidget) -> QRectF:
        plot_item = plot_widget.getPlotItem()
        if plot_item is None:
            return plot_widget.scene().sceneRect()
        rect = plot_item.sceneBoundingRect()
        if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
            return plot_widget.scene().sceneRect()
        return rect.adjusted(-6, -6, 6, 6)

    def _plot_export_dimensions(self, plot_widget: pg.PlotWidget, width: int, height: int) -> tuple[int, int]:
        source_rect = self._plot_export_source_rect(plot_widget)
        if source_rect.isNull() or source_rect.width() <= 0 or source_rect.height() <= 0:
            return max(1, int(width)), max(1, int(height))

        width = max(1, int(width))
        height = max(1, int(height))
        source_aspect = float(source_rect.width()) / float(source_rect.height())
        target_aspect = float(width) / float(height)

        # Fit the export into the requested box without distorting text or axes.
        if target_aspect > source_aspect:
            width = max(1, int(round(height * source_aspect)))
        else:
            height = max(1, int(round(width / source_aspect)))
        return width, height

    def _export_plot_to_png(
            self,
            plot_widget: pg.PlotWidget,
            file_path: str,
            width: int,
            height: int,
            transparent_background: bool = False,
    ):
        width, height = self._plot_export_dimensions(plot_widget, width, height)
        image = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32)
        background_color = plot_widget.backgroundBrush().color()
        if not background_color.isValid():
            background_color = QColor(255, 255, 255)
        image.fill(Qt.transparent if transparent_background else background_color)

        painter = QtGui.QPainter(image)
        original_background = background_color
        try:
            if transparent_background:
                plot_widget.setBackground((0, 0, 0, 0))
            plot_widget.scene().render(
                painter,
                QRectF(0, 0, width, height),
                self._plot_export_source_rect(plot_widget),
                Qt.KeepAspectRatio,
            )
        finally:
            if transparent_background:
                plot_widget.setBackground(original_background)
            painter.end()

        if not image.save(file_path, "PNG"):
            logger.error("Failed to save spectral plot PNG export to %s", file_path)
            return
        logger.info("Saved spectral plot PNG export to %s", file_path)

    def _export_plot_to_pdf(self, plot_widget: pg.PlotWidget, file_path: str, width: int, height: int):
        width, height = self._plot_export_dimensions(plot_widget, width, height)
        dpi = 300
        pdf_writer = QtGui.QPdfWriter(file_path)
        pdf_writer.setResolution(dpi)
        pdf_writer.setPageMargins(QMarginsF(0, 0, 0, 0), QtGui.QPageLayout.Millimeter)
        page_width_mm = width / dpi * 25.4
        page_height_mm = height / dpi * 25.4
        pdf_writer.setPageSize(QtGui.QPageSize(QSizeF(page_width_mm, page_height_mm), QtGui.QPageSize.Millimeter))

        painter = QtGui.QPainter(pdf_writer)
        try:
            viewport = painter.viewport()
            plot_widget.scene().render(
                painter,
                QRectF(0, 0, viewport.width(), viewport.height()),
                self._plot_export_source_rect(plot_widget),
                Qt.KeepAspectRatio,
            )
        finally:
            painter.end()
        logger.info("Saved spectral plot PDF export to %s", file_path)

    @staticmethod
    def _normalize_length_unit(unit: str | None) -> str:
        if unit is None:
            return "\u00b5m"
        normalized = str(unit).replace("Â", "").replace("Ã‚", "").strip()
        if normalized.lower() in {"um", "\u00b5m"}:
            return "\u00b5m"
        return normalized

    def set_export_scalebar_config(
            self,
            pixel_size_um: float | None = None,
            length: float | None = None,
            unit: str | None = None,
            visible: bool | None = None,
    ):
        if pixel_size_um is not None and np.isfinite(pixel_size_um) and pixel_size_um > 0:
            self.export_scalebar_pixel_size_um = float(pixel_size_um)
        if length is not None and np.isfinite(length) and length > 0:
            self.export_scalebar_length = float(length)
        if unit is not None:
            self.export_scalebar_unit = self._normalize_length_unit(unit)
        if visible is not None:
            self.export_scalebar_visible = bool(visible)
    
    def save_preset(self, mode='seeds'):
        """ 
        Saves the current colormaps, vmin, vmax positions, and the H & W seeds to a file
        
        Mode can be 'seeds' or 'results' to save the H or W seeds respectively from the init or the resulting NNMF analysis
        """
        # Open a file dialog to select where to save the TIFF file
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Preset",
            "",
            "Preset Files (*.preset);;All Files (*)",
            options=options
        )

        # Save the H seeds
        if mode.lower() == 'seeds':
            seeds_H = self.spectral_cmps_seed
        elif mode.lower() == 'results':
            seeds_H = self.spectral_cmps
        else:
            raise ValueError("Invalid mode. Mode must be 'seeds' or 'results'")

        # Ensure the file has the correct extension 
        if not file_path:
            return

        self.save_to_presets(file_path, seeds_H, self.wavenumbers, self.color_manager.get_all_colors_rgb(), self.histogram_states)

    def save_components(self):
        # Open a file dialog to select where to save the CSV file
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save H Components as CSV",
            "",
            "CSV Files (*.csv);;All Files (*)",
            options=options
        )

        if not file_path:  # User canceled the dialog
            return

        axis_values = self.axis_labels if self.axis_labels is not None else [str(v) for v in self.wavenumbers[...]]

        header_label = "Channel Label" if self.axis_labels is not None else "Wavenumber (1/cm)"
        header = header_label + "," + ",".join([f"Component {i}" for i in range(self.spectral_cmps.shape[0])])
        rows = [
            [axis_values[i], *self.spectral_cmps[:, i].tolist()]
            for i in range(self.spectral_cmps.shape[1])
        ]
        np.savetxt(file_path, rows, delimiter=",", header=header, comments='', fmt='%s')
        logger.info(f"Saved H components to {file_path}")

    @staticmethod
    def serialize_histogram_state(state: dict) -> dict:
        levels = state.get('levels', (0, max_dtype_val))
        try:
            vmin = float(levels[0])
            vmax = float(levels[1])
        except Exception:
            vmin, vmax = 0.0, float(max_dtype_val)

        gradient = state.get('gradient', {}) if isinstance(state, dict) else {}
        ticks = list(gradient.get('ticks', [])) if isinstance(gradient, dict) else []
        # save the tick colors and their positions (norm. between 0 and 1 for the color gradient)
        if len(ticks) >= 2:
            ticks = sorted(ticks, key=lambda tick: tick[0])
            bottom_tick = ticks[0]
            top_tick = ticks[-1]
            bottom_pos = float(bottom_tick[0])
            top_pos = float(top_tick[0])
            bottom_color = tuple(bottom_tick[1])
            top_color = tuple(top_tick[1])
        else:
            bottom_pos = 0.0
            top_pos = 1.0
            bottom_color = (0, 0, 0, 255)
            top_color = (255, 255, 255, 255)

        return {
            "levels": (vmin, vmax),
            "bottom_color": bottom_color,
            "top_color": top_color,
            "bottom_pos": bottom_pos,
            "top_pos": top_pos,
        }

    @classmethod
    def export_histogram_states_for_preset(cls, histogram_states: dict) -> dict:
        exported = {}
        for key, state in sorted(histogram_states.items(), key=lambda item: int(item[0])):
            exported[int(key)] = cls.serialize_histogram_state(state)
        return exported

    @staticmethod
    def save_to_presets(fpath: str, seeds: np.array, wavenumbers: np.array,
                        colormap_colors: list[tuple[int, int, int]], histogram_states: dict):
        if not fpath.lower().endswith(".preset"):
            fpath += ".preset"

        exported_hist_states = CompositeImageViewWidget.export_histogram_states_for_preset(histogram_states)
        with open(fpath, "w") as f:
            # Save the colormap colors
            f.write(f"colormap_colors = {colormap_colors}\n")
            f.write(f"histogram_states = {exported_hist_states}\n")
            # Save the vmin and vmax positions
            f.write("vmin_vmax = [")
            for i in range(len(histogram_states)):
                f.write(f"({histogram_states[i]['levels'][0]}, {histogram_states[i]['levels'][1]}), ")
            f.write("]\n")
            # write the slider top and bottom colors
            f.write("slider_colors = [")
            for i in range(len(histogram_states)):
                f.write(f"({histogram_states[i]['gradient']['ticks'][0][1]}, {histogram_states[i]['gradient']['ticks'][1][1]}), ")
            f.write("]\n")
            f.write("slider_positions = [")
            for i in range(len(histogram_states)):
                ticks = sorted(histogram_states[i]['gradient']['ticks'], key=lambda tick: tick[0])
                f.write(f"({ticks[0][0]}, {ticks[-1][0]}), ")
            f.write("]\n")
            f.write(f"wave_numbers = {wavenumbers.tolist()}\n")
            # Save the H seeds
            f.write(f"seeds = {seeds.tolist()}")
        logger.info(f"Saved preset to {fpath}")


    @staticmethod
    def load_from_presets(fpath: str) -> tuple[
        list[tuple[int, int, int]], dict, np.ndarray, np.ndarray]:
        save_keys = {
            'histogram_states': 'histogram_states',
            'vmin_vmax': 'vmin_vmax',
            'slider_colors': 'slider_colors',
            'slider_positions': 'slider_positions',
            'colormap_colors': 'colormap_colors',
            'wave_numbers': 'wavenumbers',
            'seeds': 'seeds'
        }

        # Store loaded variables temporarily
        locals_ = {
            'histogram_states': None,
            'vmin_vmax': None,
            'slider_colors': None,
            'slider_positions': None,
            'colormap_colors': None,
            'wavenumbers': None,
            'seeds': None
        }

        with open(fpath, "r") as f:
            lines = f.readlines()
            for key, varname in save_keys.items():
                for line in lines:
                    # use eval
                    lhs, sep, rhs = line.partition('=')
                    if sep and lhs.strip() == key:
                        value = ast.literal_eval(rhs.strip())
                        locals_[varname] = value
                        break  # Stop after the first match for each key

        # Convert wavenumbers and seeds to numpy arrays if needed
        locals_['wavenumbers'] = np.array(locals_['wavenumbers'])
        locals_['seeds'] = np.array(locals_['seeds'])

        histogram_states = locals_['histogram_states']
        if histogram_states is None:
            histogram_states = {}
            vmin_vmax = locals_.get('vmin_vmax') or []
            slider_colors = locals_.get('slider_colors') or []
            slider_positions = locals_.get('slider_positions') or []
            for idx, levels in enumerate(vmin_vmax):
                colors = slider_colors[idx] if idx < len(slider_colors) else ((0, 0, 0, 255), (255, 255, 255, 255))
                positions = slider_positions[idx] if idx < len(slider_positions) else (0.0, 1.0)
                histogram_states[idx] = {
                    "levels": tuple(levels),
                    "bottom_color": tuple(colors[0]),
                    "top_color": tuple(colors[1]),
                    "bottom_pos": float(positions[0]),
                    "top_pos": float(positions[1]),
                }

        return (
            locals_['colormap_colors'],
            histogram_states,
            locals_['wavenumbers'],
            locals_['seeds']
        )

    def update_plot_line_color(self, index: int, color: QColor):
        # update the color of the plot in the spectrum view
        if 0 <= index < len(self.spectrum_lines):
            self.spectrum_lines[index].setPen(pg.mkPen(color))
        if 0 <= index < len(self.seed_lines):
            self.seed_lines[index].setPen(pg.mkPen(color))

    def reload_color_current_channel(self):
        cur_channel = self.channel_slider.value()
        # comes from the color manager, so no need to change it there
        self.set_colormap(cur_channel, self.get_color(cur_channel), change_color_manager=False)

    def reload_color(self, channel_index: int):
        color = self.get_color(channel_index)
        if self.colormap_colors[channel_index % len(self.colormap_colors)] == color:
            return
        self.set_colormap(channel_index, color, change_color_manager=False)


    def make_color_state(self, index: int, vmin_max: tuple, color: tuple[int, int, int], colorpos='default'):
        vmin, vmax = vmin_max
        # get the current minimum and maximum values of the channel at the index
        colormin_pos, colormax_pos = 0, 1
        if not colorpos=='default':
            if colorpos == 'auto':
                # get the current minimum and maximum values of the channel at the index
                if self.img is None:
                    return
                selected_im = self.img[:, :, index]
                amin = np.amin(selected_im)
                amax = np.amax(selected_im)
                # set the colormin and colormax positions to the min and max values of the image
                colormin_pos = amin / max_dtype_val
                colormax_pos = amax / max_dtype_val
                logger.debug('Calculated color positions for channel %s: %.4f, %.4f.', index, colormin_pos, colormax_pos)

        self.histogram_states[index] = {
            'gradient': {
                'mode': 'rgb',
                'ticks': [
                    (colormin_pos, (0, 0, 0, 255)),
                    (colormax_pos, color + (255,))
                ],
                'ticksVisible': True
            },
            'levels': (vmin, vmax),
            'mode': 'mono'
        }
        logger.info(f'Created histogram state for channel {index} with info {self.histogram_states[index]}')

        # set the current histogram state in the channel view
        if index == self.channel_slider.value():
            self._restore_channel_histogram_widget_state(self.histogram_states[index])

    def restore_histogram_state_from_preset(self, index: int, preset_state: dict):
        """
        Restore a saved histogram/LUT state from the JSON preset format.

        The JSON stores absolute level values plus optional bottom/top tick colors and
        positions. Older presets may only contain levels and top_color.
        """
        if not isinstance(preset_state, dict):
            return

        levels = preset_state.get("levels", (0, max_dtype_val))
        try:
            vmin = float(levels[0])
            vmax = float(levels[1])
        except Exception:
            vmin, vmax = 0.0, float(max_dtype_val)

        bottom_color = tuple(preset_state.get("bottom_color", (0, 0, 0, 255)))
        top_color = tuple(preset_state.get("top_color", self.get_color(index) + (255,)))
        if len(bottom_color) == 3:
            bottom_color = bottom_color + (255,)
        if len(top_color) == 3:
            top_color = top_color + (255,)

        bottom_pos = preset_state.get("bottom_pos", 0.0)
        top_pos = preset_state.get("top_pos", 1.0)
        try:
            bottom_pos = float(bottom_pos)
        except Exception:
            bottom_pos = vmin
        try:
            top_pos = float(top_pos)
        except Exception:
            top_pos = vmax

        # JSON presets store tick positions in data units. Convert them back to the
        # histogram gradient's normalized 0..1 coordinates used by pyqtgraph.
        if bottom_pos < 0 or bottom_pos > 1:
            bottom_pos /= max_dtype_val
        if top_pos < 0 or top_pos > 1:
            top_pos /= max_dtype_val
        bottom_pos = float(np.clip(bottom_pos, 0.0, 1.0))
        top_pos = float(np.clip(top_pos, 0.0, 1.0))
        if bottom_pos >= top_pos:
            bottom_pos, top_pos = 0.0, 1.0

        self.set_colormap(index, tuple(top_color[:3]))
        self.histogram_states[index] = {
            'gradient': {
                'mode': 'rgb',
                'ticks': [
                    (bottom_pos, tuple(bottom_color)),
                    (top_pos, tuple(top_color))
                ],
                'ticksVisible': True
            },
            'levels': (vmin, vmax),
            'mode': 'mono'
        }
        logger.info('Restored histogram state for channel %s from preset: %s', index, self.histogram_states[index])

        if index == self.channel_slider.value():
            self._restore_channel_histogram_widget_state(self.histogram_states[index])

    def set_spectral_units(self, units: str):
        if self.axis_labels is not None:
            self.spectrum_view.setLabel('bottom', 'Channels')
        elif units.lower() == 'nm':
            self.spectrum_view.setLabel('bottom', 'Wavelength (nm)')
        else:
            self.spectrum_view.setLabel('bottom', 'Wavenumber (1/cm)')

    def choose_color(self, color: QColor | None = None):
        # Open a QColorDialog to choose a color for colormap
        if color is None:
            color = QColorDialog.getColor()

        if color.isValid():
            # Convert QColor to QColor object and
            qcolor = pg.mkColor(color.name())
            self.set_colormap(self.channel_slider.value(), (qcolor.red(), qcolor.green(), qcolor.blue()))

    # new implementation of the get_rgba method where the colormap is applied to the image similar to FIJI
    # with 8 bit colormaps
    def get_rgba(self) -> np.ndarray | None:
        # print('Updating composite image')
        """
        Generate a composite RGB image from individual grayscale channels, mimicking FIJI's composite LUT behavior.

        Each channel is:
          - Linearly normalized using histogram levels (vmin, vmax)
          - Mapped to a LUT color (e.g., red, green, blue, etc.)
          - Scaled as if LUTs are 8-bit, then upscaled to 16-bit

        Returns:
            np.ndarray: RGB image in uint16 format with shape (height, width, 3)
        """
        if self.img is None:
            return

        # Create a float32 RGB image for accumulation
        rgb_image = np.zeros((*self.img.shape[:2], 3), dtype=np.float32)
        channels = self.img.shape[-1]

        for i in range(channels):
            if i not in self.histogram_states:
                continue

            histogram_state = self.histogram_states[i]

            vmin, vmax = histogram_state['levels']
            channel_data = self.img[..., i].astype(np.float32)
            if vmax <= vmin:
                continue
            norm = np.clip((channel_data - vmin) / (vmax - vmin), 0, 1)
            ticks = self._sorted_gradient_ticks(histogram_state)
            positions = np.array([tick[0] for tick in ticks], dtype=np.float32)
            colors = np.array([tick[1][:3] for tick in ticks], dtype=np.float32) / 255.0
            flat_norm = norm.reshape(-1)
            mapped_rgb = np.empty((flat_norm.size, 3), dtype=np.float32)
            for c in range(3):
                mapped_rgb[:, c] = np.interp(
                    flat_norm,
                    positions,
                    colors[:, c],
                    left=colors[0, c],
                    right=colors[-1, c],
                )
            rgb_image += mapped_rgb.reshape((*norm.shape, 3))

        # Clip the final RGB image to [0, 1] and scale to 16-bit
        rgb_image = np.clip(rgb_image, 0, 1)
        rgb_uint16 = (rgb_image * 65535).astype(np.uint16)
        return rgb_uint16

    def update_channel_and_composite_levels(self, *args, composite_levels=None):
        """
        Update the composite image and channel view levels based on the current channel's histogram state.
        Returns:

        """
        # Get the current channel index
        if self.img is None:
            return
        channel_index = self.channel_slider.value()
        # Save the histogram state
        histogram_state = self.channel_view.getHistogramWidget().saveState()
        self.histogram_states[channel_index] = histogram_state
        self._refresh_composite_from_histogram_states(composite_levels=composite_levels)
        self._sync_color_button_to_gradient()
        # self.composite_view.autoLevels()

    def _refresh_composite_from_histogram_states(self, composite_levels=None):
        if self.img is None:
            return
        false_color_im = self.get_rgba()
        if false_color_im is None:
            return

        composite_view_range = self._capture_viewbox_range(self.composite_view)
        self.composite_view.setImage(false_color_im, autoLevels=False)
        self._restore_viewbox_range(self.composite_view, composite_view_range)
        self.composite_view.ui.histogram.setHistogramRange(0, max_dtype_val)
        if auto_min_max:
            min_, max_ = self.min_max_levels()
            self.composite_view.ui.histogram.setLevels(min_, max_)
        else:
            min_, max_ = composite_levels if composite_levels is not None else self._current_composite_levels()
            self.composite_view.ui.histogram.setLevels(min_, max_)

    def min_max_levels(self):
        # Initialize variables for min_levels and max_levels
        min_levels = float(0)
        max_levels = float(max_dtype_val)

        # Iterate through the histogram_state dictionary
        levels = [state['levels'] for key, state in self.histogram_states.items()]
        min_levels = min(level[0] for level in levels)
        max_levels = min(level[1] for level in levels)

        return min_levels, max_levels

    def callback_channel(self, *args):
        if not self.timeout_callbacks:
            self.update_channel_view(*args)

    def reset_levels(self):
        # Reset the levels of the composite image to the default range (0 - 65535)
        self.composite_view.ui.histogram.setLevels(0, max_dtype_val)

    def _current_composite_levels(self) -> tuple[float, float]:
        """
        Return the current composite histogram levels, or the full dtype range if
        no valid levels are available yet.
        """
        try:
            levels = self.composite_view.getHistogramWidget().item.getLevels()
            if levels is None:
                return 0.0, float(max_dtype_val)
            min_level, max_level = float(levels[0]), float(levels[1])
            if not np.isfinite(min_level) or not np.isfinite(max_level) or min_level >= max_level:
                return 0.0, float(max_dtype_val)
            return min_level, max_level
        except Exception:
            return 0.0, float(max_dtype_val)

    def _sync_color_button_to_gradient(self):
        """Sync the ColorButton with the top color in the histogram gradient."""
        if self.timeout_callbacks:
            return
        try:
            histogram_state = self.channel_view.getHistogramWidget().saveState()
        except Exception:
            return
        channel_index = self.channel_slider.value()
        top_color = self._extract_channel_color_from_ticks(
            self._sorted_gradient_ticks(histogram_state),
            fallback=self.colormap_colors[channel_index % len(self.colormap_colors)],
        )

        current_color = self.color_widget.color().getRgb()[:3]

        if current_color == top_color:
            return  # No change needed

        # Only update if different → avoid triggering .sigColorChanged
        self.color_widget.blockSignals(True)
        self.color_widget.setColor(pg.mkColor(top_color))
        self.color_widget.blockSignals(False)

        # update plot
        self.update_plot_line_color(channel_index, pg.mkColor(top_color))

    def lock_bottom_tick(self):
        gradient = self.channel_view.getHistogramWidget().gradient
        locked_pos = 0.0
        locked_color = (0, 0, 0, 255)

        def enforce_lock():
            chan = self.channel_slider.value()
            if chan not in self.histogram_states:
                return

            # Get bottom tick (first tick)
            tick, pos = gradient.listTicks()[0]
            current_color = tick.color.getRgb()

            # Check if tick was modified
            if not np.isclose(pos, locked_pos) or current_color != locked_color:
                logger.debug('Bottom histogram tick modified manually; restoring locked state.')
                gradient.blockSignals(True)
                tick.setPos(QPointF(locked_pos, 0))  # y=0 is ignored
                current_ticks = gradient.listTicks()
                self._restore_channel_histogram_widget_state(self.histogram_states[chan])
                # remove all ticks that are not in the current ticks
                for tick, pos in gradient.listTicks():
                    if tick not in current_ticks:
                        gradient.scene().removeItem(tick)

                # tick.setColor(pg.mkColor(locked_color))
                gradient.blockSignals(False)

        # Connect once
        gradient.sigGradientChanged.connect(enforce_lock)
        enforce_lock()


class UpdateImageWorker(QObject):
    # TODO: setting images is still complicated in new threads because the widget still lives in another thread
    finished = pyqtSignal()

    def __init__(self, result_viewer_widget, img, spectral_axis, spectral_cmps):
        super().__init__()
        self.result_viewer_widget = result_viewer_widget
        self.img_file = img
        self.spectral_axis = spectral_axis
        self.spectral_cmps = spectral_cmps

    def run(self):
        # Call the update_image method of the result viewer widget
        self.result_viewer_widget.timeout_callbacks = True
        self.result_viewer_widget.img = self.img_file
        if self.spectral_axis is not None:
            if self.spectral_axis != -1:
                self.result_viewer_widget.img = np.moveaxis(self.result_viewer_widget.img, self.spectral_axis, -1)
        self.result_viewer_widget.composite_view.setImage(self.img_file)
        # adjust slider and scrollbar to max....
        channels = self.result_viewer_widget.img.shape[-1] - 1
        self.result_viewer_widget.channel_slider.setMaximum(channels)
        self.result_viewer_widget.channel_spinbox.setMaximum(channels)
        if channels:
            ch_selected = self.result_viewer_widget.channel_slider.value()
            # Initialize the channel view with all channels and switch to selected afterwards
            for i in range(self.result_viewer_widget.img.shape[-1]):
                # triggers channel update!
                self.result_viewer_widget.update_channel_view(i)
            self.result_viewer_widget.update_channel_view(0)
            self.result_viewer_widget.reset_levels()
        else:
            # self.result_viewer_widget.update_channel_view(0)
            self.result_viewer_widget.channel_slider.setValue(0)

        self.result_viewer_widget.spectral_cmps = self.spectral_cmps
        if self.spectral_cmps is not None:
            self.result_viewer_widget.plot_components(self.spectral_cmps)
        self.result_viewer_widget.timeout_callbacks = False


if __name__ == '__main__':
    app = QApplication([])
    composite_image = CompositeImageViewWidget()
    # load some example data
    try:
        result = tifffile.imread(r"./example_data/h_e_result.tif")
    except FileNotFoundError as e:
        result = np.ones((3, 100, 100), dtype=np.uint16)
    result = np.moveaxis(result, 0, -1)
    composite_image.make_color_state(0, (0, 20000), (255, 255, 255), colormin_pos=.4, colormax_pos=.5)
    composite_image.update_image(result)

    composite_image.make_color_state(0, (0, 20000), (255, 255, 255), colormin_pos=.4, colormax_pos=.5)
    # modify the colormaps
    # ...

    fov_x = 500
    bar = ScaleBar(composite_image.channel_view.view.getViewBox(), fov_x / composite_image.channel_view.image.shape[0], 500)

    bar.update_scale_bar_len(250)

    composite_image.show()
    app.exec_()
