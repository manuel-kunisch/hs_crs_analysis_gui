import json
import logging
import traceback
from pathlib import Path
from typing import List, Optional
import re

import numpy as np
from PyQt5 import QtCore, QtWidgets

from contents.cross_correlation_stitcher import CrossCorrelationStitcher  # adjust import!

logger = logging.getLogger("StitchManager")


def _parse_int_list(text: str) -> Optional[List[int]]:
    """
    Accepts: "40, 41,42" or "40 41 42" or "" -> None
    """
    s = (text or "").strip()
    if not s:
        return None
    parts = [p for p in s.replace(",", " ").split() if p.strip()]
    out: List[int] = []
    for p in parts:
        out.append(int(p))
    return out


class _StitchWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal(object)  # np.ndarray
    failed = QtCore.pyqtSignal(str)

    def __init__(self, stitcher: CrossCorrelationStitcher, folder: str, pattern: str):
        super().__init__()
        self.stitcher = stitcher
        self.folder = folder
        self.pattern = pattern

    @QtCore.pyqtSlot()
    def run(self):
        try:
            stitched = self.stitcher.stitch_folder(self.folder, pattern=self.pattern)
            self.finished.emit(stitched)
        except Exception:
            self.failed.emit(traceback.format_exc())


class StitchManager(QtCore.QObject):
    """
    Drop-in replacement for your old StitchManager:
    - has .stitch_data_widget
    - has .init_ui()
    - emits stitchedImageChanged(np.ndarray) (as object to be robust)
    """
    stitchedImageChanged = QtCore.pyqtSignal(object)  # np.ndarray

    def __init__(self):
        super().__init__()
        self.stitch_data_widget: Optional[QtWidgets.QWidget] = None
        self.stitcher: CrossCorrelationStitcher = CrossCorrelationStitcher()

        self._folder: Optional[Path] = None
        self._thread: Optional[QtCore.QThread] = None
        self._worker: Optional[_StitchWorker] = None

    # ---------------- UI ----------------
    def init_ui(self):
        w = QtWidgets.QWidget()
        self.stitch_data_widget = w

        root = QtWidgets.QVBoxLayout(w)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # --- top: drop/select ---
        top = QtWidgets.QHBoxLayout()
        root.addLayout(top)

        self.drop_label = QtWidgets.QLabel("📂 Drop a tile (or a folder) here, or choose a folder…")
        self.drop_label.setMinimumHeight(42)
        self.drop_label.setWordWrap(True)
        self.drop_label.setAcceptDrops(True)
        self.drop_label.dragEnterEvent = self._drag_enter
        self.drop_label.dropEvent = self._drop
        self.drop_label.setStyleSheet("""
            QLabel {
                border: 1px dashed #888;
                border-radius: 6px;
                padding: 8px;
                background: #2b2b2b;
                color: #ddd;
            }
        """)
        top.addWidget(self.drop_label, 1)

        self.choose_folder_btn = QtWidgets.QPushButton("Choose folder…")
        self.choose_folder_btn.clicked.connect(self._choose_folder)
        top.addWidget(self.choose_folder_btn)

        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh_table)
        top.addWidget(self.refresh_btn)

        # --- settings ---
        settings_grid = QtWidgets.QGridLayout()
        root.addLayout(settings_grid)

        # left: stitching params
        params_box = QtWidgets.QGroupBox("Stitch parameters")
        params = QtWidgets.QFormLayout(params_box)
        params.setLabelAlignment(QtCore.Qt.AlignRight)

        self.pattern_edit = QtWidgets.QLineEdit("*.tif")
        self.pattern_edit.setToolTip("Glob pattern, e.g. *.tif or *THG*.tif")
        params.addRow("Pattern", self.pattern_edit)

        self.binning_spin = QtWidgets.QSpinBox()
        self.binning_spin.setRange(1, 16)
        self.binning_spin.setValue(int(self.stitcher.binning))
        self.binning_spin.valueChanged.connect(self._update_overlap_labels)
        params.addRow("Binning", self.binning_spin)

        self.overlap_row_raw = QtWidgets.QSpinBox()
        self.overlap_row_raw.setRange(0, 5000)
        self.overlap_row_raw.setValue(180)  # raw pixels default; adjust to your typical
        self.overlap_row_raw.valueChanged.connect(self._update_overlap_labels)

        self.overlap_col_raw = QtWidgets.QSpinBox()
        self.overlap_col_raw.setRange(0, 5000)
        self.overlap_col_raw.setValue(180)
        self.overlap_col_raw.valueChanged.connect(self._update_overlap_labels)

        self.overlap_row_binned_lbl = QtWidgets.QLabel("")
        self.overlap_col_binned_lbl = QtWidgets.QLabel("")
        self._update_overlap_labels()

        row_wrap = QtWidgets.QHBoxLayout()
        row_wrap.addWidget(self.overlap_row_raw)
        row_wrap.addWidget(self.overlap_row_binned_lbl)
        params.addRow("Overlap row (raw px)", row_wrap)

        col_wrap = QtWidgets.QHBoxLayout()
        col_wrap.addWidget(self.overlap_col_raw)
        col_wrap.addWidget(self.overlap_col_binned_lbl)
        params.addRow("Overlap col (raw px)", col_wrap)

        self.sigma_spin = QtWidgets.QDoubleSpinBox()
        self.sigma_spin.setRange(0.05, 50.0)
        self.sigma_spin.setDecimals(2)
        self.sigma_spin.setSingleStep(0.1)
        self.sigma_spin.setValue(float(self.stitcher.sigma_interval))
        params.addRow("Sigma interval", self.sigma_spin)

        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["normal", "mean", "sigma", "sigma mean"])
        self.mode_combo.setCurrentText(str(self.stitcher.mode))
        params.addRow("Mode", self.mode_combo)

        self.scan_combo = QtWidgets.QComboBox()
        self.scan_combo.addItems(["left", "right"])
        self.scan_combo.setCurrentText(str(self.stitcher.scan_x_direction))
        self.scan_combo.currentTextChanged.connect(self._on_scan_dir_changed)
        params.addRow("Scan X direction", self.scan_combo)

        # --- scan direction hint + live table update ---
        self.scan_hint_lbl = QtWidgets.QLabel()
        self.scan_hint_lbl.setStyleSheet("color: #aaa;")  # subtle
        params.addRow("", self.scan_hint_lbl)
        self._on_scan_dir_changed(self.scan_combo.currentText())



        self.input_order_combo = QtWidgets.QComboBox()
        self.input_order_combo.addItems(["zyx", "yxc", "cyx"])
        self.input_order_combo.setCurrentText(str(self.stitcher.input_channel_order))
        params.addRow("Input image order", self.input_order_combo)

        self.channel_list_edit = QtWidgets.QLineEdit()
        self.channel_list_edit.setPlaceholderText("e.g. 40, 41, 42  (empty = all)")
        params.addRow("Channels to correlate", self.channel_list_edit)

        self.display_channel_spin = QtWidgets.QSpinBox()
        self.display_channel_spin.setRange(0, 9999)
        self.display_channel_spin.setValue(int(self.stitcher.display_channel))
        # params.addRow("Display channel", self.display_channel_spin)

        self.plot_check = QtWidgets.QCheckBox("Debug plot")
        self.plot_check.setChecked(bool(self.stitcher.plot))
        # params.addRow("", self.plot_check)

        self.vmax_spin = QtWidgets.QDoubleSpinBox()
        self.vmax_spin.setRange(0, 1e9)
        self.vmax_spin.setValue(float(self.stitcher.vmax))
        # params.addRow("vmax (plot)", self.vmax_spin)

        settings_grid.addWidget(params_box, 0 , 0, 3, 1)

        # right: filename parsing
        parse_box = QtWidgets.QGroupBox("Filename parsing (x/y from filename)")
        parse = QtWidgets.QFormLayout(parse_box)
        parse.setLabelAlignment(QtCore.Qt.AlignRight)

        self.regex_edit = QtWidgets.QLineEdit(self.stitcher.filename_regex)
        self.regex_edit.setToolTip('Regex must contain named groups (?P<x>...) and (?P<y>...)')
        parse.addRow("Regex", self.regex_edit)

        self.ignorecase_check = QtWidgets.QCheckBox("IGNORECASE")
        self.ignorecase_check.setChecked(bool(self.stitcher.filename_regex_flags & re.IGNORECASE))
        parse.addRow("", self.ignorecase_check)

        btns = QtWidgets.QHBoxLayout()
        self.apply_regex_btn = QtWidgets.QPushButton("Apply regex")
        self.apply_regex_btn.clicked.connect(self._apply_regex_from_ui)
        btns.addWidget(self.apply_regex_btn)

        self.save_preset_btn = QtWidgets.QPushButton("Save preset…")
        self.save_preset_btn.clicked.connect(self._save_preset)
        btns.addWidget(self.save_preset_btn)

        self.load_preset_btn = QtWidgets.QPushButton("Load preset…")
        self.load_preset_btn.clicked.connect(self._load_preset)
        btns.addWidget(self.load_preset_btn)

        parse.addRow(btns)
        settings_grid.addWidget(parse_box, 0 , 1, 1, 1)

        # --- table preview ---
        self.table = QtWidgets.QTableWidget()
        self.table.setMinimumHeight(220)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        settings_grid.addWidget(self.table, 1 , 1, 2, 1)

        # --- bottom: run/status ---
        bottom = QtWidgets.QHBoxLayout()
        root.addLayout(bottom)

        self.status_lbl = QtWidgets.QLabel("Ready.")
        bottom.addWidget(self.status_lbl, 1)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setVisible(False)
        self.progress.setMaximumWidth(200)
        bottom.addWidget(self.progress)

        self.stitch_btn = QtWidgets.QPushButton("Stitch now")
        self.stitch_btn.clicked.connect(self.stitch)
        bottom.addWidget(self.stitch_btn)

    # ---------------- drag/drop ----------------
    def _drag_enter(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def _drop(self, event):
        urls = event.mimeData().urls()
        if not urls:
            return

        p = Path(urls[0].toLocalFile())
        if p.is_dir():
            self.set_folder(p)
        elif p.is_file():
            self.set_folder(p.parent)
        else:
            self.status_lbl.setText("Drop failed: invalid path.")

    def _choose_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(None, "Select folder with tiles")
        if folder:
            self.set_folder(Path(folder))

    def set_folder(self, folder: Path):
        self._folder = Path(folder)
        self.drop_label.setText(f"📁 Folder: {self._folder}")
        self._refresh_table()

    # ---------------- table ----------------
    def _apply_regex_from_ui(self):
        try:
            flags = 0
            if self.ignorecase_check.isChecked():
                flags |= re.IGNORECASE
            self.stitcher.set_filename_regex(self.regex_edit.text(), flags=flags)
            self.status_lbl.setText("Regex applied.")
            self._refresh_table()
        except Exception as e:
            self.status_lbl.setText(f"Regex error: {e}")

    def _refresh_table(self):
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)

        if self._folder is None:
            self.status_lbl.setText("Choose/drop a folder first.")
            return

        pattern = self.pattern_edit.text().strip() or "*.tif"
        files = sorted(self._folder.glob(pattern))
        if not files and pattern.lower().endswith(".tif"):
            files = sorted(self._folder.glob(pattern + "f"))  # crude help for .tiff if user typed *.tif

        parsed = []
        skipped = 0
        xs = set()
        ys = set()
        file_map = {}  # (x,y)->name

        for f in files:
            x, y = self.stitcher.parse_xy_from_name(f)
            if x is None or y is None:
                skipped += 1
                continue
            xs.add(x)
            ys.add(y)
            file_map[(x, y)] = f.name
            parsed.append((x, y))

        if not xs or not ys:
            self.status_lbl.setText(f"Found {len(files)} files, parsed 0 tiles. (skipped={skipped})")
            return

        lookup_y = sorted(ys)

        scan = self.scan_combo.currentText() if hasattr(self, "scan_combo") else "right"
        if scan == "left":
            lookup_x = sorted(xs, reverse=True)  # mirror layout
        else:
            lookup_x = sorted(xs)  # normal layout

        self.table.setColumnCount(len(lookup_x))
        self.table.setRowCount(len(lookup_y))
        self.table.setHorizontalHeaderLabels([str(x) for x in lookup_x])
        self.table.setVerticalHeaderLabels([str(y) for y in lookup_y])

        missing = 0
        for r, y in enumerate(lookup_y):
            for c, x in enumerate(lookup_x):
                name = file_map.get((x, y))
                if name is None:
                    missing += 1
                    item = QtWidgets.QTableWidgetItem("—")
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemIsSelectable)
                    item.setForeground(QtCore.Qt.gray)
                else:
                    item = QtWidgets.QTableWidgetItem("✓")
                    item.setToolTip(name)
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                self.table.setItem(r, c, item)

        self.status_lbl.setText(
            f"Found {len(files)} files, parsed {len(parsed)} tiles (skipped={skipped}, missing={missing})."
        )

    def _update_overlap_labels(self):
        N = max(1, int(self.binning_spin.value()))
        r_raw = int(self.overlap_row_raw.value())
        c_raw = int(self.overlap_col_raw.value())
        r_bin = r_raw // N
        c_bin = c_raw // N
        self.overlap_row_binned_lbl.setText(f"→ binned: {r_bin}px")
        self.overlap_col_binned_lbl.setText(f"→ binned: {c_bin}px")

    def _on_scan_dir_changed(self, direction: str):
        # "right": higher x goes to the right (normal)
        # "left" : higher x goes to the left (mirrored display)
        if direction == "right":
            self.scan_hint_lbl.setText("Layout: X increases → (higher x on the right)")
        else:
            self.scan_hint_lbl.setText("Layout: X increases ← (higher x on the left)")

        # update visualization immediately
        try:
            self._refresh_table()
        except Exception:
            pass


    # ---------------- presets ----------------
    def _collect_settings(self) -> dict:
        return {
            "pattern": self.pattern_edit.text().strip(),
            "binning": int(self.binning_spin.value()),
            "overlap_row_raw": int(self.overlap_row_raw.value()),
            "overlap_col_raw": int(self.overlap_col_raw.value()),
            "sigma_interval": float(self.sigma_spin.value()),
            "mode": self.mode_combo.currentText(),
            "scan_x_direction": self.scan_combo.currentText(),
            "input_channel_order": self.input_order_combo.currentText(),
            "channel_list": self.channel_list_edit.text().strip(),
            "display_channel": int(self.display_channel_spin.value()),
            "plot": bool(self.plot_check.isChecked()),
            "vmax": float(self.vmax_spin.value()),
            "filename_regex": self.regex_edit.text(),
            "ignorecase": bool(self.ignorecase_check.isChecked()),
        }

    def _apply_settings(self, d: dict):
        self.pattern_edit.setText(d.get("pattern", "*.tif"))
        self.binning_spin.setValue(int(d.get("binning", 1)))
        self.overlap_row_raw.setValue(int(d.get("overlap_row_raw", 180)))
        self.overlap_col_raw.setValue(int(d.get("overlap_col_raw", 180)))
        self.sigma_spin.setValue(float(d.get("sigma_interval", 2.0)))
        self.mode_combo.setCurrentText(d.get("mode", "sigma mean"))
        self.scan_combo.setCurrentText(d.get("scan_x_direction", "left"))
        self.input_order_combo.setCurrentText(d.get("input_channel_order", "zyx"))
        self.channel_list_edit.setText(d.get("channel_list", ""))
        self.display_channel_spin.setValue(int(d.get("display_channel", 0)))
        self.plot_check.setChecked(bool(d.get("plot", False)))
        self.vmax_spin.setValue(float(d.get("vmax", 2500.0)))
        self.regex_edit.setText(d.get("filename_regex", self.stitcher.filename_regex))
        self.ignorecase_check.setChecked(bool(d.get("ignorecase", True)))
        self._apply_regex_from_ui()
        self._update_overlap_labels()

    def _save_preset(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            None, "Save stitch preset", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._collect_settings(), f, indent=2)
            self.status_lbl.setText(f"Saved preset: {Path(path).name}")
        except Exception as e:
            self.status_lbl.setText(f"Save preset failed: {e}")

    def _load_preset(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            None, "Load stitch preset", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self._apply_settings(d)
            self.status_lbl.setText(f"Loaded preset: {Path(path).name}")
            self._refresh_table()
        except Exception as e:
            self.status_lbl.setText(f"Load preset failed: {e}")

    # ---------------- stitching ----------------
    def stitch(self):
        if self._folder is None:
            self.status_lbl.setText("Choose/drop a folder first.")
            return

        # Apply GUI → stitcher
        N = max(1, int(self.binning_spin.value()))
        self.stitcher.binning = N

        # convert raw overlaps → binned overlaps (stitcher expects binned)
        self.stitcher.overlap_row = int(self.overlap_row_raw.value()) // N
        self.stitcher.overlap_col = int(self.overlap_col_raw.value()) // N

        self.stitcher.sigma_interval = float(self.sigma_spin.value())
        self.stitcher.mode = self.mode_combo.currentText()
        self.stitcher.scan_x_direction = self.scan_combo.currentText()
        self.stitcher.input_channel_order = self.input_order_combo.currentText()
        self.stitcher.channel_list = _parse_int_list(self.channel_list_edit.text())
        self.stitcher.display_channel = int(self.display_channel_spin.value())
        self.stitcher.plot = bool(self.plot_check.isChecked())
        self.stitcher.vmax = float(self.vmax_spin.value())

        print(f"Starting stitching with binning={self.stitcher.binning}, "
              f"overlap_row={self.stitcher.overlap_row}, overlap_col={self.stitcher.overlap_col},"
              f" sigma_interval={self.stitcher.sigma_interval}, mode={self.stitcher.mode}, "
              f"scan_x_direction={self.stitcher.scan_x_direction}, "
              f"input_channel_order={self.stitcher.input_channel_order}, "
              f"channel_list={self.stitcher.channel_list}, ")

        # basic sanity
        if self.stitcher.overlap_row < 0 or self.stitcher.overlap_col < 0:
            self.status_lbl.setText("Overlap must be >= 0.")
            return

        pattern = self.pattern_edit.text().strip() or "*.tif"

        # start worker thread
        self._set_busy(True, "Stitching…")
        self._thread = QtCore.QThread()
        self._thread.setPriority(QtCore.QThread.HighPriority)
        self._worker = _StitchWorker(self.stitcher, str(self._folder), pattern)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_stitch_done)
        self._worker.failed.connect(self._on_stitch_failed)

        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)

        self._thread.start()

    def _on_stitch_done(self, stitched: np.ndarray):
        self._set_busy(False, f"Done. Stitched shape: {getattr(stitched, 'shape', None)}")
        self.stitchedImageChanged.emit(stitched)

    def _on_stitch_failed(self, tb: str):
        logger.error("Stitch failed:\n%s", tb)
        self._set_busy(False, "Stitch failed (see log / traceback).")
        QtWidgets.QMessageBox.critical(None, "Stitching failed", tb)

    def _set_busy(self, busy: bool, status: str):
        self.status_lbl.setText(status)
        self.progress.setVisible(busy)
        self.stitch_btn.setEnabled(not busy)
        self.choose_folder_btn.setEnabled(not busy)
        self.refresh_btn.setEnabled(not busy)
        self.apply_regex_btn.setEnabled(not busy)


