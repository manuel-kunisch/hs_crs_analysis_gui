"""Regression tests for the v0.9.9 GUI bugfixes.

Covers the pixel-size / field-of-view calibration fields, which used to abort
the whole application: the manager parsed every keystroke with a bare
``float(text)`` inside a Qt slot (empty field -> ValueError -> PyQt5 qFatal),
formatting the FOV with no image loaded raised a TypeError the same way, and
the field being edited was rewritten to four decimals under the cursor.

Run headless:  QT_QPA_PLATFORM=offscreen python -m pytest tests -q
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets  # noqa: E402

from hs_mosaic.widgets.physical_units_manager import (  # noqa: E402
    PhysicalUnitsManager,
    parse_positive_float,
)


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


# ── lenient parsing ──────────────────────────────────────────────────────────

def test_parse_positive_float_accepts_plain_numbers():
    assert parse_positive_float("0.28") == pytest.approx(0.28)
    assert parse_positive_float(" 2 ") == pytest.approx(2.0)
    assert parse_positive_float("1e-3") == pytest.approx(1e-3)


def test_parse_positive_float_rejects_partial_and_invalid_input():
    for text in ("", " ", "-", ".", "abc", "1,5", "0", "-1", "inf", "nan", None):
        assert parse_positive_float(text) is None, repr(text)


# ── the crash paths ──────────────────────────────────────────────────────────

def test_pixel_size_typing_without_image_does_not_raise(qapp):
    manager = PhysicalUnitsManager()
    field = manager.widget.pixel_size_input
    # Clearing and retyping used to raise ValueError (empty) inside the slot,
    # and a valid value with no image loaded raised TypeError formatting the
    # (None, None) FOV. Both aborted the application.
    for text in ("", "0", "0.", "0.5", "", "-3", "2"):
        field.setText(text)
    assert manager.pixel_size == pytest.approx(2.0)  # last valid value wins
    assert manager.fov == (None, None)  # still no image, no fake FOV


def test_pixel_size_edits_are_not_rewritten_and_update_fov(qapp):
    manager = PhysicalUnitsManager()
    manager.update_image_dimensions((100, 200))  # (height, width)
    field = manager.widget.pixel_size_input

    field.setText("2")
    # The field being edited keeps the user's text (no ".0000" reformat)...
    assert field.text() == "2"
    # ...while the derived values follow: FOV = (width*px, height*px).
    assert manager.pixel_size == pytest.approx(2.0)
    assert manager.fov == (pytest.approx(400.0), pytest.approx(200.0))
    assert manager.widget.fov_input.text() == "400.00, 200.00"

    # Half-typed input in between keeps the last valid state.
    field.setText("2.")
    assert manager.pixel_size == pytest.approx(2.0)


def test_fov_edits_update_pixel_size_and_survive_partial_input(qapp):
    manager = PhysicalUnitsManager()
    manager.update_image_dimensions((100, 200))
    fov_field = manager.widget.fov_input

    for text in ("", "100", "100,", "100, 50"):
        fov_field.setText(text)  # partial inputs used to log errors / crash
    assert manager.pixel_size == pytest.approx(0.5)  # 100 / 200 columns
    assert manager.widget.pixel_size_input.text() == "0.5000"

    # The pixel-size field must still be live afterwards (the old code could
    # leave its signals blocked for good on an early return).
    manager.widget.pixel_size_input.setText("1")
    assert manager.pixel_size == pytest.approx(1.0)
