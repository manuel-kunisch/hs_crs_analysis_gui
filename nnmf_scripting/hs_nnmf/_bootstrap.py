"""Make ``hs_mosaic`` importable without installing it.

HS-MOSAIC is normally run from its source checkout rather than installed into
site-packages, so a script started from any other directory cannot import it.
This adds the checkout root to ``sys.path`` once, without touching the
HS-MOSAIC sources themselves.

Search order:

1. ``hs_mosaic`` is already importable -- do nothing
2. ``$HS_MOSAIC_ROOT`` (set this if the scripting folder was copied elsewhere)
3. the repository this package lives in (``<repo>/nnmf_scripting/hs_nnmf``)
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def ensure_hs_mosaic_importable() -> Path | None:
    """Return the checkout root that was added to ``sys.path``, or None."""
    if importlib.util.find_spec("hs_mosaic") is not None:
        return None

    candidates = []
    env_root = os.environ.get("HS_MOSAIC_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())
    # <repo>/nnmf_scripting/hs_nnmf/_bootstrap.py -> <repo>
    candidates.append(Path(__file__).resolve().parents[2])

    for candidate in candidates:
        if (candidate / "hs_mosaic" / "__init__.py").exists():
            sys.path.insert(0, str(candidate))
            return candidate

    raise ImportError(
        "Could not locate the HS-MOSAIC sources. Set HS_MOSAIC_ROOT to the "
        "hs_crs_analysis_gui checkout (the folder containing 'hs_mosaic'), "
        f"or run from that folder. Looked in: {[str(c) for c in candidates]}"
    )
