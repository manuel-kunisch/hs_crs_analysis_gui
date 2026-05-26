import logging

import pyqtgraph as pg

logger = logging.getLogger(__name__)

class ScaleBar(pg.ScaleBar):
    def __init__(self, view_box: pg.ViewBox, pixel_size: float , scale_bar_size=50, unit='µm', **kwargs):
        super().__init__(scale_bar_size, suffix=unit, **kwargs)
        self.unit = unit
        self.scale_bar_len = scale_bar_size
        self.pixel_size = pixel_size

        self.size = self.scale_bar_len / self.pixel_size
        self.setVisible(True)
        self.setParentItem(view_box)
        self.anchor((1, 1), (1, 1), offset=(-30, -30))

    def updateParent(self, new_parent):
        view = self.parentItem()
        if view is None:
            return
        # view.sigRangeChanged.connect(self.updateBar)

    def update_scale_bar_len(self, val: float):
        self.scale_bar_len = val
        logger.debug('Updated scale bar length to %s %s.', self.scale_bar_len, self.unit)
        self.update_scale_bar()

    def update_pixel_size(self, val: float):
        self.pixel_size = val
        logger.debug('Updated scale bar pixel size to %s.', self.pixel_size)
        self.update_scale_bar()

    def update_scale_bar(self):
        if not self.pixel_size:
            return # avoid division by zero
        len_scale = self.scale_bar_len
        self.size = len_scale / self.pixel_size     # length_pixel in number of pixels
        self.text.setText(f'{len_scale:.0f} {self.unit}')
        self.updateBar()
