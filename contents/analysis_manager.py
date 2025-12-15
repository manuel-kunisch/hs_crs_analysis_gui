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
        # add an attribute to store fixed W components for NNMF
        self._fixed_seed_W: dict[int, np.ndarray] = {}  # component -> (n_pixels,) float32
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

        self._seed_pixel_mode = "Max Intensity"  # or "Score"

        if init_widgets:
            self.init_ui()

    def _generate_gaussian(self, center_wavenumber: float, hwhm: float, amp: float = 1.0, eliminate_zeros=True) -> np.ndarray:
        """
        Generates a Gaussian curve centered at center_wavenumber with the specified FWHM.

        Args:
            center_wavenumber (float): The center of the Gaussian curve.
            hwhm (float): The Half Width at Half Maximum of the Gaussian curve.

        Returns:
            np.ndarray: A numpy array representing the Gaussian curve.
        """
        if self.wavenumbers is None:
            return np.zeros(1)

        # FWHM = 2 * sqrt(2 * ln(2)) * sigma
        # sigma = FWHM / (2 * sqrt(2 * ln(2)))
        sigma = hwhm / (np.sqrt(2 * np.log(2)))

        # Gaussian formula: exp(- (x - mu)^2 / (2 * sigma^2))
        gaussian = np.exp(-((self.wavenumbers - center_wavenumber) ** 2) / (2 * sigma ** 2))
        gaussian *= amp

        if eliminate_zeros:
            # add float info eps to avoid errors with zeros for NNMF
            gaussian[gaussian == 0] += np.finfo(float).eps
        return gaussian

    def init_ui(self):
        # -----------------------------
        # Helpers
        # -----------------------------
        def _icon(theme_name: str, fallback_sp):
            ico = QtGui.QIcon.fromTheme(theme_name)
            if not ico.isNull():
                return ico

            app = QtWidgets.QApplication.instance()
            if hasattr(self, "analysis_widget") and self.analysis_widget is not None:
                style = self.analysis_widget.style()  # QWidget style
            elif app is not None:
                style = app.style()  # QApplication style
            else:
                style = None

            return style.standardIcon(fallback_sp) if style is not None else QtGui.QIcon()

        def _make_btn(text, theme_icon, fallback_sp, slot=None, tooltip=None, checkable=False):
            b = QtWidgets.QPushButton(text)
            b.setIcon(_icon(theme_icon, fallback_sp))
            if tooltip:
                b.setToolTip(tooltip)
            if slot is not None:
                b.clicked.connect(slot)
            b.setCheckable(checkable)
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            return b

        # -----------------------------
        # Root widget + global styling
        # -----------------------------
        self.analysis_widget = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(self.analysis_widget)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self.analysis_widget.setStyleSheet("""
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
        QPushButton, QToolButton {
            padding: 6px 10px;
        }
        QToolButton#AnalyzeTool {
            border-radius: 10px;
            padding: 10px 12px;
            font-weight: 700;
        }
        QHeaderView::section {
            padding: 6px;
        }
        """)

        # -----------------------------
        # Top row: Analysis settings + big Analyze button
        # -----------------------------
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(10)
        root.addLayout(top_row)

        analysis_group_box = QtWidgets.QGroupBox("Analysis")
        analysis_group_box.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)
        analysis_layout = QtWidgets.QGridLayout(analysis_group_box)
        analysis_layout.setHorizontalSpacing(10)
        analysis_layout.setVerticalSpacing(6)

        # Method radio buttons
        self.pca_radio = QtWidgets.QRadioButton("PCA")
        self.nnmf_radio = QtWidgets.QRadioButton("NNMF")
        self.pca_radio.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)
        self.nnmf_radio.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)
        self.pca_radio.clicked.connect(lambda: self.update_analysis_method("PCA"))
        self.nnmf_radio.clicked.connect(lambda: self.update_analysis_method("NNMF"))
        self.nnmf_radio.setChecked(True)  # Default

        analysis_layout.addWidget(self.pca_radio, 0, 0, 1, 1)
        analysis_layout.addWidget(self.nnmf_radio, 1, 0, 1, 1)

        # Components
        comp_label = QtWidgets.QLabel("# Components:")
        comp_label.setToolTip("Set the number of components for PCA/NNMF analysis")
        self.num_components_spinbox = QtWidgets.QSpinBox(
            minimum=1, maximum=100,
            value=self.mv_analyzer.get_n_components(),
            singleStep=1
        )
        self.num_components_spinbox.setToolTip(comp_label.toolTip())
        self.num_components_spinbox.setFixedWidth(80)
        self.num_components_spinbox.valueChanged.connect(lambda n: self.mv_analyzer.update_components(n))

        analysis_layout.addWidget(comp_label, 0, 1, 1, 1)
        analysis_layout.addWidget(self.num_components_spinbox, 0, 2, 1, 1)

        # Custom init
        custom_init_check = QtWidgets.QCheckBox("Custom initialization (NNMF)")
        custom_init_check.setToolTip(
            "Use custom initialization for NNMF based on spectral and spatial seed information")
        custom_init_check.setChecked(True)
        custom_init_check.stateChanged.connect(self.mv_analyzer.set_custom_nnmf_init)
        self.mv_analyzer.set_custom_nnmf_init(custom_init_check.isChecked())

        analysis_layout.addWidget(custom_init_check, 1, 1, 1, 2)

        top_row.addWidget(analysis_group_box)

        # Big Analyze button (toolbutton looks nicer than pushbutton here)
        self.analyze_button = QtWidgets.QToolButton()
        self.analyze_button.setObjectName("AnalyzeTool")
        self.analyze_button.setText("Analyze")
        self.analyze_button.setIcon(_icon("media-playback-start", QtWidgets.QStyle.SP_MediaPlay))
        self.analyze_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon)
        self.analyze_button.setIconSize(QtCore.QSize(32, 32))
        self.analyze_button.setMinimumWidth(130)
        self.analyze_button.clicked.connect(self.analyze_data)
        top_row.addStretch(1)
        top_row.addWidget(self.analyze_button)

        # -----------------------------
        # Main area: table (left) + control panel (right)
        # -----------------------------
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        # --- Left: table container ---
        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        self.resonance_table = QtWidgets.QTableWidget()
        res_settings_options = [
            "Component", "Wavenumber", "Width",
            "# Seed Pixels", "Use subtracted data",
            "Use Gaussian", "Amplitude", "Remove"
        ]
        self.res_settings_widget_columns = {option: i for i, option in enumerate(res_settings_options)}
        self.resonance_table.setColumnCount(len(res_settings_options))
        self.resonance_table.setHorizontalHeaderLabels(res_settings_options)
        self.resonance_table.setAcceptDrops(True)
        self.resonance_table.setAlternatingRowColors(True)
        self.resonance_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        # restrict to single row selection
        self.resonance_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.resonance_table.horizontalHeader().setStretchLastSection(True)
        self.resonance_table.resizeColumnsToContents()

        # Keep your widths where you really want them
        self.resonance_table.setColumnWidth(self.res_settings_widget_columns["Component"], 110)
        self.resonance_table.setColumnWidth(self.res_settings_widget_columns["Width"], 50)

        left_layout.addWidget(self.resonance_table, 1)

        # Shortcut + hint (cleaner + readable)
        del_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+D"), self.resonance_table)
        del_shortcut.activated.connect(lambda: self.remove_res_settings(self.resonance_table.currentRow()))

        hint = QtWidgets.QLabel('Tip: Press <b>Ctrl+D</b> to delete the selected resonance row.')
        hint.setStyleSheet("opacity: 0.75;")
        hint.setAlignment(QtCore.Qt.AlignRight)
        left_layout.addWidget(hint)

        splitter.addWidget(left)

        # --- Right: control panel ---
        right = QtWidgets.QWidget()
        right.setMinimumWidth(360)
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        # (1) Resonance / actions
        actions_gb = QtWidgets.QGroupBox("Actions")
        actions_layout = QtWidgets.QVBoxLayout(actions_gb)
        actions_layout.setSpacing(8)

        add_button = _make_btn(
            "Add resonance settings",
            "list-add", QtWidgets.QStyle.SP_FileDialogNewFolder,
            slot=self.add_resonance_settings
        )
        check_W_seeds_button = _make_btn(
            "Check W seeds (from H only)",
            "dialog-ok-apply", QtWidgets.QStyle.SP_DialogApplyButton,
            slot=self.show_W_seeds
        )
        test_seeds_button = _make_btn(
            "Test seeds",
            "system-run", QtWidgets.QStyle.SP_BrowserReload,
            slot=lambda: self.make_all_seeds_from_inputs(show_seeds=True),
            tooltip="Runs your seed generation and opens the seed preview window."
        )

        actions_layout.addWidget(add_button)
        check_layout = QtWidgets.QHBoxLayout()
        check_layout.setSpacing(8)
        check_layout.addWidget(check_W_seeds_button)
        check_layout.addWidget(test_seeds_button)
        actions_layout.addLayout(check_layout)

        right_layout.addWidget(actions_gb)

        # (2) Background (rolling ball)
        bg_gb = QtWidgets.QGroupBox("Background")
        bg_gb_layout = QtWidgets.QVBoxLayout(bg_gb)
        bg_form = QtWidgets.QFormLayout()
        bg_gb_layout.addLayout(bg_form)
        bg_form.setLabelAlignment(QtCore.Qt.AlignRight)
        bg_form.setFormAlignment(QtCore.Qt.AlignTop)
        bg_form.setHorizontalSpacing(10)
        bg_form.setVerticalSpacing(8)

        self.rolling_ball_radius = QtWidgets.QSpinBox()
        self.rolling_ball_radius.setRange(1, 5000)
        self.rolling_ball_radius.setValue(11)
        self.rolling_ball_radius.setSingleStep(2)
        self.rolling_ball_radius.setFixedWidth(90)
        bg_form.addRow("Rolling ball radius (px):", self.rolling_ball_radius)
        # add rolling ball sigma for gaussian smoothing
        self.rolling_ball_sigma = QtWidgets.QDoubleSpinBox()
        self.rolling_ball_sigma.setRange(0.1, 100.0)
        self.rolling_ball_sigma.setValue(3.0)
        self.rolling_ball_sigma.setSingleStep(0.1)
        self.rolling_ball_sigma.setFixedWidth(90)
        bg_form.addRow("Gaussian smoothing (px):", self.rolling_ball_sigma)

        bg_btn_row = QtWidgets.QHBoxLayout()
        bg_btn_row.setSpacing(8)
        rb_button = _make_btn(
            "From selected resonance",
            "image-filter", QtWidgets.QStyle.SP_FileDialogContentsView,
            slot=self.rolling_background_component_from_selected_resonance
        )
        rb_avg_button = _make_btn(
            "From average image",
            "insert-image", QtWidgets.QStyle.SP_FileIcon,
            slot=self.rolling_background_component_from_average_image
        )
        bg_btn_row.addWidget(rb_button)
        bg_btn_row.addWidget(rb_avg_button)
        bg_gb_layout.addLayout(bg_btn_row)
        right_layout.addWidget(bg_gb)

        # (3) W seed init settings
        wseed_gb = QtWidgets.QGroupBox("W seed initialization")
        wseed_layout = QtWidgets.QVBoxLayout(wseed_gb)
        wseed_layout.setSpacing(8)

        h_weight_seed_check = QtWidgets.QCheckBox("H weighted")
        h_weight_seed_check.setChecked(True)
        h_weight_seed_check.stateChanged.connect(
            lambda state: setattr(self.mv_analyzer, "H_weighted_W_seed", bool(state))
        )
        self.mv_analyzer.H_weighted_W_seed = h_weight_seed_check.isChecked()

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.setSpacing(10)
        avg_w_seed_radio = QtWidgets.QRadioButton("Average image")
        empty_w_seed_radio = QtWidgets.QRadioButton("Homogeneous (empty)")
        # disable the radios when H weighted is checked
        h_weight_seed_check.stateChanged.connect(
            lambda state: avg_w_seed_radio.setDisabled(bool(state))
        )
        h_weight_seed_check.stateChanged.connect(
            lambda state: empty_w_seed_radio.setDisabled(bool(state))
        )
        # set correct initial state
        if h_weight_seed_check.isChecked():
            avg_w_seed_radio.setDisabled(True)
            empty_w_seed_radio.setDisabled(True)

        # Button group to make the radios exclusive
        W_seed_group = QtWidgets.QButtonGroup(self)
        W_seed_group.setExclusive(True)
        W_seed_group.addButton(avg_w_seed_radio)
        W_seed_group.addButton(empty_w_seed_radio)

        avg_w_seed_radio.toggled.connect(lambda checked: self.mv_analyzer.set_W_seed_mode("None") if checked else None)
        empty_w_seed_radio.toggled.connect(
            lambda checked: self.mv_analyzer.set_W_seed_mode("Empty") if checked else None)

        avg_w_seed_radio.setChecked(True)
        self.mv_analyzer.set_W_seed_mode("None")

        mode_row.addWidget(avg_w_seed_radio)
        mode_row.addWidget(empty_w_seed_radio)
        mode_row.addStretch(1)

        wseed_layout.addWidget(h_weight_seed_check)
        wseed_layout.addLayout(mode_row)

        # Seed pixel metric
        metric_row = QtWidgets.QHBoxLayout()
        metric_row.setSpacing(10)
        metric_row.addWidget(QtWidgets.QLabel("Seed pixel metric:"))
        seed_pixel_mode_dropdown = QtWidgets.QComboBox()
        seed_pixel_mode_dropdown.addItems(["Max Intensity", "Score"])
        seed_pixel_mode_dropdown.setCurrentIndex(0)
        seed_pixel_mode_dropdown.currentTextChanged.connect(lambda text: setattr(self, "_seed_pixel_mode", text))
        metric_row.addWidget(seed_pixel_mode_dropdown, 1)
        wseed_layout.addLayout(metric_row)

        right_layout.addWidget(wseed_gb)

        right_layout.addStretch(1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)

        # Done
        self.analysis_widget.setLayout(root)

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
            self.make_all_seeds_from_inputs(show_seeds=True)
        self.analyze_button.setEnabled(False)
        self.analyze_button.setText('Analysis in Progress')
        self.thread_analysis.start()
        logger.info(f"{'-' * 50}")
        logger.info(f'{datetime.now()}: Analysis started')
        logger.info(f"{'-' * 50}")

    def make_all_seeds_from_inputs(self, show_seeds=True):
        """
        1. Reload H seeds from ROIs
        2. Process spectral info (initialize also H components from it that are not yet defined via seed pixels)
        3. Fill remaining W seeds with possibly existing H seeds, if not just average the image data
        3. All remaining H seeds are randomly initialized
        Parameters
        ----------
        show_seeds: bool
            If True, a seed window will be displayed showing the generated seeds.

        Returns
        -------

        """
        self._fixed_seed_W = {}  # reset fixed W seeds

        self.reload_H_seeds_from_rois()     # reset all existing seeds and reload ROIs
        # make seeds from user inputs inside the roi manager (highest priority for H, and user inputs for W from the table)



        logger.info("Processing user inputs for W seeds and H from ROIs")
        seed_W, seed_H, seed_pixels = self._make_W_seeds_from_spectral_info(make_H_seeds=True,
                                                                            debug_mode=False)  # create W seeds from spectral info and pass to analyzer

        logger.info('..... Trying to set W seeds from H components ........')
        # fill remaining W seeds
        # tries to either fill from given H seeds or from average image data (fallback)
        self.mv_analyzer.set_up_missing_W_seeds(skip_spectral_info=True, fill_H_seed=False)  # fill the W seed matrix

        logger.info(f'{"-"*10}')
        logger.info("Set up remaining H seeds:")
        # W seeds are set

        # remainining components that are not given by rois and spectral info are randomly initialized
        self.mv_analyzer.set_up_missing_H_seeds()

        if not show_seeds:
            return

        # show seeds from the MV analyzer tj
        seed_W_3d = self.mv_analyzer.seed_W.reshape(self.mv_analyzer.raw_data_3d.shape[1],
                                                    self.mv_analyzer.raw_data_3d.shape[2], -1)
        seed_H_final = self.mv_analyzer.seed_H

        self.show_seed_window(seed_W_3d, seed_H_final, seed_pixels)

    def show_seed_window(self, seed_W_3d, seed_H, seed_pixels):
        if self.seed_window is None:
            self.seed_window = SeedWidget(
                seed_W_3d,
                seed_H,
                self.wavenumbers,
                seed_pixels,
                self.roi_manager.get_color
            )
            logger.info("Created new seed window")
        else:
            # reuse existing window
            self.seed_window.set_data(
                seed_W_3d=seed_W_3d,
                seed_H=seed_H,
                wavenumbers=self.wavenumbers,
                seed_pixels=seed_pixels,
            )
            self.seed_window.show()
            self.seed_window.raise_()
            self.seed_window.activateWindow()
        logger.info("Updated existing seed window")

    def _reload_seeds_from_rois(self):
        """
        Reload H seeds from ROIs in the ROI manager and set them in the MV analyzer.
        Also, load possible fixed W seeds from the ROIs and check for compatibility.
        Returns
        -------
        """
        self.reload_H_seeds_from_rois()
        # check if any fixed W seeds present in the ROIs may be incompatible with the image possibly due to binning


    def reload_H_seeds_from_rois(self) -> None:
        seeds_list = self.roi_manager.get_roi_mean_curves()
        # TODO: Pass the seeds to the analyzer
        self.mv_analyzer.reset_seeds()
        for i, seed_dict in enumerate(seeds_list):
            component_number = int(seed_dict['resonance'].strip('Component '))
            component_index =  component_number - 1

            # check for existing fixed_W seeds coming with the roi
            rois = self.roi_manager.get_rois_from_component_indices(component_index)

            for roi in rois:
                if hasattr(roi, "fixed_W"):
                    fixed_W = roi.fixed_W
                    # fixed_W shape is checked always in the roi manager in update_data
                    self.set_fixed_W_seed(component_index, fixed_W)
                    logger.info(f'Setting fixed W seed for component {component_index} from ROI')

            flag_bgd = self.roi_manager.roi_table.cellWidget(i, self.roi_manager.widget_columns['Background']).checkState()
            if component_index >= self.mv_analyzer.get_n_components():
                logger.error(
                    f'Component number {component_index} is out of bounds for {self.mv_analyzer.get_n_components()} components and is ignored.')
                # pop up warning box
                QtWidgets.QMessageBox.warning(self.analysis_widget, 'Warning',
                                              f'Component number {component_index} is out of bounds for'
                                              f' {self.mv_analyzer.get_n_components()} components and is ignored.')
                continue
            self.mv_analyzer.set_H_seed(component_index, seed_dict['H'], flag_background=flag_bgd)

    def set_fixed_W_seed(self, component: int, fixed_W: np.ndarray):
        """
        Store a fixed W seed for a specific component.

        Args:
            component (int): The component index.
            fixed_W (np.ndarray): The fixed W seed array of shape (n_pixels,).
        """
        self._fixed_seed_W[component] = fixed_W

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

        widget_remove = QtWidgets.QPushButton("Remove")
        widget_remove.clicked.connect(lambda: self.remove_res_settings(row_position))
        self.resonance_table.setCellWidget(row_position, self.res_settings_widget_columns["Remove"], widget_remove)

        # Add text fields from column 2 to 4
        for column in [1, 2, 3, 6]: # Columns 1, 2, 3, 4 are SpinBoxes
            item = QtWidgets.QDoubleSpinBox()
            item.setMaximum(1e7)
            self.resonance_table.setCellWidget(row_position, column, item)


        # adjust default values
        # widget_eps: QtWidgets.QDoubleSpinBox = self.resonance_table.cellWidget(row_position, self.res_settings_widget_columns['Pixel Threshold'])
        # widget_eps.setValue(0.7)
        # widget_eps.valueChanged.connect(lambda x: self.adjust_npixels)

        widget_subtract: QtWidgets.QCheckBox = QtWidgets.QCheckBox()
        widget_subtract.setChecked(True)  # Default to True (use subtracted data)
        self.resonance_table.setCellWidget(row_position, self.res_settings_widget_columns["Use subtracted data"], widget_subtract)

        widget_np: QtWidgets.QDoubleSpinBox = self.resonance_table.cellWidget(row_position, self.res_settings_widget_columns['# Seed Pixels'])
        widget_np.setValue(150)
        widget_np.valueChanged.connect(lambda x: self.adjust_eps)

        widget_gaussian = QtWidgets.QCheckBox()
        widget_gaussian.setChecked(False)  # Default to False (use pixels)
        self.resonance_table.setCellWidget(row_position, self.res_settings_widget_columns["Use Gaussian"], widget_gaussian)
        widget_gaussian.clicked.connect(lambda: self.callback_res_settings(self.resonance_table.currentRow()))

        widget_amp = self.resonance_table.cellWidget(row_position, self.res_settings_widget_columns['Amplitude'])
        widget_amp.setValue(65_535)
        widget_amp.setSingleStep(1000)


        default_wavenumber = self.default_resonances[row_position%len(self.default_resonances)][0]
        if np.amin(self.wavenumbers) <= default_wavenumber <= np.amax(self.wavenumbers):
            self.resonance_table.cellWidget(row_position, self.res_settings_widget_columns['Wavenumber']).setValue((self.default_resonances[row_position%len(self.default_resonances)][0]))
            self.resonance_table.cellWidget(row_position, self.res_settings_widget_columns['Width']).setValue((self.default_resonances[row_position%len(self.default_resonances)][1]))

        for cell in [self.res_settings_widget_columns["Wavenumber"], self.res_settings_widget_columns["Width"], self.res_settings_widget_columns["# Seed Pixels"],
                     self.res_settings_widget_columns["Amplitude"]]:
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
        # widget_eps: QtWidgets.QDoubleSpinBox = self.resonance_table.cellWidget(current_row, self.res_settings_widget_columns['Pixel Threshold'])
        widget_np: QtWidgets.QDoubleSpinBox = self.resonance_table.cellWidget(current_row, self.res_settings_widget_columns['# Seed Pixels'])
        # get the number of pixels
        n_pixels = widget_np.value()
        # get the corresponding number of pixels above the threshold
        frames = self.mv_analyzer.return_resonance_indices(self.get_spectral_info_row(current_row))
        # get the max intensity of these frames and find the amount of pixels above the threshold
        max_i = np.max(self.mv_analyzer.raw_data_3d[frames, :, :], axis=None)
        eps = np.min(max_i)/max_i[n_pixels]
        # widget_eps.setValue(eps)

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
        row = self.get_row_index(component)
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
        self.roi_manager.highlight_component_region(spectral_range, self.get_component_index(row_table))

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
        # Keep raw table info in the analyzer if you want it elsewhere
        self.mv_analyzer.update_spectral_info(self.get_all_spectral_info())
        gaussian_specs = self.get_gaussian_specs_grouped()
        logger.info(f'Gaussian specs: {gaussian_specs}')
        # delegate everything Gaussian-related to ROIManager
        self.roi_manager.update_gaussian_models_from_spectral_info(gaussian_specs)

    def get_spectral_info_row(self, row: int) -> dict[str, float | int]:
        """
        main method to extract the spectral information from the table

        Returns a dictionary with the spectral information for the selected row. If the row is incomplete, an empty dictionary is returned.
        """
        cnumber = self.get_component_index(row)

        def get_value(column_name: str, cast_type: type, default=None):
            """Helper function to extract and convert a cell value."""
            widget_pos = self.res_settings_widget_columns.get(column_name, None)
            if widget_pos is None:
                return default
            widget: QtWidgets.QDoubleSpinBox = self.resonance_table.cellWidget(row, widget_pos)

            if widget:
                if cast_type is bool:
                    try:
                        return widget.isChecked()
                    except ValueError:
                        pass
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
        use_gauss = get_value('Use Gaussian', bool)
        amp = get_value('Amplitude', float)

        # Validate required values
        if wnumber is None or width is None or (thres is None and n_pixels is None):
            return {}

        dict_entry = {
            'Component': cnumber,
            'Wavenumber': wnumber,
            'Width': width,
            'Pixel Threshold': thres,
            '# Seed Pixels': n_pixels,
            'Use Gaussian': use_gauss,
            'Amplitude': amp
        }
        return dict_entry

    def get_spectral_info(self, component: int) -> dict[str, float | int]:
        """
        convenience method to get the spectral information for a specific component
        Args:
            component (int): The 0-based index of the component.

        """
        # iterate over all table entries and filter out the spectral information for the selected component
        info = dict()
        for row in range(self.resonance_table.rowCount()):
            # find the correct row index
            current_component: str = self.resonance_table.cellWidget(row, self.res_settings_widget_columns['Component']).currentText()
            # remove everything left from the last space to receive the component number
            current_component = self.get_component_index(row)
            if int(current_component) == component:
                info = self.get_spectral_info_row(row)
        return info

    def get_spectral_infos(self, component: int) -> list[dict[str, float | int]]:
        """
        convenience method to get all spectral information for a specific component
        Args:
            component (int): The 0-based index of the component.
        """
        infos = []
        for row in range(self.resonance_table.rowCount()):
            if self.get_component_index(row) == component:
                infos.append(self.get_spectral_info_row(row))
        return infos

    def get_all_spectral_info(self) -> list[dict[str, float | int]]:
        """ convenience method to get all spectral information from the table, only returns valid entries """
        info = []
        for row in range(self.resonance_table.rowCount()):
            info.append(self.get_spectral_info_row(row))
        return info

    def get_gaussian_specs_grouped(self) -> dict[int, list[tuple[float, float, float]]]:
        """
        Collect Gaussian peak definitions per component from the resonance table.

        Returns
        -------
        dict:
            {
              comp_idx: [(center, hwhm, amplitude), ...],
              ...
            }

            Each dict key contains a list of tuples defining Gaussian peaks for that component.
        """
        gaussians: dict[int, list[tuple[float, float, float]]] = {}

        for info in self.get_all_spectral_info():
            # skip empty/invalid rows
            if not info:
                continue

            # respect the "Use Gaussian" checkbox
            if not info.get("Use Gaussian", False):
                continue

            comp = int(info["Component"])
            center = float(info["Wavenumber"])
            hwhm  = float(info["Width"])           # interpret 'Width' column as HWHM
            amp   = float(info.get("Amplitude", 65535.0))

            gaussians.setdefault(comp, []).append((center, hwhm, amp))

        return gaussians

    def get_component_index(self, row: int):
        """
        Returns the component number (0-based) for the given row in the resonance table.
        Note: Displayed component 1 is internally represented as 0 etc.
        """
        component_combobox: QtWidgets.QComboBox = self.resonance_table.cellWidget(row, self.res_settings_widget_columns['Component'])
        if component_combobox is None:
            return None
        # get only text after the last space
        return int(component_combobox.currentText().split(' ')[-1]) - 1

    def get_row_index(self, component: int) -> int | None:
        """
        Returns the row number of the component in the table. If multiple components are found, the first one is returned.
        If no component is found, None is returned.

        Parameters
        ----------
        component

        Returns
        ------
        """
        # find the row number of the component in the table
        for row in range(self.resonance_table.rowCount()):
            if self.get_component_index(row) == component:
                return row
        return None

    def get_row_indices(self, component: int) -> list[int] | None:
        rows = []
        for row in range(self.resonance_table.rowCount()):
            if self.get_component_index(row) == component:
                rows.append(row)
        return rows if rows else None

    def _make_W_seeds_from_spectral_info(self, make_H_seeds=True, debug_mode=True) -> Tuple[np.ndarray, np.ndarray, dict[int, tuple[np.ndarray, np.ndarray]]]:
        """
        Creates W seeds from the spectral information in the resonance table. Takes into account the ROI definitions in the ROI manager for H seeds.
        The created seeds are passed to the MV analyzer.

        Important! This function cannot be moved to the MV analyzer, as it depends on the GUI elements for spectral info and ROIs.

        Parameters
        ----------
        make_H_seeds
        debug_mode

        Returns
        -------

        """
        logger.info(f"Processing spectral info to create W {"and H" if make_H_seeds else ""} seeds")
        # get the spectral information from the table
        # convert the wavenumber to indices
        seed_W = np.zeros((self.mv_analyzer.data_2d.shape[0], self.mv_analyzer.get_n_components()))

        if self._fixed_seed_W:
            for comp, fixed_W in self._fixed_seed_W.items():
                if comp < seed_W.shape[1] and fixed_W.shape[0] == seed_W.shape[0]:
                    seed_W[:, comp] = fixed_W
                    logger.info(f'Setting fixed W seed for component {comp} from ROI')
                else:
                    logger.warning(f'Fixed W seed for component {comp} has incompatible shape and is ignored.')

        # iterate over all components and create the W seeds
        for i in range(self.mv_analyzer.get_n_components()):
            # check if any spectral info exists for this component
            info_dict_list = self.get_spectral_infos(i)
            if not info_dict_list:
                logger.info(f'No spectral info found for component W[{i}], skipping W seed creation for now.')
                continue

            # collect all resonance indices for this component, slices where resonance is expected
            res_indices = np.array([], dtype=int)
            for info_dict in info_dict_list:
                res_indices = np.append(res_indices, self.mv_analyzer.return_resonance_indices(info_dict))

            # ... (Logic for weights and subtracted data same as before) ...

            weights = np.ones(res_indices.size)
            # Shortened for brevity: insert your existing W seed averaging code here
            data = self.mv_analyzer.data_2d
            if self.resonance_table.cellWidget(self.get_row_index(i),
                                               self.res_settings_widget_columns['Use subtracted data']).isChecked():
                data = self.mv_analyzer.resonance_data_2d

            if res_indices.size > 0:
                seed = np.average(data[..., res_indices], axis=1, weights=weights)
                seed_W[..., i] = seed

        self.mv_analyzer.set_W_seed_matrix(seed_W)

        n_components = self.mv_analyzer.get_n_components()
        # 2. Find Seed Pixels
        # Optimization: We check which components actually NEED pixel searching
        # Only search if NO ROI defined AND "Use Gaussian" is NOT checked
        # --- 2. Determine H Seed Source and Find Pixels if needed ---
        seed_H = np.zeros((n_components, self.wavenumbers.size))
        seed_pixel_dict = {}

        if make_H_seeds:
            # Identify components that must use the pixel search fallback
            seed_pixel_dict = self._check_and_find_seeds(n_components)

            # --- 3. Fill H Seeds based on determined source ---
            for i in range(n_components):
                # Priority 1: Existing ROI
                if self.roi_manager.is_component_defined(i):
                    decision_str = 'Existing user ROI'
                    # seed_H[i, :] = self.roi_manager.get_component_seed(i)
                    logger.info(f"Seed H[{i}] is already set from {decision_str}")
                    # self.mv_analyzer.set_H_seed(i, seed_H[i, :], flag_background=)
                    continue
                else:
                    logger.info(f"No ROI defined for component H{i}; Trying to process spectral info.")

                """
                # removed redundant block since Gaussians are set as dummy ROIs in the ROI manager
                
                # Priority 2: Gaussian (Check if *any* info entry has it checked)
                print(f"{i=}")
                print(f"{self.get_spectral_infos(i)=}")
                infos = self.get_spectral_infos(i)

                # check if any spectral info requests a Gaussian
                use_gaussian_for_comp = any(info.get('Use Gaussian', False) for info in infos)

                if use_gaussian_for_comp:
                    gaussian_accum = np.zeros_like(self.wavenumbers)
                    for info in infos:
                        # concatenate the gaussians
                        if info.get('Use Gaussian', False):
                            amp = info.get('Amplitude', 65_535)
                            gaussian_accum += self._generate_gaussian(info['Wavenumber'], info['Width'], amp)
                    decision_str = 'Gaussian user input'
                    seed_H[i, :] = gaussian_accum
                    logger.info(f"Set seed H[{i}] from {decision_str}")
                    self.mv_analyzer.set_H_seed(i, seed_H[i, :])
                    continue
                """
                # Priority 3: Seed Pixels (only for components where we searched and found them)
                # Create H spectrum from seed pixels
                if i in seed_pixel_dict:
                    pixels = seed_pixel_dict[i]
                    use_subtracted = False
                    row = self.get_row_index(i)
                    if row is not None:
                        use_subtracted = self.resonance_table.cellWidget(row, self.res_settings_widget_columns[
                            'Use subtracted data']).isChecked()

                    # Select data source
                    data_3d = self.mv_analyzer.resonance_data_zyx if use_subtracted else self.z3D_data

                    # Extract spectra from pixels
                    spectra = data_3d[:, pixels[0], pixels[1]]

                    # Calculate mean spectrum
                    decision_str = 'Seed Pixels'
                    seed_H[i, :] = np.mean(spectra, axis=1)
                    logger.info(f"Set seed H[{i}] from {decision_str}")
                    self.mv_analyzer.set_H_seed(i, seed_H[i, :])
                else:
                    logger.info(f"No valid seed source found for component H[{i}]; it will need to be randomly initialized later.")

        if debug_mode:
            self.show_seed_window(seed_W.reshape(self.mv_analyzer.raw_data_3d.shape[1],
                                                 self.mv_analyzer.raw_data_3d.shape[2], -1),
                                  seed_H,
                                  seed_pixel_dict)

        return seed_W, seed_H, seed_pixel_dict
        # idea: thresholding for W seeds

    def _find_free_component_index(self) -> int | None:
        n = self.mv_analyzer.get_n_components()
        used = set()

        # used by resonance table
        for r in range(self.resonance_table.rowCount()):
            c = self.get_component_index(r)
            if c is not None:
                used.add(int(c))

        # used by ROI manager
        for c in range(n):
            try:
                if self.roi_manager.is_component_defined(c):
                    used.add(c)
            except Exception:
                pass

        for c in range(n):
            if c not in used:
                return c
        return None

    def rolling_background_component_from_average_image(self):
        # get the average image over all wavenumbers
        avg_image = np.mean(self.mv_analyzer.raw_data_3d, axis=0)
        self._rolling_ball_background(avg_image)


    def rolling_background_component_from_selected_resonance(self):
        """
        Create a background component using rolling ball algorithm based on the currently selected resonance row.
        Estimates a background W component and H component.
        The background component can be added as a dummy ROI with fixed W seed.

        Returns
        -------

        """
        # make sure W seeds exist for the signal component
        self.reload_H_seeds_from_rois()
        W, H, _ = self._make_W_seeds_from_spectral_info(make_H_seeds=False, debug_mode=False)

        # get the W seed from the current user selection for W and H
        row = self.resonance_table.currentRow()
        if row is None or row < 0:
            QtWidgets.QMessageBox.information(self.analysis_widget, "Info", "Select a resonance row first.")
            return
        signal_comp = self.get_component_index(row)
        if signal_comp is None:
            QtWidgets.QMessageBox.warning(self.analysis_widget, "Warning", "Could not determine component from row.")
            return
        img_1d = W[:, signal_comp]
        img_2d = img_1d.reshape(self.mv_analyzer.raw_data_3d.shape[1], self.mv_analyzer.raw_data_3d.shape[2])
        self._rolling_ball_background(img_2d)

    def _rolling_ball_background(self, img_2d: np.ndarray):
        bg_comp = self._find_free_component_index()
        if bg_comp is None:
            # simplest behavior: grow by one
            new_n = self.mv_analyzer.get_n_components() + 1
            self.num_components_spinbox.setValue(new_n)  # triggers mv_analyzer.update_components
            bg_comp = new_n - 1

        radius = int(self.rolling_ball_radius.value())
        sigma = float(self.rolling_ball_sigma.value())

        W_bg, H_bg = self.mv_analyzer.create_background_component_from_reference(img_2d,
                                                                                 background_component=int(bg_comp),
                                                                                 radius_px=radius,
                                                                                 smooth_sigma=sigma,
                                                                                 write_into_seeds=False)

        # make a new window and show the W_bg in a pyqtgraph image view
        bg_W_view = self.make_W_seed_view(W_bg.reshape(self.mv_analyzer.raw_data_3d.shape[1],
                                                       self.mv_analyzer.raw_data_3d.shape[2], -1))
        bg_W_view.setWindowTitle(f"Background W Component {bg_comp + 1}")
        bg_W_view.show()

        # add user prompt if he/she want to add the W as seed as well (saved in the roi)
        reply = QtWidgets.QMessageBox.question(self.analysis_widget, 'Add Background ROI',
                                               f'Do you want to add the background component {bg_comp + 1} as a'
                                               f' dummy ROI with fixed W seed?'
                                               f'\n\n'
                                               f'Note: W will be saved in the ROI and used as fixed W seed for future analysis runs until removed.',
                                               QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                               QtWidgets.QMessageBox.Yes)

        # kill the bg_W_view if it is still open
        if bg_W_view is not None:
            bg_W_view.close()

        if reply == QtWidgets.QMessageBox.No:
            return

        self.roi_manager.add_dummy_roi(H_bg, component_number=int(bg_comp + 1), is_background=True,
                                       spectrum_name="RollingBall BG",
                                       fixed_W=W_bg
                                       # pass fixed W to the roi so it gets loaded on seed creation
                                       )

        # Optional: immediately show/update seed window
        self.make_all_seeds_from_inputs(show_seeds=True)

    def _check_and_find_seeds(self, n_components: int, debug_mode: bool = debug) -> dict[int, tuple[np.ndarray, np.ndarray]]:
        """
        Identify components that need seed pixel searching and perform the search.
        Parameters
        ----------
        n_components
        debug_mode

        Returns
        -------

        """
        components_needing_pixels = []
        seed_pixel_dict = {}
        # Check the source priority (ROI -> Gaussian -> Pixel) for all components
        for i in range(n_components):
            row = self.get_row_index(i)
            has_roi = self.roi_manager.is_component_defined(i)

            # Check if we are forced to use Gaussian for this component
            use_gaussian_checked = False
            if row is not None:
                # Assumes "Use Gaussian" is checked
                use_gaussian_checked = self.resonance_table.cellWidget(row, self.res_settings_widget_columns[
                    'Use Gaussian']).isChecked()

            # If no ROI and no Gaussian, this component needs the pixel search
            if not has_roi and not use_gaussian_checked:
                components_needing_pixels.append(i)

        logger.info(f"{components_needing_pixels=}")
        # Perform pixel search only for the required components
        if components_needing_pixels:
            # find the seed pixels for these components
            seed_pixel_dict = self.find_seed_pixels(components=components_needing_pixels, debug_mode=debug_mode)
        return seed_pixel_dict

    def find_seed_pixels(
            self,
            find_for_all: bool = False,
            components: list[int] = None,
            unique_seed_pixels: bool = True,
            debug_mode: bool = debug
    ) -> dict[int, tuple[np.ndarray, np.ndarray]]:
        """
        Find seed pixels for the specified components.

        Args:
            unique_seed_pixels (bool): if True, ensures seed pixels are unique across
                components (by excluding them from subsequent searches).
            find_for_all (bool): if True, finds seed pixels for all components regardless
                of ROI. (Ignored if 'components' list is provided)
            components (list[int]): List of component indices (0-based) to search for.
                If None and not find_for_all, it searches based on current ROI status.
            debug_mode (bool): if True, show the seed pixels in a new composite_image.
            metric (str): "intensity" → use max intensity in resonance frames (old behavior);
                          "score"     → use SNR-like score: resonance peak vs baseline.

        Returns:
            dict[int, tuple[np.ndarray, np.ndarray]]:
                Key is component index, value is (y_coords, x_coords) of seed pixels.
        """
        metric = self._seed_pixel_mode
        logger.info(f'Starting seed pixel search with {metric} metric.')
        # Determine the components to process
        components_to_process = components
        if components_to_process is None:
            components_to_process = list(range(self.mv_analyzer.get_n_components()))

        logger.info(f'Searching for seed pixels for components: {components_to_process}')
        background_components = self.roi_manager.get_background_components()
        excluded_pixels = self.roi_manager.get_components_pixels(background_components)
        seed_pixels_for_component: dict[int, tuple[np.ndarray, np.ndarray]] = {}

        for i in components_to_process:
            # Skip if explicitly checking for components without ROI and this one has one,
            # unless find_for_all is True.
            if not find_for_all and self.roi_manager.is_component_defined(i):
                logger.info(f'Skipping component {i} as it has a defined ROI and find_for_all is False.')
                continue

            # get all spectral info rows for this component
            spectral_info_list = self.get_spectral_infos(i)
            if not spectral_info_list:
                logger.warning(f'No spectral information found for component {i}')
                continue

            # --- Aggregate resonance frames AND parameters from *all* spectral infos ---
            frames = np.array([], dtype=int)
            epsilons = []
            n_pixels_list = []

            for spectral_info in spectral_info_list:
                # collect resonance indices
                frames = np.append(frames, self.mv_analyzer.return_resonance_indices(spectral_info))

                # collect thresholds / N_pixels if present
                eps = spectral_info.get('Pixel Threshold')
                if eps is not None and eps > 0:
                    epsilons.append(float(eps))

                npix = spectral_info.get('# Seed Pixels')
                if npix is not None and npix > 0:
                    n_pixels_list.append(int(npix))

            # unique frames (in case multiple specs share frames)
            frames = np.unique(frames)

            if frames.size == 0:
                logger.warning(f'No resonance indices found for component {i}')
                continue

            # combine epsilon and N_pixels from all rows:
            # - epsilon: use smallest (most permissive) epsilon
            # - N_pixels: sum of requested pixels across all peaks
            epsilon = min(epsilons) if epsilons else None
            N_pixels = int(np.sum(n_pixels_list)) if n_pixels_list else None

            # --- Decide on Threshold Method (no popup) ---
            use_epsilon = (epsilon is not None and epsilon > 0)

            if use_epsilon and N_pixels is not None:
                # If both are available, we treat N_pixels as fallback if epsilon too strict.
                # For now we choose the same logic as before: prefer N_pixels if >0.
                if N_pixels > 0:
                    use_epsilon = False
                else:
                    use_epsilon = True

            if N_pixels is None or N_pixels <= 0:
                use_epsilon = True

            # --- Log & Data Preparation ---
            logger.info(f'Finding seed pixels for component {i} in frames {frames.tolist()}')
            frames_of_interest = self.z3D_data[frames, ...].astype(float)

            # Exclude the background pixels by setting them to a very low score later
            # (we'll explicitly overwrite metric_frame for these).
            # No need to touch frames_of_interest directly anymore.

            # --- Build metric frame ---
            if metric.lower() == "score":
                # 1) "Signal": max intensity in resonance frames
                signal_frame = np.mean(frames_of_interest, axis=0)

                # 2) "Baseline": mean intensity outside resonance frames
                n_frames_total = self.z3D_data.shape[0]
                all_frames = np.arange(n_frames_total)
                outside_frames = np.setdiff1d(all_frames, frames)

                if outside_frames.size > 0:
                    baseline_frame = np.mean(
                        self.z3D_data[outside_frames, ...].astype(float), axis=0
                    )
                else:
                    baseline_frame = np.zeros_like(signal_frame)

                # 3) SNR-like score: high if bright at resonance and dim elsewhere
                eps = 1e-6
                metric_frame = (signal_frame - baseline_frame) / (baseline_frame + eps)
                metric_frame[metric_frame < 0] = 0.0  # clip negatives
                logger.info(f"Using 'score' metric for component {i}.")
            else:
                # Pure intensity (old behavior): maximum intensity in resonance frames
                metric_frame = np.amax(frames_of_interest, axis=0)
                logger.info(f"Using 'intensity' metric for component {i}.")

            # Make absolutely sure excluded pixels are never picked
            if excluded_pixels.size:
                metric_frame[excluded_pixels[0], excluded_pixels[1]] = -np.inf

            # --- Find Pixels ---
            if use_epsilon:
                max_pixel_val = np.nanmax(metric_frame)
                if not np.isfinite(max_pixel_val):
                    logger.warning(f"Metric frame for component {i} has no finite values.")
                    continue

                seed_pixels = np.where(metric_frame > max_pixel_val * (epsilon if epsilon is not None else 0.0))
                logger.info(
                    f"Using Pixel Threshold ({epsilon}) for component {i}. "
                    f"Found {seed_pixels[0].size} pixels."
                )
            else:
                # Find the N_pixels highest metric values
                flat = metric_frame.ravel()
                # handle case where everything might be -inf
                if not np.isfinite(flat).any():
                    logger.warning(f"Metric frame for component {i} has no finite values.")
                    continue

                sorted_idx = np.argsort(flat)  # ascending
                N_pixels = int(N_pixels)
                N_pixels = min(N_pixels, flat.size)

                seed_pixels_flat = sorted_idx[-N_pixels:]
                seed_pixels = np.unravel_index(seed_pixels_flat, metric_frame.shape)
                logger.info(f"Using N_pixels ({N_pixels}) for component {i}.")

            # --- Store / update exclusion ---
            if seed_pixels[0].size > 0:
                seed_pixels_for_component[i] = seed_pixels
                if unique_seed_pixels:
                    # Append the found seed pixels to the excluded set for subsequent components
                    new_pixels = np.array(seed_pixels)
                    if excluded_pixels.size == 0:
                        excluded_pixels = new_pixels
                    else:
                        excluded_pixels = np.concatenate((excluded_pixels, new_pixels), axis=1)
                    logger.debug(
                        f'Added seed pixels for component {i} to the excluded pixels. '
                        f'New shape: {excluded_pixels.shape}'
                    )
            else:
                logger.warning(f"No seed pixels found for component {i} with current settings.")

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
        logger.info(f"Analysis Manager: Image of shape {img.shape} and wavenumbers of length {len(wavenumbers)} updated in mv_analyzer.")
        logger.info(f"Analysis Manager: Image dtype {img.dtype}")
        logger.info(f"Analysis Manager: Image contains zeros: {np.any(img == 0)}")

    def update_modified_data(self, data: np.ndarray):
        self.mv_analyzer.update_resonance_image_data(data)

    def update_wavenumbers(self, wavenumbers):
        self.wavenumbers = wavenumbers
        self.mv_analyzer.update_wavenumbers(wavenumbers)
        self.roi_manager.update_wavenumbers(wavenumbers)



