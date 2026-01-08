import logging
import os

import numpy as np
import pyqtgraph as pg
import tifffile
from PyQt5 import QtGui
from PyQt5.Qt import QObject
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QPointF
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QHBoxLayout, QSpinBox, QComboBox,
    QPushButton, QColorDialog, QSizePolicy, QGridLayout, QSpacerItem, QSplitter, QSlider, QCheckBox, QFileDialog)
from pyqtgraph import PlotItem

from contents.color_manager import ComponentColorManager
from contents.custom_pyqt_objects import ImageViewYXC, ImageViewLineRoiYXZ
from contents.fiji_saver import FIJISaver
from contents.scalebar import ScaleBar

max_but_size = (100, 50)
dtype = np.uint16
max_dtype_val = np.iinfo(dtype).max

logger = logging.getLogger("Composite Image Viewer")
auto_min_max = False


# TODO: add table to the widget which allows to disable certain components
class CompositeImageViewWidget(QMainWindow):
    colormap_colors = [
        (255, 0, 0),  # Red
        (0, 255, 0),  # Green
        (0, 0, 255),  # Blue
        (255, 255, 255),  # Greys
        (0, 255, 255),  # Cyan
        (255, 0, 255),  # Magenta
        (255, 255, 0),  # Yellow
        (255, 165, 0),  # Orange
        (128, 0, 128),  # Purple
        (255, 192, 203),  # Pink
    ]
    color_changed_signal = pyqtSignal(int, QColor)
    def __init__(self, img:np.ndarray = None, spectral_cmps: np.ndarray|None = None,
                 color_manager: ComponentColorManager=None):
        super().__init__()
        self.img = img
        self.color_manager = color_manager
        # sync the colormap colors with the color manager if provided
        if self.color_manager is not None:
            self.colormap_colors = self.color_manager.get_all_colors_rgb()
        self.spectral_cmps = spectral_cmps
        self.spectral_cmps_seed = None
        self.wavenumbers = None
        self.fiji_saver = FIJISaver(self.img, f'{os.path.join(os.getcwd(), "result.tif")}',
                                    colors=self.colormap_colors, dtype=np.uint16)
        self.custom_model = False
        self.update_thread = QThread()
        self.timeout_callbacks = False


        # %% GUI setup
        self.setWindowTitle("ImageViewer with Composite Image and Channels")
        self.setGeometry(100, 100, 900, 900)

        self.central_widget = QWidget(self)
        self.setCentralWidget(self.central_widget)
        self.master_v_layout = QVBoxLayout(self.central_widget)

        # Create a QHBoxLayout to hold the scrollbar and v_layout
        self.main_h_layout = QHBoxLayout()
        # Create a QHBoxLayout to hold the scrollbar, label, and color button
        option_widget_v_layout = QHBoxLayout()
        # Right column
        right_col_v_layout = QVBoxLayout()
        right_col_v_layout.setAlignment(Qt.AlignTop)
        main_img_layout = QGridLayout()

        # Create a PyqtGraph ImageView widget for the composite image
        self.composite_view = ImageViewYXC()
        self.composite_view.view.setDefaultPadding(0)
        self.composite_view.ui.roiBtn.hide()
        self.composite_view.ui.menuBtn.hide()
        self.composite_view.ui.histogram.setHistogramRange(0, max_dtype_val)
        self.composite_view.ui.histogram.axis.hide()
        self.composite_view.ui.histogram.axis.setRange(0, max_dtype_val)
        self.composite_view.ui.histogram.axis.fixedWidth = 10
        self.composite_view.ui.histogram.axis.setMaximumWidth(10)
        # self.composite_view.ui.histogram.hide()

        # %% Make splitter for the composite image and the channel view

        # adjust the image shape to the expected shape returned by the NNMF
        self.composite_view.ui.histogram.setHistogramRange(0, max_dtype_val)
        self.composite_view.ui.histogram.setLevels(0, max_dtype_val)
        main_plot_v_splitter = QSplitter()
        main_plot_v_splitter.setOrientation(Qt.Vertical)
        main_plot_v_splitter.addWidget(self.composite_view)


        # Create a PyqtGraph ImageView widget for individual channels
        component_layout = QHBoxLayout()
        self.channel_view = ImageViewLineRoiYXZ(view=PlotItem())
        self.channel_view.view.setDefaultPadding(0)
        self.spectrum_view = pg.PlotWidget(title="Spectrum", size=(100,300))
        self.spectrum_view.setLabel('left', 'Intensity counts')
        self.spectrum_view.setLabel('bottom', 'Wavenumber (1/cm)')
        self.legend = self.spectrum_view.addLegend()
        self.spectrum_lines = []
        self.seed_lines = []

        self.custom_labels: dict = {}



        # add button to save the composite image
        save_tiff_button = QPushButton("Save Composite Image")
        save_tiff_button.clicked.connect(self.save_data)
        
        # add button to save the H seeds with combobox to select the mode
        save_seeds_button = QPushButton("Save Preset")
        save_seed_mode_combobox = QComboBox()
        save_seed_mode_combobox.addItem("Results")
        save_seed_mode_combobox.addItem("Seeds")
        save_seed_mode_label = QLabel("Mode:")
        save_seeds_button.clicked.connect(lambda: self.save_preset(mode=save_seed_mode_combobox.currentText().lower()))

        save_H_as_csv_button = QPushButton("Save H as CSV")
        save_H_as_csv_button.clicked.connect(self.save_components)

        # Create a QPushButton for resetting the levels
        reset_levels_button = QPushButton("Reset Black Levels")
        # reset_levels_button.setMaximumWidth(50)
        reset_levels_button.clicked.connect(self.reset_levels)

        composite_buttons_layout = QGridLayout()
        composite_buttons_layout.addWidget(save_tiff_button, 0, 0, alignment=Qt.AlignHCenter)
        composite_buttons_layout.addWidget(save_seeds_button, 0, 1, alignment=Qt.AlignRight)
        composite_buttons_layout.addWidget(save_seed_mode_label, 0, 2, alignment=Qt.AlignRight)
        composite_buttons_layout.addWidget(save_seed_mode_combobox, 0, 3, alignment=Qt.AlignLeft)
        composite_buttons_layout.addWidget(save_H_as_csv_button, 0, 4, alignment=Qt.AlignCenter)
        composite_buttons_layout.addWidget(reset_levels_button, 0, 5, alignment=Qt.AlignRight)
        composite_buttons_widget = QWidget()
        composite_buttons_widget.setLayout(composite_buttons_layout)

        composite_widget = QWidget()
        composite_layout = QVBoxLayout()
        composite_widget.setLayout(composite_layout)
        composite_layout.addWidget(self.composite_view)
        composite_layout.addWidget(composite_buttons_widget)
        composite_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        main_plot_v_splitter.addWidget(composite_widget)
        # Create a QSplitter to contain the ImageView and PlotWidget
        components_h_splitter = QSplitter()
        # Add the widgets to the components_h_splitter
        components_h_splitter.addWidget(self.channel_view)
        components_h_splitter.addWidget(self.spectrum_view)
        # Set the orientation of the components_h_splitter (horizontal in this case)
        components_h_splitter.setOrientation(Qt.Horizontal)
        main_plot_v_splitter.addWidget(components_h_splitter)
        # Add the components_h_splitter to the layout
        main_img_layout.addWidget(main_plot_v_splitter, 0, 0, 20, 20)
        main_img_layout.addLayout(option_widget_v_layout, 20, 0, 1, 10)
        # Add v_layout to the h_layout
        self.main_h_layout.addLayout(main_img_layout, stretch=5)
        self.main_h_layout.addLayout(right_col_v_layout)

        # Set stretch factors (e.g., 2:1 ratio)
        main_plot_v_splitter.setStretchFactor(0, 2)  # composite_widget gets 2x the space
        main_plot_v_splitter.setStretchFactor(1, 1)  # components_h_splitter gets 1x the space

        # %% Buttons to modfiy the false color images
        # Create a VLayout for channel selection in preview
        channel_selection_layout = QGridLayout()
        
        image_channels = 1
        if self.img is not None:
            image_channels = self.img.shape[2]
            self.update_image(self.img)
        # Add a QScrollBar for selecting the channel
        self.channel_slider = QSlider()
        self.channel_slider.setTickPosition(QSlider.TicksBothSides)
        self.channel_slider.setTickInterval(1)
        self.channel_slider.setOrientation(1)  # Horizontal orientation
        self.channel_slider.setMinimum(0)
        self.channel_slider.setMaximum(image_channels - 1)
        self.channel_slider.setMaximumWidth(200)
        self.channel_slider.valueChanged.connect(self.callback_channel)
        # let the scrollbar expand horizontally but not vertically
        # self.channel_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # self.channel_slider.setFixedHeight(10)  # Adjust the width as needed
        # Row 1, Column 0, Span 1 row, 2 columns
        channel_selection_layout.addWidget(self.channel_slider, 1, 0, 2, 2, alignment=Qt.AlignHCenter)

        # Create a QSpinBox for selecting the channel
        self.channel_spinbox = QSpinBox()
        self.channel_spinbox.setRange(0, image_channels - 1)
        self.channel_spinbox.valueChanged.connect(self.callback_channel)
        channel_spinbox_group = QHBoxLayout()
        channel_spinbox_group.setAlignment(Qt.AlignLeft)
        channel_label = QLabel("Channel: ")

        # Adjusting the QSpinBox size
        self.channel_spinbox.setMinimumWidth(50)  # Set a minimum width
        self.channel_spinbox.setMaximumWidth(80)  # Limit width for compactness
        self.channel_spinbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)  # Prevent resizing

        # Adjusting the QSlider size
        self.channel_slider.setFixedHeight(20)  # Set a smaller height
        self.channel_slider.setMinimumWidth(150)  # Ensure it's not too small
        self.channel_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # Allow horizontal stretching


        # make label only take as much space as required...
        channel_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        channel_spinbox_group.addWidget(channel_label)
        channel_spinbox_group.addWidget(self.channel_spinbox)
        channel_selection_layout.addLayout(channel_spinbox_group, 0,0, 1, 2, alignment=Qt.AlignHCenter)

        option_widget_v_layout.addLayout(channel_selection_layout)

        hint_label = QLabel("Hint: You can double press the dock symbol to undock the composite_image and you "+
                            "can also dock it into the data section")
        hint_label.setWordWrap(True)
        hint_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.MinimumExpanding)
        hint_label.setMaximumWidth(100)
        right_col_v_layout.addWidget(hint_label)
        italic_font = QtGui.QFont()
        italic_font.setItalic(True)
        hint_label.setFont(italic_font)




        # Add stretchable spacers to control the spacing between widgets
        horizontal_spacer = QSpacerItem(0, 0, 1, 0)
        vertical_spacer = QSpacerItem(0, 0, 0, 1)

        channel_selection_layout.addItem(horizontal_spacer, 0, 1)

        # Create a QPushButton for choosing a colormap color
        self.color_button = QPushButton("Choose Channel Color")
        # self.color_button.setMaximumSize(*max_but_size)
        self.color_button.clicked.connect(lambda: self.choose_color())
        channel_selection_layout.addWidget(self.color_button, 0, 2, alignment=Qt.AlignHCenter)

        # add autoscale button for channel view
        autoscale_button = QPushButton("AutoScale")
        # autoscale_button.setMaximumSize(*max_but_size)
        autoscale_button.clicked.connect(self.channel_view.autoLevels)
        channel_selection_layout.addWidget(autoscale_button, 0, 3, alignment=Qt.AlignHCenter)

        # Create a ColorButton for choosing the colormap color
        self.color_widget = pg.ColorButton()
        self.color_widget.sigColorChanged.connect(self.callback_color_widget)
        channel_selection_layout.addWidget(self.color_widget, 1, 2, alignment=Qt.AlignHCenter)

        self.show_seeds_check = QCheckBox("Show Seeds")
        self.show_seeds_check.setCheckable(True)
        self.show_seeds_check.clicked.connect(lambda state: self.plot_seeds(self.spectral_cmps_seed) if state else self.plot_seeds(np.array([])))
        self.show_seeds_check.setMaximumWidth(100)
        main_img_layout.addWidget(self.show_seeds_check, 20, 19, 1, 1, alignment=Qt.AlignVCenter)

        # Add the h_layout to the main layout
        self.master_v_layout.addLayout(self.main_h_layout)

        # Initialize colormap, levels, and max value state dictionaries
        self.histogram_states = {}


        # Connect the slot function to histogram level sliders' valueChanged signals
        self.channel_view.getHistogramWidget().item.sigLevelsChanged.connect(self.update_channel_and_composite_levels)
        # Monitor manual LUT changes
        self.channel_view.getHistogramWidget().item.sigLookupTableChanged.connect(self.update_channel_and_composite_levels)
        # hide the gradient ticks
        self.channel_view.getHistogramWidget().gradient.showTicks(True)
        # self.lock_bottom_tick()

    def update_wavenumbers(self, wavenumbers):
        self.wavenumbers = wavenumbers
        self.fiji_saver.wavenumbers = wavenumbers
        self.plot_components(self.spectral_cmps)

        # TODO: update plot

    def update_label(self, component_number: int, new_label: str):
        # Store/update the label for the given component
        self.custom_labels[component_number] = new_label
        self.refresh_label_overlay(component_number)  # Optional: Re-render or update something
        self.fiji_saver.labels = self.custom_labels

    def plot_components(self, spectral_components: np.ndarray):
        """

        Args:
            spectral_components:
                PCs or Matrix H from PCA or NNMF analysis

        Returns:

        """
        #TODO: add labels with the custom label name from the user or at least the index of the component
        self.spectrum_view.clear()
        self.spectrum_lines = []
        self.seed_lines = []
        # Plot each component of H resp. the PCs
        try:
            num_components = spectral_components.shape[0]
        except AttributeError as e:
            logger.warning(e)
            return
        # self.spectrum_view.setTitle(rf"{'Custom' if self.custom_model else 'Random'} NNMF H Components")
        for i in range(num_components):
            component = spectral_components[i, :]
            name = self.custom_labels.get(i, f'Component {i}') if self.custom_model else f'Component {i}'
            line = self.spectrum_view.plot(self.wavenumbers, component, pen=pg.mkPen(self.get_color(i)), name=name)
            self.spectrum_lines.append(line)
        if self.custom_model:
            if self.show_seeds_check.isChecked():
                self.plot_seeds(self.spectral_cmps_seed, dashed=True)


    def refresh_label_overlay(self, index: int):
        """
            Update the label of a PlotDataItem in the spectrum view without replotting it.
            """
        if not self.spectrum_lines:
            return
        line = self.spectrum_lines[index]

        # Remove the old legend entry
        self.legend.removeItem(line)
        new_label = self.custom_labels.get(index, f'Component {index}')
        self.legend.addItem(line, new_label)

        if self.channel_slider.value() == index:
            # Update the title of the channel view
            self.channel_view.view.setTitle(f"Channel {index} {new_label}")


    def plot_seeds(self, seeds: np.ndarray, dashed: bool = True):
        # TODO: plot seeds in the spectrum view
        # add button to switch between seeds and components
        if self.seed_lines:
            # remove seed from the spectrum view
            for line in self.seed_lines:
                self.spectrum_view.removeItem(line)
            self.seed_lines = []

        if seeds is None:
            return
        for i in range(seeds.shape[0]):
            seed = seeds[i, :]
            line = self.spectrum_view.plot(self.wavenumbers, seed, pen=pg.mkPen(self.get_color(i), style=Qt.DashLine if dashed else Qt.SolidLine),
                                           name=f'Seed {i}')
            self.seed_lines.append(line)
        # raise NotImplementedError("Plotting seeds is not yet implemented,\nPlease do not pass seeds to the result viewer")

    def update_image(self, img_file: np.ndarray, spectral_axis: int | None = None,
                     spectral_cmps:np.ndarray|None = None,
                     spectral_cmps_seed: np.ndarray|None = None,
                     custom_model: bool = False,
                     update_gamma_curve=False):
        """
        Args:
            img_file: np.ndarray
                Img file with order (y, x, z).
                Position of z (spectral info) can be modified using the spectral_axis kwarg.
                Important: Spectral slices must be along the final axis -1 if not specified
            spectral_axis:
            spectral_cmps:
            spectral_cmps_seed:
        Returns:
            None
        """
        self.timeout_callbacks = True
        self.img = img_file
        if spectral_axis is not None:
            if spectral_axis != -1:
                self.img = np.moveaxis(self.img, spectral_axis, -1)
        self.composite_view.setImage(img_file)
        # adjust slider and scrollbar to max....
        channels = self.img.shape[-1] - 1
        self.channel_slider.setMaximum(channels)
        self.channel_spinbox.setMaximum(channels)

        if update_gamma_curve:
            self.update_color_positions()
        if channels:
            # Initialize the channel view with all channels and switch to selected afterwards
            for i in range(1, self.img.shape[-1]):
                # triggers channel update!
                self.update_channel_view(i)
            self.update_channel_view(0)
            self.reset_levels()
        else:
            # self.update_channel_view(0)
            self.channel_slider.setValue(0)

        self.spectral_cmps = spectral_cmps
        self.spectral_cmps_seed = spectral_cmps_seed
        self.custom_model = custom_model
        if spectral_cmps is not None:
            self.plot_components(spectral_cmps)
        self.timeout_callbacks = False
        # print('Updated Channel View')



        """ Threading function """
        # def update_image(self, img_file: np.ndarray, spectral_axis: int | None = None,
        #              spectral_cmps :np.ndarray = None):
        # """
        # Args:
        #     img_file: np.ndarray
        #         Img file with order (y, x, z).
        #         Position of z (spectral info) can be modified using the spectral_axis kwarg.
        #         Important: Spectral slices must be along the final axis -1 if not specified
        # Returns:
        #     None
        # """
        # self.worker = UpdateImageWorker(self, img_file, spectral_axis, spectral_cmps)
        # self.worker.moveToThread(self.update_thread)
        # # Connect pyqt signals
        # self.update_thread.started.connect(self.worker.run)
        # self.worker.finished.connect(self.update_thread.quit)
        # # Connect the finished function to the self.worker
        # self.worker.finished.connect(self.worker.deleteLater)
        #
        # # optional: delete thread after completion with self.thread_analysis.finished.connect(self.thread.deleteLater)
        #
        # logger.info(f'{datetime.now()}: Analysis thread set up')
        # self.update_thread.start()
        # # self.analyze_button.setEnabled(False)
        # logger.info(f'{datetime.now()}: Analysis started')

    def get_color(self, channel: int) -> tuple[int, int, int]:
        if self.color_manager is not None:
            return self.color_manager.get_color_rgb(channel)
        if channel in self.histogram_states:
            histogram_state = self.histogram_states[channel]
            colormap_color = histogram_state['gradient']['ticks'][1][1][:3]
        else:
            colormap_color = self.colormap_colors[channel % len(self.colormap_colors)]
        return colormap_color

    def update_channel_view(self, channel_index):
        if self.img is None:
            return 
        self.channel_slider.setValue(channel_index)
        logger.debug('Update Time %i' % channel_index)
        # Get the selected channel
        selected_im = self.img[:, :, channel_index]

        # Update the channel view
        self.channel_view.setImage(selected_im, autoLevels=False)

        # Apply saved levels and histogram state if available
        if channel_index in self.histogram_states:
            histogram_state = self.histogram_states[channel_index]
            self.channel_view.getHistogramWidget().restoreState(histogram_state)
            self.channel_view.ui.histogram.setHistogramRange(0, max_dtype_val)
            # self.channel_view.ui.histogram.setHistogramRange(np.amin(selected_im), np.amax(selected_im))
            # 4th value of the histogram_state['gradient']['ticks'][1][1] is opacity of the top color and should be omitted
            colormap_color = histogram_state['gradient']['ticks'][1][1][:3]
            logger.debug("Channel known")
        else:
            # If levels or histogram state is not available,
            # set default levels and histogram state
            # Choose a predefined colormap color for the first view of each channel from the
            # config file
            colormap_color = self.color_manager.get_color_rgb(channel_index) if self.color_manager is not None\
                else self.colormap_colors[channel_index % len(self.colormap_colors)]
            self.channel_view.autoLevels()
            # self.channel_view.setLevels(0, max_dtype_val)
            # self.channel_view.setLevels(np.amin(selected_im), np.amax(selected_im))
            self.channel_view.ui.histogram.setHistogramRange(0, max_dtype_val)
            self.make_color_state(channel_index, (0, max_dtype_val), colormap_color, colorpos='default')
            # self.update_levels()
            logger.debug("Channel unknown")
        # Update the QSpinBox with the current channel index
        self.channel_spinbox.setValue(channel_index)
        logger.debug(f'{channel_index =}, {colormap_color =}')
        # Set the color of the ColorButton to match the current colormap color
        self.color_widget.blockSignals(True)
        self.color_widget.setColor(pg.mkColor(colormap_color))
        self.color_widget.blockSignals(False)
        # Update the label to show current channel index
        self.channel_view.view.setTitle(f"Channel {channel_index} {self.custom_labels.get(channel_index, '')}")

    def callback_color_widget(self):
        # Get the selected color from the ColorButton
        selected_color = self.color_widget.color()
        self.color_widget.blockSignals(True)
        self.choose_color(selected_color)
        self.color_widget.blockSignals(False)

    def sync_colormap_current_channel_to_widget(self):
        # Get the selected color from the ColorButton
        selected_color = self.color_widget.color()

        # Convert QColor to pg.Color and set it as colormap color
        colormap_color = (selected_color.red(), selected_color.green(), selected_color.blue())
        # check if the colormap already exists in the histogram states and extract colormin and colormax positions
        pos_min, pos_max = 0, 1
        opacity_min, opacity_max = 255, 255
        if self.channel_slider.value() in self.histogram_states:
            pos_min = self.histogram_states[self.channel_slider.value()]['gradient']['ticks'][0][0]
            pos_max = self.histogram_states[self.channel_slider.value()]['gradient']['ticks'][1][0]
            opacity_min = self.histogram_states[self.channel_slider.value()]['gradient']['ticks'][0][1][3]
            opacity_max = self.histogram_states[self.channel_slider.value()]['gradient']['ticks'][1][1][3]

        colormap = pg.ColorMap(pos=[pos_min, pos_max], color=[(0, 0, 0) + (opacity_min,), colormap_color + (opacity_max,)])

        # update the colormap color for the current channel in the class variable
        self.colormap_colors[self.channel_slider.value()] = colormap_color
        # Update the colormap in the PlotWidget
        self.channel_view.setColorMap(colormap)

    def update_color_positions(self):
        # get the min and max values for all channels
        if self.img is None:
            return
        print('Updating color positions in result viewer to match FIJI linear gamma curve')
        for i in range(self.img.shape[-1]):
            histogram_state = self.histogram_states.get(i, None)
            if histogram_state is None:
                print(f'No histogram state for channel {i}. Skip update')
                continue
            selected_im = self.img[:, :, i]
            amin = np.amin(selected_im)
            amax = np.amax(selected_im)
            # set the colormin and colormax positions to the min and max values of the image
            colormin_pos = amin / max_dtype_val
            colormax_pos = amax / max_dtype_val
            # update the histogram state with the new colormap color

            old_opacity_min = histogram_state['gradient']['ticks'][0][1][3]
            old_opacity_max = histogram_state['gradient']['ticks'][1][1][3]

            histogram_state['gradient']['ticks'][0] = (colormin_pos, (0, 0, 0, old_opacity_min))
            histogram_state['gradient']['ticks'][1] = (colormax_pos, self.colormap_colors[i] + (old_opacity_max,))
            print(f'Updated color positions for channel {i} to {colormin_pos}, {colormax_pos}')

    def set_colormap(self, index: int, color: tuple[int, int, int], change_color_manager=True):
        # Set the colormap color for the specified index

        self.colormap_colors[index % len(self.colormap_colors)] = color


        logger.info(f"Composite Image: Setting colormap color for channel {index} to {color}")
        if self.color_manager:
            if change_color_manager:
                # emits a signal as well
                print('Changed set color in color manager')
                self.color_manager.set_color_rgb(index, color)

        if index == self.channel_slider.value():
            self.color_widget.setColor(pg.mkColor(color))

        if index in self.histogram_states:
            # Update the histogram state with the new colormap color
            histogram_state = self.histogram_states[index]
            histogram_state['gradient']['ticks'][1] = (histogram_state['gradient']['ticks'][1][0], (color + (255,)))
            logger.info(f'Updated colormap color for channel {index}')

        # update the composite image with the new colormap color
        self.update_plot_line_color(index, QColor(*color))
        self.sync_colormap_current_channel_to_widget()

        # self.update_channel_and_composite_levels()
        # update is automatically triggered by gradient change

    def save_data(self):
        # Open a file dialog to select where to save the TIFF file
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Composite Image",
            "",
            "TIFF Files (*.tif *.tiff);;All Files (*)",
            options=options
        )

        if not file_path:  # User canceled the dialog
            return

            # Ensure the file has the correct extension
        if not file_path.lower().endswith((".tif", ".tiff")):
            file_path += ".tif"

        # save the composite image as tiff file with the current color maps
        # self.fiji_saver.fpath = file_path
        image_3d = np.moveaxis(self.img, -1, 0)
        self.fiji_saver.update_image(image_3d)
        self.fiji_saver.path = file_path
        # luts are referenced via the class variable colormap_colors
        # print(f'colormap colors {self.colormap_colors}, {self.fiji_saver.colormaps}')

        scale_factor_8bit_nbit = 255 / max_dtype_val
        # pass the ranges from the histogram states to the fiji saver in the format list((min1, max1), (min2, max2), ...)
        ranges_nbit = [self.histogram_states[i]['levels'] for i in range(image_3d.shape[0])]
        # ranges_8bit = [(int(min_ * scale_factor_8bit_nbit), int(max_ * scale_factor_8bit_nbit)) for min_, max_ in ranges_nbit]
        self.fiji_saver.ranges = ranges_nbit
        self.fiji_saver.colormaps = self.color_manager.get_all_colors_rgb() if self.color_manager is not None else self.colormap_colors
        self.fiji_saver.save_composite_image()
    
    def save_preset(self, mode='seeds'):
        """ 
        Saves the current colormaps, vmin, vmax positions, and the H & W seeds to a file
        
        Mode can be 'seeds' or 'results' to save the H or W seeds respectively from the init or the resulting NNMF analysis
        """
        # Open a file dialog to select where to save the TIFF file
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Preset",
            "",
            "Preset Files (*.preset);;All Files (*)",
            options=options
        )

        # Save the H seeds
        if mode.lower() == 'seeds':
            seeds_H = self.spectral_cmps_seed
        elif mode.lower() == 'results':
            seeds_H = self.spectral_cmps
        else:
            raise ValueError("Invalid mode. Mode must be 'seeds' or 'results'")

        # Ensure the file has the correct extension 
        if not file_path:
            return

        self.save_to_presets(file_path, seeds_H, self.wavenumbers, self.color_manager.get_all_colors_rgb(), self.histogram_states)

    def save_components(self):
        # Open a file dialog to select where to save the CSV file
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save H Components as CSV",
            "",
            "CSV Files (*.csv);;All Files (*)",
            options=options
        )

        if not file_path:  # User canceled the dialog
            return

        wavenumbers = self.wavenumbers[...]

        # save to text with header "wavenumbers, cmp1, cmp2, ..."
        header = "Wavenumber (1/cm)," + ",".join([f"Component {i}" for i in range(self.spectral_cmps.shape[0])])
        data_to_save = np.vstack((wavenumbers, self.spectral_cmps)).T
        np.savetxt(file_path, data_to_save, delimiter=",", header=header, comments='')
        logger.info(f"Saved H components to {file_path}")

    @staticmethod
    def save_to_presets(fpath: str, seeds: np.array, wavenumbers: np.array,
                        colormap_colors: list[tuple[int, int, int]], histogram_states: dict):
        if not fpath.lower().endswith(".preset"):
            fpath += ".preset"

        with open(fpath, "w") as f:
            # Save the colormap colors
            f.write(f"colormap_colors = {colormap_colors}\n")
            # Save the vmin and vmax positions
            f.write("vmin_vmax = [")
            for i in range(len(histogram_states)):
                f.write(f"({histogram_states[i]['levels'][0]}, {histogram_states[i]['levels'][1]}), ")
            f.write("]\n")
            # write the slider top and bottom colors
            f.write("slider_colors = [")
            for i in range(len(histogram_states)):
                f.write(f"({histogram_states[i]['gradient']['ticks'][0][1]}, {histogram_states[i]['gradient']['ticks'][1][1]}), ")
            f.write("]\n")
            f.write(f"wave_numbers = {wavenumbers.tolist()}\n")
            # Save the H seeds
            f.write(f"seeds = {seeds.tolist()}")
        logger.info(f"Saved preset to {fpath}")


    @staticmethod
    def load_from_presets(fpath: str) -> tuple[
        list[tuple[int, int, int]], list[tuple[int, int]], np.ndarray, np.ndarray]:
        save_keys = {
            'vmin_vmax': 'vmin_vmax',
            'colormap_colors': 'colormap_colors',
            'wave_numbers': 'wavenumbers',
            'seeds': 'seeds'
        }

        # Store loaded variables temporarily
        locals_ = {
            'vmin_vmax': None,
            'colormap_colors': None,
            'wavenumbers': None,
            'seeds': None
        }

        with open(fpath, "r") as f:
            lines = f.readlines()
            for key, varname in save_keys.items():
                for line in lines:
                    if key in line:
                        # Evaluate the value and assign to locals_ dictionary
                        value = eval(line.split('=', 1)[1].strip())
                        locals_[varname] = value
                        break  # Stop after the first match for each key

        # Convert wavenumbers and seeds to numpy arrays if needed
        locals_['wavenumbers'] = np.array(locals_['wavenumbers'])
        locals_['seeds'] = np.array(locals_['seeds'])

        return (
            locals_['colormap_colors'],
            locals_['vmin_vmax'],
            locals_['wavenumbers'],
            locals_['seeds']
        )

    def update_plot_line_color(self, index: int, color: QColor):
        # update the color of the plot in the spectrum view
        if self.spectrum_lines:
            self.spectrum_lines[index].setPen(pg.mkPen(color))
        if self.seed_lines:
            self.seed_lines[index].setPen(pg.mkPen(color))

    def reload_color_current_channel(self):
        cur_channel = self.channel_slider.value()
        # comes from the color manager, so no need to change it there
        self.set_colormap(cur_channel, self.get_color(cur_channel), change_color_manager=False)

    def reload_color(self, channel_index: int):
        self.set_colormap(channel_index, self.get_color(channel_index), change_color_manager=False)
        cur_channel = self.channel_slider.value()
        if cur_channel != channel_index:
            self.update_channel_view(channel_index)
            self.update_channel_view(cur_channel)

    def make_color_state(self, index: int, vmin_max: tuple, color: tuple[int, int, int], colorpos='default'):
        vmin, vmax = vmin_max
        # get the current minimum and maximum values of the channel at the index
        colormin_pos, colormax_pos = 0, 1
        if not colorpos=='default':
            if colorpos == 'auto':
                # get the current minimum and maximum values of the channel at the index
                if self.img is None:
                    return
                selected_im = self.img[:, :, index]
                amin = np.amin(selected_im)
                amax = np.amax(selected_im)
                # set the colormin and colormax positions to the min and max values of the image
                colormin_pos = amin / max_dtype_val
                colormax_pos = amax / max_dtype_val
                print(f'Calculated color positions for channel {index} to {colormin_pos}, {colormax_pos}')

        self.histogram_states[index] = {
            'gradient': {
                'mode': 'rgb',
                'ticks': [
                    (colormin_pos, (0, 0, 0, 255)),
                    (colormax_pos, color + (255,))
                ],
                'ticksVisible': False
            },
            'levels': (vmin, vmax),
            'mode': 'mono'
        }
        logger.info(f'Created histogram state for channel {index} with info {self.histogram_states[index]}')

        # set the current histogram state in the channel view
        if index == self.channel_slider.value():
            self.channel_view.getHistogramWidget().restoreState(self.histogram_states[index])

    def set_spectral_units(self, units: str):
        if units.lower() == 'nm':
            self.spectrum_view.setLabel('bottom', 'Wavelength (nm)')
        else:
            self.spectrum_view.setLabel('bottom', 'Wavenumber (1/cm)')

    def choose_color(self, color: QColor | None = None):
        # Open a QColorDialog to choose a color for colormap
        if color is None:
            color = QColorDialog.getColor()

        if color.isValid():
            # Convert QColor to QColor object and
            qcolor = pg.mkColor(color.name())
            self.set_colormap(self.channel_slider.value(), (qcolor.red(), qcolor.green(), qcolor.blue()))

        self.sync_colormap_current_channel_to_widget()

    # new implementation of the get_rgba method where the colormap is applied to the image similar to FIJI
    # with 8 bit colormaps
    def get_rgba(self) -> np.ndarray | None:
        # print('Updating composite image')
        """
        Generate a composite RGB image from individual grayscale channels, mimicking FIJI's composite LUT behavior.

        Each channel is:
          - Linearly normalized using histogram levels (vmin, vmax)
          - Mapped to a LUT color (e.g., red, green, blue, etc.)
          - Scaled as if LUTs are 8-bit, then upscaled to 16-bit

        Returns:
            np.ndarray: RGB image in uint16 format with shape (height, width, 3)
        """
        if self.img is None:
            return

        # Create a float32 RGB image for accumulation
        rgb_image = np.zeros((*self.img.shape[:2], 3), dtype=np.float32)
        channels = self.img.shape[-1]

        for i in range(channels):
            if i not in self.histogram_states:
                continue

            histogram_state = self.histogram_states[i]

            vmin, vmax = histogram_state['levels']
            ticks = histogram_state['gradient']['ticks']

            # Sort ticks to be sure
            ticks = sorted(ticks, key=lambda t: t[0])  # t[0] = position in [0, 1]

            # Assume two ticks only: (pos0, color0), (pos1, color1)
            pos0, color0 = ticks[0]
            pos1, color1 = ticks[1]

            # Normalize image data
            channel_data = self.img[..., i].astype(np.float32)
            norm = np.clip((channel_data - vmin) / (vmax - vmin), 0, 1)

            # Interpolate mask in gradient range
            grad_range = np.clip((norm - pos0) / (pos1 - pos0), 0, 1)

            # LUT color (only top color is applied)
            lut_color = np.array(color1[:3], dtype=np.float32) / 255.0

            for c in range(3):
                rgb_image[..., c] += grad_range * lut_color[c]

        # Clip the final RGB image to [0, 1] and scale to 16-bit
        rgb_image = np.clip(rgb_image, 0, 1)
        rgb_uint16 = (rgb_image * 65535).astype(np.uint16)
        return rgb_uint16

    def update_channel_and_composite_levels(self):
        """
        Update the composite image and channel view levels based on the current channel's histogram state.
        Returns:

        """
        # Get the current channel index
        if self.img is None:
            return
        channel_index = self.channel_slider.value()
        # Save the histogram state
        histogram_state = self.channel_view.getHistogramWidget().saveState()
        self.histogram_states[channel_index] = histogram_state
        false_color_im = self.get_rgba()
        self.composite_view.setImage(false_color_im, autoLevels=False)
        self._sync_color_button_to_gradient()
        # Restore the previous view settings
        """
        # Get the current view settings
        view_range = self.composite_view.getView().viewRange()
        view_center = self.composite_view.getView().viewPixelSize()
        self.composite_view.getView().setRange(xRange=view_range[0], yRange=view_range[1])
        # Optionally, you can center the view on the image
        image_width = self.img.shape[1]
        image_height = self.img.shape[0]
        view_width = view_range[0][1] - view_range[0][0]
        view_height = view_range[1][1] - view_range[1][0]
        x_offset = (image_width - view_width) / 2
        y_offset = (image_height - view_height) / 2
        print(x_offset, y_offset)
        self.composite_view.getView().setXRange(view_range[0][0] + x_offset, view_range[0][1] + x_offset)
        self.composite_view.getView().setYRange(view_range[1][0] + y_offset, view_range[1][1] + y_offset)
        """

        self.composite_view.ui.histogram.setHistogramRange(0, max_dtype_val)
        if auto_min_max:
            min_, max_ = self.min_max_levels()
            self.composite_view.ui.histogram.setLevels(min_, max_)
        # self.composite_view.autoLevels()

    def min_max_levels(self):
        # Initialize variables for min_levels and max_levels
        min_levels = float(0)
        max_levels = float(max_dtype_val)

        # Iterate through the histogram_state dictionary
        levels = [state['levels'] for key, state in self.histogram_states.items()]
        min_levels = min(level[0] for level in levels)
        max_levels = min(level[1] for level in levels)

        return min_levels, max_levels

    def callback_channel(self, *args):
        if not self.timeout_callbacks:
            self.update_channel_view(*args)

    def reset_levels(self):
        # Reset the levels of the composite image to the default range (0 - 65535)
        self.composite_view.ui.histogram.setLevels(0, max_dtype_val)

    def _sync_color_button_to_gradient(self):
        """Sync the ColorButton with the top color in the histogram gradient."""
        if self.timeout_callbacks:
            return
        gradient = self.channel_view.getHistogramWidget().gradient

        # Safely extract the tick colors
        top_color = None
        top_pos = -1

        for tick_obj, pos in gradient.listTicks():
            if pos > top_pos:
                top_pos = pos
                top_color = tick_obj.color.getRgb()[:3]  # (r, g, b)
        if top_color is None:
            return

            # Compare with current color in color_button
        current_color = self.color_widget.color().getRgb()[:3]

        if current_color == top_color:
            return  # No change needed

        # Only update if different → avoid triggering .sigColorChanged
        self.color_widget.blockSignals(True)
        self.color_widget.setColor(pg.mkColor(top_color))
        self.color_widget.blockSignals(False)

        # update plot
        self.update_plot_line_color(self.channel_slider.value(), pg.mkColor(top_color))

    def lock_bottom_tick(self):
        gradient = self.channel_view.getHistogramWidget().gradient
        locked_pos = 0.0
        locked_color = (0, 0, 0, 255)

        def enforce_lock():
            chan = self.channel_slider.value()
            if chan not in self.histogram_states:
                return

            # Get bottom tick (first tick)
            tick, pos = gradient.listTicks()[0]
            current_color = tick.color.getRgb()

            # Check if tick was modified
            if not np.isclose(pos, locked_pos) or current_color != locked_color:
                print("Bottom tick modified. Enforcing manual lock.")
                gradient.blockSignals(True)
                tick.setPos(QPointF(locked_pos, 0))  # y=0 is ignored
                current_ticks = gradient.listTicks()
                self.channel_view.getHistogramWidget().restoreState(self.histogram_states[chan])
                # remove all ticks that are not in the current ticks
                for tick, pos in gradient.listTicks():
                    if tick not in current_ticks:
                        gradient.scene().removeItem(tick)

                # tick.setColor(pg.mkColor(locked_color))
                gradient.blockSignals(False)

        # Connect once
        gradient.sigGradientChanged.connect(enforce_lock)
        enforce_lock()


