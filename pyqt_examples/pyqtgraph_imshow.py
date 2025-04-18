import sys  # We need sys so that we can pass argv to QApplication

import pyqtgraph as pg
from PySide2 import QtWidgets, QtCore
from tifffile import imread

image_file = imread('/Users/mkunisch/Nextcloud/Manuel_BA/HS_CARS_Lung_cells_day_2_Vukosaljevic_et_al/2017_03_23_Lungcells_Day2_60mWBoth_2xZoom_16ms_Pos2_HS_CARS_ch-1_C.tif')

class MainWindow(QtWidgets.QMainWindow):

    def __init__(self, *args, **kwargs):
        super(MainWindow, self).__init__(*args, **kwargs)

        self.graphWidget = pg.ImageView()
        self.setCentralWidget(self.graphWidget)

        self.graphWidget.setImage(image_file[0,...], colorMap='viridis')
        # ... init continued ...
        self.timer = QtCore.QTimer()
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.update_plot_data)
        self.timer.start()
        self.i = 0

    def update_plot_data(self):
        self.i += 1
        self.graphWidget.setImage(image_file[self.i%image_file.shape[0], ...])

app = QtWidgets.QApplication(sys.argv)
w = MainWindow()
w.show()
sys.exit(app.exec_())