import random
import sys

from PySide2.QtCore import Qt
from PySide2.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDial,
    QDoubleSpinBox,
    QFontComboBox,
    QLabel,
    QLCDNumber,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)


# Subclass QMainWindow to customize your application's main composite_image
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Widgets App")

        layout = QVBoxLayout()

        widgets = [
            QCheckBox("Check Box"),
            QComboBox(),
            QDateEdit(),
            QDateTimeEdit(),
            QDial(),
            QDoubleSpinBox(),
            QFontComboBox(),
            QLCDNumber(),
            QLabel("Label"),
            QLineEdit(),
            QProgressBar(),
            QPushButton("Button"),
            QRadioButton("Radio Button"),
            QSlider(Qt.Horizontal),
            QSpinBox(),
            QTimeEdit(),
        ]

        for w in widgets:
            layout.addWidget(w)

        button = QPushButton("Randomize Values")
        button.clicked.connect(self.randomize_values)
        layout.addWidget(button)

        self.setStyleSheet('''
            QCheckBox { color: blue; }
            QLabel { font-size: 16px; }
        ''')

        widget = QWidget()
        widget.setLayout(layout)

        self.setCentralWidget(widget)

    def randomize_values(self):
        for widget in self.centralWidget().children():
            if isinstance(widget, QDateEdit):
                widget.setDate(random.choice([QDateEdit.minimumDate, QDateEdit.maximumDate]))
            elif isinstance(widget, QDateTimeEdit):
                widget.setDateTime(random.choice([QDateTimeEdit.minimumDateTime(), QDateTimeEdit.maximumDateTime()]))
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(random.uniform(widget.minimum(), widget.maximum()))
            elif isinstance(widget, QLCDNumber):
                widget.display(random.randint(0, 999))
            elif isinstance(widget, QLineEdit):
                widget.setText(f"Random: {random.randint(1, 100)}")
            elif isinstance(widget, QProgressBar):
                widget.setValue(random.randint(0, 100))
            elif isinstance(widget, QSlider):
                widget.setValue(random.randint(widget.minimum(), widget.maximum()))
            elif isinstance(widget, QSpinBox):
                widget.setValue(random.randint(widget.minimum(), widget.maximum()))


app = QApplication(sys.argv)
window = MainWindow()
window.show()
sys.exit(app.exec_())
