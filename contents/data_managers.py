import json
import logging
import os
import sys

import numpy as np
from PyQt5 import QtWidgets, QtCore
from tifffile import TiffFile, imread

from contents import stitch_functions as stitching
from contents.physical_units_manager import PhysicalUnitsManager
from contents.rolling_ball_correction import RollingBallCorrectionWidget, RollingBallCorrectionController
from contents.stitch_manager import StitchManager

logger = logging.getLogger('Data Manager')


class ImageLoader(QtWidgets.QWidget):
    def __init__(self, update_img_callback: callable, parent: QtWidgets.QWidget):
        """
        Widget for loading images and performing basic operations on them
        Args:
            update_img_callback: the callback function that is executed when the image is loaded
            parent:
        """
        super().__init__(parent)
        self.current_path = None
        self._raw_image = None  # store the raw image for reprocessing, e.g., rolling ball. None if not applicable
        self.wavelength_meta = None
        self.update_img_callback = update_img_callback
        self._image = None
        self.init_ui()


    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Create a QTabWidget to manage tabs
        tab_widget = QtWidgets.QTabWidget(self)

        # Create the main tab
        main_tab = QtWidgets.QWidget()
        self.main_grid_layout = QtWidgets.QGridLayout(main_tab)
        data_h_layout = QtWidgets.QHBoxLayout()

        # Create drag & drop label
        self.drag_label = QtWidgets.QLabel("📂 Drag & Drop TIFF Files Here")
        #self.drag_label.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignHCenter)
        self.drag_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        # self.drag_label.setFixedHeight(60)
        # self.drag_label.setMaximumWidth(700)
        # add linebreaks to the label if the text is too long
        self.drag_label.setWordWrap(True)
        # Set style for the drag label
        self.drag_label.setStyleSheet("""
            QLabel {
                border: 1px dashed #888;
                border-radius: 6px;
                padding: 8px;
                background: #2b2b2b;
                color: #ddd;
            }
        """)

        # Enable drag & drop
        self.drag_label.setAcceptDrops(True)
        # Connect drag & drop events
        self.drag_label.dragEnterEvent = self.drag_enter_event
        self.drag_label.dropEvent = self.drop_event

        # add ability to click the label which opens a file dialog
        self.drag_label.mousePressEvent = self.load_image_from_file_dialog

        # data_h_layout.addWidget(QtWidgets.QLabel("Data Path"), alignment=QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        data_h_layout.addWidget(self.drag_label)

        path_widget = QtWidgets.QWidget()
        path_widget.setLayout(data_h_layout)
        self.main_grid_layout.addWidget(path_widget, 0, 2)

        # add preset save buttons as dummies
        self.save_preset_button = QtWidgets.QPushButton('Save Preset')
        self.load_preset_button = QtWidgets.QPushButton('Load Preset')
        # add the preset buttons to the loader widget ui
        self.main_grid_layout.addWidget(self.save_preset_button, 0, 0)
        self.main_grid_layout.addWidget(self.load_preset_button, 0, 1)


        # tab_widget.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        # Add tab to widget
        tab_widget.addTab(main_tab, "Single HS Image")

        # Add the tab widget to the main layout
        layout.addWidget(tab_widget)

        # Create the stitching tab
        stitching_tab = QtWidgets.QWidget()
        stitching_layout = QtWidgets.QVBoxLayout(stitching_tab)

        # Add the stitching tab to the tab widget
        tab_widget.addTab(stitching_tab, "HS Image Stitching")
        # Initialize and add the StitchManager widget to the stitching tab
        self.stitch_manager = StitchManager()
        self.stitch_manager.init_ui()
        stitching_layout.addWidget(self.stitch_manager.stitch_data_widget)
        self.stitch_manager.stitchedImageChanged.connect(self.load_image)

        # Add rolling ball correction tab
        rb_tab = QtWidgets.QWidget()
        tab_widget.addTab(rb_tab, "Rolling Ball Correction")
        rb_layout = QtWidgets.QVBoxLayout(rb_tab)
        self.rb_ctrl = RollingBallCorrectionController()
        self.rb_widget = RollingBallCorrectionWidget(self.rb_ctrl)
        self.rb_ctrl.configChanged.connect(self._reprocess_from_raw)
        self.rb_ctrl.referenceChanged.connect(self._reprocess_from_raw)
        rb_layout.addWidget(self.rb_widget)
        # Provide StitchManager with a per-run, thread-safe tile preprocessor
        self.stitch_manager.set_tile_preprocess_factory(self._rb_tile_preprocess_factory)

        # Add physical units tab
        self.physical_units_manager = PhysicalUnitsManager()
        physical_units_tab = self.physical_units_manager.widget
        self.physical_units_manager.widget.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        tab_widget.addTab(physical_units_tab, "Physical Units")

    def _rb_tile_preprocess_factory(self):
        """
        Return a thread-safe callable to preprocess tiles, or None.
        For stitching, you typically want REFERENCE mode only (to avoid seams).
        """
        if not self.rb_ctrl.cfg.enabled:
            return None

        # Strong recommendation: only allow reference mode for stitching
        if self.rb_ctrl.cfg.mode != "reference" or self.rb_ctrl.reference_model() is None:
            logger.warning("Rolling-ball enabled but not in reference mode; not applying to tiles to avoid seams.")
            return None

        snap = self.rb_ctrl.snapshot()  # thread-safe frozen config/model
        return snap.apply

    def load_image_from_text(self):
        # Get the text from the text edit widget
        file_path = self.text_edit.toPlainText().strip()

        # Check if the entered text is a valid TIFF file path
        if file_path.lower().endswith('.tif') or file_path.lower().endswith('.tiff'):
            # Load the image using the loader class
            image_data = self.load_tiff(file_path)

            # If stitching is enabled, perform stitching
            # if self.stitch_check.isChecked():
            #     image_data = self.stitch_images(image_data)

    def load_image_from_file_dialog(self, *args):
        # Open a file dialog to select a TIFF file
        file_dialog = QtWidgets.QFileDialog()
        file_path, _ = file_dialog.getOpenFileName(self, "Open TIFF File", "", "TIFF Files (*.tif *.tiff)")

        # Check if a file was selected
        if file_path:
            # Load the image using the loader class
            image_data = self.load_tiff(file_path)

    def drag_enter_event(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def drop_event(self, event):
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            file_path = mime_data.urls()[0].toLocalFile()
            if file_path.lower().endswith(('.tif', '.tiff')):
                self.load_tiff(file_path)
            else:
                self.drag_label.setText("❌ Invalid File Type")


    def load_tiff(self, fpath):
        # check if a wavelength json file is in the directory
        self.try_load_wavelength_json(os.path.dirname(fpath))
        image = self._prepare_loaded_tiff_dtype(imread(fpath), fpath)
        self._apply_tiff_pixel_size_metadata(fpath)
        self.drag_label.setText(f"✔ Loaded: {fpath.split('/')[-1]}")
        logger.info(f"Loaded image from {fpath}")

        self.current_path = fpath

        self._raw_image = image

        # 2) apply rolling ball BEFORE anything else sees it
        if self.rb_ctrl.cfg.enabled:
            if image.ndim == 4:
                logger.warning("Rolling-ball correction does not support 4D stacks yet. Loading the raw 4D image instead.")
                QtWidgets.QMessageBox.information(
                    self,
                    "Rolling-ball skipped for 4D data",
                    "Rolling-ball correction currently supports 2D and 3D data only.\n\n"
                    "The 4D stack was loaded without rolling-ball correction.",
                )
                corrected = image
            else:
                corrected = self.rb_ctrl.apply(image)
        else:
            corrected = image

        self.image = corrected  # load as image and trigger callback attached to update_img_callback
        return self.image

    @staticmethod
    def _prepare_loaded_tiff_dtype(image: np.ndarray, fpath: str) -> np.ndarray:
        """
        Convert TIFF input to the GUI's current 16-bit working range without
        silently wrapping 32-bit or float images.
        """
        image = np.asarray(image)
        if image.dtype == np.uint16:
            return image

        original_dtype = image.dtype
        is_float_input = np.issubdtype(original_dtype, np.floating)
        if np.issubdtype(original_dtype, np.complexfloating):
            logger.warning("Loaded complex TIFF %s. Using absolute values before conversion to uint16.", fpath)
            image = np.abs(image)
            is_float_input = True

        working = np.asarray(image, dtype=np.float32)
        finite_mask = np.isfinite(working)
        if not np.any(finite_mask):
            logger.warning("Loaded TIFF %s contains no finite values. Replacing image with zeros.", fpath)
            return np.zeros(working.shape, dtype=np.uint16)

        finite_values = working[finite_mask]
        min_val = float(np.min(finite_values))
        max_val = float(np.max(finite_values))

        if min_val < 0:
            logger.warning(
                "Loaded TIFF %s has negative values (min %.6g). Shifting to non-negative before uint16 conversion.",
                fpath,
                min_val,
            )
            working = working - min_val
            max_val -= min_val
            min_val = 0.0

        working = np.nan_to_num(working, nan=0.0, posinf=max_val, neginf=0.0)

        if max_val <= 0:
            logger.warning("Loaded TIFF %s has zero dynamic range after conversion. Returning zeros.", fpath)
            return np.zeros(working.shape, dtype=np.uint16)

        if is_float_input:
            logger.info(
                "Loaded %s TIFF %s. Scaling floating-point values [%.6g, %.6g] to 0..65535.",
                original_dtype,
                fpath,
                min_val,
                max_val,
            )
            scaled = working * (np.iinfo(np.uint16).max / max_val)
            return np.clip(scaled, 0, np.iinfo(np.uint16).max).astype(np.uint16)

        if max_val <= np.iinfo(np.uint16).max and min_val >= 0:
            logger.info("Loaded %s TIFF %s; casting safely to uint16.", original_dtype, fpath)
            return np.clip(working, 0, np.iinfo(np.uint16).max).astype(np.uint16)

        logger.warning(
            "Loaded %s TIFF %s with values outside uint16 range [%.6g, %.6g]. "
            "Scaling to 0..65535 to avoid overflow/wrap-around.",
            original_dtype,
            fpath,
            min_val,
            max_val,
        )
        scaled = working * (np.iinfo(np.uint16).max / max_val)
        return np.clip(scaled, 0, np.iinfo(np.uint16).max).astype(np.uint16)

    def _apply_tiff_pixel_size_metadata(self, fpath: str):
        pixel_size_meta = self._read_tiff_pixel_size_metadata(fpath)
        if pixel_size_meta is None:
            return

        pixel_size, unit = pixel_size_meta
        self.physical_units_manager.set_pixel_size_and_unit(pixel_size, unit)
        logger.info("Applied TIFF/ImageJ pixel size metadata: %.6g %s/px", pixel_size, unit)

    @staticmethod
    def _read_tiff_pixel_size_metadata(fpath: str):
        """
        Read TIFF/ImageJ pixel size metadata from the first page of the TIFF file, if available and valid.
         - Supports ImageJ metadata "unit" for physical unit and "XResolution"/"YResolution" tags for pixel size.
         - Returns (pixel_size, unit) if valid metadata is found, or None if metadata is missing/invalid.
         - Logs warnings for unsupported units, invalid resolutions, or anisotropic pixel sizes.
         - Catches and logs any exceptions during metadata reading without crashing the application.
        """
        try:
            with TiffFile(fpath) as tif:
                imagej_meta = tif.imagej_metadata or {}
                unit = ImageLoader._normalize_imagej_unit(imagej_meta.get("unit"))
                if unit is None:
                    return None

                page = tif.pages[0]
                x_resolution = ImageLoader._resolution_tag_to_float(page.tags.get("XResolution"))
                y_resolution = ImageLoader._resolution_tag_to_float(page.tags.get("YResolution"))
                if x_resolution is None or x_resolution <= 0:
                    return None

                pixel_size_x = 1.0 / x_resolution
                pixel_size_y = 1.0 / y_resolution if y_resolution and y_resolution > 0 else pixel_size_x
                if not np.isclose(pixel_size_x, pixel_size_y, rtol=1e-3, atol=1e-12):
                    logger.warning(
                        "TIFF metadata has anisotropic pixel sizes (x=%.6g %s, y=%.6g %s). "
                        "The GUI supports one pixel size, using x.",
                        pixel_size_x, unit, pixel_size_y, unit,
                    )
                return pixel_size_x, unit
        except Exception:
            logger.debug("Could not read TIFF/ImageJ pixel size metadata from %s", fpath, exc_info=True)
            return None

    @staticmethod
    def _resolution_tag_to_float(tag):
        if tag is None:
            return None
        value = tag.value
        if isinstance(value, tuple) and len(value) == 2:
            numerator, denominator = value
            if denominator == 0:
                return None
            return float(numerator) / float(denominator)
        return float(value)

    @staticmethod
    def _normalize_imagej_unit(unit):
        if unit is None:
            return None
        if isinstance(unit, bytes):
            unit = unit.decode("latin-1", errors="ignore")
        normalized = str(unit).strip().lower().replace("\\u00b5", "µ").replace("μ", "µ")
        if normalized in {"µm", "um", "micron", "microns", "micrometer", "micrometers", "micrometre", "micrometres"}:
            return "µm"
        if normalized in {"nm", "nanometer", "nanometers", "nanometre", "nanometres"}:
            return "nm"
        if normalized in {"mm", "millimeter", "millimeters", "millimetre", "millimetres"}:
            return "mm"
        return None

    def _reprocess_from_raw(self):
        logger.info("Reprocessing image from raw data")
        if self.image is None:
            logger.warning("No image loaded; cannot reprocess")
            return
        if self._raw_image is None:
            # inform the user that processing is not possible
            QtWidgets.QMessageBox.warning(
                self,
                "Reprocessing Not Possible",
                "No raw image data available for reprocessing.\n\n"
                "Please rerun the image loading step (e.g. stitching).",
            )
            return
        if self.rb_ctrl.cfg.enabled and self._raw_image.ndim == 4:
            QtWidgets.QMessageBox.information(
                self,
                "Rolling-ball skipped for 4D data",
                "Rolling-ball correction currently supports 2D and 3D data only.\n\n"
                "The 4D stack was reloaded without rolling-ball correction.",
            )
            img = self._raw_image
        else:
            img = self.rb_ctrl.apply(self._raw_image) if self.rb_ctrl.cfg.enabled else self._raw_image
        self.image = img    # trigger callback attached to update_img_callback

    def try_load_wavelength_json(self, directory: str):
        self.wavelength_meta = None
        meta_path = os.path.join(directory, "wavelength.json")

        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as fh:
                    meta = json.load(fh)

                # basic validation + normalization
                custom_values = meta.get("custom_values", meta.get("custom_points"))
                custom_labels = meta.get("custom_labels", meta.get("labels"))
                spectral_unit = meta.get("spectral_unit", meta.get("unit"))

                if spectral_unit is not None:
                    spectral_unit = str(spectral_unit).strip().lower()
                    if spectral_unit in {"nm", "nanometer", "nanometers", "wavelength"}:
                        spectral_unit = "nm"
                    elif spectral_unit in {"cm-1", "cm^-1", "1/cm", "cm⁻¹", "wavenumber", "raman"}:
                        spectral_unit = "cm⁻¹"
                    else:
                        raise ValueError("spectral_unit must be 'nm' or 'cm⁻¹'")

                if custom_values is not None or custom_labels is not None:
                    if custom_values is not None:
                        custom_values = [float(value) for value in custom_values]
                    if custom_labels is not None:
                        custom_labels = [str(value) for value in custom_labels]
                    if custom_values is not None and custom_labels is not None and len(custom_values) != len(custom_labels):
                        raise ValueError("custom_values and custom_labels must have the same length")
                    if custom_values is None and custom_labels is None:
                        raise ValueError("Custom wavelength metadata requires custom_values and/or custom_labels")

                    self.wavelength_meta = {
                        "custom_values": custom_values,
                        "custom_labels": custom_labels,
                        "spectral_unit": spectral_unit,
                    }
                else:
                    tuned_beam = meta.get("tuned_beam", "").lower()
                    if tuned_beam not in {"stokes", "pump"}:
                        raise ValueError("tuned_beam must be 'stokes' or 'pump'")

                    fixed_beam_nm = float(meta["fixed_beam_nm"])  # required
                    tuned_min_nm = meta.get("tuned_min_nm")
                    tuned_max_nm = meta.get("tuned_max_nm")
                    tuned_step_nm = meta.get("tuned_step_nm")

                    if tuned_min_nm is None and tuned_max_nm is None and tuned_step_nm is None:
                        raise ValueError(
                            "Need at least tuned_min_nm + tuned_max_nm OR tuned_step_nm"
                        )

                    self.wavelength_meta = {
                        "tuned_beam": tuned_beam,
                        "fixed_beam_nm": fixed_beam_nm,
                        "tuned_min_nm": float(tuned_min_nm) if tuned_min_nm is not None else None,
                        "tuned_max_nm": float(tuned_max_nm) if tuned_max_nm is not None else None,
                        "tuned_step_nm": float(tuned_step_nm) if tuned_step_nm is not None else None,
                        "spectral_unit": spectral_unit,
                    }

                logger.info(f"Loaded wavelength metadata from {meta_path}")
                print(self.wavelength_meta)
            except Exception:
                logger.exception(f"Failed to read wavelength metadata from {meta_path}")
        else:
            logger.info(f"No wavelength.json found in {directory}")


    def load_image(self, image_data):
        # load image from external source (e.g., stitching manager)
        self._raw_image = None  # prevent reprocessing from raw
        self.image = image_data
        return image_data

    @property
    def image(self):
        return self._image

    @image.setter
    def image(self, new_image):
        self._image = new_image
        if self.update_img_callback:
            self.update_img_callback(new_image)

