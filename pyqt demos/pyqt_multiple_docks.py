import sys

from PyQt5 import QtWidgets
from pyqtgraph.dockarea import DockArea, Dock


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        # Create the central widget and set it as the main widget
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        central_layout = QtWidgets.QVBoxLayout(central_widget)

        # Create a DockArea from PyQtGraph
        self.dock_area = DockArea()
        central_layout.addWidget(self.dock_area)

        # Create and add docks
        self.create_docks()

    def create_docks(self):
        # Create docks
        self.left_dock = Dock("Left Dock", size=(150, 300))
        self.right_dock = Dock("Right Dock", size=(150, 300))
        self.top_dock = Dock("Top Dock", size=(300, 150))
        self.bottom_dock = Dock("Bottom Dock", size=(300, 150))
        self.central_dock = Dock("Central Dock", size=(300, 300))

        # Add docks to the DockArea
        self.dock_area.addDock(self.left_dock, 'left')
        self.dock_area.addDock(self.right_dock, 'right')
        self.dock_area.addDock(self.top_dock, 'top')
        self.dock_area.addDock(self.bottom_dock, 'bottom')
        self.dock_area.addDock(self.central_dock, 'bottom')

        # Set the central dock to fill the remaining space
        self.dock_area.addDock(self.central_dock, 'bottom', self.bottom_dock)

        # Fill docks with widgets for testing
        self.left_dock.addWidget(QtWidgets.QLabel("Left Dock Content"))
        self.right_dock.addWidget(QtWidgets.QLabel("Right Dock Content"))
        self.top_dock.addWidget(QtWidgets.QLabel("Top Dock Content"))
        self.bottom_dock.addWidget(QtWidgets.QLabel("Bottom Dock Content"))
        self.central_dock.addWidget(QtWidgets.QLabel("Central Dock Content"))


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.resize(800, 600)
    window.show()
    sys.exit(app.exec_())