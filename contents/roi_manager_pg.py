import logging
import sys
from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtGui import QColor
from pyqtgraph.dockarea import Dock
from scipy.ndimage import gaussian_filter1d, gaussian_filter, label, maximum_filter

from composite_image import max_dtype_val, CompositeImageViewWidget as ci
from contents.custom_pyqt_objects import ImageViewYX
from contents.hs_image_view import ROITableDelegate, ColorButton
from contents.spectrum_loader import SpectrumLoader

logger = logging.getLogger('ROI Manager')


@dataclass(slots=True)
class AutoROISuggestionSettings:
    projection_mode: str = "Average image"
    use_processed_data: bool = False
    local_background_sigma: float = 8.0
    spatial_bin_factor: int = 1
    smoothing_sigma: float = 2
    threshold_ratio: float = 0.40
    peak_region_ratio: float = 0.72
    peak_window: int = 5
    min_group_area: int = 6
    min_roi_diagonal_px: int = 0
    max_groups_per_component: int = 4
    max_rois_per_group: int = 2
    candidate_pool_factor: int = 6
    padding_px: int = 4
    merge_similar_spectra: bool = True
    spectral_similarity_threshold: float = 0.9
    spectral_smoothing_sigma: float = 1.0
    replace_previous_auto: bool = True


@dataclass(slots=True)
class AutoROISuggestion:
    component: int
    y: int
    x: int
    height: int
    width: int
    score: float

