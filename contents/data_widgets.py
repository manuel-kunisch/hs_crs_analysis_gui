import logging

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
    def __init__(self, img=None, init_roi_plot_widget=False):
        super().__init__()
        # widgets initialized in other methods 
        self.show_processed_image_check = None
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

        self.linescan_dock = Dock("Linescan", size=(100, 500))
        self.image_view_dock = Dock("Image", size=(500, 500))
        # Adding the docks to the DockArea()


        self.dock_area.addDock(self.image_view_dock, 'top')
        self.dock_area.addDock(self.linescan_dock, 'left', self.image_view_dock)
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

        # To hide the Linescan ROI hide the dock...

        # Disable the ROI menu
        # self.raman_raw_image_view.ui.roiBtn.hide()
        # Connect ROI selection change event
        self.raman_raw_image_view.roi.sigRegionChanged.connect(self.update_plot)
        # self.image_item = image_file  # Create a sample image

        # Setting the size of the image view
        self.image_view_dock.addWidget(self.raman_raw_image_view, 0, 0, 16, 16)

        # Initialize the ROI manager and give it access to the image view
        self.roi_manager = ROIManager(self.raman_raw_image_view)
        # add the ROI manager widgets to the dock area
        self.dock_area.addDock(self.roi_manager.roi_table_dock, "bottom")
        self.dock_area.addDock(self.roi_manager.roi_plot_dock, "left", self.roi_manager.roi_table_dock)
        self.roi_manager.processed_data_signal.connect(lambda data:
                                                       self.callback_processed_img(
                                                           self.show_processed_image_check.isChecked(), data))

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
        self.auto_play_button.setIcon(qta.icon('mdi.animation-play-outline'))
        # self.auto_play_button.setIcon(Qt.QIcon('icons/play.png'))
        # show the play icon
        self.auto_play_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.auto_play_button.clicked.connect(self.raman_raw_image_view.togglePause)
        self.auto_play_button.setCheckable(True)
        self.auto_play_button.setChecked(True)

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


    def show_average_image(self, state=True):
        if state:
            self.auto_play_button.setChecked(False)
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
        # TODO: this function is a mess. Refactor it or make it more modular
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
        # pass data to ROI manager, calculate the subtracted data etc.
        self.roi_manager.update_data(img)
        if self.show_processed_image_check.isChecked():
            self.callback_processed_img(True)
            return
        if self.show_average_image_check.isChecked():
            self.show_average_image(True)
            return
        self.display_raw_image(keep_view=False)


    def display_raw_image(self, keep_view=True):
        logger.info('Displaying raw image')
        self.raman_raw_image_view.setImage(self.image[...], keep_viewbox=keep_view)

    def display_modified_image(self, modified_data: np.ndarray = None, keep_view=False):
        """
        abstract function to display a modified image e.g. background subtracted of the current data.

        modified_data: np.ndarray of the same shape as the raw image except axis 0 (frames) can vary
        """
        current_index = self.raman_raw_image_view.currentIndex
        if modified_data is not None:
            if not modified_data.size:
                self.display_raw_image(keep_view)
            else:
                self.raman_raw_image_view.setImage(modified_data[...], keep_viewbox=keep_view)
            if modified_data.shape[0] >= current_index:
                self.raman_raw_image_view.setCurrentIndex(current_index)
            return

        # call without arguments to display the subtracted data
        if self.roi_manager.subtracted_data is not None:
            logger.info('Displaying subtracted data')
            print(self.roi_manager.subtracted_data.shape)
            self.raman_raw_image_view.setImage(self.roi_manager.subtracted_data[...], keep_viewbox=keep_view)
            if self.roi_manager.subtracted_data.shape[0] >= current_index:
                self.raman_raw_image_view.setCurrentIndex(current_index)
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
        # Plot the z_data in the new plot
        l = self.roi_avg_plot_wid.plot(self.raman_raw_image_view.wavenumber, z_data, pen=roi_pen, name=label)

        self.roi_avg_lines[roi_id] = l
        # Add any additional configurations you need
        # ...

        # Show the dock
        self.roi_plot_dock.show()

    def request_binning(self, binning_factor: int):
        # requests to bin the image and adjusts the view range accordingly
        view = self.raman_raw_image_view.getView()
        view_range = view.viewRange()
        self.request_binning_signal.emit(binning_factor)
        scale = self._binning_factor / binning_factor
        self._binning_factor = binning_factor
        view.setXRange(view_range[0][0] * scale, view_range[0][1] * scale)
        view.setYRange(view_range[1][0] * scale, view_range[1][1] * scale)

    def remove_plot_roi(self, roi_id):
        if roi_id in self.roi_avg_lines and self.roi_avg_lines[roi_id]:
            line_item = self.roi_avg_lines[roi_id]
            self.roi_avg_plot_wid.removeItem(line_item)


