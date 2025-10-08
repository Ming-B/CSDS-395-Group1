from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
from PySide6.QtGui import QFont


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