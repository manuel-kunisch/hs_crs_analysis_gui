"""Component color management with named, color-blind-aware palettes.

Three named palettes are provided out of the box:

* ``okabe_ito`` (default) — the Okabe-Ito 8-colour qualitative palette,
  designed for protanopia and deuteranopia. Recommended for publication
  figures (Wong, *Nat. Methods* **8**, 441, 2011).
* ``high_contrast`` — magenta-green-cyan-led palette optimised for additive
  composite display on dark backgrounds. The magenta + green pair is the
  standard colour-blind-friendly alternative to red + green in
  multi-channel fluorescence microscopy.
* ``classic_rgb`` — the legacy saturated RGB cycle that HS-MOSAIC shipped
  before v0.9.3. Kept for backwards compatibility with users who expect
  component 1 = red, 2 = green, 3 = blue.

The palette is the *initial* colour assignment for new components. Per-component
choices made through the GUI colour pickers (or loaded from a ``.preset``) take
precedence and are not overridden when the palette is switched.
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QComboBox, QLabel, QWidget


# Named palette definitions. Each entry is a list of QColor specs as
# hex strings, kept hex-only for readability and for round-tripping into
# JSON presets.
PALETTES: dict[str, list[str]] = {
    # Okabe & Ito 8-colour palette — color-blind safe, scientific default.
    # Source: Okabe, M. & Ito, K. "Color Universal Design (CUD)" (2008);
    # popularised by Wong, B. "Color blindness." Nat. Methods 8, 441 (2011).
    "okabe_ito": [
        "#E69F00",   # Orange
        "#56B4E9",   # Sky blue
        "#009E73",   # Bluish green
        "#F0E442",   # Yellow
        "#0072B2",   # Blue
        "#D55E00",   # Vermillion
        "#CC79A7",   # Reddish purple
        "#000000",   # Black
    ],
    # Legacy palette shipped before v0.9.3. Kept for backwards compatibility.
    "classic_rgb": [
        "#FF0000",   # Red
        "#00FF00",   # Green
        "#0000FF",   # Blue
        "#FFFF00",   # Yellow
        "#00FFFF",   # Cyan
        "#FF00FF",   # Magenta
        "#FF8000",   # Orange
        "#8000FF",   # Purple
    ],
    # High-contrast palette hand-tuned for additive composite display on
    # dark backgrounds. Built around the magenta–green–cyan trio, which is
    # the standard colour-blind-friendly alternative to red–green–blue in
    # multi-channel fluorescence microscopy (magenta + green co-localise to
    # white, the classic two-colour overlap signal). Brighter overall than
    # Okabe-Ito, at the cost of being slightly less "scientifically neutral".
    "high_contrast": [
        "#FF00FF",   # Magenta             — purple-pink primary
        "#00FF00",   # Pure green          — clearly separated from any blue/cyan
        "#00B0FF",   # Sky blue            — distinctly bluer than green
        "#FFAA00",   # Amber               — warm orange
        "#FFFF00",   # Yellow              — peak luminance
        "#FF80C0",   # Pink                — light warm magenta variant
        "#9966FF",   # Purple              — cool, distinct from both magenta and blue
        "#FF6040",   # Coral               — warm red variant
    ],
}

# Human-readable labels for the GUI palette selector. Order here is the order
# they appear in any dropdown built from PALETTE_LABELS.items().
PALETTE_LABELS: dict[str, str] = {
    "okabe_ito":     "Color-blind safe (Okabe-Ito)",
    "high_contrast": "High contrast (magenta–green, composite-optimised)",
    "classic_rgb":   "Classic RGB (legacy)",
}

# The default palette for fresh sessions / presets that do not specify one
DEFAULT_PALETTE = "high_contrast"

# The palette used for legacy presets (those saved before v0.9.3 that have no
# ``palette_name`` field). Pre-v0.9.3 sessions used the saturated RGB cycle,
# so loading a legacy preset without explicit per-component colours should
# restore the user to that visual identity.
LEGACY_PRESET_PALETTE = "classic_rgb"


def _colors_from_palette(palette_name: str) -> list[QColor]:
    """Return a fresh list of QColor objects for the named palette."""
    if palette_name not in PALETTES:
        raise ValueError(
            f"Unknown palette {palette_name!r}; available: {sorted(PALETTES)}"
        )
    return [QColor(hex_str) for hex_str in PALETTES[palette_name]]


def _coerce_to_qcolor(c) -> QColor:
    """Accept a QColor, hex string, or (R, G, B[, A]) tuple/list and return a QColor."""
    if isinstance(c, QColor):
        return QColor(c)  # defensive copy
    if isinstance(c, str):
        return QColor(c)
    if isinstance(c, (tuple, list)):
        return QColor(*c)
    # Fall back to QColor's own conversion (raises if it can't handle it)
    return QColor(c)


class ComponentColorManager(QObject):
    """Holds the per-component colour list and broadcasts changes."""

    # Signal emitted when a single colour changes: (component_index, new_QColor)
    sigColorChanged = pyqtSignal(int, QColor)
    # Signal emitted when the palette is replaced wholesale (palette_name)
    sigPaletteChanged = pyqtSignal(str)

    def __init__(
        self,
        default_colors: list | None = None,
        palette_name: str | None = None,
    ):
        """Create the colour manager.

        Parameters
        ----------
        default_colors
            Explicit list of colour specs (QColor / hex str / RGB tuple). If
            given, takes precedence over ``palette_name`` — used for restoring
            saved presets verbatim.
        palette_name
            Name of one of the entries in :data:`PALETTES`. Used when
            ``default_colors`` is not supplied. Defaults to
            :data:`DEFAULT_PALETTE`.
        """
        super().__init__()
        self._palette_name: str = palette_name or DEFAULT_PALETTE
        if default_colors is not None:
            self._colors = [_coerce_to_qcolor(c) for c in default_colors]
        else:
            self._colors = _colors_from_palette(self._palette_name)

    # ── Palette management ────────────────────────────────────────────
    @property
    def palette_name(self) -> str:
        """Name of the currently active palette."""
        return self._palette_name

    def set_palette(self, palette_name: str) -> None:
        """Switch the active palette and refresh component colours.

        Emits :attr:`sigColorChanged` for every component slot so all
        downstream widgets update, plus :attr:`sigPaletteChanged` once
        at the end.
        """
        if palette_name == self._palette_name:
            return
        if palette_name not in PALETTES:
            raise ValueError(
                f"Unknown palette {palette_name!r}; "
                f"available: {sorted(PALETTES)}"
            )
        self._palette_name = palette_name
        new_colors = _colors_from_palette(palette_name)
        # Preserve the previous length so existing component slots stay valid;
        # extra slots beyond the palette cycle through it.
        old_len = len(self._colors)
        if old_len <= len(new_colors):
            self._colors = new_colors[:old_len] if old_len > 0 else new_colors
        else:
            # Cycle through the palette to fill all existing slots.
            self._colors = [
                new_colors[i % len(new_colors)] for i in range(old_len)
            ]
        for i, color in enumerate(self._colors):
            self.sigColorChanged.emit(i, color)
        self.sigPaletteChanged.emit(self._palette_name)

    # ── Colour accessors ──────────────────────────────────────────────
    def get_qcolor(self, index: int) -> QColor:
        """Get QColor for a component index (cycles if index > len)."""
        if not self._colors:
            return QColor(255, 255, 255)
        return self._colors[index % len(self._colors)]

    def get_color_rgb(self, index: int):
        """Get color in (R,G,B) tuple format."""
        c = self.get_qcolor(index)
        return (c.red(), c.green(), c.blue())

    def get_pg_color(self, index: int):
        """Get color in format suitable for pyqtgraph (R,G,B,A)."""
        c = self.get_qcolor(index)
        return (c.red(), c.green(), c.blue(), 255)

    def set_color(self, index: int, color: QColor):
        """Update color and notify all listeners."""
        # Ensure list is long enough
        while len(self._colors) <= index:
            self._colors.append(QColor(255, 255, 255))

        self._colors[index] = color
        self.sigColorChanged.emit(index, color)

    def set_color_rgb(self, index: int, *args):
        """Set color using RGB values.

        Accepts either separate args:   ``set_color_rgb(0, 255, 0, 0)``
        or a single tuple:              ``set_color_rgb(0, (255, 0, 0))``
        """
        if len(args) == 1 and isinstance(args[0], (list, tuple)):
            rgb = args[0]
        else:
            rgb = args
        color = QColor(*rgb)
        self.set_color(index, color)

    def get_all_colors_rgb(self):
        """Get all colors as a list of (R,G,B) tuples."""
        return [self.get_color_rgb(i) for i in range(len(self._colors))]


# ── UI helper ────────────────────────────────────────────────────────────
def create_palette_selector(
    color_manager: "ComponentColorManager",
    parent: QWidget | None = None,
    label_text: str = "Palette:",
    tooltip: str | None = None,
) -> tuple[QLabel, QComboBox]:
    """Build a (label, combobox) pair wired to a ComponentColorManager.

    Multiple selectors created from the same ``color_manager`` stay
    bidirectionally in sync: changing one (or programmatically calling
    ``color_manager.set_palette(...)`` from anywhere) updates all the others
    via the ``sigPaletteChanged`` signal.

    Typical usage:

    label, combo = create_palette_selector(self.color_manager)
    my_layout.addWidget(label)
    my_layout.addWidget(combo)
    """
    if tooltip is None:
        tooltip = (
            "Default component-colour palette for new components.\n"
            "Per-component colour picks (and colours loaded from .preset) "
            "override this."
        )

    label = QLabel(label_text, parent)
    combo = QComboBox(parent)
    combo.setToolTip(tooltip)

    # Populate from the global registry — adding a new entry to PALETTES /
    # PALETTE_LABELS makes it appear in every selector automatically.
    for internal_name, display in PALETTE_LABELS.items():
        combo.addItem(display, internal_name)

    if color_manager is not None:
        current_idx = combo.findData(color_manager.palette_name)
        if current_idx >= 0:
            combo.setCurrentIndex(current_idx)

    def _on_palette_chosen(_idx, combo_=combo, mgr_=color_manager):
        if mgr_ is None:
            return
        name = combo_.currentData()
        if name:
            mgr_.set_palette(name)

    combo.currentIndexChanged.connect(_on_palette_chosen)

    if color_manager is not None:
        def _sync(name: str, combo_=combo):
            idx = combo_.findData(name)
            if idx >= 0 and combo_.currentIndex() != idx:
                combo_.blockSignals(True)
                combo_.setCurrentIndex(idx)
                combo_.blockSignals(False)

        color_manager.sigPaletteChanged.connect(_sync)

    return label, combo
