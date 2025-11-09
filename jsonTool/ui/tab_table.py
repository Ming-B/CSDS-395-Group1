from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView, QHeaderView, QPushButton,
    QMessageBox, QApplication, QAbstractItemView, QToolButton, QMenu,
    QLabel, QSpinBox, QInputDialog, QStyledItemDelegate, QLineEdit, QStyle
)
from PySide6.QtCore import Slot, Qt, QModelIndex
from PySide6.QtGui import QPalette

from jsonTool.core.document import JSONDocument
from jsonTool.core.recent_files import RecentFilesManager
from jsonTool.ui.models.json_table_model import JsonTableModel



class SolidEditorDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        ed = super().createEditor(parent, option, index)

        if isinstance(ed, QLineEdit):
            ed.setAutoFillBackground(True)
            pal = ed.palette()
            pal.setColor(QPalette.Base, option.palette.color(QPalette.Base))
            pal.setColor(QPalette.Text, option.palette.color(QPalette.Text))
            ed.setPalette(pal)
        return ed

    def paint(self, painter, option, index):

        if option.state & QStyle.State_Editing:
            painter.save()
            painter.fillRect(option.rect, option.palette.brush(QPalette.Base))
            painter.restore()
            return
        # 其他情况走默认绘制
        super().paint(painter, option, index)



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

        self._delegate = SolidEditorDelegate(self.table_view)
        self.table_view.setItemDelegate(self._delegate)

        # Table configuration
        self.table_view.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
        )
        
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSortingEnabled(True)
        
        # Auto-resize columns
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
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
        self.menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        
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