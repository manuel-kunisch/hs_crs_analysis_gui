import logging

from PyQt5 import QtCore
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLabel,
    QLineEdit, QCheckBox, QComboBox, QSpinBox, QSizePolicy,
)

logger = logging.getLogger(__name__)


class PhysicalUnitsWidget(QWidget):
    fov_change_signal = pyqtSignal(tuple, str)
    options_changed = pyqtSignal(dict)

    # Conversion factors from each supported unit to micrometres.
    _TO_UM = {"nm": 1e-3, "µm": 1.0, "mm": 1e3}

    def __init__(self, parent=None):
        super().__init__(parent)

        self.unit = "µm"
        self.image_shape = None  # to be set externally, as (height, width)
        self.pixel_size = .28    # default pixel size in µm

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # --- Header -------------------------------------------------------
        title_label = QLabel("Physical Units")
        title_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        root.addWidget(title_label)

        subtitle = QLabel(
            "Calibrate pixel size and field of view, and configure the scale "
            "bar used for on-screen display and exported figures."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: palette(mid);")
        root.addWidget(subtitle)

        # The form sits in a fixed-width column on the left so the controls
        # don't stretch across the whole (often very wide) tab. A trailing
        # horizontal stretch keeps it left-aligned; a trailing vertical
        # stretch (added at the end) keeps everything pinned to the top.
        content_row = QHBoxLayout()
        content_row.setSpacing(16)
        form_col = QVBoxLayout()
        form_col.setSpacing(12)

        form_col.addWidget(self._build_calibration_group())
        form_col.addWidget(self._build_scale_bar_group())
        form_col.addWidget(self._build_details_group())

        form_container = QWidget()
        form_container.setLayout(form_col)
        form_container.setMaximumWidth(520)
        form_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        content_row.addWidget(form_container)
        content_row.addStretch(1)
        root.addLayout(content_row)
        root.addStretch(1)

        # Keep the derived "Image Details" panel in sync whenever the
        # calibration controls change.
        self.unit_dropdown.currentTextChanged.connect(self._on_unit_changed)
        self.pixel_size_input.textChanged.connect(self.refresh_image_details)
        self.fov_input.textChanged.connect(self.refresh_image_details)

        self.refresh_image_details()

    # ------------------------------------------------------------------ UI
    def _build_calibration_group(self) -> QGroupBox:
        group = QGroupBox("Calibration")
        form = QFormLayout(group)
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        # Unit
        self.unit_dropdown = QComboBox()
        self.unit_dropdown.addItems(["nm", "µm", "mm"])
        self.unit_dropdown.setCurrentText(self.unit)
        self.unit_dropdown.setToolTip("Physical length unit used for pixel size, field of view, and the scale bar.")
        self.unit_dropdown.currentTextChanged.connect(self.emit_fov_change)
        form.addRow("Unit:", self.unit_dropdown)

        # Pixel size (+ live unit suffix)
        self.pixel_size_input = QLineEdit()
        self.pixel_size_input.setPlaceholderText("e.g. 0.28")
        self.pixel_size_input.setText(str(self.pixel_size))
        self.pixel_size_input.setToolTip("Physical size of one pixel. Editing this recomputes the field of view.")
        self.pixel_size_input.textChanged.connect(self.update_fov_from_pixel_size)
        self.pixel_size_suffix = QLabel(f"{self.unit} / px")
        self.pixel_size_suffix.setStyleSheet("color: palette(mid);")
        px_row = QHBoxLayout()
        px_row.setContentsMargins(0, 0, 0, 0)
        px_row.setSpacing(6)
        px_row.addWidget(self.pixel_size_input, 1)
        px_row.addWidget(self.pixel_size_suffix)
        px_widget = QWidget()
        px_widget.setLayout(px_row)
        form.addRow("Pixel size:", px_widget)

        # Field of view (+ live unit suffix)
        self.fov_input = QLineEdit()
        self.fov_input.setPlaceholderText("e.g. 512, 512")
        self.fov_input.setToolTip("Physical width and height of the image, as 'width, height'. Editing this recomputes the pixel size.")
        self.fov_input.textChanged.connect(self.update_pixel_size_from_fov)
        self.fov_suffix = QLabel(self.unit)
        self.fov_suffix.setStyleSheet("color: palette(mid);")
        fov_row = QHBoxLayout()
        fov_row.setContentsMargins(0, 0, 0, 0)
        fov_row.setSpacing(6)
        fov_row.addWidget(self.fov_input, 1)
        fov_row.addWidget(self.fov_suffix)
        fov_widget = QWidget()
        fov_widget.setLayout(fov_row)
        form.addRow("Field of view:", fov_widget)

        return group

    def _build_scale_bar_group(self) -> QGroupBox:
        group = QGroupBox("Scale Bar")
        form = QFormLayout(group)
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        self.scale_bar_length_spinbox = QSpinBox()
        self.scale_bar_length_spinbox.setRange(1, 1000)
        self.scale_bar_length_spinbox.setValue(50)
        self.scale_bar_length_spinbox.setToolTip("Length of the scale bar drawn on the image, in the selected unit.")
        self.scale_bar_suffix = QLabel(self.unit)
        self.scale_bar_suffix.setStyleSheet("color: palette(mid);")
        sb_row = QHBoxLayout()
        sb_row.setContentsMargins(0, 0, 0, 0)
        sb_row.setSpacing(6)
        sb_row.addWidget(self.scale_bar_length_spinbox)
        sb_row.addWidget(self.scale_bar_suffix)
        sb_row.addStretch(1)
        sb_widget = QWidget()
        sb_widget.setLayout(sb_row)
        form.addRow("Length:", sb_widget)

        self.show_scalebar_checkbox = QCheckBox("Show scale bar")
        self.show_scalebar_checkbox.setToolTip("Overlay the scale bar on the displayed image.")
        self.use_physical_units_checkbox = QCheckBox("Use physical units")
        self.use_physical_units_checkbox.setToolTip("Label axes and exports in physical units instead of pixels.")
        self.show_scalebar_checkbox.stateChanged.connect(self.emit_options_changed)
        self.use_physical_units_checkbox.stateChanged.connect(self.emit_options_changed)
        form.addRow("", self.show_scalebar_checkbox)
        form.addRow("", self.use_physical_units_checkbox)

        return group

    def _build_details_group(self) -> QGroupBox:
        group = QGroupBox("Image Details")
        form = QFormLayout(group)
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        # image_shape_label is part of the public API (set elsewhere); keep it.
        self.image_shape_label = QLabel("not set")
        self.detail_megapixels = QLabel("—")
        self.detail_fov = QLabel("—")
        self.detail_pixel = QLabel("—")
        self.detail_area = QLabel("—")

        form.addRow("Dimensions:", self.image_shape_label)
        form.addRow("Resolution:", self.detail_megapixels)
        form.addRow("Field of view:", self.detail_fov)
        form.addRow("Pixel size:", self.detail_pixel)
        form.addRow("Imaged area:", self.detail_area)

        return group

    # -------------------------------------------------------------- helpers
    def _on_unit_changed(self, unit: str):
        """Update the inline unit suffixes, then refresh the details panel."""
        self.unit = unit
        for label in (
            getattr(self, "fov_suffix", None),
            getattr(self, "scale_bar_suffix", None),
        ):
            if label is not None:
                label.setText(unit)
        if getattr(self, "pixel_size_suffix", None) is not None:
            self.pixel_size_suffix.setText(f"{unit} / px")
        self.refresh_image_details()

    def _current_pixel_size(self):
        try:
            value = float(self.pixel_size_input.text())
            return value if value > 0 else None
        except (TypeError, ValueError):
            return None

    def _format_pixel_size(self, px: float, unit: str) -> str:
        px_nm = px * self._TO_UM[unit] * 1e3
        if unit == "nm":
            return f"{px:g} nm / px"
        return f"{px:g} {unit} / px  ({px_nm:.1f} nm)"

    def _format_area(self, fov_w: float, fov_h: float, unit: str) -> str:
        area = fov_w * fov_h
        primary = f"{area:,.1f} {unit}²"
        area_um2 = area * (self._TO_UM[unit] ** 2)
        if area_um2 >= 1e6:
            secondary_val, secondary_unit = area_um2 / 1e6, "mm²"
        elif area_um2 < 1.0:
            secondary_val, secondary_unit = area_um2 * 1e6, "nm²"
        else:
            secondary_val, secondary_unit = area_um2, "µm²"
        if secondary_unit == f"{unit}²":
            return primary
        return f"{primary}  ({secondary_val:.4g} {secondary_unit})"

    def refresh_image_details(self, *_):
        """Recompute the read-only Image Details panel from the current
        image shape and calibration controls. Safe to call at any time."""
        unit = self.unit_dropdown.currentText()
        px = self._current_pixel_size()
        shape = self.image_shape

        if shape is None or len(shape) < 2:
            self.detail_megapixels.setText("—")
            self.detail_fov.setText("—")
            self.detail_pixel.setText("—" if px is None else self._format_pixel_size(px, unit))
            self.detail_area.setText("—")
            return

        height, width = int(shape[0]), int(shape[1])
        self.detail_megapixels.setText(f"{width * height / 1e6:.2f} MP  ({width:,} × {height:,} px)")

        if px is None:
            self.detail_fov.setText("— (set a pixel size)")
            self.detail_pixel.setText("—")
            self.detail_area.setText("—")
            return

        fov_w, fov_h = width * px, height * px
        self.detail_fov.setText(f"{fov_w:.2f} × {fov_h:.2f} {unit}")
        self.detail_pixel.setText(self._format_pixel_size(px, unit))
        self.detail_area.setText(self._format_area(fov_w, fov_h, unit))

    # ----------------------------------------------------------- public API
    def set_image_shape(self, shape: tuple):
        self.image_shape = shape
        if shape is not None and len(shape) >= 2:
            self.image_shape_label.setText(f"{int(shape[1]):,} × {int(shape[0]):,} px")
        else:
            self.image_shape_label.setText("not set")
        self.refresh_image_details()

    def update_fov_from_pixel_size(self):
        if self.image_shape is None:
            return
        try:
            px_size = float(self.pixel_size_input.text())
            fov = (self.image_shape[1] * px_size, self.image_shape[0] * px_size)
            self.fov_input.setText(f"{fov[0]:.2f}, {fov[1]:.2f}")
            self.fov_change_signal.emit(fov, self.unit_dropdown.currentText())
        except ValueError:
            pass

    def update_pixel_size_from_fov(self):
        if self.image_shape is None:
            return
        try:
            fov_str = self.fov_input.text()
            fx, fy = map(float, fov_str.split(","))
            px_size = fx / self.image_shape[1]
            self.pixel_size_input.setText(f"{px_size:.4f}")
            self.fov_change_signal.emit((fx, fy), self.unit_dropdown.currentText())
        except ValueError:
            pass

    def emit_options_changed(self):
        self.options_changed.emit({
            "show_scalebar": self.show_scalebar_checkbox.isChecked(),
            "use_physical_units": self.use_physical_units_checkbox.isChecked()
        })

    def emit_fov_change(self):
        try:
            fov_str = self.fov_input.text()
            fx, fy = map(float, fov_str.split(","))
            self.fov_change_signal.emit((fx, fy), self.unit_dropdown.currentText())
        except ValueError:
            pass


class PhysicalUnitsManager:
    def __init__(self):
        self.unit = 'µm'
        self.image_shape = None
        self.fov = (None, None)
        self.pixel_size = None
        self.widget = PhysicalUnitsWidget()
        self.widget.unit_dropdown.currentTextChanged.connect(lambda text: self.update_unit(text))
        self.widget.pixel_size_input.textChanged.connect(lambda text: self.update_pixel_size(float(text)))
        self.widget.fov_input.textChanged.connect(lambda text: self.update_fov_from_str(text))

        # load pixel size, unit and fov from widget
        self.unit = self.widget.unit_dropdown.currentText()
        self.pixel_size = float(self.widget.pixel_size_input.text())

    def update_image_dimensions(self, image_shape):
        """
        Update the image dimensions and recalculate the field of view (FOV).
        Args:
            image_shape: Must be a tuple of two integers representing the image dimensions (height, width).
        Returns:
        """
        self.image_shape = image_shape
        logger.info(f"Image dimensions updated: {self.image_shape}")
        # recalculate the fov
        if self.image_shape is not None:
            # FOV is stored/displayed as (width, height).
            self.fov = (self.image_shape[1] * self.pixel_size, self.image_shape[0] * self.pixel_size)
            self.widget.fov_input.setText(f"{self.fov[0]:.2f}, {self.fov[1]:.2f}")
        else:
            logger.warning("Image shape is not set. Cannot compute FOV.")
        # Route through the widget so the formatted dimensions label AND the
        # derived Image Details panel both stay in sync.
        self.widget.set_image_shape(self.image_shape)

    def update_unit(self, unit: str):
        self.unit = unit
        logger.info(f"Physical unit updated: {self.unit}")
        self.dimensions_updated()

    def update_pixel_size(self, pixel_size: float):
        self.pixel_size = pixel_size
        if self.image_shape:
            self.fov = (self.image_shape[1] * self.pixel_size, self.image_shape[0] * self.pixel_size)
        self.widget.fov_input.setText(f"{self.fov[0]:.2f}, {self.fov[1]:.2f}")
        self.dimensions_updated()

    def set_pixel_size_and_unit(self, pixel_size: float, unit: str):
        """
        Set pixel size from trusted metadata without requiring the image shape
        to be initialized already.
        """
        if unit not in {"nm", "µm", "mm"}:
            raise ValueError(f"Unsupported physical unit: {unit}")

        self.pixel_size = float(pixel_size)
        self.unit = unit

        self.widget.unit_dropdown.blockSignals(True)
        self.widget.unit_dropdown.setCurrentText(unit)
        self.widget.unit_dropdown.blockSignals(False)
        # The dropdown signal is blocked above, so refresh the inline unit
        # suffixes manually to match the new unit.
        self.widget._on_unit_changed(unit)

        self.widget.pixel_size_input.blockSignals(True)
        self.widget.pixel_size_input.setText(f"{self.pixel_size:.6g}")
        self.widget.pixel_size_input.blockSignals(False)

        if self.image_shape:
            self.fov = (self.image_shape[1] * self.pixel_size, self.image_shape[0] * self.pixel_size)
            self.widget.fov_input.blockSignals(True)
            self.widget.fov_input.setText(f"{self.fov[0]:.2f}, {self.fov[1]:.2f}")
            self.widget.fov_input.blockSignals(False)
            self.dimensions_updated()

        # Refresh the read-only details even when signals were blocked above.
        self.widget.refresh_image_details()

    def dimensions_updated(self):
        self.widget.fov_change_signal.emit(self.fov, self.unit)

    def update_fov(self, fov: float or tuple[float, float]):
        # stop the widget from emitting signals
        self.widget.pixel_size_input.blockSignals(True)
        # check if user input is single float or tuple
        if isinstance(fov, float):
            width = height = fov
        elif isinstance(fov, tuple) and len(fov) == 2:
            width, height = fov
        else:
            raise ValueError("FOV must be a float or a tuple of two floats.")
        if self.image_shape is None:
            logger.warning("Image shape is not set. Cannot compute pixel size from FOV.")
            return
        self.fov = (width, height)
        self.pixel_size = width / self.image_shape[1]
        logger.info(f"Updated FOV: {self.fov}, Computed Pixel Size: {self.pixel_size}")
        self.widget.pixel_size_input.setText(f"{self.pixel_size:.4f}")
        self.dimensions_updated()
        self.widget.pixel_size_input.blockSignals(False)
        self.widget.refresh_image_details()

    def update_fov_from_str(self, fov_str: str):
        try:
            fov = tuple(map(float, fov_str.split(",")))
            self.update_fov(fov)
        except ValueError:
            logger.error("Invalid FOV format. Expected format: 'width, height'")

    def get_fov(self):
        return self.fov
