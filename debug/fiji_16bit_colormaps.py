import tifffile

dpath = r"C:\Users\manue\OneDrive - uni-bielefeld.de\Master\GUI\Vpyqt demo\contents\test-1.tif"
# Load your 16-bit TIFF file
with tifffile.TiffFile(dpath) as tif:
    # Print full metadata dictionary
    print("\n=== TIFF TAGS ===")
    for page in tif.pages:
        print(page.tags)

    print("\n=== IMAGEJ METADATA ===")
    print(tif.imagej_metadata)


    print("\n=== DESCRIPTION TAG ===")
    print(tif.pages[0].description)
    print(type(tif.pages[0].description))

    print("\n=== SHAPE & INFO ===")
    print("Shape:", tif.series[0].shape)
    print("Axes:", tif.series[0].axes)

    # modify the metadata key 'spacing' to 0.5 to have a pixel distance of 'spacing' ['unit'] / per pixels
    tif.imagej_metadata['spacing'] = 0.5

    print(tif.imagej_metadata)

    # Save the modified metadata to a new file
    tifffile.imwrite("new_metadata.tif", tif.asarray(), imagej=True, metadata=tif.imagej_metadata)


# make a random 16 bit images of 3 channels and NxN pixels

import numpy as np
from contents.fiji_saver import FIJISaver

np.random.seed(0)
n_channels = 3
n_pixels = 512
image = np.random.randint(0, 65535, (n_channels, n_pixels, n_pixels), dtype=np.uint16)

lut1 = FIJISaver.create_lut_for_fiji((255, 0, 255))
lut2 = FIJISaver.create_lut_for_fiji((0, 255, 0))
lut3 = FIJISaver.create_lut_for_fiji((255, 255, 255))
luts = [lut1, lut2, lut3]


metadata = {'LUTs': luts,
 'Ranges': [(0, 65535)] * n_channels,
 'mode': 'composite', 'unit': '\\u00B5m', 'spacing': 0.5
 }
# Save the image with the luts
tifffile.imwrite("random_image.tif", image, imagej=True, metadata=metadata)
