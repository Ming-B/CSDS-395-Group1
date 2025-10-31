# ui/tab_doc.py
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextBrowser, QMenu
)
from PySide6.QtCore import Qt
import markdown


class DocTab(QWidget):
    """Documentation tab that renders Markdown files in /data based on language selection."""

    def __init__(self, parent=None, config_ref: dict | None = None, save_config_cb=None):
        super().__init__(parent)

        self._data_dir = Path(__file__).resolve().parents[1] / "data"

        # 语言与文件映射
        self._lang_files = {
            "English": self._data_dir / "doc_en.md",
            "中文": self._data_dir / "doc_zh.md",
        }

        # Config 引用（来自 MainWindow）
        self._config = config_ref if config_ref is not None else {}
        self._save_config_cb = save_config_cb

        # 从 config 获取默认语言
        self._current_lang = self._config.get("default_lang", "English")
        if self._current_lang not in self._lang_files:
            self._current_lang = "English"

        # -------- 顶部行：按钮 + 标题 --------
        top_layout = QHBoxLayout()
        self.lang_button = QPushButton("En/文", self)
        self.lang_button.setFixedWidth(70)

        self.title_label = QLabel("CWRU | CSDS 395 | Fall 2025", self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        top_layout.addWidget(self.lang_button, alignment=Qt.AlignmentFlag.AlignLeft)
        top_layout.addWidget(self.title_label, alignment=Qt.AlignmentFlag.AlignLeft)
        top_layout.addStretch(1)

        # -------- 下方：Markdown 渲染 --------
        self.viewer = QTextBrowser(self)
        self.viewer.setOpenExternalLinks(True)
        self.viewer.setReadOnly(True)

        # -------- 主布局 --------
        layout = QVBoxLayout(self)
        layout.addLayout(top_layout)
        layout.addWidget(self.viewer)

        # -------- 下拉菜单 --------
        self._menu = QMenu(self)
        for lang in self._lang_files.keys():
            action = self._menu.addAction(lang)
            action.triggered.connect(lambda checked=False, l=lang: self.set_language(l))
        self.lang_button.setMenu(self._menu)

        # 默认语言加载
        self.set_language(self._current_lang)

    def set_language(self, lang: str):
        """切换语言并刷新显示，并写入 config"""
        if lang not in self._lang_files:
            return
        self._current_lang = lang
        file_path = self._lang_files[lang]

        if file_path.exists():
            text = file_path.read_text(encoding="utf-8")
            html = markdown.markdown(text, extensions=["tables", "fenced_code"])
            self.viewer.setHtml(html)
        else:
            self.viewer.setHtml(f"<p><b>File not found:</b> {file_path}</p>")

        # 保存默认语言到 config
        if isinstance(self._config, dict):
            self._config["default_lang"] = lang
            if callable(self._save_config_cb):
                self._save_config_cb()
