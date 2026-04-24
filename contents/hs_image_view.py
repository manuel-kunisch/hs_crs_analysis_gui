import logging

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, QtWidgets, QtGui
from pyqtgraph import VTickGroup

from contents.custom_pyqt_objects import ImageViewLineRoi

logger = logging.getLogger('HS Image Viewer')


class RamanImageView(ImageViewLineRoi):
    playback_state_changed = QtCore.pyqtSignal(bool)

    #FIXME: Make this a ROI plot which shows the mean intensity over different Raman shifts
    """
    modified ImageView object with additional features

    changed functionalities:
    - removed scalable frame composite_image (roiPlot)
    - added wavenumbers to roiPlot


    added features:
    - A button auto scales the image levels
    - S button auto ranges the image pan
    """
    def __init__(self, *args, roi_plot_widget=None, autoplay=True,
                 max_ticks = 10, **kwargs):
        super().__init__(*args, **kwargs)
        # self.roi = pg.LineSegmentROI([(0, 0), (50, 50)])
        self.max_ticks = max_ticks
        self.unit = "cm⁻¹"
        self.fps = 10.0
        self.autoplay = False
        self._play_once_on_next_image = bool(autoplay)
        self._reset_to_start_on_play_once = bool(autoplay)
        self._playback_tick_in_progress = False
        self._suppress_manual_stop = False
        # create vertical ticks in the frame graph
        self.frameTicks = VTickGroup(yrange=[0.8, 1], pen=0.4)
        # make frame plot unscalable
        # ui.roiPlot is the PlotItem() for the frames
        self.ui.roiBtn.setText("Current Frame Linescan")
        self.ui.roiPlot.addItem(self.frameTicks, ignoreBounds=False)
        self.ui.roiBtn.setChecked(True)
        # enlarge the ROI plot
        self.ui.roiPlot.setMinimumSize(QtCore.QSize(0, 60))

        self.playLoop = True  # Initialize play loop flag

        self.ui.roiPlot.getAxis('bottom').setLabel(r'Raman Shift [1/cm]')
        # self.ui.roiPlot.setMenuEnabled(False)

        # Hide AutoScale Button of Frame Scale
        self.ui.roiPlot.hideButtons()
        self.frame_label = pg.TextItem(text='', color=(255, 255, 255))
        self.addItem(self.frame_label)
        self.frame_label.setPos(10, 1)
        self.linescan = []
        self.wavenumber = None
        self.axis_labels = None
        self.roiPlotWidget = roi_plot_widget

    def set_spectral_units(self, unit: str):
        unit = "nm" if (unit or "").strip().lower() == "nm" else "cm⁻¹"
        if self.axis_labels is not None:
            self.ui.roiPlot.getAxis('bottom').setLabel('Channels')
        elif unit == "nm":
            self.ui.roiPlot.getAxis('bottom').setLabel('Wavelength [nm]')
        else:
            self.ui.roiPlot.getAxis('bottom').setLabel('Raman Shift [1/cm]')
        self.unit = unit
        self.updateImage()

    def set_axis_labels(self, labels):
        self.axis_labels = None if labels is None else [str(label) for label in labels]
        if self.axis_labels is None:
            self.set_spectral_units(self.unit)
        else:
            self.ui.roiPlot.getAxis('bottom').setLabel('Channels')
            self.update_timeline_ticks()
            self.updateImage()

    def _capture_histogram_state(self):
        try:
            return self.getHistogramWidget().saveState()
        except Exception:
            return None

    def _restore_histogram_state(self, state):
        if state is None:
            return
        try:
            self.getHistogramWidget().restoreState(state)
        except Exception:
            logger.debug('Could not restore RamanImageView histogram state.', exc_info=True)

    def updateImage(self, show_frame_label=False, **kwargs):
        super().updateImage(**kwargs)
        frame = self.currentIndex
        if show_frame_label:
            self.frame_label.setText(f'Frame: {frame}')
        if self.view is not None and self.axis_labels is not None and 0 <= frame < len(self.axis_labels):
            self.view.setTitle(f'Frame: {frame} @ {self.axis_labels[frame]}')
        elif self.view is not None and self.wavenumber is not None and 0 <= frame < len(self.wavenumber):
            self.view.setTitle(f'Frame: {frame} @ {self.wavenumber[self.currentIndex]:.1f} {self.unit}')

    def roiChanged(self, *args, plot_widget=None):
        # args is the line roi which is passed at the event call
        data_cur_im, coords = self.roi.getArrayRegion(self.image[self.currentIndex, ...], self.imageItem, axes=(1, 0), returnMappedCoords=True)
        y_vals = data_cur_im

        pl = plot_widget
        if pl is None:
            plot_widget = self.roiPlotWidget
            pl = self.roiPlotWidget
        pl = pl.plot()
        pl.clear()
        # Assumes a single ROI
        if len(self.linescan) == 0:
            self.linescan.append(pl)
            self.roiCurves.append(pl)
        plot_widget.setLabels(left='Intensity [a.u.]', bottom='Pixel')
        x_vals = np.arange(len(y_vals))  # Generate x values based on the length of y_vals
        # Overwrite existing plot by calling the listed object
        self.linescan[-1].setData(x_vals, y_vals)

    def roiClicked(self):
        showRoiPlot = False
        if self.ui.roiBtn.isChecked():
            showRoiPlot = True
            self.roi.show()
            self.ui.roiPlot.setMouseEnabled(True, True)
            # self.ui.splitter.setSizes([int(self.height() * 0.6), int(self.height() * 0.4)])
            # self.ui.splitter.handle(1).setEnabled(True)
            self.roiChanged()
            for c in self.roiCurves:
                c.show()
            # self.ui.roiPlot.showAxis('left')
        else:
            self.roi.hide()
            self.ui.roiPlot.setMouseEnabled(False, False)
            for c in self.roiCurves:
                c.hide()
            self.ui.roiPlot.hideAxis('left')
        # Overwrite adjustment of Timeline
        """
         if self.hasTimeAxis():
            showRoiPlot = True
            mn = self.tVals.min()
            mx = self.tVals.max()
            self.ui.roiPlot.setXRange(mn, mx, padding=0.01)
            self.timeLine.show()
            self.timeLine.setBounds([mn, mx])
            if not self.ui.roiBtn.isChecked():
                self.ui.splitter.setSizes([self.height() - 35, 35])
                self.ui.splitter.handle(1).setEnabled(False)
        else:
            self.timeLine.hide()
        self.ui.roiPlot.setVisible(showRoiPlot)
        """
        pass

    def stopAutoPlay(self):
        self.set_playing(False)

    def is_playing(self) -> bool:
        return self.playTimer.isActive()

    def request_single_autoplay_cycle(self, reset_to_start: bool = True):
        self._play_once_on_next_image = True
        self._reset_to_start_on_play_once = bool(reset_to_start)

    def set_playing(self, playing: bool):
        playing = bool(playing)
        was_playing = self.is_playing()
        self.autoplay = playing

        if playing and self.image is not None and self.nframes() > 1:
            interval_ms = max(1, int(round(1000.0 / self.fps)))
            self.playTimer.start(interval_ms)
        else:
            self.playTimer.stop()
            if playing:
                self.autoplay = False
                playing = False

        if was_playing != playing:
            logger.info('Auto Play %s', 'Started' if playing else 'Paused')
            self.playback_state_changed.emit(playing)

    def set_playback_fps(self, fps: float):
        self.fps = max(0.1, float(fps))
        if self.autoplay:
            self.set_playing(True)

    def togglePause(self):
        self.set_playing(not self.is_playing())

    def play(self, fps=None):
        logger.debug('play(): Keep playing')
        if fps is not None:
            self.fps = max(0.1, float(fps))
        self.set_playing(True)

    def timeout(self):
        if self.image is None or self.nframes() <= 1:
            self.set_playing(False)
            return

        next_index = self.currentIndex + 1
        if next_index >= self.nframes():
            if not self.playLoop:
                # after a single cycle set the image to the center-most frame
                center_index = self.nframes() // 2
                self._playback_tick_in_progress = True
                self._suppress_manual_stop = True
                try:
                    self.setCurrentIndex(center_index)
                finally:
                    self._suppress_manual_stop = False
                    self._playback_tick_in_progress = False
                self.playLoop = True
                self.set_playing(False)
                return
            next_index = 0

        self._playback_tick_in_progress = True
        self._suppress_manual_stop = True
        try:
            self.setCurrentIndex(next_index)
        finally:
            self._suppress_manual_stop = False
            self._playback_tick_in_progress = False

    def timeLineChanged(self):
        histogram_state = self._capture_histogram_state()
        super().timeLineChanged()
        self._restore_histogram_state(histogram_state)
        logger.debug('timeLineChanged(): Time Line call')
        self.roiChanged()
        if self.autoplay and not self._playback_tick_in_progress and not self._suppress_manual_stop:
            self.set_playing(False)

    def hideTimeLine(self):
        self.ui.roiPlot.hideAxis('bottom')
        self.ui.roiPlot.hideAxis('left')
        self.ui.roiPlot.hideButtons()
        self.ui.roiPlot.hide()
        self.ui.roiPlot.setMouseEnabled(False, False)

    def setImage(self, *args, keep_viewbox=False, **kwargs):
        # keep the current frame index
        current_frame = self.currentIndex
        logger.debug('setImage method called')
        histogram_state = self._capture_histogram_state() if keep_viewbox else None
        if keep_viewbox:
            view = self.getView()
            view_range = view.viewRange()
            kwargs.setdefault('autoLevels', False)
            kwargs.setdefault('autoHistogramRange', False)
        self._suppress_manual_stop = True
        try:
            super().setImage(*args, axes={'x': 2, 'y': 1, 't': 0}, **kwargs)
        finally:
            self._suppress_manual_stop = False
        if keep_viewbox:
            # Restore the previous view settings
            view.setXRange(view_range[0][0] , view_range[0][1] )
            view.setYRange(view_range[1][0] , view_range[1][1] )
        # set the current frame index to the previous value if possible
        if current_frame < self.nframes():
            self._suppress_manual_stop = True
            try:
                self.setCurrentIndex(current_frame)
            finally:
                self._suppress_manual_stop = False
        play_once = self._play_once_on_next_image and self.nframes() > 1
        self._play_once_on_next_image = False
        if play_once:
            if self._reset_to_start_on_play_once:
                self._suppress_manual_stop = True
                try:
                    self.setCurrentIndex(0)
                finally:
                    self._suppress_manual_stop = False
            self.playLoop = False
            self.play(self.fps)
        # Start user-controlled looping autoplay
        elif self.autoplay:
            self.playLoop = True
            self.play(self.fps)
        self.update_timeline_ticks()
        self._restore_histogram_state(histogram_state)

    def update_timeline_ticks(self):
        if self.axis_labels is not None:
            bottom_axis = self.ui.roiPlot.getAxis('bottom')
            step = max(1, len(self.axis_labels) // max(1, self.max_ticks - 2))
            tick_values = [(i, label) for i, label in enumerate(self.axis_labels) if i % step == 0]
            if tick_values:
                bottom_axis.setTicks([tick_values])
            return

        if self.wavenumber is None:
            return
        bottom_axis = self.ui.roiPlot.getAxis('bottom')
        step = max(1, len(self.wavenumber) // (self.max_ticks - 2))

        tick_values = [(i, f'{v:.0f}') for i, v in enumerate(self.wavenumber) if i % step == 0]
        if not tick_values:
            return
        bottom_axis.setTicks([tick_values])
        # Force an update of the GUI
        # self.ui.roiPlot.getViewBox().autoRange()

    def keyPressEvent(self, ev):
        if ev.key() == QtCore.Qt.Key.Key_Space:
            self.togglePause()
            ev.accept()
        elif ev.key() == QtCore.Qt.Key.Key_A:
            self.autoLevels()
        elif ev.key() == QtCore.Qt.Key.Key_S:
            self.autoRange()
        else:
            # Call the predefined key press events
            super().keyPressEvent(ev)


class ColorButton(QtWidgets.QPushButton):
    def __init__(self, color):
        super().__init__()
        self.color = color
        self.setStyleSheet(f"background-color: {color.name()}")
        self.clicked.connect(self.pick_color)

    def pick_color(self):
        new_color = QtWidgets.QColorDialog.getColor(self.color)
        if new_color.isValid():
            self.color = new_color
            self.setStyleSheet(f"background-color: {new_color.name()}")
            self.color_changed.emit(new_color)

    def setColor(self, color: QtGui.QColor):
        self.color = color
        self.setStyleSheet(f"background-color: {color.name()}")

    color_changed = QtCore.pyqtSignal(QtGui.QColor)


class ROITableDelegate(QtWidgets.QItemDelegate):
    def createEditor(self, parent, option, index):
        if index.column() == 3:
            combo_box = QtWidgets.QComboBox(parent)
            combo_box.addItem("LineROI")
            combo_box.addItem("RectROI")
            return combo_box
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        if index.column() == 3:
            text = index.data()
            combo_box = editor
            combo_box.setCurrentText(text)
        else:
            super().setEditorData(editor, index)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)

    def setModelData(self, editor, model, index):
        if index.column() == 3:
            combo_box = editor
            roi_type = combo_box.currentText()
            model.setData(index, roi_type)
        else:
            super().setModelData(editor, model, index)
