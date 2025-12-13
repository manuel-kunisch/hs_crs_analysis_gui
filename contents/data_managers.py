import json
import logging
import os
import sys

import numpy as np
from PyQt5 import QtWidgets, QtCore
from tifffile import imread

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
        image = imread(fpath).astype(np.uint16)     # assume 16 bit image and read in as such
        self.drag_label.setText(f"✔ Loaded: {fpath.split('/')[-1]}")
        logger.info(f"Loaded image from {fpath}")

        self._raw_image = image

        # 2) apply rolling ball BEFORE anything else sees it
        if self.rb_ctrl.cfg.enabled:
            corrected = self.rb_ctrl.apply(image)
        else:
            corrected = image

        self.image = corrected  # load as image and trigger callback attached to update_img_callback
        return self.image

    def _reprocess_from_raw(self):
        logger.info("Reprocessing image from raw data")
        if self._raw_image is None:
            # inform the user that processing is not possible
            QtWidgets.QMessageBox.warning(
                self,
                "Reprocessing Not Possible",
                "No raw image data available for reprocessing.\n\n"
                "Please rerun the image loading step (e.g. stitching).",
            )
            return
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

