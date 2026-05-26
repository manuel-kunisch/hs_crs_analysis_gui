import logging

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtGui
from PyQt5.QtCore import Qt, QRect, QPoint
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import QSlider, QWidget, QVBoxLayout, QHBoxLayout, \
    QStyleOptionSlider, QStyle

logger = logging.getLogger(__name__)


class ImageViewLineRoi(pg.ImageView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.roi = pg.LineSegmentROI(positions=[(0,0), (10,10)])
        self.view.addItem(self.roi)
        self.roi.sigRegionChanged.connect(self.roiChanged)

    def roiChanged(self, *args, plot_widget=None):
        # args is the line roi which is passed at the event call
        # Plots line scan below the ImageItem
        # only works for this single ROI
        data, coords = self.roi.getArrayRegion(self.image, self.imageItem, returnMappedCoords=True)
        if data.ndim == 1:
            y_vals = data
        else:
            y_vals = data.mean(axis=self.axes['x'])  # Average along x-axis
        logger.debug(f'{data.shape=}')
        pl = plot_widget
        if pl is None:
            pl = self.ui.roiPlot
        pl = pl.plot()
        # Assumes a single ROI
        if len(self.roiCurves) == 0:
            self.roiCurves.append(pl)
        self.ui.roiPlot.setLabels(left='Intensity [a.u.]', bottom='Pixel')
        x_vals = np.arange(len(y_vals))  # Generate x values based on the length of y_vals
        # Overwrite existing plot by calling the listed object
        self.roiCurves[-1].setData(x_vals, y_vals)


class ImageViewYXC(pg.ImageView):
    # Corrected class with argument order y,x,c
    # Dim 3 defines the RGB Coloring
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def setImage(self, img, **kwargs):
        if 'axes' not in kwargs:
            ax_order = {'x': 1, 'y': 0, 'c': 2}
            if img.ndim > 3:
                ax_order.update({'t': 3})      # Corrected assignment
            kwargs['axes'] = ax_order  # Use direct assignment instead of .update()
        super().setImage(img, **kwargs)


class ImageViewYX(pg.ImageView):
    # Corrected class with argument order y,x
    # Index 0 corresponds to column
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def setImage(self, img, **kwargs):
        if 'axes' not in kwargs:
            ax_order = {'x': 1, 'y': 0}
            if img.ndim == 3:
                ax_order.update({'t': 2})      # Corrected assignment
            elif img.ndim == 4:
                ax_order.update({'c': 3})  # Corrected assignment
            kwargs['axes'] = ax_order  # Use direct assignment instead of .update()
        super().setImage(img, **kwargs)


class ImageViewLineRoiYXZ(ImageViewYX):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.roi = pg.LineSegmentROI(positions=[(0,0), (10,10)])
        self.view.addItem(self.roi)
        self.roi.sigRegionChanged.connect(self.roiChanged)

    def roiChanged(self, *args, plot_widget=None):
        # args is the line roi which is passed at the event call
        # Plots line scan below the ImageItem
        # only works for this single ROI
        data, coords = self.roi.getArrayRegion(self.image, self.imageItem, returnMappedCoords=True, axes=(1, 0))
        if data.ndim == 1:
            y_vals = data
        else:
            y_vals = data.mean(axis=self.axes['x'])  # Average along x-axis
        logger.debug(f'{data.shape=}')
        pl = plot_widget
        if pl is None:
            pl = self.ui.roiPlot
        pl = pl.plot()
        # Assumes a single ROI
        if len(self.roiCurves) == 0:
            self.roiCurves.append(pl)
        self.ui.roiPlot.setLabels(left='Intensity [a.u.]', bottom='Pixel')
        x_vals = np.arange(len(y_vals))  # Generate x values based on the length of y_vals
        # Overwrite existing plot by calling the listed object
        self.roiCurves[-1].setData(x_vals, y_vals)


class LineROICustom(pg.ROI):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.addScaleHandle([1, 1], [0, 0])
        self.addRotateHandle([0, 0], [0.5, 0.5])


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


class CustomGraphicsView(pg.GraphicsView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMenuEnabled(False)
        self.setMouseEnabled(False, False)


# Label slider
# adapted from https://gist.github.com/wiccy46/b7d8a1d57626a4ea40b19c5dbc5029ff
class QLabeledSlider(QWidget):
    def __init__(self, minimum, maximum, interval=1, orientation=Qt.Horizontal,
            labels=None, p0=0, parent=None):
        super(QLabeledSlider, self).__init__(parent=parent)

        levels=range(minimum, maximum + interval, interval)

        if labels is not None:
            if not isinstance(labels, (tuple, list)):
                raise Exception("<labels> is a list or tuple.")
            if len(labels) != len(levels):
                raise Exception("Size of <labels> doesn't match levels.")
            self.levels=list(zip(levels,labels))
        else:
            self.levels=list(zip(levels,map(str,levels)))

        if orientation==Qt.Horizontal:
            self.layout=QVBoxLayout(self)
        elif orientation==Qt.Vertical:
            self.layout=QHBoxLayout(self)
        else:
            raise Exception("<orientation> wrong.")

        # gives some space to print labels
        self.left_margin=10
        self.top_margin=10
        self.right_margin=10
        self.bottom_margin=10

        self.layout.setContentsMargins(self.left_margin,self.top_margin,
                self.right_margin,self.bottom_margin)

        self.sl=QSlider(orientation, self)
        self.sl.setMinimum(minimum)
        self.sl.setMaximum(maximum)
        self.sl.setValue(minimum)
        self.sl.setSliderPosition(p0)
        if orientation==Qt.Horizontal:
            self.sl.setTickPosition(QSlider.TicksBelow)
            self.sl.setMinimumWidth(300) # just to make it easier to read
        else:
            self.sl.setTickPosition(QSlider.TicksLeft)
            self.sl.setMinimumHeight(300) # just to make it easier to read
        self.sl.setTickInterval(interval)
        self.sl.setSingleStep(1)

        self.layout.addWidget(self.sl)

    def paintEvent(self, e):

        super(QLabeledSlider, self).paintEvent(e)
        style=self.sl.style()
        painter=QPainter(self)
        st_slider=QStyleOptionSlider()
        st_slider.initFrom(self.sl)
        st_slider.orientation=self.sl.orientation()

        length=style.pixelMetric(QStyle.PM_SliderLength, st_slider, self.sl)
        available=style.pixelMetric(QStyle.PM_SliderSpaceAvailable, st_slider, self.sl)

        for v, v_str in self.levels:

            # get the size of the label
            rect=painter.drawText(QRect(), Qt.TextDontPrint, v_str)

            if self.sl.orientation()==Qt.Horizontal:
                # I assume the offset is half the length of slider, therefore
                # + length//2
                x_loc=QStyle.sliderPositionFromValue(self.sl.minimum(),
                        self.sl.maximum(), v, available)+length//2

                # left bound of the text = center - half of text width + L_margin
                left=x_loc-rect.width()//2+self.left_margin
                bottom=self.rect().bottom()

                # enlarge margins if clipping
                if v==self.sl.minimum():
                    if left<=0:
                        self.left_margin=rect.width()//2-x_loc
                    if self.bottom_margin<=rect.height():
                        self.bottom_margin=rect.height()

                    self.layout.setContentsMargins(self.left_margin,
                            self.top_margin, self.right_margin,
                            self.bottom_margin)

                if v==self.sl.maximum() and rect.width()//2>=self.right_margin:
                    self.right_margin=rect.width()//2
                    self.layout.setContentsMargins(self.left_margin,
                            self.top_margin, self.right_margin,
                            self.bottom_margin)

            else:
                y_loc=QStyle.sliderPositionFromValue(self.sl.minimum(),
                        self.sl.maximum(), v, available, upsideDown=True)

                bottom=y_loc+length//2+rect.height()//2+self.top_margin-3
                # there is a 3 px offset that I can't attribute to any metric

                left=self.left_margin-rect.width()
                if left<=0:
                    self.left_margin=rect.width()+2
                    self.layout.setContentsMargins(self.left_margin,
                            self.top_margin, self.right_margin,
                            self.bottom_margin)

            pos=QPoint(left, bottom)
            painter.drawText(pos, v_str)

        return