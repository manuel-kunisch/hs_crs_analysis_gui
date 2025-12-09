import json
import logging
import sys

import pyqtgraph as pg
from PyQt5 import QtCore, Qt  # Import the necessary modules
from PyQt5 import QtWidgets
from pyqtgraph.dockarea.Dock import Dock
from pyqtgraph.dockarea.DockArea import DockArea

from composite_image import CompositeImageViewWidget
from contents import analysis_manager, data_widgets
from contents.data_widgets import DataWidget
from contents.scalebar import ScaleBar

logger = logging.getLogger('Main')
logger.setLevel(logging.INFO)

#image_file = imread(
#    '/Users/mkunisch/Nextcloud/Manuel_BA/HS_CARS_Lung_cells_day_2_Vukosaljevic_et_al/2017_03_23_Lungcells_Day2_60mWBoth_2xZoom_16ms_Pos2_HS_CARS_ch-1_C.tif')


# example_image2 = np.moveaxis(tifffile.imread('/Users/mkunisch/Nextcloud/Manuel_BA/HS_CARS_Lung_cells_day_2_Vukosaljevic_et_al/Results/2023_05_23_15614_reshaped_NMF_2017_03_23_Lungcells_Day2_60mWBoth_2xZoom_16ms_Pos2_HS_CARS_ch-1_C.tif'),
#                            0, -1)


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

        # widget to visualize the data loaded in the data_handler widget
        self.data_widget = DataWidget()  # raw data handling
        self.data_widget.roi_manager.color_change_signal.connect(self.update_luts_result)
        self.analysis_manager = analysis_manager.AnalysisManager(roi_manager=self.data_widget.roi_manager)
        self.data_widget.roi_manager.processed_data_signal.connect(self.analysis_manager.update_modified_data)
        self.data_widget.roi_manager.preset_load_signal.connect(self.preset_loaded)
        self.analysis_manager.worker.finished.connect(lambda: self.tab_widget.setCurrentIndex(1))

        # Create a CompositeImageViewWidget widget to showcase the results
        self.result_viewer_widget = CompositeImageViewWidget()  # Create CompositeImageViewWidget widget
        # move the widget to the main thread
        self.result_viewer_widget.color_changed_signal.connect(self.update_luts_roi)
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
        self.data_handler.loader_widget.load_preset_button.clicked.connect(lambda: print('Load preset'))

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
        self.result_viewer_widget.fiji_saver.pixel_size_um = px_size_um

    def update_scale_bars(self, len: float):
        self.scale_bar_raw.update_scale_bar_len(len)
        self.scale_bar_channels.update_scale_bar_len(len)
        self.scale_bar_composite.update_scale_bar_len(len)

    def update_luts_result(self, lut_index: int, color: tuple):
        # pass the current selected color scheme to the result viewer colormaps
        self.result_viewer_widget.set_colormap(lut_index, color)
        logger.info(f'Updated color scheme {lut_index = } {color = }')

    def update_luts_roi(self, lut_index: int, color: tuple):
        # update the color scheme of the roi manager
        self.data_widget.roi_manager.update_roi_color_component(lut_index, color)
        ...

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
            "image_path": self.data_handler.loader_widget.drag_label.text(),
            "image": self.data_handler.loader_widget.image.tolist() if self.data_handler.loader_widget.image is not None else None,
            "binning_factor": self.data_handler.get_current_binning(),
            "fov": self.data_handler.loader_widget.physical_units_manager.get_fov(),
            "unit": self.data_handler.loader_widget.physical_units_manager.unit,
            # wavennumber widget
            "wavenumbers": self.data_handler.wavenumber_widget.wavenumbers.tolist(),
            "lambda_min": self.data_handler.wavenumber_widget.min_wavelength_entry.text(),
            "lambda_max": self.data_handler.wavenumber_widget.max_wavelength_entry.text(),
            "mode": self.data_handler.wavenumber_widget.beam_mode,

            # components and resonance settings
            "num_components": self.analysis_manager.num_components_spinbox.value(),
            "analysis_method": self.analysis_manager.mv_analyzer.analysis_method,
            "custom_model": self.analysis_manager.mv_analyzer.custom_nnmf_init,
            "spectral_preset": self.analysis_manager.get_all_spectral_info(),
            "w_seed_settings": [self.analysis_manager.mv_analyzer.full_W_seed, self.analysis_manager.mv_analyzer.avg_W_seed,
                                self.analysis_manager.mv_analyzer.H_weighted_W_seed],

            # rois save all rois and their table entries
            """
            "roi_manager": {
                "rois": self.data_widget.roi_manager.get_all_rois(),
                "roi_table": self.data_widget.roi_manager.get_roi_table_data(),
                "roi_labels": self.data_widget.roi_manager.get_roi_labels(),
                "roi_colors": self.data_widget.roi_manager.get_roi_colors()
            },
            """
            
            "histogram_states": {
                k: {
                    "levels": v["levels"],
                    "top_color": v["gradient"]["ticks"][1][1],  # top tick color
                    "bottom_color": v["gradient"]["ticks"][0][1],
                    "top_pos": v["gradient"]["ticks"][1][0],
                    "bottom_pos": v["gradient"]["ticks"][0][0],
                }
                for k, v in self.result_viewer_widget.histogram_states.items()
            },
            "labels": self.result_viewer_widget.custom_labels
        }

        # open a file dialog to save the preset
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Preset", "", "JSON Files (*.json)")
        with open(path, 'w') as f:
            json.dump(preset, f, indent=4)
        logger.info(f"Saved preset to {path}")

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
