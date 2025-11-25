# ui/tab_table.py
# ------------------------------------------------------------
# 新版 Table 标签页：从 JSON 手动选择属性，根据结构上下文匹配相似项，扁平化为二维表，并导出为 Excel
# ------------------------------------------------------------

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List, Tuple, Dict, Optional

from PySide6.QtCore import (
    Qt, QModelIndex, QItemSelection, QItemSelectionModel, QPoint, Slot
)
from PySide6.QtGui import QAction, QPainter
from PySide6.QtWidgets import QStyleOptionViewItem

from PySide6.QtWidgets import (
    QWidget, QSplitter, QVBoxLayout, QHBoxLayout, QPushButton, QTreeView,
    QHeaderView, QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox,
    QAbstractItemView, QMenu, QStyledItemDelegate
)

# 按要求使用该导入路径
from jsonTool.core.json_model import JsonModel


# ======================== 绘制委托：为“已确认属性”上色为绿色 ========================
class ConfirmHighlightDelegate(QStyledItemDelegate):
    """为 TreeView 中已确认的属性（路径命中集合）绘制绿色背景。"""
    def __init__(self, path_checker, parent=None):
        """
        :param path_checker: callable(index)->bool，用于判断该 index 是否在已确认集合中
        """
        super().__init__(parent)
        self._is_confirmed = path_checker

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        # 仅在第0列且命中“已确认属性”时，填充绿色背景
        if index.column() == 0 and self._is_confirmed(index):
            painter.save()
            painter.fillRect(option.rect, "#d8f5d0")  # 浅绿色
            painter.restore()
        super().paint(painter, option, index)


