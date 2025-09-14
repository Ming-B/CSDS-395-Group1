
# This file is originally based on the Qt official example "jsonmodel.py"
# Copyright (C) 2022 The Qt Company Ltd., licensed under BSD-3-Clause.
# https://doc.qt.io/qtforpython-6/examples/example_widgets_itemviews_jsonmodel.html
#
# I’ve kept the core structure, but roughly half of the code has been refactored and extended with new methods. 
# Modifications in this version include:
# - Added options for editable keys/values
# - Added monospaced font and syntax coloring for JSON values
# - Implemented key/value formatting helpers and type-aware rendering
# - Enhanced setData() to support type conversion and structural reload
# - Removed demo main() block for cleaner integration


# core/json_model.py
from __future__ import annotations

import json
from typing import Any, Tuple

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QObject, Qt
from PySide6.QtGui import QFont, QColor


class TreeItem:
    """A Json item corresponding to a line in QTreeView"""

    def __init__(self, parent: "TreeItem" = None):
        self._parent = parent
        self._key = ""
        self._value = ""
        self._value_type = None
        self._children = []

    def appendChild(self, item: "TreeItem"):
        self._children.append(item)

    def child(self, row: int) -> "TreeItem":
        return self._children[row]

    def parent(self) -> "TreeItem":
        return self._parent

    def childCount(self) -> int:
        return len(self._children)

    def row(self) -> int:
        return self._parent._children.index(self) if self._parent else 0

    @property
    def key(self) -> str:
        return self._key

    @key.setter
    def key(self, key: str):
        self._key = key

    @property
    def value(self) -> Any:
        return self._value

    @value.setter
    def value(self, value: Any):
        self._value = value

    @property
    def value_type(self):
        return self._value_type

    @value_type.setter
    def value_type(self, value):
        self._value_type = value

    @classmethod
    def load(
        cls, value: list | dict, parent: "TreeItem" = None, sort=True
    ) -> "TreeItem":
        rootItem = TreeItem(parent)
        rootItem.key = "root"

        if isinstance(value, dict):
            items = sorted(value.items()) if sort else value.items()
            for key, value in items:
                child = cls.load(value, rootItem)
                child.key = key
                child.value_type = type(value)
                rootItem.appendChild(child)

        elif isinstance(value, list):
            for index, value in enumerate(value):
                child = cls.load(value, rootItem)
                child.key = index
                child.value_type = type(value)
                rootItem.appendChild(child)

        else:
            rootItem.value = value
            rootItem.value_type = type(value)

        return rootItem