class ROIManager(QtCore.QObject):
    max_component_slots = 9
    default_colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255),
                      (255, 255, 255), (128, 128, 128), (128, 0, 0), (128, 128, 0), (0, 128, 0), (128, 0, 128),
                      (0, 128, 128), (0, 0, 128)]
    new_roi_signal = QtCore.pyqtSignal(int)  # Signal to inform about new ROIs
    plot_roi_signal = QtCore.pyqtSignal(str, np.ndarray, str)  # Signal with ROI index and signal
    remove_roi_plot_signal = QtCore.pyqtSignal(str)  # Signal to inform about removed plots.
    processed_data_signal = QtCore.pyqtSignal(np.ndarray)  # Signal to send the processed data to the main composite_image
    color_change_signal = QtCore.pyqtSignal(int, tuple)  # Signal when color is changed in the ROI table
    label_change_signal = QtCore.pyqtSignal(int, str)  # Signal when label is changed in the ROI table
    preset_load_signal = QtCore.pyqtSignal(int, object, object)  # Signal to load a preset

    def __init__(self, image_view: pg.ImageView, color_manager=None):
        super().__init__()
        self.image_view = image_view
        self.spectral_units = "cm⁻¹"
        self.rois = []  # list that stores each roi object sorted by index
        self.gaussian_specs_by_component: dict[int, list[tuple[float, float, float]]] = {}
        self.roi_region_change_signals = {}
        self.roi_click_signals = {}
        self.active_roi = None
        self.fill_roi = None
        self.subtract_signal = None
        self.wavenumbers = None
        self.roi_id_idx = {}
        self._selection_sync_in_progress = False
        self._highlighted_table_row = None
        self.raw_data = self.image_view.getImageItem().image
        self.subtracted_data = None
        self.spectrum_loaders = dict()
        self.auto_roi_settings = AutoROISuggestionSettings()
        self.fixed_w_seed_view = None
        # Creating a dock
        # Set up the ROI table and add it to the ROI table dock
        self.roi_table_dock = Dock("Seed ROIs", size=(810, 500))
        self.roi_table = QtWidgets.QTableWidget()
        cols = ['Name', 'Color', 'Resonance', 'Background', 'Subtract', 'Scale', 'Offset', 'Gaussian σ', 'Export',
                'ROI Shape', 'Live Update', 'Plot', 'Show', 'Remove']
        self.widget_columns = dict(**{col: idx for idx, col in enumerate(cols)})
        self.roi_table.setColumnCount(len(cols))
        self.roi_table.setHorizontalHeaderLabels(cols)
        self.roi_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.roi_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)

        self.color_manager = color_manager

        # Connect the selection changed signal of the table to a slot
        self.roi_table.currentCellChanged.connect(self.update_selected_roi)
        self.roi_table.setItemDelegateForColumn(3, ROITableDelegate(self.roi_table))
        button_style = self.roi_table.style()

        def themed_button_icon(theme_names, fallback):
            for theme_name in theme_names:
                icon = QtGui.QIcon.fromTheme(theme_name)
                if not icon.isNull():
                    return icon
            return button_style.standardIcon(fallback)

        def plus_button_icon():
            icon = QtGui.QIcon.fromTheme("list-add")
            if not icon.isNull():
                return icon
            size = 16
            pixmap = QtGui.QPixmap(size, size)
            pixmap.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(pixmap)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            pen = QtGui.QPen(self.roi_table.palette().color(QtGui.QPalette.ButtonText), 2)
            pen.setCapStyle(QtCore.Qt.RoundCap)
            painter.setPen(pen)
            margin = 4
            center = size // 2
            painter.drawLine(center, margin, center, size - margin)
            painter.drawLine(margin, center, size - margin, center)
            painter.end()
            return QtGui.QIcon(pixmap)

        # Create a button for adding a line ROI
        add_line_roi_button = QtWidgets.QPushButton("Add ROI")
        add_line_roi_button.setIcon(plus_button_icon())
        add_line_roi_button.clicked.connect(lambda: self.add_roi())

        remove_all_rois_button = QtWidgets.QPushButton("Clear ROIs")
        trash_icon = button_style.standardIcon(
            getattr(QtWidgets.QStyle, "SP_TrashIcon", QtWidgets.QStyle.SP_DialogDiscardButton)
        )
        remove_all_rois_button.setIcon(trash_icon)
        remove_all_rois_button.setToolTip("Remove all ROIs from the image and ROI table")
        remove_all_rois_button.clicked.connect(self.remove_all_rois)

        suggest_rois_button = QtWidgets.QPushButton("Suggest ROIs")
        suggest_rois_button.setIcon(
            themed_button_icon(
                ["system-search", "edit-find", "help-hint", "dialog-question"],
                QtWidgets.QStyle.SP_MessageBoxQuestion,
            )
        )
        suggest_rois_button.clicked.connect(self.suggest_rois_from_image)

        load_spectra_button = QtWidgets.QPushButton("Load Spectrum from File")
        load_spectra_button.setIcon(button_style.standardIcon(QtWidgets.QStyle.SP_DialogOpenButton))
        load_spectra_button.clicked.connect(self.load_spectra)
        
        load_preset_button = QtWidgets.QPushButton("Load Lookup Table and Spectra Preset")
        load_preset_button.setIcon(button_style.standardIcon(QtWidgets.QStyle.SP_FileIcon))
        load_preset_button.clicked.connect(self.load_presets)

        # add buttons on top of the table
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addWidget(add_line_roi_button, alignment=QtCore.Qt.AlignCenter)
        button_layout.addWidget(remove_all_rois_button, alignment=QtCore.Qt.AlignCenter)
        button_layout.addWidget(suggest_rois_button, alignment=QtCore.Qt.AlignCenter)
        button_layout.addWidget(load_spectra_button, alignment=QtCore.Qt.AlignCenter)
        button_layout.addWidget(load_preset_button, alignment=QtCore.Qt.AlignCenter)
        button_widget = QtWidgets.QWidget()
        button_widget.setLayout(button_layout)
        self.roi_table_dock.addWidget(button_widget)
        # add the table to the dock
        self.roi_table_dock.addWidget(self.roi_table)
        # bind shortcut on del press to remove the selected row / ROI
        del_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence("Del"), self.roi_table)
        del_shortcut.activated.connect(self._remove_selected_or_active_roi)
        self._refresh_roi_table_layout()
        QtCore.QTimer.singleShot(0, self._refresh_roi_table_layout)

        # %% ROI plot
        self.roi_plot_dock= Dock("ROI Average Plot", size=(320, 240), closable=False)
        self.roi_plot_dock.setStretch(320, 240)
        self.roi_plotter = ROIPlotter(self)
        self.roi_plot_dock.addWidget(self.roi_plotter)

    def update_data(self, data_cyx: np.ndarray = None):
        """
        Callback when new data is loaded into the image view.

        Parameters
        ----------
        data_cyx : np.ndarray, optional
            New data to use. If None, uses the current image data.
        Returns
        -------
        """
        logger.info(f"Updating raw data in ROI Manager")
        self.raw_data = data_cyx
        # check if there is a roi that is used for background subtraction
        if self.fill_roi is not None:
            # find the index of this roi and subtract it
            logger.info('Reapplying background subtraction to new data')
            for row in range(self.roi_table.rowCount()):
                if self.roi_table.cellWidget(row, self.widget_columns['Subtract']).isChecked():
                    self.subtract_background(self.rois[row], refill=False)
                    # break the for loop, only one roi can be used for background subtraction
                    break

        logger.info("Updating gaussian models")
        # check for gaussian model rois and replot them
        self.update_gaussian_models_from_spectral_info(self.gaussian_specs_by_component)

        # remove all fixed W from the rois (when new data is loaded, or after binning)
        c = 0
        for roi in self.rois:
            if hasattr(roi, 'fixed_W'):
                del roi.fixed_W
                c += 1
                logger.info(f"Removed fixed W from {c} ROIs after data update")
        # prompt a warning to the user if any fixed W were removed
        if c > 0:
            QtWidgets.QMessageBox.warning(None, "Fixed W removed",
                                          f"{c} ROIs had fixed W values assigned which were removed after data update.")
        self.replot_all_rois()

    def update_wavenumbers(self, wavenumbers):
        self.wavenumbers = wavenumbers
        # update the loaded spectra to the new wavenumbers
        for roi_id, (spec, index) in self.spectrum_loaders.items():
            dummy_roi = self.rois[self.roi_id_idx[roi_id]]

            # Update the target wavenumbers on the shared loader object
            spec.update_wavenumbers(wavenumbers)

            # Prepare spectrum for ALL components in this file (populates spec.target_spectra)
            spec.prepare_spectrum()

            # 2. Get the correct spectrum data for this specific ROI
            # spectrum is the list of arrays (spec.target_spectra)
            # We use the stored 'index' to get the correct component's array
            spectrum_data = spec.target_spectra[index]

            # 3. Update the DummyROI with its specific data
            dummy_roi.update_spectrum(spectrum_data)

        try:
            self.replot_all_rois()
        except Exception as e:
            logger.error(f"Error while replotting ROIs after wavenumber update: {e}. Data must still be updated")

    def eventFilter(self, watched, event):
        """
        Intercept events on ROI table widgets to synchronize selection with the image view.
        """
        if not self._selection_sync_in_progress and event.type() in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.FocusIn):
            row = self._row_for_table_widget(watched)
            if row is not None:
                QtCore.QTimer.singleShot(
                    0,
                    lambda row=row: self._select_roi_by_row(
                        row,
                        ensure_image_visible=False,
                        ensure_table_visible=False,
                        sync_table_selection=False,
                    ),
                )
        return super().eventFilter(watched, event)

    def _register_table_selection_widget(self, widget: QtWidgets.QWidget | None):
        """
        Install event filters on the given widget and all its child widgets to synchronize selection with the image view.
        """
        if widget is None:
            return
        for child in [widget, *widget.findChildren(QtWidgets.QWidget)]:
            if child.property("roi_selection_filter_installed"):
                continue
            child.setProperty("roi_selection_filter_installed", True)
            child.installEventFilter(self)

    def _row_for_table_widget(self, widget: QtCore.QObject | None) -> int | None:
        current = widget
        while isinstance(current, QtCore.QObject):
            for row in range(self.roi_table.rowCount()):
                for col in range(self.roi_table.columnCount()):
                    if self.roi_table.cellWidget(row, col) is current:
                        return row
            current = current.parent() if hasattr(current, "parent") else None
        return None

    def _refresh_roi_table_layout(self):
        """
        Adjust column widths based on content and available space, with special handling for checkbox columns.
        """
        header = self.roi_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        auto_widths = getattr(self, "_roi_table_auto_widths", {})
        checkbox_columns = {"Background", "Subtract", "Live Update", "Plot"}
        indicator_width = self.roi_table.style().pixelMetric(QtWidgets.QStyle.PM_IndicatorWidth) + 16

        default_widths = {
            "Name": 140,
            "Resonance": 160,
            "Color": 58,
            "Background": 40,
            "Subtract": 40,
            "Scale": 72,
            "Offset": 58,
            "Gaussian σ": 86,
            "Export": 70,
            "ROI Shape": 122,
            "Live Update": 96,
            "Plot": 52,
            "Show": 64,
            "Remove": 84,
        }
        for name, width in default_widths.items():
            if name in self.widget_columns:
                column = self.widget_columns[name]
                desired_width = width
                if name in checkbox_columns:
                    # adjust checkbox column to fit the header text if it's wider than the indicator
                    header_item = self.roi_table.horizontalHeaderItem(column)
                    header_text = header_item.text() if header_item is not None else name
                    desired_width = max(header.fontMetrics().horizontalAdvance(header_text) + 12, indicator_width)

                current_width = self.roi_table.columnWidth(column)
                previous_auto_width = auto_widths.get(column)
                if previous_auto_width is None or abs(current_width - previous_auto_width) <= 2 or current_width < desired_width:
                    self.roi_table.setColumnWidth(column, desired_width)
                    auto_widths[column] = desired_width

        # ...........
        # After setting default widths, distribute any remaining space to the "Name" and "Resonance" columns
        flexible_columns = [
            self.widget_columns[name]
            for name in ("Name", "Resonance")
            if name in self.widget_columns
        ]
        available_width = self.roi_table.viewport().width()
        current_width = sum(self.roi_table.columnWidth(col) for col in range(self.roi_table.columnCount()))
        extra_width = available_width - current_width
        if extra_width > 0 and flexible_columns:
            extra_per_column, remainder = divmod(extra_width, len(flexible_columns))
            for index, column in enumerate(flexible_columns):
                new_width = self.roi_table.columnWidth(column) + extra_per_column + (1 if index < remainder else 0)
                self.roi_table.setColumnWidth(column, new_width)
                auto_widths[column] = new_width

        self.roi_table.resizeRowsToContents()
        self._roi_table_auto_widths = auto_widths

    def _remove_selected_or_active_roi(self):
        """
        Remove the selected or active ROI highlight from the image view, if possible.
        """
        if self.active_roi in self.rois:
            self.remove_roi(self.active_roi)
            return
        row = self.roi_table.currentRow()
        if 0 <= row < len(self.rois):
            self.remove_roi(self.rois[row])

    def _select_table_row(
        self,
        row: int,
        ensure_visible: bool = False,
    ):
        if not 0 <= row < self.roi_table.rowCount():
            return

        model_index = self.roi_table.model().index(row, 0)
        self.roi_table.clearSelection()
        self.roi_table.setCurrentIndex(model_index)
        self.roi_table.selectRow(row)
        if ensure_visible:
            self.roi_table.scrollTo(model_index, QtWidgets.QAbstractItemView.PositionAtCenter)

    def _apply_table_row_highlight(self, row: int, highlighted: bool):
        """
        Apply or remove highlight styling to the 'Name' widget of the specified table row if selected.
        """
        if not 0 <= row < self.roi_table.rowCount():
            return

        name_widget = self.roi_table.cellWidget(row, self.widget_columns['Name'])
        if name_widget is None:
            return

        base_style = name_widget.property("roi_base_style")
        if base_style is None:
            base_style = name_widget.styleSheet()
            name_widget.setProperty("roi_base_style", base_style)

        if highlighted:
            highlight_style = (
                f"{base_style}\n"
                "QLineEdit {"
                " border: 2px solid rgb(255, 215, 64);"
                " background-color: rgba(255, 215, 64, 0.12);"
                " }"
            )
            name_widget.setStyleSheet(highlight_style)
        else:
            name_widget.setStyleSheet(str(base_style))
            name_widget.style().unpolish(name_widget)
            name_widget.style().polish(name_widget)
            name_widget.update()
        self.roi_table.resizeRowToContents(row)

    def _set_table_row_highlight(self, row: int | None):
        previous_row = self._highlighted_table_row
        if previous_row is not None and previous_row != row:
            self._apply_table_row_highlight(previous_row, highlighted=False)

        if row is None or not 0 <= row < self.roi_table.rowCount():
            self._highlighted_table_row = None
            return

        self._apply_table_row_highlight(row, highlighted=True)
        self._highlighted_table_row = row

    def _ensure_roi_visible(self, roi: pg.ROI, always_center: bool = False):
        """
        Adjust the view to ensure the given ROI is fully visible.
        """
        if roi is None or isinstance(roi, DummyROI):
            return

        bounds = roi.mapRectToParent(roi.boundingRect())
        if not bounds.isValid() or bounds.isNull():
            return

        view = self.image_view.getView()
        view_box = view.getViewBox() if hasattr(view, "getViewBox") else view
        x_range, y_range = view_box.viewRange()
        x0, x1 = sorted((float(x_range[0]), float(x_range[1])))
        y0, y1 = sorted((float(y_range[0]), float(y_range[1])))

        fully_visible = (
            bounds.left() >= x0
            and bounds.right() <= x1
            and bounds.top() >= y0
            and bounds.bottom() <= y1
        )
        if fully_visible and not always_center:
            return

        view_width = max(1.0, x1 - x0, float(bounds.width()) * 1.15)
        view_height = max(1.0, y1 - y0, float(bounds.height()) * 1.15)
        center = bounds.center()
        center_x = float(center.x())
        center_y = float(center.y())

        image = self.raw_data if self.raw_data is not None else self.image_view.getImageItem().image
        if image is not None:
            image_shape = np.shape(image)
            if len(image_shape) >= 2:
                image_height = float(image_shape[-2])
                image_width = float(image_shape[-1])
                if view_width < image_width:
                    center_x = float(np.clip(center_x, view_width / 2.0, image_width - view_width / 2.0))
                else:
                    center_x = image_width / 2.0
                if view_height < image_height:
                    center_y = float(np.clip(center_y, view_height / 2.0, image_height - view_height / 2.0))
                else:
                    center_y = image_height / 2.0

        target_x = (center_x - view_width / 2.0, center_x + view_width / 2.0)
        target_y = (center_y - view_height / 2.0, center_y + view_height / 2.0)
        if hasattr(view_box, "setRange"):
            view_box.setRange(xRange=target_x, yRange=target_y, padding=0.0)
        else:
            view_box.setXRange(*target_x, padding=0.0)
            view_box.setYRange(*target_y, padding=0.0)

    def _select_roi(
        self,
        roi: pg.ROI | None,
        ensure_image_visible: bool = False,
        ensure_table_visible: bool = False,
        sync_table_selection: bool = True,
    ):
        """
        Select the given ROI, update the table selection and highlight, and optionally ensure visibility in the image view and table.
        """
        row = self.roi_id_idx.get(str(roi)) if roi is not None else None
        if row is None or not 0 <= row < len(self.rois):
            self.active_roi = None
            for other_roi in self.rois:
                self.set_roi_highlight(other_roi, highlighted=False)
            self._set_table_row_highlight(None)
            return

        self.active_roi = roi
        if sync_table_selection:
            self._selection_sync_in_progress = True
            try:
                self._select_table_row(
                    row,
                    ensure_visible=ensure_table_visible,
                )
            finally:
                self._selection_sync_in_progress = False

        for other_roi in self.rois:
            self.set_roi_highlight(other_roi, highlighted=other_roi == roi)
        self._set_table_row_highlight(row)

        if ensure_image_visible:
            self._ensure_roi_visible(roi)

    def _select_roi_by_row(
        self,
        row: int,
        ensure_image_visible: bool = False,
        ensure_table_visible: bool = False,
        sync_table_selection: bool = True,
    ):
        if not 0 <= row < len(self.rois):
            return
        self._select_roi(
            self.rois[row],
            ensure_image_visible=ensure_image_visible,
            ensure_table_visible=ensure_table_visible,
            sync_table_selection=sync_table_selection,
        )

    def _show_roi_by_row(self, row: int):
        if not 0 <= row < len(self.rois):
            return
        self._select_roi_by_row(row, ensure_image_visible=False, ensure_table_visible=True)
        self._ensure_roi_visible(self.rois[row], always_center=True)

    def _show_roi_for_table_widget(self, widget: QtWidgets.QWidget | None):
        row = self._row_for_table_widget(widget)
        if row is None:
            return
        # handle dummy rois with only W data
        roi = self.rois[row] if 0 <= row < len(self.rois) else None
        if roi is not None and hasattr(roi, "fixed_W"):
            self._show_fixed_w_seed(roi)
            return
        self._show_roi_by_row(row)

    def _show_fixed_w_seed(self, roi: pg.ROI):
        fixed_W = getattr(roi, "fixed_W", None)
        if fixed_W is None or self.raw_data is None or np.ndim(self.raw_data) < 3:
            return

        _, height, width = self.raw_data.shape
        if np.size(fixed_W) != height * width:
            logger.warning(
                "Cannot show fixed W seed for ROI %s because shape %s does not match image size (%s, %s).",
                roi,
                np.shape(fixed_W),
                height,
                width,
            )
            return

        w_image = np.asarray(fixed_W, dtype=float).reshape(height, width)
        if self.fixed_w_seed_view is None:
            self.fixed_w_seed_view = ImageViewYX()
            self.fixed_w_seed_view.ui.roiBtn.hide()
            self.fixed_w_seed_view.ui.menuBtn.hide()

        color = self._get_roi_base_color(roi)
        cmap = pg.ColorMap(
            pos=np.array([0.0, 1.0]),
            color=np.array([[0, 0, 0, 255], [color.red(), color.green(), color.blue(), 255]]),
        )
        self.fixed_w_seed_view.setColorMap(cmap)
        self.fixed_w_seed_view.setImage(w_image)
        self.fixed_w_seed_view.setWindowTitle(f"{roi.label} W Seed")
        self.fixed_w_seed_view.show()
        self.fixed_w_seed_view.raise_()

    def _component_from_table_widget(self, widget: QtWidgets.QWidget | None) -> int | None:
        row = self._row_for_table_widget(widget)
        if row is None:
            return None
        return self.component_number_from_table_index(row)

    def _set_component_color(self, component_number: int | None, qcolor: QtGui.QColor, emit_signal: bool = True):
        """
        Helper method to set the color for a given component number, update the default colors,
        and optionally emit a signal to the color manager.
        """
        if component_number is None:
            return
        rgb = qcolor.getRgb()[:-1]
        self.default_colors[component_number % len(self.default_colors)] = rgb
        if self.color_manager is None:
            return
        if emit_signal:
            self.color_manager.set_color_rgb(component_number, rgb)
            return
        blocker = QtCore.QSignalBlocker(self.color_manager)
        self.color_manager.set_color_rgb(component_number, rgb)
        del blocker

    def _emit_component_color_updates(self, component_numbers):
        """
        Send color update signals for the specified component numbers to ensure all listeners are updated with the current colors.
        """
        if self.color_manager is None:
            return
        seen = set()    # make sure each component number only emits one signal, even if it appears multiple times in the list (e.g. multiple ROIs with same component)
        for component_number in component_numbers:
            if component_number is None or component_number in seen:
                continue
            seen.add(component_number)
            self.color_manager.sigColorChanged.emit(component_number, self.color_manager.get_qcolor(component_number))

    def _apply_row_color(self, row: int, qcolor: QtGui.QColor, update_widget: bool = True):
        if not 0 <= row < len(self.rois):
            return
        roi = self.rois[row]
        label_widget = self.roi_table.cellWidget(row, self.widget_columns['Name'])
        label_text = label_widget.text() if label_widget is not None else getattr(roi, "label", f"ROI {row + 1}")
        self.set_roi_properties(roi, qcolor, label_text)
        color_widget: ColorButton | None = self.roi_table.cellWidget(row, self.widget_columns['Color'])
        if update_widget and color_widget is not None:
            color_widget.setColor(qcolor)
        self.update_roi_plot(roi)
        component_number = self.component_number_from_table_index(row)
        if component_number is not None:
            self.roi_plotter.update_component_fallback(component_number)

    def _handle_color_button_changed(self, widget: QtWidgets.QWidget | None, qcolor: QtGui.QColor):
        """
        Set the component color based on the color button change, update the ROI color, and emit signals to update the color manager if applicable.
        """
        row = self._row_for_table_widget(widget)
        if row is None:
            return
        component_number = self.component_number_from_table_index(row)
        if self.color_manager is not None and component_number is not None:
            self.update_roi_color(row, qcolor, emit_signal=False)
            self._set_component_color(component_number, qcolor, emit_signal=True)
            return
        self.update_roi_color(row, qcolor)

    def _handle_component_changed(self, widget: QtWidgets.QWidget | None):
        row = self._row_for_table_widget(widget)
        if row is None or not 0 <= row < len(self.rois):
            return
        old_component = widget.property("last_component_number")
        new_component = self.component_number_from_table_index(row)
        widget.setProperty("last_component_number", new_component)
        self.roi_plotter.roi_component_changed(str(self.rois[row]), new_component)
        if old_component is not None and old_component != new_component:
            self._emit_label_for_component(int(old_component))
        if new_component is not None:
            self._emit_label_for_component(new_component, preferred_row=row)

    def _handle_shape_changed(self, widget: QtWidgets.QWidget | None, roi_shape: str):
        row = self._row_for_table_widget(widget)
        if row is None:
            return
        self.change_roi_type(roi_shape, row)

    def _row_and_roi_for_table_widget(self, widget: QtWidgets.QWidget | None) -> tuple[int | None, pg.ROI | None]:
        row = self._row_for_table_widget(widget)
        if row is None or not 0 <= row < len(self.rois):
            return None, None
        return row, self.rois[row]

    def _handle_name_changed(self, widget: QtWidgets.QWidget | None, text: str):
        row, roi = self._row_and_roi_for_table_widget(widget)
        if roi is None:
            return
        self.set_roi_properties(
            roi,
            self._get_roi_base_color(roi),
            text,
            replot=True,
        )
        component_number = self.component_number_from_table_index(row)
        if component_number is not None:
            self._emit_label_for_component(component_number, preferred_row=row)

    def _component_label_text_from_row(self, row: int) -> str:
        name_widget = self.roi_table.cellWidget(row, self.widget_columns['Name'])
        if name_widget is None:
            return ""
        try:
            return str(name_widget.text())
        except Exception:
            return ""

    def _emit_label_for_component(self, component_number: int, preferred_row: int | None = None):
        candidate_rows = []
        if preferred_row is not None and 0 <= preferred_row < self.roi_table.rowCount():
            candidate_rows.append(preferred_row)
        candidate_rows.extend(
            row for row in range(self.roi_table.rowCount())
            if row != preferred_row and self.component_number_from_table_index(row) == component_number
        )

        for row in candidate_rows:
            if self.component_number_from_table_index(row) != component_number:
                continue
            text = self._component_label_text_from_row(row)
            self.label_change_signal.emit(component_number, text or f"Component {component_number}")
            return

        self.label_change_signal.emit(component_number, f"Component {component_number}")

    def _emit_all_component_labels(self):
        seen_components = set()
        for row in range(self.roi_table.rowCount()):
            component_number = self.component_number_from_table_index(row)
            if component_number is None or component_number in seen_components:
                continue
            seen_components.add(component_number)
            self._emit_label_for_component(component_number, preferred_row=row)

    def _handle_remove_button_clicked(self, widget: QtWidgets.QWidget | None):
        _, roi = self._row_and_roi_for_table_widget(widget)
        if roi is None:
            return
        self.remove_roi(roi)

    def _handle_roi_update_widget_changed(self, widget: QtWidgets.QWidget | None):
        _, roi = self._row_and_roi_for_table_widget(widget)
        if roi is None:
            return
        self.update_roi(roi)

    def _handle_export_button_clicked(self, widget: QtWidgets.QWidget | None):
        _, roi = self._row_and_roi_for_table_widget(widget)
        if roi is None:
            return
        self.export_roi(roi)

    def _handle_subtract_toggled(self, widget: QtWidgets.QWidget | None, state: bool):
        _, roi = self._row_and_roi_for_table_widget(widget)
        if roi is None:
            return
        if state:
            self.subtract_background(roi)
        else:
            self.remove_subtraction(roi)

    def _handle_plot_toggled(self, widget: QtWidgets.QWidget | None, state: bool):
        _, roi = self._row_and_roi_for_table_widget(widget)
        if roi is None:
            return
        self.hide_roi(roi, state)

    def _handle_live_update_toggled(self, widget: QtWidgets.QWidget | None, state: bool):
        _, roi = self._row_and_roi_for_table_widget(widget)
        if roi is None:
            return
        self.connect_signals_to_roi(roi, state)

    def _handle_background_toggled(self, widget: QtWidgets.QWidget | None, state: bool):
        _, roi = self._row_and_roi_for_table_widget(widget)
        if roi is None:
            return
        self.sync_components(roi, state)

    def _on_roi_clicked(self, roi: pg.ROI, *_):
        self._select_roi(roi, ensure_image_visible=False, ensure_table_visible=True)

    def component_prompt(self) -> int | None:
        default_component_number = self._suggest_component_number()
        component_number, ok = QtWidgets.QInputDialog.getInt(
            None,
            "Component Number",
            "Enter the component number",
            default_component_number,
            1,
            self.max_component_slots,
            1,
        )
        if not ok:
            return None
        return component_number

    def add_roi(self, user_prompt=True):
        component_number = self.component_prompt() if user_prompt else self._suggest_component_number()
        if component_number is None:
            return

        # get the center position of the image view
        view_range = self.image_view.getView().viewRange()
        center = np.array(view_range)
        # average the x and y values to get the center
        center = np.mean(center, axis=1)

        # set roi size to 15% of the current view range
        roi_size = np.array([view_range[0][1] - view_range[0][0], view_range[1][1] - view_range[1][0]]) * 0.15

        # Assuming a RectROI for simplicity, adjust as needed for other ROI types
        roi = pg.RectROI(center - np.array(roi_size) / 2, roi_size, pen=(0, 9))
        roi_number = len(self.rois)
        color = self.color_manager.get_color_rgb(component_number-1) if self.color_manager else self.default_colors[
            roi_number % len(self.default_colors)]
        label = "ROI {}".format(roi_number + 1)
        self.set_roi_properties(roi, color, label)
        self.image_view.getView().addItem(roi)
        self.rois.append(roi)  # Add the ROI to the list
        # Generate a unique ID to identify the ROI
        roi_id = str(roi)
        self.roi_id_idx[roi_id] = len(self.rois) - 1
        cur_index = self.add_last_roi_to_table(new_roi_id=roi_id,
                                               component_number=component_number - 1)  # Update the table view
        self.connect_signals_to_roi(roi,
                                    on_region_change=self.roi_table.cellWidget(cur_index, self.widget_columns['Live Update']).isChecked())
        self.request_plot_avg_intensity(roi_id)
        self.new_roi_signal.emit(self.component_number_from_table_index(cur_index))


    # ------------------------------------
    # ROI Auto Suggestion Methods
    # ------------------------------------
    def add_rect_roi_from_bounds(
        self,
        component_number: int,
        pos: tuple[float, float],
        size: tuple[float, float],
        label_text: str | None = None,
        auto_suggested: bool = False,
        score: float | None = None,
    ) -> str:
        """
        Add a rectangular ROI to the image view based on specified position and size, with optional labeling and auto-suggestion metadata.
        """
        component_number = int(component_number)
        color = self.color_manager.get_color_rgb(component_number) if self.color_manager else self.default_colors[
            component_number % len(self.default_colors)
        ]
        roi = pg.RectROI(pos, size, pen=pg.mkPen(color), movable=True)
        label_text = label_text or f"ROI {len(self.rois) + 1}"
        self.set_roi_properties(roi, color, label_text)
        if auto_suggested:
            roi.is_auto_suggested = True
            roi.auto_suggestion_score = float(score if score is not None else 0.0)

        self.image_view.getView().addItem(roi)
        self.rois.append(roi)
        roi_id = str(roi)
        self.roi_id_idx[roi_id] = len(self.rois) - 1
        cur_index = self.add_last_roi_to_table(
            new_roi_id=roi_id,
            component_number=component_number,
            roi_name=label_text,
        )
        self.connect_signals_to_roi(
            roi,
            on_region_change=self.roi_table.cellWidget(cur_index, self.widget_columns['Live Update']).isChecked(),
        )
        self.request_plot_avg_intensity(roi_id)
        self.new_roi_signal.emit(self.component_number_from_table_index(cur_index))
        return roi_id

    def clear_auto_suggested_rois(self) -> int:
        """
        Remove all ROIs that were marked as auto-suggested and return the count of removed ROIs.
        """
        rois_to_remove = [roi for roi in list(self.rois) if getattr(roi, "is_auto_suggested", False)]
        for roi in rois_to_remove[::-1]:
            self.remove_roi(roi)
        return len(rois_to_remove)

    def suggest_rois_from_image(self):
        if self.raw_data is None:
            QtWidgets.QMessageBox.information(None, "Suggest ROIs", "Load an image stack first.")
            return

        settings = self._prompt_auto_roi_settings()
        if settings is None:
            return

        removed = 0
        if settings.replace_previous_auto:
            removed = self.clear_auto_suggested_rois()

        # Stage 1: collapse the spectral stack into one spatial response map.
        response_map = self._build_spatial_response_map(settings)
        if response_map is None or response_map.size == 0 or float(np.max(response_map)) <= 0:
            QtWidgets.QMessageBox.information(
                None,
                "Suggest ROIs",
                "No usable image projection could be built from the current stack.",
            )
            return
        # response map is a 2D numpy array with the selected projection method

        # ignore already occupied ROI areas
        occupied_mask = self._spatial_roi_mask(include_auto=True)
        if occupied_mask.any():
            response_map = response_map.copy()
            response_map[occupied_mask] = 0.0

        # Stage 2: find localized bright spatial candidates from that map alone.
        raw_suggestions = self._extract_suggestions_from_response_map(response_map, settings)
        if not raw_suggestions:
            QtWidgets.QMessageBox.information(
                None,
                "Suggest ROIs",
                "No peak groups were found. Try lowering the threshold or the local-background sigma.",
            )
            return

        available_components = self._available_component_numbers()
        if not available_components:
            QtWidgets.QMessageBox.information(
                None,
                "Suggest ROIs",
                f"All {self.max_component_slots} component slots are already used. Remove or reassign ROIs first.",
            )
            return

        requested_groups = max(1, int(settings.max_groups_per_component))
        target_group_count = min(requested_groups, len(available_components))
        # Stage 3: merge spatial candidates whose mean spectra suggest the same
        # underlying component, then assign the surviving groups to free component
        # slots in descending score order.
        grouped_suggestions = self._group_suggestions_by_spectrum(
            raw_suggestions,
            settings,
            target_group_count=target_group_count,
            max_members_per_group=int(settings.max_rois_per_group),
        )

        # put the final ROIS in the ImageView
        created = []
        for component, grouped in zip(available_components[:len(grouped_suggestions)], grouped_suggestions):
            for suggestion in grouped:
                suggestion_out = AutoROISuggestion(
                    component=component,
                    y=suggestion.y,
                    x=suggestion.x,
                    height=suggestion.height,
                    width=suggestion.width,
                    score=suggestion.score,
                )
                created.append(suggestion_out)
                self.add_rect_roi_from_bounds(
                    component_number=component,
                    pos=(suggestion_out.x, suggestion_out.y),
                    size=(suggestion_out.width, suggestion_out.height),
                    label_text=self._next_auto_roi_label(component),
                    auto_suggested=True,
                    score=suggestion_out.score,
                )

        message_lines = [
            f"Detected {len(raw_suggestions)} candidate regions.",
            f"Merged them into {len(grouped_suggestions)} spectral groups.",
            f"Created {len(created)} ROI suggestions across {len(grouped_suggestions)} suggested components.",
        ]
        accepted_suggestions = sum(len(group) for group in grouped_suggestions)
        skipped_within_group = max(0, len(raw_suggestions) - accepted_suggestions)
        if skipped_within_group:
            message_lines.append(
                f"Left {skipped_within_group} extra candidate regions unused after spectral grouping and limit application."
            )
        if removed:
            message_lines.append(f"Removed {removed} previous auto ROI suggestions.")
        if requested_groups > len(grouped_suggestions):
            message_lines.append(
                f"Requested {requested_groups} spectral groups, but only {len(grouped_suggestions)} distinct populated groups were found."
            )
        if requested_groups > len(available_components):
            message_lines.append(
                f"{requested_groups - len(available_components)} requested spectral groups could not be assigned because only {len(available_components)} component slots were free."
            )
        QtWidgets.QMessageBox.information(None, "ROI suggestions created", "\n".join(message_lines))

    def _prompt_auto_roi_settings(self) -> AutoROISuggestionSettings | None:
        dialog = QtWidgets.QDialog()
        dialog.setWindowTitle("Suggest ROIs")
        dialog.setModal(True)

        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setSpacing(10)

        hint = QtWidgets.QLabel(
            "Scans the image stack without any resonance input. "
            "It builds a 2D projection, enhances local peaks, groups bright regions, and adds one ROI per suggestion. "
            "Balanced stack scan normalizes each frame first so one dominant resonance does not hide weaker groups."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        def add_tooltip_row(label_text: str, widget: QtWidgets.QWidget, tooltip: str):
            label = QtWidgets.QLabel(label_text)
            label.setToolTip(tooltip)
            widget.setToolTip(tooltip)
            form.addRow(label, widget)

        projection_combo = QtWidgets.QComboBox()
        projection_combo.addItems(["Balanced stack scan", "Average image", "Maximum projection", "Current frame"])
        projection_combo.setCurrentText(self.auto_roi_settings.projection_mode)
        projection_tooltip = (
            "Chooses how the image stack is collapsed into one 2D scan image. "
            "Balanced stack scan rescales each frame first so one dominant resonance does not hide weaker groups."
        )

        processed_check = QtWidgets.QCheckBox("Use processed image when available")
        processed_check.setChecked(bool(self.auto_roi_settings.use_processed_data and self.subtracted_data is not None))
        processed_check.setEnabled(self.subtracted_data is not None)
        processed_tooltip = (
            "Uses the processed or background-subtracted stack instead of the raw stack, if that processed data exists."
        )

        background_sigma_spin = QtWidgets.QDoubleSpinBox()
        background_sigma_spin.setRange(0.0, 100.0)
        background_sigma_spin.setDecimals(1)
        background_sigma_spin.setSingleStep(0.5)
        background_sigma_spin.setValue(float(self.auto_roi_settings.local_background_sigma))
        background_sigma_tooltip = (
            "Subtracts a blurred copy of the projection to emphasize local bright structures. "
            "Higher values remove broader background variation."
        )

        binning_combo = QtWidgets.QComboBox()
        for factor in (1, 2, 4, 8):
            binning_combo.addItem(str(factor), factor)
        binning_index = binning_combo.findData(int(self.auto_roi_settings.spatial_bin_factor))
        if binning_index >= 0:
            binning_combo.setCurrentIndex(binning_index)
        binning_tooltip = (
            "Downsamples the scan image before peak finding. "
            "Higher binning is faster and more robust to noise, but can miss very small regions."
        )

        smoothing_spin = QtWidgets.QDoubleSpinBox()
        smoothing_spin.setRange(0.0, 10.0)
        smoothing_spin.setDecimals(1)
        smoothing_spin.setSingleStep(0.2)
        smoothing_spin.setValue(float(self.auto_roi_settings.smoothing_sigma))
        smoothing_tooltip = (
            "Applies spatial smoothing before peak detection. "
            "Increase this to suppress pixel noise; decrease it to preserve sharper structures."
        )

        threshold_spin = QtWidgets.QDoubleSpinBox()
        threshold_spin.setRange(10.0, 95.0)
        threshold_spin.setDecimals(0)
        threshold_spin.setSingleStep(5.0)
        threshold_spin.setSuffix(" %")
        threshold_spin.setValue(float(self.auto_roi_settings.threshold_ratio * 100.0))
        threshold_tooltip = (
            "Controls how bright a candidate region must be relative to the response map. "
            "Lower values find more regions, including weaker ones."
        )

        min_area_spin = QtWidgets.QSpinBox()
        min_area_spin.setRange(1, 500)
        min_area_spin.setValue(int(self.auto_roi_settings.min_group_area))
        min_area_tooltip = (
            "Smallest connected bright region that is allowed to become a suggestion. "
            "Increase this to ignore tiny speckles."
        )

        min_diagonal_spin = QtWidgets.QSpinBox()
        min_diagonal_spin.setRange(0, 5000)
        min_diagonal_spin.setSingleStep(2)
        min_diagonal_spin.setSuffix(" px")
        min_diagonal_spin.setValue(int(self.auto_roi_settings.min_roi_diagonal_px))
        min_diagonal_tooltip = (
            "Minimum diagonal length of the final suggested ROI box in image pixels. "
            "Use this when you want the suggester to prefer larger structures and ignore small localized objects."
        )

        max_rois_spin = QtWidgets.QSpinBox()
        max_rois_spin.setRange(1, self.max_component_slots)
        max_rois_spin.setValue(int(self.auto_roi_settings.max_groups_per_component))
        max_groups_tooltip = (
            "Maximum number of distinct spectral groups/components to suggest in one scan."
        )

        max_per_group_spin = QtWidgets.QSpinBox()
        max_per_group_spin.setRange(1, 25)
        max_per_group_spin.setValue(int(self.auto_roi_settings.max_rois_per_group))
        max_per_group_tooltip = (
            "Limits how many separate spatial ROIs can be created inside one spectral group/component."
        )

        merge_spectra_check = QtWidgets.QCheckBox("Merge spectrally similar regions")
        merge_spectra_check.setChecked(bool(self.auto_roi_settings.merge_similar_spectra))
        merge_duplicates_tooltip = (
            "Keeps detection image-based, but merges regions whose mean spectra are nearly identical so they share one component."
        )

        spectral_threshold_spin = QtWidgets.QDoubleSpinBox()
        spectral_threshold_spin.setRange(70.0, 100.0)
        spectral_threshold_spin.setDecimals(0)
        spectral_threshold_spin.setSingleStep(1.0)
        spectral_threshold_spin.setSuffix(" %")
        spectral_threshold_spin.setValue(float(self.auto_roi_settings.spectral_similarity_threshold * 100.0))
        spectral_threshold_spin.setEnabled(merge_spectra_check.isChecked())
        merge_spectra_check.toggled.connect(spectral_threshold_spin.setEnabled)
        similarity_tooltip = (
            "Similarity required to treat two ROI mean spectra as the same group. "
            "Higher values merge fewer regions; lower values merge more aggressively."
        )

        replace_auto_check = QtWidgets.QCheckBox("Replace previous auto ROI suggestions")
        replace_auto_check.setChecked(bool(self.auto_roi_settings.replace_previous_auto))
        replace_auto_tooltip = (
            "If enabled, previously auto-generated ROI suggestions are removed before creating new ones."
        )

        add_tooltip_row("Projection:", projection_combo, projection_tooltip)
        add_tooltip_row("Processed data:", processed_check, processed_tooltip)
        add_tooltip_row("Local background sigma:", background_sigma_spin, background_sigma_tooltip)
        add_tooltip_row("Spatial binning:", binning_combo, binning_tooltip)
        add_tooltip_row("Peak smoothing:", smoothing_spin, smoothing_tooltip)
        add_tooltip_row("Peak threshold:", threshold_spin, threshold_tooltip)
        add_tooltip_row("Min group area:", min_area_spin, min_area_tooltip)
        add_tooltip_row("Min ROI diagonal:", min_diagonal_spin, min_diagonal_tooltip)
        add_tooltip_row("Max suggested groups:", max_rois_spin, max_groups_tooltip)
        add_tooltip_row("Max ROIs per group:", max_per_group_spin, max_per_group_tooltip)
        add_tooltip_row("Merge duplicates:", merge_spectra_check, merge_duplicates_tooltip)
        add_tooltip_row("Similarity threshold:", spectral_threshold_spin, similarity_tooltip)
        replace_auto_check.setToolTip(replace_auto_tooltip)
        layout.addLayout(form)
        layout.addWidget(replace_auto_check)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return None

        self.auto_roi_settings = AutoROISuggestionSettings(
            projection_mode=str(projection_combo.currentText()),
            use_processed_data=bool(processed_check.isChecked()),
            local_background_sigma=float(background_sigma_spin.value()),
            spatial_bin_factor=int(binning_combo.currentData()),
            smoothing_sigma=float(smoothing_spin.value()),
            threshold_ratio=float(threshold_spin.value()) / 100.0,
            peak_region_ratio=float(self.auto_roi_settings.peak_region_ratio),
            peak_window=int(self.auto_roi_settings.peak_window),
            min_group_area=int(min_area_spin.value()),
            min_roi_diagonal_px=int(min_diagonal_spin.value()),
            max_groups_per_component=int(max_rois_spin.value()),
            max_rois_per_group=int(max_per_group_spin.value()),
            candidate_pool_factor=int(self.auto_roi_settings.candidate_pool_factor),
            padding_px=int(self.auto_roi_settings.padding_px),
            merge_similar_spectra=bool(merge_spectra_check.isChecked()),
            spectral_similarity_threshold=float(spectral_threshold_spin.value()) / 100.0,
            spectral_smoothing_sigma=float(self.auto_roi_settings.spectral_smoothing_sigma),
            replace_previous_auto=bool(replace_auto_check.isChecked()),
        )
        return self.auto_roi_settings

    @staticmethod
    def _normalize_projection_response(
        projection: np.ndarray,
        background_sigma: float,
    ) -> np.ndarray:
        """
        Convert a 2D image into a dimensionless "response map" for ROI finding.

        The physical picture is: first remove the slow, broad background so only
        local contrast remains, then scale the result into a comparable 0..1 range.
        Downstream thresholds are therefore applied to "how unusually bright is this
        spot locally?" rather than to raw detector counts.
        """
        projection = np.asarray(projection, dtype=float)
        projection = np.nan_to_num(projection, nan=0.0, posinf=0.0, neginf=0.0)

        if background_sigma > 0:
            local_background = gaussian_filter(projection, sigma=float(background_sigma))
            projection = projection - local_background

        projection[projection < 0] = 0.0
        positive_values = projection[projection > 0]
        if positive_values.size == 0:
            return np.zeros_like(projection, dtype=np.float32)

        scale = float(np.percentile(positive_values, 99.5))
        if not np.isfinite(scale) or scale <= 0:
            scale = float(np.max(positive_values))
        if scale > 0:
            projection = np.clip(projection / scale, 0.0, 1.0)

        return projection.astype(np.float32, copy=False)

    @classmethod
    def _build_balanced_stack_projection(
        cls,
        stack: np.ndarray,
        background_sigma: float,
    ) -> np.ndarray:
        """
        Build a projection in which strong and weak spectral slices contribute more
        equally.

        In practical terms, each frame is normalized on its own before the strongest
        few responses are averaged per pixel.  This helps weak slice-specific
        structure survive when a plain average image would be dominated by only a
        few very bright resonances.
        """
        if stack.ndim == 2:
            return cls._normalize_projection_response(stack, background_sigma)

        frame_responses = [
            cls._normalize_projection_response(frame, background_sigma)
            for frame in stack
        ]
        if not frame_responses:
            return np.zeros(stack.shape[1:], dtype=np.float32)

        normalized_stack = np.stack(frame_responses, axis=0)
        top_k = min(3, normalized_stack.shape[0])
        kth_index = max(0, normalized_stack.shape[0] - top_k)
        top_responses = np.partition(normalized_stack, kth_index, axis=0)[kth_index:, ...]
        projection = np.mean(top_responses, axis=0)
        return projection.astype(np.float32, copy=False)

    def _build_spatial_response_map(self, settings: AutoROISuggestionSettings) -> np.ndarray | None:
        """
        Collapse the full spectral stack into one 2D map that answers:
        "where in the field of view is there likely a localized object worth drawing
        an ROI around?"

        Different projection modes encode different physical assumptions.  Average
        image favors structures that stay bright across many slices, whereas
        balanced stack scan tries harder to rescue features that are prominent only
        in a smaller subset of slices.
        """
        stack = self.subtracted_data if settings.use_processed_data and self.subtracted_data is not None else self.raw_data
        if stack is None or not np.size(stack):
            return None

        stack = np.asarray(stack, dtype=float)
        if stack.ndim == 2:
            return self._normalize_projection_response(stack, background_sigma=float(settings.local_background_sigma))

        projection_mode = settings.projection_mode.lower()
        if projection_mode == "balanced stack scan":
            return self._build_balanced_stack_projection(
                stack,
                background_sigma=float(settings.local_background_sigma),
            )
        if projection_mode == "maximum projection":
            projection = np.max(stack, axis=0)
        elif projection_mode == "current frame":
            frame_index = int(np.clip(self.image_view.currentIndex, 0, stack.shape[0] - 1))
            projection = stack[frame_index, ...]
        else:
            projection = np.mean(stack, axis=0)

        return self._normalize_projection_response(
            projection,
            background_sigma=float(settings.local_background_sigma),
        )

    def _spatial_roi_mask(self, include_auto: bool = True) -> np.ndarray:
        """
        Return a boolean mask of the same height and width as the image, where pixels covered by any existing ROI are True.
        """
        if self.raw_data is None:
            return np.zeros((0, 0), dtype=bool)

        mask = np.zeros(self.raw_data.shape[1:], dtype=bool)
        for roi in self.rois:
            if isinstance(roi, DummyROI):
                continue
            if getattr(roi, "is_gaussian_model", False):
                continue
            if not include_auto and getattr(roi, "is_auto_suggested", False):
                continue
            pixels = self.get_pixels_in_roi(roi)
            mask[pixels[1].astype(int), pixels[0].astype(int)] = True
        return mask

    def _available_component_numbers(self) -> list[int]:
        """
        Return all 0-based indices that have an underlying ROI.
        """
        used_components = set()
        for row in range(self.roi_table.rowCount()):
            component = self.component_number_from_table_index(row)
            if component is not None:
                used_components.add(component)
        return [component for component in range(self.max_component_slots) if component not in used_components]

    def _suggest_component_number(self) -> int:
        available_components = self._available_component_numbers()
        if available_components:
            return available_components[0] + 1
        return self.max_component_slots

    def _group_suggestions_by_spectrum(
        self,
        suggestions: list[AutoROISuggestion],
        settings: AutoROISuggestionSettings,
        target_group_count: int | None = None,
        max_members_per_group: int | None = None,
    ) -> list[list[AutoROISuggestion]]:
        """
        Merge spatially separate candidate boxes if their mean spectra look like the
        same underlying component.

        The detection step is image-driven first: find bright localized structures.
        This step is spectrum-driven second: decide which of those structures are
        probably manifestations of the same chemistry or morphology.
        """
        if not suggestions:
            return []
        target_group_count = max(
            1,
            int(settings.max_groups_per_component if target_group_count is None else target_group_count),
        )
        max_members_per_group = max(
            1,
            int(settings.max_rois_per_group if max_members_per_group is None else max_members_per_group),
        )
        ranked_suggestions = sorted(suggestions, key=lambda suggestion: suggestion.score, reverse=True)

        if self.raw_data is None or not settings.merge_similar_spectra:
            return [[suggestion] for suggestion in ranked_suggestions[:target_group_count]]

        threshold = float(np.clip(settings.spectral_similarity_threshold, 0.0, 1.0))
        grouped: list[dict[str, object]] = []

        for suggestion in ranked_suggestions:
            # Use the mean spectrum inside each candidate box as a compact spectral
            # fingerprint for deciding whether two spatially distant ROIs should be
            # treated as one component.
            spectrum = self._spectrum_for_bounds(suggestion)
            vector = self._normalize_spectrum_for_similarity(
                spectrum,
                sigma=float(settings.spectral_smoothing_sigma),
            )

            if vector is None:
                if len(grouped) >= target_group_count:
                    if all(
                        len(existing_group["members"]) >= max_members_per_group
                        for existing_group in grouped
                    ):
                        break
                    continue
                grouped.append({"prototype": None, "vectors": [], "members": [suggestion]})
                continue

            best_index = None
            best_similarity = -1.0
            for group_index, group in enumerate(grouped):
                prototype = group["prototype"]
                if prototype is None:
                    continue
                # Cosine similarity compares spectral shape more than absolute
                # brightness, which is what we want for "same component?" logic.
                similarity = float(np.dot(vector, prototype))   # cosine similarity without norm
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_index = group_index

            if best_index is not None and best_similarity >= threshold:
                group = grouped[best_index]
                members = group["members"]
                if len(members) >= max_members_per_group:
                    if len(grouped) >= target_group_count and all(
                        len(existing_group["members"]) >= max_members_per_group
                        for existing_group in grouped
                    ):
                        break
                    continue
                members.append(suggestion)
                vectors = group["vectors"]
                if vector is not None:
                    vectors.append(vector)
                    stacked = np.vstack(vectors)
                    prototype = np.mean(stacked, axis=0)
                    norm = np.linalg.norm(prototype)
                    group["prototype"] = prototype / norm if norm > 0 else prototype
                if len(grouped) >= target_group_count and all(
                    len(existing_group["members"]) >= max_members_per_group
                    for existing_group in grouped
                ):
                    break
                continue

            if len(grouped) >= target_group_count:
                if all(
                    len(existing_group["members"]) >= max_members_per_group
                    for existing_group in grouped
                ):
                    break
                continue

            grouped.append({"prototype": vector, "vectors": [vector], "members": [suggestion]})
            if len(grouped) >= target_group_count and all(
                len(existing_group["members"]) >= max_members_per_group
                for existing_group in grouped
            ):
                break

        grouped.sort(
            key=lambda group: max(member.score for member in group["members"]),
            reverse=True,
        )
        return [
            sorted(group["members"], key=lambda member: member.score, reverse=True)
            for group in grouped
        ]

    def _spectrum_for_bounds(self, suggestion: AutoROISuggestion) -> np.ndarray | None:
        if self.raw_data is None:
            return None

        y0 = max(0, int(np.floor(suggestion.y)))
        x0 = max(0, int(np.floor(suggestion.x)))
        y1 = min(self.raw_data.shape[1], int(np.ceil(suggestion.y + suggestion.height)))
        x1 = min(self.raw_data.shape[2], int(np.ceil(suggestion.x + suggestion.width)))
        if y1 <= y0 or x1 <= x0:
            return None

        block = self.raw_data[:, y0:y1, x0:x1]
        if block.size == 0:
            return None
        # Averaging over the candidate footprint suppresses single-pixel noise and
        # gives a representative spectrum of that spatial island.
        return np.mean(block, axis=(1, 2))

    @staticmethod
    def _normalize_spectrum_for_similarity(spectrum: np.ndarray | None, sigma: float = 0.0) -> np.ndarray | None:
        if spectrum is None:
            return None

        vector = np.asarray(spectrum, dtype=float)
        if vector.ndim != 1 or vector.size == 0:
            return None

        vector = np.nan_to_num(vector, nan=0.0, posinf=0.0, neginf=0.0)
        if sigma > 0:
            vector = gaussian_filter1d(vector, sigma=float(sigma))

        # Remove a weak baseline before normalization so the comparison is driven by
        # spectral shape, not by a constant offset.
        baseline = float(np.percentile(vector, 10))
        vector = vector - baseline
        vector[vector < 0] = 0.0
        norm = float(np.linalg.norm(vector))
        if norm <= 0:
            return None
        return vector / norm

    def _next_auto_roi_label(self, component: int) -> str:
        count = 0
        for row in range(self.roi_table.rowCount()):
            if self.component_number_from_table_index(row) != component:
                continue
            if getattr(self.rois[row], "is_auto_suggested", False):
                count += 1
        return f"Auto ROI C{component + 1}.{count + 1}"

    @staticmethod
    def _coarsen_image(image: np.ndarray, factor: int) -> np.ndarray:
        factor = max(1, int(factor))
        if factor == 1:
            return image.copy()

        height, width = image.shape
        coarse_height = height // factor
        coarse_width = width // factor
        if coarse_height == 0 or coarse_width == 0:
            return image.copy()

        cropped = image[: coarse_height * factor, : coarse_width * factor]
        return cropped.reshape(coarse_height, factor, coarse_width, factor).mean(axis=(1, 3))

    @staticmethod
    def _bbox_iou(first_box: tuple[int, int, int, int], second_box: tuple[int, int, int, int]) -> float:
        y0 = max(first_box[0], second_box[0])
        x0 = max(first_box[1], second_box[1])
        y1 = min(first_box[2], second_box[2])
        x1 = min(first_box[3], second_box[3])

        if y1 <= y0 or x1 <= x0:
            return 0.0

        intersection = float((y1 - y0) * (x1 - x0))
        first_area = float(max(0, first_box[2] - first_box[0]) * max(0, first_box[3] - first_box[1]))
        second_area = float(max(0, second_box[2] - second_box[0]) * max(0, second_box[3] - second_box[1]))
        union = first_area + second_area - intersection
        if union <= 0:
            return 0.0
        return intersection / union

    @classmethod
    def _extract_suggestions_from_response_map(
        cls,
        response_map: np.ndarray,
        settings: AutoROISuggestionSettings,
    ) -> list[AutoROISuggestion]:
        """
        Turn the 2D response map into concrete ROI box proposals.

        The logic is intentionally multi-stage: coarsen and smooth the map, sweep
        through several thresholds, label connected bright regions, then place boxes
        around local maxima inside those regions.  Using several thresholds makes
        the method less brittle: strong compact peaks and weaker broader objects can
        both survive the first pass.
        """
        response_map = np.asarray(response_map, dtype=float)
        if response_map.size == 0:
            return []

        factor = max(1, int(settings.spatial_bin_factor))
        coarse_map = cls._coarsen_image(response_map, factor)   # apply binning if desired
        if coarse_map.size == 0:
            return []

        if settings.smoothing_sigma > 0:
            # Smooth on the coarse map because this is the scale on which candidate
            # boxes are proposed.  It reduces pixel noise without pretending to know
            # sub-pixel structure.
            coarse_map = gaussian_filter(coarse_map, sigma=float(settings.smoothing_sigma))
        coarse_map = np.nan_to_num(coarse_map, nan=0.0, posinf=0.0, neginf=0.0)
        coarse_map[coarse_map < 0] = 0.0

        positive_values = coarse_map[coarse_map > 0]
        if positive_values.size == 0:
            return []

        max_value = float(np.max(positive_values))
        if max_value <= 0:
            return []

        peak_window = max(3, int(settings.peak_window))
        if peak_window % 2 == 0:
            peak_window += 1
        local_maxima = coarse_map == maximum_filter(coarse_map, size=peak_window, mode="nearest")

        suggestions: list[AutoROISuggestion] = []
        seen_boxes: list[tuple[int, int, int, int]] = []
        min_group_area = max(1, int(settings.min_group_area))
        # define the upper limit of ROIs to look out for
        target_candidates = (
            max(1, int(settings.max_groups_per_component))
            * max(1, int(settings.max_rois_per_group))
            * max(2, int(settings.candidate_pool_factor))
        )
        # try to scale actual number by pool factor since later candidates may merge to the same group

        # define 5 search levels relative to the global max to find also weaker resonances
        high_ratio = float(np.clip(settings.threshold_ratio, 0.05, 0.99))
        low_ratio = max(0.12, high_ratio * 0.35)    # clip low ratio to 1/e or at least 12 %
        threshold_ratios = np.linspace(high_ratio, low_ratio, num=5)
        percentile_levels = np.linspace(85.0, 50.0, num=5)  # stop percentile at median to avoid too much noise

        for threshold_ratio, percentile_level in zip(threshold_ratios, percentile_levels):
            robust_floor = float(np.percentile(positive_values, percentile_level))
            threshold = max(max_value * float(threshold_ratio), robust_floor)
            candidate_mask = coarse_map >= threshold
            if not candidate_mask.any():
                continue

            # Connected-component labeling turns the thresholded response map into
            # separate candidate objects that can each host one or several peaks.
            labeled_regions, n_regions = label(candidate_mask)
            for region_index in range(1, n_regions + 1):
                # find bright blobs instead of just bright pixels
                region_mask = labeled_regions == region_index
                if int(region_mask.sum()) < min_group_area:
                    # skip regions where the is not enough pixels above threshold to even draw a box
                    continue

                peak_coords = np.argwhere(local_maxima & region_mask)
                if peak_coords.size == 0:
                    coords = np.argwhere(region_mask)
                    if coords.size == 0:
                        continue
                    peak_coords = np.array([coords[np.argmax(coarse_map[coords[:, 0], coords[:, 1]])]])

                peak_coords = sorted(
                    peak_coords.tolist(),
                    key=lambda coord: coarse_map[coord[0], coord[1]],
                    reverse=True,
                )

                local_boxes: list[tuple[int, int, int, int]] = []
                for peak_y, peak_x in peak_coords:
                    peak_value = float(coarse_map[peak_y, peak_x])
                    if peak_value <= 0:
                        continue

                    # Try to draw islands based on peaks with the scipy label method
                    # connect continuous regions to form a candidate
                    local_threshold = max(threshold, peak_value * float(settings.peak_region_ratio))
                    local_mask = region_mask & (coarse_map >= local_threshold)
                    local_labels, _ = label(local_mask)
                    label_value = int(local_labels[peak_y, peak_x]) if local_labels.size else 0
                    coords = np.argwhere(local_labels == label_value) if label_value > 0 else np.argwhere(region_mask)
                    if coords.size == 0:
                        # ignore
                        continue

                    y0, x0 = coords.min(axis=0)
                    y1, x1 = coords.max(axis=0) + 1
                    coarse_box = (int(y0), int(x0), int(y1), int(x1))
                    if any(cls._bbox_iou(coarse_box, other_box) >= 0.85 for other_box in local_boxes):
                        continue
                    if any(cls._bbox_iou(coarse_box, other_box) >= 0.75 for other_box in seen_boxes):
                        continue

                    # At this point the suggestion is purely spatial: "there is a
                    # localized bright object here."  The later spectral grouping
                    # step decides whether several such boxes should share one
                    # component label.
                    scaled_suggestion = cls._scale_suggestion_to_full_resolution(
                        AutoROISuggestion(
                            component=-1,
                            y=int(y0),
                            x=int(x0),
                            height=int(y1 - y0),
                            width=int(x1 - x0),
                            score=peak_value,
                        ),
                        full_shape=response_map.shape,
                        factor=factor,
                        padding_px=int(settings.padding_px),
                    )

                    # final check: is the ROI smaller than desired? If yes, continue searching
                    min_diagonal_px = max(0.0, float(settings.min_roi_diagonal_px))
                    if min_diagonal_px > 0:
                        diagonal_px = float(np.hypot(scaled_suggestion.width, scaled_suggestion.height))
                        if diagonal_px < min_diagonal_px:
                            continue

                    local_boxes.append(coarse_box)
                    seen_boxes.append(coarse_box)
                    suggestions.append(scaled_suggestion)

                    if len(suggestions) >= target_candidates:
                        break

                if len(suggestions) >= target_candidates:
                    break

            if len(suggestions) >= target_candidates:
                break

        suggestions.sort(key=lambda suggestion: suggestion.score, reverse=True)
        return suggestions[:target_candidates]

    @staticmethod
    def _scale_suggestion_to_full_resolution(
        suggestion: AutoROISuggestion,
        full_shape: tuple[int, int],
        factor: int,
        padding_px: int,
    ) -> AutoROISuggestion:
        factor = max(1, int(factor))
        padding_px = max(0, int(padding_px))

        y0 = max(0, suggestion.y * factor - padding_px)
        x0 = max(0, suggestion.x * factor - padding_px)
        y1 = min(full_shape[0], (suggestion.y + suggestion.height) * factor + padding_px)
        x1 = min(full_shape[1], (suggestion.x + suggestion.width) * factor + padding_px)

        return AutoROISuggestion(
            component=suggestion.component,
            y=int(y0),
            x=int(x0),
            height=max(1, int(y1 - y0)),
            width=max(1, int(x1 - x0)),
            score=float(suggestion.score),
        )


    def add_last_roi_to_table(self, new_roi_id=None, component_number=None, dummy: bool = False,
                              roi_name: str or None = None,
                              is_background: bool = False) -> int:
        """
        Loads the last added ROI from self.rois list and adds it to the table.
        Args:
            new_roi_id:

        Returns:

        """
        # Clear and update the table view with current ROI information
        new_row_idx = self.roi_table.rowCount()
        roi = self.rois[-1]
        self.roi_table.insertRow(new_row_idx)

        if roi_name is not None:
            roi.label = roi_name
            self.set_roi_properties(roi, self._get_roi_base_color(roi), roi_name)
        label_item = QtWidgets.QLineEdit(roi.label)
        base_name_style = (
            "QLineEdit {"
            " border: 2px solid transparent;"
            " background-color: transparent;"
            " padding: 0px 2px;"
            " }"
        )
        label_item.setStyleSheet(base_name_style)
        label_item.setProperty("roi_base_style", base_name_style)
        label_item.textChanged.connect(lambda text, widget=label_item: self._handle_name_changed(widget, text))
        # check for label item text changes
        # label_item.cellChanged.connect(lambda text, roi_item=roi: self.update_roi_plot(roi_item))
        color_button = ColorButton(self._get_roi_base_color(roi))
        color_button.color_changed.connect(lambda col, button=color_button: self._handle_color_button_changed(button, col))

        max_cmp_number = self.max_component_slots
        resonance_combobox = QtWidgets.QComboBox()
        resonance_combobox.addItems("Compontent %i" % i for i in range(1, max_cmp_number+1))
        index = new_row_idx
        if component_number is not None:
            index = component_number
        resonance_combobox.setCurrentIndex(index % max_cmp_number)
        resonance_combobox.setProperty("last_component_number", index % max_cmp_number)
        resonance_combobox.currentIndexChanged.connect(lambda idx, combo=resonance_combobox: self._handle_component_changed(combo))
        remove_button = QtWidgets.QPushButton("Remove")
        remove_button.clicked.connect(lambda state, button=remove_button: self._handle_remove_button_clicked(button))

        show_button = QtWidgets.QPushButton("Show")
        show_button.setToolTip("Center the image view on this ROI.")
        show_button.clicked.connect(lambda state, button=show_button: self._show_roi_for_table_widget(button))

        smooth_spinbox = QtWidgets.QDoubleSpinBox()
        smooth_spinbox.setValue(0)
        smooth_spinbox.setRange(0, 100)
        smooth_spinbox.setSingleStep(.5)
        smooth_spinbox.valueChanged.connect(lambda value, widget=smooth_spinbox: self._handle_roi_update_widget_changed(widget))

        export_button = QtWidgets.QPushButton("Export")
        export_button.clicked.connect(lambda state, button=export_button: self._handle_export_button_clicked(button))

        type_item = QtWidgets.QComboBox()
        type_item.addItems(["LineROI", "RectROI", "EllipseROI", "RotatableRectROI"])
        type_item.setCurrentText("LineROI" if isinstance(roi, pg.LineROI) else "RectROI")
        type_item.setMinimumContentsLength(len("RotatableRectROI"))
        type_item.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        type_item.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)

        subtract_button = QtWidgets.QCheckBox()
        subtract_button.setChecked(False)
        subtract_button.clicked.connect(lambda state, widget=subtract_button: self._handle_subtract_toggled(widget, state))

        # Create a checkbox for the "Plot" column
        plot_checkbox = QtWidgets.QCheckBox()
        plot_checkbox.setChecked(True)
        plot_checkbox.stateChanged.connect(lambda state, widget=plot_checkbox: self._handle_plot_toggled(widget, state))

        update_checkbox = QtWidgets.QCheckBox()
        update_checkbox.setChecked(True)
        # only emit the roi_changed signal on region change finish or on region change depending on the checkbox state
        update_checkbox.stateChanged.connect(lambda state, widget=update_checkbox: self._handle_live_update_toggled(widget, state))

        background_checkbox = QtWidgets.QCheckBox()
        background_checkbox.stateChanged.connect(lambda state, widget=background_checkbox: self._handle_background_toggled(widget, state))
        background_checkbox.setChecked(is_background)

        scale_spinbox = QtWidgets.QDoubleSpinBox()
        scale_spinbox.setValue(1)
        scale_spinbox.setRange(1e-2, 10)
        scale_spinbox.setSingleStep(.05)
        scale_spinbox.valueChanged.connect(lambda value, widget=scale_spinbox: self._handle_roi_update_widget_changed(widget))

        offset_spinbox = QtWidgets.QDoubleSpinBox()
        offset_spinbox.setValue(0)
        offset_spinbox.setRange(-max_dtype_val, max_dtype_val)
        offset_spinbox.setSingleStep(500)
        offset_spinbox.valueChanged.connect(lambda value, widget=offset_spinbox: self._handle_roi_update_widget_changed(widget))

        self.roi_table.setCellWidget(new_row_idx, 0, label_item)
        self._register_table_selection_widget(label_item)
        roi_table_items = [color_button, resonance_combobox, background_checkbox, subtract_button, scale_spinbox, offset_spinbox,
                           smooth_spinbox, export_button, type_item, update_checkbox, plot_checkbox, show_button, remove_button]
        for col, item in enumerate(roi_table_items):
            self.roi_table.setCellWidget(new_row_idx, col + 1, item)
            self._register_table_selection_widget(item)
        # adjust cell widths to contents
        logger.debug(roi)
        type_item.currentTextChanged.connect(lambda shape, combo=type_item: self._handle_shape_changed(combo, shape))
        type_item.setEnabled(not dummy)
        has_fixed_w = hasattr(roi, "fixed_W")
        show_button.setEnabled((not dummy) or has_fixed_w)
        # Modify show button text depending on ROI type (dummys from other results have special treatment)
        if has_fixed_w:
            show_button.setText("Show W")
            show_button.setToolTip("Show the stored W seed image for this row.")
        if not getattr(roi, "seed_H_enabled", True):
            plot_checkbox.setChecked(False)
            plot_checkbox.setEnabled(False)
            plot_checkbox.setToolTip("This row carries only a W seed and does not plot an H spectrum.")

        state = False
        # set checked state based on the component number
        _, idx = self.is_component_defined(component_number, return_index=True)
        if idx is not None:
            state = self.roi_table.cellWidget(idx, self.widget_columns['Background']).isChecked()
        background_checkbox.setChecked(state)

        self._refresh_roi_table_layout()
        if component_number is not None:
            self._emit_label_for_component(int(component_number), preferred_row=new_row_idx)
        return new_row_idx

    from contents.spectrum_loader import SpectrumLoader
    # make sure DummyROI is imported as well
    # from contents.some_module import DummyROI

    def _build_gaussian_model_spectrum(
        self,
        peaks: list[tuple[float, float, float]],
    ) -> np.ndarray:
        """
        Sum of all Gaussian peaks in 'peaks' on self.wavenumbers.
        peaks: list of (center, hwhm, amp).
        """
        if self.wavenumbers is None:
            return np.zeros(1, dtype=float)

        model = np.zeros_like(self.wavenumbers, dtype=float)
        for center, hwhm, amp in peaks:
            model += self._gaussian_curve(center, hwhm, amp)
        return model

    def _gaussian_curve(self, center: float, hwhm: float, amp: float, remove_zeros=True) -> np.ndarray:
        """
        Half-width-at-half-max Gaussian.
        """
        sigma = hwhm / np.sqrt(2 * np.log(2.0))
        g = np.exp(-((self.wavenumbers - center) ** 2) / (2.0 * sigma ** 2))
        curve = amp * g
        if remove_zeros:
            curve[curve == 0] += np.finfo(float).eps
        return amp * g

    def update_gaussian_models_from_spectral_info(
            self, gaussian_specs: dict[int, list[tuple[float, float, float]]]
    ):
        """
        Main entry point called by AnalysisManager.

        - Parses spectral_info_list from the resonance table.
        - Extracts Gaussian settings (Use Gaussian == True).
        - For each component:
            * computes the model spectrum (sum of Gaussians),
            * creates/updates a Gaussian dummy ROI row,
            * makes sure the curves are plotted.

        Parameters
        ----------
        gaussian_specs : dict[int, list[tuple[float, float, float]]]
            Pre-parsed Gaussian specs by component.
        """
        self.gaussian_specs_by_component = gaussian_specs

        comps_updated = set(gaussian_specs.keys())
        # 2) For each component: compute model spectrum & create/update dummy ROI
        for comp_idx, peaks in gaussian_specs.items():
            logger.info(f"Building Gaussian model for component {comp_idx} with {len(peaks)} peaks")
            model_spectrum = self._build_gaussian_model_spectrum(peaks)
            self._create_or_update_gaussian_dummy_roi(comp_idx, model_spectrum)

        # 3) Remove any Gaussian dummy ROIs for components no longer using Gaussian models
        existing_dummy_comps = self._existing_dummy_gaussian_rois()
        for comp_idx in existing_dummy_comps:
            if comp_idx not in comps_updated:
                self._remove_gaussian_dummy_roi(comp_idx)

    def _remove_gaussian_dummy_roi(self, component: int):
        """
        Remove the Gaussian dummy ROI for 'component', if it exists.
        """
        row = self.find_gaussian_dummy_row_for_component(component)
        if row is not None:
            logger.info(f"Removing Gaussian dummy ROI for component {component}")
            roi = self.rois[row]
            self.remove_roi(roi)

    def _existing_dummy_gaussian_rois(self) -> list[int]:
        """
        Return a list of component indices that have Gaussian dummy ROIs.
        """
        components = []
        for row in range(self.roi_table.rowCount()):
            if self.is_gaussian_dummy_row(row):
                comp_idx = self.component_number_from_table_index(row)
                if comp_idx is not None:
                    components.append(comp_idx)
        return components

    def _create_or_update_gaussian_dummy_roi(self, component: int, spectrum: np.ndarray):
        """
        Ensure there is exactly one Gaussian dummy ROI for 'component'.

        - If it already exists, update its spectrum.
        - If not, create it, add full table row + widgets (like other ROIs),
          but only name and color remain editable.
        """
        # 1) Update existing Gaussian dummy ROI if present
        row = self.find_gaussian_dummy_row_for_component(component)
        if row is not None:
            logger.info(f"Dummy ROI for component {component} exists, updating spectrum")
            roi: DummyROI = self.rois[row]
            # get the roi
            roi.update_spectrum(spectrum)
            self.update_roi_plot(roi)
            logger.info(f"Updated Gaussian dummy ROI for component {component} with new spectrum length {len(spectrum)}")
            return

        logger.info(f"Creating new Gaussian dummy ROI for component {component}")
        # 2) Create a new DummyROI, similar to prepare_roi_from_external_spectrum
        roi = DummyROI('', spectrum)
        roi.pen = pg.mkPen(self.color_manager.get_color_rgb(component) if self.color_manager else self.default_colors[
                           component % len(self.default_colors)])
        roi.is_gaussian_model = True

        self.rois.append(roi)
        roi_id = str(roi)
        self.roi_id_idx[roi_id] = len(self.rois) - 1

        row = self.add_last_roi_to_table(new_roi_id=roi_id, component_number=component, dummy=True,
                                         roi_name=f"Component {component + 1} (Gaussian model)")

        self.request_plot_avg_intensity(roi_id)
        self.new_roi_signal.emit(self.component_number_from_table_index(row))

        # 3) Lock everything except name + color
        self._lock_gaussian_row_widgets(row)

    def is_gaussian_dummy_row(self, row: int) -> bool:
        """
        Returns True if this row corresponds to a Gaussian dummy ROI.
        """
        if row >= len(self.rois):
            return False
        roi = self.rois[row]
        return getattr(roi, "is_gaussian_model", False)

    def find_gaussian_dummy_row_for_component(self, component: int) -> int | None:
        """
        Return the row index of the Gaussian dummy ROI for this component,
        or None if none exists. Ignores normal/user ROIs.
        """
        for row in range(self.roi_table.rowCount()):
            comp_idx = self.component_number_from_table_index(row)
            if comp_idx != component:
                continue
            if self.is_gaussian_dummy_row(row):
                return row
        return None

    def _lock_gaussian_row_widgets(self, row: int):
        """
        For the Gaussian dummy row:
        - Only allow editing the name and color.
        - Disable all other widgets (component selector, background, etc.).
        """
        name_col = self.widget_columns.get('Name', None)
        color_col = self.widget_columns.get('Color', None)
        plot_col = self.widget_columns.get('Plot', None)

        for col in range(self.roi_table.columnCount()):
            keep_editable = (col == name_col or col == color_col or col == plot_col)
            if keep_editable:
                continue

            w = self.roi_table.cellWidget(row, col)
            if w is not None:
                w.setEnabled(False)

            item = self.roi_table.item(row, col)
            if item is not None:
                item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)

    def load_spectra(self):
        file_name, _ = QtWidgets.QFileDialog.getOpenFileName(None, "Load spectrum", "",
                                                             "Spectrum Files (*.txt *.asc *.csv)")
        if not file_name:
            return  # Cancelled

        # Initialize loader and load all spectra
        spec_loader = SpectrumLoader(target_wavenumbers=self.wavenumbers)
        try:
            spec_loader.load_spectrum(file_name)
            spec_loader.prepare_spectrum()
        except Exception as exc:
            logger.exception("Failed to load spectrum file %s", file_name)
            QtWidgets.QMessageBox.warning(
                None,
                "Spectrum Load Failed",
                f"Could not load spectrum file:\n{file_name}\n\n{exc}",
            )
            return

        # check if more than one spectrum is loaded
        if len(spec_loader.target_spectra) == 0:
            logger.warning("No spectra loaded from file.")
            return
        elif len(spec_loader.target_spectra) > 1:
            # inform user in dialog
            QtWidgets.QMessageBox.information(None, "Multiple Spectra Loaded",
                                                f"{len(spec_loader.target_spectra)} spectra loaded from file.\n"
                                                f"Please define the component number for each spectrum.")

        # Iterate over the loaded spectra and create an ROI for each one
        for i in range(len(spec_loader.target_spectra)):
            component_number = self.component_prompt()
            if component_number is None:
                break

            # Call the preparation function, passing the specific index 'i'
            self.prepare_roi_from_external_spectrum(spec_loader, component_number, index=i)

    def prepare_roi_from_external_spectrum(self, spec_loader: SpectrumLoader, component_number: int, index: int):
        spectrum_data = spec_loader.target_spectra[index]
        spectrum_name = spec_loader.names[index]

        roi_id = self.add_dummy_roi(spectrum_data, component_number, spectrum_name)
        # This line stores the loader object. Since the loader now contains ALL spectra,
        # this mapping is technically complex, but follows your original intent to store the loader object.
        self.spectrum_loaders[roi_id] = (spec_loader, index)

    def add_dummy_roi(self, spectrum_data: np.ndarray, component_number: int, spectrum_name: str = "",
                      is_background:bool = False,
                      fixed_W: np.ndarray = None,
                      seed_H_enabled: bool = True,
                      result_seed_dummy: bool = False) -> str:
        """
        Add a DummyROI with the given spectrum data and properties. Pretends to be a loaded ROI with a spectrum.
        Parameters
        ----------
        spectrum_data: np.ndarray
            The spectrum data to associate with the DummyROI.
        component_number: int
            The component number in 1-based indexing for color selection and table entry.
        spectrum_name: str
            The name to assign to the DummyROI.
        is_background:
            Whether this ROI is marked as background in the table.
        fixed_W: np.ndarray, optional
            If provided, assigns fixed W values to the DummyROI. These will be passed with the ROI.
        seed_H_enabled: bool
            Whether this DummyROI should be considered as an H seed for reconstruction.
        result_seed_dummy: bool
            Whether this DummyROI is created from promoted NNMF results. This flag is used to identify
            and remove these rows later when new results are promoted.
        Returns
        -------
        str
            The unique ID of the created DummyROI object.
        """
        roi = DummyROI(spectrum_name, spectrum_data)
        roi.seed_H_enabled = bool(seed_H_enabled)
        roi.is_result_seed_dummy = bool(result_seed_dummy)

        # Calculate pen color (component_number - 1 converts 1-based index to 0-based for color list)
        comp_idx = component_number - 1
        roi.pen = pg.mkPen(self.color_manager.get_color_rgb(comp_idx) if self.color_manager else self.default_colors[
                           comp_idx % len(self.default_colors)])

        self.rois.append(roi)
        # Generate a unique ID to identify the ROI
        roi_id = str(roi)
        self.roi_id_idx[roi_id] = len(self.rois) - 1

        if fixed_W is not None:
            # W components directly assigned to the DummyROI, will be removed when the ROI is deleted
            self.add_W_to_roi(roi, fixed_W)

        cur_index = self.add_last_roi_to_table(new_roi_id=roi_id, component_number=comp_idx, dummy=True,
                                               roi_name=spectrum_name,
                                               is_background=is_background)  # Use the loaded name
        self.request_plot_avg_intensity(roi_id)
        self.new_roi_signal.emit(self.component_number_from_table_index(cur_index))
        return roi_id

    def load_presets(self):
        fpath, _ = QtWidgets.QFileDialog.getOpenFileName(None, "Load presets", "", "Preset Files (*.preset)")
        if not fpath:
            return

        colormap_colors, histogram_states, wavenumbers, seeds = ci.load_from_presets(fpath)

        fname = fpath.split('/')[-1].split('.')[0]

        mode_box = QtWidgets.QMessageBox()
        mode_box.setWindowTitle("Load LUT Preset")
        mode_box.setText("How should the preset be applied?")
        mode_box.setInformativeText(
            "You can import the saved spectra as dummy ROIs or only apply the LUT/histogram settings "
            "to the existing components."
        )
        load_lut_only_button = mode_box.addButton("LUTs Only", QtWidgets.QMessageBox.ActionRole)
        load_lut_and_rois_button = mode_box.addButton("LUTs + ROIs", QtWidgets.QMessageBox.ActionRole)
        cancel_button = mode_box.addButton(QtWidgets.QMessageBox.Cancel)
        mode_box.setDefaultButton(load_lut_only_button)
        mode_box.exec_()

        clicked = mode_box.clickedButton()
        if clicked == cancel_button or clicked is None:
            return

        preset_components = list(range(len(colormap_colors)))
        for idx, color in enumerate(colormap_colors):
            self._set_component_color(idx, QColor(*color), emit_signal=False)

        if clicked == load_lut_and_rois_button:
            # Check if ROIs exist and ask user to delete them before importing new spectra.
            if len(self.rois) > 0:
                reply = QtWidgets.QMessageBox.question(
                    None,
                    'Delete all ROIs?',
                    'Do you want to delete all previous ROIs before importing the preset spectra?',
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.No,
                )
                if reply == QtWidgets.QMessageBox.Yes:
                    # We must iterate over a copy of the list because remove_roi modifies self.rois
                    for roi in self.rois.copy():
                        self.remove_roi(roi)

            # 1. Initialize the SpectrumLoader ONCE
            spectrum_loader = SpectrumLoader(self.wavenumbers)
            spectrum_loader.wavenumbers = np.array(wavenumbers)

            # 2. Populate the SpectrumLoader's internal lists (spectra and names)
            for idx, seed in enumerate(seeds):
                spectrum_loader.spectra.append(np.array(seed))
                spectrum_loader.names.append(f"{fname} H{idx}")

            # 3. Process all spectra (interpolation/cutting) simultaneously.
            spectrum_loader.prepare_spectrum()

            # 4. Create ROI rows from the imported spectra.
            for idx in range(len(spectrum_loader.target_spectra)):
                component_number = idx + 1
                self.prepare_roi_from_external_spectrum(spectrum_loader, component_number, index=idx)

        self.reload_colors()
        self._emit_component_color_updates(preset_components)

        self.preset_load_signal.emit(len(seeds), histogram_states, colormap_colors)

    def get_color_rgba(self, component_number):
        # find the desired row of the component in the table
        for idx in range(self.roi_table.rowCount()):
            # extract the number of the component from the combobox
            component = self.component_number_from_table_index(idx)
            # if the component number is the same as the desired component, return the color
            if component == component_number:
                return self.roi_table.cellWidget(idx, self.widget_columns['Color']).color.getRgb()
        # if not found, return the default color
        return self.color_manager.get_color_rgb(component_number) + (255,) if self.color_manager else self.default_colors[
            component_number % len(self.default_colors)] + (255,)

    def component_number_from_table_index(self, idx: int) -> int | None:
        """
        Returns the 0-based index of the component, i.e. the first component "Component 1" will return 0.
        """
        col = self.widget_columns['Resonance']

        # Try as a widget (QComboBox)
        widget = self.roi_table.cellWidget(idx, col)
        if widget is not None:
            text = widget.currentText()
        else:
            # Fallback: maybe there is a plain QTableWidgetItem
            item = self.roi_table.item(idx, col)
            if item is None:
                return None
            text = item.text()

        # Expect something like "Component 3" or just "3"
        parts = text.split()
        if not parts:
            return None
        try:
            return int(parts[-1]) - 1
        except ValueError:
            return None

    def plot_roi(self, roi: pg.ROI, signal=None, label=''):
        roi_id = str(roi)
        if signal is None:
            signal = self.get_roi_average(roi)
        self.plot_roi_signal.emit(roi_id, signal, label)
        self.roi_plotter.plot_roi_average(roi_id, signal, label)

    @staticmethod
    def _get_roi_base_color(roi: pg.ROI) -> QtGui.QColor:
        base_pen = getattr(roi, "base_pen", None)
        if base_pen is not None:
            return base_pen.color()
        return roi.pen.color()

    def update_roi_plot(self, roi):
        """
        Helper function to update the plot of the ROI and send the signal to the plot
        Args:
            roi:

        Returns:

        """
        roi_idx = self.roi_id_idx.get(str(roi))
        if roi_idx is None:
            return
        if not getattr(roi, "seed_H_enabled", True):
            self.plot_roi(roi, np.array([]), '')
            return
        if self.roi_table.cellWidget(roi_idx, self.widget_columns['Plot']).isChecked():
            signal = self.get_roi_average(roi)
        else:
            signal = np.array([])
        roi_label = self.roi_table.cellWidget(roi_idx, self.widget_columns['Name']).text()
        self.plot_roi(roi, signal, roi_label)

    def update_roi(self, roi: pg.ROI):
        logger.info(f"Updating Smoothing and Scale of ROI {roi}")
        self.request_plot_avg_intensity(str(roi), smooth=True, scale=True, offset=True)
        # check if this roi is used for background subtraction
        if self.fill_roi is not None:
            if self.roi_table.cellWidget(self.roi_id_idx[str(roi)], self.widget_columns['Subtract']).isChecked():
                self.subtract_background(roi, refill=False)

    def add_W_to_roi(self, roi: pg.ROI, W: np.ndarray):
        roi.fixed_W = W

    def set_roi_properties(self, roi, color, label, replot=False):
        base_pen = pg.mkPen(color, width=2)
        base_pen.setCosmetic(True)
        base_hover_pen = pg.mkPen(color, width=3)
        base_hover_pen.setCosmetic(True)
        roi.base_pen = base_pen
        roi.base_hover_pen = base_hover_pen
        if not hasattr(roi, "base_z_value"):
            roi.base_z_value = roi.zValue()
        roi.label = label
        self.set_roi_highlight(roi, highlighted=roi == self.active_roi)
        if replot:
            self.update_roi_plot(roi)

    def export_roi(self, roi: pg.ROI):
        roi_idx = self.roi_id_idx.get(str(roi))
        signal = self.get_roi_average(roi).T
        header = 'rel. Intensity (a.u.)'
        # add the wavenumbers to the signal column 0 are the wavenumbers, column 1 the intensity values
        if self.wavenumbers is not None:
            signal = np.vstack((self.wavenumbers, signal)).T
            unit = getattr(self, "spectral_units", "cm⁻¹")
            if unit == "nm":
                header = "Wavelength (nm), " + header
            else:
                header = "Wavenumber (cm-1), " + header

        # open user prompt to enter name of the file, default is the label of the ROI
        file_name, _ = QtWidgets.QFileDialog.getSaveFileName(None, "Export ROI", f"{roi.label}", "CSV Files (*.csv)")
        if not file_name:
            return # Cancelled
        np.savetxt(f"{file_name}", signal, delimiter=",", header=header, comments='')
        logger.info(f"Exported ROI {roi_idx} to {file_name}")

    def remove_roi(self, roi: pg.ROI):
        roi_id = str(roi)
        index = self.roi_id_idx.get(roi_id)
        if index is None:
            logger.error("ROI %s not found in roi_id_idx mapping, cannot remove."%roi_id)
            return
        if 0 <= index < len(self.rois):
            was_active = roi == self.active_roi
            # check if the roi has been subtracted from the image
            if self.fill_roi is not None:
                # check if the table index has the subtract checkbox checked
                if self.roi_table.cellWidget(index, self.widget_columns['Subtract']).isChecked():
                    self.remove_subtraction(roi_id)

            roi = self.rois.pop(index)
            self.image_view.getView().removeItem(roi)
            # update the roi_id_idx dictionary
            if roi_id is not None:
                del self.roi_id_idx[roi_id]
            # update all rois in the dictionary with the new index when their previous index is higher than the removed one
            for roi in self.rois[index:]:
                self.roi_id_idx[str(roi)] -= 1

            # remove from signal dict
            if roi_id in self.roi_region_change_signals:
                self.disconnect(self.roi_region_change_signals[roi_id])
                del self.roi_region_change_signals[roi_id]
            if roi_id in self.roi_click_signals:
                self.disconnect(self.roi_click_signals[roi_id])
                del self.roi_click_signals[roi_id]

            if roi_id in self.spectrum_loaders:
                del self.spectrum_loaders[roi_id]
                logger.info(f"Removed loaded spectrum {roi_id}")

            self.remove_roi_plot_signal.emit(roi_id)
            self.roi_plotter.remove_plot_roi(roi_id)
            # self.update_roi_table()  # Update the table view

            cmp = self.component_number_from_table_index(index)


            self.roi_table.removeRow(index)
            self._refresh_roi_table_layout()


            new_cmp = False
            # check if another roi for this component exists and update the label name
            for idx in range(self.roi_table.rowCount()):
                if self.component_number_from_table_index(idx) == cmp:
                    # update the label name
                    self.label_change_signal.emit(
                        cmp,
                        self.roi_table.cellWidget(idx, self.widget_columns['Name']).text(),
                    )
                    new_cmp = True
                    break
            if not new_cmp and cmp is not None:
                # if no other roi exists for this component, set back to default name
                self.label_change_signal.emit(cmp, f"Component {cmp}")
            if self.active_roi in self.rois:
                self._select_roi(self.active_roi, ensure_image_visible=False, ensure_table_visible=False)
            elif was_active:
                self.active_roi = None
                if self.rois:
                    self._select_roi_by_row(min(index, len(self.rois) - 1), ensure_image_visible=False, ensure_table_visible=True)
                else:
                    self._set_table_row_highlight(None)
            logger.info(f"Removed ROI {index}")

    def remove_all_rois(self):
        if not self.rois:
            return
        for roi in reversed(self.rois.copy()):  # make a hard copy to not reverse the initial list
            self.remove_roi(roi)


    def hide_roi(self, roi: pg.ROI, state: bool):
        self.update_roi_plot(roi)

    def update_roi_color_component(self, component_number, color: QtGui.QColor):
        """
        Updates the color of a given component in the table and the corresponding ROI. Is called externally.
        """
        logger.debug(f'Updating color of component {component_number} to {color}')
        # finding the component in the table
        for idx in range(self.roi_table.rowCount()):
            if self.component_number_from_table_index(idx) == component_number:
                self._set_component_color(component_number, color, emit_signal=False)
                logger.debug(f'Updating color of component {component_number} at index {idx} to {color.getRgb()}')
                self.update_roi_color(idx, color, emit_signal=False)  # do not emit the signal to avoid infinite loop

    def update_roi_color(self, roi_idx, qcolor: QtGui.QColor, emit_signal=True):
        logger.debug('Color update', qcolor)
        self._apply_row_color(roi_idx, qcolor, update_widget=True)
        if emit_signal:
            self.color_change_signal.emit(roi_idx, qcolor.getRgb()[:-1])

    def reload_colors(self):
        if self.color_manager:
            for idx in range(self.roi_table.rowCount()):
                component_number = self.component_number_from_table_index(idx)
                qcolor = self.color_manager.get_qcolor(component_number)
                self.update_roi_color(idx, qcolor, emit_signal=False)
            self.roi_plotter.refresh_all_component_fallbacks()

    def update_selected_roi(self, *_):
        if self._selection_sync_in_progress:
            return
        selected_row = self.roi_table.currentRow()
        if selected_row < 0:
            return
        logger.debug('New ROI selected in Table')
        self._select_roi_by_row(
            selected_row,
            ensure_image_visible=False,
            ensure_table_visible=False,
            sync_table_selection=False,
        )

    def change_roi_type(self, roi_shape, row_idx):
        old_roi = self.rois[row_idx]
        old_roi_id = str(old_roi)
        was_active = old_roi == self.active_roi
        new_roi = None

        if roi_shape == 'RectROI':
            new_roi = pg.RectROI(old_roi.pos(), old_roi.size(), pen=old_roi.pen, movable=True)
        elif roi_shape == 'LineROI':
            new_roi = pg.LineSegmentROI(old_roi.pos(), old_roi.size(), pen=old_roi.pen, movable=True)
        elif roi_shape == 'EllipseROI':
            new_roi = pg.EllipseROI(old_roi.pos(), old_roi.size(), pen=old_roi.pen, movable=True)
        elif roi_shape == 'CircleROI':
            new_roi = pg.CircleROI(old_roi.pos(), old_roi.size(), pen=old_roi.pen, movable=True)
        elif roi_shape == 'RotatableRectROI':
            new_roi = pg.RectROI(old_roi.pos(), old_roi.size(), pen=old_roi.pen, movable=True)
            new_roi.addRotateHandle([0, 0], [0.5, 0.5])
        else:
            return
        if new_roi:
            new_roi.label = old_roi.label
            new_roi.setZValue(old_roi.zValue())
            for attr_name in ("is_auto_suggested", "auto_suggestion_score", "base_z_value"):
                if hasattr(old_roi, attr_name):
                    setattr(new_roi, attr_name, getattr(old_roi, attr_name))
            if hasattr(old_roi, "base_pen"):
                new_roi.base_pen = pg.mkPen(old_roi.base_pen)
            if hasattr(old_roi, "base_hover_pen"):
                new_roi.base_hover_pen = pg.mkPen(old_roi.base_hover_pen)
            self.image_view.removeItem(old_roi)
            self.remove_roi_plot_signal.emit(str(old_roi))
            self.roi_plotter.remove_plot_roi(str(old_roi))
            self.image_view.addItem(new_roi)
        row_idx = self.rois.index(old_roi)
        self.rois[row_idx] = new_roi
        if old_roi_id in self.roi_id_idx:
            del self.roi_id_idx[old_roi_id]
        self.roi_id_idx[str(new_roi)] = row_idx
        if old_roi_id in self.roi_region_change_signals:
            self.disconnect(self.roi_region_change_signals[old_roi_id])
            del self.roi_region_change_signals[old_roi_id]
        if old_roi_id in self.roi_click_signals:
            self.disconnect(self.roi_click_signals[old_roi_id])
            del self.roi_click_signals[old_roi_id]
        self.connect_signals_to_roi(
            new_roi,
        )
        self.request_plot_avg_intensity(str(new_roi))
        if was_active:
            self._select_roi(new_roi, ensure_image_visible=False, ensure_table_visible=True)
        else:
            self.set_roi_highlight(new_roi, highlighted=False)

    def connect_signals_to_roi(self, roi: pg.ROI, on_region_change=True):
        roi_id = str(roi)
        if roi_id in self.roi_region_change_signals:
            self.disconnect(self.roi_region_change_signals[roi_id])
        if on_region_change:
            sig = roi.sigRegionChanged.connect(lambda: self.request_plot_avg_intensity(roi_id))
        else:
            sig = roi.sigRegionChangeFinished.connect(lambda: self.request_plot_avg_intensity(roi_id))
            logger.warning(f'Switched to region change finished for {roi_id}')
        self.roi_region_change_signals[roi_id] = sig
        if not isinstance(roi, DummyROI) and hasattr(roi, "sigClicked"):
            roi.setAcceptedMouseButtons(QtCore.Qt.LeftButton)
            if roi_id in self.roi_click_signals:
                self.disconnect(self.roi_click_signals[roi_id])
            self.roi_click_signals[roi_id] = roi.sigClicked.connect(
                lambda clicked_roi, event, roi_item=roi: self._on_roi_clicked(roi_item, event)
            )

    def sync_components(self, roi: pg.ROI, state: bool):
        """
        Function to synchronize the background state of the components
        Args:
            roi (pg.ROI): The ROI object
            state (bool): The state of the checkbox
        Returns:

        """
        roi_idx = self.roi_id_idx.get(str(roi))
        # get the component number of the current ROI
        component = self.component_number_from_table_index(roi_idx)

        # find all rows with the same component number and check the background checkbox
        for idx in range(self.roi_table.rowCount()):
            if self.component_number_from_table_index(idx) == component:
                self.roi_table.cellWidget(idx, self.widget_columns['Background']).setChecked(state)
        # replot is needed as the background selection requires unsubtracted data for the roi
        self.replot_all_rois()

    def is_component_defined(self, component, return_index=False):
        for idx in range(self.roi_table.rowCount()):
            if self.component_number_from_table_index(idx) == component:
                roi = self.rois[idx] if idx < len(self.rois) else None
                if roi is not None and not getattr(roi, "seed_H_enabled", True):
                    continue
                if return_index:
                    return True, idx
                return True
        if return_index:
            return False, None
        return False

    def component_has_plotted_roi(self, component: int) -> bool:
        """
        Returns True if there is at least one ROI assigned to *component*
        whose 'Plot' checkbox is currently checked.
        """
        for idx in range(self.roi_table.rowCount()):
            if self.component_number_from_table_index(idx) == component:
                plot_chk = self.roi_table.cellWidget(idx, self.widget_columns['Plot'])
                if plot_chk is not None and plot_chk.isChecked():
                    return True
        return False

    def component_has_fixed_W(self, component: int) -> bool:
        """
        Returns True if there is at least one ROI assigned to *component*
        that has fixed_W defined.
        """
        for idx in range(self.roi_table.rowCount()):
            if self.component_number_from_table_index(idx) == component:
                roi = self.rois[idx]
                if hasattr(roi, 'fixed_W'):
                    return True
        return False

    def set_roi_highlight(self, roi, highlighted=True):
        """
        Change the color of the ROI to highlight it
        Args:
            roi: (pg.ROI) The ROI object to be highlighted
            highlighted: (bool) If True, the ROI will be highlighted, otherwise it will be unhighlighted
        """
        if roi is None or isinstance(roi, DummyROI):
            return

        roi_idx = self.roi_id_idx.get(str(roi))
        if not hasattr(roi, "base_pen"):
            # load the color from the widget if no base pen has been assigned yet
            if roi_idx is not None:
                color_widget = self.roi_table.cellWidget(roi_idx, self.widget_columns['Color'])
                color = color_widget.color if color_widget is not None else roi.pen.color()
            else:
                color = roi.pen.color()
            roi.base_pen = pg.mkPen(color, width=2)
            roi.base_pen.setCosmetic(True)
            roi.base_hover_pen = pg.mkPen(color, width=3)
            roi.base_hover_pen.setCosmetic(True)
        if not hasattr(roi, "base_z_value"):
            roi.base_z_value = roi.zValue()

        if highlighted:
            pen = pg.mkPen((255, 235, 120), width=4)
            pen.setCosmetic(True)
            roi.hoverPen = pg.mkPen((255, 255, 255), width=5)
            roi.hoverPen.setCosmetic(True)
            roi.setZValue(float(roi.base_z_value) + 1000.0)
        else:
            pen = pg.mkPen(roi.base_pen)
            roi.hoverPen = pg.mkPen(getattr(roi, "base_hover_pen", roi.base_pen))
            roi.setZValue(float(roi.base_z_value))

        roi.setPen(pen)
        # replot the ROI with the correct pen
        if roi_idx is not None:
            name_widget = self.roi_table.cellWidget(roi_idx, self.widget_columns['Name'])
            if name_widget is not None:
                self.plot_roi(roi, label=name_widget.text())

    def get_roi_mean_curves(self) -> list[dict]:
        # iterate over all entries in the table, sort them by their resonance given in the combobox and average identical resonances together
        resonances = []
        # find all resonances
        for idx in range(self.roi_table.rowCount()):
            roi = self.rois[idx]
            if not getattr(roi, "seed_H_enabled", True):
                continue
            # get the resonance of the current ROI
            resonance = self.roi_table.cellWidget(idx, self.widget_columns['Resonance']).currentText()
            # find all ROIs with the same resonance
            if resonance not in resonances:
                resonances.append(resonance)
        # create a list of lists with the mean curves for each resonance
        mean_curves = []
        for resonance in resonances:
            curves = []
            res_index = None
            for idx in range(self.roi_table.rowCount()):
                roi = self.rois[idx]
                if not getattr(roi, "seed_H_enabled", True):
                    continue
                if self.roi_table.cellWidget(idx, self.widget_columns['Resonance']).currentText() == resonance:
                    xy_avg = self.get_roi_average(roi)
                    curves.append(xy_avg)
                    res_index = idx
            if not curves or res_index is None:
                continue
            # average the curves and add them to the list of dictionaries where 'H' stores the mean curve, 'resonance' the resonance and 'label' the user defined label
            logger.info(f"Averaging {len(curves)} curves for  H[{resonance}]]")
            mean_curves.append({
                'H': np.mean(curves, axis=0),
                'resonance': resonance,
                'label': self.roi_table.cellWidget(res_index, self.widget_columns['Name']).text(),
                'is_background': bool(self.roi_table.cellWidget(res_index, self.widget_columns['Background']).isChecked()),
            })
        return mean_curves

    def subtract_background(self, roi: pg.ROI , refill=True):
        """
        Function to subtract the background level from each image slice in the stack
        Args:
            roi_idx:

        Returns:

        """
        logger.info('Subtracting background')
        roi_idx = self.roi_id_idx.get(str(roi))
        if self.fill_roi is not None:
            # check if the fill_roi.roi is the same as the current roi
            if self.fill_roi.roi != roi:
                self.remove_subtraction()
                # uncheck all subtract checkboxes except for the current roi
                for idx in range(self.roi_table.rowCount()):
                    if idx != roi_idx:
                        self.roi_table.cellWidget(idx, self.widget_columns['Subtract']).setChecked(False)

        # set the background checkbox to checked
        self.roi_table.cellWidget(roi_idx, self.widget_columns['Background']).setChecked(True)
        if refill:            # Create a semi-transparent rectangle inside the ROI
            self.fill_roi = FillROI(roi)
            self.fill_roi.fill()
        if self.subtract_signal is None:
            # pass the index always from the dictionary as it might have changed upon deletion of other ROIs
            self.subtract_signal = roi.sigRegionChangeFinished.connect(lambda: self.subtract_background(roi,
                                                                                                        refill=False))
        # Subtract the background from the ROI
        spectral_background = self.get_roi_average(roi)
        tiled_background = spectral_background[:, np.newaxis, np.newaxis]
        # subtract the average background for each Raman shift from the image stack
        self.subtracted_data = self.raw_data - tiled_background
        self.subtracted_data[self.subtracted_data <= 0] = sys.float_info.epsilon
        """
        # debug: show the subtracted data in a pg imageview
        self.debug_image_view = pg.ImageView()
        self.debug_image_view.setImage(self.subtracted_data, axes={'t': 0, 'x': 2, 'y': 1})
        self.debug_image_view.show()
        # compare with the initial data to see the difference
        """
        # request to replot all rois
        try:
            self.replot_all_rois()
        except Exception as e:
            logger.error(f'Error replotting ROIs after background subtraction: {e}. Data not fully updated.')
            logger.error(f"Raw data shape: {self.raw_data.shape}, Subtracted data shape: {self.subtracted_data.shape}")
        self.processed_data_signal.emit(self.subtracted_data)

    def get_background_components(self) -> list:
        # find all checkboxes where the background is checked
        background_components = []
        for idx in range(self.roi_table.rowCount()):
            if self.roi_table.cellWidget(idx, self.widget_columns['Background']).isChecked():
                background_components.append(self.component_number_from_table_index(idx))
        return list(set(background_components))

    def remove_subtraction(self, roi: pg.ROI=None):
        if self.fill_roi is not None:
            self.fill_roi.restore_original_roi()
            self.fill_roi = None
            self.subtracted_data = None
            logger.info('Removed ROI subtraction')
            self.processed_data_signal.emit(np.array([]))
            self.replot_all_rois()
            self.disconnect(self.subtract_signal)
            self.subtract_signal = None

    def move_and_scale_all_rois(self, scale_factor):
        for roi in self.rois:
            self.move_and_scale_roi(roi, scale_factor)
        self.replot_all_rois()

    def move_and_scale_roi(self, roi, scale_factor):
        roi.setSize(roi.size() * scale_factor)
        roi.setPos(roi.pos() * scale_factor)

    def replot_all_rois(self):
        # convenience function to replot all rois
        for roi in self.rois:
            self.request_plot_avg_intensity(str(roi))

    def request_plot_avg_intensity(self, roi_id: str, smooth=True, scale=True, offset=True):
        # Convert ROI ID to table index
        idx = self.roi_id_idx.get(roi_id)
        logger.debug(roi_id, self.roi_id_idx.keys())
        logger.debug('Plot request', idx)
        if idx is not None and 0 <= idx < len(self.rois):
            roi = self.rois[idx]
            if roi is not None:
                if not getattr(roi, "seed_H_enabled", True):
                    self.plot_roi(roi, np.array([]), '')
                    return
                xy_avg = self.get_roi_average(roi, apply_scale=scale, apply_smoothing=smooth, apply_offset=offset,
                                              clip_negative=True)
                # Check if the checkbox is checked before emitting the signal
                if self.roi_table.cellWidget(idx, self.widget_columns['Plot']).isChecked():
                    self.plot_roi(roi, xy_avg, self.roi_table.cellWidget(idx, self.widget_columns['Name']).text())

    def get_roi_average(self, roi: pg.ROI, apply_smoothing=True, apply_scale=True, apply_offset=True,
                        clip_negative=True) -> np.array:
        # check if the roi is flagged as background via the checkbox
        processed_im = self.raw_data
        background_checK = self.roi_table.cellWidget(self.roi_id_idx[str(roi)], self.widget_columns['Background']).isChecked()
        if not background_checK and self.subtracted_data is not None:
            processed_im = self.subtracted_data
        z_stack = roi.getArrayRegion(processed_im, self.image_view.imageItem, axes=(2, 1),
                                     returnMappedCoords=False)
        logger.debug('Shape of ROI selection', z_stack.shape)
        xy_avg = np.mean(z_stack, axis=(1, 2))
        # check if the roi should be smoothed
        idx = self.roi_id_idx[str(roi)]
        smooth = self.roi_table.cellWidget(idx, self.widget_columns['Gaussian σ']).value()
        if apply_offset:
            offset = self.roi_table.cellWidget(idx, self.widget_columns['Offset']).value()
            xy_avg += offset
            if clip_negative:
                xy_avg[xy_avg <= 0] = 1
        if apply_scale:
            scale = self.roi_table.cellWidget(idx, self.widget_columns['Scale']).value()
            xy_avg *= scale
        if smooth > 0 and apply_smoothing:
            logger.warning(f'Smoothing ROI {idx} with sigma {smooth}')
            xy_avg = gaussian_filter1d(xy_avg, smooth)
        return  xy_avg

    def plot_roi_changed(self, state, roi_id):
        # Emit the signal only if the checkbox is checked
        if state == QtCore.Qt.Checked:
            self.request_plot_avg_intensity(roi_id)
        else:
            # Inform other classes if the checkbox is unchecked
            # pass empty array to plot nothing
            self.plot_roi(self.rois[self.roi_id_idx.get(roi_id)], np.array([]), '')

    def highlight_component_region(self, spectral_range, component_number: int):
        rois = self.get_rois_from_component_indices(component_number)
        for roi in rois:
            self.roi_plotter.highlight_region(spectral_range, str(roi), overwrite=False)

    def get_roi_idx(self, roi_id):
        for key, value in self.roi_id_idx.items():
            if value == str(roi_id):
                return key
        return None  # Return None if the target value is not found in the dictionary

    def get_component_seed(self, component: int) -> np.ndarray | None:
        """
        Priority:
        1) If a spatial ROI exists for this component -> mean spectrum of ROI.
        2) Else if Gaussian specs exist for this component -> summed Gaussian model.
        3) Else -> None.
        """
        # 1) real ROIs
        for idx in range(self.roi_table.rowCount()):
            if self.component_number_from_table_index(idx) != component:
                continue
            roi = self.rois[idx] if idx < len(self.rois) else None
            if roi is not None and not getattr(roi, "seed_H_enabled", True):
                continue
            if roi is not None and not getattr(roi, "is_gaussian_model", False):
                return self.get_roi_average(roi)

        # 2) Gaussian dummy ROI
        row = self.find_gaussian_dummy_row_for_component(component)
        if row is not None:
            roi = self.rois[row]
            return self.get_roi_average(roi)

        # 3) nothing
        return None

    def get_roi_from_component_index(self, component_number: int) -> pg.ROI or None:
        for idx in range(self.roi_table.rowCount()):
            if self.component_number_from_table_index(idx) == component_number:
                return self.rois[idx]
        return None

    def get_rois_from_component_indices(self, component_number: int) -> list[pg.ROI]:
        """
        Returns all ROIs assigned to the given component number.

        Parameters
        ----------
        component_number: int
            The component number to search for (in 0-based indexing).
        Returns
        -------

        """
        rois = []
        for idx in range(self.roi_table.rowCount()):
            if self.component_number_from_table_index(idx) == component_number:
                rois.append(self.rois[idx])
        return rois

    def get_components_pixels(self, components: list) -> np.ndarray or None:
        # pixels is a 2xnpixels array with the x and y coordinates of the pixels
        pixels = np.empty((2, 0), dtype=int)
        for component in components:
            component_pixels = self.get_component_pixels(component)
            pixels = np.append(pixels, component_pixels, axis=1)
            # add to pixel array
        return pixels


    def get_component_pixels(self, component) -> np.ndarray:
        """
        Returns the pixel indices inside the ROIs of a given component in the format (y, x) -> usable for indexing
        """
        rois = self.get_rois_from_component_indices(component)
        if not rois:
            return None
        y_indices = np.array([])
        x_indices = np.array([])
        for roi in rois:
            x, y = self.get_pixels_in_roi(roi)
            # add the values of the flattened arrays to the pixel array
            x_indices = np.append(x_indices, x.flatten())
            y_indices = np.append(y_indices, y.flatten())
        x_indices = x_indices.flatten()
        y_indices = y_indices.flatten()
        pixels = np.array([y_indices, x_indices], dtype=int)
        return pixels

    def get_pixels_in_roi(self, roi) -> np.ndarray:
        """Returns pixel indices inside the ROI."""
        # Get the ROI bounds in image coordinates
        x0, y0 = roi.pos()
        w, h = roi.size()

        # Generate a grid of pixel coordinates
        x_pixels = np.arange(int(x0), int(x0 + w))
        y_pixels = np.arange(int(y0), int(y0 + h))

        # Create meshgrid of (x, y) coordinates
        xx, yy = np.meshgrid(x_pixels, y_pixels)

        # Clip to ensure indices are inside image bounds
        xx = np.clip(xx, 0, self.raw_data.shape[2] - 1)  # Width dimension
        yy = np.clip(yy, 0, self.raw_data.shape[1] - 1)  # Height dimension

        return np.array([xx, yy])  # These are the pixel coordinates inside the ROI


    # ------------
    # import and export of ROIs

    # --- ROI preset I/O ---------------------------------------------------------

    def clear_all_rois(self):
        # remove from end to avoid index shifts
        for roi in list(self.rois)[::-1]:
            try:
                self.remove_roi(roi)
            except Exception:
                pass

    def export_state(self) -> dict:
        rois_out = []
        for row, roi in enumerate(self.rois):
            # skip gaussian model dummy rows (they are regenerated from resonance table)
            if getattr(roi, "is_gaussian_model", False):
                continue

            row_state = {
                "name": self.roi_table.cellWidget(row, self.widget_columns["Name"]).text(),
                "color": list(getattr(roi, "base_pen", roi.pen).color().getRgb()),  # [r,g,b,a]
                "component": int(self.component_number_from_table_index(row) or 0),
                "resonance_index": int(self.roi_table.cellWidget(row, self.widget_columns["Resonance"]).currentIndex()),
                "background": bool(self.roi_table.cellWidget(row, self.widget_columns["Background"]).isChecked()),
                "subtract": bool(self.roi_table.cellWidget(row, self.widget_columns["Subtract"]).isChecked()),
                "scale": float(self.roi_table.cellWidget(row, self.widget_columns["Scale"]).value()),
                "offset": float(self.roi_table.cellWidget(row, self.widget_columns["Offset"]).value()),
                "smooth_sigma": float(self.roi_table.cellWidget(row, self.widget_columns["Gaussian σ"]).value()),
                "roi_shape": str(self.roi_table.cellWidget(row, self.widget_columns["ROI Shape"]).currentText()),
                "live_update": bool(self.roi_table.cellWidget(row, self.widget_columns["Live Update"]).isChecked()),
                "plot": bool(self.roi_table.cellWidget(row, self.widget_columns["Plot"]).isChecked()),
            }

            is_dummy = isinstance(roi, DummyROI)
            row_state["dummy"] = bool(is_dummy)

            if is_dummy:
                row_state["spectrum_name"] = getattr(roi, "spectrum_name", row_state["name"])
                row_state["spectrum_data"] = roi.spectrum_data.tolist()
                row_state["seed_H_enabled"] = bool(getattr(roi, "seed_H_enabled", True))
                row_state["result_seed_dummy"] = bool(getattr(roi, "is_result_seed_dummy", False))
            else:
                row_state["pos"] = [float(roi.pos()[0]), float(roi.pos()[1])]
                row_state["size"] = [float(roi.size()[0]), float(roi.size()[1])]
                if hasattr(roi, "angle"):
                    try:
                        row_state["angle"] = float(roi.angle())
                    except Exception:
                        pass

            if hasattr(roi, "fixed_W"):
                row_state["fixed_W"] = roi.fixed_W.tolist()

            rois_out.append(row_state)

        return {"rois": rois_out}

    def import_state(self, state: dict):
        """
        Rebuild ROIs + table entries so the GUI looks identical after load.
        Assumes image + binning are already applied.
        """
        self.clear_all_rois()

        rois = state.get("rois", []) if isinstance(state, dict) else []
        subtract_row_to_apply = None
        imported_component_colors: dict[int, QtGui.QColor] = {}

        for entry in rois:
            dummy = bool(entry.get("dummy", False))
            roi_obj = None

            if dummy:
                # component_number is 1-based for add_dummy_roi()
                comp_1based = int(entry.get("resonance_index", 0)) + 1
                roi_id = self.add_dummy_roi(
                    spectrum_data=np.asarray(entry["spectrum_data"], dtype=float),
                    component_number=comp_1based,
                    spectrum_name=str(entry.get("spectrum_name", "")),
                    is_background=bool(entry.get("background", False)),
                    fixed_W=np.asarray(entry["fixed_W"], dtype=float) if entry.get("fixed_W") is not None else None,
                    seed_H_enabled=bool(entry.get("seed_H_enabled", True)),
                    result_seed_dummy=bool(entry.get("result_seed_dummy", False)),
                )
                roi_obj = self.rois[self.roi_id_idx[roi_id]]
                row = self.roi_id_idx[roi_id]
            else:
                # create a base RectROI, then set shape via combobox (reuses your own change_roi_type())
                pos = entry.get("pos", [0, 0])
                size = entry.get("size", [10, 10])
                roi_obj = pg.RectROI(pos, size, pen=(0, 9))
                self.image_view.getView().addItem(roi_obj)
                self.rois.append(roi_obj)
                roi_id = str(roi_obj)
                self.roi_id_idx[roi_id] = len(self.rois) - 1

                comp0 = int(entry.get("resonance_index", 0))
                row = self.add_last_roi_to_table(new_roi_id=roi_id, component_number=comp0, dummy=False,
                                                 roi_name=entry.get("name", None))
                self.connect_signals_to_roi(roi_obj, on_region_change=True)
                self.request_plot_avg_intensity(roi_id)

            # --- Apply table/widget states (block signals to avoid cascades) ---
            name_w = self.roi_table.cellWidget(row, self.widget_columns["Name"])
            color_w = self.roi_table.cellWidget(row, self.widget_columns["Color"])
            res_cb = self.roi_table.cellWidget(row, self.widget_columns["Resonance"])
            bg_cb = self.roi_table.cellWidget(row, self.widget_columns["Background"])
            sub_cb = self.roi_table.cellWidget(row, self.widget_columns["Subtract"])
            sc_sb = self.roi_table.cellWidget(row, self.widget_columns["Scale"])
            off_sb = self.roi_table.cellWidget(row, self.widget_columns["Offset"])
            sm_sb = self.roi_table.cellWidget(row, self.widget_columns["Gaussian σ"])
            shape_cb = self.roi_table.cellWidget(row, self.widget_columns["ROI Shape"])
            live_cb = self.roi_table.cellWidget(row, self.widget_columns["Live Update"])
            plot_cb = self.roi_table.cellWidget(row, self.widget_columns["Plot"])

            # add signal blockers for all widgets to prevent signals from firing while we set their values
            blockers = [QtCore.QSignalBlocker(w) for w in
                        [name_w, color_w, res_cb, bg_cb, sub_cb, sc_sb, off_sb, sm_sb, shape_cb, live_cb, plot_cb] if
                        w is not None]

            if name_w is not None:
                name_w.setText(str(entry.get("name", "")))

            entry_qcolor = None
            if color_w is not None:
                color = entry.get("color", [255, 0, 0, 255])
                entry_qcolor = QtGui.QColor(color[0], color[1], color[2], color[3])
                color_w.setColor(entry_qcolor)

            if res_cb is not None:
                res_cb.setCurrentIndex(int(entry.get("resonance_index", 0)))

            if bg_cb is not None:
                bg_cb.setChecked(bool(entry.get("background", False)))

            if sc_sb is not None:
                sc_sb.setValue(float(entry.get("scale", 1.0)))

            if off_sb is not None:
                off_sb.setValue(float(entry.get("offset", 0.0)))

            if sm_sb is not None:
                sm_sb.setValue(float(entry.get("smooth_sigma", 0.0)))

            if live_cb is not None:
                live_cb.setChecked(bool(entry.get("live_update", True)))
                # rewire ROI signals according to live_update
                try:
                    self.connect_signals_to_roi(self.rois[row], on_region_change=live_cb.isChecked())
                except Exception:
                    pass

            if plot_cb is not None:
                plot_cb.setChecked(bool(entry.get("plot", True)))

            if shape_cb is not None:
                shape_cb.setCurrentText(str(entry.get("roi_shape", "RectROI")))
                # this triggers change_roi_type via your existing signal

            # store subtract to apply AFTER everything exists
            if sub_cb is not None and bool(entry.get("subtract", False)):
                sub_cb.setChecked(True)
                subtract_row_to_apply = row

            del blockers  # release blockers

            # angle (only if the ROI supports it)
            ang = entry.get("angle", None)
            if ang is not None:
                try:
                    self.rois[row].setAngle(float(ang))
                except Exception:
                    pass

            if entry_qcolor is not None:
                component_number = self.component_number_from_table_index(row)
                if component_number is not None:
                    imported_component_colors[component_number] = QtGui.QColor(entry_qcolor)
                self._apply_row_color(row, entry_qcolor, update_widget=True)

            # ensure plots reflect imported settings
            try:
                self.update_roi(self.rois[row])
                self.update_roi_plot(self.rois[row])
            except Exception:
                pass

        # Apply subtraction once at the end (avoids repeated re-subtractions while building)
        if subtract_row_to_apply is not None:
            try:
                self.subtract_background(self.rois[subtract_row_to_apply], refill=True)
            except Exception:
                pass

        for component_number, qcolor in imported_component_colors.items():
            self._set_component_color(component_number, qcolor, emit_signal=False)

        if imported_component_colors:
            self.reload_colors()
            self._emit_component_color_updates(imported_component_colors.keys())

        self._emit_all_component_labels()

        try:
            self.replot_all_rois()
        except Exception:
            pass


