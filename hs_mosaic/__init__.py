"""HS-MOSAIC — Hyperspectral Multivariate Optical Spectral Analysis and Imaging Components.

A GUI-driven seeded NNMF / NNLS pipeline for hyperspectral and multispectral
microscopy data.

Public entry point::

    from hs_mosaic import main
    main()

or, after ``pip install hs-mosaic``::

    $ hs-mosaic
"""

from importlib import metadata as _metadata

try:
    __version__ = _metadata.version("hs-mosaic")
except _metadata.PackageNotFoundError:  # editable install before pip install -e .
    __version__ = "0.0.0+local"

from hs_mosaic.app import main

__all__ = ["main", "__version__"]
