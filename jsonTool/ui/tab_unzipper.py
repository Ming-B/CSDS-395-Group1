# ui/tab_unzipper.py
from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, List, Tuple

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QPushButton, QTableWidget, QTableWidgetItem, QFileDialog,
    QHeaderView, QListWidget, QListWidgetItem, QMenu, QMessageBox
)

# -------- optional dependency (MsgPack) --------
try:
    import msgpack  # type: ignore
except Exception:  # pragma: no cover
    msgpack = None


# ========= Worker =========
@dataclass
class DecodeTask:
    input_path: str
    output_name: str   # file name only, no directory
    decoder: str       # decoder id, e.g., "msgpack"


class DecodeWorker(QThread):
    progressed = Signal(str, str, bool, str)  # input_path, output_path, ok, message

    def __init__(self, tasks: List[DecodeTask], out_dir: str, parent=None):
        super().__init__(parent)
        self.tasks = tasks
        self.out_dir = out_dir

    def _decode_msgpack(self, input_path: str) -> object:
        if msgpack is None:
            raise RuntimeError(
                "MsgPack decoder not available. Please install 'msgpack' package."
            )
        with open(input_path, "rb") as f:
            return msgpack.unpack(f, strict_map_key=False)

    def _ensure_json_name(self, name: str) -> str:
        # sanitize: keep only basename; append .json if missing
        base = os.path.basename(name.strip()) or "output.json"
        if not base.lower().endswith(".json"):
            base += ".json"
        return base

    def _write_json(self, data: object, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def run(self):
        for task in self.tasks:
            in_path = task.input_path
            try:
                if not os.path.isfile(in_path):
                    raise FileNotFoundError(in_path)

                # decode
                if task.decoder == "msgpack":
                    data = self._decode_msgpack(in_path)
                else:
                    raise ValueError(f"Unsupported decoder: {task.decoder}")

                out_name = self._ensure_json_name(task.output_name or Path(in_path).stem + ".json")
                out_path = Path(self.out_dir) / out_name

                # write json
                self._write_json(data, out_path)

                self.progressed.emit(in_path, out_path, True, "OK")
            except Exception as e:  # pragma: no cover
                self.progressed.emit(in_path, "", False, str(e))


# ========= Main Tab =========
class UnzipperTab(QWidget):
    """
    Independent tab to decode binary-compressed files into readable JSON.
    - No snapshot/workspace integration.
    - Left: choose multiple files, per-file output name, decoder selection.
    - Right: choose output folder -> start, list shows finished tasks in green (errors in red).
    """

    SUPPORTED_DECODERS: List[Tuple[str, str]] = [
        ("MsgPack", "msgpack"),  # (label, id)
        # future: ("CBOR", "cbor"), ("BSON", "bson"), ...
    ]

    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_decoder_label = "MsgPack"
        self.current_decoder_id = "msgpack"
        self.output_dir: Optional[str] = None
        self.worker: Optional[DecodeWorker] = None

        # ---------- Root layout with splitter ----------
        root = QHBoxLayout(self)
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        root.addWidget(self.splitter)

        # ---------- Left side ----------
        self.left_panel = QWidget(self)
        left_v = QVBoxLayout(self.left_panel)
        left_v.setContentsMargins(0, 0, 0, 0)
        left_v.setSpacing(8)

        # Top row: [Choose Files...]  [Decoder ▾]
        left_top = QHBoxLayout()
        self.btn_choose_files = QPushButton("Choose Files...", self.left_panel)
        self.btn_decoder = QPushButton(f"Decoder ▾  ({self.current_decoder_label})", self.left_panel)
        left_top.addWidget(self.btn_choose_files)
        left_top.addWidget(self.btn_decoder)
        left_top.addStretch(1)
        left_v.addLayout(left_top)

        # Table: Input File | Output Name | X
        self.table = QTableWidget(0, 3, self.left_panel)
        self.table.setHorizontalHeaderLabels(["Input File", "Output Name", "X"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.AllEditTriggers)
        left_v.addWidget(self.table, 1)

        self.splitter.addWidget(self.left_panel)

        # ---------- Right side ----------
        self.right_panel = QWidget(self)
        right_v = QVBoxLayout(self.right_panel)
        right_v.setContentsMargins(0, 0, 0, 0)
        right_v.setSpacing(8)

        # Top row: [Choose Output Folder...]
        self.btn_choose_output = QPushButton("Choose Output Folder...", self.right_panel)
        right_v.addWidget(self.btn_choose_output, 0)

        # Progress list
        self.progress_list = QListWidget(self.right_panel)
        right_v.addWidget(self.progress_list, 1)

        self.splitter.addWidget(self.right_panel)
        self.splitter.setSizes([800, 400])

        # ---------- Connections ----------
        self.btn_choose_files.clicked.connect(self._action_choose_files)
        self.btn_choose_output.clicked.connect(self._action_choose_output)

        # Decoder menu
        menu = QMenu(self.btn_decoder)
        for label, dec_id in self.SUPPORTED_DECODERS:
            act = menu.addAction(label)
            act.triggered.connect(lambda checked=False, l=label, i=dec_id: self._set_decoder(l, i))
        self.btn_decoder.setMenu(menu)

    # ================== UI Actions ==================
    def _action_choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Choose Files",
            "",
            "All Files (*);;MsgPack Files (*.msgpack *.mpk *.mp *.bin)"
        )
        if not paths:
            return
        self._add_files(paths)

    def _action_choose_output(self):
        out_dir = QFileDialog.getExistingDirectory(self, "Choose Output Folder", "")
        if not out_dir:
            return
        self.output_dir = out_dir
        # Start immediately after folder chosen
        self._start_decoding()

    def _set_decoder(self, label: str, dec_id: str):
        self.current_decoder_label = label
        self.current_decoder_id = dec_id
        self.btn_decoder.setText(f"Decoder ▾  ({label})")

    # ================== Table Helpers ==================
    def _add_files(self, paths: List[str]):
        for p in paths:
            p = str(Path(p).resolve())
            if not os.path.isfile(p):
                continue
            # skip duplicates already in table
            if self._find_row_by_input(p) != -1:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)

            # col 0: input path (read-only)
            item_in = QTableWidgetItem(p)
            item_in.setFlags(item_in.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item_in)

            # col 1: output name (editable) -> default: basename + .json
            default_name = Path(p).stem + ".json"
            item_out = QTableWidgetItem(default_name)
            self.table.setItem(row, 1, item_out)

            # col 2: remove button "X"
            btn_x = QPushButton("X", self.table)
            btn_x.setToolTip("Remove this file")
            btn_x.clicked.connect(self._remove_row_clicked)
            self.table.setCellWidget(row, 2, btn_x)

    def _find_row_by_input(self, input_path: str) -> int:
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it and it.text() == input_path:
                return r
        return -1

    def _remove_row_clicked(self):
        btn = self.sender()
        if not btn:
            return
        # locate which row this button is in
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 2) is btn:
                self.table.removeRow(r)
                break

    # ================== Decoding Flow ==================
    def _collect_tasks(self) -> List[DecodeTask]:
        tasks: List[DecodeTask] = []
        for r in range(self.table.rowCount()):
            in_item = self.table.item(r, 0)
            out_item = self.table.item(r, 1)
            if not in_item:
                continue
            in_path = in_item.text().strip()
            out_name = (out_item.text().strip() if out_item else "") or (Path(in_path).stem + ".json")
            # sanitize file name: basename only
            out_name = os.path.basename(out_name)
            tasks.append(DecodeTask(input_path=in_path, output_name=out_name, decoder=self.current_decoder_id))
        return tasks

    def _start_decoding(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Busy", "Decoding is in progress.")
            return
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "Info", "Please choose at least one file.")
            return
        if not self.output_dir:
            QMessageBox.information(self, "Info", "Please choose an output folder.")
            return

        tasks = self._collect_tasks()
        if not tasks:
            QMessageBox.information(self, "Info", "Nothing to do.")
            return

        # clear previous progress
        self.progress_list.clear()

        # disable buttons while working
        self._set_enabled(False)

        # start worker
        self.worker = DecodeWorker(tasks, self.output_dir, self)
        self.worker.progressed.connect(self._on_task_progress)
        self.worker.finished.connect(lambda: self._set_enabled(True))
        self.worker.start()

    def _set_enabled(self, enabled: bool):
        self.btn_choose_files.setEnabled(enabled)
        self.btn_choose_output.setEnabled(enabled)
        self.btn_decoder.setEnabled(enabled)
        self.table.setEnabled(enabled)

    def _on_task_progress(self, input_path: str, output_path: str, ok: bool, message: str):
        name = Path(input_path).name
        if ok:
            item = QListWidgetItem(f"{name}  →  {Path(output_path).name}")
            item.setForeground(Qt.GlobalColor.darkGreen)
        else:
            item = QListWidgetItem(f"{name}  ✖  {message}")
            item.setForeground(Qt.GlobalColor.red)
        self.progress_list.addItem(item)
        self.progress_list.scrollToBottom()

    # ================== Config / Persistence (none) ==================
    # Intentionally no snapshot/workspace interfaces here.


# ========== Minimal hook for manual testing ==========
if __name__ == "__main__":  # pragma: no cover
    # simple preview if you run this file directly
    from PySide6.QtWidgets import QApplication
    import sys
    app = QApplication(sys.argv)
    w = UnzipperTab()
    w.resize(1024, 600)
    w.show()
    sys.exit(app.exec())
