"""Allow ``python -m hs_mosaic`` to launch the GUI."""
from hs_mosaic.app import main

if __name__ == "__main__":
    raise SystemExit(main())