class SeedWidget(QtWidgets.QWidget):
    default_colors = CompositeImageViewWidget.colormap_colors
    def __init__(self, seed_W_3d: np.ndarray, seed_H: np.ndarray, wavenumbers,
                 seed_pixels: dict or None = None, color_getter: Callable = None):
        super(SeedWidget, self).__init__()
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
        self.seed_plot_signal = False
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
        # widget = QtWidgets.QWidget()
        self.setLayout(layout)
        # self.setCentralWidget(widget)
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

    def _on_timeline_position_changed(self, *args):
        """Called when the timeLine position changes (for current-component plotting)."""
        self.plot_seed_pixels(self.seed_W_view.currentIndex)


    def set_data(
            self,
            seed_W_3d: np.ndarray,
            seed_H: np.ndarray,
            wavenumbers: np.ndarray,
            seed_pixels: dict | None,
    ):
        """Update all data in one go when reusing the window."""
        self.seed_W_3d = seed_W_3d
        self.wavenumbers = wavenumbers
        self.seed_pixels = seed_pixels

        # update W image and x-axis ticks
        self.update_seed_W(seed_W_3d)

        # update H spectra
        self.update_seed_H(seed_H)

        # re-draw seed markers according to current checkbox state
        self._replot_seeds()

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
        """Handle both checkboxes:
           - state from 'all seed pixels' → cmp is None
           - state from 'current component' → cmp is an int
        """
        checked = bool(state)

        if checked:
            if cmp is not None:
                # 'current component' checkbox turned ON
                self.plot_seed_pixels(cmp)
                if not self.seed_plot_signal:
                    self.seed_W_view.timeLine.sigPositionChanged.connect(
                        self._on_timeline_position_changed
                    )
                    self.seed_plot_signal = True
            else:
                # 'all seed pixels' checkbox turned ON
                self.plot_all_seed_pixels()
        else:
            # checkbox turned OFF: clear current scatters
            for scatter in list(self.scatters):
                self.seed_W_view.removeItem(scatter)
            self.scatters.clear()

            # if this was the 'current component' checkbox, disconnect timeline
            if cmp is not None and self.seed_plot_signal:
                try:
                    self.seed_W_view.timeLine.sigPositionChanged.disconnect(
                        self._on_timeline_position_changed
                    )
                except TypeError:
                    # was already disconnected; ignore
                    pass
                self.seed_plot_signal = False

    def plot_all_seed_pixels(self, delete_previous=True):
        if self.seed_pixels is None:
            return

        if delete_previous:
            self.clear_scatters()

        for component, pixels in self.seed_pixels.items():
            self.add_scatter(pixels, component)

    def plot_seed_pixels(self, component: int, delete_previous=True):
        if delete_previous:
            self.clear_scatters()
        if self.seed_pixels is None or component not in self.seed_pixels:
            return
        pixels = self.seed_pixels[component]
        self.add_scatter(pixels, component)

    def add_scatter(self, pixels, component):
        vis_pixel_pos = np.array(pixels) + 0.5
        positions = np.array([[vis_pixel_pos[1][i], vis_pixel_pos[0][i]] for i in range(len(pixels[0]))])
        scatter = pg.ScatterPlotItem(
            pos=positions,
            size=8,
            brush=pg.mkBrush(self.get_color(component)[:3]),
            symbol='+',
            pen=pg.mkPen(self.get_color(component)[:3], width=1)
        )
        self.seed_W_view.addItem(scatter)
        self.scatters.append(scatter)
        return scatter

    def clear_scatters(self):
        for scatter in self.scatters:
            self.seed_W_view.removeItem(scatter)
        self.scatters.clear()

    def update_seed_W(self, seed_W: np.ndarray):
        self.seed_W_3d = seed_W
        self.seed_W_view.setImage(seed_W)

        # Update bottom axis ticks if the number of components changed
        axis = self.seed_W_view.ui.roiPlot.getAxis('bottom')
        axis.setTicks([[(i, str(i)) for i in range(int(self.seed_W_3d.shape[2]))]])

    def update_seed_H(self, seed_H):
        self.seed_H = seed_H
        # clear previous plots
        self.seed_H_plot.clear()
        for i in range(self.seed_H.shape[0]):
            try:
                pen = pg.mkPen(self.get_color(i))
            except TypeError:
                logger.error('Error getting color for seed H plot; using white instead.')
                pen = pg.mkPen(self.default_colors[i%len(self.default_colors)])
            self.seed_H_plot.plot(self.wavenumbers, self.seed_H[i, :], pen=pen, name=f'Component {i}')


    def _replot_seeds(self):
        """Re-draw the seed markers based on current checkboxes and data."""
        self.clear_scatters()
        if self.seed_pixels is None:
            return

        # If you want to respect your two checkboxes, store them as attributes
        # in init_ui, e.g. self.chk_all, self.chk_current.
        try:
            if getattr(self, "chk_all", None) is not None and self.chk_all.isChecked():
                self.plot_all_seed_pixels(delete_previous=False)
            elif getattr(self, "chk_current", None) is not None and self.chk_current.isChecked():
                self.plot_seed_pixels(self.seed_W_view.currentIndex, delete_previous=False)
            else:
                # Default: show current component
                self.plot_seed_pixels(self.seed_W_view.currentIndex, delete_previous=False)
        except Exception:
            # Fallback if checkboxes don't exist (first version)
            self.plot_seed_pixels(self.seed_W_view.currentIndex, delete_previous=False)

    def closeEvent(self, event: QtGui.QCloseEvent):
        # make sure internal graphics view & scene are cleaned up deterministically
        # self.seed_W_view.close()
        super().closeEvent(event)

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
