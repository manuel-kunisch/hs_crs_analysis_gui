import logging

import sys
import numpy as np
import pyqtgraph as pg
import qtawesome as qta
from PyQt5 import QtWidgets, QtCore, Qt
from pyqtgraph.dockarea import DockArea, Dock

from composite_image import dtype, max_dtype_val
from contents.data_managers import ImageLoader
from contents.hs_image_view import RamanImageView
from contents.roi_manager_pg import ROIManager

logger = logging.getLogger('Data Manager')


class DataWidget(QtWidgets.QWidget):
    """
    Main class to manage raw data handling
    """
    request_binning_signal = QtCore.pyqtSignal(int)
    def __init__(self, img=None, init_roi_plot_widget=False, color_manager=None):
        super().__init__()
        # widgets initialized in other methods 
        self.show_processed_image_check = None
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
        self.roi_avg_plot_wid.setLabel('bottom', text='Wavenumbers')
        self.roi_avg_plot_wid.setLabel('left', text='Intensity [a.u.]')
        self.roi_avg_lines = dict()

    def init_dock_area(self):
        self.dock_area_widget = QtWidgets.QWidget(self)  # Placeholder widget to contain the DockArea
        self.layout.addWidget(self.dock_area_widget)

        self.dock_area_layout = QtWidgets.QVBoxLayout(self.dock_area_widget)  # Layout for the placeholder widget
        self.dock_area = DockArea()
        self.dock_area_layout.addWidget(self.dock_area)

        self.linescan_dock = Dock("Linescan", size=(50, 500))
        self.image_view_dock = Dock("Image", size=(500, 500))
        self.image_view_dock.setStretch(500)
        # Adding the docks to the DockArea()


        self.dock_area.addDock(self.image_view_dock, 'top')
        self.dock_area.addDock(self.linescan_dock, 'left', self.image_view_dock)
        # give image view dock more space

        # linescan_dock.hideTitleBar()
        line_plot_widget = pg.PlotWidget(title="Linsecan")
        self.linescan_dock.addWidget(line_plot_widget)

        # Add Plot item to show axis labels
        plot = pg.PlotItem(title='ImView')
        plot.setTitle()
        plot.setLabel(axis='left', text='Y-axis')
        plot.setLabel(axis='bottom', text='X-axis')
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
        self.roi_manager.processed_data_signal.connect(lambda data:
                                                       self.callback_processed_img(
                                                           self.show_processed_image_check.isChecked(), data))
        self.set_linescan_visible(False)

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
        self.roi_manager.spectral_units = unit
        self.roi_manager.roi_plotter.set_spectral_units(unit)
        self.raman_raw_image_view.set_spectral_units(unit)

    def set_spectral_axis_labels(self, labels):
        self.raman_raw_image_view.set_axis_labels(labels)

    def init_toolbar(self):
        self.lut_combo_box = QtWidgets.QComboBox(self)
        self.lut_combo_box.addItems(['grey', 'thermal', 'flame', 'yellowy', 'bipolar', 'spectrum', 'cyclic', 'greyclip',
                                     'viridis', 'inferno', 'plasma', 'magma', "red", "green", "blue", "yellow",
                                     "orange", "purple", "pink", "magenta", "custom"])
        self.lut_combo_box.setCurrentIndex(2)
        self.lut_combo_box.currentIndexChanged.connect(self.update_lut)

        """
        toolbar = QtWidgets.QToolBar(self)
        toolbar.addWidget(QtWidgets.QLabel("Image LUT"))
        toolbar.addWidget(self.lut_combo_box)
        toolbar.setMaximumHeight(30)  # Set a maximum height for the toolbar
        """
        autoscale_button = QtWidgets.QPushButton("Autoscale")
        autoscale_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        autoscale_button.setIcon(Qt.QIcon('icons/autoscale.png'))
        autoscale_button.clicked.connect(self.autoscale_image)
        #toolbar.addWidget(autoscale_button)


        self.auto_play_button = QtWidgets.QPushButton(self)
        self.auto_play_button.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        self.auto_play_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.auto_play_button.clicked.connect(
            lambda checked: self.raman_raw_image_view.set_playing(checked)
        )
        self.auto_play_button.setCheckable(True)
        self.auto_play_button.setChecked(False)

        self.auto_play_speed_spinbox = QtWidgets.QDoubleSpinBox(self)
        self.auto_play_speed_spinbox.setRange(0.5, 60.0)
        self.auto_play_speed_spinbox.setSingleStep(0.5)
        self.auto_play_speed_spinbox.setDecimals(1)
        self.auto_play_speed_spinbox.setValue(self.raman_raw_image_view.fps)
        self.auto_play_speed_spinbox.setSuffix(" fps")
        self.auto_play_speed_spinbox.valueChanged.connect(self.raman_raw_image_view.set_playback_fps)
        self.raman_raw_image_view.playback_state_changed.connect(self.sync_auto_play_button)

        self.show_processed_image_check = QtWidgets.QCheckBox("Display Processed Image")
        self.show_processed_image_check.clicked.connect(self.callback_processed_img)
        # toolbar.addWidget(self.show_processed_image_check)

        self.show_average_image_check = QtWidgets.QCheckBox("Display Average Image")
        self.show_average_image_check.clicked.connect(lambda state: self.show_average_image(state))
        # toolbar.addWidget(self.show_average_image_check)

        self.binning_combo_box = QtWidgets.QComboBox(self)
        self.binning_combo_box.addItems(['1', '2', '4', '8', '16'])
        self.binning_combo_box.setCurrentText(str(self._binning_factor))
        self.binning_combo_box.currentTextChanged.connect(lambda bin_str: self.request_binning(int(bin_str)))
        # toolbar.addWidget(self.binning_combo_box)

        self.show_average_image_check.clicked.connect(lambda state: self.show_processed_image_check.setChecked(False) if state else None)
        self.show_processed_image_check.clicked.connect(lambda state:self.show_average_image_check.setChecked(False) if state else None)

        # toolbar.addWidget(self.auto_play_button)

        first_row_layout = QtWidgets.QHBoxLayout()
        lut_widget = QtWidgets.QWidget()
        lut_widget.setContentsMargins(0, 0, 0, 0)
        lut_layout = QtWidgets.QHBoxLayout()
        lut_layout.setContentsMargins(0, 0, 0, 0)
        lut_widget.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        lut_widget.setLayout(lut_layout)
        lut_label = QtWidgets.QLabel("Image LUT")
        lut_label.setPixmap(qta.icon('mdi.palette').pixmap(16, 16))
        lut_layout.addWidget(lut_label)
        lut_layout.addWidget(self.lut_combo_box)
        first_row_layout.addWidget(lut_widget)
        first_row_layout.addWidget(autoscale_button)
        first_row_layout.addWidget(self.auto_play_button)
        first_row_layout.addWidget(QtWidgets.QLabel("Autoplay"))
        first_row_layout.addWidget(self.auto_play_speed_spinbox)
        first_row_widget = QtWidgets.QWidget()
        first_row_widget.setMaximumHeight(50)
        first_row_widget.setLayout(first_row_layout)

        second_row_layout = QtWidgets.QHBoxLayout()
        second_row_widget = QtWidgets.QWidget()
        second_row_widget.setMaximumHeight(50)
        second_row_widget.setLayout(second_row_layout)
        second_row_layout.addWidget(self.show_processed_image_check)
        second_row_layout.addWidget(self.show_average_image_check)
        binning_widget = QtWidgets.QWidget()
        binning_layout = QtWidgets.QHBoxLayout()
        binning_layout.setContentsMargins(0, 0, 0, 0)
        binning_widget.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        binning_widget.setLayout(binning_layout)
        binning_layout.addWidget(QtWidgets.QLabel("Binning"))
        binning_layout.addWidget(self.binning_combo_box)
        second_row_layout.addWidget(binning_widget)
        # reduce vertical padding
        margins = first_row_layout.getContentsMargins()
        margins = (*margins[:-1], 0)
        first_row_widget.layout().setContentsMargins(*margins)

        self.image_view_dock.addWidget(first_row_widget, row=16, col=0, colspan=16)
        self.image_view_dock.addWidget(second_row_widget, row=17, col=0, colspan=16)
        self.sync_auto_play_button(self.raman_raw_image_view.is_playing())

    def sync_auto_play_button(self, is_playing: bool):
        self.auto_play_button.blockSignals(True)
        self.auto_play_button.setChecked(is_playing)
        icon_type = QtWidgets.QStyle.SP_MediaPause if is_playing else QtWidgets.QStyle.SP_MediaPlay
        self.auto_play_button.setIcon(self.style().standardIcon(icon_type))
        self.auto_play_button.setToolTip("Pause autoplay" if is_playing else "Start autoplay")
        self.auto_play_button.blockSignals(False)


    def show_average_image(self, state=True):
        if state:
            self.raman_raw_image_view.stopAutoPlay()
            avg = np.expand_dims(np.mean(self.image, axis=0), axis=0)
            # fill the axis 0 with the average image with the same shape as the original image so we can quickly
            # switch between the average and the original image and keep the current frame index
            avg = np.repeat(avg, self.image.shape[0], axis=0)
            self.raman_raw_image_view.setImage(avg, keep_viewbox=True)
            self.raman_raw_image_view.getView().setTitle('Average Image')
            # TODO: block the user to move the timeline in the imageview
            # self.raman_raw_image_view.hideTimeLine()
        else:
            self.display_raw_image()

    # create new subtracted data
    def callback_processed_img(self, state: bool, data: np.ndarray=None, label_text: str = None):
        # Keep raw, processed, and averaged display paths synchronized in one place.
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
            if self.show_average_image_check.isChecked():
                self.show_average_image(True)
                return
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

    def update_img(self, img: np.ndarray):
        self.image = img
        logger.info("Updating ROI manager data")
        self.roi_manager.update_data(img)
        self.raman_raw_image_view.request_single_autoplay_cycle(reset_to_start=True)
        # pass data to ROI manager, calculate the subtracted data etc.
        if self.show_processed_image_check.isChecked():
            self.callback_processed_img(True)
            return
        if self.show_average_image_check.isChecked():
            self.show_average_image(True)
            return
        self.display_raw_image(keep_view=False)

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
    Helper window to manually enter or load wavenumbers from a file.
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
            self, "Open Wavenumber File", "", "Text Files (*.txt *.csv *.dat);;All Files (*)"
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

        self.setStyleSheet("""
        QGroupBox {
            font-weight: 600;
            border: 1px solid rgba(180,180,180,0.35);
            border-radius: 8px;
            margin-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 6px;
        }
        QLabel.unit { opacity: 0.75; }
        QAbstractSpinBox:disabled { color: #808080; }
        QCheckBox { padding: 2px 4px; }
        QToolButton { padding: 8px; border-radius: 10px; }
        """)

        # --- Top Bar: Source Selector ---
        top_bar = QtWidgets.QHBoxLayout()
        top_bar.setContentsMargins(10, 5, 10, 0)
        top_bar.addWidget(QtWidgets.QLabel("Source:"))

        self.source_combo = QtWidgets.QComboBox()
        self.source_combo.addItems(["Calculated (Pump/Stokes)", "Custom / Manual"])
        self.source_combo.currentIndexChanged.connect(self.on_source_changed)
        top_bar.addWidget(self.source_combo)

        self.custom_unit_combo = QtWidgets.QComboBox()
        self.custom_unit_combo.addItems([ "cm⁻¹", "nm"])
        self.custom_unit_combo.setFixedWidth(60)
        self.custom_unit_combo.currentIndexChanged.connect(self.update_wavenums)

        top_bar.addSpacing(15)

        top_bar.addWidget(QtWidgets.QLabel("Unit:"))
        top_bar.addWidget(self.custom_unit_combo)
        top_bar.addStretch()

        main_layout.addLayout(top_bar)

        # --- Stacked Widget for Modes ---
        self.stack = QtWidgets.QStackedWidget()
        main_layout.addWidget(self.stack)

        # PAGE 1: Calculated (Existing Logic)
        self.page_calc = QtWidgets.QWidget()
        calc_layout = QtWidgets.QHBoxLayout(self.page_calc)
        calc_layout.setContentsMargins(10, 8, 10, 8)
        calc_layout.setSpacing(10)

        self.pump_beam_group = QtWidgets.QGroupBox("Pump Beam")
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
        swap_button.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_BrowserReload))
        swap_button.setToolTip("Swap which beam is tuned (Pump ↔ Stokes)")
        swap_button.clicked.connect(self.swap_beams)
        calc_layout.addWidget(swap_button)

        # Stokes Group
        self.stokes_beam_group = QtWidgets.QGroupBox("Stokes Beam")
        fixed_beam_layout = QtWidgets.QGridLayout(self.stokes_beam_group)
        fixed_beam_layout.setHorizontalSpacing(10)
        fixed_beam_layout.setVerticalSpacing(6)

        fixed_label = QtWidgets.QLabel("λ<sub>fixed</sub> =")
        fixed_label.setTextFormat(QtCore.Qt.RichText)
        fixed_beam_layout.addWidget(fixed_label, 0, 0)

        self.fixed_entry = _NumericEntry(value=1064.0, decimals=2, width=max_width)
        fixed_beam_layout.addWidget(self.fixed_entry, 0, 1)
        fixed_beam_layout.addWidget(QtWidgets.QLabel("nm"), 0, 2)

        self.source_combo.currentTextChanged.connect(lambda unit: self.fixed_entry.setEnabled(False) if unit == "nm" else self.fixed_entry.setEnabled(True))
        calc_layout.addWidget(self.stokes_beam_group)

        # Add Page 1 to stack
        self.stack.addWidget(self.page_calc)

        # PAGE 2: Custom (New)
        self.page_custom = QtWidgets.QWidget()
        custom_layout = QtWidgets.QHBoxLayout(self.page_custom)
        custom_layout.setContentsMargins(10, 8, 10, 8)

        custom_group = QtWidgets.QGroupBox("Custom Wavenumbers")
        cg_layout = QtWidgets.QHBoxLayout(custom_group)

        self.btn_load_custom = QtWidgets.QPushButton("Edit / Load Wavenumbers...")
        self.btn_load_custom.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_FileDialogDetailedView))
        self.btn_load_custom.clicked.connect(self.open_custom_dialog)

        self.custom_status_label = QtWidgets.QLabel("No data loaded.")
        self.custom_status_label.setStyleSheet("color: gray; font-style: italic;")

        cg_layout.addWidget(self.btn_load_custom)
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

        # --- Connections ---
        self.min_max_checkbox.stateChanged.connect(self.on_min_max_checked)
        self.stepsize_checkbox.stateChanged.connect(self.on_stepsize_checked)

        self.min_wavelength_entry.textChanged.connect(self.update_wavenums)
        self.max_wavelength_entry.textChanged.connect(self.update_wavenums)
        self.stepsize_entry.textChanged.connect(self.update_wavenums)
        self.fixed_entry.textChanged.connect(self.update_wavenums)

    def on_source_changed(self, index):
        self.stack.setCurrentIndex(index)
        self.update_wavenums()

    def open_custom_dialog(self):
        current_data = self.custom_axis_labels if self.custom_axis_labels is not None else self.custom_wavenumbers
        dlg = WavenumberLoadDialog(target_length=self.n_frames, current_data=current_data, parent=self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.custom_wavenumbers = dlg.loaded_data
            self.custom_axis_labels = dlg.loaded_labels
            self.update_wavenums()

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

        unit_str = self.custom_unit_combo.currentText()

        if is_custom:
            if self.custom_wavenumbers is None:
                self.wavenumbers = np.arange(channels, dtype=np.float32)
                self.custom_axis_labels = None
                self.custom_status_label.setText("Default: Indices")
                # Fallback labels
                self.min_label.setText(f"Min: {float(np.min(self.wavenumbers)):.0f} (idx)")
                self.max_label.setText(f"Max: {float(np.max(self.wavenumbers)):.0f} (idx)")
                self.warn_label.setVisible(False)
                # Emit indices, but technically unit_str might be misleading here if not set
                # but usually user loads data immediately.
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
                        self.min_label.setText(f"Min: {float(np.min(self.wavenumbers)):.2f} {unit_str}")
                        self.max_label.setText(f"Max: {float(np.max(self.wavenumbers)):.2f} {unit_str}")

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
                self.fixed_entry.setEnabled(False)
                stepsize = float(self.stepsize_entry.value())
                maximum = minimum + stepsize * (channels - 1)
                with QtCore.QSignalBlocker(self.max_wavelength_entry):
                    self.max_wavelength_entry.setValue(maximum)

            # 2. Calculate Axis
            # Check if we are doing Raman (Fixed enabled) or Hyperspectral (Fixed disabled)
            if unit_str != "nm":
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
            self.min_label.setText(f"Min: {float(np.min(self.wavenumbers)):.2f} {unit_str}")
            self.max_label.setText(f"Max: {float(np.max(self.wavenumbers)):.2f} {unit_str}")

        self.num_label.setText(f"Frames: {self.n_frames}")
        self.wavenumbers_changed.emit(self.wavenumbers)

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
                unit_index = self.custom_unit_combo.findText(str(spectral_unit))
                if unit_index >= 0:
                    self.custom_unit_combo.setCurrentIndex(unit_index)

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
            unit_index = self.custom_unit_combo.findText(str(spectral_unit))
            if unit_index >= 0:
                self.custom_unit_combo.setCurrentIndex(unit_index)

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
            "unit": str(self.custom_unit_combo.currentText()),  # "cm⁻¹" or "nm"
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

        unit = str(state.get("unit", "cm⁻¹"))
        uidx = self.custom_unit_combo.findText(unit)
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

        self.loader_dock = Dock("Data", size=(300, 300))
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
        self._suspend_custom_axis_warning = False
        self._current_slice_index = 0
        self._slice_axis_label = "Slice"

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
        self.update_image_callback(self._display_image)

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

    def new_image_loaded(self, image: np.ndarray):
        logger.info('New image loaded')

        # --- normalize (if requested) ---
        if self._normalize:
            logger.info('Normalizing loaded image to %s dynamic range.', max_dtype_val)
            image = np.multiply(image, max_dtype_val / np.amax(image, axis=None))
            image = image.astype(dtype)
            logger.info('Image normalized')

        # check if image contains zeros or nans that are invalid for further processing
        if np.isnan(image).any() or np.isinf(image).any() or np.any(image == 0):
            logger.warning('Loaded image contains NaN or Inf values, which may cause issues in further processing.')
            image = np.nan_to_num(image, nan=0.0, posinf=0.0, neginf=0.0)
            image = image.astype(np.float32) # ensure float type for epsilon replacement, float32 is well enough
            image[image==0] = sys.float_info.epsilon    # replace zeros with small value to avoid issues in log scaling etc.
            logger.warning('NaN and Inf values replaced with 0.0, zeros replaced with small epsilon value.')
            logger.warning(f"Image dtype after replacement: {image.dtype}")

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

        if not self._suspend_custom_axis_warning:
            self.wavenumber_widget.warn_and_switch_from_custom_source(parent=self)

        if wavelength_meta is not None:
            logger.info("Applying wavelength metadata to WavenumberWidget")
            self.wavenumber_widget.apply_wavelength_meta(wavelength_meta, n_frames)
        else:
            # still keep the widget in sync with the frame count
            self.wavenumber_widget.set_nframes(n_frames)

        # push image to the rest of the pipeline
        self.update_image_callback(self._display_image)

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
