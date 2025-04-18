import numpy as np
import pyqtgraph as pg

# Example data
data = np.random.rand(100, 100)  # Grayscale image
highlight_mask = np.zeros((100, 100, 4), dtype=np.uint8)  # RGBA mask

# Define highlighted pixels
highlighted_pixels = [(50, 50), (30, 40), (70, 80)]
for x, y in highlighted_pixels:
    highlight_mask[y, x] = [255, 0, 0, 255]  # Red highlight with full opacity

app = pg.mkQApp()
win = pg.GraphicsLayoutWidget()
view = win.addViewBox()

# Create ImageItems
img_item = pg.ImageItem(data)
overlay_item = pg.ImageItem(highlight_mask)
overlay_item.setOpacity(1)  # Adjust transparency

# Add to the ViewBox
view.addItem(img_item)
view.addItem(overlay_item)


# use scatter plot to highlight pixels
# Define highlighted pixels
positions = np.array([[50, 50], [30, 40], [70, 80]])

# Scatter plot with different markers
scatter = pg.ScatterPlotItem(
    pos=positions,
    size=15,
    brush=pg.mkBrush('r'),
    symbol='+',  # Change this to 'o', 'x', 'star', etc.
    pen=pg.mkPen('w', width=2)  # White outline
)
view.addItem(scatter)

win.show()
app.exec_()