class FillROI(QtCore.QObject):
    def __init__(self, roi: pg.ROI):
        super().__init__()
        self.roi: pg.ROI = roi
        self.fill_item = None  # Overlay fill item
        self._original_translate = roi.translate  # Save original translate method
        self._original_setSize = roi.setSize if hasattr(roi, "setSize") else None  # Save resizing method
        # Connect signals to update fill dynamically
        self.roi.sigRegionChanged.connect(self.reapply_fill)

    def fill(self):
        """Fill the ROI with the same color as its pen color."""
        self.clear_fill()  # Ensure previous fill is removed

        # Create a new fill item based on the ROI's shape
        path = self.roi.shape()  # Get the exact shape
        self.fill_item = QtWidgets.QGraphicsPathItem(path)

        color = self.roi.pen.color()  # Get the ROI's pen color
        color.setAlpha(100)  # Set fill color to 100/255 transparency
        self.fill_item.setBrush(pg.mkBrush(color.lighter(150)))  # Lighter shade of ROI color
        self.fill_item.setPen(pg.mkPen(None))  # No border

        # Attach fill item to ROI so it moves/resizes together
        self.fill_item.setParentItem(self.roi)
        # Optional: lock features of the ROI
        # self.lock_resizing()
        # self.lock_movement()

    def clear_fill(self):
        """Remove the existing fill item."""
        if self.fill_item is not None:
            self.fill_item.setParentItem(None)  # Detach from ROI
            self.fill_item.setPen(pg.mkPen(None))  # Ensure no border
            self.fill_item.setBrush(pg.mkBrush(None))  # Ensure no fill
            self.fill_item = None  # Reset reference


    def reapply_fill(self):
        """Reapply fill dynamically when ROI is resized or moved."""
        if self.fill_item is None:
            return  # No fill to update
        self.fill()  # Automatically clears old fill and applies new one

    def lock_movement(self):
        """Disable movement."""
        self.roi.translate = lambda *args, **kwargs: None

    def unlock_movement(self):
        """Enable movement."""
        if hasattr(self, "_original_translate"):
            self.roi.translate = self._original_translate

    def lock_resizing(self):
        """Disable resizing if the ROI supports setSize()."""
        if self._original_setSize is not None:
            self.roi.setSize = lambda *args, **kwargs: None

    def unlock_resizing(self):
        """Enable resizing."""
        if self._original_setSize is not None:
            self.roi.setSize = self._original_setSize

    def restore_original_roi(self):
        """Restore original translate and setSize methods of the ROI."""
        self.unlock_movement()
        self.unlock_resizing()  # Unlock resizing if supported
        self.clear_fill()


