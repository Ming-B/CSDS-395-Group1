# ui/tab_splitter.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Tuple, Dict

from PySide6.QtCore import Qt, QModelIndex, QItemSelection, QItemSelectionModel, Slot
from PySide6.QtWidgets import (
    QWidget, QSplitter, QVBoxLayout, QHBoxLayout, QPushButton, QTreeView,
    QHeaderView, QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox, QFrame,
    QLabel
)

from core.json_model import JsonModel


# ----------------------------- Helper: custom QTreeView with SHIFT same-parent range -----------------------------
class RangeTreeView(QTreeView):
    """
    A tree view that, when SHIFT is held, selects a contiguous range of rows
    among siblings (same parent) between the 'anchor' index and the clicked index.
    - CTRL/CMD works as usual (toggle/add).
    - Regular clicks update anchor.
    - Selection is row-based (both columns).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.anchor_index: QModelIndex | None = None
        self.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        # Light green selection
        self.setStyleSheet(
            "QTreeView::item:selected { background: #d8f5d0; color: black; }"
        )

    def mousePressEvent(self, event):
        idx = self.indexAt(event.pos())
        mods = event.modifiers()

        # SHIFT range only when we have a valid anchor and same parent
        if (mods & Qt.ShiftModifier) and self.anchor_index and idx.isValid():
            a = self.anchor_index.sibling(self.anchor_index.row(), 0)
            b = idx.sibling(idx.row(), 0)
            if a.parent() == b.parent():
                parent = a.parent()
                model = self.model()
                start = min(a.row(), b.row())
                end = max(a.row(), b.row())
                sel = QItemSelection(
                    model.index(start, 0, parent),
                    model.index(end, model.columnCount() - 1, parent),
                )
                sm = self.selectionModel()
                if mods & (Qt.ControlModifier | Qt.MetaModifier):
                    sm.select(sel, QItemSelectionModel.Select | QItemSelectionModel.Rows)
                else:
                    sm.clearSelection()
                    sm.select(sel, QItemSelectionModel.Select | QItemSelectionModel.Rows)
                self.setCurrentIndex(idx)
                # Do not update anchor on SHIFT gesture
                return

        # Default behavior; update anchor on non-SHIFT actions
        super().mousePressEvent(event)
        if not (mods & Qt.ShiftModifier):
            if idx.isValid():
                self.anchor_index = idx

    def reset_anchor(self):
        self.anchor_index = None


# ----------------------------- Data structure for export -----------------------------
@dataclass
class SubPick:
    path: Tuple[Any, ...]   # JSON path from root, keys can be str or int
    display_name: str       # generated human-friendly name (e.g., "mechBattleBalances_branch_1")
    parent_key_label: str   # for branch counting reference


# ----------------------------- Main Tab -----------------------------
class SplitterTab(QWidget):
    """
    Splitter tab:
    - Independent of snapshots/workspace.
    - Left: open a JSON file, browse tree, multi-select substructures (Ctrl/Cmd, Shift same-parent range),
      selected nodes highlighted (light green) until confirmed.
    - Right: confirm selection -> list entries with editable output names and X button to remove.
      Bottom: Choose Output Folder -> export each picked substructure as standalone JSON.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # --- State ---
        self._current_data: Any = None
        self._anon_counter = 1  # for unnamed parents (six-digit base)
        self._branch_counters: Dict[str, int] = {}  # base_name -> last branch idx

        # --- Root Splitter ---
        root = QVBoxLayout(self)
        self.splitter = QSplitter(Qt.Horizontal, self)
        root.addWidget(self.splitter)

        # ================= Left Panel =================
        self.left_panel = QWidget(self)
        left_v = QVBoxLayout(self.left_panel)
        left_v.setContentsMargins(0, 0, 0, 0)
        left_v.setSpacing(8)

        # Top toolbar (Open JSON + Expand/Collapse)
        left_toolbar = QHBoxLayout()
        self.btn_open = QPushButton("Open JSON...", self.left_panel)
        self.btn_expand_all = QPushButton("[]<", self.left_panel); self.btn_expand_all.setToolTip("Expand All")
        self.btn_collapse_all = QPushButton("[]=", self.left_panel); self.btn_collapse_all.setToolTip("Collapse All")
        self.btn_expand_sel = QPushButton("+<", self.left_panel); self.btn_expand_sel.setToolTip("Expand Selection")
        self.btn_collapse_sel = QPushButton("+=", self.left_panel); self.btn_collapse_sel.setToolTip("Collapse Selection")
        left_toolbar.addWidget(self.btn_open)
        left_toolbar.addSpacing(12)
        left_toolbar.addWidget(self.btn_expand_all)
        left_toolbar.addWidget(self.btn_collapse_all)
        left_toolbar.addWidget(self.btn_expand_sel)
        left_toolbar.addWidget(self.btn_collapse_sel)
        left_toolbar.addStretch(1)
        left_v.addLayout(left_toolbar)

        # Tree
        self.tree = RangeTreeView(self.left_panel)
        left_v.addWidget(self.tree, 1)

        # Model (read-only)
        self.model = JsonModel(editable_keys=False, editable_values=False)
        self.tree.setModel(self.model)

        # Header and view tweaks
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.setIndentation(16)
        self.tree.setRootIsDecorated(True)

        # ================= Right Panel =================
        self.right_panel = QWidget(self)
        right_v = QVBoxLayout(self.right_panel)
        right_v.setContentsMargins(0, 0, 0, 0)
        right_v.setSpacing(8)

        # Right top: Confirm Selection
        right_top = QHBoxLayout()
        self.btn_confirm = QPushButton("Confirm Selection", self.right_panel)
        right_top.addWidget(self.btn_confirm)
        right_top.addStretch(1)
        right_v.addLayout(right_top)

        # Table: Picked substructures -> [Name | Output Name | X]
        self.table = QTableWidget(0, 3, self.right_panel)
        self.table.setHorizontalHeaderLabels(["Substructure", "Output Name", "X"])
        th = self.table.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.Stretch)
        th.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        th.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        right_v.addWidget(self.table, 1)

        # Right bottom: Choose output folder to start export
        self.btn_export = QPushButton("Choose Output Folder", self.right_panel)
        right_v.addWidget(self.btn_export, 0)

        # Put panels into splitter
        self.splitter.addWidget(self.left_panel)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setSizes([800, 500])

        # --- Connections ---
        self.btn_open.clicked.connect(self._action_open_json)
        self.btn_expand_all.clicked.connect(self._on_expand_all)
        self.btn_collapse_all.clicked.connect(self._on_collapse_all)
        self.btn_expand_sel.clicked.connect(self._on_expand_selection)
        self.btn_collapse_sel.clicked.connect(self._on_collapse_selection)

        self.btn_confirm.clicked.connect(self._action_confirm_selection)
        self.btn_export.clicked.connect(self._action_choose_output_and_export)

        # Hint label when nothing loaded
        self._hint = QLabel("Open a JSON file to begin.", self.left_panel)
        self._hint.setStyleSheet("color:#666;")
        left_v.addWidget(self._hint, 0)

    # ===================== Left: JSON open / view controls =====================
    def _action_open_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open JSON", "", "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
            data = json.loads(text)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open:\n{path}\n\n{e}")
            return

        self._current_data = data
        self.model.load(data)
        self._hint.hide()
        self.tree.reset_anchor()
        self.tree.expandToDepth(0)

    # View toolbar
    @Slot()
    def _on_expand_all(self):
        self.tree.expandAll()

    @Slot()
    def _on_collapse_all(self):
        self.tree.collapseAll()

    @Slot()
    def _on_expand_selection(self):
        idx = self._current_root_index()
        if not idx.isValid():
            QMessageBox.information(self, "Info", "No selection.")
            return
        self._expand_subtree(idx)

    @Slot()
    def _on_collapse_selection(self):
        idx = self._current_root_index()
        if not idx.isValid():
            QMessageBox.information(self, "Info", "No selection.")
            return
        self._collapse_subtree(idx)

    def _current_root_index(self) -> QModelIndex:
        idx = self.tree.currentIndex()
        if not idx.isValid():
            return QModelIndex()
        return idx.sibling(idx.row(), 0)

    def _expand_subtree(self, index: QModelIndex):
        if not index.isValid():
            return
        self.tree.expand(index)
        m = self.tree.model()
        rows = m.rowCount(index)
        for i in range(rows):
            child = m.index(i, 0, index)
            self._expand_subtree(child)

    def _collapse_subtree(self, index: QModelIndex):
        if not index.isValid():
            return
        m = self.tree.model()
        rows = m.rowCount(index)
        for i in range(rows):
            child = m.index(i, 0, index)
            self._collapse_subtree(child)
        self.tree.collapse(index)

    # ===================== Left -> Right: Confirm Selection =====================
    def _index_to_path(self, index: QModelIndex) -> List[Any]:
        """Return JSON path (list of keys/indices) from root to this item."""
        if not index.isValid():
            return []
        item = index.internalPointer()
        path = []
        cur = item
        while cur and cur.parent() is not None:
            path.append(cur.key)
            cur = cur.parent()
        path.reverse()
        return path

    def _normalize_selection_to_top_most(self, indexes: List[QModelIndex]) -> List[QModelIndex]:
        """Remove descendants when an ancestor is also selected (keep top-most only)."""
        paths = [(tuple(self._index_to_path(idx)), idx) for idx in indexes if idx.isValid()]
        # sort by path length ascending
        paths.sort(key=lambda t: len(t[0]))
        result: List[QModelIndex] = []
        kept_paths: List[Tuple[Any, ...]] = []
        for p, idx in paths:
            if not any(self._is_prefix(existing, p) for existing in kept_paths):
                kept_paths.append(p)
                result.append(idx)
        return result

    @staticmethod
    def _is_prefix(prefix: Tuple[Any, ...], path: Tuple[Any, ...]) -> bool:
        if len(prefix) > len(path):
            return False
        return path[:len(prefix)] == prefix

    def _display_name_for_index(self, idx: QModelIndex, parent_branch_map: Dict[str, int]) -> Tuple[str, str]:
        """
        Return (display_name, parent_key_label) for the given index.
        Rules:
        - If item's key is a string -> use it directly.
        - If item's key is an int (list element):
            - If parent key is string -> use "{parent}_branch_{n}" (n increments per parent).
            - Else -> "{NNNNNN}_branch_{n}", NNNNNN is a global 6-digit counter.
        """
        item = idx.internalPointer()
        key = item.key
        parent_item = item.parent()
        parent_key = parent_item.key if parent_item else None

        if isinstance(key, str) and key != "":
            # named
            return key, f"@self:{key}"

        # list element or unnamed
        # parent named?
        base: str
        if isinstance(parent_key, str) and parent_key != "":
            base = parent_key
        else:
            base = f"{self._anon_counter:06d}"
            self._anon_counter += 1

        # branch count per base
        n = parent_branch_map.get(base, 0) + 1
        parent_branch_map[base] = n
        return f"{base}_branch_{n}", base

    @Slot()
    def _action_confirm_selection(self):
        """Take current tree selection (top-most), generate names, push into right table; clear selection."""
        if self._current_data is None:
            QMessageBox.information(self, "Info", "Please open a JSON file first.")
            return

        sel_rows = self.tree.selectionModel().selectedRows(0)
        if not sel_rows:
            QMessageBox.information(self, "Info", "Please select one or more substructures.")
            return

        # Keep only top-most
        top_most = self._normalize_selection_to_top_most(sel_rows)

        # Prepare parent-base counters for this commit
        parent_branch_map: Dict[str, int] = {}

        for idx in top_most:
            path = tuple(self._index_to_path(idx))
            display_name, parent_label = self._display_name_for_index(idx, parent_branch_map)
            self._add_pick_to_table(SubPick(path=path, display_name=display_name, parent_key_label=parent_label))

        # Clear left selections (green highlight disappears)
        self.tree.selectionModel().clearSelection()
        self.tree.clearSelection()
        self.tree.reset_anchor()

    def _add_pick_to_table(self, pick: SubPick):
        r = self.table.rowCount()
        self.table.insertRow(r)

        # Column 0: display name (read-only) + store path under UserRole
        item_name = QTableWidgetItem(pick.display_name)
        item_name.setFlags(item_name.flags() & ~Qt.ItemFlag.ItemIsEditable)
        # store path for export
        item_name.setData(Qt.ItemDataRole.UserRole, pick.path)
        self.table.setItem(r, 0, item_name)

        # Column 1: output name (editable) default: display_name + .json
        default_out = pick.display_name + ".json" if not pick.display_name.lower().endswith(".json") else pick.display_name
        item_out = QTableWidgetItem(default_out)
        self.table.setItem(r, 1, item_out)

        # Column 2: X (remove)
        btn_x = QPushButton("X", self.table)
        btn_x.setToolTip("Remove this row")
        btn_x.clicked.connect(self._remove_row_clicked)
        self.table.setCellWidget(r, 2, btn_x)

    def _remove_row_clicked(self):
        btn = self.sender()
        if not btn:
            return
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 2) is btn:
                self.table.removeRow(r)
                break

    # ===================== Export =====================
    def _get_by_path(self, data: Any, path: Tuple[Any, ...]) -> Any:
        ref = data
        for k in path:
            ref = ref[k]
        return ref

    @Slot()
    def _action_choose_output_and_export(self):
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "Info", "No items to export. Confirm a selection first.")
            return
        if self._current_data is None:
            QMessageBox.information(self, "Info", "Please open a JSON file first.")
            return

        out_dir = QFileDialog.getExistingDirectory(self, "Choose Output Folder", "")
        if not out_dir:
            return

        # iterate rows
        ok_count = 0
        for r in range(self.table.rowCount()):
            name_item = self.table.item(r, 0)
            out_item = self.table.item(r, 1)
            if not name_item:
                continue

            path = name_item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(path, tuple):
                continue

            # output file name
            out_name = (out_item.text().strip() if out_item else "") or (name_item.text() + ".json")
            out_name = os.path.basename(out_name)
            if not out_name.lower().endswith(".json"):
                out_name += ".json"
            out_path = os.path.join(out_dir, out_name)

            # extract and write
            try:
                sub = self._get_by_path(self._current_data, path)
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(sub, f, ensure_ascii=False, indent=4)
                # mark row green
                name_item.setForeground(Qt.GlobalColor.darkGreen)
                ok_count += 1
            except Exception as e:
                # mark row red and show error in tooltip
                name_item.setForeground(Qt.GlobalColor.red)
                name_item.setToolTip(str(e))

        QMessageBox.information(self, "Done", f"Exported {ok_count} item(s).")
