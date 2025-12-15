import logging
import sys

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtGui import QColor
from pyqtgraph.dockarea import Dock
from scipy.ndimage import gaussian_filter1d

from composite_image import max_dtype_val, CompositeImageViewWidget as ci
from contents.hs_image_view import ROITableDelegate, ColorButton
from contents.spectrum_loader import SpectrumLoader

logger = logging.getLogger('ROI Manager')

class ROIManager(QtCore.QObject):
    default_colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255),
                      (255, 255, 255), (128, 128, 128), (128, 0, 0), (128, 128, 0), (0, 128, 0), (128, 0, 128),
                      (0, 128, 128), (0, 0, 128)]
    new_roi_signal = QtCore.pyqtSignal(int)  # Signal to inform about new ROIs
    plot_roi_signal = QtCore.pyqtSignal(str, np.ndarray, str)  # Signal with ROI index and signal
    remove_roi_plot_signal = QtCore.pyqtSignal(str)  # Signal to inform about removed plots.
    processed_data_signal = QtCore.pyqtSignal(np.ndarray)  # Signal to send the processed data to the main composite_image
    color_change_signal = QtCore.pyqtSignal(int, tuple)  # Signal when color is changed in the ROI table
    label_change_signal = QtCore.pyqtSignal(int, str)  # Signal when label is changed in the ROI table
    preset_load_signal = QtCore.pyqtSignal(int, list, list)  # Signal to load a preset

    def __init__(self, image_view: pg.ImageView):
        super().__init__()
        self.image_view = image_view
        self.rois = []  # list that stores each roi object sorted by index
        self.gaussian_specs_by_component: dict[int, list[tuple[float, float, float]]] = {}
        self.roi_region_change_signals = {}
        self.active_roi = None
        self.fill_roi = None
        self.subtract_signal = None
        self.wavenumbers = None
        self.roi_id_idx = {}
        self.raw_data = self.image_view.getImageItem().image
        self.subtracted_data = None
        self.spectrum_loaders = dict()
        # Creating a dock
        # Set up the ROI table and add it to the ROI table dock
        self.roi_table_dock = Dock("Seed ROIs", size=(810, 1000))
        self.roi_table = QtWidgets.QTableWidget()
        cols = ['Name', 'Color', 'Resonance', 'Background', 'Subtract', 'Scale', 'Offset', 'Gaussian σ', 'Export',
                'ROI Shape', 'Live Update', 'Plot', 'Remove']
        self.widget_columns = dict(**{col: idx for idx, col in enumerate(cols)})
        self.roi_table.setColumnCount(len(cols))
        self.roi_table.setHorizontalHeaderLabels(cols)

        # Connect the selection changed signal of the table to a slot
        self.roi_table.itemSelectionChanged.connect(self.update_selected_roi)
        self.roi_table.setItemDelegateForColumn(3, ROITableDelegate(self.roi_table))

        # Create a button for adding a line ROI
        add_line_roi_button = QtWidgets.QPushButton("Add ROI")
        add_line_roi_button.clicked.connect(lambda: self.add_roi())

        load_spectra_button = QtWidgets.QPushButton("Load Spectrum from File")
        load_spectra_button.clicked.connect(self.load_spectra)
        
        load_preset_button = QtWidgets.QPushButton("Load Preset")
        load_preset_button.clicked.connect(self.load_presets)

        # add buttons on top of the table
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addWidget(add_line_roi_button, alignment=QtCore.Qt.AlignCenter)
        button_layout.addWidget(load_spectra_button, alignment=QtCore.Qt.AlignCenter)
        button_layout.addWidget(load_preset_button, alignment=QtCore.Qt.AlignCenter)
        button_widget = QtWidgets.QWidget()
        button_widget.setLayout(button_layout)
        self.roi_table_dock.addWidget(button_widget)
        # add the table to the dock
        self.roi_table_dock.addWidget(self.roi_table)
        # bind shortcut on del press to remove the selected row / ROI
        del_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence("Del"), self.roi_table)
        del_shortcut.activated.connect(lambda: self.remove_roi(self.rois[self.roi_table.currentRow()]))
        # self.roi_table.resizeColumnsToContents()

        # %% ROI plot
        self.roi_plot_dock= Dock("ROI Average Plot", size=(400, 300), closable=False)
        self.roi_plotter = ROIPlotter(self)
        self.roi_plot_dock.addWidget(self.roi_plotter)

    def update_data(self, data_cyx: np.ndarray = None):
        if data_cyx is None:
            self.raw_data = self.image_view.getImageItem().image
        else:
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

    def component_prompt(self) -> int:
        roi_number = len(self.rois)
        # Prompt the user to enter the component number
        component_number, ok = QtWidgets.QInputDialog.getInt(None, "Component Number", "Enter the component number",
                                                             roi_number + 1)
        if not ok:
            component_number = roi_number + 1
        return component_number

    def add_roi(self, user_prompt=True):
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
        component_number = self.component_prompt() if user_prompt else roi_number
        color = self.default_colors[component_number - 1 % len(self.default_colors)]
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
            self.set_roi_properties(roi, roi.pen.color(), roi_name)
        label_item = QtWidgets.QLineEdit(roi.label)
        label_item.textChanged.connect(lambda text, roi_item=roi: self.set_roi_properties(roi_item, roi_item.pen.color(), text, replot=True))
        label_item.textChanged.connect(lambda text: self.label_change_signal.emit(component_number, text))
        # check for label item text changes
        # label_item.cellChanged.connect(lambda text, roi_item=roi: self.update_roi_plot(roi_item))
        color_button = ColorButton(roi.pen.color())

        max_cmp_number = 9
        resonance_combobox = QtWidgets.QComboBox()
        resonance_combobox.addItems("Compontent %i" % i for i in range(1, max_cmp_number+1))
        index = new_row_idx
        if component_number is not None:
            index = component_number
        resonance_combobox.setCurrentIndex(index % max_cmp_number)
        resonance_combobox.currentIndexChanged.connect(lambda idx: self.roi_plotter.roi_component_changed(str(roi), int(idx)))
        remove_button = QtWidgets.QPushButton("Remove")
        remove_button.clicked.connect(lambda state: self.remove_roi(roi))

        smooth_spinbox = QtWidgets.QDoubleSpinBox()
        smooth_spinbox.setValue(0)
        smooth_spinbox.setRange(0, 100)
        smooth_spinbox.setSingleStep(.5)
        smooth_spinbox.valueChanged.connect(lambda value: self.update_roi(roi))

        export_button = QtWidgets.QPushButton("Export")
        export_button.clicked.connect(lambda state: self.export_roi(roi))

        type_item = QtWidgets.QComboBox()
        type_item.addItems(["LineROI", "RectROI", "EllipseROI", "RotatableRectROI"])
        type_item.setCurrentText("LineROI" if isinstance(roi, pg.LineROI) else "RectROI")
        type_item.setMaximumWidth(75)

        subtract_button = QtWidgets.QCheckBox()
        subtract_button.setChecked(False)
        subtract_button.clicked.connect(lambda state, roi_idx=new_row_idx: self.subtract_background(roi) if state else self.remove_subtraction(roi))

        # Create a checkbox for the "Plot" column
        plot_checkbox = QtWidgets.QCheckBox()
        plot_checkbox.setChecked(True)
        plot_checkbox.stateChanged.connect(lambda state: self.hide_roi(roi, state))

        update_checkbox = QtWidgets.QCheckBox()
        update_checkbox.setChecked(True)
        # only emit the roi_changed signal on region change finish or on region change depending on the checkbox state
        update_checkbox.stateChanged.connect(lambda state: self.connect_signals_to_roi(roi, state))

        background_checkbox = QtWidgets.QCheckBox()
        background_checkbox.stateChanged.connect(lambda state: self.sync_components(roi, state))
        background_checkbox.setChecked(is_background)

        scale_spinbox = QtWidgets.QDoubleSpinBox()
        scale_spinbox.setValue(1)
        scale_spinbox.setRange(1e-2, 10)
        scale_spinbox.setSingleStep(.05)
        scale_spinbox.valueChanged.connect(lambda value: self.update_roi(roi))

        offset_spinbox = QtWidgets.QDoubleSpinBox()
        offset_spinbox.setValue(0)
        offset_spinbox.setRange(-max_dtype_val, max_dtype_val)
        offset_spinbox.setSingleStep(500)
        offset_spinbox.valueChanged.connect(lambda value: self.update_roi(roi))

        self.roi_table.setCellWidget(new_row_idx, 0, label_item)
        roi_table_items = [color_button, resonance_combobox, background_checkbox, subtract_button, scale_spinbox, offset_spinbox,
                           smooth_spinbox, export_button, type_item, update_checkbox, plot_checkbox, remove_button]
        for col, item in enumerate(roi_table_items):
            self.roi_table.setCellWidget(new_row_idx, col + 1, item)
        # adjust cell widths to contents


        color_button.color_changed.connect(lambda color, roi_idx=new_row_idx: self.update_roi_color(roi_idx, color))
        logger.debug(roi)
        type_item.currentTextChanged.connect(lambda shape, row=new_row_idx: self.change_roi_type(shape, row))
        type_item.setEnabled(not dummy)

        state = False
        # set checked state based on the component number
        _, idx = self.is_component_defined(component_number, return_index=True)
        if idx is not None:
            state = self.roi_table.cellWidget(idx, self.widget_columns['Background']).isChecked()
        background_checkbox.setChecked(state)

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
        roi.pen = pg.mkPen(self.default_colors[component % len(self.default_colors)])
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
        spec_loader.load_spectrum(file_name)
        spec_loader.prepare_spectrum()

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
                      fixed_W: np.ndarray = None) -> str:
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
        Returns
        -------
        str
            The unique ID of the created DummyROI object.
        """
        roi = DummyROI(spectrum_name, spectrum_data)

        # Calculate pen color (component_number - 1 converts 1-based index to 0-based for color list)
        comp_idx = component_number - 1
        roi.pen = pg.mkPen(self.default_colors[comp_idx % len(self.default_colors)])

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

        colormap_colors, vmin_vmax, wavenumbers, seeds = ci.load_from_presets(fpath)

        fname = fpath.split('/')[-1].split('.')[0]

        # Check if ROIs exist and ask user to delete them
        if len(self.rois) > 0:
            reply = QtWidgets.QMessageBox.question(None, 'Delete all ROIs?',
                                                   'Do you want to delete all previous ROIs?',
                                                   QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                                   QtWidgets.QMessageBox.No)
            if reply == QtWidgets.QMessageBox.Yes:
                # We must iterate over a copy of the list because remove_roi modifies self.rois
                for roi in self.rois.copy():
                    self.remove_roi(roi)

        # 1. Initialize the SpectrumLoader ONCE
        spectrum_loader = SpectrumLoader(self.wavenumbers)
        spectrum_loader.wavenumbers = np.array(wavenumbers)

        # 2. Populate the SpectrumLoader's internal lists (spectra and names)
        for idx, seed in enumerate(seeds):
            # Add the seed array to the list of spectra
            spectrum_loader.spectra.append(np.array(seed))

            # Add a name to the list of names
            name = f"{fname} H{idx}"
            spectrum_loader.names.append(name)

        # 3. Process all spectra (interpolation/cutting) simultaneously
        # This populates spectrum_loader.target_spectra
        spectrum_loader.prepare_spectrum()

        # 4. Loop through the resulting target spectra and create ROIs
        for idx in range(len(spectrum_loader.target_spectra)):
            # Component number for the ROI table (starts at 1)
            component_number = idx + 1

            # FIX: Call the updated prepare_roi function with the required index
            self.prepare_roi_from_external_spectrum(spectrum_loader, component_number, index=idx)

            # Load the colormap color from the preset.
            # Use idx (0-based) for the colormap_colors list, but component_number (1-based) for the lookup.
            self.update_roi_color(component_number - 1, QColor(*colormap_colors[idx]))

        self.preset_load_signal.emit(len(seeds), vmin_vmax, colormap_colors)

        self.preset_load_signal.emit(len(seeds), vmin_vmax, colormap_colors)

    def get_color(self, component_number):
        # find the desired row of the component in the table
        for idx in range(self.roi_table.rowCount()):
            # extract the number of the component from the combobox
            component = self.component_number_from_table_index(idx)
            # if the component number is the same as the desired component, return the color
            if component == component_number:
                return self.roi_table.cellWidget(idx, self.widget_columns['Color']).color.getRgb()
        return self.default_colors[component_number % len(self.default_colors)] + (255,)

    def component_number_from_table_index(self, idx: int) -> int | None:
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

    def update_roi_plot(self, roi):
        """
        Helper function to update the plot of the ROI and send the signal to the plot
        Args:
            roi:

        Returns:

        """
        roi_idx = self.roi_id_idx.get(str(roi))
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
        roi.setPen(pg.mkPen(color))
        roi.label = label
        if replot:
            self.update_roi_plot(roi)

    def export_roi(self, roi: pg.ROI):
        roi_idx = self.roi_id_idx.get(str(roi))
        signal = self.get_roi_average(roi).T
        header = 'rel. Intensity (a.u.)'
        # add the wavenumbers to the signal column 0 are the wavenumbers, column 1 the intensity values
        if self.wavenumbers is not None:
            signal = np.vstack((self.wavenumbers, signal)).T
            header = 'Wavenumber (cm-1), ' + header
        # open user prompt to enter name of the file, default is the label of the ROI
        file_name, _ = QtWidgets.QFileDialog.getSaveFileName(None, "Export ROI", f"{roi.label}", "CSV Files (*.csv)")
        if not file_name:
            return # Cancelled
        np.savetxt(f"{file_name}", signal, delimiter=",", header=header, comments='')
        logger.info(f"Exported ROI {roi_idx} to {file_name}")

    def remove_roi(self, roi: pg.ROI):
        roi_id = str(roi)
        index = self.roi_id_idx.get(roi_id)
        if 0 <= index < len(self.rois):
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

            if roi_id in self.spectrum_loaders:
                del self.spectrum_loaders[roi_id]
                logger.info(f"Removed loaded spectrum {roi_id}")

            self.remove_roi_plot_signal.emit(roi_id)
            self.roi_plotter.remove_plot_roi(roi_id)
            # self.update_roi_table()  # Update the table view

            cmp = self.component_number_from_table_index(index)


            self.roi_table.removeRow(index)


            new_cmp = False
            # check if another roi for this component exists and update the label name
            for idx in range(self.roi_table.rowCount()):
                if self.component_number_from_table_index(idx) == cmp:
                    # update the label name
                    self.label_change_signal.emit(idx, self.roi_table.cellWidget(idx, self.widget_columns['Name']).text())#
                    new_cmp = True
                    break
            if not new_cmp:
                # if no other roi exists for this component, set back to default name
                self.label_change_signal.emit(index, f"Component {index}")
            logger.info(f"Removed ROI {index}")


    def hide_roi(self, roi: pg.ROI, state: bool):
        self.update_roi_plot(roi)

    def update_roi_color_component(self, component_number, color: QtGui.QColor):
        """
        Updates the color of a given component in the table and the corresponding ROI
        """
        logger.debug(f'Updating color of component {component_number} to {color}')
        # finding the component in the table
        for idx in range(self.roi_table.rowCount()):
            if self.component_number_from_table_index(idx) == component_number:
                self.default_colors[component_number] = color.getRgb()
                logger.debug(f'Updating color of component {component_number} at index {idx} to {color.getRgb()}')
                self.update_roi_color(idx, color, emit_signal=False)  # do not emit the signal to avoid infinite loop

    def update_roi_color(self, roi_idx, qcolor: QtGui.QColor, emit_signal=True):
        logger.debug('Color update', qcolor)
        roi = self.rois[roi_idx]
        roi.setPen(pg.mkPen(qcolor))
        # TODO: send update to plot
        self.update_roi_plot(roi)
        if emit_signal:
            self.color_change_signal.emit(roi_idx, qcolor.getRgb()[:-1])
        # update the color widget in the table
        color_widget: pg.ColorButton = self.roi_table.cellWidget(roi_idx, self.widget_columns['Color'])
        color_widget.setColor(qcolor)


    def update_selected_roi(self):
        selected_items = self.roi_table.selectedItems()
        if not selected_items:
            return
        logger.debug('New ROI selected in Table')
        selected_row = selected_items[0].row()
        if 0 <= selected_row < len(self.rois):
            selected_roi = self.rois[selected_row]
            self.active_roi = selected_roi
            # Highlight the selected ROI (change its color or style)
            for roi in self.rois:
                if roi == selected_roi:
                    self.set_roi_highlight(roi)
                else:
                    self.set_roi_highlight(roi, highlighted=False)

    def change_roi_type(self, roi_shape, row_idx):
        old_roi = self.rois[row_idx]
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
            self.image_view.removeItem(old_roi)
            self.remove_roi_plot_signal.emit(str(old_roi))
            self.roi_plotter.remove_plot_roi(str(old_roi))
            self.image_view.addItem(new_roi)
        row_idx = self.rois.index(old_roi)
        self.rois[row_idx] = new_roi
        self.roi_id_idx[str(new_roi)] = row_idx
        self.connect_signals_to_roi(new_roi)
        self.request_plot_avg_intensity(str(new_roi))

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
        roi_idx = self.roi_id_idx.get(str(roi))
        if highlighted:
            pen = pg.mkPen((255, 255, 0), width=5)
        else:
            # get the original pen of the ROI from the table
            if roi_idx is not None:
                pen = pg.mkPen(self.roi_table.cellWidget(roi_idx, self.widget_columns['Color']).color.getRgb())
            else:
                pen = pg.mkPen(roi.pen.color().getRgb())

        roi.setPen(pen)
        # replot the ROI with the correct pen
        self.plot_roi(roi, label=self.roi_table.cellWidget(roi_idx, self.widget_columns['Name']).text())

    def get_roi_mean_curves(self) -> list[dict]:
        # iterate over all entries in the table, sort them by their resonance given in the combobox and average identical resonances together
        resonances = []
        # find all resonances
        for idx in range(self.roi_table.rowCount()):
            roi = self.rois[idx]
            # get the resonance of the current ROI
            resonance = self.roi_table.cellWidget(idx, self.widget_columns['Resonance']).currentText()
            # find all ROIs with the same resonance
            if resonance not in resonances:
                resonances.append(resonance)
        # create a list of lists with the mean curves for each resonance
        mean_curves = []
        for resonance in resonances:
            curves = []
            for idx in range(self.roi_table.rowCount()):
                roi = self.rois[idx]
                if self.roi_table.cellWidget(idx, self.widget_columns['Resonance']).currentText() == resonance:
                    xy_avg = self.get_roi_average(roi)
                    curves.append(xy_avg)
                    res_index = idx
            # average the curves and add them to the list of dictionaries where 'H' stores the mean curve, 'resonance' the resonance and 'label' the user defined label
            logger.info(f"Averaging {len(curves)} curves for  H[{resonance}]]")
            mean_curves.append({'H': np.mean(curves, axis=0), 'resonance': resonance, 'label': self.roi_table.cellWidget(res_index, self.widget_columns['Name']).text()})
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
                        print('Unchecking', idx)
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
        # Plot the z_data in the new plot
        l = self.plot(self.roi_manager.wavenumbers, z_data, pen=roi_pen, name=label)

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
            return

        # New line
        color_rgba = self.roi_manager.get_color(component_number)
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
        print(f"Component {component_number} has spectral range {spectral_range}")

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
        x_mask = (self.roi_manager.wavenumbers >= x_min) & (self.roi_manager.wavenumbers <= x_max)

        # filter data for filling
        x_fill = self.roi_manager.wavenumbers[x_mask]
        y_fill = y[x_mask]

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