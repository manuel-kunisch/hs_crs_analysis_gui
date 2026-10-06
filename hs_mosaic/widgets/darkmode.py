"""Backwards-compatible entry point for the application theme.

The actual design system lives in :mod:`hs_mosaic.widgets.theme`; this module
keeps the historical ``set_darkmode(app)`` name working.
"""
from PyQt5.QtWidgets import QApplication

from hs_mosaic.widgets.theme import apply_theme


def set_darkmode(app: QApplication):
    apply_theme(app)
