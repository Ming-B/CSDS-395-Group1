from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeView, QHeaderView, QPushButton,
    QMessageBox, QApplication, QLabel, QSplitter, QMenu, QFrame, QScrollArea
)
from PySide6.QtCore import Slot, QModelIndex, Qt

from jsonTool.core.json_model import JsonModel
from jsonTool.core.document import JSONDocument

from jsonTool.core.database import get_database_manager
from PySide6.QtCore import Signal


class ViewerTab(QWidget):
    filesChanged = Signal()
    """Viewer tab: read-only tree with local expand/collapse toolbar, single/double readers,
    right-side recent file list, per-reader file chooser, and view-state preservation.

    Notes:
    - 保留原有公共接口与核心行为。
    - 工具栏按钮使用精简符号并提供英文 tooltip。
    - [ | ] 按钮切换单/双阅读器。
    - 右侧竖栏展示 recent_files（存于 config/user.json），每行末尾有 'X' 删除记录。
    - 每个阅读器顶部显示当前文件名 + ▼ 下拉（与右栏同步）。
    - Viewer 只读、与 Editor 独立；不会写入 workspace 快照。
    """

    # ----------------------------- INIT -----------------------------
    def __init__(self, parent=None, document: JSONDocument | None = None):
        super().__init__(parent)

        # External document (兼容现有应用流程)
        self.document = document
        self._set_busy_cb = None  # MainWindow may inject set_busy

        # Config/user.json
        self._root_dir = Path(__file__).resolve().parents[1]
        self._config_dir = self._root_dir / "config"
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._config_file = self._config_dir / "user.json"

        # Unified recent file manager (sharing the same user.json with Editor)
        # self.recent_mgr = RecentFilesManager(str(self._config_file))

        # Reader states
        self._double_mode: bool = False
        # Reader #1 跟随全局 document；若用户通过 ▼ 选择了文件，则锁定到该文件
        self._pane1_locked_to_file: bool = False
        self._pane1_file_path: str | None = None  # 锁定时记录路径
        self._pane2_file_path: str | None = None  # 右侧阅读器文件路径（双窗模式时）

        # ---- Root layout: Top toolbar + Splitter(main readers + right sidebar) ----
        root_layout = QVBoxLayout(self)

        # ---------- Toolbar row ----------
        toolbar = QHBoxLayout()
        # 精简符号 + 英文 tooltip
        # []<   +<   []=   +=
        self.btn_expand_all = QPushButton("⬇️📁", self)
        self.btn_expand_all.setToolTip("Expand All")
        self.btn_collapse_all = QPushButton("⬆️📁", self)
        self.btn_collapse_all.setToolTip("Collapse All")
        self.btn_expand_sel = QPushButton("➡️📄", self)
        self.btn_expand_sel.setToolTip("Expand Selection")
        self.btn_collapse_sel = QPushButton("⬅️📄", self)
        self.btn_collapse_sel.setToolTip("Collapse Selection")

        # 单/双阅读器切换：[ | ]
        self.btn_toggle_double = QPushButton("🪟🪟", self)
        self.btn_toggle_double.setToolTip("Double Windows")
        # self.btn_toggle_save = QPushButton("Save", self)
        # self.btn_toggle_save.setToolTip("Save")

        toolbar.addWidget(self.btn_expand_all)
        toolbar.addWidget(self.btn_collapse_all)
        toolbar.addWidget(self.btn_expand_sel)
        toolbar.addWidget(self.btn_collapse_sel)
        toolbar.addSpacing(8)
        toolbar.addWidget(self.btn_toggle_double)
        # Add save button right after the double window button
        # toolbar.addWidget(self.btn_toggle_save)
        toolbar.addStretch(1)
        root_layout.addLayout(toolbar)

        # ---------- Splitter: left(main readers) | right(recent list) ----------
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        root_layout.addWidget(self.splitter)

        # ----- Left composite: two reader blocks (second is hidden in single mode) -----
        self.left_composite = QWidget(self)
        self.left_layout = QHBoxLayout(self.left_composite)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(8)

        # Reader #1 block (header + tree)
        self.reader1 = self._make_reader_block()
        self.left_layout.addWidget(self.reader1["frame"], 1)

        # Reader #2 block（默认隐藏，启用双窗时显示）
        self.reader2 = self._make_reader_block()
        self.reader2["frame"].setVisible(False)
        self.left_layout.addWidget(self.reader2["frame"], 1)

        self.splitter.addWidget(self.left_composite)

        # ----- Right sidebar: recent files vertical list with remove 'X' -----
        self.right_sidebar = self._make_right_sidebar()
        self.splitter.addWidget(self.right_sidebar["frame"])
        self.splitter.setSizes([800, 220])

        # ---------- Models and tree setup ----------
        # 左阅读器模型（只读）
        self.model = JsonModel(editable_keys=False, editable_values=False)
        self.reader1["tree"].setModel(self.model)
        # 右阅读器模型（只读）
        self.model2 = JsonModel(editable_keys=False, editable_values=False)
        self.reader2["tree"].setModel(self.model2)

        # 视图参数
        self._tune_tree(self.reader1["tree"])
        self._tune_tree(self.reader2["tree"])

        # 当前操作的 Tree（工具栏对其生效）
        self._active_tree: QTreeView = self.reader1["tree"]
        self.reader1["tree"].focusInEvent = self._wrap_focus_in(self.reader1["tree"], self.reader1["tree"].focusInEvent)
        self.reader2["tree"].focusInEvent = self._wrap_focus_in(self.reader2["tree"], self.reader2["tree"].focusInEvent)

        # 左阅读器的视图状态保存/恢复（用于 MainWindow 切换快照时正确展开/定位/滚动）
        self._saved_expanded_paths: list[list[object]] = []
        self._saved_current_path: list[object] | None = None
        self._saved_scroll: int = 0
        self._pending_restore_state: dict | None = None
        self.model.modelAboutToBeReset.connect(self._save_view_state)
        self.model.modelReset.connect(self._restore_view_state)

        # 事件连接
        self.btn_expand_all.clicked.connect(self._on_expand_all)
        self.btn_collapse_all.clicked.connect(self._on_collapse_all)
        self.btn_expand_sel.clicked.connect(self._on_expand_selection)
        self.btn_collapse_sel.clicked.connect(self._on_collapse_selection)
        self.btn_toggle_double.clicked.connect(self._toggle_double_mode)
        # self.btn_toggle_save.clicked.connect(self._on_save)

        # Reader 顶部 ▼ 菜单（与右栏 recent_files 同步）
        self._rebuild_reader_menu(self.reader1, which=1)
        self._rebuild_reader_menu(self.reader2, which=2)

        # 绑定全局 document（左阅读器在未锁定时跟随）
        if self.document is not None:
            if self.document.get_data() is not None:
                self.model.load(self.document.get_data())
                self._update_reader_title_from_doc(self.reader1, default_label="(Current Document)")
            self.document.dataChanged.connect(self.on_document_changed)

        # 根据 config 构建右侧 recent 列表
        self._refresh_stored_sidebar()

    # ----------------------------- UI HELPERS -----------------------------
    def _tune_tree(self, tree: QTreeView):
        header = tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        tree.setIndentation(16)
        tree.setRootIsDecorated(True)
        tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)

    def _wrap_focus_in(self, tree: QTreeView, orig_handler):
        def _handler(event):
            self._active_tree = tree
            if callable(orig_handler):
                return orig_handler(event)
            return None
        return _handler

    def _make_reader_block(self) -> dict:
        """Create a (frame -> vbox -> header(hbox: title btn + ▼) + tree)."""
        frame = QFrame(self)
        frame.setFrameShape(QFrame.Shape.NoFrame)
        vbox = QVBoxLayout(frame)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(4)

        # header: filename label button + ▼ menu button
        header_h = QHBoxLayout()
        header_h.setContentsMargins(0, 0, 0, 0)
        header_h.setSpacing(6)

        title_btn = QPushButton("(Current Document)", frame)
        title_btn.setToolTip("Click the ▼ on the right to choose a file for this reader")
        title_btn.setEnabled(False)  # 显示用

        menu_btn = QPushButton("▼", frame)
        menu_btn.setFixedWidth(24)
        menu_btn.setToolTip("Choose a file for this reader")

        header_h.addWidget(title_btn, 1)
        header_h.addWidget(menu_btn, 0)
        vbox.addLayout(header_h)

        tree = QTreeView(frame)
        vbox.addWidget(tree, 1)

        return {"frame": frame, "vbox": vbox, "title": title_btn, "menu_btn": menu_btn, "tree": tree}

    # ---------------- Sidebar creation ----------------
    def _make_right_sidebar(self) -> dict:
        """Right vertical list panel showing stored files from database with 'X' removers."""
        self.db_mgr = get_database_manager()

        frame = QFrame(self)
        frame.setMinimumWidth(220)
        frame.setMaximumWidth(340)
        frame.setFrameShape(QFrame.Shape.StyledPanel)

        vbox = QVBoxLayout(frame)
        vbox.setContentsMargins(6, 6, 6, 6)
        vbox.setSpacing(6)

        title = QLabel("Stored Files", frame)
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        title.setStyleSheet("font-weight: 600;")
        vbox.addWidget(title)

        scroll = QScrollArea(frame)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        content_v = QVBoxLayout(content)
        content_v.setContentsMargins(0, 0, 0, 0)
        content_v.setSpacing(4)
        content_v.addStretch(1)  # tail stretch
        scroll.setWidget(content)
        vbox.addWidget(scroll, 1)

        return {"frame": frame, "scroll": scroll, "content": content, "content_v": content_v}

    # ---------------- Add a file row ----------------
    def _right_add_item(self, file_info: dict):
        """Add a row to the right sidebar for a stored file with 'X' to remove."""
        index = file_info["index"]
        name = file_info["file_name"]

        row = QFrame(self.right_sidebar["content"])
        row.setFrameShape(QFrame.Shape.StyledPanel)
        row.setStyleSheet("QFrame { border: 0px solid #ddd; border-radius: 6px; }")
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(6)

        label = QLabel(name, row)
        label.setToolTip(f"Index: {index}")
        label.mousePressEvent = lambda e, idx=index: self._file_clicked(idx)

        btn_x = QPushButton("X", row)
        btn_x.setFixedWidth(22)
        btn_x.setToolTip("Remove from database")
        btn_x.clicked.connect(lambda _, idx=index: self._remove_file_and_refresh(idx))

        h.addWidget(label, 1)
        h.addWidget(btn_x, 0)

        cv = self.right_sidebar["content_v"]
        cv.insertWidget(cv.count() - 1, row)

    # ---------------- Remove a file ----------------
    def _remove_file_and_refresh(self, index: int):
        """Remove file from database and refresh sidebar."""
        self.db_mgr.delete_json_by_index(index)
        self._refresh_stored_sidebar()
        self.filesChanged.emit()

    # ---------------- Refresh sidebar ----------------
    def _refresh_stored_sidebar(self):
        """Clear sidebar and reload all files from database."""
        cv = self.right_sidebar["content_v"]
        for i in reversed(range(cv.count() - 1)):
            item = cv.itemAt(i)
            w = item.widget()
            if w:
                w.setParent(None)

        for file_info in self.db_mgr.get_all_files():
            self._right_add_item(file_info)

        # Optional: sync dropdown menus
        self._rebuild_reader_menu(self.reader1, which=1)
        self._rebuild_reader_menu(self.reader2, which=2)

    # ---------------- Rebuild reader menu ----------------
    def _rebuild_reader_menu(self, reader_block: dict, which: int):
        """Rebuild dropdown menu for a reader using database files."""
        btn = reader_block["menu_btn"]
        menu = QMenu(btn)

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
                act.triggered.connect(lambda checked=False, idx=index, w=which: self._choose_file_for_reader_by_index(w, idx))

        btn.setMenu(menu)

    # ---------------- Optional: file clicked handler ----------------
    def _file_clicked(self, index: int):
        """Handle click on a file in the sidebar."""
        file_data = self.db_mgr.get_file_by_index(index)
        print("File clicked:", file_data)

    # ---------------- Optional: choose file for reader ----------------
    def _choose_file_for_reader_by_index(self, which: int, index: int):
        """Load selected file into a reader."""
        file_data = self.db_mgr.get_file_by_index(index)
        data = file_data["data"]
        if not file_data:
            return
        if which == 1:
            self._pane1_locked_to_file = True
            self.reader1["title"].setText(file_data["file_name"])
            self.model.load(data)  # 左阅读器模型
        else:
            self.reader2["title"].setText(file_data["file_name"])
            self.model2.load(data)
        print(f"Loading file for reader {which}:", file_data["file_name"])


    # ---------------------- Double / Single toggle ----------------------
    def _toggle_double_mode(self):
        self._double_mode = not self._double_mode
        self.reader2["frame"].setVisible(self._double_mode)
        if self._double_mode and self._pane2_file_path is None:
            self.reader2["title"].setText("(Choose a file ▼)")
        # 调整 splitter 大小分配
        if self._double_mode:
            self.splitter.setSizes([700, 320])
        else:
            self.splitter.setSizes([900, 220])

    # ---------------- Busy banner injection ----------------
    def set_busy_callback(self, cb):
        self._set_busy_cb = cb

    def _busy(self, on: bool, msg: str = "Working... please do not repeat operations"):
        if callable(self._set_busy_cb):
            self._set_busy_cb(on, msg)
            QApplication.processEvents()

    # ---------------- Document updates (left reader) ----------------
    @Slot(object)
    def on_document_changed(self, data):
        """左阅读器在未锁定时跟随全局文档；同时把当前文档路径加入 recent_files。"""
        # 1) recent_files 自动记录（无论是否锁定左阅读器，都应记录打开的文件）
        fp = getattr(self.document, "file_path", None)
        if fp:
            # self.recent_mgr.add_file(fp)
            self._refresh_stored_sidebar()

        # 2) 左阅读器视图跟随（未锁定时）
        if not self._pane1_locked_to_file:
            self.model.load(data)
            self._update_reader_title_from_doc(self.reader1, default_label="(Current Document)")

    def _update_reader_title_from_doc(self, reader_block: dict, default_label="(Current Document)"):
        fp = getattr(self.document, "file_path", None)
        reader_block["title"].setText(Path(fp).name if fp else default_label)


    # ---------------- Snapshot-facing API (LEFT reader only) ----------------
    def capture_view_state(self) -> dict:
        """供 MainWindow 在保存进展快照时读取视图状态；Viewer 本身不写快照文件。"""
        expanded = []

        m = self.reader1["tree"].model()

        def dfs(parent_index: QModelIndex, prefix_path: list):
            rows = m.rowCount(parent_index)
            for r in range(rows):
                idx = m.index(r, 0, parent_index)
                ti = idx.internalPointer()
                item_path = prefix_path + [ti.key]
                if self.reader1["tree"].isExpanded(idx):
                    expanded.append(item_path)
                dfs(idx, item_path)

        dfs(QModelIndex(), [])
        cur_path = None
        cur = self.reader1["tree"].currentIndex()
        if cur.isValid():
            cur_path = self._index_to_path(cur.sibling(cur.row(), 0))

        return {
            "expanded_paths": expanded,
            "current_path": cur_path,
            "scroll": self.reader1["tree"].verticalScrollBar().value(),
        }

    def schedule_restore_view_state(self, state: dict | None):
        """由 MainWindow 在加载快照前调用，交由 modelReset 后恢复展开/定位/滚动。"""
        self._pending_restore_state = state or None

    def _ask_store_to_database(self, file_path):
        file_path = Path(file_path)
        """Ask user if they want to store the JSON file to storage"""
        try:
            from jsonTool.core.database import get_database_manager
            
            reply = QMessageBox.question(
                self, 
                "Store to Storage", 
                f"Do you want to store '{file_path.name}' to storage?\n\n(File will be saved to stored_files/ directory)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.Yes:
                self._busy(True, "Storing file...")
                
                # Get current JSON data
                json_data = self.document.get_data()
                
                # Store to storage
                db_manager = get_database_manager()
                file_index = db_manager.store_json_file(file_path.name, json_data)
                
                QMessageBox.information(
                    self, 
                    "Success", 
                    f"File '{file_path.name}' stored with index {file_index}\n\nYou can commit and push to share with team."
                )
                
                # self.statusBar().showMessage(f"Stored to storage: index {file_index}", 5000)
                
        except Exception as e:
            QMessageBox.critical(self, "Storage Error", f"Failed to store file:\n{e}")
        finally:
            self._busy(False)

    # ---------------- Toolbar handlers (act on active tree) ----------------
    @Slot()
    def _on_expand_all(self):
        tv = self._active_tree or self.reader1["tree"]
        self._busy(True)
        try:
            tv.expandAll()
        finally:
            self._busy(False)

    @Slot()
    def _on_collapse_all(self):
        tv = self._active_tree or self.reader1["tree"]
        self._busy(True)
        try:
            tv.collapseAll()
        finally:
            self._busy(False)

    @Slot()
    def _on_expand_selection(self):
        tv = self._active_tree or self.reader1["tree"]
        idx = tv.currentIndex()
        if not idx.isValid():
            QMessageBox.information(self, "Info", "No selection.")
            return
        idx0 = idx.sibling(idx.row(), 0)
        self._busy(True)
        try:
            self._expand_subtree_indexed(tv, idx0)
        finally:
            self._busy(False)

    @Slot()
    def _on_collapse_selection(self):
        tv = self._active_tree or self.reader1["tree"]
        idx = tv.currentIndex()
        if not idx.isValid():
            QMessageBox.information(self, "Info", "No selection.")
            return
        idx0 = idx.sibling(idx.row(), 0)
        self._busy(True)
        try:
            self._collapse_subtree_indexed(tv, idx0)
        finally:
            self._busy(False)

    """@Slot()
    def _on_save(self):
        tv = self._active_tree or self.reader1["tree"]
        idx = tv.currentIndex()
        fp = getattr(self.document, "file_path", None)
        try:
            self._ask_store_to_database(fp)
        finally:
            self._busy(False)"""

    # ---------------- Helpers ----------------
    def _current_root_index(self) -> QModelIndex:
        # 为向后兼容保留：返回“当前激活树”的当前行索引的第 0 列
        tv = self._active_tree or self.reader1["tree"]
        idx = tv.currentIndex()
        if not idx.isValid():
            return QModelIndex()
        return idx.sibling(idx.row(), 0)

    def _expand_subtree(self, index: QModelIndex):
        # 为向后兼容保留：作用于左阅读器
        self._expand_subtree_indexed(self.reader1["tree"], index)

    def _collapse_subtree(self, index: QModelIndex):
        # 为向后兼容保留：作用于左阅读器
        self._collapse_subtree_indexed(self.reader1["tree"], index)

    def _expand_subtree_indexed(self, tree: QTreeView, index: QModelIndex):
        if not index.isValid():
            return
        tree.expand(index)
        m = tree.model()
        rows = m.rowCount(index)
        for i in range(rows):
            child = m.index(i, 0, index)
            self._expand_subtree_indexed(tree, child)

    def _collapse_subtree_indexed(self, tree: QTreeView, index: QModelIndex):
        if not index.isValid():
            return
        m = tree.model()
        rows = m.rowCount(index)
        for i in range(rows):
            child = m.index(i, 0, index)
            self._collapse_subtree_indexed(tree, child)
        tree.collapse(index)

    # ---------------- View-state save/restore (LEFT reader only) ----------------
    def _index_to_path(self, index: QModelIndex) -> list:
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
        # left reader only（保持原行为）
        tree = self.reader1["tree"]
        self._saved_expanded_paths.clear()
        self._saved_current_path = None
        self._saved_scroll = tree.verticalScrollBar().value()

        m = tree.model()

        def dfs(parent_index: QModelIndex, prefix_path: list):
            rows = m.rowCount(parent_index)
            for r in range(rows):
                idx = m.index(r, 0, parent_index)
                ti = idx.internalPointer()
                item_path = prefix_path + [ti.key]
                if tree.isExpanded(idx):
                    self._saved_expanded_paths.append(item_path)
                dfs(idx, item_path)

        dfs(QModelIndex(), [])

        cur = tree.currentIndex()
        if cur.isValid():
            self._saved_current_path = self._index_to_path(cur.sibling(cur.row(), 0))

    def _restore_view_state(self):
        # left reader only（保持原行为）
        tree = self.reader1["tree"]
        state = self._pending_restore_state
        use_pending = state is not None

        if not use_pending:
            state = {
                "expanded_paths": self._saved_expanded_paths,
                "current_path": self._saved_current_path,
                "scroll": self._saved_scroll,
            }

        m = tree.model()

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
                tree.expand(idx)

        curp = state.get("current_path")
        if curp:
            idx = find_index_by_path(curp)
            if idx is not None:
                tree.setCurrentIndex(idx)

        scr = state.get("scroll")
        if isinstance(scr, int):
            tree.verticalScrollBar().setValue(scr)

        self._saved_expanded_paths.clear()
        self._saved_current_path = None
        self._pending_restore_state = None
