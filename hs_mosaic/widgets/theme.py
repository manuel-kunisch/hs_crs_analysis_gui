"""Application-wide design system for HS-MOSAIC.

One place defines the palette, the Qt stylesheet, the pyqtgraph defaults and
the dock styling, so every widget module can stay free of inline stylesheets.

The palette is the validated dark-chart palette from the ENVI hyperspectral
viewer (surface/panel/ink tones + one blue accent): categorical component
colors stay the job of ``color_manager``; this module only owns the chrome.

Usage::

    from hs_mosaic.widgets.theme import apply_theme
    app = QtWidgets.QApplication(argv)
    apply_theme(app)   # before any pyqtgraph widget is created
"""
from __future__ import annotations

import hashlib
import os
import tempfile

import pyqtgraph as pg
from PyQt5 import QtCore, QtGui, QtWidgets

# ── Design tokens ──────────────────────────────────────────────────────────
SURFACE = "#1a1a19"      # chart / image backgrounds, line edits, tables
PANEL = "#232322"        # window and panel background
PANEL_2 = "#2c2c2a"      # raised controls (buttons, headers, tabs)
PANEL_3 = "#3a3a37"      # hovered controls
BORDER = "#3d3d3a"       # hairline borders
BORDER_SOFT = "#31312f"  # subtler borders (table grid)
INK = "#ffffff"          # primary text
INK_2 = "#c3c2b7"        # secondary text, plot foreground
INK_MUTED = "#898781"    # disabled text, hints
ACCENT = "#3987e5"       # selection, highlights, primary action
ACCENT_HOVER = "#5599ec"
ACCENT_DIM = "#2b5f9e"
WARN = "#d0a030"
DANGER = "#d95940"
# Selection never uses its own color for ROIs: the active ROI keeps its
# component color (thicker + brighter) while the others drop opacity, and the
# table row is marked with ACCENT like every other selection in the app.

_ICON_DIR = None


def _icon_dir() -> str:
    """Directory with the small SVGs the stylesheet references (created once)."""
    global _ICON_DIR
    if _ICON_DIR is not None:
        return _ICON_DIR
    # Key the cache directory by the glyph colors: the SVGs below are only
    # written when missing, so a palette change in a later release must land
    # in a fresh directory instead of reusing another version's stale art.
    palette_tag = hashlib.sha1(f"{INK}|{INK_MUTED}|{INK_2}".encode()).hexdigest()[:8]
    path = os.path.join(tempfile.gettempdir(), f"hs_mosaic_theme_{palette_tag}")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        # unwritable/full temp dir: degrade to missing glyphs (like the
        # guarded writes below) instead of failing the whole launch
        pass
    svgs = {
        "check.svg": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12">'
            f'<path d="M2.5 6.5 L5 9 L9.5 3.5" stroke="{INK}" stroke-width="2" '
            'fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        ),
        "check_dim.svg": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12">'
            f'<path d="M2.5 6.5 L5 9 L9.5 3.5" stroke="{INK_MUTED}" stroke-width="2" '
            'fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        ),
        "down.svg": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            f'<path d="M2 3.5 L5 6.5 L8 3.5" stroke="{INK_2}" stroke-width="1.6" '
            'fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        ),
        "up.svg": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            f'<path d="M2 6.5 L5 3.5 L8 6.5" stroke="{INK_2}" stroke-width="1.6" '
            'fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        ),
    }
    for name, content in svgs.items():
        file_path = os.path.join(path, name)
        try:
            if not os.path.exists(file_path):
                with open(file_path, "w", encoding="utf-8") as fh:
                    fh.write(content)
        except OSError:
            pass
    _ICON_DIR = path.replace("\\", "/")
    return _ICON_DIR


