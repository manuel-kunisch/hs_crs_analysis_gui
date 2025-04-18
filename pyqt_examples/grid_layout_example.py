import sys

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QLabel, QLineEdit, QPushButton, QDockWidget, QTextEdit, \
    QGridLayout


class NonClosableDockWidget(QDockWidget):
    def closeEvent(self, event):
        event.ignore()  # Ignore the close event to prevent the dock widget from being closed

class DockAndGridLayoutExample(QMainWindow):
    def __init__(self):
        super().__init__()

        self.initUI()

    def initUI(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        grid_layout = QGridLayout()
        central_widget.setLayout(grid_layout)

        label = QLabel('Enter Text:')
        line_edit = QLineEdit()
        button = QPushButton('Submit')

        grid_layout.addWidget(label, 0, 0)
        grid_layout.addWidget(line_edit, 0, 1, 1, 2)
        grid_layout.addWidget(button, 2, 0, 1, 2)  # Button spans two columns

        dock = NonClosableDockWidget('Dock Area', self)
        dock_widget = QTextEdit()
        dock.setWidget(dock_widget)
        self.addDockWidget(1, dock)  # DockWidgetArea: Right Dock Area


        self.setWindowTitle('Dock and GridLayout Example')
        self.setGeometry(100, 100, 400, 300)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = DockAndGridLayoutExample()
    window.show()
    sys.exit(app.exec_())
