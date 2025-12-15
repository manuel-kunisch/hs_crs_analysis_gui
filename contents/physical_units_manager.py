import logging

from PyQt5 import QtCore
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QCheckBox, QGridLayout, \
    QComboBox, QSpinBox

logger = logging.getLogger(__name__)

class PhysicalUnitsWidget(QWidget):
    fov_change_signal = pyqtSignal(tuple, str)
    options_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.unit = "µm"
        self.image_shape = None  # to be set externally
        self.pixel_size = .28   # default pixel size in µm

        main_layout = QVBoxLayout(self)
        grid_layout = QGridLayout()

        # Title
        title_label = QLabel("<b>Physical Units Manager</b>")
        title_label.setAlignment(QtCore.Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # === Row 0: Unit Dropdown ===
        grid_layout.addWidget(QLabel("Unit:"), 0, 0)
        self.unit_dropdown = QComboBox()
        self.unit_dropdown.addItems(["nm", "µm", "mm"])
        self.unit_dropdown.setCurrentText(self.unit)
        self.unit_dropdown.currentTextChanged.connect(self.emit_fov_change)
        grid_layout.addWidget(self.unit_dropdown, 0, 1)

        # === Row 1: Pixel Size ===
        grid_layout.addWidget(QLabel("Pixel Size:"), 1, 0)
        self.pixel_size_input = QLineEdit()
        self.pixel_size_input.setPlaceholderText("e.g. 0.2")
        self.pixel_size_input.setText(str(self.pixel_size))
        self.pixel_size_input.textChanged.connect(self.update_fov_from_pixel_size)
        grid_layout.addWidget(self.pixel_size_input, 1, 1)

        # === Row 2: FOV ===
        grid_layout.addWidget(QLabel("Field of View:"), 2, 0)
        self.fov_input = QLineEdit()
        self.fov_input.setPlaceholderText("e.g. 512, 512")
        self.fov_input.textChanged.connect(self.update_pixel_size_from_fov)
        grid_layout.addWidget(self.fov_input, 2, 1)

        # === Row 3: Image Shape (read-only) ===
        grid_layout.addWidget(QLabel("Image Shape:"), 3, 0)
        self.image_shape_label = QLabel("not set")
        grid_layout.addWidget(self.image_shape_label, 3, 1)

        # === Row 4: Scale Bar length ===
        grid_layout.addWidget(QLabel("Scale Bar Length:"), 4, 0)
        self.scale_bar_length_spinbox = QSpinBox()
        self.scale_bar_length_spinbox.setRange(1, 1000)
        self.scale_bar_length_spinbox.setValue(50)
        grid_layout.addWidget(self.scale_bar_length_spinbox, 4, 1)

        # === Row 5: Options ===
        self.show_scalebar_checkbox = QCheckBox("Show scalebar")
        self.use_physical_units_checkbox = QCheckBox("Use physical units")
        self.show_scalebar_checkbox.stateChanged.connect(self.emit_options_changed)
        self.use_physical_units_checkbox.stateChanged.connect(self.emit_options_changed)
        grid_layout.addWidget(self.show_scalebar_checkbox, 5, 0)
        grid_layout.addWidget(self.use_physical_units_checkbox, 5, 1)

        # Final assembly
        main_layout.addLayout(grid_layout)
        self.setLayout(main_layout)

    def set_image_shape(self, shape: tuple):
        self.image_shape = shape
        self.image_shape_label.setText(str(shape))

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
            # image shape in the format (width, height)
            self.fov = (self.image_shape[1] * self.pixel_size, self.image_shape[0] * self.pixel_size)
            self.widget.fov_input.setText(f"{self.fov[0]:.2f}, {self.fov[1]:.2f}")
        else:
            logger.warning("Image shape is not set. Cannot compute FOV.")
        self.widget.image_shape_label.setText(str(self.image_shape))

    def update_unit(self, unit: str):
        self.unit = unit
        logger.info(f"Physical unit updated: {self.unit}")
        self.dimensions_updated()

    def update_pixel_size(self, pixel_size: float):
        self.pixel_size = pixel_size
        if self.image_shape:
            self.fov = tuple(dim * self.pixel_size for dim in self.image_shape)
        self.widget.fov_input.setText(f"{self.fov[0]:.2f}, {self.fov[1]:.2f}")
        self.dimensions_updated()


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

    def update_fov_from_str(self, fov_str: str):
        try:
            fov = tuple(map(float, fov_str.split(",")))
            self.update_fov(fov)
        except ValueError:
            logger.error("Invalid FOV format. Expected format: 'width, height'")

    def get_fov(self):
        return self.fov
