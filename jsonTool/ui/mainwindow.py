# ui/mainwindow.py
from pathlib import Path
from datetime import datetime
import json

from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QFileDialog, QMessageBox, QLabel, QApplication,
    QWidget, QHBoxLayout, QPushButton, QSizePolicy
)
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QProxyStyle, QStyle

from jsonTool.ui.tab_viewer import ViewerTab
from jsonTool.ui.tab_editor import EditorTab
from jsonTool.core.document import JSONDocument
from jsonTool.ui.tab_doc import DocTab
from jsonTool.ui.tab_unzipper import UnzipperTab
from jsonTool.ui.tab_splitter import SplitterTab
from jsonTool.ui.tab_table import TableTab


class FastToolTipStyle(QProxyStyle):
    """Style proxy for globally accelerated ToolTip:
       - SH_ToolTip_WakeUpDelay: ToolTip Delay before emergence (milliseconds)
       - SH_ToolTip_FallAsleepDelay: ToolTip Duration (milliseconds)
    """
    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.SH_ToolTip_WakeUpDelay:
            return 100   # ← Appears on hover for 0.1 seconds (can be turned down again, e.g. 50)
        if hint == QStyle.SH_ToolTip_FallAsleepDelay:
            return 20000 # ← Hold for up to 20 seconds to avoid disappearing too quickly (adjustable as needed)
        return super().styleHint(hint, option, widget, returnData)


