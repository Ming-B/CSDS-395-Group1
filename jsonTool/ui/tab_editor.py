# ui/tab_editor.py
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeView, QHeaderView, QPushButton,
    QMessageBox, QApplication, QAbstractItemView, QToolButton, QMenu
)
from PySide6.QtCore import Slot, QModelIndex

from jsonTool.core.json_model import JsonModel
from jsonTool.core.document import JSONDocument
from jsonTool.core.recent_files import RecentFilesManager
from jsonTool.core.database import get_database_manager


from jsonTool.ui.models.delegates import OverlayHintDelegate



class EditorTab(QWidget):
    """Editor tab: editable (keys & values), subscribes to JSONDocument for refresh, and preserves view state."""

    def __init__(self, parent=None, document: JSONDocument | None = None):
        super().__init__(parent)

        self.document = document
        self._set_busy_cb = None

        # ---- 使用 RecentFilesManager（和 Viewer 共用一份 recent list）----
        self.recent_mgr = RecentFilesManager("config/user.json")
        self.db_mgr = get_database_manager()
        self._current_file: str | None = None  # 仅用于标题显示

        # ---- Layout ----
        root_layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        # 精简符号 + 英文 tooltip
        self.btn_expand_all = QPushButton("⬇️📁", self)
        self.btn_expand_all.setToolTip("Expand All")
        self.btn_collapse_all = QPushButton("⬆️📁", self)
        self.btn_collapse_all.setToolTip("Collapse All")
        self.btn_expand_sel = QPushButton("➡️📄", self)
        self.btn_expand_sel.setToolTip("Expand Selection")
        self.btn_collapse_sel = QPushButton("⬅️📄", self)
        self.btn_collapse_sel.setToolTip("Collapse Selection")
        # self.btn_toggle_save = QPushButton("Save", self)
        # self.btn_toggle_save.setToolTip("Save")

        toolbar.addWidget(self.btn_expand_all)
        toolbar.addWidget(self.btn_collapse_all)
        toolbar.addWidget(self.btn_expand_sel)
        toolbar.addWidget(self.btn_collapse_sel)
        # toolbar.addWidget(self.btn_toggle_save)
        toolbar.addStretch(1)
        root_layout.addLayout(toolbar)

        # —— 文件选择行：左侧显示当前文件名，右侧 ▼ 下拉 —— #
        file_row = QHBoxLayout()
        self.title_btn = QPushButton("(No file)", self)
        self.title_btn.setEnabled(False)  # 只用来显示名称
        self.menu_btn = QToolButton(self)
        self.menu_btn.setText("▼")
        self.menu_btn.setFixedWidth(28)
        self.menu_btn.setToolTip("Choose a file to edit")
        self.menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)  # 点击即弹出
        file_row.addWidget(self.title_btn, 1)
        file_row.addWidget(self.menu_btn, 0)
        root_layout.addLayout(file_row)

        self.tree_view = QTreeView(self)
        root_layout.addWidget(self.tree_view)

        # Model - EDITABLE (keys + values)
        self.model = JsonModel(editable_keys=True, editable_values=True)
        self.tree_view.setModel(self.model)

        header = self.tree_view.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree_view.setIndentation(16)
        self.tree_view.setRootIsDecorated(True)

        self._edit_delegate = OverlayHintDelegate(self.tree_view)
        self.tree_view.setItemDelegate(self._edit_delegate)

        # Edit triggers: double-click / Enter(F2) / selected-click
        self.tree_view.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
        )

        # Preserve/restore view state around model resets (when structure changes)
        self._saved_expanded_paths: list[list[object]] = []
        self._saved_current_path: list[object] | None = None
        self._saved_scroll: int = 0
        self._pending_restore_state: dict | None = None  # state injected by MainWindow when loading a snapshot
        self.model.modelAboutToBeReset.connect(self._save_view_state)
        self.model.modelReset.connect(self._restore_view_state)

        # View tweaks
        header = self.tree_view.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree_view.setIndentation(16)
        self.tree_view.setRootIsDecorated(True)

        # Connect toolbar actions
        self.btn_expand_all.clicked.connect(self._on_expand_all)
        self.btn_collapse_all.clicked.connect(self._on_collapse_all)
        self.btn_expand_sel.clicked.connect(self._on_expand_selection)
        self.btn_collapse_sel.clicked.connect(self._on_collapse_selection)
        # self.btn_toggle_save.clicked.connect(self._on_save)

        # Bind document
        # 绑定文档：首次载入 + 监听变化
        if self.document is not None:
            if self.document.get_data() is not None:
                self.model.load(self.document.get_data())
                self._update_title_from_document()
                if getattr(self.document, "file_path", None):
                    self.recent_mgr.add_file(self.document.file_path)
            self.document.dataChanged.connect(self.on_document_changed)

        # 连接按钮
        self.btn_expand_all.clicked.connect(self._on_expand_all)
        self.btn_collapse_all.clicked.connect(self._on_collapse_all)
        self.btn_expand_sel.clicked.connect(self._on_expand_selection)
        self.btn_collapse_sel.clicked.connect(self._on_collapse_selection)
        # self.btn_toggle_save.clicked.connect(self._on_save)

        # 构建下拉菜单
        self._rebuild_editor_menu()
        self.model.dataChanged.connect(self._on_model_data_changed)

    # ------------ Busy banner callback injection ------------
    def set_busy_callback(self, cb):
        """Inject a callable like MainWindow.set_busy(bool, msg?)."""
        self._set_busy_cb = cb

    def _busy(self, on: bool, msg: str = "Working... please do not repeat operations"):
        """Convenience wrapper for toggling busy banner if available."""
        if callable(self._set_busy_cb):
            self._set_busy_cb(on, msg)
            QApplication.processEvents()

    # ---------- Document updates ----------
    @Slot(object)
    def on_document_changed(self, data):
        self.model.load(data)
        self._update_title_from_document()
        if getattr(self.document, "file_path", None):
            self.db_mgr.edit_json_file(self.index, data)
            self._rebuild_editor_menu()

    def _on_model_data_changed(self, top_left: QModelIndex, bottom_right: QModelIndex, roles: list[int] = []):
        # Get updated JSON from model
        data = self.model.to_json()
        # Update your document
        if self.document:
            self.document.set_data(data)
        # Save via database manager
        if hasattr(self, "index"):
            # you set self.index when loading via DB
            success = self.db_mgr.edit_json_file(self.index, data)
            if not success:
                QMessageBox.critical(self, "Save Error", "Failed to save changes to the database")
            else:
                print(f"Saved changes for index {self.index}")


    def _update_title_from_document(self):
        fp = getattr(self.document, "file_path", None)
        self._current_file = fp if isinstance(fp, str) else None
        self.title_btn.setText(Path(fp).name if fp else "(No file)")

    # ---------- Public API for MainWindow ----------
    def current_json(self):
        """Return current edited JSON (without writing to disk)."""
        return self.model.to_json()

    def capture_view_state(self) -> dict:
        """Capture expand/selection/scroll for snapshot meta."""
        expanded = []

        m = self.tree_view.model()

        def dfs(parent_index: QModelIndex, prefix_path: list):
            rows = m.rowCount(parent_index)
            for r in range(rows):
                idx = m.index(r, 0, parent_index)
                ti = idx.internalPointer()
                item_path = prefix_path + [ti.key]
                if self.tree_view.isExpanded(idx):
                    expanded.append(item_path)
                dfs(idx, item_path)

        dfs(QModelIndex(), [])
        cur_path = None
        cur = self.tree_view.currentIndex()
        if cur.isValid():
            cur_path = self._index_to_path(cur.sibling(cur.row(), 0))

        return {
            "expanded_paths": expanded,
            "current_path": cur_path,
            "scroll": self.tree_view.verticalScrollBar().value(),
        }

    def schedule_restore_view_state(self, state: dict | None):
        """Provide a pending state to be restored after the model resets."""
        self._pending_restore_state = state or None

    def set_data(self, data):
        self.model.load(data)

    def clear(self):
        self.model.clear()

    # ---------- 下拉菜单相关 ----------
    def _rebuild_editor_menu(self):
        """Rebuild dropdown menu for the editor using database files."""
        menu = QMenu(self.menu_btn)
        files = self.db_mgr.get_all_files()

        if not files:
            a = menu.addAction("(no stored files)")
            a.setEnabled(False)
        else:
            for file_info in files:
                name = file_info["file_name"]
                index = file_info["index"]
                act = menu.addAction(name)
                act.setToolTip(f"Index: {index}")
                act.triggered.connect(
                    lambda checked=False, idx=index: self._choose_file_for_editor_by_index(1, idx)
                )

        self.menu_btn.setMenu(menu)

    def _choose_file_for_editor_by_index(self, which: int, index: int):
        """Load a JSON file from the database into the editor."""
        file_data = self.db_mgr.get_file_by_index(index)
        if not file_data:
            QMessageBox.warning(self, "Load Failed", "Unable to load file from database.")
            return

        json_data = file_data["data"]
        file_name = file_data["file_name"]

        # --- Update model ---
        self.model.load(json_data)

        if self.document is None:
            self.document = JSONDocument()  # create one if missing
            
        self.document.set_data(self.model.to_json())
        self.document.file_path = file_name  # <-- set this!
        self.index = index

        # --- Update title ---
        self.title_btn.setText(file_name)
        self._current_file = file_name

        # --- Add to recent files list ---
        self.recent_mgr.add_file(file_name)

        print(f"[Editor] Loaded file {file_name} (index {index})")


    # ---------- Toolbar handlers ----------
    @Slot()
    def _on_expand_all(self):
        self._busy(True)
        try:
            self.tree_view.expandAll()
        finally:
            self._busy(False)

    @Slot()
    def _on_collapse_all(self):
        self._busy(True)
        try:
            self.tree_view.collapseAll()
        finally:
            self._busy(False)

    @Slot()
    def _on_expand_selection(self):
        idx = self._current_root_index()
        if not idx.isValid():
            QMessageBox.information(self, "Info", "No selection.")
            return
        self._busy(True)
        try:
            self._expand_subtree(idx)
        finally:
            self._busy(False)

    @Slot()
    def _on_collapse_selection(self):
        idx = self._current_root_index()
        if not idx.isValid():
            QMessageBox.information(self, "Info", "No selection.")
            return
        self._busy(True)
        try:
            self._collapse_subtree(idx)
        finally:
            self._busy(False)


    # ---------- Helpers ----------
    def _current_root_index(self) -> QModelIndex:
        """Return the selected index normalized to column 0 (the tree column)."""
        idx = self.tree_view.currentIndex()
        if not idx.isValid():
            return QModelIndex()
        return idx.sibling(idx.row(), 0)

    def _expand_subtree(self, index: QModelIndex):
        """Expand the node and all its descendants."""
        if not index.isValid():
            return
        self.tree_view.expand(index)
        m = self.tree_view.model()
        rows = m.rowCount(index)
        for i in range(rows):
            child = m.index(i, 0, index)
            self._expand_subtree(child)

    def _collapse_subtree(self, index: QModelIndex):
        """Collapse the node and all its descendants."""
        if not index.isValid():
            return
        m = self.tree_view.model()
        rows = m.rowCount(index)
        for i in range(rows):
            child = m.index(i, 0, index)
            self._collapse_subtree(child)
        self.tree_view.collapse(index)

    # ---------- View-state save/restore around model reset ----------
    def _index_to_path(self, index: QModelIndex) -> list:
        """Convert QModelIndex to a path list of keys/indexes."""
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

    def _save_view_state(self):
        """Save expanded nodes, current selection and scroll before model reset."""
        self._saved_expanded_paths.clear()
        self._saved_current_path = None
        self._saved_scroll = self.tree_view.verticalScrollBar().value()

        m = self.tree_view.model()

        def dfs(parent_index: QModelIndex, prefix_path: list):
            rows = m.rowCount(parent_index)
            for r in range(rows):
                idx = m.index(r, 0, parent_index)
                ti = idx.internalPointer()
                item_path = prefix_path + [ti.key]
                if self.tree_view.isExpanded(idx):
                    self._saved_expanded_paths.append(item_path)
                dfs(idx, item_path)

        dfs(QModelIndex(), [])

        cur = self.tree_view.currentIndex()
        if cur.isValid():
            self._saved_current_path = self._index_to_path(cur.sibling(cur.row(), 0))

    def _restore_view_state(self):
        """Restore expanded nodes, current selection and scroll after model reset."""
        state = self._pending_restore_state
        use_pending = state is not None

        if not use_pending:
            state = {
                "expanded_paths": self._saved_expanded_paths,
                "current_path": self._saved_current_path,
                "scroll": self._saved_scroll,
            }

        m = self.tree_view.model()

        def find_index_by_path(path: list) -> QModelIndex | None:
            parent = QModelIndex()
            for depth_key in path or []:
                found = None
                rows = m.rowCount(parent)
                for r in range(rows):
                    idx = m.index(r, 0, parent)
                    ti = idx.internalPointer()
                    if ti.key == depth_key:
                        found = idx
                        break
                if found is None:
                    return None
                parent = found
            return parent

        for p in state.get("expanded_paths") or []:
            idx = find_index_by_path(p)
            if idx is not None:
                self.tree_view.expand(idx)

        curp = state.get("current_path")
        if curp:
            idx = find_index_by_path(curp)
            if idx is not None:
                self.tree_view.setCurrentIndex(idx)

        scr = state.get("scroll")
        if isinstance(scr, int):
            self.tree_view.verticalScrollBar().setValue(scr)

        # Clear caches
        self._saved_expanded_paths.clear()
        self._saved_current_path = None
        self._pending_restore_state = None
