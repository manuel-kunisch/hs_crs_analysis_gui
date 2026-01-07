from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QColor
import pyqtgraph as pg


class ComponentColorManager(QObject):
    # Signal emitted when a color changes: (component_index, new_QColor)
    sigColorChanged = pyqtSignal(int, QColor)

    def __init__(self, default_colors=None):
        super().__init__()
        # Default vivid colors for components
        if default_colors is None:
            self._colors = [
                QColor(255, 0, 0),  # Red
                QColor(0, 255, 0),  # Green
                QColor(0, 0, 255),  # Blue
                QColor(255, 255, 0),  # Yellow
                QColor(0, 255, 255),  # Cyan
                QColor(255, 0, 255),  # Magenta
                QColor(255, 128, 0),  # Orange
                QColor(128, 0, 255),  # Purple
            ]
        else:
            self._colors = [QColor(c) for c in default_colors]

    def get_qcolor(self, index: int) -> QColor:
        """Get QColor for a component index (cycles if index > len)."""
        if not self._colors:
            return QColor(255, 255, 255)
        return self._colors[index % len(self._colors)]

    def get_color_rgb(self, index: int):
        """Get color in (R,G,B) tuple format."""
        c = self.get_qcolor(index)
        return (c.red(), c.green(), c.blue())

    def get_pg_color(self, index: int):
        """Get color in format suitable for pyqtgraph (R,G,B,A)."""
        c = self.get_color(index)
        return (c.red(), c.green(), c.blue(), 255)

    def set_color(self, index: int, color: QColor):
        """Update color and notify all listeners."""
        # Ensure list is long enough
        while len(self._colors) <= index:
            self._colors.append(QColor(255, 255, 255))

        self._colors[index] = color
        self.sigColorChanged.emit(index, color)

    def set_color_rgb(self, index: int, *args):
        """
        Set color using RGB values.
        Accepts either separate args: set_color_rgb(0, 255, 0, 0)
        Or a tuple: set_color_rgb(0, (255, 0, 0))
        """
        # 1. Handle the case where a single tuple/list is passed
        if len(args) == 1 and isinstance(args[0], (list, tuple)):
            rgb = args[0]
        # 2. Handle the case where integers are passed directly
        else:
            rgb = args

        # 3. Unpack the list/tuple into the QColor constructor
        color = QColor(*rgb)
        self.set_color(index, color)

    def get_all_colors_rgb(self):
        """Get all colors as a list of (R,G,B) tuples."""
        return [self.get_color_rgb(i) for i in range(len(self._colors))]