class ROIPlotter(pg.PlotWidget):
    def __init__(self, roi_manager: ROIManager):
        super().__init__()
        self.roi_manager = roi_manager
        self.spectral_units = "cm⁻¹"
        self.axis_labels = None
        self.set_spectral_units(self.spectral_units)
        self.setLabel('left', text='Intensity [a.u.]')
        self.curves = {}
        # add a legend to the plot
        self.legend = self.addLegend()
        self.roi_plot_dock = None
        # Add labels to the PlotWidget
        self.setLabel('bottom', 'Wavenumber [cm-1]')
        self.setLabel('left', text='Intensity [a.u.]')
        self.roi_avg_lines = dict()
        self.roi_highlights = dict()
        self.spectral_range = dict()
        # Fallback model spectra (e.g. Gaussian fits or seed spectra)
        # keyed by component index (0, 1, 2, ...)
        self.component_gaussians: dict[int, dict] = {}
        self.component_gaussian_lines: dict[int, pg.PlotDataItem] = {}

    def plot_roi_average(self, roi_id, z_data, label):
        roi_index = self.roi_manager.roi_id_idx.get(roi_id)
        roi_pen = self.roi_manager.rois[roi_index].pen

        if roi_id in self.roi_avg_lines and self.roi_avg_lines[roi_id]:
            line_item = self.roi_avg_lines[roi_id]
            self.removeItem(line_item)
        # Plot against the spectral axis only if it matches the ROI signal length.
        x_values = self.roi_manager.wavenumbers
        if x_values is None or len(x_values) != len(z_data):
            logger.warning(
                "ROI manager plot axis length mismatch (%s vs %s). Falling back to channel indices.",
                None if x_values is None else len(x_values),
                len(z_data),
            )
            x_values = np.arange(len(z_data))
        l = self.plot(
            x_values,
            z_data,
            pen=roi_pen,
            name=label,
            symbol='o',  # Shape: 'o' (circle), 's' (square), 't' (triangle), 'x' (cross) etc.
            symbolSize=6,
            symbolBrush=roi_pen.color(),
            symbolPen='w'  # White border for better visibility
        )

        self.roi_avg_lines[roi_id] = l
        self.update_highight(roi_id)
        # Add any additional configurations you need
        # ...

    # ------------------------------------------------------------------
    #  Fallback model curves (Gaussian / seed spectra per component)
    # ------------------------------------------------------------------

    def update_component_gaussians(
        self,
        wavenumbers: np.ndarray,
        gaussian_specs: dict[int, list[tuple[float, float, float]]],
    ):
        """
        Rebuild all model Gaussian curves from per-component peak definitions.

        Parameters
        ----------
        wavenumbers : 1D array
            Spectral axis in cm^-1.
        gaussian_specs : dict
            {component_index: [(center, hwhm, amp), ...], ...}
        """
        # Remove old model curves from the plot
        self.clear_component_gaussians()

        # Build and add new curves
        for comp_idx, peaks in gaussian_specs.items():
            if not peaks:
                continue

            logger.info(f"Building Gaussian model for component {comp_idx} with peaks: {peaks}")
            # Either sum up all peaks into one curve per component...
            curve = np.zeros_like(wavenumbers, dtype=float)
            for center, hwhm, amp in peaks:
                curve += self._generate_gaussian(wavenumbers, center, hwhm, amp)

            label = f"Component {comp_idx + 1} (model)"
            self.request_gaussian_component_plot(comp_idx, curve, label)

            # ...or, if you prefer one curve per peak, you'd call
            # request_gaussian_component_plot once per (center, hwhm, amp).

    def set_component_gaussian(self, component_number: int, z_data: np.ndarray, label: str | None = None):
        """
        Register / update the model spectrum (e.g. Gaussian fit) for one
        component. The curve is only shown if no ROI for this component
        is currently being plotted.

        component_number: 0-based component index
        z_data: 1D array matching roi_manager.wavenumbers
        """
        if label is None:
            label = f"Component {component_number + 1} (model)"

        # Keep room for a future 'seed' spectrum
        old = self.component_gaussians.get(component_number, {})
        self.component_gaussians[component_number] = {
            "gaussian": z_data,
            "seed": old.get("seed"),  # future WIP: you can fill this later
            "label": label,
        }
        logger.info(f"Set Gaussian/model spectrum for component {component_number}")
        self.update_component_fallback(component_number)

    def clear_component_gaussians(self):
        """Remove all stored model spectra and their plot items."""
        for comp in list(self.component_gaussian_lines.keys()):
            self.remove_component_fallback(comp)
        self.component_gaussians.clear()

    def plot_component_gaussian(self, component_number: int, z_data: np.ndarray, label: str):
        """
        Draw or update the fallback curve for one component.
        """
        if self.roi_manager.wavenumbers is None or z_data is None:
            return

        # Update existing line
        if component_number in self.component_gaussian_lines:
            line = self.component_gaussian_lines[component_number]
            line.setData(self.roi_manager.wavenumbers, z_data)
            line.setName(label)
            line.setPen(pg.mkPen(self.roi_manager.get_color_rgba(component_number)))
            return

        # New line
        color_rgba = self.roi_manager.get_color_rgba(component_number)
        pen = pg.mkPen(color_rgba)
        line = self.plot(self.roi_manager.wavenumbers, z_data, pen=pen, name=label)
        self.component_gaussian_lines[component_number] = line
        logger.info(f"Plotted fallback model for component {component_number}")

    def remove_component_fallback(self, component_number: int):
        """
        Remove the fallback curve for one component from the plot
        (if present).
        """
        line = self.component_gaussian_lines.pop(component_number, None)
        if line is not None:
            self.removeItem(line)

    def update_component_fallback(self, component_number: int):
        """
        Ensure that for this component either an ROI-based mean curve
        (if any ROI is plotted) **or** the Gaussian / seed model curve
        is shown – but never both.
        """
        # ROI present & plotted? → hide fallback
        if self.roi_manager.component_has_plotted_roi(component_number):
            self.remove_component_fallback(component_number)
            logger.info(f"Hiding fallback model for component {component_number} due to plotted ROI")
            return

        info = self.component_gaussians.get(component_number)
        if info is None:
            # no model available
            logger.info(f"No fallback model defined for component {component_number}")
            self.remove_component_fallback(component_number)
            return

        # Prefer seed spectrum (future WIP) if available, otherwise Gaussian
        z_data = info.get("seed")
        if z_data is None:
            z_data = info.get("gaussian")

        if z_data is None:
            self.remove_component_fallback(component_number)
            return

        logger.info(f"Showing fallback model for component {component_number}")
        self.plot_component_gaussian(component_number, z_data, info["label"])

    def refresh_all_component_fallbacks(self):
        """
        Re-evaluate all components: for each one, either show the ROI
        curve or the Gaussian / seed model curve.
        """
        for comp in list(self.component_gaussians.keys()):
            self.update_component_fallback(comp)

    def request_gaussian_component_plot(
            self,
            component_number: int,
            z_data: np.ndarray | None = None,
            label: str | None = None,
    ):
        """
        Public entry point to be called.

        - If `z_data` is given, it is stored as the Gaussian / model
          spectrum for this component.
        - In any case, the plot is updated such that **either**
          ROI mean curves (if present & plotted) **or** this model
          curve is visible.
        """
        if z_data is not None:
            self.set_component_gaussian(component_number, z_data, label)
        else:
            self.update_component_fallback(component_number)

    def roi_component_changed(self, roi_id, component_number):
        # remove the old highlight
        self.remove_highlight(roi_id)

        # find the new spectral range
        spectral_range: list[np.array] = self.spectral_range.get(component_number)
        logger.info(f"Component {component_number} has spectral range {spectral_range}")

        if spectral_range is not None:
            for area in spectral_range:
                self.highlight_region(area, roi_id, overwrite=False, append_to_spectral_dict=False)

        # NEW: ROI → component mapping changed; recompute fallbacks
        self.refresh_all_component_fallbacks()

    def highlight_region(self, spectral_range: np.array, roi_id, overwrite=True, append_to_spectral_dict=True):
        if roi_id in self.roi_highlights:
            if overwrite:
                self.remove_highlight(roi_id)
        else:
            self.roi_highlights[roi_id] = []
        # find the associated roi plot
        curve_of_interest = self.roi_avg_lines[roi_id]
        y = curve_of_interest.yData
        x_min, x_max = np.amin(spectral_range), np.amax(spectral_range)
        logger.debug('Highlighting ROI %s over spectral range [%s, %s].', roi_id, x_min, x_max)
        x_mask = (self.roi_manager.wavenumbers >= x_min) & (self.roi_manager.wavenumbers <= x_max)

        # filter data for filling
        x_fill = self.roi_manager.wavenumbers[x_mask]
        y_fill = y[x_mask]

        # make sure to avoid issue when there is only one point in the range
        if not len(y_fill):
            logger.warning(f'No y data found for ROI {roi_id} in the spectral range {spectral_range}. Highlight skipped.')
            return
        elif len(x_fill) < 2:
            # stretch the range a bit
            delta = .1
            x_fill = np.array([x_fill[0]-delta, x_fill[0]+delta])
            # calc the correct y points on the linear connections to the neighbor points
            y_fill = [y_fill[0], y_fill[0]]




        curve_zero = pg.PlotDataItem(x_fill, np.zeros_like(y_fill), pen=pg.mkPen('w', width=0))
        curve_masked = pg.PlotDataItem(x_fill, y_fill, pen=pg.mkPen('w', width=0))

        self.addItem(curve_zero)
        self.addItem(curve_masked)
        # Fill between the ROI plot and 0
        fill_between = pg.FillBetweenItem(curve_masked, curve_zero, brush=pg.mkBrush((100, 100, 250, 100)))
        self.addItem(fill_between)

        # Store the items in a list
        self.roi_highlights[roi_id].append(fill_between)
        component_number = self.roi_manager.component_number_from_table_index(self.roi_manager.roi_id_idx[roi_id])
        # add the spectral range to the dictionary to a list of spectral ranges
        if append_to_spectral_dict:
            if component_number in self.spectral_range:
                self.spectral_range[component_number].append(spectral_range)
            else:
                self.spectral_range[component_number] = [spectral_range]

    def update_highight(self, roi_id):
        # Callback function when ROI is moved, updating y-values of the masked curve
        if roi_id in self.roi_highlights:
            curve_of_interest = self.roi_avg_lines[roi_id]  # Get the main ROI curve
            y = curve_of_interest.yData  # Get the new y-values

            for fill in self.roi_highlights[roi_id]:
                curve_masked, curve_zero = fill.curves  # Get the highlight curves
                # Retrieve the x data from curve_masked
                x_range = curve_masked.xData
                if x_range is None:
                    logger.warning('Curve {roi_id} has no x data for highlight update and seems not to be highlighted anymore.')
                    continue
                # Extract updated y-values based on x_range
                x_mask = np.isin(self.roi_manager.wavenumbers, x_range)
                y_fill = y[x_mask]

                # Update the data of the masked curve
                curve_masked.setData(x_range, y_fill)
                # set the new curve on top of the y data curve
                curve_masked.setZValue(curve_of_interest.zValue() + 1)

    def remove_highlight(self, roi_id, delete_from_dict=True):
        if roi_id in self.roi_highlights:
            for fill_between in self.roi_highlights[roi_id]:
                self.removeItem(fill_between)
                self.removeItem(fill_between.curves[0])
                self.removeItem(fill_between.curves[1])
            self.roi_highlights[roi_id] = []  # Clear the list

    def remove_all_highlights(self, delete_spectral_info = False):
        logger.info('Removing all resonance highlights')
        for roi_id in list(self.roi_highlights.keys()):  # Use list() to avoid dict size changes
            self.remove_highlight(roi_id)
        self.roi_highlights.clear()
        if delete_spectral_info:
            self.spectral_range.clear()

    def remove_plot_roi(self, roi_id):
        if roi_id in self.roi_avg_lines and self.roi_avg_lines[roi_id]:
            line_item = self.roi_avg_lines[roi_id]
            self.removeItem(line_item)
        if roi_id in self.roi_highlights:
            self.remove_highlight(roi_id)

    def set_axis_labels(self, labels):
        self.axis_labels = None if labels is None else [str(label) for label in labels]
        self.set_spectral_units(self.spectral_units)

    def set_spectral_units(self, unit: str):
        unit = "nm" if (unit or "").strip().lower() == "nm" else "cm⁻¹"
        self.spectral_units = unit
        axis_labels = getattr(self, "axis_labels", None)
        self.setLabel('bottom', 'Channel' if axis_labels is not None else ('Wavelength [nm]' if unit == "nm" else 'Wavenumber [cm⁻¹]'))

    @staticmethod
    def _generate_gaussian(wavenumbers: np.ndarray, center_wavenumber: float, hwhm: float, amp: float = 1.0, eliminate_zeros=True) -> np.ndarray:
        """
        Generates a Gaussian curve centered at center_wavenumber with the specified FWHM.

        Args:
            wavenumbers (np.ndarray): The array of wavenumber values.
            center_wavenumber (float): The center of the Gaussian curve.
            hwhm (float): The Half Width at Half Maximum of the Gaussian curve.
            amp (float): Amplitude of the Gaussian curve.
            eliminate_zeros (bool): If True, replaces zeros with a small epsilon value. Note: the dtype of the returned array will be float.
        Returns:
            np.ndarray: A numpy array representing the Gaussian curve.
        """

        # FWHM = 2 * sqrt(2 * ln(2)) * sigma
        # sigma = FWHM / (2 * sqrt(2 * ln(2)))
        sigma = hwhm / (np.sqrt(2 * np.log(2)))

        # Gaussian formula: exp(- (x - mu)^2 / (2 * sigma^2))
        gaussian = np.exp(-((wavenumbers - center_wavenumber) ** 2) / (2 * sigma ** 2))
        gaussian *= amp

        if eliminate_zeros:
            # add float info eps to avoid errors with zeros for NNMF
            gaussian[gaussian == 0] += np.finfo(float).eps
        return gaussian


class DummyROI(pg.ROI):
    """ Dummy class to store spectral data in the ROI object """
    def __init__(self, spectrum_name, spectrum_data):
        super().__init__((0, 0), size=(1, 1))  # Position & size are arbitrary
        # make roi invisible
        self.setPen(pg.mkPen(None))
        self.spectrum_name = spectrum_name
        self.spectrum_data = np.asarray(spectrum_data).copy()  # Store the spectral data
        self.label = spectrum_name

    def getArrayRegion(self, *args, **kwargs):
        spectrum_3d = self.spectrum_data[:, np.newaxis, np.newaxis]
        return spectrum_3d # Return the stored spectral data as 3d image data to immiate the behavior of the pg.ROI class

    def update_spectrum(self, new_spectrum_data: list or np.ndarray):
        self.spectrum_data = np.asarray(new_spectrum_data).copy()

if __name__ == '__main__':
    print('Please run the main.py file to start the application')
