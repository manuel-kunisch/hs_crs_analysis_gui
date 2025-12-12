from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence, Callable, Optional, Dict, Tuple, Union
import re

import matplotlib.pyplot as plt
import numpy as np
import tifffile as tiff

from cross_correlate import stitch_corr


@dataclass
class CrossCorrelationStitcher:
    """
    Small wrapper around your existing `stitch_corr` pipeline,
    with all tuning knobs exposed as attributes – ideal for a GUI.

    Typical GUI usage
    -----------------
    stitcher = CrossCorrelationStitcher()
    stitcher.overlap_row = ui.overlap_row_spin.value()
    stitcher.overlap_col = ui.overlap_col_spin.value()
    stitcher.sigma_interval = ui.sigma_spin.value()
    stitcher.mode = "sigma mean"
    stitcher.display_channel = ui.channel_spin.value()
    stitcher.plot = ui.debug_plot_checkbox.isChecked()

    stitched = stitcher.stitch_folder(folder_path)
    """

    # --- stitching parameters (bind directly to widgets) ---
    overlap_row: int = 90
    overlap_col: int = 90
    sigma_interval: float = 1.0
    channel_list: Optional[Sequence[int]] = None
    mode: str = "sigma mean"          # e.g. "normal", "mean", "sigma mean"
    display_channel: int = 0          # which channel to show if plot=True
    vmax: float = 2500.0              # only used when plot=True
    plot: bool = False
    scan_x_direction: str = "left"  # or "right to left"
    binning: int = 2  # binning factor for raw data before stitching

    # --- filename parsing (x/y indices from filenames) ---
    # default matches e.g. "tile_x3_y7.tif", "stack-X-1_Y-2.tif", ...
    filename_regex: str = field(
        default=r".*[_-]x(?P<x>-?\d+)[_-]y(?P<y>-?\d+).*",
        repr=False,
    )
    filename_regex_flags: int = field(
        default=re.IGNORECASE,
        repr=False,
    )

    _compiled_regex: re.Pattern = field(init=False, repr=False)

    def __init__(self):
        self._added_channel_dim = None

    def __post_init__(self) -> None:
        self._compiled_regex = re.compile(self.filename_regex,
                                          self.filename_regex_flags)

    # ------------------------------------------------------------------
    #  Filename parsing
    # ------------------------------------------------------------------
    def set_filename_regex(self, pattern: str, flags: Optional[int] = None) -> None:
        """
        Change the pattern used to extract (x, y) from filenames.

        Parameters
        ----------
        pattern : str
            Regex with named groups "x" and "y".
            Examples
            --------
            # "pos_003_y005_x007.tif"
            r"pos_(?P<y>\\d+)_(?P<x>\\d+)\\.tif"

            # "scanX-1_Y-2_ch0.tif"
            r".*X(?P<x>-?\\d+).*Y(?P<y>-?\\d+).*"
        flags : int, optional
            re.IGNORECASE, re.ASCII, ... If None, the current flags are kept.
        """
        self.filename_regex = pattern
        if flags is not None:
            self.filename_regex_flags = flags
        self._compiled_regex = re.compile(self.filename_regex,
                                          self.filename_regex_flags)

    def parse_xy_from_name(self, path: Union[str, Path]) -> Tuple[int, int] or Tuple[None, None]:
        """
        Extract (x, y) from a filename using the configured regex.

        Returns none if no match is found.
        """
        name = Path(path).name
        m = self._compiled_regex.search(name)
        if not m:
            return None, None
        return int(m.group("x")), int(m.group("y"))

    # ------------------------------------------------------------------
    #  Dataset creation
    # ------------------------------------------------------------------
    def build_dataset_from_files(
        self,
        files: Sequence[Union[str, Path]],
        loader: Callable[[str], np.ndarray] = tiff.imread,
    ) -> Tuple[Dict[int, Dict[int, Dict[str, np.ndarray]]], list[int], list[int]]:
        """
        Convert a flat list of image files into the (data, lookup_x, lookup_y)
        structure expected by your `stitch_corr` function.

        Parameters
        ----------
        files : sequence of paths
            Every filename must contain x and y indices that the regex can extract.
        loader : callable
            Function that receives a string path and returns a 3D numpy array.

        Returns
        -------
        data : dict
            {x: {y: {"img": np.ndarray}}}
        lookup_x : list[int]
        lookup_y : list[int]
        """
        data: Dict[int, Dict[int, Dict[str, np.ndarray]]] = {}
        xs: set[int] = set()
        ys: set[int] = set()

        for f in files:
            x, y = self.parse_xy_from_name(f)
            if x is None or y is None:
                print(f"Warning: could not parse x/y from filename '{f}', skipping.")
                continue
            img = loader(str(f))

            # reshape to format (y, x, c) if needed
            if img.ndim == 2:
                img = img[:, :, np.newaxis]
                self._added_channel_dim = True
            elif img.ndim == 3:
                img = np.moveaxis(img, 0, 2)  # assume (c, y, x) → (y, x, c)
                self._added_channel_dim = False
            else:
                raise ValueError(
                    f"Loaded image from '{f}' has invalid number of dimensions: {img.ndim}"
                )

            Y, X, C = img.shape
            N = self.binning

            print(f"Binning tiles by factor {N}.")

            if Y % N != 0 or X % N != 0:
                # Handle cases where dimensions are not perfectly divisible
                # Option 1: Raise an error
                # raise ValueError(
                #     f"Image dimensions ({Y}x{X}) are not divisible by binning factor {N}"
                # )
                # Option 2: Crop to be divisible (recommended for robustness)
                Y_new = Y - (Y % N)
                X_new = X - (X % N)
                img = img[:Y_new, :X_new, :]
                Y, X = Y_new, X_new  # Update Y and X
            # bin the image
            # Reshape the image to group pixels for averaging (Y, X, C)
            # The new shape will be (Y/N, N, X/N, N, C)
            # E.g., for 4x4 binning: (Y/4, 4, X/4, 4, C)
            # We then average over the second (N) and fourth (N) axes.
            img_binned = img.reshape(Y // N, N, X // N, N, C).mean(axis=(1, 3))

            # Replace the original image with the binned image
            img = img_binned

            # DEBUG
            xs.add(x)
            ys.add(y)
            data.setdefault(x, {})[y] = {"img": img}

        lookup_x = sorted(xs)
        lookup_y = sorted(ys)
        return data, lookup_x, lookup_y

    # ------------------------------------------------------------------
    #  Stitching
    # ------------------------------------------------------------------
    def stitch(
        self,
        data: Dict[int, Dict[int, Dict[str, np.ndarray]]],
        lookup_x: Sequence[int],
        lookup_y: Sequence[int],
    ) -> np.ndarray:
        """
        Run the `stitch_corr` with the current configuration.
        """
        print('Using scan x direction:', self.scan_x_direction)
        return stitch_corr(
            data=data,
            lookup_x=list(lookup_x),
            lookup_y=list(lookup_y),
            overlap_row=self.overlap_row,
            overlap_col=self.overlap_col,
            sigma_interval=self.sigma_interval,
            channel_list=list(self.channel_list)
            if self.channel_list is not None
            else None,
            scan_x_direction=self.scan_x_direction,
            mode=self.mode,
            ch=self.display_channel,
            vmax_var=self.vmax,
            _plot=self.plot,
        )

    def stitch_from_files(
        self,
        files: Sequence[Union[str, Path]],
        loader: Callable[[str], np.ndarray] = tiff.imread,
    ) -> np.ndarray:
        """
        One-shot convenience method: parse filenames, load images, stitch.

        This is the method you probably want to call from a QThread in the GUI.
        """
        data, lookup_x, lookup_y = self.build_dataset_from_files(files, loader)
        return self.stitch(data, lookup_x, lookup_y)

    def stitch_folder(
        self,
        folder: Union[str, Path],
        pattern: str = "*.tif",
        loader: Callable[[str], np.ndarray] = tiff.imread,
    ) -> np.ndarray:
        """
        Convenience wrapper: find all matching files in a folder and stitch.

        Parameters
        ----------
        folder : str or Path
            Base folder containing tiles.
        pattern : str
            Glob pattern, default "*.tif".
        """
        folder = Path(folder)
        file_list = sorted(folder.glob(pattern))
        if not file_list:
            raise FileNotFoundError(
                f"No files matching pattern '{pattern}' in '{folder}'"
            )
        stitch_result = self.stitch_from_files(file_list, loader)
        if self._added_channel_dim:
            # delete the final channel dimension we added
            return stitch_result[:, :, 0]

        stitch_result = np.moveaxis(stitch_result, 2, 0)  # (y, x, c) -> (c, y, x)
        return stitch_result


if __name__ == "__main__":
    # Simple test / demo
    stitcher = CrossCorrelationStitcher()
    stitcher.binning = 1
    stitcher.sigma_interval = 2.0
    stitcher.overlap_row = 100 // stitcher.binning
    stitcher.overlap_col = 100 // stitcher.binning
    stitcher.mode = "sigma"    # sigma mean means outlier correction for calculation of shifts and averaging over all channels
    stitcher.display_channel = 0

    stitcher.set_filename_regex(
        r".*xyz-Table\[(?P<y>\d+)\]\s*-\s*xyz-Table\[(?P<x>\d+)\].*",
        flags=re.IGNORECASE,
    )
    """
    General recipe for custom regex for arbitrary x/y name encodings.
    Example for filenames like:
        [[ _C5.ome) xyz-Table[3] - xyz-Table[7].tif
    
    How it works:
        .* → ignore everything before
        
        xyz-Table\[(?P<x>\d+)\] → first number in brackets → named group x
        \s*-\s* → the - between the two table entries
        
        xyz-Table\[(?P<y>\d+)\] → second number in brackets → named group y
        .* → ignore the rest (]] _C5.ome)
    """

    stitcher.plot = False
    stitcher.scan_x_direction = "right"  # or "right to left"
    stitcher.channel_list = [40]  # only use channel 20 for stitching cross-correlation

    folder = '/Users/mkunisch/Desktop/Herzgewebe Tiffs/2025_11_04 thg_autofluorescence/mosaic split/thg'
    stitched = stitcher.stitch_folder(folder, pattern="*.tif")
    plt.imshow(stitched[10], cmap="viridis")
    plt.show()
