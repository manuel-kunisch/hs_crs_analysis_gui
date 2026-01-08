import json
import logging
import sys

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, Qt  # Import the necessary modules
from PyQt5 import QtWidgets
from PyQt5.QtGui import QColor
from pyqtgraph.dockarea.Dock import Dock
from pyqtgraph.dockarea.DockArea import DockArea

from composite_image import CompositeImageViewWidget
from contents import analysis_manager, data_widgets
from contents.color_manager import ComponentColorManager
from contents.data_widgets import DataWidget
from contents.scalebar import ScaleBar

logger = logging.getLogger('Main')
logger.setLevel(logging.INFO)

#image_file = imread(
#    '/Users/mkunisch/Nextcloud/Manuel_BA/HS_CARS_Lung_cells_day_2_Vukosaljevic_et_al/2017_03_23_Lungcells_Day2_60mWBoth_2xZoom_16ms_Pos2_HS_CARS_ch-1_C.tif')


# example_image2 = np.moveaxis(tifffile.imread('/Users/mkunisch/Nextcloud/Manuel_BA/HS_CARS_Lung_cells_day_2_Vukosaljevic_et_al/Results/2023_05_23_15614_reshaped_NMF_2017_03_23_Lungcells_Day2_60mWBoth_2xZoom_16ms_Pos2_HS_CARS_ch-1_C.tif'),
#                            0, -1)

def _norm_spec_unit(unit: str) -> str:
    u = (unit or "").strip().lower()
    return "nm" if u == "nm" else "cm⁻¹"

def _spec_axis_label(unit: str) -> str:
    unit = _norm_spec_unit(unit)
    return "Wavelength [nm]" if unit == "nm" else "Wavenumber [cm⁻¹]"

def _spec_unit_suffix(unit: str) -> str:
    unit = _norm_spec_unit(unit)
    return " nm" if unit == "nm" else " cm⁻¹"

