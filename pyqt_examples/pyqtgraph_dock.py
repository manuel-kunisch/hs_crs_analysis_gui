import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtGui, QtCore, Qt  # Import the necessary modules
from pyqtgraph.console import ConsoleWidget
from pyqtgraph.dockarea.Dock import Dock
from pyqtgraph.dockarea.DockArea import DockArea
from pyqtgraph.graphicsItems.VTickGroup import VTickGroup
from tifffile import imread

from composite_image import CompositeImageViewWidget
from contents.custom_pyqt_objects import ImageViewLineRoi

image_file = imread(
    '/Users/mkunisch/Nextcloud/Manuel_BA/HS_CARS_Lung_cells_day_2_Vukosaljevic_et_al/2017_03_23_Lungcells_Day2_60mWBoth_2xZoom_16ms_Pos2_HS_CARS_ch-1_C.tif')


class PlotAreaWidget(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.layout = QtWidgets.QVBoxLayout(self)
        self.setLayout(self.layout)
        self.init_dock_area()
        self.init_overview_dock()
        self.init_toolbar()
        # Initialize a list to store added ROIs
        self.rois = []
        self.active_roi = None
        self.roi_colors = {}


    def init_dock_area(self):
        self.dock_area_widget = QtWidgets.QWidget(self)  # Placeholder widget to contain the DockArea
        self.layout.addWidget(self.dock_area_widget)

        self.dock_area_layout = QtWidgets.QVBoxLayout(self.dock_area_widget)  # Layout for the placeholder widget
        self.area = DockArea()
        self.dock_area_layout.addWidget(self.area)

        d1 = Dock("Dock1", size=(1, 1))
        d2 = Dock("Dock2 - Console", size=(20, 50), closable=True)
        d3 = Dock("Dock3", size=(500, 400))
        d4 = Dock("Dock4 (tabbed) - Plot", size=(500, 200))
        self.d5 = Dock("Image", size=(500, 500))
        d6 = Dock("Dock6 (tabbed) - Plot", size=(500, 200))
        # Adding the docks to the DockArea()
        self.area.addDock(d1, 'left')
        self.area.addDock(d2, 'right')
        self.area.addDock(d3, 'bottom', d1)
        self.area.addDock(d4, 'right')
        self.area.addDock(self.d5, 'left', d1)
        self.area.addDock(d6, 'top', d4)

        w1 = pg.LayoutWidget()
        label = QtWidgets.QLabel(""" -- DockArea Example -- 
        This composite_image has 6 Dock widgets in it. Each dock can be dragged
        by its title bar to occupy a different space within the composite_image 
        but note that one dock has its title bar hidden). Additionally,
        the borders between docks may be dragged to resize. Docks that are dragged on top
        of one another are stacked in a tabbed layout. Double-click a dock title
        bar to place it in its own composite_image.
        """)
        saveBtn = QtWidgets.QPushButton('Save dock state')
        restoreBtn = QtWidgets.QPushButton('Restore dock state')
        restoreBtn.setEnabled(False)
        w1.addWidget(label, row=0, col=0)
        w1.addWidget(saveBtn, row=1, col=0)
        w1.addWidget(restoreBtn, row=2, col=0)
        d1.addWidget(w1)

        # Create a button for adding a line ROI
        self.add_line_roi_button = QtWidgets.QPushButton("Add ROI")
        self.add_line_roi_button.clicked.connect(self.add_roi)
        self.layout.addWidget(self.add_line_roi_button)

        # Set up the ROI table and add it to the ROI table dock
        roi_table_dock = Dock("ROI Table Dock")
        self.roi_table = QtWidgets.QTableWidget()
        self.roi_table.setColumnCount(5)
        self.roi_table.setHorizontalHeaderLabels(['Label', 'Color', 'Resonance', 'Actions', 'ROI Shape'])
        roi_table_dock.addWidget(self.roi_table)

        # Connect the selection changed signal of the table to a slot
        self.roi_table.itemSelectionChanged.connect(self.update_selected_roi)
        self.roi_table.setItemDelegateForColumn(3, ROITableDelegate(self.roi_table))

        state = None

        def save():
            nonlocal state
            state = self.area.saveState()
            restoreBtn.setEnabled(True)

        def load():
            nonlocal state
            self.area.restoreState(state)

        saveBtn.clicked.connect(save)
        restoreBtn.clicked.connect(load)

        w2 = ConsoleWidget()
        d2.addWidget(w2)

        d3.hideTitleBar()
        w3 = pg.PlotWidget(title="Linsecan")
        w3.plot(np.random.normal(size=100))
        d3.addWidget(w3)

        # Create the PlotWidget and add it to Dock 4
        self.plot_widget = pg.PlotWidget(title="Dock 4 plot")
        d4.addWidget(self.plot_widget)

        # Add Plot item to show axis labels
        plot = pg.PlotItem(title='ImView')
        plot.setTitle()
        plot.setLabel(axis='left', text='Y-axis')
        plot.setLabel(axis='bottom', text='X-axis')
        self.image_view = RamanImageView(view=plot, discreteTimeLine=True, roi_plot_widget=w3)  # Create a pg.ImageView() object
        self.image_view.view.setDefaultPadding(0)
        self.image_view.setColorMap(pg.colormap.get('plasma'))
        # the view option adds a grid
        # Disable the ROI menu
        # self.raman_raw_image_view.ui.roiBtn.hide()
        # Connect ROI selection change event
        self.image_view.roi.sigRegionChanged.connect(self.update_plot)
        self.image_item = image_file  # Create a sample image



        self.image_view.setImage(image_file[...])
        # Setting the size of the image view
        self.d5.addWidget(self.image_view, 0,0,16,16)
        autoscale_button = QtWidgets.QPushButton("Autoscale")
        autoscale_button.clicked.connect(self.autoscale_image)
        self.d5.addWidget(autoscale_button, 0, 12, 1,1)


        w6 = pg.PlotWidget(title="Dock 6 plot")
        w6.plot(np.random.normal(size=100))
        d6.addWidget(w6)

        self.area.addDock(roi_table_dock, "top")

    def init_overview_dock(self):
        self.overview_dock = Dock("Overview", size=(150, 300))
        self.area.addDock(self.overview_dock, 'bottom')

        self.overview_image_views = []

        for i in range(2):
            for j in range(2):
                image_view = pg.ImageView()
                self.overview_dock.addWidget(image_view, i, j)
                self.overview_image_views.append(image_view)

        self.image_selection_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.image_selection_slider.setRange(0, self.image_item.shape[0] - 1)
        self.image_selection_slider.valueChanged.connect(self.update_overview_images)
        # self.overview_dock.addWidget(self.image_selection_slider, 'bottom')

        self.update_overview_images()  # Call this to display initial images

    def init_toolbar(self):
        self.tool_box = QtWidgets.QGroupBox('Image Tools')
        self.lut_combo_box = QtWidgets.QComboBox(self)
        self.lut_combo_box.addItems(['grey', 'thermal', 'flame', 'yellowy', 'bipolar', 'spectrum', 'cyclic', 'greyclip',
                                     'viridis', 'inferno', 'plasma', 'magma', "red", "green", "blue", "yellow",
                                     "orange", "purple", "pink", "magenta", "custom"])
        self.lut_combo_box.currentIndexChanged.connect(self.update_lut)

        self.custom_toolbar = QtWidgets.QToolBar("Custom Toolbar")
        self.custom_toolbar.addWidget(QtWidgets.QLabel("Image LUT"))
        self.custom_toolbar.addWidget(self.lut_combo_box)
        self.layout.addWidget(self.custom_toolbar, 1)

    def update_overview_images(self):
        selected_image_index = self.image_selection_slider.value()

        for i, image_view in enumerate(self.overview_image_views):
            image = self.image_item[selected_image_index]
            image_view.setImage(image)

    def add_roi(self):
        # Create a ROI item and add it to the image view
        line_roi = pg.RectROI([200, 10], [200, 30], pen=(0, 9))
        color = (255, 0, 0)  # Red color
        # line_roi.setBrush(QtGui.QColor(255, 255, 0))
        label = "ROI {}".format(len(self.rois) + 1)
        self.set_roi_properties(line_roi, color, label)
        self.image_view.getView().addItem(line_roi)
        # custom_roi = CustomROIGraphicsObject(line_roi)
        # self.raman_raw_image_view.addItem(custom_roi)

        self.rois.append(line_roi)  # Add the ROI to the list
        self.roi_colors.update({line_roi: line_roi.pen})
        line_roi.sigRegionChanged.connect(self.line_roi_changed)
        self.update_roi_table()  # Update the table view

    def update_lut(self, index):
        print('Updating LUT')
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
            lut_widget = self.image_view.ui.histogram
            lut_widget.gradient.loadPreset(lut_name)
        except KeyError:
            # Own colormap
            if lut_name == 'custom':
                lut_name = None
            self.image_view.setColorMap(self.get_colormap(lut_name))
        return
        # Access the HistogramLUTWidget associated with the image view




    def get_colormap(self, color=None):
        if color is None:
            # Open a QColorDialog to choose a color for colormap
            color = Qt.QColorDialog.getColor()
            if not color.isValid():
                print('Invalid color choice')
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
        self.image_view.autoLevels()

    def update_roi_table(self):
        # Clear and update the table view with current ROI information
        self.roi_table.setRowCount(len(self.rois))
        self.roi_table.setColumnCount(5)
        for idx, roi in enumerate(self.rois):
            if idx < len(self.rois) - 1:
                continue
            label_item = QtWidgets.QTableWidgetItem(roi.label)
            color_button = ColorButton(roi.pen.color())

            resonance_combobox = QtWidgets.QComboBox()
            resonance_combobox.addItem("None")
            resonance_combobox.addItems("Resonance %i"%i for i in range(6))

            action_button = QtWidgets.QPushButton("Remove")
            action_button.clicked.connect(lambda _, i=idx: self.remove_roi(i))

            type_item = QtWidgets.QComboBox()
            type_item.addItems(["LineROI", "RectROI", "EllipseROI", "RotatableRectROI"])  # Add more options as needed
            type_item.setCurrentText("LineROI" if isinstance(roi, pg.LineROI) else "RectROI")
            self.roi_table.setItem(idx, 0, label_item)
            self.roi_table.setCellWidget(idx, 1, color_button)
            self.roi_table.setCellWidget(idx, 2, resonance_combobox)
            self.roi_table.setCellWidget(idx, 3, action_button)
            self.roi_table.setCellWidget(idx, 4, type_item)

            color_button.color_changed.connect(lambda color, roi_idx=idx: self.update_roi_color(roi_idx, color))
            print(roi)
            type_item.currentTextChanged.connect(lambda shape, row=idx: self.change_roi_type(shape, row))

    def set_roi_properties(self, roi, color, label):
        roi.setPen(pg.mkPen(color))
        roi.label = label
        self.roi_colors[roi] = roi.pen

    def remove_roi(self, index):
        roi = self.rois.pop(index)
        self.image_view.getView().removeItem(roi)
        self.update_roi_table()  # Update the table view

    def line_roi_changed(self):
        selected_roi, _ = self.image_view.roi.getArrayRegion(
            self.image_view.imageItem.image,
            self.image_view.imageItem,
            returnMappedCoords=True
        )

    # Add a new method to update the ROI color
    def update_roi_color(self, roi_idx, color):
        print('Color update')
        print(color)
        roi = self.rois[roi_idx]
        roi.setPen(pg.mkPen(color))
        self.roi_colors[roi] = roi.pen

    def update_selected_roi(self):
        selected_items = self.roi_table.selectedItems()
        if not selected_items:
            return
        print('New ROI selected in Table')
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

    def set_roi_highlight(self, roi, highlighted=True):
        # pen = QtGui.QPen()
        if highlighted:
            # pen.setColor(QtGui.QColor(255, 255, 0))  # Yellow color
            pen = pg.mkPen((255, 255, 0))
        else:
            pen = self.roi_colors[roi]  # Restore original color
        roi.setPen(pen)

    def change_roi_type(self, roi_shape, row_idx):
        old_roi = self.rois[row_idx]
        new_roi = None


        if roi_shape=='RectROI':
            new_roi = pg.RectROI(old_roi.pos(), old_roi.size(), pen=self.roi_colors[old_roi], movable=True)
        elif roi_shape=='LineROI':
            new_roi = pg.LineSegmentROI(old_roi.pos(), old_roi.size(), pen=self.roi_colors[old_roi], movable=True)
        elif roi_shape=='EllipseROI':
            new_roi = pg.EllipseROI(old_roi.pos(), old_roi.size(), pen=self.roi_colors[old_roi], movable=True)
        elif roi_shape=='CircleROI':
            new_roi = pg.CircleROI(old_roi.pos(), old_roi.size(), pen=self.roi_colors[old_roi], movable=True)
        elif roi_shape=='RotatableRectROI':
            new_roi = pg.RectROI(old_roi.pos(), old_roi.size(), pen=self.roi_colors[old_roi], movable=True)
            new_roi.addRotateHandle([0,0], [0.5, 0.5])
        else:
            return
        if new_roi:
            new_roi.label = old_roi.label
            new_roi.setZValue(old_roi.zValue())
            self.image_view.removeItem(old_roi)
            self.image_view.addItem(new_roi)
        row_idx = self.rois.index(old_roi)
        self.rois[row_idx] = new_roi
        self.roi_colors.update({new_roi: new_roi.pen})

    def update_plot(self):
        """
        selected_roi, coords = self.raman_raw_image_view.roi.getArrayRegion(self.raman_raw_image_view.imageItem.image,
                                                                  self.raman_raw_image_view.imageItem,
                                                                  returnMappedCoords=True)
        print(coords)

        # Get the indices of the pixels within the ROI
        # Crop the image stack using the indices of the ROI
        cropped_stack = image_file[:, coords.astype(int)]1
        """
        pass

class ROIManager():
    def __init__(self, image_view, update_roi_table_callback):
        roi_table_dock = Dock("ROI Table Dock")
        self.roi_table = QtWidgets.QTableWidget()
        self.roi_table.setColumnCount(5)
        self.roi_table.setHorizontalHeaderLabels(['Label', 'Color', 'Resonance', 'Actions', 'ROI Shape'])
        roi_table_dock.addWidget(self.roi_table)
        self.image_view = image_view
        self.rois = []
        self.active_roi = None
        self.roi_colors = {}
        self.update_roi_table = update_roi_table_callback

        # Connect the selection changed signal of the table to a slot
        self.roi_table.itemSelectionChanged.connect(self.update_selected_roi)
        self.roi_table.setItemDelegateForColumn(3, ROITableDelegate(self.roi_table))
        
    def add_roi(self):
        # Create a ROI item and add it to the image view
        line_roi = pg.RectROI([200, 10], [200, 30], pen=(0, 9))
        color = (255, 0, 0)  # Red color
        # line_roi.setBrush(QtGui.QColor(255, 255, 0))
        label = "ROI {}".format(len(self.rois) + 1)
        self.set_roi_properties(line_roi, color, label)
        self.image_view.getView().addItem(line_roi)
        # custom_roi = CustomROIGraphicsObject(line_roi)
        # self.raman_raw_image_view.addItem(custom_roi)

        self.rois.append(line_roi)  # Add the ROI to the list
        self.roi_colors.update({line_roi: line_roi.pen})
        line_roi.sigRegionChanged.connect(self.line_roi_changed)
        self.update_roi_table()  # Update the table view

    def update_roi_table(self):
        # Clear and update the table view with current ROI information
        self.roi_table.setRowCount(len(self.rois))
        self.roi_table.setColumnCount(5)
        for idx, roi in enumerate(self.rois):
            if idx < len(self.rois) - 1:
                continue
            label_item = QtWidgets.QTableWidgetItem(roi.label)
            color_button = ColorButton(roi.pen.color())

            resonance_combobox = QtWidgets.QComboBox()
            resonance_combobox.addItem("None")
            resonance_combobox.addItems("Resonance %i"%i for i in range(6))

            action_button = QtWidgets.QPushButton("Remove")
            action_button.clicked.connect(lambda _, i=idx: self.remove_roi(i))

            type_item = QtWidgets.QComboBox()
            type_item.addItems(["LineROI", "RectROI", "EllipseROI", "RotatableRectROI"])  # Add more options as needed
            type_item.setCurrentText("LineROI" if isinstance(roi, pg.LineROI) else "RectROI")
            self.roi_table.setItem(idx, 0, label_item)
            self.roi_table.setCellWidget(idx, 1, color_button)
            self.roi_table.setCellWidget(idx, 2, resonance_combobox)
            self.roi_table.setCellWidget(idx, 3, action_button)
            self.roi_table.setCellWidget(idx, 4, type_item)

            color_button.color_changed.connect(lambda color, roi_idx=idx: self.update_roi_color(roi_idx, color))
            print(roi)
            type_item.currentTextChanged.connect(lambda shape, row=idx: self.change_roi_type(shape, row))

    def set_roi_properties(self, roi, color, label):
        roi.setPen(pg.mkPen(color))
        roi.label = label
        self.roi_colors[roi] = roi.pen

    def remove_roi(self, index):
        roi = self.rois.pop(index)
        self.image_view.getView().removeItem(roi)
        self.update_roi_table()  # U

    def update_roi_color(self, roi_idx, color):
        print('Color update')
        print(color)
        roi = self.rois[roi_idx]
        roi.setPen(pg.mkPen(color))
        self.roi_colors[roi] = roi.pen

    def line_roi_changed(self):
        selected_roi, _ = self.image_view.roi.getArrayRegion(
            self.image_view.imageItem.image,
            self.image_view.imageItem,
            returnMappedCoords=True
        )

    def update_selected_roi(self):
        selected_items = self.roi_table.selectedItems()
        if not selected_items:
            return
        print('New ROI selected in Table')
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


        if roi_shape=='RectROI':
            new_roi = pg.RectROI(old_roi.pos(), old_roi.size(), pen=self.roi_colors[old_roi], movable=True)
        elif roi_shape=='LineROI':
            new_roi = pg.LineSegmentROI(old_roi.pos(), old_roi.size(), pen=self.roi_colors[old_roi], movable=True)
        elif roi_shape=='EllipseROI':
            new_roi = pg.EllipseROI(old_roi.pos(), old_roi.size(), pen=self.roi_colors[old_roi], movable=True)
        elif roi_shape=='CircleROI':
            new_roi = pg.CircleROI(old_roi.pos(), old_roi.size(), pen=self.roi_colors[old_roi], movable=True)
        elif roi_shape=='RotatableRectROI':
            new_roi = pg.RectROI(old_roi.pos(), old_roi.size(), pen=self.roi_colors[old_roi], movable=True)
            new_roi.addRotateHandle([0,0], [0.5, 0.5])
        else:
            return
        if new_roi:
            new_roi.label = old_roi.label
            new_roi.setZValue(old_roi.zValue())
            self.image_view.removeItem(old_roi)
            self.image_view.addItem(new_roi)
        row_idx = self.rois.index(old_roi)
        self.rois[row_idx] = new_roi
        self.roi_colors.update({new_roi: new_roi.pen})

    def set_roi_highlight(self, roi, highlighted=True):
        # pen = QtGui.QPen()
        if highlighted:
            # pen.setColor(QtGui.QColor(255, 255, 0))  # Yellow color
            pen = pg.mkPen((255, 255, 0))
        else:
            pen = self.roi_colors[roi]  # Restore original color
        roi.setPen(pen)

class ColorButton(QtWidgets.QPushButton):
    def __init__(self, color):
        super().__init__()
        self.color = color
        self.setStyleSheet(f"background-color: {color.name()}")
        self.clicked.connect(self.pick_color)

    def pick_color(self):
        new_color = QtWidgets.QColorDialog.getColor(self.color)
        if new_color.isValid():
            self.color = new_color
            self.setStyleSheet(f"background-color: {new_color.name()}")
            self.color_changed.emit(new_color)

    color_changed = QtCore.pyqtSignal(QtGui.QColor)


class CustomROIGraphicsObject(pg.GraphicsObject):
    def __init__(self, roi: pg.LineROI):
        super().__init__()
        self.roi = roi
        self.highlighted = False
        self.setFlag(self.ItemIsSelectable, True)

    def paint(self, painter, options, widget):
        color = (255, 255, 0)
        if self.highlighted:
            color = (255, 255, 0)
            painter.setPen(pg.mkPen(color))
            painter.setBrush(QtGui.QColor(255, 255, 0))  # Yellow color
        else:
            painter.setPen(pg.mkPen(color))
            painter.setBrush(QtGui.QColor(255, 255, 0))

        # path = self.roi.currentPath()
        # painter.drawPath(path)

    def boundingRect(self):
        return self.roi.boundingRect()

    def setSelected(self, selected):
        super().setSelected(selected)
        self.highlighted = selected
        self.update()

class MainApplication(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.layout = Qt.QVBoxLayout(self)
        self.setLayout(self.layout)
        self.setWindowTitle("HS Data Viewer")
        # setting  the geometry of composite_image
        # setGeometry(left, top, width, height)
        self.setGeometry(0, 0, 2560, 1440)

        self.data_section = PlotAreaWidget()  # Assuming you have defined this class

        self.tab_widget = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tab_widget)

        # Create and configure the DockArea for the CompositeImageViewWidget
        self.dock_area_widget = QtWidgets.QWidget()  # Placeholder widget to contain the DockArea
        self.layout = QtWidgets.QVBoxLayout(self.dock_area_widget)  # Layout for the placeholder widget
        self.area = DockArea()
        self.layout.addWidget(self.area)

        d1 = Dock("Multivariate Analysis Results", size=(1, 1))
        # Put orientation of dock handle
        self.area.addDock(d1, 'top')
        self.result_viewer = CompositeImageViewWidget()  # Create CompositeImageViewWidget widget
        d1.addWidget(self.result_viewer)  # Add the CompositeImageViewWidget widget to the dock

        # Create a fixed composite_image for the DockArea
        dock_window = QtWidgets.QWidget()
        dock_layout = QtWidgets.QVBoxLayout(dock_window)
        dock_layout.addWidget(self.area)

        # Add the fixed dock composite_image to the result section tab
        self.tab_widget.addTab(self.data_section, "Data Section")
        self.tab_widget.addTab(dock_window, "Result Section")


        """
        
        self.stack_widget = QtWidgets.QStackedWidget()
        self.setCentralWidget(self.stack_widget)
        
        self.stack_widget.addWidget(self.data_section)
        self.stack_widget.addWidget(self.result_section)

        self.selection_combo = QtWidgets.QComboBox()
        self.selection_combo.addItem("Data Section")
        self.selection_combo.addItem("Result Section")
        self.selection_combo.currentIndexChanged.connect(self.switch_section)
        self.addToolBar(QtCore.Qt.ToolBarArea.BottomToolBarArea, QtWidgets.QToolBar())
        self.tool_bar = self.addToolBar("Selection")
        self.tool_bar.addWidget(self.selection_combo)
        """


    def switch_section(self, index):
        self.stack_widget.setCurrentIndex(index)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Close:
            print(obj)
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



class CustomGraphicsView(pg.GraphicsView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMenuEnabled(False)
        self.setMouseEnabled(False, False)

class RamanImageView(ImageViewLineRoi):
    #FIXME: Make this a ROI plot which shows the mean intensity over different Raman shifts
    """
    modified ImageView object with additional features

    changed functionalities:
    - removed scalable frame composite_image (roiPlot)
    - added wavenumbers to roiPlot


    added features:
    - A button auto scales the image levels
    - S button auto ranges the image pan
    """
    def __init__(self, *args, roi_plot_widget=None, **kwargs):
        super().__init__(*args, **kwargs)
        # self.roi = pg.LineSegmentROI([(0, 0), (50, 50)])
        self.fps = 10
        self.play(self.fps)
        # create vertical ticks in the frame graph
        self.frameTicks = VTickGroup(yrange=[0.8, 1], pen=0.4)
        # make frame plot unscalable
        # ui.roiPlot is the PlotItem() for the frames
        self.ui.roiPlot.addItem(self.frameTicks, ignoreBounds=False)
        # enlarge the ROI plot
        self.ui.roiPlot.setMinimumSize(QtCore.QSize(0, 60))

        self.playLoop = True  # Initialize play loop flag

        self.ui.roiPlot.getAxis('bottom').setLabel(r'Raman Shift [1/cm]')
        # self.ui.roiPlot.setMenuEnabled(False)

        # Hide AutoScale Button of Frame Scale
        self.ui.roiPlot.hideButtons()
        self.frame_label = pg.TextItem(text='', color=(255, 255, 255))
        self.addItem(self.frame_label)
        self.frame_label.setPos(10, 1)

        self.linescan = []
        self.wavenumber = None
        self.roiPlotWidget = roi_plot_widget


    def updateImage(self, **kwargs):
        super().updateImage(**kwargs)
        print('Update called')
        frame = self.currentIndex
        self.frame_label.setText(f'Frame: {frame}')
        if self.view is not None and self.wavenumber is not None:
            self.view.setTitle(f'Image @ {self.wavenumber[self.currentIndex]:.1f} 1/cm')

    def roiChanged(self, *args, plot_widget=None):
        # args is the line roi which is passed at the event call
        data_cur_im, coords = self.roi.getArrayRegion(self.image[self.currentIndex, ...], self.imageItem, returnMappedCoords=True)
        y_vals = data_cur_im


        pl = plot_widget
        if pl is None:
            plot_widget = self.roiPlotWidget
            pl = self.roiPlotWidget
        pl = pl.plot()
        pl.clear()
        # Assumes a single ROI
        if len(self.linescan) == 0:
            self.linescan.append(pl)
            self.roiCurves.append(pl)
        plot_widget.setLabels(left='Intensity [a.u.]', bottom='Pixel')
        x_vals = np.arange(len(y_vals))  # Generate x values based on the length of y_vals
        # Overwrite existing plot by calling the listed object
        self.linescan[-1].setData(x_vals, y_vals)

    def roiClicked(self):
        showRoiPlot = False
        if self.ui.roiBtn.isChecked():
            showRoiPlot = True
            self.roi.show()
            self.ui.roiPlot.setMouseEnabled(True, True)
            # self.ui.splitter.setSizes([int(self.height() * 0.6), int(self.height() * 0.4)])
            # self.ui.splitter.handle(1).setEnabled(True)
            self.roiChanged()
            for c in self.roiCurves:
                c.show()
            # self.ui.roiPlot.showAxis('left')
        else:
            self.roi.hide()
            self.ui.roiPlot.setMouseEnabled(False, False)
            for c in self.roiCurves:
                c.hide()
            self.ui.roiPlot.hideAxis('left')
        # Overwrite adjustment of Timeline
        """
         if self.hasTimeAxis():
            showRoiPlot = True
            mn = self.tVals.min()
            mx = self.tVals.max()
            self.ui.roiPlot.setXRange(mn, mx, padding=0.01)
            self.timeLine.show()
            self.timeLine.setBounds([mn, mx])
            if not self.ui.roiBtn.isChecked():
                self.ui.splitter.setSizes([self.height() - 35, 35])
                self.ui.splitter.handle(1).setEnabled(False)
        else:
            self.timeLine.hide()
        self.ui.roiPlot.setVisible(showRoiPlot)
        """
        pass


    def play(self, fps):
        print('Keep playing')
        if self.image is None:
            return
        if self.currentIndex == self.image.shape[0] - 1 and self.playLoop:
            self.setCurrentIndex(0)
        else:
            super().play(fps)

    def timeLineChanged(self):
        super().timeLineChanged()
        print('Time Line call')
        self.roiChanged()
        if self.currentIndex == self.nframes()-1 and self.playLoop:
            self.setCurrentIndex(0)

    def setImage(self, *args, **kwargs):
        print('Set image method called')
        super().setImage(*args, **kwargs)
        # Start Auto Play
        self.play(self.fps)
        bottom_axis = self.ui.roiPlot.getAxis('bottom')
        self.wavenumber = np.linspace(3100, 2800, self.nframes())
        print(self.wavenumber)
        max_ticks = 20
        step = max(1, len(self.wavenumber) // (max_ticks - 2))  # Adjust for first and last ticks

        tick_values = [(i, f'{v:.0f}') for i, v in enumerate(self.wavenumber) if i % step == 0]
        # tick_values.insert(0, (0, '%.0f'%raman_shifts[0]))  # Set the first tick value
        # tick_values.append((-1, '%.0f'%(raman_shifts[-1])))  # Append the last tick
        bottom_axis.setTicks([tick_values])
        bottom_axis.setRange(-1, 1.5)


    def keyPressEvent(self, ev):
        if ev.key() == QtCore.Qt.Key.Key_Space:
            self.togglePause()
            ev.accept()
        elif ev.key() == QtCore.Qt.Key.Key_A:
            self.autoLevels()
        elif ev.key() == QtCore.Qt.Key.Key_S:
            self.autoRange()
        else:
            # Call the predefined key press events
            super().keyPressEvent(ev)

class ROITableDelegate(QtWidgets.QItemDelegate):
    def createEditor(self, parent, option, index):
        if index.column() == 3:
            combo_box = QtWidgets.QComboBox(parent)
            combo_box.addItem("LineROI")
            combo_box.addItem("RectROI")
            return combo_box
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        if index.column() == 3:
            text = index.data()
            combo_box = editor
            combo_box.setCurrentText(text)
        else:
            super().setEditorData(editor, index)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)

    def setModelData(self, editor, model, index):
        if index.column() == 3:
            combo_box = editor
            roi_type = combo_box.currentText()
            model.setData(index, roi_type)
        else:
            super().setModelData(editor, model, index)

if __name__ == '__main__':
    app = QtWidgets.QApplication([])  # Create a QApplication instance
    main_app = MainApplication()
    main_app.show()
    app.exec_()
