# core/document.py
from __future__ import annotations
import json
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool, Slot


class _LoadRunnable(QRunnable):
    def __init__(self, path: str, on_success: callable, on_error: callable):
        super().__init__()
        self._path = path
        self._on_success = on_success
        self._on_error = on_error

    def run(self):
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._on_success(self._path, data)
        except Exception as e:
            self._on_error(self._path, e)


class JSONDocument(QObject):
    """Global JSON document: holds current data & path, emits change events."""
    dataChanged = Signal(object)      # 最新的 Python 对象
    loadStarted = Signal(str)         # path
    loadFinished = Signal(str)        # path
    loadFailed = Signal(str, str)     # path, error message

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.data: Any = None
        self.file_path: Optional[str] = None
        self._pool = QThreadPool.globalInstance()

    # --- 同步 ---
    def load(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            self.data = json.load(f)
        self.file_path = path
        self.dataChanged.emit(self.data)
        return self.data

    # --- 异步（推荐用于大文件） ---
    def load_async(self, path: str):
        self.loadStarted.emit(path)

        def _ok(p: str, data: Any):
            # 回到主线程上下文（Qt 信号保证）
            self.data = data
            self.file_path = p
            self.dataChanged.emit(self.data)
            self.loadFinished.emit(p)

        def _err(p: str, e: Exception):
            self.loadFailed.emit(p, str(e))

        runnable = _LoadRunnable(path, _ok, _err)
        self._pool.start(runnable)

    def set_data(self, data: Any):
        self.data = data
        self.file_path = None
        self.dataChanged.emit(self.data)

    def save(self, path: Optional[str] = None):
        target = path or self.file_path
        if not target:
            raise ValueError("No save path specified.")
        with open(target, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def get_data(self):
        return self.data
