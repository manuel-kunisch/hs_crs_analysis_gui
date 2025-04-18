import sys

import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout


class CombinedImagesDemo(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Combined Images Demo")
        self.setGeometry(100, 100, 800, 600)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)

        # Simulated grayscale images with colormaps
        width, height = 512, 512
        gradient_image = np.linspace(0, 255, width).astype(np.uint8)
        image1 = np.tile(gradient_image, (height, 1))

        image2 = image1[::-1,::-1]

        # Convert grayscale images to RGB with colormaps
        vmin = 0
        vmax = 455
        colormap_yellow = pg.ColorMap(pos=[vmin, vmax], color=[(0,0,0), (255, 255, 0)])
        colormap_blue = pg.ColorMap(pos=[vmin, vmax], color=[(0, 0, 0), (0, 0, 255)])
        image1_rgb = colormap_yellow.map(image1)
        image2_rgb = colormap_blue.map(image2)

        # Combine images by element-wise addition
        combined_image = image1_rgb + image2_rgb

        # Create an ImageView widget to display the combined image
        self.image_view = pg.ImageView()
        layout.addWidget(self.image_view)

        # Set the combined image data in the ImageView widget
        self.image_view.setImage(combined_image)

def main():
    app = QApplication(sys.argv)
    window = CombinedImagesDemo()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
