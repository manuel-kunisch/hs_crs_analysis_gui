import logging
from datetime import datetime
from typing import Tuple, Callable

import numpy as np
import pyqtgraph as pg
import tifffile
from PyQt5 import QtGui, QtCore  # Import the necessary modules
from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QLabel
from skimage.filters.rank import minimum

from composite_image import CompositeImageViewWidget
from contents.custom_pyqt_objects import ImageViewYX
from contents.multivariate_analyzer import MultivariateAnalyzer
from contents.roi_manager_pg import ROIManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('Hyperspectral Analysis')
logger.setLevel(logging.INFO)

debug = True

class AnalysisWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(int)
    finished = QtCore.pyqtSignal(str)

    def __init__(self, mv_analyzer):
        super().__init__()
        self.mv_analyzer = mv_analyzer

    def run(self):
        # Check which radio button is selected
        analysis_method = self.mv_analyzer.analysis_method
        self.mv_analyzer.start_analysis()
        self.finished.emit(analysis_method)

"""
# Threading option 2: use thread pool in case of multiple threads
class AnalysisWorker(QtCore.QRunnable):
    analysis_complete = QtCore.pyqtSignal(str)
    def __init__(self, mv_analyzer):
        super().__init__()
        self.mv_analyzer = mv_analyzer

    def run(self):
        # Run the analysis
        self.mv_analyzer.PCA()  # Or any other analysis method you want
        # self.analysis_complete.emit('PCA')
"""