class MainApplication(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.main_v_layout = Qt.QVBoxLayout(self)
        self.setLayout(self.main_v_layout)
        self.setWindowTitle("HS Data Viewer")
        self.update_thread = Qt.QThread()
        # setting  the geometry of composite_image
        # setGeometry(left, top, width, height)
        self.setGeometry(0, 0, 1600, 900)

        # color manager for all components
        self.color_manager = ComponentColorManager()
        self.color_manager.sigColorChanged.connect(self.updated_widget_component_colors)

        # widget to visualize the data loaded in the data_handler widget
        self.data_widget = DataWidget(color_manager=self.color_manager)  # raw data handling
        self.analysis_manager = analysis_manager.AnalysisManager(roi_manager=self.data_widget.roi_manager)  # multivariate analysis manager
        self.data_widget.roi_manager.processed_data_signal.connect(self.analysis_manager.update_modified_data)
        self.data_widget.roi_manager.preset_load_signal.connect(self.preset_loaded)
        self.analysis_manager.worker.finished.connect(lambda: self.tab_widget.setCurrentIndex(1))

        # Create a CompositeImageViewWidget widget to showcase the results
        self.result_viewer_widget = CompositeImageViewWidget(color_manager=self.color_manager)  # Create CompositeImageViewWidget widget
        # pass the label names to the result viewer
        self.data_widget.roi_manager.label_change_signal.connect(self.result_viewer_widget.update_label)
        # on macos the widget has to be moved to the main thread to be able to open file dialogs etc.
        self.result_viewer_widget.moveToThread(self.thread())

        # add a data handler to manage all the data loading and saving
        # idea is: analysis manager provides layout of settings etc.
        self.data_handler = data_widgets.DataHandler(self.update_data,
                                                     analysis_widget=self.analysis_manager.analysis_widget,
                                                     default_binning=int(self.data_widget.binning_combo_box.currentText()))
        # connect changes of the binning combo box to the data handler to update the binning factor
        self.data_widget.request_binning_signal.connect(lambda x: self.update_binning(int(x)))
        # Add a receiver for the signal when wavenumbers change
        self.data_handler.wavenumber_widget.wavenumbers_changed.connect(self.update_wavenum_changed)
        self.data_handler.loader_widget.physical_units_manager.widget.fov_change_signal.connect(self.update_fov)
        self.data_handler.loader_widget.physical_units_manager.widget.scale_bar_length_spinbox.valueChanged.connect(self.update_scale_bars)
        self.data_handler.wavenumber_widget.custom_unit_combo.currentTextChanged.connect(self.change_spectral_units)

        # add scale bars
        px_size = self.data_handler.loader_widget.physical_units_manager.pixel_size
        self.scale_bar_raw = ScaleBar(self.data_widget.raman_raw_image_view.view.getViewBox(), px_size)
        self.scale_bar_channels = ScaleBar(self.result_viewer_widget.channel_view.view.getViewBox(), px_size)
        self.scale_bar_composite = ScaleBar(self.result_viewer_widget.composite_view.view, px_size)
        self.data_handler.loader_widget.physical_units_manager.widget.show_scalebar_checkbox.clicked.connect(self.show_scale_bars)
        self.show_scale_bars(self.data_handler.loader_widget.physical_units_manager.widget.show_scalebar_checkbox.isChecked())

        try:
            self.data_hFandler.wavenumber_widget.set_nframes(
                self.data_widget.raman_raw_image_view.getProcessedImage().shape[0])
        except AttributeError as e:
            # No imaging data exists yet
            self.data_handler.wavenumber_widget.set_nframes(1)


        # bind functionality to the load and save preset buttons
        self.data_handler.loader_widget.save_preset_button.clicked.connect(lambda boo: self.save_state())
        self.data_handler.loader_widget.load_preset_button.clicked.connect(lambda boo: self.load_state())

        # %% Initialization of objects done, now create the GUI

        # %% Data
        # Create a DockArea to contain the widgets

        # Get the DockArea from the data widget with the main widgets
        main_dock_area = self.data_widget.dock_area
        loader_dock = self.data_handler.get_dock_widget()
        main_dock_area.addDock(loader_dock, 'right',
                               self.data_widget.image_view_dock)
        self.data_widget.image_view_dock.setStretch(100)
        loader_dock.setStretch(1)
        dock_state_save_widget, save_dock_state = self.get_dock_state_widget()
        # main_dock_area.addDock(dock_state_save_widget, 'right', self.data_widget.roi_manager.roi_table_dock)

        # Making the main composite_image divided into severeal tabs
        self.tab_widget = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tab_widget)

        self.dock_area_widget = QtWidgets.QWidget()  # Placeholder widget to contain the DockArea
        self.main_v_layout = QtWidgets.QVBoxLayout(self.dock_area_widget)  # Layout for the placeholder widget
        self.parent_dock_area = DockArea()
        self.main_v_layout.addWidget(self.parent_dock_area)

        # Create a fixed composite_image for the DockArea
        dock_window = QtWidgets.QWidget()
        dock_layout = QtWidgets.QVBoxLayout(dock_window)
        dock_layout.addWidget(self.parent_dock_area)

        data_layout_widget = QtWidgets.QWidget()
        data_layout_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        data_layout = QtWidgets.QVBoxLayout(data_layout_widget)

        # add the dock with all thew widgets to the data section
        data_layout.addWidget(main_dock_area)
        # Add the fixed dock composite_image to the result section tab
        self.tab_widget.addTab(data_layout_widget, "Data Section")
        self.tab_widget.addTab(dock_window, "Result Section")

        # TODO: remove placeholder in future verions
        # global example_image2
        # self.result_viewer_widget.update_image(example_image2)

        # Final arguments before start
        self.analysis_manager.analysis_data_changed.connect(self.update_results)
        # %% Results
        # Create and configure the DockArea for the CompositeImageViewWidget in the result section

        d1 = Dock("Multivariate Analysis Images", size=(1, 1))
        # Put orientation of dock handle
        self.parent_dock_area.addDock(d1, 'top')
        d1.addWidget(self.result_viewer_widget)  # Add the CompositeImageViewWidget widget to the dock
        save_dock_state()





    def get_dock_state_widget(self) -> (Dock, callable):
        d1 = Dock("Dock Manager", size=(25, 25))

        w1 = pg.LayoutWidget()
        # label = QtWidgets.QLabel(""" -- DockArea Example --
        #         This composite_image has 6 Dock widgets in it. Each dock can be dragged
        #         by its title bar to occupy a different space within the composite_image
        #         but note that one dock has its title bar hidden). Additionally,
        #         the borders between docks may be dragged to resize. Docks that are dragged on top
        #         of one another are stacked in a tabbed layout. Double-click a dock title
        #         bar to place it in its own composite_image.
        #         """)
        saveBtn = QtWidgets.QPushButton('Save dock state')
        restoreBtn = QtWidgets.QPushButton('Restore dock state')
        restoreBtn.setEnabled(False)
        # w1.addWidget(label, row=0, col=0)
        w1.addWidget(saveBtn, row=1, col=0)
        w1.addWidget(restoreBtn, row=2, col=0)
        d1.addWidget(w1)

        state = None

        def save():
            nonlocal state
            state = self.parent_dock_area.saveState()
            restoreBtn.setEnabled(True)

        def load():
            nonlocal state
            self.parent_dock_area.restoreState(state)

        saveBtn.clicked.connect(save)
        restoreBtn.clicked.connect(load)

        return d1, saveBtn.click

    def update_wavenum_changed(self, wavenumbers):
        logger.info('wavenumbers changeds')
        logger.debug(wavenumbers)
        self.data_widget.update_wavenumbers(wavenumbers)
        self.analysis_manager.update_wavenumbers(wavenumbers)
        self.result_viewer_widget.update_wavenumbers(wavenumbers)
        # Inform Analyzer

    def update_data(self, img_array=None):
        logging.warning('Updating data')
        if img_array is None:
            img_array = self.get_current_image()
        self.data_handler.wavenumber_widget.set_nframes(img_array.shape[0])
        self.analysis_manager.update_image_data(img_array, self.data_handler.wavenumber_widget.wavenumbers)
        self.data_widget.update_img(img_array)
        # make the roi manager highlight all rois again if spectral info exists
        self.data_widget.roi_manager.roi_plotter.remove_all_highlights()
        self.analysis_manager.highlight_all_resonances()
        logger.info("Data update finished")
        logger.info(f"{"-"*50}")
        # add in future here callbacks to all classes that have to be informed about the refresh!

    def update_fov(self, fov: tuple, unit: str):
        # update the scale bar lengths
        px_size_um = self.data_handler.loader_widget.physical_units_manager.pixel_size
        if self.data_handler.loader_widget.physical_units_manager.unit == 'nm':
            px_size_um /= 1000
        elif self.data_handler.loader_widget.physical_units_manager.unit == 'mm':
            px_size_um *= 1000
        self.scale_bar_raw.update_pixel_size(px_size_um)
        self.scale_bar_channels.update_pixel_size(px_size_um)
        self.scale_bar_composite.update_pixel_size(px_size_um)
        # adjust the pixel size in the image saver such that physical units are saved correctly in Fiji
        self.result_viewer_widget.fiji_saver.pixel_size_um = px_size_um

    def update_scale_bars(self, len: float):
        self.scale_bar_raw.update_scale_bar_len(len)
        self.scale_bar_channels.update_scale_bar_len(len)
        self.scale_bar_composite.update_scale_bar_len(len)

    def change_spectral_units(self, unit: str):
        unit = _norm_spec_unit(unit)

        # 1) composite/result viewer
        self.result_viewer_widget.set_spectral_units(unit)

        # 2) ROI manager + ROI spectrum plot
        self.data_widget.set_spectral_units(unit)

        # 3) analysis resonance table + seed window label
        self.analysis_manager.set_spectral_units(unit)

        # 4) optional: your extra ROI plot in data_widgets.py if it exists
        if getattr(self.data_widget, "roi_avg_plot_wid", None) is not None:
            self.data_widget.roi_avg_plot_wid.setLabel('bottom', _spec_axis_label(unit))


    def updated_widget_component_colors(self, lut_index: int, color: QColor):
        # update the color scheme of all components in the data widget
        logger.info(f'Updating component colors: {lut_index = }, {color.getRgb() = }')
        self.data_widget.roi_manager.reload_colors()
        self.analysis_manager.reload_colors()
        self.result_viewer_widget.reload_color(lut_index)

    def update_binning(self, binning_factor: int):
        old_binning = self.data_handler.get_current_binning()
        self.data_handler.set_binning(binning_factor)
        scale = old_binning / binning_factor
        self.data_widget.roi_manager.move_and_scale_all_rois(scale)


    def show_scale_bars(self, show: bool):
        self.scale_bar_raw.setVisible(show)
        self.scale_bar_channels.setVisible(show)
        self.scale_bar_composite.setVisible(show)


    def get_current_image(self):
        return self.data_handler.loader_widget.image

    def update_results(self):
        # TODO move to update thread
        spectral_cmps, analyzed_img = self.analysis_manager.get_analysis_data()
        logger.info(f'Results data {analyzed_img.shape = }')
        self.result_viewer_widget.update_image(analyzed_img,
                                               spectral_cmps=spectral_cmps[: self.analysis_manager.mv_analyzer._n_components],
                                               spectral_cmps_seed=self.analysis_manager.mv_analyzer.seed_H,
                                               custom_model=self.analysis_manager.mv_analyzer.custom_nnmf_init,
                                               spectral_axis=0)

    def preset_loaded(self, n_components: int, v_min_vmax_states: list, color_states: list):
        self.analysis_manager.num_components_spinbox.setValue(n_components)
        self.analysis_manager.num_components_spinbox.valueChanged.emit(n_components)
        # create the histogram for the color states
        for index, state in enumerate(v_min_vmax_states):
            self.result_viewer_widget.make_color_state(index, state, color_states[index])
        print(v_min_vmax_states)

    def save_state(self):
        preset = {
            "image_path": self.data_handler.loader_widget.current_path,
            # "image": self.data_handler.loader_widget.image.tolist() if self.data_handler.loader_widget.image is not None else None,
            "binning_factor": self.data_handler.get_current_binning(),
            "fov": self.data_handler.loader_widget.physical_units_manager.get_fov(),
            "unit": self.data_handler.loader_widget.physical_units_manager.unit,
            # wavennumber widget
            "wavenumber_widget": self.data_handler.wavenumber_widget.export_state(),
            "wavenumbers": self.data_handler.wavenumber_widget.wavenumbers.tolist() if self.data_handler.wavenumber_widget.wavenumbers is not None else None,

            # components and resonance settings
            "num_components": self.analysis_manager.num_components_spinbox.value(),
            "analysis_method": self.analysis_manager.mv_analyzer.analysis_method,
            "custom_model": self.analysis_manager.mv_analyzer.custom_nnmf_init,
            "w_seed_settings": [self.analysis_manager.mv_analyzer.full_W_seed, self.analysis_manager.mv_analyzer.avg_W_seed,
                                self.analysis_manager.mv_analyzer.H_weighted_W_seed],

            # export resonance table state
            "spectral_preset": self.analysis_manager.export_resonance_table_state(),

            # export roi manager state
            "roi_manager": self.data_widget.roi_manager.export_state(),
            
            "histogram_states": {
                k: {
                    "levels": v["levels"],
                    "top_color": v["gradient"]["ticks"][1][1],  # top tick color
                    "bottom_color": v["gradient"]["ticks"][0][1],
                    "top_pos": v['levels'][1],
                    "bottom_pos": v['levels'][0],
                }
                for k, v in self.result_viewer_widget.histogram_states.items()
            },
            "labels": self.result_viewer_widget.custom_labels
        }

        # open a file dialog to save the preset
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Preset", "", "JSON Files (*.json)")
        if not path:
            return  # user cancelled
        with open(path, 'w') as f:
            json.dump(preset, f, indent=4)
        logger.info(f"Saved preset to {path}")

    def load_state(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load Preset", "", "JSON Files (*.json)")
        if not path:
            return
        with open(path, "r") as f:
            preset = json.load(f)

        # ---- ORDER MATTERS ----
        # 1) load image (so n_frames/shape exist)
        img_path = preset.get("image_path", None)
        if img_path and isinstance(img_path, str):
            try:
                self.data_handler.loader_widget.load_tiff(img_path)
            except Exception:
                pass
        elif preset.get("image", None) is not None:
            self.data_handler.loader_widget.image = np.asarray(preset["image"])

        # 2) binning (BEFORE ROIs)
        try:
            self.update_binning(int(preset.get("binning_factor", self.data_handler.get_current_binning())))
        except Exception:
            pass

        # 3) physical units
        try:
            pum = self.data_handler.loader_widget.physical_units_manager
            if "unit" in preset:
                pum.unit = preset["unit"]
            if "fov" in preset and hasattr(pum, "set_fov"):
                pum.set_fov(tuple(preset["fov"]))
        except Exception:
            pass

        # 4) wavenumbers (this updates data_widget + analysis_manager + result viewer)
        # only matters when no image is loaded yet
        if preset.get("wavenumbers", None) is not None:
            wav = np.asarray(preset["wavenumbers"], dtype=float)
            self.data_handler.wavenumber_widget.wavenumbers = wav
            self.update_wavenum_changed(wav)

        wav_state = preset.get("wavenumber_widget", None)
        if isinstance(wav_state, dict):
            self.data_handler.wavenumber_widget.import_state(wav_state)
        else:
            # legacy fallback (old preset format)
            if preset.get("lambda_min", None) is not None:
                self.data_handler.wavenumber_widget.min_wavelength_entry.setText(str(preset["lambda_min"]))
            if preset.get("lambda_max", None) is not None:
                self.data_handler.wavenumber_widget.max_wavelength_entry.setText(str(preset["lambda_max"]))
            if preset.get("mode", None) is not None:
                self.data_handler.wavenumber_widget.beam_mode = preset["mode"]

            if preset.get("wavenumbers", None) is not None:
                self.data_handler.wavenumber_widget.custom_wavenumbers = np.asarray(preset["wavenumbers"],
                                                                                    dtype=np.float32)
                self.data_handler.wavenumber_widget.source_combo.setCurrentIndex(1)  # custom
                self.data_handler.wavenumber_widget.stack.setCurrentIndex(1)

            self.data_handler.wavenumber_widget.update_wavenums()

        self.change_spectral_units(self.data_handler.wavenumber_widget.custom_unit_combo.currentText())
        # 5) ROIs (after image+binning+wavenumbers exist)
        roi_state = preset.get("roi_manager", None)
        if roi_state and hasattr(self.data_widget.roi_manager, "import_state"):
            self.data_widget.roi_manager.import_state(roi_state)

        # 6) analysis settings + resonance table
        self.analysis_manager.num_components_spinbox.setValue(int(preset.get("num_components", 3)))
        self.analysis_manager.mv_analyzer.set_custom_nnmf_init(bool(preset.get("custom_model", True)))

        rows = preset.get("spectral_preset", None)
        if rows is not None and hasattr(self.analysis_manager, "import_resonance_table_state"):
            self.analysis_manager.import_resonance_table_state(rows)


        # 7) result-viewer histograms + labels (your existing structure)
        labels = preset.get("labels", None)
        if isinstance(labels, dict) and labels:
            # snapshot so iteration can't be affected
            labels_items = list(labels.items())

            # decouple from preset dict (avoid shared reference)
            self.result_viewer_widget.custom_labels = {}

            for k, v in labels_items:
                try:
                    self.result_viewer_widget.update_label(int(k), v)  # update_label should fill custom_labels
                except Exception:
                    pass

        hist = preset.get("histogram_states", None)
        if isinstance(hist, dict):
            # best-effort: recreate color states immediately
            for k, st in hist.items():
                try:
                    idx = int(k)
                    logger.info(f"Restoring histogram state for component {idx} with levels {st['levels']} and top color {st['top_color']}")
                    self.result_viewer_widget.make_color_state(idx, st["levels"], st["top_color"])
                except Exception:
                    pass

    def switch_section(self, index):
        self.stack_widget.setCurrentIndex(index)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Close:
            if obj == self.result_dock:
                self.dock_result_viewer()
                event.ignore()  # Ignore the close event to prevent the composite_image from closing
                return True
        return super().eventFilter(obj, event)

    def dock_result_viewer(self):
        # Reparent the undocked viewer back into the dock
        self.tab_widget.addTab(self.result_dock, "Result Section")
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.result_dock)
        self.tab_widget.setCurrentIndex(0)

    # convenience method to set some default data
    def set_data(self, fpath):
        self.data_handler.loader_widget.load_tiff(fpath)
        # self.data_handler.loader_widget.text_edit.setText(fpath)
        # self.update_data()
        # set the entry in the data widget to the file path

    # set functions for closing the application
    def closeEvent(self, event):
        if self.analysis_manager.seed_window is not None:
            self.analysis_manager.seed_window.close()

if __name__ == '__main__':
    import faulthandler, signal
    faulthandler.enable(all_threads=True)
    from contents.darkmode import set_darkmode
    app = QtWidgets.QApplication(sys.argv)  # Create a QApplication instance that runs in a dedicated thread.
    # Issue: Unlike on MacOS, darkmode is not automatically set with Windows 
    set_darkmode(app)
    main_app = MainApplication()
    try:
        main_app.set_data('./example_data/2016_05_13_Nematode_K11_60mW_816,7nm_60mW_1064nm_PMT804_HyperwaveVar.mat_COR_Channel1.tif')
    except FileNotFoundError as e:
        logger.error(f"Could not load example data: {e}")

    # set default size of the main window
    main_app.resize(1920, 1080)
    # show window maximized
    # main_app.showMaximized()

    main_app.show()
    app.exec_()