class MainWindow(QMainWindow):
    """Main window with a menu bar, a tab widget, snapshot/undo/redo, config, and a bottom busy banner."""

    def __init__(self, parent=None):
        super().__init__(parent)
        
        app = QApplication.instance()
        if app is not None:
            app.setStyle(FastToolTipStyle(app.style()))

        self.setWindowTitle("JSON Tool")
        self.resize(1000, 650)

        # ------------ Config (persist last_open_dir) ------------
        root_dir = Path(__file__).resolve().parents[1]
        self._config_dir = root_dir / "config"
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._config_file = self._config_dir / "user.json"
        self._config = self._load_user_config()

        # ------------ Global document ------------
        self.document = JSONDocument()

        # ------------ History & workspace ------------
        self._workspace = root_dir / "workspace"
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._clear_workspace()  # clear on app start

        self._history_files: list[Path] = []
        self._history_index: int = -1
        self._snapshot_prefix: str = "document"  # updated from opened file name

        # ------------ Central tabs ------------
        self.tabs = QTabWidget(self)
        self.setCentralWidget(self.tabs)

        # Tab: Viewer (read-only) & Editor (editable)
        self.viewer_tab = ViewerTab(self, document=self.document)
        self.editor_tab = EditorTab(self, document=self.document)
        self.splitter_tab = SplitterTab(self)
        self.unzipper_tab = UnzipperTab(self)
        self.doc_tab = DocTab(self, config_ref=self._config, save_config_cb=self._save_user_config)
        self.table_tab = TableTab(self, document=self.document)
        self.tabs.addTab(self.viewer_tab, "Viewer")
        self.tabs.addTab(self.editor_tab, "Editor")
        self.tabs.addTab(self.splitter_tab, "Splitter")
        self.tabs.addTab(self.unzipper_tab, "Unzipper")
        self.tabs.addTab(self.doc_tab, "Docs")
        self.tabs.addTab(self.table_tab, "Table")



        # ------------ Menu and left-corner buttons ------------
        self._build_menu_and_top_buttons()

        # ------------ Bottom busy banner ------------
        self._busy_label = QLabel("", self)
        self._busy_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.statusBar().addPermanentWidget(self._busy_label, 1)
        self._idle_banner()
        # make status bar taller and text wrap
        self._busy_label.setWordWrap(True)
        self._busy_label.setMinimumHeight(32)
        self._busy_label.setContentsMargins(6, 4, 6, 4)
        self._busy_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.statusBar().setStyleSheet("QStatusBar { min-height: 32px; }")

        self.statusBar().showMessage("Ready")

        # Inject busy API to tabs
        self.viewer_tab.set_busy_callback(self.set_busy)
        self.editor_tab.set_busy_callback(self.set_busy)
        self.table_tab.set_busy_callback(self.set_busy)

    # ---------------- Config helpers ----------------
    def _load_user_config(self) -> dict:
        try:
            if self._config_file.exists():
                return json.loads(self._config_file.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_user_config(self):
        try:
            self._config_file.write_text(json.dumps(self._config, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass  # non-critical

    # ---------------- Menu + Left Buttons ----------------
    def _build_menu_and_top_buttons(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

        # Open (start from last_open_dir if available). No shortcut (only keep Ctrl+S / Ctrl+Z overall).
        open_action = QAction("Open...", self)
        open_action.triggered.connect(self._action_open_file)
        file_menu.addAction(open_action)

        # Open from Last Folder… (explicit start dir). No shortcut.
        open_last_action = QAction("Open from Last Folder...", self)
        open_last_action.triggered.connect(self._action_open_from_last_folder)
        file_menu.addAction(open_last_action)

        # Close. No shortcut.
        close_action = QAction("Close", self)
        close_action.triggered.connect(self._action_close_file)
        file_menu.addAction(close_action)

        file_menu.addSeparator()

        # Save (overwrite original file). No shortcut (to avoid accidental overwrite).
        save_file_action = QAction("Save", self)
        save_file_action.triggered.connect(self._action_save_file_overwrite)
        file_menu.addAction(save_file_action)

        # Save As… (pick a new path). No shortcut.
        save_as_action = QAction("Save As...", self)
        save_as_action.triggered.connect(self._action_save_file_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        # Save Progress (snapshot to workspace). KEEP Ctrl+S
        save_prog_action = QAction("Save Progress", self)
        save_prog_action.setShortcut(QKeySequence.StandardKey.Save)  # Ctrl+S
        save_prog_action.triggered.connect(self._action_save_progress)
        file_menu.addAction(save_prog_action)

        # Undo. KEEP Ctrl+Z
        undo_action = QAction("Undo", self)
        undo_action.setShortcut(QKeySequence.StandardKey.Undo)  # Ctrl+Z
        undo_action.triggered.connect(self._action_undo)
        file_menu.addAction(undo_action)

        # Redo. No shortcut.
        redo_action = QAction("Redo", self)
        redo_action.triggered.connect(self._action_redo)
        file_menu.addAction(redo_action)

        # ---- Left-corner buttons (Save Progress / Undo / Redo) ----
        corner = QWidget(self)
        hl = QHBoxLayout(corner)
        hl.setContentsMargins(6, 0, 0, 0)
        hl.setSpacing(8)

        self.btn_save = QPushButton("Save Progress", corner)
        self.btn_undo = QPushButton("Undo", corner)
        self.btn_redo = QPushButton("Redo", corner)

        # Qt QSS doesn't support filter/opacity -> use hover/disabled colors instead
        style = (
            "QPushButton { padding: 2px 10px; border-radius: 6px; font-weight: 600; }"
            "QPushButton#save { background:#eeeeee; color:#333; }"
            "QPushButton#save:hover { background:#1e88e5; color:white; }"
            "QPushButton#undo { background:#eeeeee; color:#333; }"
            "QPushButton#undo:hover, QPushButton#redo:hover { background:#1e88e5; color:white; }"
            "QPushButton#redo { background:#eeeeee; color:#333; }"
            "QPushButton:disabled { background:#aaaaaa; color:#333333; }"
        )
        self.btn_save.setObjectName("save")
        self.btn_undo.setObjectName("undo")
        self.btn_redo.setObjectName("redo")
        corner.setStyleSheet(style)

        self.btn_save.clicked.connect(self._action_save_progress)
        self.btn_undo.clicked.connect(self._action_undo)
        self.btn_redo.clicked.connect(self._action_redo)

        hl.addWidget(self.btn_save)
        hl.addWidget(self.btn_undo)
        hl.addWidget(self.btn_redo)

        menubar.setCornerWidget(corner, Qt.TopLeftCorner)

        # Initial state
        self._refresh_history_buttons()

    # ---------------- Busy Banner API ----------------
    # ---------------- Busy Banner API ----------------
    def set_busy(self, is_busy: bool, msg: str = "Working... please do not repeat operations"):
        if is_busy:
            self._busy_banner(msg)
            QApplication.processEvents()
        else:
            self._idle_banner()

    def _busy_banner(self, msg: str):
        self._busy_label.setText(msg)
        self._busy_label.setStyleSheet(
            "QLabel { background-color: #d32f2f; color: white; "
            "padding: 4px 10px; border-radius: 4px; font-weight: 600; }"
        )

    def _idle_banner(self):
        self._busy_label.setText("")
        # 清空样式，恢复默认
        self._busy_label.setStyleSheet(
            "QLabel { background: transparent; color: black; padding: 0px; }"
        )


    # ---------------- File Actions ----------------
    def _action_open_file(self):
        start_dir = self._config.get("last_open_dir", "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Open JSON", start_dir, "JSON Files (*.json);;All Files (*)"
        )
        if path:
            self._open_file_common(Path(path))

    def _action_open_from_last_folder(self):
        start_dir = self._config.get("last_open_dir", "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Open JSON (Last Folder)", start_dir, "JSON Files (*.json);;All Files (*)"
        )
        if path:
            self._open_file_common(Path(path))

    def _open_file_common(self, p: Path):
        try:
            self.set_busy(True, "Loading file...")
            self.document.load(str(p))  # triggers dataChanged; both tabs react
            self.statusBar().showMessage(f"Loaded: {p}", 5000)
            self.setWindowTitle(f"JSON Tool — {p}")

            # Remember last folder to config
            self._config["last_open_dir"] = str(p.parent)
            self._save_user_config()

            # Reset snapshot prefix and history
            self._snapshot_prefix = p.stem
            self._history_files.clear()
            self._history_index = -1

            # Clear workspace and immediately save an initial snapshot (with per-tab meta)
            self._clear_workspace()
            self._save_snapshot(
                self.document.get_data(),
                update_document=False,
                banner_msg="Saving initial snapshot..."
            )
            
            # Ask if user wants to store to database
            self._ask_store_to_database(p)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open file:\n{e}")
        finally:
            self.set_busy(False)

    def _action_close_file(self):
        """Clear document + workspace."""
        self.document.set_data({})
        self._clear_workspace()
        self._history_files.clear()
        self._history_index = -1
        self.setWindowTitle("JSON Tool")
        self.statusBar().showMessage("Closed")
        self._refresh_history_buttons()

    # ----- Save (overwrite original file) & Save As -----
    def _action_save_file_overwrite(self):
        """Write current data to the original file path (overwrite)."""
        data = self._collect_current_json()
        if data is None:
            QMessageBox.information(self, "Info", "No data to save.")
            return
        try:
            # If there's no original path, fall back to Save As...
            file_path = getattr(self.document, "file_path", None)
            if not file_path:
                self._action_save_file_as()
                return
            self.set_busy(True, "Saving file...")
            # Keep document data in sync and overwrite via document.save()
            self.document.set_data(data)
            self.document.save()  # relies on existing self.document.file_path
            self.statusBar().showMessage(f"Saved: {self.document.file_path}", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save file:\n{e}")
        finally:
            self.set_busy(False)

    def _action_save_file_as(self):
        """Prompt for a new path, write data, update document path and config."""
        data = self._collect_current_json()
        if data is None:
            QMessageBox.information(self, "Info", "No data to save.")
            return

        # Default dir: last_open_dir or current document dir
        start_dir = self._config.get("last_open_dir", "")
        cur_path = getattr(self.document, "file_path", None)
        if cur_path:
            try:
                start_dir = str(Path(cur_path).parent)
            except Exception:
                pass

        new_path, _ = QFileDialog.getSaveFileName(
            self, "Save JSON As", start_dir, "JSON Files (*.json);;All Files (*)"
        )
        if not new_path:
            return

        p = Path(new_path)
        if p.suffix.lower() != ".json":
            p = p.with_suffix(".json")

        try:
            self.set_busy(True, "Saving file as...")
            with p.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Update document metadata and UI
            self.document.set_data(data)
            self.document.file_path = str(p)
            self.setWindowTitle(f"JSON Tool — {p}")
            self._snapshot_prefix = p.stem

            # Remember new folder
            self._config["last_open_dir"] = str(p.parent)
            self._save_user_config()

            self.statusBar().showMessage(f"Saved As: {p}", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save file:\n{e}")
        finally:
            self.set_busy(False)

    # ---------------- Snapshot workspace ----------------
    def _clear_workspace(self):
        """Remove all files in workspace directory."""
        if not self._workspace.exists():
            self._workspace.mkdir(parents=True, exist_ok=True)
            return
        for p in self._workspace.glob("*"):
            try:
                if p.is_file():
                    p.unlink()
            except Exception:
                pass

    def _snapshot_path(self) -> Path:
        now = datetime.now()
        stamp = now.strftime("%Y_%m_%d_%H%M_%S")
        fname = f"{self._snapshot_prefix}_snapshot_{stamp}.json"
        return self._workspace / fname

    def _collect_current_json(self):
        """
        Prefer Editor's current (possibly unsaved) JSON;
        fall back to document data otherwise.
        """
        try:
            data = self.editor_tab.current_json()
            if data is not None:
                return data
        except Exception:
            pass
        return self.document.get_data()

    def _list_data_snapshots(self) -> list[Path]:
        """Return only real data snapshots, excluding any *.meta.json."""
        all_json = self._workspace.glob(f"{self._snapshot_prefix}_snapshot_*.json")
        return sorted(p for p in all_json if not p.name.endswith(".meta.json"))

    def _rebuild_history_list(self):
        # Only collect data snapshots (exclude ...meta.json)
        self._history_files = self._list_data_snapshots()

    def _save_snapshot(self, data, *, update_document: bool, banner_msg: str):
        """
        Write snapshot JSON + per-tab meta, refresh history pointer and buttons.
        NOTE: we call `capture_view_state()` on both tabs so that a future undo/redo
        can restore expand/collapse/selection/scroll positions correctly.
        """
        if data is None:
            QMessageBox.information(self, "Info", "No data to save.")
            return

        try:
            self.set_busy(True, banner_msg)
            path = self._snapshot_path()

            # 1) Write data
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # 2) Sync document (to let Viewer see the change immediately if requested)
            if update_document:
                self.document.set_data(data)

            # 3) Capture and write meta for both tabs (REQUIRED for view restore)
            meta = {
                "version": 1,
                "tabs": {
                    "Editor": self.editor_tab.capture_view_state(),
                    "Viewer": self.viewer_tab.capture_view_state(),
                }
            }
            with path.with_suffix(".meta.json").open("w", encoding="utf-8") as mf:
                json.dump(meta, mf, indent=2, ensure_ascii=False)

            # 4) Refresh history & index
            self._rebuild_history_list()
            self._history_index = len(self._history_files) - 1
            self._refresh_history_buttons()

            self.statusBar().showMessage(f"Saved snapshot: {path.name}", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save snapshot:\n{e}")
        finally:
            self.set_busy(False)

    def _action_save_progress(self):
        data = self._collect_current_json()
        self._save_snapshot(data, update_document=True, banner_msg="Saving snapshot...")
        
    def _ask_store_to_database(self, file_path: Path):
        """Ask user if they want to store the JSON file to storage"""
        try:
            from jsonTool.core.database import get_database_manager
            
            reply = QMessageBox.question(
                self, 
                "Store to Storage", 
                f"Do you want to store '{file_path.name}' to storage?\n\n(File will be saved to stored_files/ directory)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            if reply == QMessageBox.Yes:
                self.set_busy(True, "Storing file...")
                
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

                # ✅ Refresh both tabs (force Viewer and Editor to reload)
                self.document.set_data(self.document.get_data())
                self.viewer_tab._refresh_stored_sidebar()
                self.editor_tab._rebuild_editor_menu()
                QApplication.processEvents()

                
                self.statusBar().showMessage(f"Stored to storage: index {file_index}", 5000)
                
        except Exception as e:
            QMessageBox.critical(self, "Storage Error", f"Failed to store file:\n{e}")
        finally:
            self.set_busy(False)

    def _load_history_at(self, idx: int):
        """
        Load snapshot by index and update UI/state pointer, restoring per-tab view states.
        IMPORTANT: we schedule the restore BEFORE setting document data,
        so that each tab applies the stored state right after handling dataChanged().
        """
        if idx < 0 or idx >= len(self._history_files):
            return
        path = self._history_files[idx]

        try:
            # Read meta (if present)
            meta_path = path.with_suffix(".meta.json")
            editor_state = None
            viewer_state = None
            if meta_path.exists():
                try:
                    with meta_path.open("r", encoding="utf-8") as mf:
                        meta = json.load(mf)
                    tabs = meta.get("tabs", {})
                    editor_state = tabs.get("Editor")
                    viewer_state = tabs.get("Viewer")
                except Exception:
                    editor_state = None
                    viewer_state = None

            # Schedule restore on both tabs BEFORE loading data
            self.editor_tab.schedule_restore_view_state(editor_state)
            self.viewer_tab.schedule_restore_view_state(viewer_state)

            self.set_busy(True, f"Loading snapshot ({idx+1}/{len(self._history_files)})...")

            # Load data
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self.document.set_data(data)

            # Update history pointer & buttons
            self._history_index = idx
            self._refresh_history_buttons()
            self.statusBar().showMessage(f"Loaded snapshot: {path.name}", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load snapshot:\n{e}")
        finally:
            self.set_busy(False)

    def _action_undo(self):
        if self._history_index == -1:
            self._rebuild_history_list()
            if not self._history_files:
                return
            self._history_index = len(self._history_files) - 1

        new_idx = self._history_index - 1
        if new_idx >= 0:
            self._load_history_at(new_idx)

    def _action_redo(self):
        if self._history_index == -1:
            self._rebuild_history_list()
            if not self._history_files:
                return
            self._history_index = 0

        new_idx = self._history_index + 1
        if new_idx < len(self._history_files):
            self._load_history_at(new_idx)

    def _refresh_history_buttons(self):
        self._rebuild_history_list()
        n = len(self._history_files)
        i = self._history_index
        self.btn_save.setEnabled(True)
        self.btn_undo.setEnabled(n > 0 and (i == -1 or i > 0))
        self.btn_redo.setEnabled(n > 0 and (i != -1 and (i + 1) < n))

    # ---------------- Window lifecycle ----------------
    def closeEvent(self, event):
        # Clear workspace on app exit
        try:
            self._clear_workspace()
        finally:
            super().closeEvent(event)
