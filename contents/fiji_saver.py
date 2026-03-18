import logging
import os
import struct

import numpy as np
import tifffile as tiff
from numpy._typing import ArrayLike

logger = logging.getLogger(__name__)

class FIJISaver:
    def __init__(self, image, path, colors: list[ArrayLike] = None, ranges = None, dtype=np.uint16):
        self.path = path
        self.colormaps = colors
        self.dtype: np.dtype = dtype   # luts can only be directly applied in 8 bit images
        self.ranges = ranges
        self.update_image(image)
        self.labels = {}
        self.pixel_size_um = 1.  # default pixel size in micrometers
        if colors is None:
            self.colormaps = [(255, 0, 255), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 0), (0, 255, 255)]

    def save_composite_image(self):
        colors = []
        n_colors = int(self.image.shape[0])

        # Default to min/max values if not set

        if self.ranges is None:
            max_val = np.iinfo(self.dtype).max
            self.ranges = [(0, max_val)] * n_colors
        elif len(self.ranges) != n_colors:
            raise ValueError('Number of ranges must match number of channels')


        for i in range(n_colors):
            colors.append(self.create_lut_for_fiji(self.colormaps[i % len(self.colormaps)]))

        # flatten the ranges to a single tuple
        tuple_ranges = tuple(val for r in self.ranges for val in r)

        logger.debug('Writing FIJI channel ranges: %s', tuple_ranges)

        # old variant using extratags
        """
        flat_ranges = [val for r in self.ranges for val in
                      r]  # Flatten [(min1, max1), (min2, max2)] → [min1, max1, min2, max2]
        ijtags = self.imagej_metadata_tags({'LUTs': colors, 'Ranges': flat_ranges}, '>')
        # passing LUTs is not really easy. The LUTs are stored in the metadata as a list of 3 numpy arrays.
        # IJMetadata contains application internal metadata in a binary format. The color information is in the luts metadata
        tiff.imwrite(f'{self.path}', self.image, byteorder='>', imagej=True,
                     metadata={'mode': 'composite'}, extratags=ijtags)
        """
        labels = [str(self.labels.get(i, f'Component {i}')) for i in range(n_colors)]
        metadata = {'LUTs': colors,
                    'Ranges': tuple_ranges,
                    'Labels': labels,
                    'mode': 'composite', 'unit': '\\u00B5m'
         }
        res = 1/self.pixel_size_um
        tiff.imwrite(f'{self.path}', self.image, imagej=True, metadata=metadata, resolution=(res, res))
        logger.info(f'Image saved to {self.path}')

    def update_image(self, image):
        self.image = image
        if self.image is not None:
            # convert to uint8 for proper LUT handling
            self.image = self.normalize_to_dtype(self.image, self.dtype)

    @staticmethod
    def create_lut_for_fiji(lut_color: ArrayLike):
        # LUTs are always 8-bit. Images can be 16-bit and the scale must be adjusted accordingly in the metadata
        r, g, b = lut_color

        lut_dtype = np.uint8
        n_vals = np.iinfo(lut_dtype).max + 1
        color = np.zeros((3, n_vals), dtype=lut_dtype)

        color[0] = np.linspace(0, r, n_vals, dtype=lut_dtype)
        color[1] = np.linspace(0, g, n_vals, dtype=lut_dtype)
        color[2] = np.linspace(0, b, n_vals, dtype=lut_dtype)
        return color

    @staticmethod
    def normalize_to_dtype(image: np.ndarray, dtype:np.dtype = np.uint8):
        """ Normalize a 16-bit image to 8-bit for proper LUT handling. """
        if image.dtype == dtype:
            return image
        max_val = np.iinfo(dtype).max
        return ((image - image.min()) / (image.max() - image.min()) * max_val).astype(dtype)


    @staticmethod
    def imagej_metadata_tags(metadata, byteorder):
        """Return IJMetadata and IJMetadataByteCounts tags from metadata dict.

        The tags can be passed to the TiffWriter.save function as extratags.

        """
        header = [{'>': b'IJIJ', '<': b'JIJI'}[byteorder]]
        bytecounts = [0]
        body = []

        def writestring(data, byteorder):
            return data.encode('utf-16' + {'>': 'be', '<': 'le'}[byteorder])

        def writedoubles(data, byteorder):
            return struct.pack(byteorder + ('d' * len(data)), *data)

        def writebytes(data, byteorder):
            return data.tobytes()

        metadata_types = (
            ('Info', b'info', 1, writestring),
            ('Labels', b'labl', None, writestring),
            ('Ranges', b'rang', 1, writedoubles),
            ('LUTs', b'luts', None, writebytes),
            ('Plot', b'plot', 1, writebytes),
            ('ROI', b'roi ', 1, writebytes),
            ('Overlays', b'over', None, writebytes))

        for key, mtype, count, func in metadata_types:
            if key not in metadata:
                continue
            if byteorder == '<':
                mtype = mtype[::-1]
            values = metadata[key]
            if count is None:
                count = len(values)
            else:
                values = [values]
            header.append(mtype + struct.pack(byteorder + 'I', count))
            for value in values:
                data = func(value, byteorder)
                body.append(data)
                bytecounts.append(len(data))

        body = b''.join(body)
        header = b''.join(header)
        data = header + body
        bytecounts[0] = len(header)
        bytecounts = struct.pack(byteorder + ('I' * len(bytecounts)), *bytecounts)
        return ((50839, 'B', len(data), data, True),
                (50838, 'I', len(bytecounts) // 4, bytecounts, True))


if __name__ == '__main__':
    # Create a dummy 3-channel image stack (C, H, W)
    # image = np.random.randint(0, 255, (3, 512, 512)).astype(np.uint8)

    image = tiff.imread('../result.tif')
    path = os.path.join(os.getcwd(), 'test.tif')
    fiji_saver = FIJISaver(image, path)
    # Define slider min/max values for each channel
    # ranges = [(0, 100), (0, 255), (255, 255)]  # (min, max) for each channel
    # fiji_saver.ranges = ranges
    fiji_saver.save_composite_image()