class AnalysisManager(QtCore.QObject):
    # signals are always declared at class levels!
    # to properly function, inheriting from QObject is required with signals and slots in PyQt.
    analysis_data_changed = QtCore.pyqtSignal(np.ndarray, np.ndarray)
    resonance_settings_changed = QtCore.pyqtSignal(np.ndarray)
    # default raman resonances
    default_resonances = [[2850, 20], [2930, 15], [3000, 15], [3060, 15], [3120, 15], [3180, 15]]
    def __init__(self, init_widgets=True, data=None, roi_manager:ROIManager|None=None):
        super().__init__()
        self.seed_window: QtWidgets.QMainWindow or None = None
        self.z3D_data = None
        self.wavenumbers = None
        self.roi_manager:ROIManager|None = roi_manager
        self.roi_manager.new_roi_signal.connect(self.highlight_resonance_component)
        # Main widget instantiated in the init_ui method
        self.analysis_widget = None
        self.mv_analyzer = MultivariateAnalyzer(data, 3, self.wavenumbers)

        # set up thread for analysis
        self.thread_analysis = QtCore.QThread()
        self.worker = AnalysisWorker(self.mv_analyzer)
        self.worker.moveToThread(self.thread_analysis)
        # Connect pyqt signals
        self.thread_analysis.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread_analysis.quit)
        # Connect the finished function to the worker
        self.worker.finished.connect(lambda: self.analysis_completed(self.mv_analyzer.analysis_method))
        self.thread_analysis.finished.connect(
            lambda: self.analyze_button.setEnabled(True)
        )
        self.thread_analysis.finished.connect(
            lambda: self.analyze_button.setText('Analyze')
        )


        if init_widgets:
            self.init_ui()


    def init_ui(self):
        # Create the main widget
        self.analysis_widget = QtWidgets.QWidget()
        master_ui_layout = QtWidgets.QGridLayout(self.analysis_widget)

        # Create a group box for radio buttons
        analysis_group_box = QtWidgets.QGroupBox("Analysis Method")
        analysis_grid = QtWidgets.QGridLayout()
        analysis_group_box.setLayout(analysis_grid)

        # Add Radio Buttons for choosing between PCA and NNMF
        self.pca_radio = QtWidgets.QRadioButton("PCA")
        self.nnmf_radio = QtWidgets.QRadioButton("NNMF")
        self.pca_radio.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)
        # Connect radio button signals to update analysis method
        self.pca_radio.clicked.connect(lambda: self.update_analysis_method("PCA"))
        self.nnmf_radio.clicked.connect(lambda: self.update_analysis_method("NNMF"))
        self.nnmf_radio.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)
        self.nnmf_radio.setChecked(True)  # Default to PCA

        # Add SpinBox for number of components
        spin_box_label = QtWidgets.QLabel("# Components:")
        self.num_components_spinbox = QtWidgets.QSpinBox(minimum=1, maximum=100, value=self.mv_analyzer.get_n_components(), singleStep=1)
        self.num_components_spinbox.setToolTip("Set the number of components for PCA/NNMF analysis")
        self.num_components_spinbox.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.num_components_spinbox.valueChanged.connect(
            lambda n: self.mv_analyzer.update_components(n)
        )
        spin_box_label.setToolTip("Set the number of components for PCA/NNMF analysis")
        spin_box_label.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        components_hbox = QtWidgets.QHBoxLayout()
        components_hbox.addWidget(spin_box_label)
        components_hbox.addWidget(self.num_components_spinbox, alignment=QtCore.Qt.AlignLeft)

        custom_init_hbox = QtWidgets.QHBoxLayout()
        custom_init_check = QtWidgets.QCheckBox()
        custom_init_check.setChecked(True)
        custom_init_label = QtWidgets.QLabel("Custom Initialization")
        custom_init_label.setToolTip("Use custom initialization for NNMF based on spectral and spatial seed information")
        custom_init_label.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        custom_init_check.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        custom_init_hbox.addWidget(custom_init_label)
        custom_init_hbox.addWidget(custom_init_check, alignment=QtCore.Qt.AlignLeft)
        # pass the current state of the checkbox to the analyzer object
        custom_init_check.stateChanged.connect(self.mv_analyzer.set_custom_nnmf_init)
        self.mv_analyzer.set_custom_nnmf_init(custom_init_check.isChecked())


        analysis_grid.addWidget(self.pca_radio, 0, 0, 2, 1)
        analysis_grid.addWidget(self.nnmf_radio, 2, 0, 2, 1)
        components_widget = QtWidgets.QWidget()
        components_widget.setLayout(components_hbox)
        components_widget.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)
        custom_init_widget = QtWidgets.QWidget()
        custom_init_widget.setLayout(custom_init_hbox)
        analysis_grid.addWidget(components_widget, 0, 2, 2, 1)
        analysis_grid.addWidget(custom_init_widget, 2, 2, 2, 1)
        # Add the group box to the vertical layout
        master_ui_layout.addWidget(analysis_group_box, 0, 0)

        # Create a horizontal layout for table and analyze button
        table_and_button_layout = QtWidgets.QGridLayout()

        # Create a table to show files
        self.resonance_table = QtWidgets.QTableWidget()
        res_settings_options = ["Component", "Wavenumber", "Width", "Pixel Threshold", "# Seed Pixels", "Use subtracted data"]
        self.res_settings_widget_columns = {option: i for i, option in enumerate(res_settings_options)}
        self.resonance_table.setColumnCount(len(res_settings_options))  # Assuming one column for file paths
        self.resonance_table.setHorizontalHeaderLabels(res_settings_options)
        self.resonance_table.setAcceptDrops(True)

        # bind shortcut on del press to remove the selected row
        del_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+D"), self.resonance_table)
        del_shortcut.activated.connect(lambda: self.remove_res_settings(self.resonance_table.currentRow()))
        # add hint that pressing "Ctrl+D" will delete the selected row with small font
        del_hint_label = QLabel('Press "Ctrl+D" to delete selected row/setting')
        del_hint_label.setStyleSheet("font-size: 4pt")
        del_hint_label.setWordWrap(True)
        del_hint_label.setMaximumWidth(70)
        table_and_button_layout.addWidget(del_hint_label, 5, 4, alignment=QtCore.Qt.AlignRight)

        spectral_button_widget = QtWidgets.QWidget()
        spectral_button_layout = QtWidgets.QVBoxLayout()
        spectral_button_widget.setLayout(spectral_button_layout)
        spectral_button_widget.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)

        # Add the table to the horizontal layout
        table_and_button_layout.addWidget(self.resonance_table, 0, 0, 5, 5, alignment=QtCore.Qt.AlignTop)
        # Add button to add resonance settings
        add_button = QtWidgets.QPushButton("Add Resonance Settings")
        add_button.clicked.connect(self.add_resonance_settings)
        spectral_button_layout.addWidget(add_button)
        # table_and_button_layout.addWidget(spectral_button_widget, 0, 5, alignment=QtCore.Qt.AlignTop )


        # Add Analyze button
        self.analyze_button = QtWidgets.QPushButton("Analyze")
        self.analyze_button.clicked.connect(self.analyze_data)
        # table_and_button_layout.addWidget(self.analyze_button, 2, 5, alignment=QtCore.Qt.AlignVCenter)
        analysis_grid.addWidget(self.analyze_button, 1, 1, 2, 1)

        # highlight the analyze button
        self.analyze_button.setStyleSheet("background-color: darkkhaki")
        self.analyze_button.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)
        # W seed handling
        w_seed_label = QLabel('W Seed Settings:')
        table_and_button_layout.addWidget(w_seed_label, 5, 0, alignment=QtCore.Qt.AlignRight)
        # Add button to check W seeds
        check_W_seeds_button = QtWidgets.QPushButton("Check W Seeds (from H only)")
        check_W_seeds_button.clicked.connect(self.show_W_seeds)
        spectral_button_layout.addWidget(check_W_seeds_button)

        # add button to test the spectral info handling
        test_spectral_info_button = QtWidgets.QPushButton('Test spectral info')
        # table_and_button_layout.addWidget(test_spectral_info_button, 4, 5, alignment=QtCore.Qt.AlignVCenter)
        test_spectral_info_button.clicked.connect(lambda: self.make_W_seeds_from_spectral_info(debug_mode=True))
        test_spectral_info_button.setStyleSheet("background-color: gray")
        spectral_button_layout.addWidget(test_spectral_info_button)

        test_seed_setup_button = QtWidgets.QPushButton('Test seed setup')
        # table_and_button_layout.addWidget(test_seed_setup_button, 3, 5, alignment=QtCore.Qt.AlignVCenter)
        test_seed_setup_button.clicked.connect(lambda state: self.seed_debug(show_seeds=True))
        test_seed_setup_button.setStyleSheet("background-color: gray")
        spectral_button_layout.addWidget(test_spectral_info_button)

        analysis_grid.addWidget(spectral_button_widget, 0, 3, 4, 1)

        # Create a QButtonGroup for exclusivity
        W_seed_group = QtWidgets.QButtonGroup(self)  # Set 'self' as parent to keep group linked to UI
        W_seed_group.setExclusive(True)  # Ensures only one can be selected

        # Create radio buttons
        h_weight_seed_check = QtWidgets.QCheckBox("H Weighted")
        h_weight_seed_check.setChecked(True)
        h_weight_seed_check.stateChanged.connect(
            lambda checked: setattr(self.mv_analyzer, 'H_weighted_W_seed', checked))
        self.mv_analyzer.H_weighted_W_seed = h_weight_seed_check.isChecked()
        avg_w_seed_radio = QtWidgets.QRadioButton("Average Image")
        empty_w_seed_radio = QtWidgets.QRadioButton("Empty")


        # Add to the button group
        # W_seed_group.addButton(h_weight_seed_check)
        W_seed_group.addButton(avg_w_seed_radio)
        W_seed_group.addButton(empty_w_seed_radio)

        h_weight_seed_check.setChecked(True)
        table_and_button_layout.addWidget(h_weight_seed_check, 5, 1, alignment=QtCore.Qt.AlignLeft)
        table_and_button_layout.addWidget(avg_w_seed_radio, 5, 2, alignment=QtCore.Qt.AlignLeft)
        table_and_button_layout.addWidget(empty_w_seed_radio, 5, 3, alignment=QtCore.Qt.AlignLeft)
        # Connect radio button state changes to the set_W_seed_mode method
        avg_w_seed_radio.toggled.connect(
            lambda checked: self.mv_analyzer.set_W_seed_mode("None") if checked else None)
        # h_weight_seed_check.toggled.connect(
        #    lambda checked: self.mv_analyzer.set_W_seed_mode("H weights") if checked else None)
        empty_w_seed_radio.toggled.connect(
            lambda checked: self.mv_analyzer.set_W_seed_mode("Empty") if checked else None)
        self.mv_analyzer.set_W_seed_mode("None")
        avg_w_seed_radio.setChecked(True)
        # Add the horizontal layout to the vertical layout
        master_ui_layout.addLayout(table_and_button_layout, 1, 0)

        # Set the main layout of the widget
        self.analysis_widget.setLayout(master_ui_layout)

    """
    def analyze_data(self):
        logger.info(f"{datetime.now()}: Analysis started")
        print(self.mv_analyzer.analysis_method)
        self.mv_analyzer.start_analysis()
        self.analysis_data_changed.emit(*self.get_analysis_data())
    """

    def analyze_data(self):
        """
        Function to start the correct analysis method based on the selected radio button.

        The function will start the analysis in a separate thread to keep the GUI responsive.
        Returns:

        """
        if self.nnmf_radio.isChecked() and self.mv_analyzer.custom_nnmf_init:
            self.seed_debug(show_seeds=True)
        self.analyze_button.setEnabled(False)
        self.analyze_button.setText('Analysis in Progress')
        self.thread_analysis.start()
        logger.info(f"{'-' * 50}")
        logger.info(f'{datetime.now()}: Analysis started')
        logger.info(f"{'-' * 50}")

    def seed_debug(self, show_seeds=True):
        self.reload_H_seeds_from_rois()     # reset all existing seeds and reload ROIs
        seed_W, seed_H, seed_pixels = self.make_W_seeds_from_spectral_info(debug_mode=False) # create W seeds from spectral info and pass to analyzer
        logger.info(f'{"-" * 50}')
        logger.info("W seeds:")
        # first try to set up from the spectral data (weighted by H if exists) and then from the H seeds from the ROIs if no info is available,
        # otherwise the W seed is randomly initialized
        # TODO: random W initialization can be overhauled to be more sophisticated
        self.mv_analyzer.set_up_W_seed(skip_spectral_info=True, fill_H_seed=False)  # fill the W seed matrix

        logger.info(f'{"-"*50}')
        logger.info("H seeds:")
        # W seeds are set
        # set up H seeds that are not yet ready from W seeds
        for i, H in enumerate(self.mv_analyzer.seed_H):
            if not H.all() and seed_H[i].all():
                logger.info(f'H{i} seed not set and is initialized with seed pixel spectra')
                self.mv_analyzer.set_H_seed(i, seed_H[i, :])
        # remainining components that are not given by rois and spectral info are randomly initialized
        self.mv_analyzer.set_up_H_seed()

        if not show_seeds:
            return

        seed_W_3d = self.mv_analyzer.seed_W.reshape(self.mv_analyzer.raw_data_3d.shape[1],
                                                    self.mv_analyzer.raw_data_3d.shape[2], -1)
        """
        if self.seed_window is not None:
            self.seed_window.close()
        """
        self.seed_window = SeedWindow(seed_W_3d, self.mv_analyzer.seed_H, self.wavenumbers, seed_pixels, self.roi_manager.get_color)


    def reload_H_seeds_from_rois(self) -> None:
        seeds_list = self.roi_manager.get_roi_mean_curves()
        # TODO: Pass the seeds to the analyzer
        self.mv_analyzer.reset_seeds()
        for i, seed_dict in enumerate(seeds_list):
            component_number = int(seed_dict['resonance'].strip('Component ')) - 1
            flag_bgd = self.roi_manager.roi_table.cellWidget(i, self.roi_manager.widget_columns['Background']).checkState()
            if component_number >= self.mv_analyzer.get_n_components():
                logger.error(
                    f'Component number {component_number} is out of bounds for {self.mv_analyzer.get_n_components()} components and is ignored.')
                # pop up warning box
                QtWidgets.QMessageBox.warning(self.analysis_widget, 'Warning',
                                              f'Component number {component_number} is out of bounds for'
                                              f' {self.mv_analyzer.get_n_components()} components and is ignored.')
                continue
            self.mv_analyzer.set_H_seed(component_number, seed_dict['H'], flag_background=flag_bgd)

    def analysis_completed(self, analysis_method):
        logger.info(f"{datetime.now()}: {analysis_method} finished ")
        # Emit signal to the application
        # TODO: run in new thread, plotting takes time!
        self.analysis_data_changed.emit(*self.get_analysis_data())

    def update_analysis_method(self, method):
        self.mv_analyzer.analysis_method = method

    def get_analysis_data(self) -> (np.ndarray, np.ndarray):
        if self.pca_radio.isChecked():
            analysis_method = "PCA"
            return self.mv_analyzer.PCs, self.mv_analyzer.pca_2DX
        elif self.nnmf_radio.isChecked():
            analysis_method = "NNMF"
            return self.mv_analyzer.fixed_H, self.mv_analyzer.fixed_W_2D

    def add_resonance_settings(self):
        # Add a row to the table
        row_position = self.resonance_table.rowCount()
        self.resonance_table.insertRow(row_position)

        # Set the number in column 1
        item = QtWidgets.QComboBox()
        item.addItems([f"Component {i+1}" for i in range(9)])
        item.setCurrentIndex(row_position%9)
        self.resonance_table.setCellWidget(row_position, 0, item)
        item.currentIndexChanged.connect(lambda: self.callback_res_settings(self.resonance_table.currentRow()))

        # Add text fields from column 2 to 4
        for column in range(1, len(self.res_settings_widget_columns) -1):
            item = QtWidgets.QDoubleSpinBox()
            item.setMaximum(1e7)
            self.resonance_table.setCellWidget(row_position, column, item)

        # Add checkbox for the last column
        item = QtWidgets.QCheckBox()
        item.setChecked(True)
        self.resonance_table.setCellWidget(row_position, 5, item)

        # adjust default values
        widget_eps: QtWidgets.QDoubleSpinBox = self.resonance_table.cellWidget(row_position, self.res_settings_widget_columns['Pixel Threshold'])
        widget_eps.setValue(0.7)
        widget_eps.valueChanged.connect(lambda x: self.adjust_npixels)

        widget_np: QtWidgets.QDoubleSpinBox = self.resonance_table.cellWidget(row_position, self.res_settings_widget_columns['# Seed Pixels'])
        widget_np.setValue(1000)
        widget_np.valueChanged.connect(lambda x: self.adjust_eps)


        default_wavenumber = self.default_resonances[row_position%len(self.default_resonances)][0]
        if np.amin(self.wavenumbers) <= default_wavenumber <= np.amax(self.wavenumbers):
            self.resonance_table.cellWidget(row_position, self.res_settings_widget_columns['Wavenumber']).setValue((self.default_resonances[row_position%len(self.default_resonances)][0]))
            self.resonance_table.cellWidget(row_position, self.res_settings_widget_columns['Width']).setValue((self.default_resonances[row_position%len(self.default_resonances)][1]))

        for cell in range(1, len(self.res_settings_widget_columns)-1):
            item = self.resonance_table.cellWidget(row_position, cell)
            item.valueChanged.connect(lambda: self.callback_res_settings(self.resonance_table.currentRow()))
        self.callback_res_settings(row_position)
        # if not row_position:
        #     self.resonance_table.resizeColumnsToContents()

    def remove_res_settings(self, row):
        self.resonance_table.removeRow(row)
        self.callback_res_settings(row)

    def adjust_npixels(self):
        current_row = self.resonance_table.currentRow()
        widget_eps: QtWidgets.QDoubleSpinBox = self.resonance_table.cellWidget(current_row, self.res_settings_widget_columns['Pixel Threshold'])
        widget_np: QtWidgets.QDoubleSpinBox = self.resonance_table.cellWidget(current_row, self.res_settings_widget_columns['# Seed Pixels'])
        # get the epsilon value
        eps = widget_eps.value()
        # get the corresponding number of pixels above the threshold
        frames = self.mv_analyzer.return_resonance_indices(self.get_spectral_info_row(current_row))
        # get the max intensity of these frames and find the amount of pixels above the threshold
        max_i = np.max(self.mv_analyzer.raw_data_3d[frames, :, :], axis=None)
        n_pixels = np.sum(np.max(self.mv_analyzer.raw_data_3d[frames, :, :], axis=0) > max_i*eps)
        widget_np.setValue(n_pixels)

    def adjust_eps(self):
        print('adjusting eps')
        current_row = self.resonance_table.currentRow()
        widget_eps: QtWidgets.QDoubleSpinBox = self.resonance_table.cellWidget(current_row, self.res_settings_widget_columns['Pixel Threshold'])
        widget_np: QtWidgets.QDoubleSpinBox = self.resonance_table.cellWidget(current_row, self.res_settings_widget_columns['# Seed Pixels'])
        # get the number of pixels
        n_pixels = widget_np.value()
        # get the corresponding number of pixels above the threshold
        frames = self.mv_analyzer.return_resonance_indices(self.get_spectral_info_row(current_row))
        # get the max intensity of these frames and find the amount of pixels above the threshold
        max_i = np.max(self.mv_analyzer.raw_data_3d[frames, :, :], axis=None)
        eps = np.min(max_i)/max_i[n_pixels]
        widget_eps.setValue(eps)

    def callback_res_settings(self, current_row):
        logger.info(f'Resonance callback triggered')
        self.update_spectral_info()
        logger.info(f'new spectral info in the mv_analyzer:{self.mv_analyzer.spectral_info}')
        # self.highlight_resonance_row(current_row)
        # TODO: lazy variant, rehighlight all resonances when something changes, hard to keep track of all changes
        self.highlight_all_resonances()

    def highlight_all_resonances(self):
        self.roi_manager.roi_plotter.remove_all_highlights(delete_spectral_info=True)
        for row in range(self.resonance_table.rowCount()):
            self.highlight_resonance_row(row)

    def highlight_resonance_component(self, component: int):
        logger.info('Checking if resonance info exists')
        row = self.get_row_number(component)
        if row is None:
            logger.info(f'No resonance info found for component {component}')
            return
        self.highlight_resonance_row(row)

    def highlight_resonance_row(self, row_table):
        # highlight the new resonance region in the ROI plot
        info = self.get_spectral_info_row(row_table)
        if not info:
            return
        spectral_range = np.array([info['Wavenumber'] - info['Width'], info['Wavenumber'] + info['Width']])
        self.roi_manager.highlight_component_region(spectral_range, self.get_component_number(row_table))

    def show_W_seeds(self):
        """ debug function to check the W seeds from the spectral data"""
        self.reload_H_seeds_from_rois()
        if not self.mv_analyzer._W_prepared:
            self.mv_analyzer.estimate_W_seed_matrix_from_H()
        # open a new floating composite_image with the W seeds in a pyqtgraph image view
        W_seed_3d = self.mv_analyzer.seed_W.reshape(self.mv_analyzer.raw_data_3d.shape[1],
                                                    self.mv_analyzer.raw_data_3d.shape[2], -1)
        self.seed_W_view = self.make_W_seed_view(W_seed_3d)
        self.seed_W_view.show()

    def make_W_seed_view(self, W_seed_3d, seed_pixels: dict = None, plot_all_seeds: bool = False):
        seed_W_view = ImageViewYX()
        seed_W_view.setImage(W_seed_3d)

        def update_color_channel(cmp: int):
            pen_color = self.roi_manager.get_color(cmp)
            cmap = pg.ColorMap(pos=np.linspace(0.0, 1.0, 2), color=np.array([[0, 0, 0, 255], pen_color]))
            seed_W_view.setColorMap(cmap)

        seed_W_view.ui.roiPlot.setMinimumSize(QtCore.QSize(0, 60))
        axis = seed_W_view.ui.roiPlot.getAxis('bottom')
        axis.setLabel("W component")
        axis.setTicks([[(i, str(i)) for i in range(int(W_seed_3d.shape[2]))]])

        update_color_channel(0)
        seed_W_view.timeLine.sigPositionChanged.connect(
            lambda line: update_color_channel(seed_W_view.currentIndex)
        )

        # Track the current scatter plot
        current_scatter = [None]  # Use a list to keep a mutable reference

        def add_scatter(pixels: dict, component: int):
            if current_scatter[0] is not None:
                seed_W_view.removeItem(current_scatter[0])  # Remove previous scatter

            if component not in pixels:
                return

            pixels = pixels[component]
            vis_pixel_pos = np.array(pixels) + 0.5
            positions = np.array([[vis_pixel_pos[1][i], vis_pixel_pos[0][i]] for i in range(len(pixels[0]))])

            scatter = pg.ScatterPlotItem(
                pos=positions,
                size=8,
                brush=pg.mkBrush(self.roi_manager.get_color(component)),
                symbol='+',
                pen=pg.mkPen(self.roi_manager.get_color(component), width=1)
            )
            seed_W_view.addItem(scatter)
            current_scatter[0] = scatter  # Update reference to new scatter

        if seed_pixels is not None:
            if plot_all_seeds:
                for component in seed_pixels.keys():
                    add_scatter(seed_pixels, component)
            else:
                add_scatter(seed_pixels, seed_W_view.currentIndex)
                seed_W_view.timeLine.sigPositionChanged.connect(
                    lambda: add_scatter(seed_pixels, seed_W_view.currentIndex)
                )

        return seed_W_view

    def update_spectral_info(self):
        logger.info('Spectral Info Updated')
        self.mv_analyzer.spectral_info = self.get_all_spectral_info()
        # plot the new spectral info in the ROI plot


    def get_spectral_info(self, component: int) -> dict[str, float | int]:
        # iterate over all table entries and filter out the spectral information for the selected component
        info = dict()
        for row in range(self.resonance_table.rowCount()):
            # find the correct row index
            current_component: str = self.resonance_table.cellWidget(row, self.res_settings_widget_columns['Component']).currentText()
            # remove everything left from the last space to receive the component number
            current_component = self.get_component_number(row)
            if int(current_component) == component:
                info = self.get_spectral_info_row(row)
        return info

    def get_spectral_infos(self, component: int) -> list[dict[str, float | int]]:
        """ convenience method to get all spectral information for a specific component """
        infos = []
        for row in range(self.resonance_table.rowCount()):
            if self.get_component_number(row) == component:
                infos.append(self.get_spectral_info_row(row))
        return infos

    def get_all_spectral_info(self) -> list[dict[str, float | int]]:
        """ convenience method to get all spectral information from the table, only returns valid entries """
        info = []
        for row in range(self.resonance_table.rowCount()):
            info.append(self.get_spectral_info_row(row))
        return info

    def get_component_number(self, row: int):
        """
        Note: Displayed component 1 is internally represented as 0 etc.
        """
        component_combobox: QtWidgets.QComboBox = self.resonance_table.cellWidget(row, self.res_settings_widget_columns['Component'])
        if component_combobox is None:
            return None
        # get only text after the last space
        return int(component_combobox.currentText().split(' ')[-1]) - 1

    def get_row_number(self, component: int) -> int | None:
        # find the row number of the component in the table
        for row in range(self.resonance_table.rowCount()):
            if self.get_component_number(row) == component:
                return row
        return None

    def get_spectral_info_row(self, row: int) -> dict[str, float | int]:
        """
        main method to extract the spectral information from the table

        Returns a dictionary with the spectral information for the selected row. If the row is incomplete, an empty dictionary is returned.
        """
        cnumber = self.get_component_number(row)

        def get_value(column_name: str, cast_type: type, default=None):
            """Helper function to extract and convert a cell value."""
            widget: QtWidgets.QDoubleSpinBox = self.resonance_table.cellWidget(row, self.res_settings_widget_columns[column_name])
            if widget:
                try:
                    return cast_type(widget.value())
                except ValueError:
                    pass
            return default

        # Extract values using the helper function
        wnumber = get_value('Wavenumber', float)
        width = get_value('Width', float)
        thres = get_value('Pixel Threshold', float)
        n_pixels = get_value('# Seed Pixels', int)

        # Validate required values
        if wnumber is None or width is None or (thres is None and n_pixels is None):
            return {}

        dict_entry = {
            'Component': cnumber,
            'Wavenumber': wnumber,
            'Width': width,
            'Pixel Threshold': thres,
            '# Seed Pixels': n_pixels
        }
        return dict_entry

    def make_W_seeds_from_spectral_info(self, make_H_seeds=True, debug_mode=True) -> Tuple[np.ndarray, np.ndarray, dict[int, tuple[np.ndarray, np.ndarray]]]:
        """ testing function if the spectal info is correctly interpreted """
        # get the spectral information from the table
        # convert the wavenumber to indices
        seed_W = np.zeros((self.mv_analyzer.data_2d.shape[0], self.mv_analyzer.get_n_components()))
        # iterate over all components and create the W seeds
        for i in range(self.mv_analyzer.get_n_components()):
            info_dict_list = self.get_spectral_infos(i)
            if not info_dict_list:
                logger.warning(f'No spectral information found for component {i}')
                continue
            res_indices = np.array([], dtype=int)
            for info_dict in info_dict_list:
                # check if a seed info exists from the roi manager and ask for confirmation
                res_indices = np.append(res_indices, self.mv_analyzer.return_resonance_indices(info_dict))
            weights = np.ones(res_indices.size)
            if self.roi_manager.is_component_defined(i):
                # check if the roi manager has a seed for the current component and ask if the spectral info should be used
                if QtWidgets.QMessageBox.question(self.analysis_widget, 'Seed Overwrite',
                                                  f"Component {i} has a defined ROI seed. Do you want to use the spectral as additional weighting for the W seed?",
                                                  QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No) == QtWidgets.QMessageBox.Yes:
                    weights = self.roi_manager.get_component_seed(i)[res_indices]
            logger.info(f'Creating W seed from available spectral info {info_dict_list}')
            logger.info(f'Component {i}: {res_indices=}')
            # create a seed for the current component
            row = self.get_row_number(i)
            data = self.mv_analyzer.data_2d
            if self.resonance_table.cellWidget(row, self.res_settings_widget_columns['Use subtracted data']).isChecked():
                logger.info(f'Using subtracted data for component W{i} estimation')
                data = self.mv_analyzer.resonance_data_2d
            res_slices = data[..., res_indices]
            seed = np.average(res_slices, axis=1, weights=weights)
            seed_W[..., i] = seed
        self.mv_analyzer.seed_W = seed_W
        print('Created W seed from spectral info. Debug mode:', debug_mode)
        # new dimension is yxc
        seed_W_3d = seed_W.reshape(self.z3D_data.shape[1], self.z3D_data.shape[2], -1)

        seed_pixel_dict = self.find_seed_pixels(find_for_all=True, debug_mode=False)

        # estimate seed_H from the seed pixel spectra
        seed_H = np.zeros((seed_W.shape[1], self.wavenumbers.size))
        if make_H_seeds:
            for i, pixels in seed_pixel_dict.items():
                row = self.get_row_number(i)
                if self.resonance_table.cellWidget(row, self.res_settings_widget_columns['Use subtracted data']).isChecked():
                    # use the subtracted data for the seed H
                    spectra = self.mv_analyzer.resonance_data_zyx[:, pixels[0], pixels[1]]
                    logger.info(f'Using subtracted data for component H{i} estimation')
                else:
                    spectra = self.z3D_data[:, pixels[0], pixels[1]]
                mean_spectrum = np.mean(spectra, axis=1)
                seed_H[i, :] = mean_spectrum


        if debug_mode:
            self.seed_window = QtWidgets.QMainWindow()
            self.seed_window.setWindowTitle('Seeds from spectral info')
            print('Showing W seeds')
            seed_W_view = ImageViewYX()
            seed_W_view.setImage(seed_W_3d)

            # seed pixels
            for component, pixels in seed_pixel_dict.items():
                # add +.5 to the pixel positions to center the marker in the pixel
                vis_pixel_pos = np.array(pixels) + 0.5
                # rearrange the pixel positions to the correct format of array([[y1, x1], [y2, x2], ...])
                positions = np.array([[vis_pixel_pos[1][i], vis_pixel_pos[0][i]] for i in range(len(pixels[0]))])
                scatter = pg.ScatterPlotItem(
                    pos=positions,
                    size=8,
                    brush=pg.mkBrush(self.roi_manager.get_color(component)),
                    symbol='+',  # Change this to 'o', 'x', 'star', etc.
                    pen=pg.mkPen(self.roi_manager.get_color(component), width=1)  # White outline
                )
                seed_W_view.addItem(scatter)

            seed_h_plot = pg.PlotWidget()
            for i in range(seed_H.shape[0]):
                seed_h_plot.plot(self.wavenumbers, seed_H[i, :], pen=pg.mkPen(self.roi_manager.get_color(i)),
                                 name=f'Component {i}')
            seed_h_plot.setLabel('left', 'Intensity')
            seed_h_plot.setLabel('bottom', 'Wavenumber [1/cm]')
            seed_h_plot.addLegend()

            layout = QtWidgets.QHBoxLayout()
            layout.addWidget(seed_W_view)
            layout.addWidget(seed_h_plot)
            widget = QtWidgets.QWidget()
            widget.setLayout(layout)
            self.seed_window.setCentralWidget(widget)
            self.seed_window.show()

        return seed_W, seed_H, seed_pixel_dict
        # idea: thresholding for W seeds

    def find_seed_pixels(self, find_for_all: bool = False, unique_seed_pixels=True, debug_mode: bool =debug) -> dict[int, tuple[np.ndarray, np.ndarray]]:
        """
        Find seed pixels for the components in the spectral info table
        Args:
            unique_seed_pixels (bool): if True, add the seed pixels to the excluded pixels
            find_for_all (bool): if True, find seed pixels for all components, otherwise only for components without a defined ROI
            debug_mode (bool): if True, show the seed pixels in a new composite_image

        Returns:
            Key is the component number, value is a tuple of numpy arrays with the y and x coordinates of the seed pixels.
            The pixel positions are in the format (y, x) as numpy arrays so they can be directly used for indexing
        """
        print('Finding seed pixels for all components. Debug mode:', debug_mode)
        # find seed pixels for the components in the spectral info table

        # take the rois from roi manager and check if some backgound was defined, exclude this from the seed pixels
        # if no background was defined, use the whole image
        background_components = self.roi_manager.get_background_components()

        excluded_pixels = self.roi_manager.get_components_pixels(background_components)
        # get the current position of the ROIs associated with the background components
        # for each spectral info entry where no ROI is defined, find the seed pixels
        seed_pixels_for_component = dict()

        for i in range(self.mv_analyzer.get_n_components()):
            if not self.roi_manager.is_component_defined(i) or find_for_all:
                # find seed pixels for the current component
                frames = np.array([], dtype=int)
                spectral_info_list = self.get_spectral_infos(i)
                if not spectral_info_list:
                    logger.warning(f'No spectral information found for component {i}')
                    continue
                for spectral_info in spectral_info_list:
                    frames = np.append(frames, self.mv_analyzer.return_resonance_indices(spectral_info))
                # find the highest pixel values in the frames and exclude the background pixels
                logger.info(f'Finding seed pixels for component {i} in frames {frames}')
                frames_of_interest = self.z3D_data[frames, ...].astype(float)
                # exclude the background pixels by setting them to zero
                if excluded_pixels.size:
                    frames_of_interest[:, excluded_pixels[0], excluded_pixels[1]] = 1e-10

                # maximum intensity projection of the frames
                max_intensity_frame = np.amax(frames_of_interest, axis=0)

                # find the highest pixel values in the frames up to max*epsilon or N_pixels are found as defined in the table
                max_pixel_val = np.amax(frames_of_interest)

                N_pixels = spectral_info['# Seed Pixels']
                epsilon = spectral_info['Pixel Threshold']

                use_epsilon = True
                if N_pixels is not None and epsilon is not None:
                    aw = QtWidgets.QMessageBox.question(self.analysis_widget, 'Seed parameter',
                                                                  'Would you like to use the pixel threshold?'
                                                                  ' Otherwise the N_pixel entry is used')
                    if aw == QtWidgets.QMessageBox.No:
                        use_epsilon = False

                if epsilon is None:
                    use_epsilon = False

                if use_epsilon:
                    seed_pixels = np.where(max_intensity_frame > max_pixel_val * epsilon)
                else:
                    # find the N_pixels highest pixel values
                    sorted_frame = np.argsort(max_intensity_frame, axis=None)
                    seed_pixels = np.unravel_index(sorted_frame[-N_pixels:], max_intensity_frame.shape)

                seed_pixels_for_component[i] = seed_pixels
                if unique_seed_pixels:
                    # remove the seed pixels from the excluded pixels
                    excluded_pixels = np.concatenate((excluded_pixels, np.array(seed_pixels)), axis=1)
                    logger.warning(f'Added seed pixels for component {i} to the excluded pixels.\nNew shape: {excluded_pixels.shape}')
                # TODO: more sophisiticated approach with applying gauss fits etc. to find the seed pixels
        return seed_pixels_for_component

    def set_H_seeds_from_spectral_info(self):
        # check if the seed H matrix is already initialized by a spatial ROI for defined resonances in the table
        # if not, create a seed H matrix entry by finding seed pixels
        seed_pixels = self.find_seed_pixels(find_for_all=False)
        # set the seeds in the MV analyzer object
        for component, pixels in seed_pixels.items():
            # get the spectrum for each pixel
            spectra = self.z3D_data[:, pixels[0], pixels[1]]
            mean_spectrum = np.mean(spectra, axis=1)
            print(mean_spectrum.shape)
            self.mv_analyzer.set_H_seed(component, mean_spectrum)

    def update_image_data(self, img, wavenumbers):
        self.z3D_data = img
        self.wavenumbers = wavenumbers
        self.mv_analyzer.update_image_data(img, self.mv_analyzer.get_n_components(), self.wavenumbers)

    def update_modified_data(self, data: np.ndarray):
        self.mv_analyzer.update_resonance_image_data(data)

    def update_wavenumbers(self, wavenumbers):
        self.wavenumbers = wavenumbers
        self.mv_analyzer.update_wavenumbers(wavenumbers)
        self.roi_manager.update_wavenumbers(wavenumbers)