# ======================== 自定义 TreeView：同父级 Shift 连选 ========================
class RangeTreeView(QTreeView):
    """支持 Shift 在同一父节点间做连续兄弟行选择；Ctrl/Cmd 多选；行选择模式。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.anchor_index: Optional[QModelIndex] = None
        self.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        # 当前选中为蓝色（样式表控制）
        self.setStyleSheet("QTreeView::item:selected { background: #cfe8ff; color: black; }")

    def mousePressEvent(self, event):
        idx = self.indexAt(event.pos())
        mods = event.modifiers()

        # -----Shift 连选：同一父节点范围-----
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
                return

        super().mousePressEvent(event)
        if not (mods & Qt.ShiftModifier):
            if idx.isValid():
                self.anchor_index = idx

    def reset_anchor(self):
        """清除锚点。"""
        self.anchor_index = None


# ======================== 主类：TableTab ========================
class TableTab(QWidget):
    """Table 标签页：左侧 JSON 选择属性，右侧表格扁平化视图，支持导出 Excel。"""

    # -----初始化-----
    def __init__(self, parent=None, document: Any | None = None):
        """初始化 UI、模型、状态。"""
        super().__init__(parent)
        self.document = document
        self._set_busy_cb = None

        # 左侧 JSON 模型与视图
        self.json_model = JsonModel(editable_keys=False, editable_values=False)
        self.tree = RangeTreeView(self)
        self.tree.setModel(self.json_model)

        # “已确认属性路径集合”（绝对路径元组）
        self._confirmed_attr_paths: set[Tuple[Any, ...]] = set()
        # 已确认属性相对路径（相对于共同父节点）
        self._confirmed_attr_relpaths: List[List[Any]] = []
        self._confirmed_attr_headers: List[str] = []
        # 已确认属性的“共同父节点”的绝对路径
        self._confirmed_subroot_abs_path: Optional[List[Any]] = None

        # 为 TreeView 安装绿色高亮绘制委托
        self.tree.setItemDelegate(
            ConfirmHighlightDelegate(self._index_is_confirmed, self.tree)
        )

        # 右侧表格视图
        self.table = QTableWidget(self)
        self.table.setColumnCount(0)
        self.table.setRowCount(0)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        # 允许拖拽重排列头（视觉重排）
        self.table.horizontalHeader().setSectionsMovable(True)

        # 顶部工具栏
        self.btn_export = QPushButton("Export Excel", self)
        self.btn_fit = QPushButton("Fit", self)
        self.btn_select_attr = QPushButton("Selected Attribute", self)
        self.btn_add_attr = QPushButton("Add Attribute", self)

        # 组装布局
        self._build_layout()

        # 绑定信号
        self.btn_export.clicked.connect(self._action_export_excel)
        self.btn_fit.clicked.connect(self._action_fit_columns)
        self.btn_select_attr.clicked.connect(self._action_confirm_selected_attributes)
        self.btn_add_attr.clicked.connect(self._action_add_to_table)

        # 表头右键（列）
        self.table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self._on_header_context_menu)
        # 行头右键（行）
        self.table.verticalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.verticalHeader().customContextMenuRequested.connect(self._on_rows_context_menu)

        # 连接全局文档（如有）
        if self.document is not None:
            if self.document.get_data() is not None:
                self.json_model.load(self.document.get_data())
            self.document.dataChanged.connect(self.on_document_changed)

    # -----布局构建-----
    def _build_layout(self):
        """搭建 UI：工具栏 + 左右分栏（支持拖拽分隔）。"""
        root = QVBoxLayout(self)

        # 工具栏（仅保留指定按钮）
        bar = QHBoxLayout()
        bar.addWidget(self.btn_export)
        bar.addWidget(self.btn_fit)
        bar.addSpacing(12)
        bar.addWidget(self.btn_select_attr)
        bar.addWidget(self.btn_add_attr)
        bar.addStretch(1)
        root.addLayout(bar)

        # 分割器
        splitter = QSplitter(Qt.Horizontal, self)
        root.addWidget(splitter, 1)

        # 左：JSON 视图（超出自动滚动）
        left = QWidget(self)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(4)

        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        lv.addWidget(self.tree, 1)

        # 右：表格视图（超出自动滚动）
        right = QWidget(self)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(4)
        rv.addWidget(self.table, 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([700, 500])

    # ======================== Busy 辅助 ========================
    def set_busy_callback(self, cb):
        """注入 MainWindow 的忙碌提示回调。"""
        self._set_busy_cb = cb

    def _busy(self, on: bool, msg: str = "Working..."):
        """调用忙碌提示。"""
        if callable(self._set_busy_cb):
            self._set_busy_cb(on, msg)

    # ======================== 文档数据变化 ========================
    @Slot(object)
    def on_document_changed(self, data):
        """当全局文档改变：刷新左侧 JSON；右侧保持为当前表格（不自动清空）。"""
        self._busy(True, "Loading JSON...")
        try:
            self.json_model.load(data)
            # 清除临时选择锚点
            self.tree.reset_anchor()
            # 既有表格保留；已确认属性清空
            self._confirmed_attr_paths.clear()
            self._confirmed_attr_relpaths.clear()
            self._confirmed_attr_headers.clear()
            self._confirmed_subroot_abs_path = None
            self.tree.viewport().update()
        finally:
            self._busy(False)

    # ======================== JSON 索引/路径工具 ========================
    def _index0(self, idx: QModelIndex) -> QModelIndex:
        """将任意列索引转换为第0列表头索引。"""
        return idx.sibling(idx.row(), 0)

    def _index_to_path(self, index: QModelIndex) -> List[Any]:
        """把模型索引转为绝对路径（root 不包含）。"""
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

    def _index_is_confirmed(self, index: QModelIndex) -> bool:
        """判断该索引是否属于“已确认属性集合”。"""
        if not index.isValid():
            return False
        path = tuple(self._index_to_path(self._index0(index)))
        return path in self._confirmed_attr_paths

    def _common_parent_item(self, idxs: List[QModelIndex]):
        """返回所选索引的共同父 TreeItem；若不一致返回 None。"""
        parent = None
        for idx in idxs:
            it = idx.internalPointer()
            p = it.parent()
            if parent is None:
                parent = p
            elif p is not parent:
                return None
        return parent

    # ======================== 按钮：确认属性 ========================
    @Slot()
    def _action_confirm_selected_attributes(self):
        """确认左侧选中的属性（允许跨层级）。
        逻辑：计算所有被选中节点绝对路径的“最低共同祖先”(LCA) 作为基准，
        将每个选中节点的绝对路径转为“相对 LCA 的相对路径”，用于后续 Add Attribute。
        同时把这些选中节点标记为“已确认”（绿色高亮）。
        """
        # -----收集选择：转为第0列索引-----
        sel = [self._index0(i) for i in self.tree.selectionModel().selectedRows(0)]
        if not sel:
            QMessageBox.information(self, "Info", "Please select one or more attributes on the left JSON view.")
            return

        # -----绝对路径列表-----
        abs_paths: List[List[Any]] = [self._index_to_path(idx) for idx in sel]

        # -----计算 LCA（最低共同祖先路径）-----
        def lca_path(paths: List[List[Any]]) -> List[Any]:
            if not paths:
                return []
            base = list(paths[0])
            for p in paths[1:]:
                # 缩短 base，直到成为 p 的前缀
                while len(base) > 0 and p[:len(base)] != base:
                    base.pop()
                if not base:
                    break
            return base

        subroot_abs = lca_path(abs_paths)  # 允许跨层：以 LCA 为“共同父（基）”
        self._confirmed_subroot_abs_path = subroot_abs

        # -----构造相对路径与列头-----
        relpaths: List[List[Any]] = []
        headers: List[str] = []
        abs_paths_tuples = []

        for ap in abs_paths:
            rel = ap[len(subroot_abs):]  # 相对 LCA 的路径
            relpaths.append(rel)

            # 列名：使用最后一段（必要时可改成用 '.' 连接的全路径）
            if not rel:
                header = "(self)"
            else:
                last = rel[-1]
                header = f"[{last}]" if isinstance(last, int) else str(last)
            headers.append(header)

            abs_paths_tuples.append(tuple(ap))

        # -----保存“已确认属性”-----
        self._confirmed_attr_relpaths = relpaths
        self._confirmed_attr_headers = headers
        self._confirmed_attr_paths = set(abs_paths_tuples)

        # 清掉当前（蓝色）选择，让绿色高亮可见
        self.tree.clearSelection()
        self.tree.viewport().update()



    # ======================== 按钮：添加到表格 ========================
    @Slot()
    def _action_add_to_table(self):
        """选择一个父级容器（[] 或 {}），把与已确认属性同层的所有“兄弟子结构”展平到表格。"""
        if not self._confirmed_attr_relpaths or self._confirmed_subroot_abs_path is None:
            QMessageBox.information(self, "Info", "Please confirm attributes first (Selected Attribute).")
            return

        # 当前索引或向上找到最近容器
        cur = self._index0(self.tree.currentIndex())
        if not cur.isValid():
            QMessageBox.information(self, "Info", "Please click a container (array or object) as the range.")
            return

        container_idx = self._find_nearest_container(cur)
        if container_idx is None:
            QMessageBox.warning(self, "Invalid range", "Please select an array or object as the range.")
            return

        container_abs = self._index_to_path(container_idx)
        subroot_abs = self._confirmed_subroot_abs_path

        # 容器必须是共同父的祖先（向上递归）
        if not self._is_prefix(container_abs, subroot_abs):
            QMessageBox.warning(
                self, "Invalid range",
                "The chosen range must be an ancestor of the confirmed attributes' parent."
            )
            return

        # 容器 -> 共同父 的相对路径
        rel_from_container = subroot_abs[len(container_abs):]  # 可能为 []

        # 第一个“变化维度”：数组索引或对象键；若为空，则“共同父”即容器本身
        if rel_from_container:
            first = rel_from_container[0]
            rel_tail = rel_from_container[1:]
            vary_kind = "list" if isinstance(first, int) else "dict"
        else:
            rel_tail = []
            vary_kind = self._container_kind(container_idx)

        # 确保列存在
        col_map = self._ensure_columns(self._confirmed_attr_headers, self._confirmed_attr_relpaths)

        # 遍历兄弟子结构
        data_root = self.json_model.to_json()
        rows_added = 0

        if vary_kind == "list":
            container_obj = self._get_by_path_safe(data_root, container_abs)
            if not isinstance(container_obj, list):
                QMessageBox.warning(self, "Invalid range", "The chosen range is not an array.")
                return
            for i in range(len(container_obj)):
                base_path = container_abs + [i] + rel_tail
                self._append_row_by_relpaths(data_root, base_path, col_map)
                rows_added += 1

        elif vary_kind == "dict":
            container_obj = self._get_by_path_safe(data_root, container_abs)
            if not isinstance(container_obj, dict):
                QMessageBox.warning(self, "Invalid range", "The chosen range is not an object.")
                return
            for k in list(container_obj.keys()):
                base_path = container_abs + [k] + rel_tail
                self._append_row_by_relpaths(data_root, base_path, col_map)
                rows_added += 1

        else:
            QMessageBox.warning(self, "Invalid range", "Unsupported range kind.")
            return

        # 重置左侧高亮
        self._confirmed_attr_paths.clear()
        self.tree.viewport().update()

        QMessageBox.information(self, "Done", f"Added {rows_added} row(s).")

    # -----容器/路径辅助-----
    def _find_nearest_container(self, idx: QModelIndex) -> Optional[QModelIndex]:
        """向上寻找最近的容器（list/dict）的索引。"""
        cur = idx
        while cur.isValid():
            item = cur.internalPointer()
            if item.value_type in (list, dict):
                return self._index0(cur)
            cur = cur.parent()
        return None

    def _container_kind(self, idx: QModelIndex) -> str:
        """返回容器类型：'list'/'dict'/''。"""
        if not idx.isValid():
            return ''
        item = idx.internalPointer()
        if item.value_type is list:
            return 'list'
        if item.value_type is dict:
            return 'dict'
        return ''

    def _is_prefix(self, prefix: List[Any], whole: List[Any]) -> bool:
        """判断 prefix 是否 whole 的前缀。"""
        if len(prefix) > len(whole):
            return False
        return whole[:len(prefix)] == prefix

    def _get_by_path_safe(self, data: Any, path: List[Any]) -> Any:
        """安全按路径取值（失败返回 None）。"""
        ref = data
        try:
            for k in path:
                ref = ref[k]
            return ref
        except Exception:
            return None

    def _get_by_rel(self, base: Any, rel: List[Any]) -> Any:
        """从 base 出发按相对路径取值（失败返回 None）。"""
        ref = base
        try:
            for k in rel:
                ref = ref[k]
            return ref
        except Exception:
            return None

    # -----表格填充-----
    def _ensure_columns(self, headers: List[str], relpaths: List[List[Any]]) -> Dict[int, List[Any]]:
        """确保表格包含指定列；返回 列索引 -> 相对路径 的映射。"""
        existing = {self.table.horizontalHeaderItem(i).text(): i
                    for i in range(self.table.columnCount())
                    if self.table.horizontalHeaderItem(i) is not None}

        col_map: Dict[int, List[Any]] = {}
        for name, rel in zip(headers, relpaths):
            col_name = name
            if col_name in existing:
                col = existing[col_name]
            else:
                # 处理重名：追加 _2/_3...
                base = col_name
                n = 2
                while col_name in existing:
                    col_name = f"{base}_{n}"
                    n += 1
                col = self.table.columnCount()
                self.table.insertColumn(col)
                self.table.setHorizontalHeaderItem(col, QTableWidgetItem(col_name))
                existing[col_name] = col
            col_map[col] = rel
        return col_map

    def _append_row_by_relpaths(self, data_root: Any, base_path: List[Any], col_map: Dict[int, List[Any]]):
        """以 base_path 为“子结构根”，按 col_map 的相对路径取值，追加为一行。"""
        base = self._get_by_path_safe(data_root, base_path)
        r = self.table.rowCount()
        self.table.insertRow(r)
        for col, rel in col_map.items():
            val = self._get_by_rel(base, rel) if base is not None else None
            text = self._value_to_cell(val)
            self.table.setItem(r, col, QTableWidgetItem(text))

    def _value_to_cell(self, v: Any) -> str:
        """把 JSON 值转换为单元格文本；对象/数组序列化为紧凑 JSON。"""
        if isinstance(v, (dict, list)):
            try:
                return json.dumps(v, ensure_ascii=False)
            except Exception:
                return str(v)
        if v is None:
            return ""
        return str(v)

    # ======================== 表头（列）右键菜单 ========================
    def _on_header_context_menu(self, pos: QPoint):
        """列头右键菜单：一层拆分、删除列、删除所有列、移到最左、移到最右。"""
        header = self.table.horizontalHeader()
        global_pos = header.mapToGlobal(pos)
        col = header.logicalIndexAt(pos)
        if col < 0:
            return

        menu = QMenu(self)
        act_split = QAction("Split Down One Level", self)
        act_del = QAction("Delete This Column", self)
        act_del_all = QAction("Delete All Columns", self)
        act_move_leftmost = QAction("Move to Leftmost", self)
        act_move_rightmost = QAction("Move to Rightmost", self)

        menu.addAction(act_split)
        menu.addSeparator()
        menu.addAction(act_del)
        menu.addAction(act_del_all)
        menu.addSeparator()
        menu.addAction(act_move_leftmost)
        menu.addAction(act_move_rightmost)

        act_split.triggered.connect(lambda: self._split_one_level(col))
        act_del.triggered.connect(lambda: self._delete_column(col))
        act_del_all.triggered.connect(self._delete_all_columns)
        act_move_leftmost.triggered.connect(lambda: self._move_column(col, 0))
        act_move_rightmost.triggered.connect(lambda: self._move_column(col, self.table.columnCount() - 1))

        menu.exec(global_pos)

    # -----列：拆分一层-----
    def _split_one_level(self, col: int):
        """把当前列中“对象/数组字符串”下探一层拆分为多列（仅一层）。"""
        parsed_rows: List[Any] = []
        is_any = False
        max_list_len = 0
        dict_keys: set[str] = set()

        for r in range(self.table.rowCount()):
            it = self.table.item(r, col)
            s = it.text() if it else ""
            try:
                val = json.loads(s)
                parsed_rows.append(val)
                is_any = True
                if isinstance(val, list):
                    max_list_len = max(max_list_len, len(val))
                elif isinstance(val, dict):
                    dict_keys.update(map(str, val.keys()))
            except Exception:
                parsed_rows.append(None)

        if not is_any:
            QMessageBox.information(self, "Info", "Nothing to split: the column is not JSON objects/arrays.")
            return

        base_name = self.table.horizontalHeaderItem(col).text() if self.table.horizontalHeaderItem(col) else f"Col{col}"
        new_cols_info: List[Tuple[str, str]] = []  # (header, kind: "dict:key" / "list:index")

        if dict_keys:
            for k in sorted(dict_keys):
                new_cols_info.append((f"{base_name}.{k}", f"dict:{k}"))
        else:
            for i in range(max_list_len):
                new_cols_info.append((f"{base_name}[{i}]", f"list:{i}"))

        # 在当前列右侧依次插入
        insert_pos = col + 1
        for i, (hdr, _) in enumerate(new_cols_info):
            nc = insert_pos + i
            self.table.insertColumn(nc)
            self.table.setHorizontalHeaderItem(nc, QTableWidgetItem(hdr))

        # 填充
        for r in range(self.table.rowCount()):
            val = parsed_rows[r]
            for i, (_, kind) in enumerate(new_cols_info):
                nc = insert_pos + i
                cell = ""
                if isinstance(val, dict) and kind.startswith("dict:"):
                    k = kind.split(":", 1)[1]
                    cell = self._value_to_cell(val.get(k))
                elif isinstance(val, list) and kind.startswith("list:"):
                    idx = int(kind.split(":", 1)[1])
                    if 0 <= idx < len(val):
                        cell = self._value_to_cell(val[idx])
                self.table.setItem(r, nc, QTableWidgetItem(cell))

    # -----列：删除该列-----
    def _delete_column(self, col: int):
        """删除指定列。"""
        if 0 <= col < self.table.columnCount():
            self.table.removeColumn(col)

    # -----列：删除所有列-----
    def _delete_all_columns(self):
        self.table.setRowCount(0)
        """删除所有列（清空所有装载的属性）。"""
        while self.table.columnCount() > 0:
            self.table.removeColumn(0)

    # -----列：移动到某位置（最左/最右）-----
    def _move_column(self, src: int, dst_visual: int):
        """将列移动到目标位置：通过交换单元格与表头文本实现。"""
        if src < 0 or src >= self.table.columnCount():
            return
        dst = max(0, min(dst_visual, self.table.columnCount() - 1))
        if src == dst:
            return

        step = 1 if dst > src else -1
        c = src
        while c != dst:
            self._swap_columns(c, c + step)
            c += step

    def _swap_columns(self, a: int, b: int):
        """交换两列的所有单元格与表头。"""
        if min(a, b) < 0 or max(a, b) >= self.table.columnCount() or a == b:
            return
        for r in range(self.table.rowCount()):
            ia = self.table.takeItem(r, a)
            ib = self.table.takeItem(r, b)
            self.table.setItem(r, a, ib)
            self.table.setItem(r, b, ia)
        ha = self.table.horizontalHeaderItem(a)
        hb = self.table.horizontalHeaderItem(b)
        self.table.setHorizontalHeaderItem(a, hb if hb else QTableWidgetItem(""))
        self.table.setHorizontalHeaderItem(b, ha if ha else QTableWidgetItem(""))

    # ======================== 行头右键菜单 ========================
    def _on_rows_context_menu(self, pos: QPoint):
        """行头右键菜单：删除选中行、删除所有行。"""
        vheader = self.table.verticalHeader()
        global_pos = vheader.mapToGlobal(pos)

        menu = QMenu(self)
        act_del_sel = QAction("Delete Selected Rows", self)
        act_del_all = QAction("Delete All Rows", self)
        menu.addAction(act_del_sel)
        menu.addAction(act_del_all)

        act_del_sel.triggered.connect(self._delete_selected_rows)
        act_del_all.triggered.connect(self._delete_all_rows)

        menu.exec(global_pos)

    def _delete_selected_rows(self):
        """删除当前选中的行（可能多选）。"""
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def _delete_all_rows(self):
        """删除所有行。"""
        self.table.setRowCount(0)

    # ======================== 视图操作 ========================
    @Slot()
    def _action_fit_columns(self):
        """自适应列宽。"""
        self.table.resizeColumnsToContents()

    # ======================== 导出 Excel ========================
    @Slot()
    def _action_export_excel(self):
        """导出当前表格为 Excel（首行冻结），缺库回退 CSV。"""
        default_name = "toExcel.xlsx"
        if self.document and getattr(self.document, "file_path", None):
            stem = Path(self.document.file_path).stem
            default_name = f"{stem}_toExcel.xlsx"

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Excel", default_name, "Excel Files (*.xlsx);;All Files (*)"
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        ok = self._write_xlsx(path)
        if ok:
            QMessageBox.information(self, "Done", f"Exported to:\n{path}")
        else:
            # 回退 CSV
            csv_path = os.path.splitext(path)[0] + ".csv"
            if self._write_csv(csv_path):
                QMessageBox.information(
                    self, "Done",
                    f"Excel writer not available. Exported CSV instead:\n{csv_path}"
                )
            else:
                QMessageBox.critical(self, "Error", "Failed to export.")

    def _write_xlsx(self, path: str) -> bool:
        """尝试使用 openpyxl 或 xlsxwriter 导出 .xlsx，并冻结首行。"""
        # 优先 openpyxl
        try:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            # 表头
            headers = [self.table.horizontalHeaderItem(i).text() if self.table.horizontalHeaderItem(i) else f"Col{i}"
                       for i in range(self.table.columnCount())]
            ws.append(headers)
            # 冻结首行
            ws.freeze_panes = "A2"
            # 数据行
            for r in range(self.table.rowCount()):
                row = []
                for c in range(self.table.columnCount()):
                    it = self.table.item(r, c)
                    row.append(it.text() if it else "")
                ws.append(row)
            wb.save(path)
            return True
        except Exception:
            pass

        # 次选 xlsxwriter
        try:
            import xlsxwriter
            wb = xlsxwriter.Workbook(path)
            ws = wb.add_worksheet()
            # 表头
            headers = [self.table.horizontalHeaderItem(i).text() if self.table.horizontalHeaderItem(i) else f"Col{i}"
                       for i in range(self.table.columnCount())]
            for c, h in enumerate(headers):
                ws.write(0, c, h)
            # 冻结首行
            ws.freeze_panes(1, 0)
            # 数据行
            for r in range(self.table.rowCount()):
                for c in range(self.table.columnCount()):
                    it = self.table.item(r, c)
                    ws.write(r + 1, c, it.text() if it else "")
            wb.close()
            return True
        except Exception:
            return False

    def _write_csv(self, path: str) -> bool:
        """回退导出 CSV。"""
        try:
            import csv
            with open(path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                headers = [self.table.horizontalHeaderItem(i).text() if self.table.horizontalHeaderItem(i) else f"Col{i}"
                           for i in range(self.table.columnCount())]
                w.writerow(headers)
                for r in range(self.table.rowCount()):
                    row = []
                    for c in range(self.table.columnCount()):
                        it = self.table.item(r, c)
                        row.append(it.text() if it else "")
                    w.writerow(row)
            return True
        except Exception:
            return False
