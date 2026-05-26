"""Component color management with named, color-blind-aware palettes.

Four named palettes are provided out of the box:

* ``magenta_cyan_yellow`` (default) — the additive-secondary trio
  (magenta + cyan + yellow), which provides the highest mutual contrast on a
  black composite background of any 3-color combination. Padded with five
  supplementary colors for components 4-8.
* ``high_contrast`` — magenta-green-sky-blue-led palette, brighter than
  Okabe-Ito while still preserving the color-blind-friendly magenta + green
  colocalisation signal of multi-channel fluorescence microscopy.
* ``okabe_ito`` — the canonical 8-color qualitative palette designed for
  protanopia and deuteranopia. Recommended specifically when color-vision
  deficiency is a concern in the audience (Wong, *Nat. Methods* **8**, 441,
  2011).
* ``classic_rgb`` — the legacy saturated RGB cycle that HS-MOSAIC shipped
  before v0.9.3. Kept for backwards compatibility with users who expect
  component 1 = red, 2 = green, 3 = blue.

The palette is the *initial* color assignment for new components. Per-component
choices made through the GUI color pickers (or loaded from a ``.preset``) take
precedence and are not overridden when the palette is switched. When any
component differs from the palette's baseline value, the manager reports the
palette as *customized* via :attr:`ComponentColorManager.is_customized` and the
:attr:`ComponentColorManager.sigCustomizationChanged` signal — the GUI palette
selector reflects this by appending ``(customized)`` to the current entry.
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QComboBox, QLabel, QWidget


# Named palette definitions. Each entry is a list of QColor specs as
# hex strings, kept hex-only for readability and for round-tripping into
# JSON presets.
PALETTES: dict[str, list[str]] = {
    # Magenta-Cyan-Yellow trio — the three additive secondaries. Each is
    # "two of three RGB primaries lit", which makes them maximally bright
    # on a black additive composite background AND maximally distinct from
    # each other in the additive-mixing sense (each is missing a DIFFERENT
    # primary, so their pairwise overlaps land on cleanly different mixes
    # rather than degenerating to white). This is the best 3-color
    # contrast palette for composite display; supplementary colors fill
    # slots 4-8 for higher component counts.
    "magenta_cyan_yellow": [
        "#FF00FF",   # Magenta
        "#00FFFF",   # Cyan
        "#FFFF00",   # Yellow
        "#00FF00",   # Pure green        — distinct from cyan (no blue)
        "#FF8000",   # Orange            — warm, distinct from yellow (no blue)
        "#0080FF",   # Sky blue          — bluer than cyan
        "#FFFFFF",   # White             — max brightness for "extras"
        "#FF6040",   # Coral             — warm red-orange variant
    ],
    # Okabe & Ito 8-color palette — color-blind safe, scientific default.
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
    # the standard color-blind-friendly alternative to red–green–blue in
    # multi-channel fluorescence microscopy (magenta + green co-localise to
    # white, the classic two-color overlap signal). Brighter overall than
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
    "magenta_cyan_yellow": "Magenta–Cyan–Yellow (max contrast)",
    "high_contrast":       "High contrast (magenta–green, composite-optimised)",
    "okabe_ito":           "Color-blind safe (Okabe-Ito)",
    "classic_rgb":         "Classic RGB (legacy)",
}

# The default palette for fresh sessions / presets that do not specify one
DEFAULT_PALETTE = "magenta_cyan_yellow"

# The palette used for legacy presets (those saved before v0.9.3 that have no
# ``palette_name`` field). Pre-v0.9.3 sessions used the saturated RGB cycle,
# so loading a legacy preset without explicit per-component colors should
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
    """Holds the per-component color list and broadcasts changes."""

    # Signal emitted when a single color changes: (component_index, new_QColor)
    sigColorChanged = pyqtSignal(int, QColor)
    # Signal emitted when the palette is replaced wholesale (palette_name)
    sigPaletteChanged = pyqtSignal(str)
    # Signal emitted when the customisation status flips: True when at least
    # one component color now differs from the active palette's baseline,
    # False when all components match the baseline again. Use this in GUI
    # widgets to render "(customized)" hints next to the palette selector.
    sigCustomizationChanged = pyqtSignal(bool)

    def __init__(
        self,
        default_colors: list | None = None,
        palette_name: str | None = None,
    ):
        """Create the color manager.

        Parameters
        ----------
        default_colors
            Explicit list of color specs (QColor / hex str / RGB tuple). If
            given, takes precedence over ``palette_name`` — used for restoring
            saved presets verbatim. When this path is taken, the customisation
            check still runs against the named palette's baseline, so a
            preset that explicitly stored colors which match the palette is
            reported as *not* customized, and one whose colors differ is.
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

        # Snapshot of the palette's baseline at the moment the palette is
        # set / switched. Customisation = any current color differs from
        # its slot in this baseline.
        self._palette_baseline: list[QColor] = _colors_from_palette(self._palette_name)
        self._customized: bool = self._compute_customized()

    # ── Palette management ────────────────────────────────────────────
    @property
    def palette_name(self) -> str:
        """Name of the currently active palette."""
        return self._palette_name

    @property
    def is_customized(self) -> bool:
        """True if at least one component color differs from the active
        palette's baseline. Switches back to False when every component
        matches its slot in the palette again (e.g. after re-applying the
        same palette, or after manually restoring the baseline colors)."""
        return self._customized

    def set_palette(self, palette_name: str) -> None:
        """Switch the active palette and refresh component colors.

        Emits :attr:`sigColorChanged` for every component slot so all
        downstream widgets update, plus :attr:`sigPaletteChanged` once
        at the end. Always resets the customisation baseline to the new
        palette and emits :attr:`sigCustomizationChanged` if the
        customized state actually flipped.
        """
        # Allow re-applying the same palette as a "reset to baseline"
        # — useful when the user wants to undo manual color edits.
        new_colors = _colors_from_palette(palette_name) if palette_name in PALETTES else None
        if new_colors is None:
            raise ValueError(
                f"Unknown palette {palette_name!r}; "
                f"available: {sorted(PALETTES)}"
            )

        palette_actually_changed = palette_name != self._palette_name
        self._palette_name = palette_name

        # Preserve the previous length so existing component slots stay valid;
        # extra slots beyond the palette cycle through it.
        old_len = len(self._colors)
        if old_len <= len(new_colors):
            self._colors = new_colors[:old_len] if old_len > 0 else list(new_colors)
        else:
            self._colors = [
                new_colors[i % len(new_colors)] for i in range(old_len)
            ]

        # Refresh the customisation baseline to match the newly-applied palette.
        self._palette_baseline = list(new_colors)

        for i, color in enumerate(self._colors):
            self.sigColorChanged.emit(i, color)
        if palette_actually_changed:
            self.sigPaletteChanged.emit(self._palette_name)
        # The set of colors is now identical to the baseline, so
        # customisation MUST be False. Emit if this is a change.
        self._update_customization(False)

    # ── Customisation tracking ────────────────────────────────────────
    def _baseline_color_for(self, index: int) -> QColor:
        """Return the palette-baseline color for ``index``, cycling
        if ``index`` exceeds the baseline length (same as get_qcolor's
        cycling behaviour)."""
        if not self._palette_baseline:
            return QColor(255, 255, 255)
        return self._palette_baseline[index % len(self._palette_baseline)]

    def _compute_customized(self) -> bool:
        if len(self._colors) != len(self._palette_baseline):
            # Different length means some component slot has no baseline
            # counterpart of identical position — treat as customized.
            return True
        for cur, base in zip(self._colors, self._palette_baseline):
            if cur.rgb() != base.rgb():
                return True
        return False

    def _update_customization(self, new_state: bool | None = None) -> None:
        """Recompute (or take given) customisation flag and emit if changed."""
        if new_state is None:
            new_state = self._compute_customized()
        if new_state != self._customized:
            self._customized = new_state
            self.sigCustomizationChanged.emit(new_state)

    # ── color accessors ──────────────────────────────────────────────
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
        """Update color and notify all listeners.

        Also recomputes the customisation status: if the new color makes
        the manager state diverge from (or re-converge with) the active
        palette baseline, :attr:`sigCustomizationChanged` fires.
        """
        # Ensure list is long enough
        while len(self._colors) <= index:
            self._colors.append(QColor(255, 255, 255))

        self._colors[index] = color
        self.sigColorChanged.emit(index, color)
        self._update_customization()

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
            "Default component-color palette for new components.\n"
            "Per-component color picks (and colors loaded from .preset) "
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

        # Mark the currently-selected item with " (customized)" whenever the
        # user has modified any per-component color away from the active
        # palette's baseline. Other items always show their canonical label.
        # We reset ALL item texts on every update so switching palettes
        # never leaves a stale "(customized)" tag on a previously-active
        # entry. blockSignals around setItemText prevents the currentIndexChanged
        # cascade from re-triggering set_palette.
        def _refresh_customization(is_customized: bool, combo_=combo):
            combo_.blockSignals(True)
            try:
                for i in range(combo_.count()):
                    name = combo_.itemData(i)
                    if name is None:
                        continue
                    base = PALETTE_LABELS.get(name, name)
                    combo_.setItemText(i, f"{base} (customized)"
                                       if is_customized and i == combo_.currentIndex()
                                       else base)
            finally:
                combo_.blockSignals(False)

        color_manager.sigCustomizationChanged.connect(_refresh_customization)
        # Initialise — show the current state on first render (handles the
        # case where the manager was already customized when the selector
        # was constructed, e.g. after preset load).
        _refresh_customization(color_manager.is_customized)

    return label, combo
