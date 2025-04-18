import sys

from PyQt5.QtCore import *
from PyQt5.QtWidgets import *


class dockdemo(QMainWindow):
    def __init__(self, parent=None):
        super(dockdemo, self).__init__(parent)

        layout = QHBoxLayout()
        bar = self.menuBar()
        file = bar.addMenu("File")
        file.addAction("New")
        file.addAction("save")
        file.addAction("quit")

        self.items = QDockWidget("Dockable")
        self.listWidget = QListWidget()
        self.listWidget.addItem("item1")
        self.listWidget.addItem("item2")
        self.listWidget.addItem("item3")

        self.items.setWidget(self.listWidget)
        # self.items.setFloating(False)
        self.setCentralWidget(QTextEdit())
        self.addDockWidget(Qt.RightDockWidgetArea, self.items)
        self.setLayout(layout)
        self.setWindowTitle("Dock demo")


class DockTabDemo(QMainWindow):
    def __init__(self, parent=None):
        super(DockTabDemo, self).__init__(parent)

        # Menu bar setup
        bar = self.menuBar()
        file_menu = bar.addMenu("File")
        file_menu.addAction("New")
        file_menu.addAction("Save")
        file_menu.addAction("Quit")

        # Create the tab widget
        tab_widget = QTabWidget()
        tab1 = QMainWindow()
        tab2 = QMainWindow()
        tab3 = QMainWindow()
        tab_widget.addTab(tab1, "Tab 1")
        tab_widget.addTab(tab2, "Tab 2")
        tab_widget.addTab(tab3, "Tab 3")

        # Get all the tabs from the tab widget and set up docks
        for i in range(tab_widget.count()):
            tab = tab_widget.widget(i)
            self.setup_tab_with_docks(tab)

        # Set the tab widget as the central widget of the QMainWindow
        self.setCentralWidget(tab_widget)
        self.setWindowTitle("Dock Tab Demo")

    def setup_tab_with_docks(self, tab):
        """Setup docks inside a QMainWindow which is embedded in a tab."""
        # Create a dockable widget
        dock = QDockWidget("Dockable", self)
        list_widget = QListWidget()
        list_widget.addItem("Item 1")
        list_widget.addItem("Item 2")
        list_widget.addItem("Item 3")
        dock.setWidget(list_widget)

        # Add the dock widget to the QMainWindow (tab)
        tab.addDockWidget(Qt.RightDockWidgetArea, dock)

        # Add a central widget to the tab's QMainWindow
        central_widget = QWidget()
        tab.setCentralWidget(central_widget)
        tab_layout = QVBoxLayout()
        central_widget.setLayout(tab_layout)

        # Add other widgets to the tab's central widget layout
        tab_layout.addWidget(QTextEdit("Text Edit 1"))
        tab_layout.addWidget(QTextEdit("Text Edit 2"))

def main():
    app = QApplication(sys.argv)
    ex = DockTabDemo()
    ex.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()