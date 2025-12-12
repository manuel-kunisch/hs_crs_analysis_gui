from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence, Callable, Optional, Dict, Tuple, Union
import re

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

    def parse_xy_from_name(self, path: Union[str, Path]) -> Tuple[int, int]:
        """
        Extract (x, y) from a filename using the configured regex.

        Raises ValueError if the pattern does not match.
        """
        name = Path(path).name
        m = self._compiled_regex.search(name)
        if not m:
            raise ValueError(
                f"Could not extract (x, y) from filename '{name}' "
                f"using pattern '{self.filename_regex}'"
            )
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
            img = loader(str(f))

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
        Run the real `stitch_corr` with the current configuration.
        """
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
        return self.stitch_from_files(file_list, loader)