def make_palette() -> QtGui.QPalette:
    p = QtGui.QPalette()
    roles = {
        QtGui.QPalette.Window: PANEL,
        QtGui.QPalette.WindowText: INK,
        QtGui.QPalette.Base: SURFACE,
        QtGui.QPalette.AlternateBase: "#1f1f1e",
        QtGui.QPalette.Text: INK,
        QtGui.QPalette.Button: PANEL_2,
        QtGui.QPalette.ButtonText: INK,
        QtGui.QPalette.Highlight: ACCENT,
        QtGui.QPalette.HighlightedText: INK,
        QtGui.QPalette.ToolTipBase: PANEL_2,
        QtGui.QPalette.ToolTipText: INK,
        QtGui.QPalette.Link: ACCENT,
        QtGui.QPalette.PlaceholderText: INK_MUTED,
        QtGui.QPalette.BrightText: "#ff6b6b",
    }
    for role, color in roles.items():
        p.setColor(role, QtGui.QColor(color))
    for role in (QtGui.QPalette.WindowText, QtGui.QPalette.Text, QtGui.QPalette.ButtonText):
        p.setColor(QtGui.QPalette.Disabled, role, QtGui.QColor(INK_MUTED))
    p.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Light, QtGui.QColor(PANEL))
    return p


