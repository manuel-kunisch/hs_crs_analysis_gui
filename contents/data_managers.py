import json
import logging
import os

import numpy as np
from PyQt5 import QtWidgets, QtCore
from tifffile import imread

from contents import stitch_functions as stitching
from contents.physical_units_manager import PhysicalUnitsManager

logger = logging.getLogger('Data Manager')


class ImageLoader(QtWidgets.QWidget):
    def __init__(self, update_img_callback: callable, parent: QtWidgets.QWidget):
        """
        Widget for loading images and performing basic operations on them
        Args:
            update_img_callback: the callback function that is executed when the image is loaded
            parent:
        """
        super().__init__(parent)
        self.wavelength_meta = None
        self.update_img_callback = update_img_callback
        self._image = None
        self.init_ui()


    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Create a QTabWidget to manage tabs
        tab_widget = QtWidgets.QTabWidget(self)

        # Create the main tab
        main_tab = QtWidgets.QWidget()
        self.main_grid_layout = QtWidgets.QGridLayout(main_tab)
        data_h_layout = QtWidgets.QHBoxLayout()

        # Create drag & drop label
        self.drag_label = QtWidgets.QLabel("📂 Drag & Drop TIFF Files Here")
        #self.drag_label.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignHCenter)
        self.drag_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        # self.drag_label.setFixedHeight(60)
        # self.drag_label.setMaximumWidth(700)
        # add linebreaks to the label if the text is too long
        self.drag_label.setWordWrap(True)
        # Set style for the drag label
        self.drag_label.setStyleSheet("""
                    QLabel {
                        border: 2px thick #aaa;
                        background-color: darkgray;
                        color: #555;
                        font-size: 8pt;
                        padding: 3px;
                    }
                    QLabel:hover {
                        background-color: #e8e8e8;
                    }
                """)

        # Enable drag & drop
        self.drag_label.setAcceptDrops(True)
        # Connect drag & drop events
        self.drag_label.dragEnterEvent = self.drag_enter_event
        self.drag_label.dropEvent = self.drop_event

        # add ability to click the label which opens a file dialog
        self.drag_label.mousePressEvent = self.load_image_from_file_dialog

        # data_h_layout.addWidget(QtWidgets.QLabel("Data Path"), alignment=QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        data_h_layout.addWidget(self.drag_label, alignment=QtCore.Qt.AlignLeft | QtCore.Qt.AlignRight)

        path_widget = QtWidgets.QWidget()
        path_widget.setLayout(data_h_layout)
        self.main_grid_layout.addWidget(path_widget, 0, 2)

        # add preset save buttons as dummies
        self.save_preset_button = QtWidgets.QPushButton('Save Preset')
        self.load_preset_button = QtWidgets.QPushButton('Load Preset')
        # add the preset buttons to the loader widget ui
        self.main_grid_layout.addWidget(self.save_preset_button, 0, 0)
        self.main_grid_layout.addWidget(self.load_preset_button, 0, 1)


        # tab_widget.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        # Add tab to widget
        tab_widget.addTab(main_tab, "Single HS Image")

        # Add the tab widget to the main layout
        layout.addWidget(tab_widget)

        # Create the stitching tab
        stitching_tab = QtWidgets.QWidget()
        stitching_layout = QtWidgets.QVBoxLayout(stitching_tab)

        # Add the stitching tab to the tab widget
        tab_widget.addTab(stitching_tab, "HS Image Stitching")


        # Initialize and add the StitchManager widget to the stitching tab
        self.stitch_manager = StitchManager()
        self.stitch_manager.init_ui()
        stitching_layout.addWidget(self.stitch_manager.stitch_data_widget)
        self.stitch_manager.stitchedImageChanged.connect(self.load_image)

        # Add rolling ball correction tab
        rb_tab = QtWidgets.QWidget()
        tab_widget.addTab(rb_tab, "Rolling Ball Correction")

        # Add physical units tab
        self.physical_units_manager = PhysicalUnitsManager()
        physical_units_tab = self.physical_units_manager.widget
        self.physical_units_manager.widget.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        tab_widget.addTab(physical_units_tab, "Physical Units")



    def load_image_from_text(self):
        # Get the text from the text edit widget
        file_path = self.text_edit.toPlainText().strip()

        # Check if the entered text is a valid TIFF file path
        if file_path.lower().endswith('.tif') or file_path.lower().endswith('.tiff'):
            # Load the image using the loader class
            image_data = self.load_tiff(file_path)

            # If stitching is enabled, perform stitching
            # if self.stitch_check.isChecked():
            #     image_data = self.stitch_images(image_data)

    def load_image_from_file_dialog(self, *args):
        # Open a file dialog to select a TIFF file
        file_dialog = QtWidgets.QFileDialog()
        file_path, _ = file_dialog.getOpenFileName(self, "Open TIFF File", "", "TIFF Files (*.tif *.tiff)")

        # Check if a file was selected
        if file_path:
            # Load the image using the loader class
            image_data = self.load_tiff(file_path)

    def drag_enter_event(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def drop_event(self, event):
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            file_path = mime_data.urls()[0].toLocalFile()
            if file_path.lower().endswith(('.tif', '.tiff')):
                self.load_tiff(file_path)
            else:
                self.drag_label.setText("❌ Invalid File Type")


    def load_tiff(self, fpath):
        # check if a wavelength json file is in the directory
        self.try_load_wavelength_json(os.path.dirname(fpath))
        self.image = imread(fpath).astype(np.uint16)
        self.drag_label.setText(f"✔ Loaded: {fpath.split('/')[-1]}")
        logger.info(f"Loaded image from {fpath}")
        # check if the tiff contains zeros
        if np.any(self.image == 0):
            logger.warning('Image contains zeros')
            self.image[self.image == 0] = 1
            logger.warning('Zeros replaced with 1')
        return self.image

    def try_load_wavelength_json(self, directory: str):
        self.wavelength_meta = None
        meta_path = os.path.join(directory, "wavelength.json")

        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as fh:
                    meta = json.load(fh)

                # basic validation + normalization
                tuned_beam = meta.get("tuned_beam", "").lower()
                if tuned_beam not in {"stokes", "pump"}:
                    raise ValueError("tuned_beam must be 'stokes' or 'pump'")

                fixed_beam_nm = float(meta["fixed_beam_nm"])  # required

                tuned_min_nm = meta.get("tuned_min_nm")
                tuned_max_nm = meta.get("tuned_max_nm")
                tuned_step_nm = meta.get("tuned_step_nm")

                if tuned_min_nm is None and tuned_max_nm is None and tuned_step_nm is None:
                    raise ValueError(
                        "Need at least tuned_min_nm + tuned_max_nm OR tuned_step_nm"
                    )

                self.wavelength_meta = {
                    "tuned_beam": tuned_beam,
                    "fixed_beam_nm": fixed_beam_nm,
                    "tuned_min_nm": float(tuned_min_nm) if tuned_min_nm is not None else None,
                    "tuned_max_nm": float(tuned_max_nm) if tuned_max_nm is not None else None,
                    "tuned_step_nm": float(tuned_step_nm) if tuned_step_nm is not None else None,
                }

                logger.info(f"Loaded wavelength metadata from {meta_path}")
                print(self.wavelength_meta)
            except Exception:
                logger.exception(f"Failed to read wavelength metadata from {meta_path}")
        else:
            logger.info(f"No wavelength.json found in {directory}")


    def load_image(self, image_data):
        self.image = image_data
        return image_data

    @property
    def image(self):
        return self._image

    @image.setter
    def image(self, new_image):
        self._image = new_image
        if self.update_img_callback:
            self.update_img_callback(new_image)


class StitchManager(QtCore.QObject):
    stitchedImageChanged = QtCore.pyqtSignal(np.ndarray)
    def __init__(self, init_widgets = True):
        super().__init__()
        self.stitch_data = dict()
        self.stitch_data_widget = None
        self.stitch_base = None
        # if init_widgets:
        #     self.init_ui()

    def init_ui(self):
        # Create the main widget
        self.stitch_data_widget = QtWidgets.QWidget()
        main_layout = QtWidgets.QHBoxLayout(self.stitch_data_widget)
        layout = QtWidgets.QVBoxLayout(self.stitch_data_widget)

        # Create a table to show files
        self.files_table = QtWidgets.QTableWidget()
        self.files_table.setColumnCount(1)  # Assuming one column for file paths
        self.files_table.setHorizontalHeaderLabels(["Files"])
        self.files_table.setAcceptDrops(True)
        self.files_table.dropEvent = self.drop_event

        # Create a vertical layout for the settings
        settings_layout = QtWidgets.QHBoxLayout()

        self.pos_indicator_textbox = QtWidgets.QLineEdit("pos")
        self.delimiter_indicator_textbox = QtWidgets.QLineEdit("_")
        # Create spin boxes for row and column overlap
        self._row_overlap_spinbox = QtWidgets.QSpinBox()
        self._column_overlap_spinbox = QtWidgets.QSpinBox()
        self._row_overlap_spinbox.setRange(0, 200)
        self._column_overlap_spinbox.setRange(0, 200)
        self._row_overlap_spinbox.setValue(90)  # Default values
        self._column_overlap_spinbox.setValue(90)

        # Create spin box for max weight
        self._max_weight_spinbox = QtWidgets.QSpinBox()
        self._max_weight_spinbox.setRange(0, 1)
        self._max_weight_spinbox.setValue(1)  # Default value

        # Create a dictionary to map labels to corresponding widgets
        settings_widgets = {
            "Pos Indicator": self.pos_indicator_textbox,
            "Delimiter Indicator": self.delimiter_indicator_textbox,
            "Row Overlap": self._row_overlap_spinbox,
            "Column Overlap": self._column_overlap_spinbox,
            "Max Weight": self._max_weight_spinbox,
            # "Correlation Settings": correlation_frame,
        }

        # Add widgets to the settings layout
        for i, (label, widget) in enumerate(settings_widgets.items()):
            label_widget = QtWidgets.QLabel(label)
            label_widget.setAlignment(QtCore.Qt.AlignCenter)

            # Create a grid layout for each setting
            setting_grid_layout = QtWidgets.QGridLayout()
            setting_grid_layout.addWidget(label_widget, 0, i, 1, 2)  # Label in row 0, spanning 1 row, 2 columns
            setting_grid_layout.addWidget(widget, 1, i, 1, 2)  # Widget in row 1, spanning 1 row, 2 columns

            settings_layout.addLayout(setting_grid_layout)

        # Create a LabelFrame for Correlation
        correlation_frame = QtWidgets.QFrame()
        correlation_layout = QtWidgets.QVBoxLayout(correlation_frame)
        correlation_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        correlation_frame.setLineWidth(1)

        # Checkbox for Correlation
        self._correlation_checkbox = QtWidgets.QCheckBox("Correlate?")
        correlation_layout.addWidget(self._correlation_checkbox)

        # QLineEdit for Channels
        self._channels_entry = QtWidgets.QLineEdit()
        correlation_layout.addWidget(QtWidgets.QLabel("Channels"))
        correlation_layout.addWidget(self._channels_entry)

        # Spinbox for Sigma Interval
        self._sigma_interval_spinbox = QtWidgets.QDoubleSpinBox()
        self._sigma_interval_spinbox.setRange(0.1, 10.0)
        self._sigma_interval_spinbox.setSingleStep(0.1)
        self._sigma_interval_spinbox.setValue(1.0)  # Default value
        correlation_layout.addWidget(QtWidgets.QLabel("Sigma Interval"))
        correlation_layout.addWidget(self._sigma_interval_spinbox)

        # Checkboxes for Mean and Average
        modes_layout = QtWidgets.QHBoxLayout()
        self._mean_checkbox = QtWidgets.QCheckBox("Mean")
        self._average_checkbox = QtWidgets.QCheckBox("Average")
        modes_layout.addWidget(self._mean_checkbox)
        modes_layout.addWidget(self._average_checkbox)
        correlation_layout.addWidget(QtWidgets.QLabel("Modes"))
        correlation_layout.addLayout(modes_layout)

        # Add the widgets to the main layout
        layout.addWidget(QtWidgets.QLabel("Files for Stitching"))
        self.drop_wid = QtWidgets.QTextEdit()
        self.drop_wid.setPlaceholderText("Drag and drop TIFF files here...")
        layout.addWidget(self.drop_wid)
        self.drop_wid.setAcceptDrops(True)
        self.drop_wid.dropEvent = self.drop_event
        layout.addWidget(self.files_table)
        layout.addLayout(settings_layout)
        main_layout.addLayout(layout)
        # layout.addWidget(QtWidgets.QLabel("Correlation"))
        main_layout.addWidget(correlation_frame)

    def drop_event(self, event):
        # Handle drop events
        mime_data = event.mimeData()

        # Check if the dropped data contains URLs
        if mime_data.hasUrls():
            logger.debug('Start drop event debug:')
            logger.debug('Has URL')
            file_path = mime_data.urls()[0].toLocalFile()
            folder_path = os.path.dirname(file_path)
            x, y, num, base = stitching.stitch_pos_finder(file_path, pos_key=self.pos_indicator,
                                                          delimiter=self.delimiter_indicator)
            base_filename = str(os.path.basename(base))
            self.stitch_base = base_filename.split(self.pos_indicator)[0]
            self.drop_wid.setText(self.stitch_base)
            logger.debug('Splitted', self.stitch_base)
            # Create entry in dict
            self.stitch_data[self.stitch_base] = {'pos': {}}
            logger.debug('-'*100)
            logger.debug(x,y, num, base)
            logger.debug('-'*100)
            logger.debug(base_filename)
            self.stitch_load(folder_path, base_filename)
            self.stitch()
        else:
            logger.debug('NO URL')
            logger.debug('\n\n')


    def get_tiff_files(self, directory):
        """
        Returns file names of tiff files with their extension
        """
        tiff_files = [os.path.basename(f) for f in os.listdir(directory) if f.lower().endswith('.tif')]
        return tiff_files

    def update_table(self):
        # Clear existing table
        self.files_table.clear()
        lookup_x = self.stitch_data[self.stitch_base]['lookup']['x']
        lookup_y = self.stitch_data[self.stitch_base]['lookup']['y']
        # Set row and column count based on lookup values
        self.files_table.setRowCount(len(lookup_y))
        self.files_table.setColumnCount(len(lookup_x))

        for j, ypos in enumerate(lookup_y):
            for i, xpos in enumerate(lookup_x):
                try:
                    item = QtWidgets.QTableWidgetItem(str(self.stitch_data[self.stitch_base]['pos'][xpos][ypos]['number']))
                except KeyError:
                    QtWidgets.QMessageBox.warning(self, '', 'Error: your data is lacking images.')
                    return
                self.files_table.setItem(j, i, item)


    def stitch_load(self, folder_path, base_fname: str):
        new_dnames = []
        x_pos = []  # for lookup tables
        y_pos = []
        dnames = self.get_tiff_files(folder_path)
        remaining = []
        # Split filename at pos indicator
        base_name = base_fname.split(self.pos_indicator)[0]
        logger.debug('Splitted', base_name)
        for i, dname in enumerate(dnames):
            root, ext = os.path.splitext(dname)
            if root.startswith(base_name):
                x, y, num, fname = stitching.stitch_pos_finder(dname)
                if fname is None:  # if pos is not in the name, i.e. file does not belong to stitch data
                    remaining.append(fname)
                    continue  # jumps to the start of the loop


                signal = imread(os.path.join(folder_path, dname), is_ome=False)
                # TODO add Intensity correction functionality later s
                # updated_signal = self.check_intensity_correction(signal)
                updated_signal = signal

                if x in self.stitch_data[base_name]['pos']:
                    self.stitch_data[base_name]['pos'][x].update({y: {'img': updated_signal, 'number': num, 'raw_img': signal}})
                    x_pos.append(x)
                    y_pos.append(y)
                else:
                    self.stitch_data[base_name]['pos'].update({x: {y: {'img': updated_signal, 'number': num, 'raw_img': signal}}})
                    y_pos.append(y)
            else:
                logger.debug('Not in basenames')
                dtype = '.tif'
                new_dnames.append(str(root) + dtype)

        # self.dnames.set(new_dnames + remaining)
        lookup_x = sorted(set(x_pos))
        lookup_y = sorted(set(y_pos))
        logger.debug(lookup_x, lookup_y)
        logger.debug(self.stitch_data)
        # logger.info(lookup_x, lookup_y)
        self.stitch_data[base_name].update({'lookup': {'x': lookup_x, 'y': lookup_y}})

        # Create or update the table with stitched image numbers
        self.update_table()

        y_images = []

        # check if each dimension is the same
        logger.debug(self.stitch_data[base_name].keys())
        for key in self.stitch_data[base_name]['pos']:  # sorting and counting (cols and rows could probably be unordered)
            y_images.append(len(self.stitch_data[base_name]['pos'][key]))

    def stitch(self):
        overlap_row = self.row_overlap
        overlap_col = self.column_overlap
        base = self.stitch_base
        lookup_y = self.stitch_data[base]['lookup']['y']
        lookup_x = self.stitch_data[base]['lookup']['x']

        logger.info('Start stitching images with row overlap: %.0f column overlap: %.0f pixels.' % (overlap_row, overlap_col))
        weight_list_x = stitching.lin_weights(overlap_row, self.max_weight)
        weight_list_y = stitching.lin_weights(overlap_col, self.max_weight)

        x_stitch_list = []
        for j in range(0, len(lookup_x)):
            # colum stitching for each y
            ystart = lookup_y[0]
            logger.debug('y: ', ystart)
            xpos = lookup_x[j]
            logger.debug('xpos: ', xpos)
            stitch_data = self.stitch_data[base]['pos'][xpos][ystart]
            stitch = stitch_data['img'] # top image of stitching: start point of each row

            logger.debug('start image for row stitching: ', stitch_data['number'])
            # now: y fixed, start building elongated columns
            for ii, ypos in enumerate(lookup_y[1:]):      # iterate over each row (xpos)
                data_bottom = self.stitch_data[base]['pos'][xpos][ypos]
                bottom = data_bottom['img']              # list of bottom images
                image_top_ = stitch[:, :-overlap_row, :]         # cut off the overlap data
                image_bottom_ = bottom[:, overlap_row:,:]       # cut off

                logger.debug('attaching: ', data_bottom['number'])
                image_shape = image_top_.shape
                stitch_center = np.empty((image_shape[0], overlap_row , image_shape[-1])) #save averaged data

                for i in range(0, overlap_row):   # start at the top, place the bottom image on top of it
                    image_top = stitch[:, -overlap_row+i, :]
                    image_bottom = bottom[:, i,:]      # stitching overlap_rows
                    stacked_rows = np.stack((image_top,image_bottom), axis=1)
                    avg_rows = np.average(stacked_rows, axis=1, weights=weight_list_x[i])   # average of each row
                    stitch_center[:, i, :] = avg_rows

                stitch = np.concatenate((image_top_, stitch_center, image_bottom_), axis=1)
            x_stitch_list.append({'img': stitch, 'col': xpos})          # images are flipped WHY?


        """"
        column stitching: fix the row and iterate over columns
        
        IMPORTANT, CURRENTLY ONLY FROM RIGHT TO LEFT 
        """

        scan_direction_x = 'left'

        if scan_direction_x == 'left':
            add_slice = np.s_[:,:, :-overlap_col]
            current_slice = np.s_[:, :, overlap_col:]
            add_indices = np.arange(-overlap_col, 0)
            current_indices = np.flipud(add_indices + 1) * (-1)
        else:
            current_slice = np.s_[:, :, :-overlap_col]
            add_slice = np.s_[:, :, overlap_col:]
            current_indices = np.arange(-overlap_col, 0)
            add_indices = np.flipud(current_indices + 1) * (-1)
        # x_stitch_list = list(reversed(x_stitch_list))
        stitch_y_data = x_stitch_list[0]
        stitch_y = stitch_y_data['img']   # right image
        logger.debug('start column stitching with column ', stitch_y_data['col'])
        ii=0

        """
        careful here, think about a clever way to implement different scan directions,
        incicces will completely change :( probably it's better to have functions stitch_left, stitch_right to optimize calculation time')
        """

        for j in x_stitch_list[1:]:
            ii+=1
            logger.debug('start to attach xpos', j['col'])
            to_add = j['img']   # left currently
            to_add_ = to_add[add_slice]
            current_ = stitch_y[current_slice]
            image_shape = to_add_.shape
            stitch_center = np.empty((image_shape[0], image_shape[1] , overlap_row)) #save averaged data
            for i, add_index in enumerate(add_indices):   # we move the right image to the left; the left image must have the largest weight at the start
                image_to_add = to_add[:, :, add_index]  # here: start with the most-left pixel of the image to add (it is on the left!)
                image_current = stitch_y[:,: , current_indices[i]]
                """
                opposite weights for scan direction right 
                """
                stacked_cols = np.stack((image_to_add, image_current), axis=2)
                avg_cols = np.average(stacked_cols, axis=2, weights=weight_list_y[i]) # average of each row
                stitch_center[:,:,i] = avg_cols
            stitch_y = np.concatenate((to_add_, stitch_center, current_), axis=2)  # stitched data

        self.stitched_image = stitch_y

        self.stitchedImageChanged.emit(self.stitched_image)

    # Getters for important properties
    @property
    def delimiter_indicator(self) -> str:
        return self.delimiter_indicator_textbox.text()

    @property
    def pos_indicator(self) -> str:
        return self.pos_indicator_textbox.text()

    @property
    def row_overlap(self):
        return int(self._row_overlap_spinbox.value())

    @property
    def column_overlap(self)  -> int :
        return int(self._column_overlap_spinbox.value())

    @property
    def max_weight(self):
        return self._max_weight_spinbox.value()

    @property
    def correlation_checked(self):
        return self._correlation_checkbox.isChecked()

    @property
    def sigma_interval(self):
        return self._sigma_interval_spinbox.value()

    @property
    def channels_entry(self):
        return self._channels_entry.text()

    @property
    def mean_checked(self):
        return self._mean_checkbox.isChecked()

    @property
    def average_checked(self):
        return self._average_checkbox.isChecked()

    # Setter methods for important properties
    @row_overlap.setter
    def row_overlap(self, value):
        self._row_overlap_spinbox.setValue(value)

    @column_overlap.setter
    def column_overlap(self, value):
        self._column_overlap_spinbox.setValue(value)

    @max_weight.setter
    def max_weight(self, value):
        self._max_weight_spinbox.setValue(value)

    @correlation_checked.setter
    def correlation_checked(self, value):
        self._correlation_checkbox.setChecked(value)

    @sigma_interval.setter
    def sigma_interval(self, value):
        self._sigma_interval_spinbox.setValue(value)

    @channels_entry.setter
    def channels_entry(self, value):
        self._channels_entry.setText(value)

    @mean_checked.setter
    def mean_checked(self, value):
        self._mean_checkbox.setChecked(value)

    @average_checked.setter
    def average_checked(self, value):
        self._average_checkbox.setChecked(value)