class SeedWindow(QtWidgets.QMainWindow):
    default_colors = CompositeImageViewWidget.colormap_colors
    def __init__(self, seed_W_3d: np.ndarray, seed_H: np.ndarray, wavenumbers,
                 seed_pixels: dict or None = None, color_getter: Callable = None):
        super(SeedWindow, self).__init__()
        self.seed_W_3d = seed_W_3d
        self.seed_H = seed_H
        self.wavenumbers = wavenumbers
        self.seed_H_plot = pg.PlotWidget()
        self.seed_H_plot.addLegend()
        self.seed_W_view = ImageViewYX()
        self.seed_pixels = seed_pixels
        self.get_color = color_getter if color_getter is not None else lambda i: self.default_colors[i]
        self.scatters = []
        self.change_colormap_on_change = True
        self.seed_plot_signal = None
        self.colormap_signal = None
        self.setWindowTitle('Seed Visualization')
        self.init_ui()

    def init_ui(self):
        self.seed_W_view.setImage(self.seed_W_3d)
        for i in range(self.seed_H.shape[0]):
            self.seed_H_plot.plot(self.wavenumbers, self.seed_H[i, :], pen=pg.mkPen(self.get_color(i)), name=f'Component {i}')
        self.seed_H_plot.setLabel('left', 'Intensity')
        self.seed_H_plot.setLabel('bottom', 'Wavenumber [1/cm]')

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.seed_W_view)
        layout.addWidget(self.seed_H_plot)
        widget = QtWidgets.QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)
        self.seed_W_view.ui.roiPlot.setMinimumSize(QtCore.QSize(0, 60))
        axis = self.seed_W_view.ui.roiPlot.getAxis('bottom')
        axis.setLabel("W component")
        axis.setTicks([[(i, str(i)) for i in range(int(self.seed_W_3d.shape[2]))]])
        self.update_color_channel(0)

        # add a new row with an HBox layout
        hbox = QtWidgets.QHBoxLayout()
        # add a label and a checkbox_colormap to the HBox
        label = QtWidgets.QLabel('Change color map with W component')
        checkbox_colormap = QtWidgets.QCheckBox()
        checkbox_colormap.setChecked(self.change_colormap_on_change)

        # connect the checkbox_colormap to the change_colormap_on_change attribute
        checkbox_colormap.stateChanged.connect(lambda state: setattr(self, 'change_colormap_on_change', state))
        checkbox_colormap.stateChanged.connect(self.callback_color_change)
        self.callback_color_change(self.change_colormap_on_change)

        # add the label and the checkbox to the HBox
        hbox.addWidget(label)
        hbox.addWidget(checkbox_colormap)

        # add checkbox for seed plotting
        seed_plot_checkbox = QtWidgets.QCheckBox('Plot all seed pixels')
        seed_plot_checkbox.stateChanged.connect(self.callback_seed_pixels)
        hbox.addWidget(seed_plot_checkbox)

        # add chechbox to toggle between plotting all seeds or only the selected channel
        seed_plot_checkbox = QtWidgets.QCheckBox('Plot seed pixels for current component')
        seed_plot_checkbox.stateChanged.connect(lambda state: self.callback_seed_pixels(state, self.seed_W_view.currentIndex))
        seed_plot_checkbox.setChecked(True)
        self.callback_seed_pixels(True, self.seed_W_view.currentIndex)
        hbox.addWidget(seed_plot_checkbox)

        # add buttons to save H & W seeds via a file dialog to a tif and csv file
        save_seeds_button = QtWidgets.QPushButton('Save seeds')
        save_seeds_button.clicked.connect(lambda x: self.save_seeds())
        hbox.addWidget(save_seeds_button)

        # add the HBox to the layout
        layout.addLayout(hbox)
        self.show()

    def save_seeds(self):
        time = datetime.now().strftime("%Y_%m_%d_%H-%M-%S")
        file_path = QtWidgets.QFileDialog.getSaveFileName(self, f'Save W & H seeds to path', f'{time}_W_seeds.tif', 'TIFF (*.tif)')[0]
        if not file_path:
            return
        if not file_path.endswith('.tif'):
            file_path += '.tif'
        tifffile.imwrite(file_path, np.moveaxis(self.seed_W_3d, -1, 0).astype(np.uint16))
        csv_path = file_path.replace('.tif', '.csv')
        csv_path.replace('W_seeds', 'H_seeds')
        H = np.vstack((self.wavenumbers, self.seed_H)).T
        header = 'Wavenumber (cm-1), ' + ', '.join([f'Component {i}' for i in range(self.seed_H.shape[0])])
        np.savetxt(csv_path, H, delimiter=',', header=header)
        logger.info(f'Saved seeds to {file_path} and {csv_path}')


    def callback_color_change(self, state):
        self.change_colormap_on_change = state
        if state:
            self.colormap_signal = self.seed_W_view.timeLine.sigPositionChanged.connect(
                                lambda line: self.update_color_channel(self.seed_W_view.currentIndex))
        else:
            if self.colormap_signal is not None:
                self.disconnect(self.colormap_signal)
                self.colormap_signal = None

    def update_color_channel(self, cmp: int):
        pen_color = self.get_color(cmp)
        cmap = pg.ColorMap(pos=np.linspace(0.0, 1.0, 2), color=np.array([[0, 0, 0, 255], pen_color]))
        self.seed_W_view.setColorMap(cmap)

    def callback_seed_pixels(self, state, cmp: int = None):
        if state:
            if cmp is not None:
                self.plot_seed_pixels(cmp)
                self.seed_plot_signal = self.seed_W_view.timeLine.sigPositionChanged.connect(lambda: self.plot_seed_pixels(self.seed_W_view.currentIndex))
            else:
                self.plot_all_seed_pixels()
        else:
            for scatter in self.scatters:
                self.seed_W_view.removeItem(scatter)
                self.scatters.remove(scatter)
            if self.seed_plot_signal is not None:
                self.disconnect(self.seed_plot_signal)
                self.seed_plot_signal = None

    def plot_all_seed_pixels(self, delete_previous=True):
        if self.seed_pixels is None:
            return

        if delete_previous:
            for scatter in self.scatters:
                self.seed_W_view.removeItem(scatter)
                self.scatters.remove(scatter)
        for component, pixels in self.seed_pixels.items():
            # add +.5 to the pixel positions to center the marker in the pixel
            vis_pixel_pos = np.array(pixels) + 0.5
            # rearrange the pixel positions to the correct format of array([[y1, x1], [y2, x2], ...])
            positions = np.array([[vis_pixel_pos[1][i], vis_pixel_pos[0][i]] for i in range(len(pixels[0]))])
            scatter = pg.ScatterPlotItem(
                pos=positions,
                size=8,
                brush=pg.mkBrush(self.get_color(component)),
                symbol='+',  # Change this to 'o', 'x', 'star', etc.
                pen=pg.mkPen(self.get_color(component), width=1)  # White outline
            )
            self.add_scatter(pixels, component)

    def plot_seed_pixels(self, component: int, delete_previous=True):
        if delete_previous:
            for scatter in self.scatters:
                self.seed_W_view.removeItem(scatter)
                self.scatters.remove(scatter)
        if self.seed_pixels is None:
            return
        if component not in self.seed_pixels:
            return
        pixels = self.seed_pixels[component]
        self.add_scatter(pixels, component)

    def add_scatter(self, pixels, component):
        vis_pixel_pos = np.array(pixels) + 0.5
        positions = np.array([[vis_pixel_pos[1][i], vis_pixel_pos[0][i]] for i in range(len(pixels[0]))])
        scatter = pg.ScatterPlotItem(
            pos=positions,
            size=8,
            brush=pg.mkBrush(self.get_color(component)),
            symbol='+',
            pen=pg.mkPen(self.get_color(component), width=1)
        )
        self.seed_W_view.addItem(scatter)
        self.scatters.append(scatter)
        return scatter

    def update_seed_W(self, seed_W):
        self.seed_W_3d = seed_W
        self.seed_W_view.setImage(seed_W)

    def update_seed_H(self, seed_H):
        self.seed_H = seed_H
        for i in range(self.seed_H.shape[0]):
            self.seed_H_plot.plot(self.wavenumbers, self.seed_H[i, :], pen=pg.mkPen(self.roi_manager.get_color(i)), name=f'Component {i}')

if __name__ == '__main__':
    from tifffile import imread, tifffile

    image_file = imread(
        '/Users/mkunisch/Nextcloud/Manuel_BA/HS_CARS_Lung_cells_day_2_Vukosaljevic_et_al/2017_03_23_Lungcells_Day2_60mWBoth_2xZoom_16ms_Pos2_HS_CARS_ch-1_C.tif')
    show_raw_img = False



    analyzer = MultivariateAnalyzer(image_file, 4)
    analyzer.standardize_and_reshape_data()

    z, y, x = image_file.shape
    image_file_2d = image_file.reshape(-1, image_file.shape[0])
    image_file_reshaped = image_file.reshape(-1, y, x)
    print(f'{np.all(image_file == image_file_reshaped) = }')

    # analyzer.PCA()
    # analyzer.plot_PCA_mpl()

    # analyzer.randomNNMF()
    # analyzer.plot_nnmf_mpl()

    analyzer.set_H_seed(0, np.zeros(50))

