import logging
import sys
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
from contents.color_manager import ComponentColorManager
from contents.hs_image_view import ColorButton

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('Hyperspectral Analysis')
logger.setLevel(logging.INFO)

debug = False

class AnalysisWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(int)
    finished = QtCore.pyqtSignal(str)

    def __init__(self, run_callable: Callable[[], None], method_getter: Callable[[], str]):
        super().__init__()
        self._run_callable = run_callable
        self._method_getter = method_getter

    def run(self):
        self._run_callable()
        self.finished.emit(self._method_getter())

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
    def __init__(self, roi_manager, init_widgets=True, data=None):
        super().__init__()
        self.roi_manager: ROIManager | None = roi_manager
        self.color_manager:ComponentColorManager|None = self.roi_manager.color_manager
        self.seed_window: QtWidgets.QMainWindow or None = None
        self.z3D_data = None
        # add an attribute to store fixed W components for NNMF
        self._fixed_seed_W: dict[int, np.ndarray] = {}  # component -> (n_pixels,) float32
        self._fixed_seed_W_counts: dict[int, int] = {}  # component -> number of fixed W maps averaged into the stored mean
        self.rolling_ball_preview_dialog: QtWidgets.QDialog | None = None
        self.wavenumbers = None
        self.spectral_units = "cm⁻¹"
        self.axis_labels = None
        self._analysis_series_4d: np.ndarray | None = None
        self._analysis_series_label: str = "Slice"
        self._analysis_series_index: int = 0
        self._analysis_result_spectra: np.ndarray | None = None
        self._analysis_result_images: np.ndarray | None = None
        self._analysis_fit_info: dict | list[dict | None] | None = None

        self.roi_manager.new_roi_signal.connect(self.highlight_resonance_component)
        # Main widget instantiated in the init_ui method
        self.analysis_widget = None
        self.mv_analyzer = MultivariateAnalyzer(data, 3, self.wavenumbers)
        self._overwrite_existing_W_from_H = True
        self.w_seed_mode_dropdown: QtWidgets.QComboBox | None = None
        self.overwrite_W_from_H_check: QtWidgets.QCheckBox | None = None
        self.seed_pixel_mode_dropdown: QtWidgets.QComboBox | None = None
        self.nnmf_solver_dropdown: QtWidgets.QComboBox | None = None
        self.nnmf_backend_dropdown: QtWidgets.QComboBox | None = None
        self.nnmf_max_iter_spinbox: QtWidgets.QSpinBox | None = None
        self.nnls_max_iter_spinbox: QtWidgets.QSpinBox | None = None
        self.analysis_progress_widget: QtWidgets.QWidget | None = None
        self.analysis_progress_label: QtWidgets.QLabel | None = None
        self.analysis_progress_bar: QtWidgets.QProgressBar | None = None
        self._nnmf_option_widgets: list[QtWidgets.QWidget] = []
        self.custom_init_check: QtWidgets.QCheckBox | None = None
        self.fixed_h_nnls_only_check: QtWidgets.QCheckBox | None = None
        self.fast_multislice_nnmf_check: QtWidgets.QCheckBox | None = None
        self.scale_w_to_16bit_check: QtWidgets.QCheckBox | None = None

        # set up thread for analysis
        self.thread_analysis = QtCore.QThread()
        self.worker = AnalysisWorker(self._run_analysis_job, lambda: self.mv_analyzer.analysis_method)
        self.worker.moveToThread(self.thread_analysis)
        # Connect pyqt signals
        self.thread_analysis.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread_analysis.quit)
        self.worker.progress.connect(self._update_analysis_progress)
        # Connect the finished function to the worker
        self.worker.finished.connect(lambda: self.analysis_completed(self.mv_analyzer.analysis_method))
        self.thread_analysis.finished.connect(
            lambda: self.analyze_button.setEnabled(True)
        )
        self.thread_analysis.finished.connect(
            lambda: self.analyze_button.setText('Analyze')
        )
        self.thread_analysis.finished.connect(self._finish_analysis_progress)

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
            padding: 10px 14px;
            font-weight: 700;
            color: white;
            background-color: #4f79aa;
            border: 1px solid #7ea8d6;
            border-bottom: 3px solid #2d4f75;
        }
        QToolButton#AnalyzeTool:hover {
            background-color: #5c88bc;
        }
        QToolButton#AnalyzeTool:pressed {
            background-color: #436a97;
            border-bottom: 1px solid #2d4f75;
            padding-top: 12px;
            padding-bottom: 8px;
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
        analysis_group_box.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        analysis_layout = QtWidgets.QHBoxLayout(analysis_group_box)
        analysis_layout.setContentsMargins(12, 8, 12, 8)
        analysis_layout.setSpacing(12)

        def _make_section_title(text: str) -> QtWidgets.QLabel:
            label = QtWidgets.QLabel(text)
            label.setStyleSheet("font-weight: 700; color: #d7dee8;")
            return label

        def _make_divider() -> QtWidgets.QFrame:
            line = QtWidgets.QFrame()
            line.setFrameShape(QtWidgets.QFrame.VLine)
            line.setFrameShadow(QtWidgets.QFrame.Sunken)
            line.setStyleSheet("color: rgba(180,180,180,0.30);")
            return line

        # Method section
        method_panel = QtWidgets.QWidget()
        method_layout = QtWidgets.QVBoxLayout(method_panel)
        method_layout.setContentsMargins(0, 0, 0, 0)
        method_layout.setSpacing(4)
        method_layout.addWidget(_make_section_title("Method"))

        method_buttons = QtWidgets.QHBoxLayout()
        method_buttons.setContentsMargins(0, 0, 0, 0)
        method_buttons.setSpacing(10)
        self.pca_radio = QtWidgets.QRadioButton("PCA")
        self.nnmf_radio = QtWidgets.QRadioButton("NNMF")
        self.pca_radio.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)
        self.nnmf_radio.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)
        self.pca_radio.clicked.connect(lambda: self.update_analysis_method("PCA"))
        self.nnmf_radio.clicked.connect(lambda: self.update_analysis_method("NNMF"))
        self.nnmf_radio.setChecked(True)
        method_buttons.addWidget(self.pca_radio)
        method_buttons.addWidget(self.nnmf_radio)
        method_buttons.addStretch(1)
        method_layout.addLayout(method_buttons)

        comp_row = QtWidgets.QHBoxLayout()
        comp_row.setContentsMargins(0, 0, 0, 0)
        comp_row.setSpacing(8)
        comp_label = QtWidgets.QLabel("Components:")
        comp_label.setToolTip("Set the number of components for PCA/NNMF analysis")
        self.num_components_spinbox = QtWidgets.QSpinBox(
            minimum=1, maximum=100,
            value=self.mv_analyzer.get_n_components(),
            singleStep=1
        )
        self.num_components_spinbox.setToolTip(comp_label.toolTip())
        self.num_components_spinbox.setFixedWidth(72)
        self.num_components_spinbox.valueChanged.connect(self._handle_component_count_changed)
        comp_row.addWidget(comp_label)
        comp_row.addWidget(self.num_components_spinbox)
        comp_row.addStretch(1)
        method_layout.addLayout(comp_row)

        custom_init_check = QtWidgets.QCheckBox("Custom initialization")
        custom_init_check.setToolTip(
            "Use custom initialization for NNMF based on spectral and spatial seed information")
        custom_init_check.setChecked(True)
        custom_init_check.stateChanged.connect(self.mv_analyzer.set_custom_nnmf_init)
        self.mv_analyzer.set_custom_nnmf_init(custom_init_check.isChecked())
        self.custom_init_check = custom_init_check
        method_layout.addWidget(custom_init_check)

        self.fixed_h_nnls_only_check = QtWidgets.QCheckBox("Fixed-H NNLS mode")
        self.fixed_h_nnls_only_check.setToolTip(
            "3D: use the fixed-H NNLS abundance maps directly as the result.\n"
            "4D: reuse the displayed slice as the fixed-H reference and rebuild the W maps per slice."
        )
        self.fixed_h_nnls_only_check.stateChanged.connect(self._sync_fixed_h_mode_seed_requirements)
        method_layout.addWidget(self.fixed_h_nnls_only_check)
        self.fast_multislice_nnmf_check = None
        method_layout.addStretch(1)
        analysis_layout.addWidget(method_panel)
        analysis_layout.addWidget(_make_divider())

        # NNMF options section
        options_panel = QtWidgets.QWidget()
        options_layout = QtWidgets.QVBoxLayout(options_panel)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(4)
        options_title = _make_section_title("NNMF Options")
        options_layout.addWidget(options_title)

        options_form = QtWidgets.QFormLayout()
        options_form.setContentsMargins(0, 0, 0, 0)
        options_form.setHorizontalSpacing(10)
        options_form.setVerticalSpacing(4)
        options_form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        solver_label = QtWidgets.QLabel("Solver:")
        solver_label.setToolTip("Choose the scikit-learn NMF solver. 'cd' is usually faster on CPU; 'mu' is the legacy multiplicative-update path.")
        self.nnmf_solver_dropdown = QtWidgets.QComboBox()
        self.nnmf_solver_dropdown.addItem("Coordinate Descent (cd)", "cd")
        self.nnmf_solver_dropdown.addItem("Multiplicative Updates (mu)", "mu")
        self.nnmf_solver_dropdown.setToolTip(solver_label.toolTip())
        self.nnmf_solver_dropdown.currentIndexChanged.connect(
            lambda index: (
                self.mv_analyzer.set_nnmf_solver(self.nnmf_solver_dropdown.itemData(index)),
                self._sync_nnmf_backend_controls()
            )
        )
        self.nnmf_solver_dropdown.setCurrentIndex(1)
        self.mv_analyzer.set_nnmf_solver(self.nnmf_solver_dropdown.itemData(1))
        options_form.addRow(solver_label, self.nnmf_solver_dropdown)

        backend_label = QtWidgets.QLabel("Backend:")
        backend_label.setToolTip(
            "Controls GPU use for multiplicative-update NNMF. "
            "'cd' always runs on the scikit-learn CPU backend."
        )
        self.nnmf_backend_dropdown = QtWidgets.QComboBox()
        self.nnmf_backend_dropdown.addItem("Automatic", "auto")
        self.nnmf_backend_dropdown.addItem("CPU only", "cpu")
        self.nnmf_backend_dropdown.addItem("Prefer GPU", "gpu")
        self.nnmf_backend_dropdown.setToolTip(backend_label.toolTip())
        self.nnmf_backend_dropdown.currentIndexChanged.connect(
            lambda index: self.mv_analyzer.set_nnmf_backend_preference(
                self.nnmf_backend_dropdown.itemData(index)
            )
        )
        self.nnmf_backend_dropdown.setCurrentIndex(0)
        self.mv_analyzer.set_nnmf_backend_preference(self.nnmf_backend_dropdown.itemData(0))
        options_form.addRow(backend_label, self.nnmf_backend_dropdown)

        nnmf_iters_label = QtWidgets.QLabel("NNMF iters:")
        nnmf_iters_label.setToolTip("Maximum iterations for both scikit-learn and torch NNMF backends.")
        self.nnmf_max_iter_spinbox = QtWidgets.QSpinBox()
        self.nnmf_max_iter_spinbox.setRange(1, 100000)
        self.nnmf_max_iter_spinbox.setSingleStep(100)
        self.nnmf_max_iter_spinbox.setValue(int(self.mv_analyzer.nnmf_max_iter))
        self.nnmf_max_iter_spinbox.setFixedWidth(82)
        self.nnmf_max_iter_spinbox.setToolTip(nnmf_iters_label.toolTip())
        self.nnmf_max_iter_spinbox.valueChanged.connect(self.mv_analyzer.set_nnmf_max_iter)
        options_form.addRow(nnmf_iters_label, self.nnmf_max_iter_spinbox)

        nnls_iters_label = QtWidgets.QLabel("NNLS iters:")
        nnls_iters_label.setToolTip("Maximum iterations for fixed-H NNLS reconstruction.")
        self.nnls_max_iter_spinbox = QtWidgets.QSpinBox()
        self.nnls_max_iter_spinbox.setRange(1, 100000)
        self.nnls_max_iter_spinbox.setSingleStep(100)
        self.nnls_max_iter_spinbox.setValue(int(self.mv_analyzer.nnls_max_iter))
        self.nnls_max_iter_spinbox.setFixedWidth(82)
        self.nnls_max_iter_spinbox.setToolTip(nnls_iters_label.toolTip())
        self.nnls_max_iter_spinbox.valueChanged.connect(self.mv_analyzer.set_nnls_max_iter)
        options_form.addRow(nnls_iters_label, self.nnls_max_iter_spinbox)

        options_layout.addLayout(options_form)
        options_layout.addStretch(1)
        analysis_layout.addWidget(options_panel)
        analysis_layout.addStretch(1)

        self._nnmf_option_widgets = [
            options_title,
            solver_label,
            self.nnmf_solver_dropdown,
            backend_label,
            self.nnmf_backend_dropdown,
            nnmf_iters_label,
            self.nnmf_max_iter_spinbox,
            nnls_iters_label,
            self.nnls_max_iter_spinbox,
            custom_init_check,
            self.fixed_h_nnls_only_check,
        ]

        self._sync_nnmf_backend_controls()
        self._sync_fixed_h_mode_seed_requirements()
        self._sync_analysis_mode_controls()

        top_row.addWidget(analysis_group_box, 1)

        # Run section
        run_group_box = QtWidgets.QGroupBox("Run")
        run_group_box.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)
        run_layout = QtWidgets.QVBoxLayout(run_group_box)
        run_layout.setContentsMargins(12, 8, 12, 8)
        run_layout.setSpacing(6)

        self.analyze_button = QtWidgets.QToolButton()
        self.analyze_button.setObjectName("AnalyzeTool")
        self.analyze_button.setText("Run Analysis")
        self.analyze_button.setIcon(_icon("media-playback-start", QtWidgets.QStyle.SP_MediaPlay))
        self.analyze_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.analyze_button.setIconSize(QtCore.QSize(24, 24))
        self.analyze_button.setAutoRaise(False)
        self.analyze_button.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.analyze_button.setMinimumSize(170, 52)
        self.analyze_button.clicked.connect(self.analyze_data)

        self.scale_w_to_16bit_check = QtWidgets.QCheckBox("Scale results to 16-bit")
        self.scale_w_to_16bit_check.setChecked(True)
        self.scale_w_to_16bit_check.setToolTip(
            "Globally scale displayed NNMF/NNLS result maps to the uint16 range. "
            "Disable this to inspect raw floating-point result values."
        )

        run_button_row = QtWidgets.QHBoxLayout()
        run_button_row.setContentsMargins(0, 0, 0, 0)
        run_button_row.setSpacing(10)
        run_button_row.addWidget(self.analyze_button)
        run_button_row.addWidget(self.scale_w_to_16bit_check, alignment=QtCore.Qt.AlignVCenter)
        run_button_row.addStretch(1)
        run_layout.addLayout(run_button_row)

        self.analysis_progress_widget = QtWidgets.QWidget()
        progress_layout = QtWidgets.QHBoxLayout(self.analysis_progress_widget)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(6)
        self.analysis_progress_label = QtWidgets.QLabel("Slice progress")
        self.analysis_progress_label.setStyleSheet("color: #97a3af; font-size: 11px;")
        self.analysis_progress_bar = QtWidgets.QProgressBar()
        self.analysis_progress_bar.setRange(0, 100)
        self.analysis_progress_bar.setValue(0)
        self.analysis_progress_bar.setFixedHeight(12)
        self.analysis_progress_bar.setTextVisible(False)
        progress_layout.addWidget(self.analysis_progress_label)
        progress_layout.addWidget(self.analysis_progress_bar, 1)
        run_layout.addWidget(self.analysis_progress_widget)

        top_row.addWidget(run_group_box)
        self._finish_analysis_progress()

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
            "Component",
            "Color",
            "Wavenumber", "Width",
            "# Seed Pixels", "Use subtracted data",
            "Use Gaussian", "Amplitude", "Remove"
        ]

        if self.color_manager is None:
            res_settings_options.remove("Color")

        self.res_settings_widget_columns = {option: i for i, option in enumerate(res_settings_options)}
        self.resonance_table.setColumnCount(len(res_settings_options))
        self.resonance_table.setHorizontalHeaderLabels(res_settings_options)
        self._refresh_spectral_column_labels()
        self.resonance_table.setAcceptDrops(True)
        self.resonance_table.setAlternatingRowColors(True)
        self.resonance_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        # restrict to single row selection
        self.resonance_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._refresh_resonance_table_layout()
        QtCore.QTimer.singleShot(0, self._refresh_resonance_table_layout)

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
        actions_layout = QtWidgets.QHBoxLayout(actions_gb)
        actions_layout.setSpacing(8)

        add_button = _make_btn(
            "Add resonance settings",
            "list-add", QtWidgets.QStyle.SP_FileDialogNewFolder,
            slot=self.add_resonance_settings
        )
        check_W_seeds_button = _make_btn(
            "Preview W seeds",
            "dialog-ok-apply", QtWidgets.QStyle.SP_DialogApplyButton,
            slot=self.show_W_seeds,
            tooltip="Preview the current W maps with the selected W seed method."
        )
        test_seeds_button = _make_btn(
            "Test seeds",
            "system-run", QtWidgets.QStyle.SP_BrowserReload,
            slot=lambda: self.make_all_seeds_from_inputs(show_seeds=True),
            tooltip="Runs your seed generation and opens the seed preview window."
        )

        actions_layout.addWidget(add_button)
        actions_layout.addWidget(test_seeds_button)
        """
        # old layout
        check_layout = QtWidgets.QHBoxLayout()
        check_layout.setSpacing(8)
        check_layout.addWidget(check_W_seeds_button)
        check_layout.addWidget(test_seeds_button)
        actions_layout.addLayout(check_layout)
        """

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

        self.rolling_ball_projection_combo = QtWidgets.QComboBox()
        self.rolling_ball_projection_combo.addItem("Mean Projection", "mean")
        self.rolling_ball_projection_combo.addItem("Max Projection", "max")
        self.rolling_ball_projection_combo.addItem("Min Projection", "min")
        self.rolling_ball_projection_combo.setFixedWidth(120)
        bg_form.addRow("Reference image:", self.rolling_ball_projection_combo)

        bg_btn_row = QtWidgets.QHBoxLayout()
        bg_btn_row.setSpacing(8)
        rb_button = _make_btn(
            "Preview Background",
            "image-filter", QtWidgets.QStyle.SP_FileDialogContentsView,
            slot=self.rolling_background_component_from_projection
        )
        bg_btn_row.addWidget(rb_button)
        bg_btn_row.addStretch(1)
        bg_gb_layout.addLayout(bg_btn_row)
        right_layout.addWidget(bg_gb)

        # (3) Seed init settings
        wseed_gb = QtWidgets.QGroupBox("Seed initialization")
        wseed_layout = QtWidgets.QVBoxLayout(wseed_gb)
        wseed_layout.setSpacing(8)

        method_row = QtWidgets.QHBoxLayout()
        method_row.setSpacing(10)
        method_row.addWidget(QtWidgets.QLabel("W map from H:"))
        self.w_seed_mode_dropdown = QtWidgets.QComboBox()
        self.w_seed_mode_dropdown.addItem("NNLS abundance map (recommended)", "NNLS abundance map")
        self.w_seed_mode_dropdown.addItem("Selective score map", "Selective score map")
        self.w_seed_mode_dropdown.addItem("H-weighted average (legacy)", "H weights")
        self.w_seed_mode_dropdown.addItem("Average image (fallback)", "Average image")
        self.w_seed_mode_dropdown.addItem("Homogeneous (empty)", "Homogeneous (empty)")
        self.w_seed_mode_dropdown.currentIndexChanged.connect(
            lambda index: self.mv_analyzer.set_W_seed_mode(self.w_seed_mode_dropdown.itemData(index))
        )
        method_row.addWidget(self.w_seed_mode_dropdown, 1)
        wseed_layout.addLayout(method_row)

        wseed_hint = QtWidgets.QLabel(
            "Uses the current H seed to build the spatial W map. "
            "Fixed W masks from ROIs are kept unchanged."
        )
        wseed_hint.setWordWrap(True)
        wseed_hint.setStyleSheet("color: #6b7280;")
        wseed_layout.addWidget(wseed_hint)

        self.w_seed_mode_dropdown.setCurrentIndex(0)
        self.mv_analyzer.set_W_seed_mode(self.w_seed_mode_dropdown.itemData(0))

        self.overwrite_W_from_H_check = QtWidgets.QCheckBox("Overwrite existing W with H-based map")
        self.overwrite_W_from_H_check.setChecked(self._overwrite_existing_W_from_H)
        self.overwrite_W_from_H_check.setToolTip(
            "If enabled, H-based W estimation replaces existing spectral W seeds. "
            "If disabled, it only fills missing W columns."
        )
        self.overwrite_W_from_H_check.toggled.connect(
            lambda state: setattr(self, "_overwrite_existing_W_from_H", bool(state))
        )
        wseed_layout.addWidget(self.overwrite_W_from_H_check)

        # Seed pixel metric
        metric_row = QtWidgets.QHBoxLayout()
        metric_row.setSpacing(10)
        metric_row.addWidget(QtWidgets.QLabel("H seed pixel metric:"))
        self.seed_pixel_mode_dropdown = QtWidgets.QComboBox()
        self.seed_pixel_mode_dropdown.addItems(["Max Intensity", "Score"])
        self.seed_pixel_mode_dropdown.setCurrentIndex(0)
        self.seed_pixel_mode_dropdown.currentTextChanged.connect(lambda text: setattr(self, "_seed_pixel_mode", text))
        metric_row.addWidget(self.seed_pixel_mode_dropdown, 1)
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
        self._analysis_result_spectra = None
        self._analysis_result_images = None
        self._analysis_fit_info = None
        if self._analysis_series_4d is not None:
            self._begin_analysis_progress(int(self._analysis_series_4d.shape[0]))
        else:
            self._finish_analysis_progress()
        if self.nnmf_radio.isChecked():
            if self._fixed_h_mode_enabled():
                if not self.mv_analyzer.custom_nnmf_init:
                    self._finish_analysis_progress()
                    QtWidgets.QMessageBox.warning(
                        self.analysis_widget,
                        "Custom initialization required",
                        "Fixed-H NNLS mode requires custom H seeds. Enable 'Custom initialization (NNMF)' first.",
                    )
                    return
                fill_missing_h = self._analysis_series_4d is not None
                self._prepare_fixed_h_seed_template(show_seeds=True, fill_missing_h=fill_missing_h)
                if not fill_missing_h and not self.mv_analyzer.has_complete_H_seed_set():
                    self._finish_analysis_progress()
                    QtWidgets.QMessageBox.warning(
                        self.analysis_widget,
                        "Incomplete H seeds",
                        "Fixed-H NNLS is only available when every component has an H seed.\n\n"
                        "Add ROI/spectral H seeds for all components first.",
                    )
                    return
            elif self.mv_analyzer.custom_nnmf_init:
                if self._analysis_series_4d is not None:
                    self._prepare_fixed_h_seed_template(show_seeds=True, fill_missing_h=True)
                else:
                    self.make_all_seeds_from_inputs(show_seeds=True)
        self.analyze_button.setEnabled(False)
        self.analyze_button.setText('Analysis in Progress')
        self.thread_analysis.start()
        logger.info(f"{'-' * 50}")
        logger.info(f'{datetime.now()}: Analysis started')
        logger.info(f"{'-' * 50}")

    def set_analysis_series(self, data: np.ndarray | None, slice_axis_label: str = "Slice", current_slice_index: int = 0):
        if data is not None and data.ndim == 4:
            self._analysis_series_4d = np.asarray(data)
            self._analysis_series_label = str(slice_axis_label or "Slice")
            self._analysis_series_index = int(np.clip(current_slice_index, 0, self._analysis_series_4d.shape[0] - 1))
        else:
            self._analysis_series_4d = None
            self._analysis_series_label = str(slice_axis_label or "Slice")
            self._analysis_series_index = 0
        self._sync_fixed_h_mode_seed_requirements()

    def get_analysis_series_label(self) -> str:
        return self._analysis_series_label

    def _run_analysis_job(self):
        if self._use_fixed_h_nnls_only():
            self.mv_analyzer.fixed_H = np.array(self.mv_analyzer.seed_H, copy=True)
            self.mv_analyzer.fixed_W = np.array(self.mv_analyzer.seed_W, copy=True)
            self.mv_analyzer.fixed_W_2D = self.mv_analyzer.fixed_W.reshape(
                self.mv_analyzer.raw_data_3d.shape[1],
                self.mv_analyzer.raw_data_3d.shape[2],
                -1,
            ).transpose(2, 0, 1)
            self._analysis_result_spectra = np.array(self.mv_analyzer.seed_H, copy=True)
            self._analysis_result_images = np.array(self.mv_analyzer.fixed_W_2D, copy=True)
            self._analysis_fit_info = None if self.mv_analyzer.last_nnls_info is None else dict(self.mv_analyzer.last_nnls_info)
            return

        if self._analysis_series_4d is not None:
            self._run_multislice_analysis()
            return

        self.mv_analyzer.start_analysis()
        if self.mv_analyzer.analysis_method == "PCA":
            self._analysis_result_spectra = self.mv_analyzer.PCs
            self._analysis_result_images = self.mv_analyzer.pca_2DX
            self._analysis_fit_info = None
        else:
            self._analysis_result_spectra = self.mv_analyzer.fixed_H
            self._analysis_result_images = self.mv_analyzer.fixed_W_2D
            self._analysis_fit_info = None if self.mv_analyzer.last_nnmf_info is None else dict(self.mv_analyzer.last_nnmf_info)

    def _run_multislice_analysis(self):
        series = self._analysis_series_4d
        if series is None or series.ndim != 4:
            raise RuntimeError("No 4D analysis series is configured.")

        total_slices = int(series.shape[0])
        self.worker.progress.emit(0)

        analysis_method = self.mv_analyzer.analysis_method
        n_components = self.mv_analyzer.get_n_components()
        wavenumbers = None if self.wavenumbers is None else np.array(self.wavenumbers, copy=True)
        spectral_info = self.mv_analyzer.spectral_info
        custom_init = bool(self.mv_analyzer.custom_nnmf_init)
        solver = self.mv_analyzer.nnmf_solver
        backend_preference = self.mv_analyzer.nnmf_backend_preference
        w_seed_mode = self.mv_analyzer.w_seed_mode
        fast_mode = bool(custom_init and self._use_fast_multislice_nnmf())
        reference_slice_index = int(np.clip(self._analysis_series_index, 0, series.shape[0] - 1))

        display_data = None if self.z3D_data is None else np.array(self.z3D_data, copy=True)
        display_seed_H = None if self.mv_analyzer.seed_H is None else np.array(self.mv_analyzer.seed_H, copy=True)
        display_seed_H_bg = None if self.mv_analyzer.seed_H_background_flag is None else np.array(self.mv_analyzer.seed_H_background_flag, copy=True)
        display_seed_W = None if self.mv_analyzer.seed_W is None else np.array(self.mv_analyzer.seed_W, copy=True)
        fixed_seed_W = {comp: np.array(seed, copy=True) for comp, seed in self._fixed_seed_W.items()}

        spectra_per_slice = []
        images_per_slice = []
        reference_result = None
        fit_info_per_slice: list[dict | None] | None = [] if analysis_method != "PCA" else None
        reference_fit_info = None if self.mv_analyzer.last_nnls_info is None else dict(self.mv_analyzer.last_nnls_info)

        if fast_mode:
            logger.info(
                "4D fast mode enabled: reusing the reference-slice NNLS seed result on %s %s and "
                "recomputing the same fixed-H NNLS seed maps on the remaining slices.",
                self._analysis_series_label.lower(),
                reference_slice_index + 1,
            )
            reference_result = {
                "H": None if display_seed_H is None else np.array(display_seed_H[:n_components], copy=True),
                "W": None if display_seed_W is None else display_seed_W.reshape(
                    self.mv_analyzer.raw_data_3d.shape[1],
                    self.mv_analyzer.raw_data_3d.shape[2],
                    -1,
                ).transpose(2, 0, 1)[:n_components],
            }

        for slice_index in range(series.shape[0]):
            slice_data = np.array(series[slice_index], copy=True)
            logger.info("Running %s on %s %s/%s", analysis_method, self._analysis_series_label.lower(), slice_index + 1, series.shape[0])

            if fast_mode and slice_index == reference_slice_index and reference_result is not None:
                spectra_per_slice.append(np.array(reference_result["H"], copy=True))
                images_per_slice.append(np.array(reference_result["W"], copy=True))
                if fit_info_per_slice is not None:
                    fit_info_per_slice.append(None if reference_fit_info is None else dict(reference_fit_info))
                self.worker.progress.emit(int(round(100.0 * (slice_index + 1) / max(1, total_slices))))
                continue

            self.z3D_data = slice_data
            self.mv_analyzer.update_image_data(slice_data, n_components, wavenumbers)
            if spectral_info is not None:
                self.mv_analyzer.update_spectral_info(spectral_info)
            self.mv_analyzer.set_custom_nnmf_init(custom_init)
            self.mv_analyzer.set_nnmf_solver(solver)
            self.mv_analyzer.set_nnmf_backend_preference(backend_preference)
            self.mv_analyzer.set_W_seed_mode(w_seed_mode)
            self._update_multislice_modified_data(slice_data)

            if analysis_method == "PCA":
                self.mv_analyzer.PCA()
                spectra_per_slice.append(np.array(self.mv_analyzer.PCs[:n_components], copy=True))
                images_per_slice.append(np.array(self.mv_analyzer.pca_2DX[:n_components], copy=True))
                self.worker.progress.emit(int(round(100.0 * (slice_index + 1) / max(1, total_slices))))
                continue

            if fast_mode:
                seed_result = self._build_fixed_h_seed_result(
                    H_template=display_seed_H,
                    H_background_template=display_seed_H_bg,
                    fixed_seed_W=fixed_seed_W,
                )
                spectra_per_slice.append(np.array(seed_result["H"][:n_components], copy=True))
                images_per_slice.append(np.array(seed_result["W"][:n_components], copy=True))
                if fit_info_per_slice is not None:
                    fit_info_per_slice.append(
                        None if self.mv_analyzer.last_nnls_info is None else dict(self.mv_analyzer.last_nnls_info)
                    )
                self.worker.progress.emit(int(round(100.0 * (slice_index + 1) / max(1, total_slices))))
                continue

            if custom_init:
                self.mv_analyzer.seed_H = None if display_seed_H is None else np.array(display_seed_H, copy=True)
                self.mv_analyzer.seed_H_background_flag = None if display_seed_H_bg is None else np.array(display_seed_H_bg, copy=True)
                self.mv_analyzer.seed_W = None
                self.mv_analyzer._W_prepared = False
                self.mv_analyzer.estimate_W_seed_matrix_from_H(
                    overwrite=True,
                    skip_components=fixed_seed_W.keys(),
                )
                self.mv_analyzer.set_up_missing_W_seeds(skip_spectral_info=True, fill_H_seed=False)
                if self.mv_analyzer.seed_W is None:
                    self.mv_analyzer.seed_W = np.zeros((self.mv_analyzer.data_2d.shape[0], n_components), dtype=np.float64)
                for comp, fixed_W in fixed_seed_W.items():
                    if 0 <= comp < n_components and fixed_W.shape[0] == self.mv_analyzer.seed_W.shape[0]:
                        self.mv_analyzer.seed_W[:, comp] = fixed_W
                self.mv_analyzer._W_prepared = np.all(self.mv_analyzer.seed_W)
                self.mv_analyzer.NNMF(skip_seed_fining=True)
            else:
                self.mv_analyzer.randomNNMF()

            spectra_per_slice.append(np.array(self.mv_analyzer.fixed_H[:n_components], copy=True))
            images_per_slice.append(np.array(self.mv_analyzer.fixed_W_2D[:n_components], copy=True))
            if fit_info_per_slice is not None:
                fit_info_per_slice.append(
                    None if self.mv_analyzer.last_nnmf_info is None else dict(self.mv_analyzer.last_nnmf_info)
                )
            self.worker.progress.emit(int(round(100.0 * (slice_index + 1) / max(1, total_slices))))

        self._analysis_result_spectra = np.stack(spectra_per_slice, axis=0)
        self._analysis_result_images = np.stack(images_per_slice, axis=0)
        self._analysis_fit_info = fit_info_per_slice
        self.worker.progress.emit(100)

        if display_data is not None:
            self.z3D_data = display_data
            self.mv_analyzer.update_image_data(display_data, n_components, wavenumbers)
            if spectral_info is not None:
                self.mv_analyzer.update_spectral_info(spectral_info)
            self.mv_analyzer.set_custom_nnmf_init(custom_init)
            self.mv_analyzer.set_nnmf_solver(solver)
            self.mv_analyzer.set_nnmf_backend_preference(backend_preference)
            self.mv_analyzer.set_W_seed_mode(w_seed_mode)
            self._update_multislice_modified_data(display_data)
            self.mv_analyzer.seed_H = None if display_seed_H is None else np.array(display_seed_H, copy=True)
            self.mv_analyzer.seed_H_background_flag = None if display_seed_H_bg is None else np.array(display_seed_H_bg, copy=True)
            self.mv_analyzer.seed_W = None if display_seed_W is None else np.array(display_seed_W, copy=True)
            self.mv_analyzer._W_prepared = bool(self.mv_analyzer.seed_W is not None and np.all(self.mv_analyzer.seed_W))

    def _prepare_fixed_h_seed_template(self, show_seeds: bool = True, fill_missing_h: bool = True):
        """
        Build the reusable H/fixed-W seed template once on the currently displayed slice.
        This deliberately skips the full W construction because fixed-H modes rebuild or
        solve W separately afterwards.
        """
        self._ensure_nnls_seed_mode_selected()
        self._fixed_seed_W = {}
        self._fixed_seed_W_counts = {}

        self.reload_H_seeds_from_rois()
        logger.info("Processing reusable H seeds for fixed-H analysis modes")
        _, _, seed_pixels = self._make_W_seeds_from_spectral_info(make_H_seeds=True, debug_mode=False)

        if fill_missing_h:
            logger.info('Ensuring all H seeds are available before per-slice W reconstruction.')
            self.mv_analyzer.set_up_missing_H_seeds()

        if not show_seeds:
            return

        seed_result = self._build_fixed_h_seed_result(
            H_template=self.mv_analyzer.seed_H,
            H_background_template=self.mv_analyzer.seed_H_background_flag,
            fixed_seed_W=self._fixed_seed_W,
        )
        self.show_seed_window(seed_result["W"].transpose(1, 2, 0), seed_result["H"], seed_pixels)

    def _fixed_h_mode_enabled(self) -> bool:
        return bool(
            self.nnmf_radio.isChecked()
            and self.fixed_h_nnls_only_check is not None
            and self.fixed_h_nnls_only_check.isChecked()
        )

    def _use_fixed_h_nnls_only(self) -> bool:
        return self._fixed_h_mode_enabled() and self._analysis_series_4d is None

    def _use_fast_multislice_nnmf(self) -> bool:
        return self._fixed_h_mode_enabled() and self._analysis_series_4d is not None

    def _sync_fixed_h_mode_seed_requirements(self, state=None):
        fixed_h_mode = self._fixed_h_mode_enabled()
        if fixed_h_mode:
            self._ensure_nnls_seed_mode_selected()
        if self.w_seed_mode_dropdown is not None:
            self.w_seed_mode_dropdown.setEnabled(not fixed_h_mode)

    def _ensure_nnls_seed_mode_selected(self):
        target_label = "NNLS abundance map"
        if self.w_seed_mode_dropdown is not None:
            for idx in range(self.w_seed_mode_dropdown.count()):
                if self.w_seed_mode_dropdown.itemData(idx) == target_label:
                    if self.w_seed_mode_dropdown.currentIndex() != idx:
                        blocker = QtCore.QSignalBlocker(self.w_seed_mode_dropdown)
                        self.w_seed_mode_dropdown.setCurrentIndex(idx)
                        del blocker
                    break
        self.mv_analyzer.set_W_seed_mode(target_label)

    def _build_fixed_h_seed_result(
            self,
            *,
            H_template: np.ndarray | None,
            H_background_template: np.ndarray | None,
            fixed_seed_W: dict[int, np.ndarray],
    ) -> dict:
        self._ensure_nnls_seed_mode_selected()
        self.mv_analyzer.seed_H = None if H_template is None else np.array(H_template, copy=True)
        self.mv_analyzer.seed_H_background_flag = None if H_background_template is None else np.array(H_background_template, copy=True)
        self.mv_analyzer.seed_W = None
        self.mv_analyzer._W_prepared = False
        self._rebuild_W_seeds_from_H(overwrite_existing=self._overwrite_existing_W_from_H)
        self.mv_analyzer.set_up_missing_W_seeds(skip_spectral_info=True, fill_H_seed=False)
        if self.mv_analyzer.seed_W is None:
            self.mv_analyzer.seed_W = np.zeros((self.mv_analyzer.data_2d.shape[0], self.mv_analyzer.get_n_components()), dtype=np.float64)
        for comp, fixed_W in fixed_seed_W.items():
            if 0 <= comp < self.mv_analyzer.seed_W.shape[1] and fixed_W.shape[0] == self.mv_analyzer.seed_W.shape[0]:
                self.mv_analyzer.seed_W[:, comp] = fixed_W
        self.mv_analyzer._W_prepared = bool(np.all(self.mv_analyzer.seed_W))
        self._log_last_nnls_summary()
        return {
            "H": np.array(self.mv_analyzer.seed_H, copy=True),
            "W": self.mv_analyzer.seed_W.reshape(
                self.mv_analyzer.raw_data_3d.shape[1],
                self.mv_analyzer.raw_data_3d.shape[2],
                -1,
            ).transpose(2, 0, 1),
        }

    def _log_last_nnls_summary(self):
        info = getattr(self.mv_analyzer, "last_nnls_info", None)
        if not info:
            logger.info("NNLS finished without an available backend summary.")
            return

        backend = info.get("backend", "unknown")
        algorithm = info.get("algorithm", "nnls")
        source = info.get("source", "unknown")
        final_error = info.get("final_error")
        relative_error = info.get("relative_error")
        tol = info.get("tol")
        cache_hit = bool(info.get("cache_hit", False))
        n_iter = info.get("n_iter")
        max_chunk_iter = info.get("max_chunk_iter")
        mean_chunk_iter = info.get("mean_chunk_iter")

        logger.info(
            "NNLS finished: backend=%s, algorithm=%s, source=%s, cache_hit=%s, final_error=%s, relative_error=%s, tol=%s",
            backend,
            algorithm,
            source,
            cache_hit,
            final_error,
            relative_error,
            tol,
        )
        if n_iter is not None:
            logger.info("NNLS iterations: %s", n_iter)
        if max_chunk_iter is not None:
            logger.info("NNLS max chunk iterations: %s", max_chunk_iter)
        if mean_chunk_iter is not None:
            logger.info("NNLS mean chunk iterations: %s", mean_chunk_iter)

    def _apply_fixed_W_overrides_to_results(self, fixed_seed_W: dict[int, np.ndarray]):
        if not fixed_seed_W or self.mv_analyzer.fixed_W is None:
            return
        updated = False
        for comp, fixed_W in fixed_seed_W.items():
            if 0 <= comp < self.mv_analyzer.fixed_W.shape[1] and fixed_W.shape[0] == self.mv_analyzer.fixed_W.shape[0]:
                self.mv_analyzer.fixed_W[:, comp] = fixed_W
                updated = True
        if updated:
            self.mv_analyzer.fixed_W_2D = self.mv_analyzer.reshape_2d_3d_mv_data(self.mv_analyzer.fixed_W)

    def _update_multislice_modified_data(self, slice_data: np.ndarray):
        subtract_row = None
        for row in range(self.roi_manager.roi_table.rowCount()):
            sub_cb = self.roi_manager.roi_table.cellWidget(row, self.roi_manager.widget_columns["Subtract"])
            if sub_cb is not None and sub_cb.isChecked():
                subtract_row = row
                break
        if subtract_row is None:
            self.mv_analyzer.update_resonance_image_data(np.array([]))
            return

        roi = self.roi_manager.rois[subtract_row] if subtract_row < len(self.roi_manager.rois) else None
        if roi is None:
            self.mv_analyzer.update_resonance_image_data(np.array([]))
            return

        try:
            z_stack = roi.getArrayRegion(
                slice_data,
                self.roi_manager.image_view.imageItem,
                axes=(2, 1),
                returnMappedCoords=False,
            )
            if z_stack is None or z_stack.size == 0:
                self.mv_analyzer.update_resonance_image_data(np.array([]))
                return
            spectral_background = np.mean(z_stack, axis=(1, 2))
            tiled_background = spectral_background[:, np.newaxis, np.newaxis]
            subtracted_data = slice_data - tiled_background
            subtracted_data[subtracted_data <= 0] = sys.float_info.epsilon
            self.mv_analyzer.update_resonance_image_data(subtracted_data)
        except Exception as exc:
            logger.warning("Could not update per-slice processed data for 4D analysis. Falling back to raw data. Error: %s", exc)
            self.mv_analyzer.update_resonance_image_data(np.array([]))

    def _handle_component_count_changed(self, n_components: int):
        self.mv_analyzer.update_components(n_components)

    def import_current_result_component(self, target: str, component_index: int, slice_index: int = 0) -> bool:
        """
        Main input point to set ROIs with dummy data for W and H in the ROI Manager.
        Works with references of the NNMF result `fixed_W` and `fixed_H`.
        These dummy ROIs will be evaluated during the subsequent seed generation process.
        """
        mode = (target or "").strip().lower()
        if mode not in {"h", "w", "both"}:
            logger.warning('Unknown result-to-seed target requested: %s', target)
            return False

        fixed_H = self._analysis_result_spectra
        fixed_W_images = self._analysis_result_images
        if fixed_H is None or fixed_W_images is None:
            fixed_H = self.mv_analyzer.fixed_H
            fixed_W = self.mv_analyzer.fixed_W
        else:
            fixed_H = np.asarray(fixed_H)
            fixed_W_images = np.asarray(fixed_W_images)
            if fixed_H.ndim == 3:
                slice_index = int(np.clip(slice_index, 0, fixed_H.shape[0] - 1))
                fixed_H = fixed_H[slice_index]
            if fixed_W_images.ndim == 4:
                slice_index = int(np.clip(slice_index, 0, fixed_W_images.shape[0] - 1))
                fixed_W = fixed_W_images[slice_index].reshape(fixed_W_images.shape[1], -1).T
            else:
                fixed_W = fixed_W_images.reshape(fixed_W_images.shape[0], -1).T

        if fixed_H is None or fixed_W is None:
            QtWidgets.QMessageBox.warning(
                self.analysis_widget,
                "No NNMF result available",
                "Run NNMF first before copying the current result into the seed initialization.",
            )
            return False

        expected_H_shape = (self.mv_analyzer.get_n_components(), self.mv_analyzer.raw_data_3d.shape[0])
        expected_W_shape = (self.mv_analyzer.data_2d.shape[0], self.mv_analyzer.get_n_components())
        fixed_H = np.asarray(fixed_H, dtype=np.float64)
        fixed_W = np.asarray(fixed_W, dtype=np.float64)
        if fixed_H.shape != expected_H_shape or fixed_W.shape != expected_W_shape:
            QtWidgets.QMessageBox.warning(
                self.analysis_widget,
                "Result/seed shape mismatch",
                "The current NNMF result no longer matches the loaded dataset or component count.",
            )
            logger.warning(
                'Cannot promote current results to seeds because of shape mismatch: H %s vs %s, W %s vs %s.',
                fixed_H.shape,
                expected_H_shape,
                fixed_W.shape,
                expected_W_shape,
            )
            return False

        if not 0 <= component_index < expected_H_shape[0]:
            QtWidgets.QMessageBox.warning(
                self.analysis_widget,
                "Invalid component",
                f"Component {component_index + 1} is outside the current NNMF result range.",
            )
            return False

        if mode == "w":
            spectrum_name = f"Result W{component_index}"
        elif mode == "both":
            spectrum_name = f"Result H+W {component_index}"
        else:
            spectrum_name = f"Result H{component_index}"
        self.roi_manager.add_dummy_roi(
            spectrum_data=fixed_H[component_index],
            component_number=component_index + 1,
            spectrum_name=spectrum_name,
            fixed_W=fixed_W[:, component_index] if mode in {"w", "both"} else None,
            seed_H_enabled=(mode != "w"),
            result_seed_dummy=False,
        )
        logger.info('Imported NNMF result component %s as %s dummy ROI.', component_index, mode)
        return True

    def make_all_seeds_from_inputs(self, show_seeds=True):
        """
        1. Reload H seeds from ROIs
        2. Process spectral info (initialize also H components from it that are not yet defined via seed pixels)
        3. Rebuild W seeds from the chosen H-to-W method wherever an H seed exists
           or only fill missing W columns, depending on the W overwrite setting
        4. Fill any remaining W seeds with a fallback image-based seed
        5. Randomly initialize only the H seeds that are still missing
        Parameters
        ----------
        show_seeds: bool
            If True, a seed window will be displayed showing the generated seeds.

        Returns
        -------

        """
        self._fixed_seed_W = {}  # reset fixed W seeds
        self._fixed_seed_W_counts = {}

        self.reload_H_seeds_from_rois()     # reset all existing seeds and reload ROIs
        # make seeds from user inputs inside the roi manager (highest priority for H, and user inputs for W from the table)



        logger.info("Processing user inputs for W seeds and H from ROIs")
        seed_W, seed_H, seed_pixels = self._make_W_seeds_from_spectral_info(make_H_seeds=True,
                                                                            debug_mode=False)  # create W seeds from spectral info and pass to analyzer

        logger.info(
            'Updating W seeds from the current H seeds using %s (overwrite_existing=%s).',
            self.mv_analyzer.w_seed_mode,
            self._overwrite_existing_W_from_H,
        )
        self._rebuild_W_seeds_from_H(overwrite_existing=self._overwrite_existing_W_from_H)

        logger.info('Filling remaining W seeds after H-based initialization.')
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

    def _rebuild_W_seeds_from_H(self, overwrite_existing: bool = True):
        self.mv_analyzer.estimate_W_seed_matrix_from_H(
            overwrite=overwrite_existing,
            skip_components=self._fixed_seed_W.keys()
        )

    def show_seed_window(self, seed_W_3d, seed_H, seed_pixels):
        if self.seed_window is None:
            self.seed_window = SeedWidget(
                seed_W_3d,
                seed_H,
                self.wavenumbers,
                seed_pixels,
                self.roi_manager.get_color_rgba
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
        self._fixed_seed_W = {}
        self._fixed_seed_W_counts = {}
        # extract the fixed images that should serve as seed and set them fixed
        for row, roi in enumerate(self.roi_manager.rois):
            if not hasattr(roi, "fixed_W"):
                continue
            component_index = self.roi_manager.component_number_from_table_index(row)
            if component_index is None:
                continue
            self.set_fixed_W_seed(component_index, roi.fixed_W)
            logger.info(f'Setting fixed W seed for component {component_index} from ROI')
        for i, seed_dict in enumerate(seeds_list):
            component_number = int(seed_dict['resonance'].strip('Component '))
            component_index =  component_number - 1

            flag_bgd = bool(seed_dict.get('is_background', False))
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
        Store a fixed W seed for a specific component for later analysis.

        If multiple ROIs provide a fixed W seed for the same component, the
        stored map is updated by a running mean and a warning is logged.

        Args:
            component (int): The component index.
            fixed_W (np.ndarray): The fixed W seed array of shape (n_pixels,).
        """
        fixed_W = np.asarray(fixed_W, dtype=np.float64)
        current_W_seed_cmp = self._fixed_seed_W.get(component, None)
        if current_W_seed_cmp is None:
            self._fixed_seed_W[component] = fixed_W
            self._fixed_seed_W_counts[component] = 1
        else:
            count = self._fixed_seed_W_counts.get(component, 1)
            # Repeatedly using (old + new) / 2 would bias the mean toward the most recent ROI.
            cmp_avg = (current_W_seed_cmp * count + fixed_W) / (count + 1)
            self._fixed_seed_W[component] = cmp_avg
            self._fixed_seed_W_counts[component] = count + 1
            logger.warning(f"Component {component} has multiple fixed W seeds from different ROIs."
                           f" Averaging them together. This may indicate overlapping ROIs with different spatial seed maps.")


    def analysis_completed(self, analysis_method):
        logger.info(f"{datetime.now()}: {analysis_method} finished ")
        # Emit signal to the application
        # TODO: run in new thread, plotting takes time!
        self.analysis_data_changed.emit(*self.get_analysis_data())

    def update_analysis_method(self, method):
        self.mv_analyzer.analysis_method = method
        self._sync_analysis_mode_controls()

    def _begin_analysis_progress(self, total_slices: int):
        if self.analysis_progress_widget is None or self.analysis_progress_bar is None or self.analysis_progress_label is None:
            return
        total_slices = max(1, int(total_slices))
        self.analysis_progress_label.setText(f"Slice progress 0/{total_slices}")
        self.analysis_progress_bar.setRange(0, 100)
        self.analysis_progress_bar.setValue(0)
        self.analysis_progress_widget.setEnabled(True)

    def _update_analysis_progress(self, percent: int):
        if self.analysis_progress_widget is None or self.analysis_progress_bar is None or self.analysis_progress_label is None:
            return
        if self._analysis_series_4d is None:
            return
        total_slices = max(1, int(self._analysis_series_4d.shape[0]))
        percent = int(np.clip(percent, 0, 100))
        completed = min(total_slices, int(round((percent / 100.0) * total_slices)))
        self.analysis_progress_label.setText(f"Slice progress {completed}/{total_slices}")
        self.analysis_progress_bar.setValue(percent)

    def _finish_analysis_progress(self):
        if self.analysis_progress_widget is None or self.analysis_progress_bar is None or self.analysis_progress_label is None:
            return
        self.analysis_progress_bar.setValue(0)
        self.analysis_progress_label.setText("Slice progress")
        self.analysis_progress_widget.setEnabled(False)

    def _sync_analysis_mode_controls(self):
        use_nnmf = bool(self.nnmf_radio.isChecked())
        for widget in self._nnmf_option_widgets:
            if widget is not None:
                widget.setEnabled(use_nnmf)
        self._sync_fixed_h_mode_seed_requirements()
        self._sync_nnmf_backend_controls()

    def _sync_nnmf_backend_controls(self):
        if self.nnmf_backend_dropdown is None:
            return
        use_backend_selector = self.mv_analyzer.nnmf_solver == "mu" and self.nnmf_radio.isChecked()
        self.nnmf_backend_dropdown.setEnabled(use_backend_selector)

    def get_analysis_data(self) -> (np.ndarray, np.ndarray):
        if self._analysis_result_spectra is not None and self._analysis_result_images is not None:
            return self._analysis_result_spectra, self._analysis_result_images
        if self.pca_radio.isChecked():
            return self.mv_analyzer.PCs, self.mv_analyzer.pca_2DX
        return self.mv_analyzer.fixed_H, self.mv_analyzer.fixed_W_2D

    def get_analysis_fit_info(self) -> dict | list[dict | None] | None:
        if self._analysis_fit_info is not None:
            return self._analysis_fit_info
        if self.pca_radio.isChecked():
            return None
        if self.mv_analyzer.last_nnmf_info is not None:
            return dict(self.mv_analyzer.last_nnmf_info)
        if self.mv_analyzer.last_nnls_info is not None:
            return dict(self.mv_analyzer.last_nnls_info)
        return None

    def _refresh_resonance_table_layout(self):
        header = self.resonance_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        auto_widths = getattr(self, "_resonance_table_auto_widths", {})
        checkbox_columns = {"Use subtracted data", "Use Gaussian"}
        indicator_width = self.resonance_table.style().pixelMetric(QtWidgets.QStyle.PM_IndicatorWidth) + 16

        default_widths = {
            "Component": 130,
            "Wavenumber": 120,
            "# Seed Pixels": 120,
            "Amplitude": 110,
            "Color": 64,
            "Width": 72,
            "Use subtracted data": 136,
            "Use Gaussian": 110,
            "Remove": 88,
        }
        for name, width in default_widths.items():
            if name in self.res_settings_widget_columns:
                column = self.res_settings_widget_columns[name]
                desired_width = width
                if name in checkbox_columns:
                    header_item = self.resonance_table.horizontalHeaderItem(column)
                    header_text = header_item.text() if header_item is not None else name
                    desired_width = max(header.fontMetrics().horizontalAdvance(header_text) + 12, indicator_width)

                current_width = self.resonance_table.columnWidth(column)
                previous_auto_width = auto_widths.get(column)
                if previous_auto_width is None or abs(current_width - previous_auto_width) <= 2 or current_width < desired_width:
                    self.resonance_table.setColumnWidth(column, desired_width)
                    auto_widths[column] = desired_width

        flexible_columns = [
            self.res_settings_widget_columns[name]
            for name in ("Component", "Wavenumber", "# Seed Pixels", "Amplitude")
            if name in self.res_settings_widget_columns
        ]
        available_width = self.resonance_table.viewport().width()
        current_width = sum(self.resonance_table.columnWidth(col) for col in range(self.resonance_table.columnCount()))
        extra_width = available_width - current_width
        if extra_width > 0 and flexible_columns:
            extra_per_column, remainder = divmod(extra_width, len(flexible_columns))
            for index, column in enumerate(flexible_columns):
                new_width = self.resonance_table.columnWidth(column) + extra_per_column + (1 if index < remainder else 0)
                self.resonance_table.setColumnWidth(column, new_width)
                auto_widths[column] = new_width

        self.resonance_table.resizeRowsToContents()
        self._resonance_table_auto_widths = auto_widths

    def add_resonance_settings(self):
        # Add a row to the table
        row_position = self.resonance_table.rowCount()
        self.resonance_table.insertRow(row_position)

        # 1. Component Selection
        item_comp = QtWidgets.QComboBox()
        item_comp.addItems([f"Component {i + 1}" for i in range(9)])
        item_comp.setCurrentIndex(row_position % 9)
        # Determine the initial component index
        comp_idx = row_position % 9

        if self.color_manager:
            # Color Button
            # Get color from manager
            initial_color = self.color_manager.get_qcolor(comp_idx)
            btn_color = ColorButton(initial_color)

            # Define a closure to capture the row and component correctly
            # We need to know which component is currently selected in this row
            def on_color_picked(new_color):
                current_comp_idx = self.get_component_index(row_position)
                if current_comp_idx is not None:
                    self.color_manager.set_color(current_comp_idx, new_color)

            btn_color.color_changed.connect(on_color_picked)

            # Also, if the user changes the "Component" Combobox, we must update the button color
            def on_component_changed(index):
                # The combo box changed, so fetch the color for the NEW component ID
                new_c_idx = self.get_component_index(row_position)
                c = self.color_manager.get_qcolor(new_c_idx)
                btn_color.setColor(c)
                self.callback_res_settings(row_position)

            item_comp.currentIndexChanged.connect(on_component_changed)
            # Set widgets in table
            self.resonance_table.setCellWidget(row_position, self.res_settings_widget_columns["Color"], btn_color)

        self.resonance_table.setCellWidget(row_position, self.res_settings_widget_columns["Component"], item_comp)

        # 3. Remove button
        widget_remove = QtWidgets.QPushButton("Remove")
        widget_remove.clicked.connect(lambda: self.remove_res_settings(row_position))
        self.resonance_table.setCellWidget(row_position, self.res_settings_widget_columns["Remove"], widget_remove)

        # Add text fields from column 2 to 4
        spinbox_columns = [1, 2, 3, 6]
        if self.color_manager is not None:
            spinbox_columns = [col + 1 for col in spinbox_columns]
        for column in spinbox_columns: # Columns 1, 2, 3, 4 are SpinBoxes
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
        self._refresh_spectral_column_labels()
        self.callback_res_settings(row_position)
        self._refresh_resonance_table_layout()

    def reload_colors(self):
        if self.color_manager is None:
            return
        for row in range(self.resonance_table.rowCount()):
            comp_idx = self.get_component_index(row)
            color = self.color_manager.get_qcolor(comp_idx)
            btn_color: ColorButton = self.resonance_table.cellWidget(row, self.res_settings_widget_columns["Color"])
            btn_color.setColor(color)

    def scale_w_to_16bit_enabled(self) -> bool:
        if self.scale_w_to_16bit_check is None:
            return True
        return bool(self.scale_w_to_16bit_check.isChecked())

    def remove_res_settings(self, row):
        self.resonance_table.removeRow(row)
        self._refresh_resonance_table_layout()
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
        logger.debug('Adjusting pixel threshold from the requested seed-pixel count.')
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
        logger.info(f'Highlighting spectral range: {spectral_range} for component {info["Component"]}')
        self.roi_manager.highlight_component_region(spectral_range, self.get_component_index(row_table))

    def show_W_seeds(self):
        """Open a temporary viewer for inspecting the current W maps."""
        self._fixed_seed_W = {}
        self._fixed_seed_W_counts = {}
        self.reload_H_seeds_from_rois()
        _, _, seed_pixels = self._make_W_seeds_from_spectral_info(make_H_seeds=True, debug_mode=False)
        self._rebuild_W_seeds_from_H(overwrite_existing=self._overwrite_existing_W_from_H)
        self.mv_analyzer.set_up_missing_W_seeds(skip_spectral_info=True, fill_H_seed=False)
        # open a new floating composite_image with the W seeds in a pyqtgraph image view
        W_seed_3d = self.mv_analyzer.seed_W.reshape(self.mv_analyzer.raw_data_3d.shape[1],
                                                    self.mv_analyzer.raw_data_3d.shape[2], -1)
        self.seed_W_view = self.make_W_seed_view(W_seed_3d, seed_pixels=seed_pixels)
        self.seed_W_view.show()

    def make_W_seed_view(self, W_seed_3d, seed_pixels: dict = None, plot_all_seeds: bool = False):
        seed_W_view = ImageViewYX()
        seed_W_view.setImage(W_seed_3d)

        def update_color_channel(cmp: int):
            pen_color = self.roi_manager.get_color_rgba(cmp)
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
                brush=pg.mkBrush(self.roi_manager.get_color_rgba(component)),
                symbol='+',
                pen=pg.mkPen(self.roi_manager.get_color_rgba(component), width=1)
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
            'Use subtracted data': get_value('Use subtracted data', bool, True),
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
        Returns the component index (0-based) for the given row in the resonance table.
        Note: Displayed component 1 is internally represented as 0 etc.
        """
        component_combobox: QtWidgets.QComboBox = self.resonance_table.cellWidget(row, self.res_settings_widget_columns['Component'])
        if component_combobox is None:
            return None
        idx = int(component_combobox.currentText().split(' ')[-1]) - 1
        return idx

    def get_row_index(self, component_idx: int) -> int | None:
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
            if self.get_component_index(row) == component_idx:
                return row
        return None

    def get_row_indices(self, component_idx: int) -> list[int] | None:
        rows = []
        for row in range(self.resonance_table.rowCount()):
            if self.get_component_index(row) == component_idx:
                rows.append(row)
        return rows if rows else None

    def _make_W_seeds_from_spectral_info(self, make_H_seeds=True, debug_mode=True) -> Tuple[np.ndarray, np.ndarray, dict[int, tuple[np.ndarray, np.ndarray]]]:
        """
        Creates W seeds from the spectral information in the resonance table.
        Takes into account the ROI definitions in the ROI manager for H seeds.
        The created seeds are passed to the MV analyzer.

        If a fixed seed of W, i.e. an image, is present in a dummy roi, all spectral
        information is disregarded and the input image will always be treated as fixed seed.

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
        fixed_w_components = set()

        if self._fixed_seed_W:
            for comp, fixed_W in self._fixed_seed_W.items():
                if comp < seed_W.shape[1] and fixed_W.shape[0] == seed_W.shape[0]:
                    seed_W[:, comp] = fixed_W
                    fixed_w_components.add(comp)
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
            if i in fixed_w_components:
                logger.info(
                    'Skipping spectral-info W seed creation for component %s because a fixed W seed is present.',
                    i,
                )
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

    def rolling_background_component_from_projection(self):
        """
        Create a background component using a simple projection of the current
        hyperspectral stack as reference image for the rolling-ball background.

        Returns
        -------

        """
        if self.mv_analyzer.raw_data_3d is None:
            QtWidgets.QMessageBox.information(self.analysis_widget, "Info", "Load an image stack first.")
            return

        projection_mode = self.rolling_ball_projection_combo.currentData() if hasattr(self, "rolling_ball_projection_combo") else "mean"
        if projection_mode == "max":
            projection_image = np.max(self.mv_analyzer.raw_data_3d, axis=0)
        elif projection_mode == "min":
            projection_image = np.min(self.mv_analyzer.raw_data_3d, axis=0)
        else:
            projection_image = np.mean(self.mv_analyzer.raw_data_3d, axis=0)

        self._rolling_ball_background(projection_image)

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

        def add_background_roi():
            self.roi_manager.add_dummy_roi(
                H_bg,
                component_number=int(bg_comp + 1),
                is_background=True,
                spectrum_name="RollingBall BG",
                fixed_W=W_bg,
                seed_H_enabled=False,
            )

        if self.rolling_ball_preview_dialog is not None:
            self.rolling_ball_preview_dialog.close()
            self.rolling_ball_preview_dialog = None

        bg_W_view = self.make_W_seed_view(
            W_bg.reshape(self.mv_analyzer.raw_data_3d.shape[1], self.mv_analyzer.raw_data_3d.shape[2], -1)
        )

        class RollingBallPreviewDialog(QtWidgets.QDialog):
            def __init__(self, parent, image_view, component_number: int, add_callback):
                super().__init__(parent)
                self._add_callback = add_callback
                self._added = False
                self.setWindowTitle(f"Background W Component {component_number}")
                self.resize(640, 720)

                layout = QtWidgets.QVBoxLayout(self)
                layout.setContentsMargins(10, 10, 10, 10)
                layout.setSpacing(8)

                info_label = QtWidgets.QLabel(
                    "Inspect the rolling-ball background map below. "
                    "Press 'Add Background ROI' to store it as a dummy ROI with fixed W."
                )
                info_label.setWordWrap(True)
                layout.addWidget(info_label)
                layout.addWidget(image_view, stretch=1)

                button_row = QtWidgets.QHBoxLayout()
                button_row.addStretch(1)
                add_button = QtWidgets.QPushButton("Add Background ROI")
                add_button.clicked.connect(self._accept_and_add)
                button_row.addWidget(add_button)
                layout.addLayout(button_row)

            def _accept_and_add(self):
                if not self._added:
                    self._add_callback()
                    self._added = True
                self.close()

            def closeEvent(self, event: QtGui.QCloseEvent):
                if self._added:
                    event.accept()
                    return

                reply = QtWidgets.QMessageBox.question(
                    self,
                    "Add Background ROI",
                    "Do you want to add this rolling-ball background component as a dummy ROI with fixed W seed before closing?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel,
                    QtWidgets.QMessageBox.Yes,
                )
                if reply == QtWidgets.QMessageBox.Yes:
                    self._add_callback()
                    self._added = True
                    event.accept()
                elif reply == QtWidgets.QMessageBox.No:
                    event.accept()
                else:
                    event.ignore()

        preview_dialog = RollingBallPreviewDialog(
            self.analysis_widget,
            bg_W_view,
            bg_comp + 1,
            add_background_roi,
        )
        preview_dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        preview_dialog.destroyed.connect(lambda *_: setattr(self, "rolling_ball_preview_dialog", None))
        self.rolling_ball_preview_dialog = preview_dialog
        preview_dialog.show()
        preview_dialog.raise_()
        preview_dialog.activateWindow()

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
            logger.debug('Setting H seed for component %s from %s seed pixels.', component, pixels[0].size)
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

    # ---- import and export
    def export_resonance_table_state(self) -> list[dict]:
        out = []
        for row in range(self.resonance_table.rowCount()):
            comp_cb = self.resonance_table.cellWidget(row, self.res_settings_widget_columns["Component"])
            wn_sb = self.resonance_table.cellWidget(row, self.res_settings_widget_columns["Wavenumber"])
            wd_sb = self.resonance_table.cellWidget(row, self.res_settings_widget_columns["Width"])
            np_sb = self.resonance_table.cellWidget(row, self.res_settings_widget_columns["# Seed Pixels"])
            sub_cb = self.resonance_table.cellWidget(row, self.res_settings_widget_columns["Use subtracted data"])
            ga_cb = self.resonance_table.cellWidget(row, self.res_settings_widget_columns["Use Gaussian"])
            amp_sb = self.resonance_table.cellWidget(row, self.res_settings_widget_columns["Amplitude"])

            out.append({
                "Component": int(comp_cb.currentIndex()) if comp_cb is not None else 0,
                "Wavenumber": float(wn_sb.value()) if wn_sb is not None else 0.0,
                "Width": float(wd_sb.value()) if wd_sb is not None else 0.0,
                "# Seed Pixels": int(np_sb.value()) if np_sb is not None else 0,
                "Use subtracted data": bool(sub_cb.isChecked()) if sub_cb is not None else True,
                "Use Gaussian": bool(ga_cb.isChecked()) if ga_cb is not None else False,
                "Amplitude": float(amp_sb.value()) if amp_sb is not None else 65535.0,
            })
        return out

    def import_resonance_table_state(self, rows: list[dict]):
        # clear table
        while self.resonance_table.rowCount() > 0:
            self.resonance_table.removeRow(0)

        for r in rows:
            self.add_resonance_settings()
            row = self.resonance_table.rowCount() - 1

            blockers = []
            for key in ["Component", "Wavenumber", "Width", "# Seed Pixels", "Use subtracted data", "Use Gaussian",
                        "Amplitude"]:
                w = self.resonance_table.cellWidget(row, self.res_settings_widget_columns[key])
                if w is not None:
                    blockers.append(QtCore.QSignalBlocker(w))

            comp_cb = self.resonance_table.cellWidget(row, self.res_settings_widget_columns["Component"])
            if comp_cb is not None:
                comp_cb.setCurrentIndex(int(r.get("Component", 0)))

            self.resonance_table.cellWidget(row, self.res_settings_widget_columns["Wavenumber"]).setValue(
                float(r.get("Wavenumber", 0.0)))
            self.resonance_table.cellWidget(row, self.res_settings_widget_columns["Width"]).setValue(
                float(r.get("Width", 0.0)))
            self.resonance_table.cellWidget(row, self.res_settings_widget_columns["# Seed Pixels"]).setValue(
                int(r.get("# Seed Pixels", 150)))

            sub_cb = self.resonance_table.cellWidget(row, self.res_settings_widget_columns["Use subtracted data"])
            if sub_cb is not None:
                sub_cb.setChecked(bool(r.get("Use subtracted data", True)))

            ga_cb = self.resonance_table.cellWidget(row, self.res_settings_widget_columns["Use Gaussian"])
            if ga_cb is not None:
                ga_cb.setChecked(bool(r.get("Use Gaussian", False)))

            self.resonance_table.cellWidget(row, self.res_settings_widget_columns["Amplitude"]).setValue(
                float(r.get("Amplitude", 65535)))

            del blockers

        # The component combobox is restored under signal blockers above, so the
        # usual currentIndexChanged path never gets a chance to sync the row color
        # button from the shared component color manager.
        self.reload_colors()

        # now propagate to analyzer + gaussian dummy ROIs + highlights
        self.update_spectral_info()
        self.highlight_all_resonances()

    def export_seed_init_state(self) -> dict:
        mode = self.mv_analyzer.w_seed_mode
        if self.w_seed_mode_dropdown is not None:
            mode = self.w_seed_mode_dropdown.itemData(self.w_seed_mode_dropdown.currentIndex())

        seed_pixel_metric = self._seed_pixel_mode
        if self.seed_pixel_mode_dropdown is not None:
            seed_pixel_metric = self.seed_pixel_mode_dropdown.currentText()

        return {
            "w_seed_mode": mode,
            "overwrite_existing_w_from_h": bool(self._overwrite_existing_W_from_H),
            "seed_pixel_metric": seed_pixel_metric,
            "fixed_h_nnls_mode": bool(self._fixed_h_mode_enabled()),
            "fixed_h_nnls_only": bool(self._use_fixed_h_nnls_only()),
            "fast_multislice_nnmf": bool(self._use_fast_multislice_nnmf()),
            "scale_results_to_16bit": bool(self.scale_w_to_16bit_enabled()),
        }

    def import_seed_init_state(self, state: dict | list | tuple | None):
        if state is None:
            return

        if isinstance(state, dict):
            settings = dict(state)
        elif isinstance(state, (list, tuple)) and len(state) >= 3:
            full, avg, h_weighted = [bool(v) for v in state[:3]]
            if h_weighted:
                mode = "H weights"
            elif full:
                mode = "Homogeneous (empty)"
            elif avg:
                mode = "Average image"
            else:
                mode = "NNLS abundance map"
            settings = {
                "w_seed_mode": mode,
                "overwrite_existing_w_from_h": False,
            }
        else:
            return

        mode = settings.get("w_seed_mode", "NNLS abundance map")
        if self.w_seed_mode_dropdown is not None:
            blocker = QtCore.QSignalBlocker(self.w_seed_mode_dropdown)
            for idx in range(self.w_seed_mode_dropdown.count()):
                if self.w_seed_mode_dropdown.itemData(idx) == mode:
                    self.w_seed_mode_dropdown.setCurrentIndex(idx)
                    break
            del blocker
        self.mv_analyzer.set_W_seed_mode(mode)

        overwrite_existing = bool(settings.get("overwrite_existing_w_from_h", False))
        self._overwrite_existing_W_from_H = overwrite_existing
        if self.overwrite_W_from_H_check is not None:
            blocker = QtCore.QSignalBlocker(self.overwrite_W_from_H_check)
            self.overwrite_W_from_H_check.setChecked(overwrite_existing)
            del blocker

        seed_pixel_metric = settings.get("seed_pixel_metric")
        if seed_pixel_metric in {"Max Intensity", "Score"}:
            self._seed_pixel_mode = seed_pixel_metric
            if self.seed_pixel_mode_dropdown is not None:
                blocker = QtCore.QSignalBlocker(self.seed_pixel_mode_dropdown)
                self.seed_pixel_mode_dropdown.setCurrentText(seed_pixel_metric)
                del blocker

        fixed_h_mode = bool(
            settings.get(
                "fixed_h_nnls_mode",
                bool(settings.get("fixed_h_nnls_only", False) or settings.get("fast_multislice_nnmf", False)),
            )
        )
        if self.fixed_h_nnls_only_check is not None:
            blocker = QtCore.QSignalBlocker(self.fixed_h_nnls_only_check)
            self.fixed_h_nnls_only_check.setChecked(fixed_h_mode)
            del blocker
        self._sync_fixed_h_mode_seed_requirements()

        if self.scale_w_to_16bit_check is not None:
            blocker = QtCore.QSignalBlocker(self.scale_w_to_16bit_check)
            scale_results = bool(
                settings.get(
                    "scale_results_to_16bit",
                    settings.get("scale_w_to_16bit", settings.get("scale_nnmf_result_to_max", True)),
                )
            )
            self.scale_w_to_16bit_check.setChecked(scale_results)
            del blocker

    def _refresh_spectral_column_labels(self):
        # Header text (keep your internal column keys "Wavenumber"/"Width"!)
        wn_col = self.res_settings_widget_columns.get("Wavenumber")
        wd_col = self.res_settings_widget_columns.get("Width")
        axis_labels = getattr(self, "axis_labels", None)
        unit = getattr(self, "spectral_units", "cm⁻¹")
        wn_label = "Channel" if axis_labels is not None else ("Wavelength (nm)" if unit == "nm" else "Wavenumber (cm⁻¹)")
        wd_label = "Width (channels)" if axis_labels is not None else ("Width (nm)" if unit == "nm" else "Width (cm⁻¹)")
        suffix = " ch" if axis_labels is not None else (" nm" if unit == "nm" else " cm⁻¹")
        if wn_col is not None:
            item = self.resonance_table.horizontalHeaderItem(wn_col)
            if item:
                item.setText(wn_label)
        if wd_col is not None:
            item = self.resonance_table.horizontalHeaderItem(wd_col)
            if item:
                item.setText(wd_label)

        # Spinbox suffixes for existing rows
        for row in range(self.resonance_table.rowCount()):
            wn_sb = self.resonance_table.cellWidget(row, wn_col) if wn_col is not None else None
            wd_sb = self.resonance_table.cellWidget(row, wd_col) if wd_col is not None else None
            if hasattr(wn_sb, "setSuffix"):
                wn_sb.setSuffix(suffix)
            if hasattr(wd_sb, "setSuffix"):
                wd_sb.setSuffix(suffix)

    def set_axis_labels(self, labels):
        self.axis_labels = None if labels is None else [str(label) for label in labels]
        self._refresh_spectral_column_labels()

    def set_spectral_units(self, unit: str):
        unit = "nm" if (unit or "").strip().lower() == "nm" else "cm⁻¹"
        self.spectral_units = unit
        self._refresh_spectral_column_labels()

        # If seed window is open, update its axis label too
        if getattr(self, "seed_window", None) is not None:
            self.seed_window.set_spectral_units(unit)

class SeedWidget(QtWidgets.QWidget):
    default_colors = CompositeImageViewWidget.colormap_colors
    def __init__(self, seed_W_3d: np.ndarray, seed_H: np.ndarray, wavenumbers,
                 seed_pixels: dict or None = None, color_getter = None,):
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

    def set_spectral_units(self, units: str):
        if units != 'nm':
            self.seed_H_plot.setLabel('bottom', 'Wavenumber [1/cm]')
        else:
            self.seed_H_plot.setLabel('bottom', 'Wavelength [nm]')

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