class WavenumberWidget(QtWidgets.QWidget):
    # Custom signal to notify about wavenumber changes
    wavenumbers_changed = QtCore.pyqtSignal(np.ndarray)
    def __init__(self, n_frames=100, **kwargs):
        super().__init__()
        self.n_frames = n_frames
        self.wavenumbers = None
        self.beam_mode = 0  # beam mode 0 is pump beam
        self.init_ui(**kwargs)

    def init_ui(self, max_width=50):
        main_layout = QtWidgets.QHBoxLayout()
        self.setLayout(main_layout)

        # Pump Beam Group
        self.pump_beam_group = QtWidgets.QGroupBox("Pump Beam")
        var_beam_layout = QtWidgets.QGridLayout(self.pump_beam_group)

        # Checkbox for min/max
        self.min_max_checkbox = QtWidgets.QCheckBox("Min/Max")
        self.min_max_checkbox.setChecked(True)  # Set initial state to checked
        var_beam_layout.addWidget(self.min_max_checkbox, 0, 0)

        # Min Wavelength Entry
        self.min_wavelength_entry = QtWidgets.QLineEdit()
        self.min_wavelength_entry.setMaximumWidth(max_width)
        self.min_wavelength_entry.setText("800")  # Default value
        var_beam_layout.addWidget(self.min_wavelength_entry, 0, 1, alignment=QtCore.Qt.AlignLeft)
        var_beam_layout.addWidget(QtWidgets.QLabel("nm"), 0, 2, alignment=QtCore.Qt.AlignLeft)

        # Max Wavelength Entry
        self.max_wavelength_entry = QtWidgets.QLineEdit()
        self.max_wavelength_entry.setMaximumWidth(max_width)
        self.max_wavelength_entry.setText("830")  # Default value
        var_beam_layout.addWidget(self.max_wavelength_entry, 0, 3, alignment=QtCore.Qt.AlignLeft)
        var_beam_layout.addWidget(QtWidgets.QLabel("nm"), 0, 4, alignment=QtCore.Qt.AlignLeft)

        # Checkbox for step size
        stepsize_checkbox = QtWidgets.QCheckBox("Stepsize")
        var_beam_layout.addWidget(stepsize_checkbox, 1, 0)

        # Stepsize Entry
        self.stepsize_entry = QtWidgets.QLineEdit()
        self.stepsize_entry.setMaximumWidth(max_width)
        self.stepsize_entry.setEnabled(False)  # Initially disabled
        var_beam_layout.addWidget(self.stepsize_entry, 1, 1, alignment=QtCore.Qt.AlignLeft)
        var_beam_layout.addWidget(QtWidgets.QLabel("nm"), 1, 2, alignment=QtCore.Qt.AlignLeft)

        main_layout.addWidget(self.pump_beam_group)

        # Button to swap pump and stokes beams
        swap_button = QtWidgets.QPushButton("↔")
        main_layout.addWidget(swap_button)

        # Stokes Beam Group
        self.stokes_beam_group = QtWidgets.QGroupBox("Stokes Beam")
        fixed_beam_layout = QtWidgets.QGridLayout(self.stokes_beam_group)

        fixed_beam_layout.setContentsMargins(0, 0, 0, 0)
        fixed_beam_layout.addWidget(QtWidgets.QLabel("λ<sub>fixed</sub>="), 0, 0)
        self.fixed_entry = QtWidgets.QLineEdit()
        self.fixed_entry.setMaximumWidth(max_width)
        self.fixed_entry.setText("1064")  # Default value
        fixed_beam_layout.addWidget(self.fixed_entry, 0, 1, alignment=QtCore.Qt.AlignLeft)
        fixed_beam_layout.addWidget(QtWidgets.QLabel("nm"), 0, 2, alignment=QtCore.Qt.AlignLeft)

        main_layout.addWidget(self.stokes_beam_group)

        # Info Box
        info_box = QtWidgets.QGroupBox("ℹ️ Info")
        info_layout = QtWidgets.QVBoxLayout(info_box)
        self.min_label = QtWidgets.QLabel("Min: ")
        self.max_label = QtWidgets.QLabel("Max: ")
        self.num_label = QtWidgets.QLabel("Frames: ")
        info_layout.addWidget(self.min_label)
        info_layout.addWidget(self.max_label)
        info_layout.addWidget(self.num_label)
        main_layout.addWidget(info_box)

        # Button group to ensure only one checkbox is selected
        button_group = QtWidgets.QButtonGroup(self)
        button_group.addButton(self.min_max_checkbox)
        button_group.addButton(stepsize_checkbox)

        # Set a custom style for disabled widgets
        self.setStyleSheet("QLineEdit:disabled { color: #808080; }")

        # Connect signals
        self.min_max_checkbox.stateChanged.connect(self.on_min_max_checked)
        stepsize_checkbox.stateChanged.connect(self.on_stepsize_checked)
        swap_button.clicked.connect(self.swap_beams)
        self.update_wavenums()

        # Connect the entries to the update_wavenums method
        self.min_wavelength_entry.textChanged.connect(self.update_wavenums)
        self.max_wavelength_entry.textChanged.connect(self.update_wavenums)
        self.stepsize_entry.textChanged.connect(self.update_wavenums)
        self.fixed_entry.textChanged.connect(self.update_wavenums)



    def on_min_max_checked(self, state):
        if state == QtCore.Qt.Checked:
            self.stepsize_entry.setEnabled(False)
        else:
            self.stepsize_entry.setEnabled(True)

    def on_stepsize_checked(self, state):
        if state == QtCore.Qt.Checked:
            self.min_wavelength_entry.setEnabled(False)
            self.max_wavelength_entry.setEnabled(False)
        else:
            self.min_wavelength_entry.setEnabled(True)
            self.max_wavelength_entry.setEnabled(True)

    def swap_beams(self):
        # Swap labels and group box titles
        pump_label = self.pump_beam_group.title()
        stokes_label = self.stokes_beam_group.title()

        self.pump_beam_group.setTitle(stokes_label)
        self.stokes_beam_group.setTitle(pump_label)

        self.beam_mode = (self.beam_mode + 1) % 2
        self.update_wavenums()
        logger.debug(self.beam_mode)


    def set_nframes(self, n_frames):
        self.n_frames = n_frames
        self.update_wavenums()

    def update_wavenums(self):
         # Get values from QLineEdit widgets
        minimum = float(self.min_wavelength_entry.text())
        fixed_wavelength = float(self.fixed_entry.text())
        channels = self.n_frames

        # Calculate fixed k
        fixed_k = 1 / (fixed_wavelength * 1e-7)
        k_fix = np.full(channels, fixed_k)

        # Check if max or stepsize mode
        if self.min_max_checkbox.isChecked():
            maximum = float(self.max_wavelength_entry.text())
            stepsize = (maximum - minimum) / channels
            self.stepsize_entry.setText(str(round(stepsize, 2)))
        else:
            stepsize = float(self.stepsize_entry.text())
            maximum = minimum + stepsize * (channels - 1)
            self.max_wavelength_entry.setText(str(round(maximum, 2)))

        # Generate wavenumbers
        lambdas = np.linspace(minimum * 1e-7, maximum * 1e-7, channels)
        k_var = np.reciprocal(lambdas)

        if not self.beam_mode:
            k_pump = k_var
            k_stokes = k_fix
        else:
            k_pump = k_fix
            k_stokes = k_var

        self.wavenumbers = np.subtract(k_pump, k_stokes)
        self.min_label.setText(f"Min: {round(min(self.wavenumbers), 2)} cm⁻¹")
        self.max_label.setText(f"Max: {round(max(self.wavenumbers), 2)} cm⁻¹")
        self.num_label.setText(f"Frames: {len(self.wavenumbers)}")
        self.wavenumbers_changed.emit(self.wavenumbers)


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

        self._binning_factor = default_binning
        self._binned_image = None   # the raw image is always available in the loader widget

    def new_image_loaded(self, image: np.ndarray):
        logger.info('New image loaded')
        # TODO: check binning before sending the image, other classes do not know and should not know about binning
        # since it is an internal operation and irrelevant for the seeds and the analysis
        if self._normalize:
            print('Normalizing image')
            print(f'{max_dtype_val=}')
            image = np.multiply(image, max_dtype_val / np.amax(image, axis=None))
            image = image.astype(dtype)
            logger.info('Image normalized')
        self._binned_image = image
        if self._binning_factor != 1:
            logger.warning('Binning factor is not 1, image will be binned')
            self._binned_image = self.bin_image_3d(image, self._binning_factor)
        self.loader_widget.physical_units_manager.update_image_dimensions(image.shape[1:])
        self.update_image_callback(self._binned_image)

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
        if self._binning_factor == 1:
            self._binned_image = self.loader_widget.image
            self.update_image_callback(self._binned_image)
        else:
            # apply binning to all image frames
            self._binned_image = self.bin_image_3d(self.loader_widget.image, self._binning_factor)
            self.update_image_callback(self._binned_image)


    def get_image(self):
        """Return the binned image (widgets only see binned data)."""
        return self._binned_image

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
        print(f'bin_image_3d: {image.shape = }')
        print(frame.shape for frame in image)
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