def make_stylesheet() -> str:
    icons = _icon_dir()
    return f"""
/* ── Base ─────────────────────────────────────────────────────────── */
QWidget {{
    color: {INK};
    selection-background-color: {ACCENT};
    selection-color: {INK};
}}
QMainWindow, QDialog {{ background-color: {PANEL}; }}
QToolTip {{
    background-color: {PANEL_2};
    color: {INK};
    border: 1px solid {BORDER};
    padding: 5px 8px;
}}
QStatusBar {{
    background: {PANEL};
    color: {INK_2};
    border-top: 1px solid {BORDER_SOFT};
}}
QStatusBar::item {{ border: none; }}

/* ── Buttons ──────────────────────────────────────────────────────── */
QPushButton {{
    background-color: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 12px;
}}
QPushButton:hover {{ background-color: {PANEL_3}; }}
QPushButton:pressed {{ background-color: {SURFACE}; }}
QPushButton:disabled {{ color: {INK_MUTED}; background-color: {PANEL}; }}
QPushButton:checked {{ background-color: {ACCENT_DIM}; border-color: {ACCENT}; }}
QPushButton:default {{ border-color: {ACCENT}; }}

QToolButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px 8px;
}}
QToolButton:hover {{ background-color: {PANEL_3}; border-color: {BORDER}; }}
QToolButton:pressed {{ background-color: {SURFACE}; }}
QToolButton:checked {{ background-color: {ACCENT_DIM}; border-color: {ACCENT}; }}
QToolButton:disabled {{ color: {INK_MUTED}; }}
QToolButton::menu-indicator {{ image: url({icons}/down.svg); width: 10px; height: 10px;
                               subcontrol-position: right center; subcontrol-origin: padding;
                               padding-right: 2px; }}

/* Primary call-to-action (Run Analysis) */
QToolButton#AnalyzeTool {{
    border-radius: 8px;
    padding: 10px 16px;
    font-weight: 700;
    color: {INK};
    background-color: {ACCENT};
    border: 1px solid {ACCENT_HOVER};
}}
QToolButton#AnalyzeTool:hover {{ background-color: {ACCENT_HOVER}; }}
QToolButton#AnalyzeTool:pressed {{ background-color: {ACCENT_DIM}; }}
QToolButton#AnalyzeTool:disabled {{ background-color: {PANEL_2}; color: {INK_MUTED}; border-color: {BORDER}; }}

/* ── Inputs ───────────────────────────────────────────────────────── */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 3px 6px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {ACCENT_DIM}; }}
QLineEdit:disabled {{ color: {INK_MUTED}; }}

QComboBox {{
    background-color: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 3px 26px 3px 8px;
    min-height: 20px;
}}
QComboBox:hover {{ background-color: {PANEL_3}; }}
QComboBox:disabled {{ color: {INK_MUTED}; background-color: {PANEL}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({icons}/down.svg); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background-color: {PANEL_2};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_DIM};
    outline: none;
}}

QAbstractSpinBox {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 2px 4px 2px 6px;
    min-height: 20px;
}}
QAbstractSpinBox:focus {{ border-color: {ACCENT_DIM}; }}
QAbstractSpinBox:disabled {{ color: {INK_MUTED}; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    background: transparent; border: none; width: 16px;
}}
QAbstractSpinBox::up-arrow {{ image: url({icons}/up.svg); width: 9px; height: 9px; }}
QAbstractSpinBox::down-arrow {{ image: url({icons}/down.svg); width: 9px; height: 9px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::down-arrow:disabled {{ image: none; }}

QCheckBox, QRadioButton {{ spacing: 6px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; }}
QCheckBox::indicator {{
    border: 1px solid {BORDER};
    border-radius: 4px;
    background-color: {SURFACE};
}}
QCheckBox::indicator:hover {{ border-color: {INK_MUTED}; }}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    image: url({icons}/check.svg);
}}
QCheckBox::indicator:checked:disabled {{
    background-color: {PANEL_2};
    border-color: {BORDER};
    image: url({icons}/check_dim.svg);
}}
QCheckBox:disabled, QRadioButton:disabled {{ color: {INK_MUTED}; }}
QRadioButton::indicator {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    background-color: {SURFACE};
}}
QRadioButton::indicator:hover {{ border-color: {INK_MUTED}; }}
QRadioButton::indicator:checked {{
    border: 4px solid {ACCENT};
    background-color: {INK};
}}

QSlider::groove:horizontal {{
    height: 4px; background: {PANEL_3}; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {INK_2}; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ background: {INK}; }}
QSlider::sub-page:horizontal {{ background: {ACCENT_DIM}; border-radius: 2px; }}

/* ── Containers ───────────────────────────────────────────────────── */
QGroupBox {{
    font-weight: 600;
    border: 1px solid {BORDER_SOFT};
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 4px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: {INK_2};
}}

QTabWidget::pane {{ border: 1px solid {BORDER_SOFT}; border-radius: 6px; top: -1px; }}
QTabBar::tab {{
    background: {PANEL};
    color: {INK_2};
    border: 1px solid transparent;
    padding: 6px 18px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
QTabBar::tab:hover {{ color: {INK}; background: {PANEL_3}; }}
QTabBar::tab:selected {{
    background: {PANEL_2};
    color: {INK};
    border-color: {BORDER_SOFT};
    border-bottom-color: {PANEL_2};
    font-weight: 600;
}}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {ACCENT_DIM}; }}
QSplitter::handle:horizontal {{ width: 4px; }}
QSplitter::handle:vertical {{ height: 4px; }}

/* ── Item views ───────────────────────────────────────────────────── */
QTableWidget, QTableView, QTreeView, QListView {{
    background-color: {SURFACE};
    alternate-background-color: #1e1e1d;
    gridline-color: {BORDER_SOFT};
    border: 1px solid {BORDER_SOFT};
    border-radius: 6px;
    selection-background-color: rgba(57, 135, 229, 60);
    selection-color: {INK};
}}
QTableView::item {{ padding: 2px; }}
QTableView::item:selected {{ background: rgba(57, 135, 229, 60); }}
QHeaderView {{ background-color: {PANEL_2}; border: none; }}
QHeaderView::section {{
    background-color: {PANEL_2};
    color: {INK_2};
    border: none;
    border-right: 1px solid {BORDER_SOFT};
    border-bottom: 1px solid {BORDER_SOFT};
    padding: 5px 8px;
    font-weight: 600;
}}
QTableCornerButton::section {{ background-color: {PANEL_2}; border: none; }}

/* ── Menus / toolbars ─────────────────────────────────────────────── */
QMenuBar {{ background: {PANEL}; color: {INK_2}; }}
QMenuBar::item {{ padding: 5px 10px; background: transparent; border-radius: 4px; }}
QMenuBar::item:selected {{ background: {PANEL_3}; color: {INK}; }}
QMenu {{
    background-color: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{ padding: 5px 24px 5px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background-color: {ACCENT_DIM}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QToolBar {{ background: transparent; border: none; spacing: 3px; padding: 2px; }}
QToolBar::separator {{ background: {BORDER}; width: 1px; margin: 4px 4px; }}

/* ── Scrollbars ───────────────────────────────────────────────────── */
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {PANEL_3}; border-radius: 5px; min-height: 30px; margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background: {INK_MUTED}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: {PANEL_3}; border-radius: 5px; min-width: 30px; margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{ background: {INK_MUTED}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ── Progress ─────────────────────────────────────────────────────── */
QProgressBar {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_SOFT};
    border-radius: 5px;
    text-align: center;
    color: {INK_2};
}}
QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: 4px; }}

/* ── App-specific hooks ───────────────────────────────────────────── */
QLabel#DragDropLabel {{
    border: 1px dashed {INK_MUTED};
    border-radius: 8px;
    padding: 10px;
    background: {SURFACE};
    color: {INK_2};
}}
QLabel#DragDropLabel:hover {{ border-color: {ACCENT}; color: {INK}; }}
QLabel#SectionTitle {{ font-weight: 700; color: {INK_2}; }}
QLabel#HintLabel {{ color: {INK_MUTED}; }}
QWidget#InspectorPanel {{
    background: {PANEL_2};
    border: 1px solid {BORDER_SOFT};
    border-radius: 8px;
}}
QLabel#ReadoutLabel {{
    color: {INK_2};
    font-family: "Consolas", "Cascadia Mono", monospace;
}}
"""


