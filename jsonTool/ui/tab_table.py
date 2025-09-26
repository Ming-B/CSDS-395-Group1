# ui/tab_table.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView, QHeaderView, QPushButton,
    QMessageBox, QApplication, QAbstractItemView, QToolButton, QMenu,
    QLabel, QSpinBox
)
from PySide6.QtCore import (
    Slot, QAbstractTableModel, Qt, QModelIndex
)
from PySide6.QtGui import QFont

from jsonTool.core.document import JSONDocument
from jsonTool.core.recent_files import RecentFilesManager


class JsonTableModel(QAbstractTableModel):
    """Table model for displaying JSON data in tabular format."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[dict] = []
        self._headers: list[str] = []
        self._editable = True
    
    def load_data(self, data: Any):
        """Load JSON data into the table model."""
        self.beginResetModel()
        
        if isinstance(data, list) and all(isinstance(item, dict) for item in data):
            self._data = data.copy()
            # Collect all unique keys from all dictionaries
            all_keys = set()
            for item in self._data:
                all_keys.update(item.keys())
            self._headers = sorted(all_keys)
        elif isinstance(data, dict):
            # Convert single dict to list of key-value pairs
            self._data = [{"Key": k, "Value": v} for k, v in data.items()]
            self._headers = ["Key", "Value"]
        else:
            # Fallback: create a simple representation
            self._data = [{"Data": str(data)}]
            self._headers = ["Data"]
        
        self.endResetModel()
    
    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._data)
    
    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._headers)
    
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return self._headers[section] if section < len(self._headers) else ""
            else:
                return str(section + 1)
        return None
    
    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._data):
            return None
        
        row = index.row()
        col = index.column()
        
        if role == Qt.DisplayRole or role == Qt.EditRole:
            if col < len(self._headers):
                key = self._headers[col]
                value = self._data[row].get(key, "")
                if isinstance(value, (dict, list)):
                    return json.dumps(value, ensure_ascii=False)
                return str(value)
        elif role == Qt.FontRole:
            font = QFont()
            if isinstance(self._data[row].get(self._headers[col], ""), (dict, list)):
                font.setItalic(True)
            return font
        
        return None
    
    def setData(self, index: QModelIndex, value: Any, role: int = Qt.EditRole) -> bool:
        if not self._editable or not index.isValid() or index.row() >= len(self._data):
            return False
        
        if role == Qt.EditRole:
            row = index.row()
            col = index.column()
            
            if col < len(self._headers):
                key = self._headers[col]
                str_value = str(value)
                
                # Try to parse JSON if it looks like JSON
                if str_value.strip().startswith(('[', '{')):
                    try:
                        parsed_value = json.loads(str_value)
                        self._data[row][key] = parsed_value
                    except json.JSONDecodeError:
                        self._data[row][key] = str_value
                else:
                    # Try to convert to appropriate type
                    try:
                        # Try int first
                        if str_value.isdigit() or (str_value.startswith('-') and str_value[1:].isdigit()):
                            self._data[row][key] = int(str_value)
                        # Try float
                        elif '.' in str_value:
                            self._data[row][key] = float(str_value)
                        # Try boolean
                        elif str_value.lower() in ('true', 'false'):
                            self._data[row][key] = str_value.lower() == 'true'
                        # Keep as string
                        else:
                            self._data[row][key] = str_value
                    except ValueError:
                        self._data[row][key] = str_value
                
                self.dataChanged.emit(index, index, [Qt.DisplayRole])
                return True
        
        return False
    
    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if self._editable:
            flags |= Qt.ItemIsEditable
        return flags
    
    def add_row(self):
        """Add a new empty row."""
        self.beginInsertRows(QModelIndex(), len(self._data), len(self._data))
        new_row = {header: "" for header in self._headers}
        self._data.append(new_row)
        self.endInsertRows()
    
    def remove_row(self, row: int) -> bool:
        """Remove a row at the specified index."""
        if 0 <= row < len(self._data):
            self.beginRemoveRows(QModelIndex(), row, row)
            del self._data[row]
            self.endRemoveRows()
            return True
        return False
    
    def add_column(self, header: str):
        """Add a new column with the given header."""
        if header in self._headers:
            return False
        
        self.beginInsertColumns(QModelIndex(), len(self._headers), len(self._headers))
        self._headers.append(header)
        for row in self._data:
            row[header] = ""
        self.endInsertColumns()
        return True
    
    def remove_column(self, col: int) -> bool:
        """Remove a column at the specified index."""
        if 0 <= col < len(self._headers):
            self.beginRemoveColumns(QModelIndex(), col, col)
            header_to_remove = self._headers[col]
            self._headers.pop(col)
            for row in self._data:
                row.pop(header_to_remove, None)
            self.endRemoveColumns()
            return True
        return False
    
    def to_json(self) -> list[dict]:
        """Export current table data as JSON."""
        return self._data.copy()
    
    def set_editable(self, editable: bool):
        """Enable or disable editing."""
        self._editable = editable


class TableTab(QWidget):
    """Table tab for displaying and editing JSON data in tabular format."""
    
    def __init__(self, parent=None, document: JSONDocument | None = None):
        super().__init__(parent)
        
        self.document = document
        self._set_busy_cb = None
        
        # Recent files manager
        self.recent_mgr = RecentFilesManager("config/user.json")
        self._current_file: str | None = None
        
        # Setup UI
        self._setup_ui()
        
        # Connect to document
        if self.document is not None:
            if self.document.get_data() is not None:
                self.model.load_data(self.document.get_data())
                self._update_title_from_document()
                if getattr(self.document, "file_path", None):
                    self.recent_mgr.add_file(self.document.file_path)
            self.document.dataChanged.connect(self.on_document_changed)
        
        # Build dropdown menu
        self._rebuild_table_menu()
    
    def _setup_ui(self):
        """Setup the user interface."""
        root_layout = QVBoxLayout(self)
        
        # Top toolbar
        toolbar = self._create_toolbar()
        root_layout.addLayout(toolbar)
        
        # File selection row
        file_row = self._create_file_row()
        root_layout.addLayout(file_row)
        
        # View options row
        options_row = self._create_options_row()
        root_layout.addLayout(options_row)
        
        # Table view
        self.table_view = QTableView(self)
        root_layout.addWidget(self.table_view)
        
        # Setup model
        self.model = JsonTableModel(self)
        self.table_view.setModel(self.model)
        
        # Table configuration
        self.table_view.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSortingEnabled(True)
        
        # Auto-resize columns
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        
        # Connect signals
        self._connect_signals()
    
    def _create_toolbar(self) -> QHBoxLayout:
        """Create the main toolbar."""
        toolbar = QHBoxLayout()
        
        # Row operations
        self.btn_add_row = QPushButton("+R", self)
        self.btn_add_row.setToolTip("Add Row")
        self.btn_remove_row = QPushButton("-R", self)
        self.btn_remove_row.setToolTip("Remove Selected Row")
        
        # Column operations
        self.btn_add_column = QPushButton("+C", self)
        self.btn_add_column.setToolTip("Add Column")
        self.btn_remove_column = QPushButton("-C", self)
        self.btn_remove_column.setToolTip("Remove Selected Column")
        
        # View operations
        self.btn_fit_columns = QPushButton("Fit", self)
        self.btn_fit_columns.setToolTip("Fit Columns to Content")
        
        # Edit toggle
        self.btn_edit_mode = QPushButton("Edit", self)
        self.btn_edit_mode.setToolTip("Toggle Edit Mode")
        self.btn_edit_mode.setCheckable(True)
        self.btn_edit_mode.setChecked(True)
        
        toolbar.addWidget(self.btn_add_row)
        toolbar.addWidget(self.btn_remove_row)
        toolbar.addWidget(self.btn_add_column)
        toolbar.addWidget(self.btn_remove_column)
        toolbar.addWidget(self.btn_fit_columns)
        toolbar.addWidget(self.btn_edit_mode)
        toolbar.addStretch(1)
        
        return toolbar
    
    def _create_file_row(self) -> QHBoxLayout:
        """Create the file selection row."""
        file_row = QHBoxLayout()
        
        self.title_btn = QPushButton("(No file)", self)
        self.title_btn.setEnabled(False)
        
        self.menu_btn = QToolButton(self)
        self.menu_btn.setText("▼")
        self.menu_btn.setFixedWidth(28)
        self.menu_btn.setToolTip("Choose a file to view in table format")
        self.menu_btn.setPopupMode(QToolButton.InstantPopup)
        
        file_row.addWidget(self.title_btn, 1)
        file_row.addWidget(self.menu_btn, 0)
        
        return file_row
    
    def _create_options_row(self) -> QHBoxLayout:
        """Create the view options row."""
        options_row = QHBoxLayout()
        
        # Row limit
        options_row.addWidget(QLabel("Max Rows:"))
        self.row_limit_spin = QSpinBox(self)
        self.row_limit_spin.setRange(10, 10000)
        self.row_limit_spin.setValue(1000)
        self.row_limit_spin.setToolTip("Limit number of rows displayed")
        options_row.addWidget(self.row_limit_spin)
        
        options_row.addStretch(1)
        
        # Info label
        self.info_label = QLabel("Ready", self)
        options_row.addWidget(self.info_label)
        
        return options_row
    
    def _connect_signals(self):
        """Connect all UI signals."""
        self.btn_add_row.clicked.connect(self._on_add_row)
        self.btn_remove_row.clicked.connect(self._on_remove_row)
        self.btn_add_column.clicked.connect(self._on_add_column)
        self.btn_remove_column.clicked.connect(self._on_remove_column)
        self.btn_fit_columns.clicked.connect(self._on_fit_columns)
        self.btn_edit_mode.toggled.connect(self._on_edit_mode_toggled)
        self.row_limit_spin.valueChanged.connect(self._on_row_limit_changed)
    
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
        """Handle document data changes."""
        self._busy(True, "Loading data into table...")
        try:
            self.model.load_data(data)
            self._update_title_from_document()
            if getattr(self.document, "file_path", None):
                self.recent_mgr.add_file(self.document.file_path)
                self._rebuild_table_menu()
            self._update_info_label()
        finally:
            self._busy(False)
    
    def _update_title_from_document(self):
        """Update the title button from document file path."""
        fp = getattr(self.document, "file_path", None)
        self._current_file = fp if isinstance(fp, str) else None
        self.title_btn.setText(Path(fp).name if fp else "(No file)")
    
    def _update_info_label(self):
        """Update the info label with current data stats."""
        rows = self.model.rowCount()
        cols = self.model.columnCount()
        self.info_label.setText(f"{rows} rows, {cols} columns")
    
    # ---------- Public API for MainWindow ----------
    def current_json(self):
        """Return current table data as JSON."""
        return self.model.to_json()
    
    def capture_view_state(self) -> dict:
        """Capture current view state for snapshots."""
        return {
            "edit_mode": self.btn_edit_mode.isChecked(),
            "row_limit": self.row_limit_spin.value(),
            "column_widths": [
                self.table_view.columnWidth(i) 
                for i in range(self.model.columnCount())
            ],
            "scroll_h": self.table_view.horizontalScrollBar().value(),
            "scroll_v": self.table_view.verticalScrollBar().value(),
        }
    
    def schedule_restore_view_state(self, state: dict | None):
        """Schedule view state restoration after model reset."""
        if not state:
            return
        
        # Restore edit mode
        edit_mode = state.get("edit_mode", True)
        self.btn_edit_mode.setChecked(edit_mode)
        
        # Restore row limit
        row_limit = state.get("row_limit", 1000)
        self.row_limit_spin.setValue(row_limit)
        
        # Restore column widths (after a short delay to let the model settle)
        column_widths = state.get("column_widths", [])
        if column_widths:
            QApplication.processEvents()
            for i, width in enumerate(column_widths):
                if i < self.model.columnCount():
                    self.table_view.setColumnWidth(i, width)
        
        # Restore scroll positions
        h_scroll = state.get("scroll_h", 0)
        v_scroll = state.get("scroll_v", 0)
        self.table_view.horizontalScrollBar().setValue(h_scroll)
        self.table_view.verticalScrollBar().setValue(v_scroll)
    
    def set_data(self, data):
        """Set table data."""
        self.model.load_data(data)
        self._update_info_label()
    
    def clear(self):
        """Clear table data."""
        self.model.load_data([])
        self._update_info_label()
    
    # ---------- File menu ----------
    def _rebuild_table_menu(self):
        """Rebuild the file selection dropdown menu."""
        menu = QMenu(self.menu_btn)
        files = self.recent_mgr.get_files()
        if not files:
            action = menu.addAction("(no recent files)")
            action.setEnabled(False)
        else:
            for abs_path in files:
                name = Path(abs_path).name
                action = menu.addAction(name)
                action.setToolTip(abs_path)
                action.triggered.connect(
                    lambda checked=False, p=abs_path: self._choose_file_for_table(p)
                )
        self.menu_btn.setMenu(menu)
    
    def _choose_file_for_table(self, abs_path: str):
        """Choose a file to display in table format."""
        try:
            self._busy(True, f"Loading {Path(abs_path).name} for table view...")
            self.title_btn.setText(Path(abs_path).name)
            if self.document is not None:
                self.document.load(abs_path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open:\n{abs_path}\n\n{e}")
        finally:
            self._busy(False)
    
    # ---------- Toolbar handlers ----------
    @Slot()
    def _on_add_row(self):
        """Add a new row to the table."""
        self.model.add_row()
        self._update_info_label()
    
    @Slot()
    def _on_remove_row(self):
        """Remove the selected row from the table."""
        current = self.table_view.currentIndex()
        if current.isValid():
            if self.model.remove_row(current.row()):
                self._update_info_label()
        else:
            QMessageBox.information(self, "Info", "Please select a row to remove.")
    
    @Slot()
    def _on_add_column(self):
        """Add a new column to the table."""
        from PySide6.QtWidgets import QInputDialog
        
        text, ok = QInputDialog.getText(
            self, "Add Column", "Enter column header:", text="New Column"
        )
        if ok and text.strip():
            if self.model.add_column(text.strip()):
                self._update_info_label()
            else:
                QMessageBox.warning(self, "Warning", f"Column '{text}' already exists.")
    
    @Slot()
    def _on_remove_column(self):
        """Remove the selected column from the table."""
        current = self.table_view.currentIndex()
        if current.isValid():
            if self.model.remove_column(current.column()):
                self._update_info_label()
        else:
            QMessageBox.information(self, "Info", "Please select a column to remove.")
    
    @Slot()
    def _on_fit_columns(self):
        """Fit all columns to their content."""
        self._busy(True, "Resizing columns...")
        try:
            self.table_view.resizeColumnsToContents()
        finally:
            self._busy(False)
    
    @Slot(bool)
    def _on_edit_mode_toggled(self, checked: bool):
        """Toggle edit mode."""
        self.model.set_editable(checked)
        self.btn_edit_mode.setText("Edit" if checked else "View")
    
    @Slot(int)
    def _on_row_limit_changed(self, value: int):
        """Handle row limit changes."""
        # This would need more sophisticated implementation to actually limit rows
        # For now, just update the info
        self._update_info_label()