class UpdateImageWorker(QObject):
    # TODO: setting images is still complicated in new threads because the widget still lives in another thread
    finished = pyqtSignal()

    def __init__(self, result_viewer_widget, img, spectral_axis, spectral_cmps):
        super().__init__()
        self.result_viewer_widget = result_viewer_widget
        self.img_file = img
        self.spectral_axis = spectral_axis
        self.spectral_cmps = spectral_cmps

    def run(self):
        # Call the update_image method of the result viewer widget
        self.result_viewer_widget.timeout_callbacks = True
        self.result_viewer_widget.img = self.img_file
        if self.spectral_axis is not None:
            if self.spectral_axis != -1:
                self.result_viewer_widget.img = np.moveaxis(self.result_viewer_widget.img, self.spectral_axis, -1)
        self.result_viewer_widget.composite_view.setImage(self.img_file)
        # adjust slider and scrollbar to max....
        channels = self.result_viewer_widget.img.shape[-1] - 1
        self.result_viewer_widget.channel_slider.setMaximum(channels)
        self.result_viewer_widget.channel_spinbox.setMaximum(channels)
        if channels:
            ch_selected = self.result_viewer_widget.channel_slider.value()
            # Initialize the channel view with all channels and switch to selected afterwards
            for i in range(self.result_viewer_widget.img.shape[-1]):
                # triggers channel update!
                self.result_viewer_widget.update_channel_view(i)
            self.result_viewer_widget.update_channel_view(0)
            self.result_viewer_widget.reset_levels()
        else:
            # self.result_viewer_widget.update_channel_view(0)
            self.result_viewer_widget.channel_slider.setValue(0)

        self.result_viewer_widget.spectral_cmps = self.spectral_cmps
        if self.spectral_cmps is not None:
            self.result_viewer_widget.plot_components(self.spectral_cmps)
        self.result_viewer_widget.timeout_callbacks = False


if __name__ == '__main__':
    app = QApplication([])
    composite_image = CompositeImageViewWidget()
    # load some example data
    try:
        result = tifffile.imread(r"./example_data/h_e_result.tif")
    except FileNotFoundError as e:
        result = np.ones((3, 100, 100), dtype=np.uint16)
    result = np.moveaxis(result, 0, -1)
    composite_image.make_color_state(0, (0, 20000), (255, 255, 255), colormin_pos=.4, colormax_pos=.5)
    composite_image.update_image(result)

    composite_image.make_color_state(0, (0, 20000), (255, 255, 255), colormin_pos=.4, colormax_pos=.5)
    # modify the colormaps
    # ...

    fov_x = 500
    bar = ScaleBar(composite_image.channel_view.view.getViewBox(), fov_x / composite_image.channel_view.image.shape[0], 500)

    bar.update_scale_bar_len(250)

    composite_image.show()
    app.exec_()
