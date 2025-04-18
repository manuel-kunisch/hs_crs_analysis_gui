import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore


class CustomGradientEditorItem(pg.GradientEditorItem):
    def __init__(self):
        # Define your custom LUT color points and colormaps here
        color_points = np.array([0.0, 1.0])
        colors = np.array([[255, 0, 0, 255], [255, 0, 0, 255]], dtype=np.uint8)

        # Create a custom GradientEditorItem with your color points and colormaps
        self.gradient = pg.ColorMap(color_points, colors)
        pg.GradientEditorItem.__init__(self, self.gradient)


app = pg.mkQApp()
win = pg.GraphicsLayoutWidget()
win.setWindowTitle("Custom Monochromatic LUT Example")

view = win.addViewBox()
image_item = pg.ImageItem(np.random.rand(100, 100))
view.addItem(image_item)

# Create a custom GradientEditorItem with red monochromatic LUT
custom_lut = CustomGradientEditorItem()

# Set the LUT for the image item
image_item.setLookupTable(custom_lut.gradient.getLookupTable(0.0, 1.0, 256))

view.setRange(QtCore.QRectF(0, 0, 100, 100))
view.setAspectLocked(True)

win.show()
app.exec_()
