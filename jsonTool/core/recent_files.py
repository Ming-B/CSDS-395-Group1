# core/recent_files.py
from __future__ import annotations
from pathlib import Path
import json


class RecentFilesManager:
    """Singleton-like manager for recent files."""

    _instance = None
    _max_files = 50

    def __new__(cls, config_path: str = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init(config_path)
        return cls._instance

    def _init(self, config_path: str | None):
        self._config_file = Path(config_path) if config_path else Path("config/user.json")
        self._config_file.parent.mkdir(parents=True, exist_ok=True)

        self._recent_files: list[str] = []
        self._load()

    # ---------------- Public API ----------------
    def get_files(self) -> list[str]:
        return list(self._recent_files)

    def add_file(self, path: str):
        """Add path to top of recent files list."""
        try:
            p = Path(path).resolve()
        except Exception:
            return
        if not p.exists():
            return

        sp = str(p)
        # 去重并置顶
        self._recent_files = [sp] + [x for x in self._recent_files if x != sp]
        self._recent_files = self._recent_files[: self._max_files]
        self._save()

    def remove_file(self, path: str):
        """Remove path from recent list."""
        self._recent_files = [x for x in self._recent_files if x != path]
        self._save()

    def clear(self):
        """Clear all recent files."""
        self._recent_files = []
        self._save()

    # ---------------- Internal ----------------
    def _load(self):
        try:
            if self._config_file.exists():
                data = json.loads(self._config_file.read_text(encoding="utf-8"))
                rf = data.get("recent_files", [])
                if isinstance(rf, list):
                    self._recent_files = [p for p in rf if isinstance(p, str) and Path(p).exists()]
        except Exception:
            self._recent_files = []

    def _save(self):
        data = {"recent_files": self._recent_files}
        try:
            self._config_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