def _themed_dock_label_style(self):
    """Replacement for pyqtgraph's DockLabel.updateStyle with our palette."""
    r = "4px"
    if self.dim:  # inactive tabbed dock
        fg, bg, border = INK_MUTED, PANEL, BORDER_SOFT
    else:
        fg, bg, border = INK_2, PANEL_2, BORDER_SOFT
    if self.orientation == "vertical":
        self.vStyle = f"""DockLabel {{
            background-color: {bg};
            color: {fg};
            border-top-right-radius: 0px;
            border-top-left-radius: {r};
            border-bottom-right-radius: 0px;
            border-bottom-left-radius: {r};
            border-width: 0px;
            border-right: 1px solid {border};
            padding-top: 3px;
            padding-bottom: 3px;
            font-size: {self.fontSize};
            font-weight: 600;
        }}"""
        self.setStyleSheet(self.vStyle)
    else:
        self.hStyle = f"""DockLabel {{
            background-color: {bg};
            color: {fg};
            border-top-right-radius: {r};
            border-top-left-radius: {r};
            border-bottom-right-radius: 0px;
            border-bottom-left-radius: 0px;
            border-width: 0px;
            border-bottom: 1px solid {border};
            padding-left: 6px;
            padding-right: 6px;
            font-size: {self.fontSize};
            font-weight: 600;
        }}"""
        self.setStyleSheet(self.hStyle)


def _theme_pyqtgraph_docks():
    """Restyle pyqtgraph docks (blue title bars -> quiet panel chrome)."""
    try:
        from pyqtgraph.dockarea.Dock import Dock, DockLabel
    except Exception:  # pragma: no cover - pyqtgraph layout changed
        return
    DockLabel.updateStyle = _themed_dock_label_style
    # The dock body frame drawn around the contents
    _orig_init = Dock.__init__

    def _init(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        self.hStyle = f"""
        Dock > QWidget {{
            border: 1px solid {BORDER_SOFT};
            border-radius: 5px;
            border-top-left-radius: 0px;
            border-top-right-radius: 0px;
            border-top-width: 0px;
        }}"""
        self.vStyle = f"""
        Dock > QWidget {{
            border: 1px solid {BORDER_SOFT};
            border-radius: 5px;
            border-top-left-radius: 0px;
            border-bottom-left-radius: 0px;
            border-left-width: 0px;
        }}"""
        self.nStyle = f"""
        Dock > QWidget {{
            border: 1px solid {BORDER_SOFT};
            border-radius: 5px;
        }}"""
        self.dragStyle = f"""
        Dock > QWidget {{
            border: 2px solid {ACCENT};
            border-radius: 5px;
        }}"""
        self.updateStyle()

    if not getattr(Dock, "_hs_mosaic_themed", False):
        Dock.__init__ = _init
        Dock._hs_mosaic_themed = True


def apply_theme(app: QtWidgets.QApplication):
    """Apply the HS-MOSAIC dark theme to the whole application.

    Must run before pyqtgraph widgets are created so the global plot
    background/foreground take effect.
    """
    app.setStyle("Fusion")
    app.setPalette(make_palette())
    app.setStyleSheet(make_stylesheet())
    pg.setConfigOptions(background=SURFACE, foreground=INK_2)
    _theme_pyqtgraph_docks()


def accent_pen(width: float = 2.0) -> "pg.mkPen":
    pen = pg.mkPen(ACCENT, width=width)
    pen.setCosmetic(True)
    return pen


def icon(name: str, color: str = INK_2, color_active: str = INK) -> QtGui.QIcon:
    """qtawesome icon in theme colors; falls back to an empty icon."""
    try:
        import qtawesome as qta
        return qta.icon(name, color=color, color_active=color_active)
    except Exception:  # pragma: no cover - icon font missing
        return QtGui.QIcon()