class JsonModel(QAbstractItemModel):
    def __init__(
        self,
        parent: QObject = None,
        *,
        editable_keys: bool = False,
        editable_values: bool = True,
    ):
        """
        :param editable_keys:  允许编辑 key（仅当父节点是 dict 时，且同级不重名）
        :param editable_values:允许编辑 value（仅第2列）
        """
        super().__init__(parent)
        self._rootItem = TreeItem()
        self._headers = ("key", "value")
        self._editable_keys = editable_keys
        self._editable_values = editable_values

        # 等宽字体
        _MONO_FONTS: Tuple[str, str] = ("Consolas", "Courier New")
        self._mono_font = QFont(_MONO_FONTS[0])
        if not self._mono_font.family():
            self._mono_font = QFont(_MONO_FONTS[1])

    # ----------- JSON 外观辅助 -----------
    @staticmethod
    def _json_key_repr(key, parent_is_list: bool) -> str:
        if parent_is_list:
            return f"[{key}]"
        try:
            return json.dumps(key)
        except Exception:
            return f'"{str(key)}"'

    @staticmethod
    def _json_value_repr(value, value_type) -> str:
        if value_type is dict:
            return "{...}"
        if value_type is list:
            return "[...]"
        if value_type is str:
            try:
                return json.dumps(value)
            except Exception:
                return f'"{str(value)}"'
        if value_type in (int, float):
            return str(value)
        if value_type is bool:
            return "true" if value is True else "false"
        if value is None or value_type is type(None):
            return "null"
        try:
            return json.dumps(value)
        except Exception:
            return str(value)

    @staticmethod
    def _type_color(value_type) -> QColor:
        if value_type in (dict, list):
            return QColor(150, 150, 150)
        if value_type is str:
            return QColor(163, 21, 21)
        if value_type in (int, float):
            return QColor(0, 0, 192)
        if value_type is bool:
            return QColor(136, 19, 145)
        if value_type is type(None):
            return QColor(128, 128, 128)
        return QColor(32, 32, 32)

    # ----------- 内部：解析与路径 -----------
    @staticmethod
    def _parse_user_input(text: str) -> Any:
        """
        尝试把用户输入解析成 Python 值（支持 number/bool/null/obj/array）；
        失败则按原样作为字符串。
        """
        if text is None:
            return ""
        s = str(text).strip()
        # 先直接按 JSON 解析（能处理 true/false/null/数字/对象/数组/带引号字符串）
        try:
            return json.loads(s)
        except Exception:
            pass
        # 宽松兼容大小写 true/false/null
        low = s.lower()
        if low == "true":
            return True
        if low == "false":
            return False
        if low == "null":
            return None
        # 其余一律当作裸字符串
        return s

    @staticmethod
    def _item_path(item: TreeItem) -> list:
        """返回从文档根到该 item 的键路径（list 中的元素为 str 或 int）。"""
        path = []
        cur = item
        while cur and cur.parent() is not None:
            path.append(cur.key)
            cur = cur.parent()
        path.reverse()
        return path

    def _set_value_by_path_and_reload(self, path: list, new_value: Any):
        """
        基于当前模型的 JSON，按路径写入新值，然后整体 reload。
        这样可以无痛应对“叶子变容器/容器变叶子”的结构变化。
        """
        data = self.to_json()
        ref = data
        for k in path[:-1]:
            ref = ref[k]  # k 既可能是 int（list 索引），也可能是 str（dict key）
        last = path[-1]
        ref[last] = new_value
        # 整体重载
        self.load(data)

    # ----------- API -----------
    def clear(self):
        self.load({})

    def load(self, document: dict | list | tuple):
        assert isinstance(document, (dict, list, tuple)), (
            "`document` must be of dict, list or tuple, " f"not {type(document)}"
        )
        self.beginResetModel()
        self._rootItem = TreeItem.load(document)
        self._rootItem.value_type = type(document)
        self.endResetModel()
        return True

    def data(self, index: QModelIndex, role: Qt.ItemDataRole) -> Any:
        if not index.isValid():
            return None

        item = index.internalPointer()

        if role == Qt.ItemDataRole.FontRole:
            return self._mono_font

        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 1:
            return self._type_color(
                item.value_type if item.childCount() == 0 else item.value_type
            )

        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                parent_item = item.parent()
                parent_is_list = bool(parent_item and parent_item.value_type is list)
                key_text = self._json_key_repr(item.key, parent_is_list)
                return f"{key_text}:"
            if index.column() == 1:
                if item.value_type is dict:
                    return "{...}  " + f"// {item.childCount()} key"
                if item.value_type is list:
                    return "[...]  " + f"// {item.childCount()} item"
                return self._json_value_repr(item.value, item.value_type)

        elif role == Qt.ItemDataRole.EditRole:
            if index.column() == 1:
                return "" if item.value is None else item.value
            if index.column() == 0:
                return item.key

    def setData(self, index: QModelIndex, value: Any, role: Qt.ItemDataRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False

        item: TreeItem = index.internalPointer()

        # 编辑 value（第2列）——允许转型
        # 编辑 value（第2列）——允许转型，但尽量避免整树 reload
        if index.column() == 1 and self._editable_values:
            # 容器节点本身不直接改成文本；要改成别的结构由下方解析处理
            if item.value_type in (dict, list):
                return False

            parsed = self._parse_user_input(value)

            # ✅ 如果不是对象/数组（即标量），直接就地更新，不触发 reload
            if not isinstance(parsed, (dict, list)):
                item.value = parsed
                item.value_type = type(parsed)
                # 让渲染颜色/文本即时更新
                self.dataChanged.emit(
                    index,
                    index,
                    [
                        Qt.ItemDataRole.EditRole,
                        Qt.ItemDataRole.DisplayRole,
                        Qt.ItemDataRole.ForegroundRole,
                    ],
                )
                return True

            # ❗如果变成对象/数组（结构变化），走路径写入 + 整体重载
            path = self._item_path(item)
            if not path:
                return False
            self._set_value_by_path_and_reload(path, parsed)
            return True

        # 编辑 key（第1列）——仅当父是 dict，且不与兄弟重名
        if index.column() == 0 and self._editable_keys:
            parent = item.parent()
            if not parent or parent.value_type is not dict:
                return False  # 列表/根节点不允许改 key
            new_key = str(value)

            # 重名检查
            for i in range(parent.childCount()):
                sib = parent.child(i)
                if sib is not item and str(sib.key) == new_key:
                    return False

            # 通过“路径写入 + 重载”实现改名（构造新字典键）
            path = self._item_path(item)
            if not path:
                return False

            data = self.to_json()
            ref = data
            for k in path[:-1]:
                ref = ref[k]
            last = path[-1]
            if isinstance(ref, list):
                # list 的“key”为索引，不允许改
                return False
            else:
                # 改名：新键赋旧值，然后删旧键
                ref[new_key] = ref.pop(last)
                self.load(data)
                return True

        return False

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: Qt.ItemDataRole
    ):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._headers[section]

    def index(self, row: int, column: int, parent=QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        parentItem = (
            self._rootItem if not parent.isValid() else parent.internalPointer()
        )
        childItem = parentItem.child(row)
        if childItem:
            return self.createIndex(row, column, childItem)
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        childItem = index.internalPointer()
        parentItem = childItem.parent()
        if parentItem == self._rootItem:
            return QModelIndex()
        return self.createIndex(parentItem.row(), 0, parentItem)

    def rowCount(self, parent=QModelIndex()):
        if parent.column() > 0:
            return 0
        parentItem = (
            self._rootItem if not parent.isValid() else parent.internalPointer()
        )
        return parentItem.childCount()

    def columnCount(self, parent=QModelIndex()):
        return 2

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        flags = super(JsonModel, self).flags(index)
        if not index.isValid():
            return flags
        if index.column() == 0 and self._editable_keys:
            return Qt.ItemFlag.ItemIsEditable | flags
        if index.column() == 1 and self._editable_values:
            return Qt.ItemFlag.ItemIsEditable | flags
        return flags

    def to_json(self, item=None):
        if item is None:
            item = self._rootItem
        nchild = item.childCount()
        if item.value_type is dict:
            document = {}
            for i in range(nchild):
                ch = item.child(i)
                document[ch.key] = self.to_json(ch)
            return document
        elif item.value_type == list:
            document = []
            for i in range(nchild):
                ch = item.child(i)
                document.append(self.to_json(ch))
            return document
        else:
            return item.value
